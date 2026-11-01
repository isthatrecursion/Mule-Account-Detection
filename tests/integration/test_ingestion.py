"""Synthetic service-path tests against real PostgreSQL, including runtime grants."""

import hashlib
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from mule_detection.application.context import ExecutionContext
from mule_detection.application.ingest_service import IngestService
from mule_detection.application.intake_recovery import IntakeRecovery
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.domain.contracts.common import parse_contract
from mule_detection.domain.feature_policy import FeaturePolicy
from mule_detection.ingestion.intake import SourceProfile
from mule_detection.persistence.errors import PersistenceConflict
from mule_detection.persistence.models import (
    AuditEvent,
    Batch,
    IntakeRequest,
    RawPublication,
    ScoreRun,
    ValidationReport,
)
from mule_detection.persistence.raw_store import RawStore
from mule_detection.persistence.repositories import Repositories
from mule_detection.persistence.sqlalchemy import session_factory
from tests.contracts.helpers import payload, synthetic_research

pytestmark = pytest.mark.postgres
CONTEXT = ExecutionContext.create("synthetic-intake-operator", "test")
CONTENT = b"record_key,amount,category\nr1,1,Savings\nr2,,UNKNOWN\n"


@pytest.fixture
def intake(db, runtime_engine, tmp_path):
    policy = parse_contract(FeaturePolicy, payload("feature_policy_v1"))
    profile = SourceProfile(
        source_id="synthetic-csv",
        schema_id="synthetic_snapshot_v1",
        data_tier="synthetic",
        policy_version=policy.policy_version,
        access_scope="synthetic-team",
        identity_columns=("record_key",),
        columns=(
            {
                "name": "record_key",
                "logical_type": "categorical",
                "role": "lineage",
                "required": True,
                "missing": "forbidden",
            },
            {
                "name": "amount",
                "logical_type": "number",
                "role": "predictor",
                "required": True,
                "missing": "imputable",
            },
            {
                "name": "category",
                "logical_type": "categorical",
                "role": "predictor",
                "required": True,
                "missing": "imputable",
            },
        ),
        approved_categories={"category": ("Savings", "Current")},
    )
    return IngestService(
        session_factory(runtime_engine),
        RawStore(tmp_path / "raw", b"x" * 32, max_bytes=65536),
        {profile.source_id: profile},
        policy,
        authorize=lambda *_: True,
        max_rows=20,
    )


def declaration(service, content=CONTENT, **changes):
    profile = next(iter(service.profiles.values()))
    manifest = dict(
        contract_version="batch_manifest_v1",
        batch_id=str(uuid4()),
        source_id=profile.source_id,
        schema_id=profile.schema_id,
        created_at="2026-10-20T00:00:00Z",
        observation_cutoff=None,
        expected_row_count=len(content.splitlines()) - 1,
        checksum=hashlib.sha256(content).hexdigest(),
        feature_policy_version=profile.policy_version,
        data_tier=profile.data_tier,
        owner_reference="synthetic-owner",
        producing_job="synthetic-job",
        provenance_limitations=[],
    )
    manifest.update(changes)
    return {
        "manifest": manifest,
        "byte_count": len(content),
        "logical_schema_signature": profile.signature,
    }


def submit(service, content=CONTENT, declared=None, **options):
    return service.ingest(
        io.BytesIO(content),
        declared or declaration(service, content),
        CONTEXT,
        idempotency_key=options.pop("idempotency_key", uuid4()),
        **options,
    )


def test_accepted_published_quality_and_safe_dto(intake, db):
    result = submit(intake, filename="../../private\\actual.csv")
    assert result.outcome == "ACCEPTED" and not result.qualified_promotion_allowed
    assert "QUALIFIED_SOURCE_NOT_CERTIFIED" in result.finding_codes
    report = json.loads(intake.store.read(result.report_reference.split(":")[-1]))
    fields = report["quality"]["fields"]
    assert fields["amount"]["missing"] == 1
    assert fields["category"]["unknown_category_count"] == 1
    assert "UNKNOWN" not in json.dumps(report["quality"])
    assert "restricted_training_diagnostics" not in report["quality"]
    assert str(intake.store.root) not in result.model_dump_json()
    with unit_of_work(db) as session:
        receipt = session.get(IntakeRequest, result.intake_id)
        assert receipt.original_filename == "actual.csv"
        assert receipt.observed["checksum"] == hashlib.sha256(CONTENT).hexdigest()
        assert Repositories(session).get_accepted_batch(result.batch_id)
        assert (
            session.scalar(
                select(func.count())
                .select_from(RawPublication)
                .where(RawPublication.state == "PUBLISHED")
            )
            == 2
        )
        assert {e.action for e in session.scalars(select(AuditEvent))} == {
            "intake:receive",
            "intake:finalize",
        }
    assert CONTENT not in intake.store.object_path(hashlib.sha256(CONTENT).hexdigest()).read_bytes()


@pytest.mark.parametrize(
    "case,code",
    [
        ("checksum", "MANIFEST_MISMATCH"),
        ("count", "MANIFEST_MISMATCH"),
        ("bytes", "MANIFEST_MISMATCH"),
        ("schema", "SCHEMA_VERSION_MISMATCH"),
        ("duplicate", "DUPLICATE_OR_MISSING_IDENTITY"),
        ("type", "CELL_TYPE_OR_MISSING"),
        ("header", "SCHEMA_HEADER"),
        ("corrupt", "CSV_INVALID"),
        ("compressed", "COMPRESSED_INPUT"),
        ("oversize", "BYTE_LIMIT"),
        ("rows", "ROW_LIMIT"),
        ("metadata", "COUNT_INVALID"),
        ("format", "UNSUPPORTED_FORMAT"),
        ("source", "SOURCE_NOT_REGISTERED"),
    ],
)
def test_rejections_leave_receipt_report_audit_and_no_scores(intake, db, case, code):
    content = CONTENT
    options = {}
    if case == "duplicate":
        content = CONTENT.replace(b"r2,", b"r1,")
    if case == "type":
        content = CONTENT.replace(b"r1,1,", b"r1,not-a-number,")
    if case == "header":
        content = CONTENT.replace(b"amount", b"unknown")
    if case == "corrupt":
        content = b"\xffprivate\x00data"
    if case == "compressed":
        content = b"\x1f\x8b" + b"compressed"
    if case == "oversize":
        content = b"x" * 65537
    if case == "rows":
        content = b"record_key,amount,category\n" + b"".join(
            f"r{i},1,Savings\n".encode() for i in range(21)
        )
    declared = declaration(intake, content)
    if case == "checksum":
        declared["manifest"]["checksum"] = "0" * 64
    if case == "count":
        declared["manifest"]["expected_row_count"] += 1
    if case == "bytes":
        declared["byte_count"] += 1
    if case == "schema":
        declared["logical_schema_signature"] = "0" * 64
    if case == "metadata":
        declared["manifest"]["expected_row_count"] = -1
    if case == "source":
        declared["manifest"]["source_id"] = "not-registered"
    if case == "format":
        options["file_format"] = "parquet"
    result = submit(intake, content, declared, **options)
    assert result.outcome == "QUARANTINED"
    assert code in result.finding_codes
    assert result.report_reference
    with unit_of_work(db) as session:
        assert session.get(IntakeRequest, result.intake_id).state == "QUARANTINED"
        assert session.scalar(select(func.count()).select_from(ScoreRun)) == 0
        with pytest.raises(PersistenceConflict):
            Repositories(session).get_accepted_batch(result.batch_id or uuid4())
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 2


def test_exact_replay_conflict_and_audited_intentional_replay(intake, db):
    declared = declaration(intake)
    key = uuid4()
    first = submit(intake, declared=declared, idempotency_key=key)
    assert submit(intake, declared=declared, idempotency_key=key) == first
    assert submit(intake, declared=declaration(intake)) == first
    with pytest.raises(PersistenceConflict):
        submit(intake, CONTENT.replace(b"r1,1", b"r1,2"), declared, idempotency_key=key)
    conflict = submit(intake, declared=declaration(intake, owner_reference="different-owner"))
    assert "INTAKE_METADATA_CONFLICT" in conflict.finding_codes
    for changes in ({"producing_job": "another-producer"}, {"created_at": "2026-10-19T00:00:00Z"}):
        conflict = submit(intake, declared=declaration(intake, **changes))
        assert "INTAKE_METADATA_CONFLICT" in conflict.finding_codes
    replay = submit(intake, replay_of=first.intake_id)
    assert replay.batch_id != first.batch_id and replay.outcome == "ACCEPTED"
    with unit_of_work(db) as session:
        assert session.scalar(select(func.count()).select_from(Batch)) == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "intake:replay")
            )
            == 1
        )


def test_parallel_exact_content_creates_one_batch(intake, db):
    declared = declaration(intake)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(intake, declared=declared), range(2)))
    with unit_of_work(db) as session:
        assert session.scalar(select(func.count()).select_from(Batch)) == 1
    assert any(r.outcome == "ACCEPTED" for r in results)


def test_same_content_conflicting_source_scope_requires_review(intake):
    first = submit(intake)
    profile = next(iter(intake.profiles.values()))
    other = profile.model_copy(
        update={"source_id": "another-source", "access_scope": "another-team"}
    )
    intake.profiles[other.source_id] = other
    declared = declaration(intake, source_id=other.source_id)
    result = submit(intake, declared=declared)
    assert result.outcome == "QUARANTINED" and result.batch_id is None
    assert "INTAKE_METADATA_CONFLICT" in result.finding_codes
    assert result != first


def test_partial_stream_failure_is_durable_and_cannot_score(intake, db):
    class Broken(io.BytesIO):
        def read(self, n=-1):
            if self.tell():
                raise OSError("PRIVATE_SOURCE_ERROR")
            return super().read(12)

    with pytest.raises(OSError):
        intake.ingest(Broken(CONTENT), declaration(intake), CONTEXT, idempotency_key=uuid4())
    with unit_of_work(db) as session:
        receipt = session.scalars(select(IntakeRequest)).one()
        assert receipt.state == "FAILED"
        assert session.scalar(select(func.count()).select_from(Batch)) == 0


def test_crash_after_file_publication_is_recoverable_without_acceptance(intake, db, monkeypatch):
    original = intake.store.finalize

    def crash(staged):
        original(staged)
        raise OSError("synthetic-crash-after-file-publication")

    monkeypatch.setattr(intake.store, "finalize", crash)
    with pytest.raises(OSError):
        submit(intake)
    monkeypatch.setattr(intake.store, "finalize", original)
    with unit_of_work(db) as session:
        session.execute(
            text("UPDATE raw_publications SET created_at = clock_timestamp() - interval '2 hours'")
        )
    result = IntakeRecovery(intake.factory, intake.store).run(
        CONTEXT, apply=True, retention_seconds=3600
    )
    assert result["published"] == 1
    with unit_of_work(db) as session:
        assert session.scalar(select(func.count()).select_from(Batch)) == 0


def test_revalidation_preserves_old_report_and_blocks_future_use(intake, db):
    result = submit(intake)
    with unit_of_work(db) as session:
        previous = session.get(Batch, result.batch_id).accepted_validation_id
    profile = intake.profiles["synthetic-csv"]
    intake.profiles[profile.source_id] = profile.model_copy(
        update={"policy_version": "new-version"}
    )
    version = intake.revalidate(result.batch_id, CONTEXT)
    assert version != previous
    with unit_of_work(db) as session:
        assert session.get(ValidationReport, previous).outcome == "ACCEPTED"
        assert session.get(ValidationReport, version).outcome == "REJECTED"
        with pytest.raises(PersistenceConflict):
            Repositories(session).get_accepted_batch(result.batch_id)


def test_research_guard_and_quality_use_development_only(intake, tmp_path):
    adapter, dataset, split = synthetic_research(tmp_path)
    profile = SourceProfile(
        source_id="synthetic-research",
        schema_id="research_v1",
        data_tier="research",
        policy_version=adapter.feature_policy.policy_version,
        access_scope="research",
        identity_columns=("Unnamed: 0",),
        columns=adapter.schema.columns,
        missing_tokens=adapter.schema.missing_tokens,
        expected_dataset_hash=adapter.trusted_dataset_sha256,
    )
    intake.profiles = {profile.source_id: profile}
    intake.policy = adapter.feature_policy
    intake.research_adapter = adapter
    intake.trusted_split = split
    content = dataset.read_bytes()
    declared = declaration(
        intake, content, provenance_limitations=["synthetic historical provenance limitation"]
    )
    result = submit(intake, content, declared)
    assert result.outcome == "ACCEPTED"
    report = json.loads(intake.store.read(result.report_reference.split(":")[-1]))
    assert report["quality"]["authorized_rows"] == 3
    assert "HOLDOUT_ONLY" not in json.dumps(report)
    assert "CONFOUNDED_RESEARCH_COHORTS" in result.finding_codes
    from mule_detection.domain.identity import research_record_key
    from mule_detection.domain.validation_policy import IntakeRejected, assert_qualified_promotion

    with pytest.raises(IntakeRejected):
        intake.research_scoring_input(
            result.batch_id, (research_record_key(adapter.trusted_dataset_sha256, 3),), CONTEXT
        )
    predictors = intake.research_scoring_input(
        result.batch_id, (research_record_key(adapter.trusted_dataset_sha256, 1),), CONTEXT
    )
    assert all(
        not {"F3924", "F2230", "Unnamed: 0"}.intersection(row) for row in predictors.values()
    )
    with pytest.raises(IntakeRejected):
        assert_qualified_promotion(report)
    diagnostics_uri = intake.training_quality(result.batch_id, CONTEXT)
    diagnostics = json.loads(intake.store.read(diagnostics_uri.split(":")[-1]))
    assert diagnostics["quality"]["authorized_rows"] == 3
    assert "restricted_training_diagnostics" in diagnostics["quality"]
    intake.authorize = lambda context, scope, action: action != "training-diagnostics"
    from mule_detection.persistence.errors import AccessDenied

    with pytest.raises(AccessDenied):
        intake.training_quality(result.batch_id, CONTEXT)


def test_recovery_deletes_only_aged_unreferenced_staging(intake):
    staged = intake.store.stage(io.BytesIO(b"orphan"))
    path = intake.store.staging_path(staged.stage_id)
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(path, (old, old))
    recovery = IntakeRecovery(intake.factory, intake.store)
    assert recovery.run(CONTEXT, retention_seconds=3600)["orphans"] == 1
    assert path.exists()
    assert (
        recovery.run(CONTEXT, apply=True, delete_orphans=True, retention_seconds=3600)["removed"]
        == 1
    )
    assert not path.exists()


@pytest.mark.parametrize("invalid", [False, True, "malformed_json"])
def test_cli_same_service_safe_output_and_exit_status(
    intake, app_root, capsys, monkeypatch, invalid
):
    from mule_detection.cli import main

    declared = declaration(intake)
    if invalid:
        declared["manifest"]["expected_row_count"] += 1
    manifest = app_root / "manifest.json"
    manifest.write_text(json.dumps(declared))
    if invalid == "malformed_json":
        manifest.write_text('{"manifest":')
    monkeypatch.setattr(
        "mule_detection.application.ingest_bootstrap.build_ingest", lambda _: intake
    )
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(CONTENT)))
    exit_code = main(
        [
            "--root",
            str(app_root),
            "validate-batch",
            "--manifest",
            str(manifest),
            "--request-id",
            str(uuid4()),
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert exit_code == (5 if invalid else 0)
    assert result["outcome"] == ("QUARANTINED" if invalid else "ACCEPTED")
    assert "r1" not in json.dumps(result)
    if invalid == "malformed_json":
        assert "CONTRACT_INVALID" in result["finding_codes"]


def test_replay_rechecks_current_source_access(intake):
    from mule_detection.persistence.errors import AccessDenied

    declared = declaration(intake)
    key = uuid4()
    submit(intake, declared=declared, idempotency_key=key)
    intake.authorize = lambda *_: False
    with pytest.raises(AccessDenied):
        submit(intake, declared=declared, idempotency_key=key)


@pytest.mark.parametrize(
    "case,code", [("future", "INCOMPATIBLE_TIMESTAMP"), ("source", "REQUIRED_SOURCE_UNAVAILABLE")]
)
def test_temporal_provenance_rules(intake, case, code):
    original = next(iter(intake.profiles.values()))
    extra = [
        {
            "name": name,
            "logical_type": "categorical",
            "role": "lineage",
            "required": True,
            "missing": "imputable",
        }
        for name in ("cutoff", "available", "snapshot", "source_present")
    ]
    profile = SourceProfile.model_validate(
        {
            **original.model_dump(),
            "columns": [*original.columns, *extra],
            "cutoff_column": "cutoff",
            "availability_column": "available",
            "snapshot_column": "snapshot",
            "required_source_columns": ["source_present"],
        }
    )
    intake.profiles[profile.source_id] = profile
    source = "" if case == "source" else "present"
    available = "2026-10-20T00:00:00Z" if case == "future" else "2026-10-19T00:00:00Z"
    content = (
        "record_key,amount,category,cutoff,available,snapshot,source_present\n"
        f"r1,1,Savings,2026-10-18T00:00:00Z,{available},2026-10-19T00:00:00Z,{source}\n"
    ).encode()
    declared = declaration(intake, content, observation_cutoff="2026-10-18T00:00:00Z")
    result = submit(intake, content, declared)
    assert code in result.finding_codes and result.outcome == "QUARANTINED"


def test_unpublished_report_and_staged_file_cannot_authorize_scoring(intake, db):
    result = submit(intake)
    # A new, untrusted report row cannot become a usable acceptance merely via its outcome.
    with unit_of_work(db) as session:
        batch = session.get(Batch, result.batch_id)
        report = ValidationReport(
            batch_id=batch.id, rules_hash="0" * 64, findings_uri="raw:staged", outcome="ACCEPTED"
        )
        session.add(report)
        session.flush()
        batch.accepted_validation_id = report.id
    with unit_of_work(db) as session:
        with pytest.raises(PersistenceConflict):
            Repositories(session).get_accepted_batch(result.batch_id)
