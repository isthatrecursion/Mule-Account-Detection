"""Synthetic accepted-input scoring through runtime DB and restricted model worker."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text

from mule_detection.application.context import ExecutionContext
from mule_detection.application.model_approval_service import ModelApprovalService
from mule_detection.application.registry_service import RegistryService
from mule_detection.application.scoring_service import ScoringService
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.domain.contracts.scoring import ScoringRequest
from mule_detection.domain.errors import DomainError
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.persistence.artifacts import ArtifactStore
from mule_detection.persistence.errors import AccessDenied, PersistenceConflict
from mule_detection.persistence.models import (
    AuditEvent,
    Batch,
    Job,
    QueueHead,
    ScoreRow,
    ScoringAttempt,
    ScoringChunk,
    ScoringTask,
)
from mule_detection.registry.bundle_loader import BundleLoader
from mule_detection.registry.bundle_writer import BundleStore, write_bundle
from mule_detection.registry.model_resolver import ModelResolver
from mule_detection.scoring.preflight import ResearchPreflight
from mule_detection.scoring.queries import ScoreQueries
from mule_detection.scoring.ranking import ReviewPolicy
from mule_detection.training.final_fit import fit_frozen_research
from tests.integration.test_registry import FakeRegistry
from tests.integration.test_training import CONTEXT
from tests.integration.test_training import training as training

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[2]
REVIEWER = ExecutionContext.create("scoring-reviewer", "test")


def record_rehearsal(name, details):
    import json
    import os

    directory = os.getenv("MULE_TEST_SCORING_REHEARSAL_DIR")
    if directory:
        path = Path(directory).resolve()
        assert path.is_relative_to(ROOT / "artifacts/phase8")
        path.mkdir(parents=True, exist_ok=True)
        with (path / (name + ".json")).open("x") as stream:
            json.dump(
                {"result": "PASSED", "input_source": "SYNTHETIC_ONLY", **details}, stream, indent=2
            )


@pytest.fixture
def scoring(training, db, tmp_path, request):
    trainer, batch, config = training
    if getattr(request, "param", None) == "logistic":
        from mule_detection.training.evaluation_policy import ModelSpec

        config = config.model_copy(
            update={"candidates": (ModelSpec(name="logistic", family="logistic"),)}
        )
    run = uuid4()
    trainer.train(batch, run, config, CONTEXT)
    data, _ = trainer.accepted_input(batch, CONTEXT)
    fitted, lineage = fit_frozen_research(
        data, FeaturePipeline.from_repository(ROOT), trainer.store, run
    )
    store = BundleStore(tmp_path / "bundles", b"z" * 32)
    digest = write_bundle(fitted, lineage, data.X.iloc[:3], store, root=ROOT)
    backend = FakeRegistry()
    registry = RegistryService(trainer.factory, store, backend, lambda *_: True)
    candidate = registry.create_candidate(digest, "scoring_synthetic", CONTEXT)
    registry.synchronize(candidate, CONTEXT)
    approval = ModelApprovalService(
        db, lambda context, action: context.actor_id == REVIEWER.actor_id
    )
    approval.decide(
        candidate,
        "test",
        "RESEARCH_DEMO",
        REVIEWER,
        reason="SYNTHETIC_SCORING",
        idempotency_key=uuid4(),
    )
    resolver = ModelResolver(trainer.factory, backend, lambda *_: True)
    loader = BundleLoader(store, resolver.authorized)

    def authorize(ctx, action):
        return ctx.actor_id == CONTEXT.actor_id and action in {
            "score:run",
            "score:read",
            "score:correct",
        }

    service = ScoringService(
        trainer.factory,
        ResearchPreflight(trainer, authorize),
        ArtifactStore(
            tmp_path / "scoring",
            b"s" * 32,
            lambda ctx, scope, action: authorize(ctx, "score:run") and scope == "research",
        ),
        resolver,
        loader,
        replace(ReviewPolicy.load(ROOT / "config/review_policy.yaml"), top_k=3),
        authorize,
        chunk_rows=16,
    )
    request = ScoringRequest(batch_id=batch, bundle_digest=digest, environment="test")
    return service, request, data, candidate, approval, fitted


def start(scoring):
    service, request, *_ = scoring
    created = service.create(request, CONTEXT)
    return service, UUID(created["job_id"]), UUID(created["run_id"])


def published(service, run):
    with unit_of_work(service.factory) as session:
        return {
            row.record_key: (
                row.raw_score,
                row.contract_payload["rank"],
                row.contract_payload["percentile"],
            )
            for row in session.scalars(select(ScoreRow).where(ScoreRow.run_id == run))
        }


def test_complete_pinned_scores_evidence_and_unavailable_are_distinct(scoring):
    service, job, run = start(scoring)
    result = service.run(job, CONTEXT)
    assert result["state"] == "COMPLETE" and len(published(service, run)) == 40
    assert result == service.run(job, CONTEXT)
    assert service.create(scoring[1], CONTEXT)["job_id"] == str(job)
    with unit_of_work(service.factory) as session:
        task = session.get(ScoringTask, job)
        row = session.scalar(
            select(ScoreRow)
            .where(ScoreRow.run_id == run)
            .order_by(ScoreRow.raw_score.desc(), ScoreRow.record_key)
        )
        cohort, key, score_id = task.cohort_id, row.record_key, row.id
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "queue:publish")
            )
            == 1
        )
    query = ScoreQueries(service)
    view = query.assessment(cohort, key, "test", CONTEXT)
    assert view.score.freshness == "STALE" and view.score.assessed_as_of is None
    assert query.assessment(cohort, "missing", "test", CONTEXT).score is None
    assert query.evidence(score_id, CONTEXT)["facts"]["scale"] == "raw_margin"
    with pytest.raises(AccessDenied):
        query.assessment(cohort, key, "test", REVIEWER)
    record_rehearsal(
        "complete",
        {
            "eligible_rows": 40,
            "selected_rows": 3,
            "same_request_same_job": True,
            "publication_events": 1,
            "contribution_scale": "raw_margin",
            "unavailable_is_null": True,
            "research_cutoff": "UNKNOWN",
            "holdout_rows_scored": 0,
        },
    )


@pytest.mark.parametrize(
    "stage", ["chunk:2", "evidence", "before_publish", "before_commit", "after_commit"]
)
def test_crash_retry_is_exact_and_previous_queue_is_preserved(scoring, stage):
    service, job, run = start(scoring)
    first = service.run(job, CONTEXT)
    reference = published(service, run)
    request = scoring[1].model_copy(update={"replay_id": uuid4(), "replay_of": run})
    created = service.create(request, CONTEXT)
    replay_job, replay_run = UUID(created["job_id"]), UUID(created["run_id"])

    def crash(point):
        if point == stage:
            raise TimeoutError("Synthetic interruption")

    with pytest.raises(TimeoutError):
        service.run(replay_job, CONTEXT, fault=crash)
    with unit_of_work(service.factory) as session:
        head = session.get(QueueHead, (session.get(ScoringTask, job).cohort_id, "test"))
        assert str(head.queue_id) == (
            service.result(replay_job, CONTEXT)["queue_id"]
            if stage == "after_commit"
            else first["queue_id"]
        )
        if stage != "after_commit":
            assert not published(service, replay_run)
    recovered = service.run(replay_job, CONTEXT)
    assert recovered["state"] == "COMPLETE"
    assert published(service, replay_run) == reference
    with unit_of_work(service.factory) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "queue:publish")
            )
            == 2
        )
    record_rehearsal(
        "crash_" + stage.replace(":", "_"),
        {
            "failure_stage": stage,
            "eligible_rows": 40,
            "recovered_matches_clean_scores_ranks_percentiles": True,
            "duplicate_publication_events": 0,
            "old_pointer_preserved_until_commit": True,
        },
    )


def test_concurrent_equivalent_creation_has_one_logical_identity(scoring):
    service, request, *_ = scoring
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.create(request, CONTEXT), range(2)))
    assert results[0] == results[1]
    with unit_of_work(service.factory) as session:
        assert session.scalar(select(func.count()).select_from(ScoringTask)) == 1


def test_quarantine_retirement_and_unauthorized_direct_worker_fail_closed(scoring, db):
    service, job, _ = start(scoring)
    with pytest.raises(AccessDenied):
        service.run(job, REVIEWER)
    with unit_of_work(db) as session:
        batch = session.get(Batch, scoring[1].batch_id)
        batch.status, batch.accepted_validation_id = "QUARANTINED", None
    with pytest.raises(PersistenceConflict):
        service.run(job, CONTEXT)
    with unit_of_work(service.factory) as session:
        assert session.get(Job, job).state == "FAILED"
        assert session.get(ScoringAttempt, (job, 1)).state == "FAILED"
        assert session.scalar(select(func.count()).select_from(QueueHead)) == 0


def test_retirement_during_publication_keeps_prior_pointer(scoring):
    service, job, run = start(scoring)
    first = service.run(job, CONTEXT)
    replay = service.create(
        scoring[1].model_copy(update={"replay_id": uuid4(), "replay_of": run}), CONTEXT
    )

    def revoke(stage):
        if stage == "before_publish":
            scoring[4].decide(
                scoring[3],
                "test",
                "RETIRED",
                REVIEWER,
                reason="SYNTHETIC_REVOCATION",
                idempotency_key=uuid4(),
            )

    with pytest.raises(DomainError):
        service.run(UUID(replay["job_id"]), CONTEXT, fault=revoke)
    with unit_of_work(service.factory) as session:
        head = session.get(QueueHead, (session.get(ScoringTask, job).cohort_id, "test"))
        assert str(head.queue_id) == first["queue_id"]


def test_missing_chunk_metadata_blocks_atomic_publication(scoring, db):
    service, job, _ = start(scoring)

    def remove(stage):
        if stage == "before_publish":
            # Corrupt staging metadata before independent publication validation.
            with unit_of_work(db) as session:
                session.execute(text("DELETE FROM scoring_chunks WHERE job_id=:job"), {"job": job})

    # Checked by the final transaction as well as the staging validator.
    with pytest.raises(DomainError):
        service.run(job, CONTEXT, fault=remove)


@pytest.mark.parametrize("scoring", ["logistic"], indirect=True)
def test_corrected_account_rebuilds_global_ranks_without_rewriting_prior_evidence(scoring, db):
    """A synthetic stable-identity source exercises the future corrected-input boundary.

    The default real research adapter deliberately cannot reconcile identities
    across extracts: its record keys are dataset-scoped. No real data is certified.
    """
    import numpy as np

    from mule_detection.domain.contracts.common import canonical_hash
    from mule_detection.ingestion.partition_guard import PartitionGuard
    from mule_detection.persistence.models import ValidationReport
    from mule_detection.persistence.repositories import Repositories
    from mule_detection.scoring.storage import frame_from_records, records_from_frame

    service, job, run = start(scoring)
    first = service.run(job, CONTEXT)
    original = published(service, run)
    data, fitted = scoring[2], scoring[5]
    target = max(original, key=lambda k: original[k][1])
    changed = data.X.copy()
    position = data.keys.index(target)
    numeric = next(
        (item, coefficient)
        for item, coefficient in zip(
            fitted.features.transformed_features_, fitted.estimator.coef_[0], strict=True
        )
        if item["index"] < fitted.numeric_stop and abs(coefficient) > 1e-10
    )
    changed.loc[changed.index[position], numeric[0]["raw_feature"]] = np.sign(numeric[1]) * 1e8
    assert fitted.predict_score(changed.iloc[[position]])[0] > max(v[0] for v in original.values())
    source = service.artifacts.put(
        records_from_frame(changed, data.keys),
        schema_id="research_features_v1",
        access_scope="research",
        context=CONTEXT,
    )
    batch_id, validation_id, event_id = uuid4(), uuid4(), uuid4()
    with unit_of_work(db) as session:
        repository = Repositories(session)
        dataset = repository.register_dataset(
            content_hash=source.digest,
            raw_uri=source.uri,
            schema_id="synthetic_stable_identity_source_v1",
            data_tier="research",
            row_count=len(data.keys),
        )
        batch = repository.register_batch(
            batch_id=batch_id,
            dataset_id=dataset.id,
            manifest_hash=canonical_hash({"event": str(event_id), "source": source.digest}),
        )
        session.add(
            ValidationReport(
                id=validation_id,
                batch_id=batch_id,
                rules_hash="b" * 64,
                findings_uri="synthetic:accepted",
                outcome="ACCEPTED",
                published=True,
            )
        )
        session.flush()
        batch.status, batch.accepted_validation_id = "ACCEPTED", validation_id

    class SyntheticStableInput(ResearchPreflight):
        def validate_keys(self, keys, dataset_hash, split_hash):
            assert (
                set(keys) == set(data.keys)
                and dataset_hash == source.digest
                and split_hash == data.split_hash
            )

        def load(self, identity, context):
            assert identity == batch_id
            with unit_of_work(service.factory) as session:
                accepted = Repositories(session).get_accepted_batch(identity)
                assert accepted.accepted_validation_id == validation_id
            records = service.artifacts.records(source, context)
            guard = PartitionGuard(source.digest, data.split_hash, frozenset(data.keys))
            guard.assert_development(data.keys, source.digest, data.split_hash)
            return replace(
                data,
                X=frame_from_records(records, data.keys, fitted.features.input_signature_),
                dataset_hash=source.digest,
                guard=guard,
            ), validation_id

    service.preflight = SyntheticStableInput(service.preflight.training, service.authorize)
    request = ScoringRequest(
        batch_id=batch_id,
        bundle_digest=scoring[1].bundle_digest,
        environment="test",
        replay_id=event_id,
        replay_of=run,
        affected_keys=(target,),
    )
    corrected = service.create(request, CONTEXT)
    service.run(UUID(corrected["job_id"]), CONTEXT)
    now = published(service, UUID(corrected["run_id"]))
    assert now[target][1] == 1 and original[target][1] > service.policy.top_k
    assert all(now[k][0] == original[k][0] for k in original if k != target)
    assert any(now[k][1] != original[k][1] for k in original if k != target)
    assert published(service, run) == original
    with unit_of_work(service.factory) as session:
        task = session.get(ScoringTask, job)
        old = ScoreQueries(service).assessment(
            task.cohort_id, target, "test", CONTEXT, opened_queue_id=UUID(first["queue_id"])
        )
        assert old.newer_assessment_available and old.score.raw_score == original[target][0]
        new = session.scalar(
            select(ScoreRow).where(
                ScoreRow.run_id == UUID(corrected["run_id"]), ScoreRow.record_key == target
            )
        )
        assert new.contract_payload["publication_event"] == "CORRECTED"
        assert new.contract_payload["baseline_score_id"]
    record_rehearsal(
        "correction",
        {
            "eligible_rows": 40,
            "affected_rows": 1,
            "unaffected_raw_scores_preserved": 39,
            "affected_rank_before": original[target][1],
            "affected_rank_after": now[target][1],
            "historical_queue_unchanged": True,
            "opened_queue_newer_assessment_flag": True,
            "source_identity_scope": "SYNTHETIC_STABLE_IDENTITY_ADAPTER_ONLY",
        },
    )


def test_nan_output_and_holdout_correction_do_not_publish(scoring, monkeypatch):
    service, job, run = start(scoring)
    from mule_detection.registry.bundle_loader import LoadedBundle

    monkeypatch.setattr(LoadedBundle, "predict_score", lambda _, frame: [float("nan")] * len(frame))
    with pytest.raises(DomainError):
        service.run(job, CONTEXT)
    assert not published(service, run)
    with pytest.raises(DomainError):
        service.create(
            scoring[1].model_copy(
                update={
                    "replay_of": run,
                    "replay_id": uuid4(),
                    "affected_keys": ("HOLDOUT_OR_UNKNOWN",),
                }
            ),
            CONTEXT,
        )


def test_replaced_fencing_token_prevents_stale_publication(scoring, db):
    from mule_detection.persistence.job_repository import JobRepository

    service, job, _ = start(scoring)

    def replace_lease(stage):
        if stage == "before_publish":
            with unit_of_work(db) as session:
                session.execute(
                    text(
                        "UPDATE jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=:id"
                    ),
                    {"id": job},
                )
                JobRepository(session).acquire(job, "replacement", seconds=60)

    with pytest.raises(PersistenceConflict):
        service.run(job, CONTEXT, fault=replace_lease)
    with unit_of_work(service.factory) as session:
        assert session.scalar(select(func.count()).select_from(QueueHead)) == 0
        assert session.get(Job, job).lease_owner == "replacement"
        assert session.get(ScoringAttempt, (job, 1)).state == "FAILED"


def test_direct_worker_rejects_injected_holdout_membership(scoring, db):
    from mule_detection.domain.identity import research_record_key

    service, job, _ = start(scoring)
    with unit_of_work(db) as session:
        task = session.get(ScoringTask, job)
        manifest = dict(task.manifest)
        manifest["keys"] = [*manifest["keys"], research_record_key(scoring[2].dataset_hash, "41")]
        task.manifest = manifest
    with pytest.raises(DomainError):
        service.run(job, CONTEXT)
    with unit_of_work(service.factory) as session:
        assert session.scalar(select(func.count()).select_from(QueueHead)) == 0
        assert session.scalar(select(func.count()).select_from(ScoringChunk)) == 0
