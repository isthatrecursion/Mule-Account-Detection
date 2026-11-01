"""Synthetic intake-to-candidate tests through runtime PostgreSQL privileges."""

import io
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from sqlalchemy import func, select

from mule_detection.application.context import ExecutionContext
from mule_detection.application.ingest_service import IngestService
from mule_detection.application.training_service import TrainingService
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.cli import main
from mule_detection.domain.contracts.labels import QualifiedLabel
from mule_detection.domain.errors import DomainError
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.ingestion.intake import SourceProfile
from mule_detection.persistence.errors import AccessDenied, PersistenceConflict
from mule_detection.persistence.models import AuditEvent, Batch, Label, ValidationReport
from mule_detection.persistence.raw_store import RawStore
from mule_detection.persistence.sqlalchemy import session_factory
from mule_detection.training.evaluation_policy import ModelSpec, TrainingConfig
from mule_detection.training.label_selector import LabelSnapshot, select_repository_labels
from mule_detection.training.report import RunStore
from tests.contracts.helpers import synthetic_research
from tests.integration.test_ingestion import declaration

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[2]
CONTEXT = ExecutionContext.create("training-engineer", "test")


@pytest.fixture
def training(db, runtime_engine, tmp_path):
    def expand(header, rows, splits):
        rows[:] = [
            [
                str(i),
                str(i / 100),
                str(i),
                "Savings" if i % 2 else "Current",
                "SYN_A" if i % 2 else "SYN_B",
                str(i % 2),
                str(i % 2),
            ]
            for i in range(1, 45)
        ]
        splits[:] = [[str(i), "dev" if i <= 40 else "holdout", str(i % 2)] for i in range(1, 45)]

    adapter, dataset, split = synthetic_research(tmp_path, change=expand)
    policy = FeaturePipeline.from_repository(ROOT).policy
    adapter = replace(adapter, expected_development_rows=40, feature_policy=policy)
    profile = SourceProfile(
        source_id="synthetic-research",
        schema_id="research_v1",
        data_tier="research",
        policy_version=policy.policy_version,
        access_scope="research",
        identity_columns=("Unnamed: 0",),
        columns=adapter.schema.columns,
        missing_tokens=adapter.schema.missing_tokens,
        expected_dataset_hash=adapter.trusted_dataset_sha256,
    )
    factory = session_factory(runtime_engine)
    raw = RawStore(tmp_path / "raw", b"x" * 32)
    intake = IngestService(
        factory,
        raw,
        {profile.source_id: profile},
        policy,
        authorize=lambda *_: True,
        max_rows=100,
        research_adapter=adapter,
        trusted_split=split,
    )
    content = dataset.read_bytes()
    accepted = intake.ingest(
        io.BytesIO(content),
        declaration(intake, content, provenance_limitations=["synthetic provenance"]),
        CONTEXT,
        idempotency_key=uuid4(),
    )
    assert accepted.outcome == "ACCEPTED"
    config = TrainingConfig(
        outer_folds=2,
        inner_folds=2,
        bootstrap_repetitions=20,
        candidates=(
            ModelSpec(name="logistic", family="logistic"),
            ModelSpec(name="tree", family="lightgbm", n_estimators=5),
        ),
    )
    service = TrainingService(
        factory,
        raw,
        RunStore(tmp_path / "training", b"y" * 32),
        adapter,
        split,
        ROOT,
        authorize=lambda *_: True,
    )
    return service, accepted.batch_id, config


def test_accepted_intake_trains_replays_and_audits_once(training, db):
    service, batch_id, config = training
    run_id = uuid4()
    result = service.train(batch_id, run_id, config, CONTEXT)
    assert result["status"] == "SUCCEEDED"
    assert result["metrics"]["logistic"]["rows"] == 40
    assert service.train(batch_id, run_id, config, CONTEXT) == result
    assert service.evaluate(run_id, CONTEXT) == result
    with unit_of_work(db) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "model:train", AuditEvent.idempotency_key == run_id)
            )
            == 1
        )
    assert not list((service.store.root / "input-staging").glob("*.csv"))


@pytest.mark.parametrize("invalid", ["quarantine", "unpublished"])
def test_invalid_current_acceptance_blocks_training(training, db, invalid):
    service, batch_id, config = training
    with unit_of_work(db) as session:
        batch = session.get(Batch, batch_id)
        if invalid == "quarantine":
            batch.status, batch.accepted_validation_id = "QUARANTINED", None
        else:
            session.get(ValidationReport, batch.accepted_validation_id).published = False
    with pytest.raises(PersistenceConflict):
        service.train(batch_id, uuid4(), config, CONTEXT)


def test_authorization_and_qualified_mode_are_enforced(training):
    service, batch_id, config = training
    service.authorize = lambda *_: False
    with pytest.raises(AccessDenied):
        service.train(batch_id, uuid4(), config, CONTEXT)
    with pytest.raises(AccessDenied):
        service.evaluate(uuid4(), CONTEXT)
    service.authorize = lambda *_: True
    with pytest.raises(DomainError):
        service.train(
            batch_id, uuid4(), config.model_copy(update={"mode": "qualified_temporal"}), CONTEXT
        )


def test_real_cli_dispatches_training_and_evaluation(training, app_root, monkeypatch, capsys):
    service, batch_id, config = training
    import mule_detection.application.training_bootstrap as bootstrap

    monkeypatch.setattr(bootstrap, "build_training", lambda _: service)
    path = app_root / "config/training_test.yaml"
    path.write_text(yaml.safe_dump(config.model_dump(mode="json")))
    run_id = uuid4()
    arguments = [
        "--root",
        str(app_root),
        "train",
        "--config",
        "config/training_test.yaml",
        "--mode",
        "research",
        "--batch-id",
        str(batch_id),
        "--run-id",
        str(run_id),
    ]
    assert main(arguments) == 0
    trained = json.loads(capsys.readouterr().out)
    assert trained["run_id"] == str(run_id)
    assert main(["--root", str(app_root), "evaluate", "--run-id", str(run_id)]) == 0
    assert json.loads(capsys.readouterr().out) == trained
    arguments[arguments.index("research")] = "qualified_temporal"
    assert main(arguments) == 5


def test_repository_label_query_never_resolves_future_outcomes(db):
    now = datetime(2026, 10, 20, tzinfo=UTC)
    first = QualifiedLabel(
        contract_version="label_v1",
        label_id=uuid4(),
        record_key="synthetic-account",
        account_id="account",
        value=1,
        label_source="approved-owner",
        event_at=now - timedelta(days=3),
        observed_at=now - timedelta(days=2),
        available_at=now - timedelta(days=2),
        mature_at=now - timedelta(days=1),
        status="ADJUDICATED",
        adjudication_reference="test",
        negative_policy_reference=None,
        version=1,
        supersedes=None,
    )
    future = first.model_copy(
        update={
            "label_id": uuid4(),
            "version": 2,
            "supersedes": first.label_id,
            "available_at": now + timedelta(days=1),
            "observed_at": now + timedelta(days=1),
            "value": 0,
        }
    )
    with unit_of_work(db) as session:
        for contract in (first, future):
            session.add(
                Label(
                    id=contract.label_id,
                    subject_key=contract.record_key,
                    outcome=str(contract.value),
                    maturity="MATURE",
                    known_at=contract.available_at,
                    supersedes_id=contract.supersedes,
                )
            )
            session.flush()
    resolved = []

    def resolver(identity):
        resolved.append(identity)
        assert identity == first.label_id
        return first

    snapshot = LabelSnapshot(
        first.record_key, first.account_id, now - timedelta(days=6), now - timedelta(days=5)
    )
    with unit_of_work(db) as session:
        selected, counts = select_repository_labels(session, (snapshot,), now, resolver)
    assert selected[first.record_key].value == 1 and counts["eligible"] == 1
    assert resolved == [first.label_id]
