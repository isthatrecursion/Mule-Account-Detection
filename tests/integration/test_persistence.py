import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from mule_detection.application.audit_service import AuditService
from mule_detection.application.context import ExecutionContext
from mule_detection.application.job_service import JobService
from mule_detection.application.review_service import ReviewService
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.persistence.errors import AccessDenied, LeaseLost, PersistenceConflict
from mule_detection.persistence.job_repository import JobRepository
from mule_detection.persistence.models import (
    Artifact,
    AuditEvent,
    Base,
    Batch,
    Case,
    Dataset,
    Job,
    JobAttempt,
    ModelRef,
    Outbox,
    QueueMember,
    QueueSnapshot,
    ReviewEvent,
    ScoreRow,
    ScoreRun,
    ValidationReport,
)
from mule_detection.persistence.repositories import Repositories
from mule_detection.persistence.sqlalchemy import make_engine, session_factory

pytestmark = pytest.mark.postgres
CONTEXT = ExecutionContext.create("synthetic-analyst", "test")
PERMISSIONS = frozenset({"case:review", "case:assign", "case:reopen"})
SCOPES = frozenset({"synthetic-team"})


@dataclass(frozen=True)
class Lineage:
    batch_id: UUID
    model_id: UUID
    artifact_id: UUID
    run_id: UUID
    score_id: UUID
    case_id: UUID


def seed(factory) -> Lineage:
    with unit_of_work(factory) as session:
        dataset = Dataset(
            content_hash="a" * 64,
            raw_uri="artifact:synthetic",
            schema_id="synthetic_v1",
            data_tier="synthetic",
            row_count=1,
        )
        session.add(dataset)
        session.flush()
        batch = Batch(dataset_id=dataset.id, manifest_hash="b" * 64)
        session.add(batch)
        session.flush()
        report = ValidationReport(
            batch_id=batch.id,
            rules_hash="c" * 64,
            findings_uri="artifact:findings",
            outcome="ACCEPTED",
        )
        session.add(report)
        session.flush()
        batch.status = "ACCEPTED"
        batch.accepted_validation_id = report.id
        model = ModelRef(
            bundle_digest="d" * 64,
            registry_name="synthetic",
            registry_version="1",
            tier="research_demo",
        )
        artifact = Artifact(
            digest="e" * 64,
            uri="artifact:sha256:" + "e" * 64,
            schema_id="synthetic_v1",
            row_count=1,
            access_scope="synthetic-team",
        )
        session.add_all([model, artifact])
        session.flush()
        run = Repositories(session).create_run(
            actor_id=CONTEXT.actor_id,
            idempotency_key=uuid4(),
            batch_id=batch.id,
            model_id=model.id,
            policy_hash="f" * 64,
            snapshot_id=artifact.id,
        )
        score = ScoreRow(
            run_id=run.id, record_key="synthetic-record", raw_score=0.5, contract_payload={}
        )
        session.add(score)
        session.flush()
        case = Case(
            subject_key="synthetic-record",
            score_id=score.id,
            access_scope="synthetic-team",
            state="IN_REVIEW",
            version=4,
            assignee=CONTEXT.actor_id,
        )
        session.add(case)
        session.flush()
        return Lineage(batch.id, model.id, artifact.id, run.id, score.id, case.id)


def transition(service, lineage, key=None, **changes):
    return service.transition(
        case_id=lineage.case_id,
        expected_version=4,
        target="REVIEWED",
        idempotency_key=key or uuid4(),
        context=CONTEXT,
        permissions=PERMISSIONS,
        scopes=SCOPES,
        conclusion=changes.get("conclusion", "NO_FURTHER_REVIEW"),
        note_reference="note:synthetic",
    )


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_migrations_match_metadata_and_head(migrated_engine, record_testsuite_property):
    assert set(Base.metadata.tables) <= set(inspect(migrated_engine).get_table_names())
    with migrated_engine.connect() as connection:
        record_testsuite_property("postgresql_version", connection.scalar(text("SELECT version()")))
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0005"
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_failed_migration_rolls_back_and_recovery_preserves_revision(db, migrated_engine, tmp_path):
    root = Path(__file__).resolve().parents[2]
    shutil.copytree(root / "migrations", tmp_path / "migrations")
    (tmp_path / "migrations/versions/0006_synthetic_failure.py").write_text(
        "from alembic import op\nimport sqlalchemy as sa\nrevision='0006_test_failure'\ndown_revision='0005'\nbranch_labels=None\ndepends_on=None\n"
        "def upgrade():\n    op.create_table('synthetic_should_rollback', sa.Column('id', sa.Integer))\n    op.execute('SELECT 1/0')\n"
    )
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(tmp_path / "migrations"))
    with pytest.raises(DBAPIError), migrated_engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
    with migrated_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0005"
        assert (
            connection.scalar(text("SELECT to_regclass('public.synthetic_should_rollback')"))
            is None
        )
    cfg = Config(str(root / "alembic.ini"))
    with migrated_engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")


def test_database_enforces_lineage_and_duplicate_identities(db):
    lineage = seed(db)
    for values in (
        {"run_id": uuid4(), "record_key": "missing-parent"},
        {"run_id": lineage.run_id, "record_key": "synthetic-record"},
    ):
        with pytest.raises(IntegrityError), unit_of_work(db) as session:
            session.add(ScoreRow(**values, raw_score=0.1, contract_payload={}))
    with db() as session:
        assert count(session, ScoreRow) == 1


def test_concurrent_run_creation_replays_or_conflicts(db):
    lineage = seed(db)
    key = uuid4()
    barrier = Barrier(2)

    def create():
        barrier.wait(timeout=10)
        with unit_of_work(db) as session:
            return (
                Repositories(session)
                .create_run(
                    actor_id=CONTEXT.actor_id,
                    idempotency_key=key,
                    batch_id=lineage.batch_id,
                    model_id=lineage.model_id,
                    policy_hash="f" * 64,
                    snapshot_id=lineage.artifact_id,
                )
                .id
            )

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(create) for _ in range(2)]
        identities = [future.result(timeout=15) for future in futures]
    assert identities[0] == identities[1]
    with pytest.raises(PersistenceConflict), unit_of_work(db) as session:
        Repositories(session).create_run(
            actor_id=CONTEXT.actor_id,
            idempotency_key=key,
            batch_id=lineage.batch_id,
            model_id=lineage.model_id,
            policy_hash="0" * 64,
            snapshot_id=lineage.artifact_id,
        )
    with db() as session:
        assert count(session, ScoreRun) == 2


def test_scoped_job_idempotency_and_concurrent_duplicate_requests(db):
    key = uuid4()
    barrier = Barrier(2)

    def create():
        barrier.wait(timeout=10)
        with unit_of_work(db) as session:
            return (
                JobRepository(session)
                .create(
                    actor_id="a",
                    operation="score",
                    idempotency_key=key,
                    request={"batch": "synthetic"},
                )
                .id
            )

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(create) for _ in range(2)]
        ids = [f.result(timeout=15) for f in futures]
    assert ids[0] == ids[1]
    with pytest.raises(PersistenceConflict), unit_of_work(db) as session:
        JobRepository(session).create(
            actor_id="a", operation="score", idempotency_key=key, request={"batch": "changed"}
        )
    for actor, operation in [("b", "score"), ("a", "validate")]:
        with unit_of_work(db) as session:
            JobRepository(session).create(
                actor_id=actor,
                operation=operation,
                idempotency_key=key,
                request={"batch": "synthetic"},
            )
    with db() as session:
        assert count(session, Job) == 3


def test_dataset_batch_registration_replay_and_change_conflict(db):
    values = dict(
        content_hash="a" * 64,
        raw_uri="artifact:synthetic",
        schema_id="synthetic_v1",
        data_tier="synthetic",
        row_count=2,
    )
    key = uuid4()
    identities = []
    for _ in range(2):
        with unit_of_work(db) as session:
            repo = Repositories(session)
            dataset = repo.register_dataset(**values)
            identities.append(
                (
                    dataset.id,
                    repo.register_batch(
                        batch_id=key, dataset_id=dataset.id, manifest_hash="b" * 64
                    ).id,
                )
            )
    assert identities[0] == identities[1]
    with pytest.raises(PersistenceConflict), unit_of_work(db) as session:
        Repositories(session).register_dataset(**{**values, "row_count": 3})
    with pytest.raises(PersistenceConflict), unit_of_work(db) as session:
        Repositories(session).register_batch(
            batch_id=key, dataset_id=identities[0][0], manifest_hash="c" * 64
        )


def test_concurrent_exact_review_replay_commits_one_event(db, runtime_engine):
    lineage = seed(db)
    key = uuid4()
    barrier = Barrier(2)

    def review():
        barrier.wait(timeout=10)
        return transition(ReviewService(session_factory(runtime_engine)), lineage, key)

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(review) for _ in range(2)]
        results = [f.result(timeout=15) for f in futures]
    assert results[0] == results[1]
    with db() as session:
        assert count(session, ReviewEvent) == count(session, AuditEvent) == 1


def test_atomic_review_audit_outbox_exact_retry_and_changed_content(db, runtime_engine):
    lineage = seed(db)
    service = ReviewService(session_factory(runtime_engine))
    key = uuid4()
    first = transition(service, lineage, key)
    assert transition(service, lineage, key) == first
    with pytest.raises(PersistenceConflict):
        transition(service, lineage, key, conclusion="NEEDS_MORE_INFORMATION")
    with db() as session:
        case = session.get(Case, lineage.case_id)
        assert case.version == 5 and case.state == "REVIEWED"
        assert (
            count(session, ReviewEvent) == count(session, AuditEvent) == count(session, Outbox) == 1
        )
        audit = session.scalars(select(AuditEvent)).one()
        assert audit.actor_id == CONTEXT.actor_id and audit.reason_reference == "note:synthetic"


@pytest.mark.parametrize("after_append", [False, True])
def test_failure_between_business_and_audit_rolls_back_everything(db, runtime_engine, after_append):
    lineage = seed(db)

    class FailingAudit(AuditService):
        def append(self, session, context, **values):
            if after_append:
                super().append(session, context, **values)
            # A real PostgreSQL constraint failure, rather than only a mocked exception.
            session.execute(text("INSERT INTO audit_events(id) VALUES (:id)"), {"id": uuid4()})

    with pytest.raises(IntegrityError):
        transition(ReviewService(session_factory(runtime_engine), FailingAudit()), lineage)
    with db() as session:
        assert session.get(Case, lineage.case_id).version == 4
        assert (
            count(session, ReviewEvent) == count(session, AuditEvent) == count(session, Outbox) == 0
        )


def test_simultaneous_reviews_only_one_commits(db, runtime_engine):
    lineage = seed(db)
    barrier = Barrier(2)

    def review():
        barrier.wait(timeout=10)
        try:
            transition(ReviewService(session_factory(runtime_engine)), lineage)
            return "committed"
        except PersistenceConflict:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(review) for _ in range(2)]
        assert sorted(f.result(timeout=15) for f in futures) == ["committed", "conflict"]
    with db() as session:
        assert session.get(Case, lineage.case_id).version == 5
        assert count(session, ReviewEvent) == count(session, AuditEvent) == 1


def test_scope_denial_and_reopen_replay_preserve_history(db, runtime_engine):
    lineage = seed(db)
    service = ReviewService(session_factory(runtime_engine))
    reviewed = transition(service, lineage)
    key = uuid4()
    kwargs = dict(
        case_id=lineage.case_id,
        expected_version=5,
        target="ASSIGNED",
        idempotency_key=key,
        context=CONTEXT,
        permissions=PERMISSIONS,
        scopes=SCOPES,
        assignee="synthetic-other",
        note_reference="note:reopen",
    )
    reopened = service.transition(**kwargs)
    assert service.transition(**kwargs) == reopened
    with pytest.raises(AccessDenied):
        service.transition(**{**kwargs, "scopes": frozenset()})
    with pytest.raises(AccessDenied):
        service.transition(**{**kwargs, "permissions": frozenset({"case:assign"})})
    with db() as session:
        assert session.get(ReviewEvent, reviewed.event_id).conclusion == "NO_FURTHER_REVIEW"
        assert session.get(Case, lineage.case_id).conclusion is None
        assert count(session, ReviewEvent) == count(session, AuditEvent) == 2


def test_runtime_privileges_and_readonly_access(db, runtime_engine, readonly_engine):
    lineage = seed(db)
    transition(ReviewService(session_factory(runtime_engine)), lineage)
    for statement in (
        "UPDATE audit_events SET actor_id = 'tampered'",
        "DELETE FROM audit_events",
        "UPDATE review_events SET note_reference = 'tampered'",
        "DELETE FROM approvals",
        "TRUNCATE audit_events",
        "CREATE TABLE forbidden(id int)",
        "UPDATE alembic_version SET version_num = 'tampered'",
        "UPDATE cases SET score_id = score_id",
        "UPDATE batches SET dataset_id = dataset_id",
        "UPDATE outbox SET payload_reference = 'tampered'",
    ):
        with pytest.raises(DBAPIError), runtime_engine.begin() as connection:
            connection.execute(text(statement))
    with readonly_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM audit_events")) == 1
    with pytest.raises(DBAPIError), readonly_engine.begin() as connection:
        connection.execute(text("DELETE FROM cases"))


def test_cross_database_role_isolation(runtime_engine, readonly_engine, migrated_engine):
    # A fixed target database is safe: these identities are expected to be refused CONNECT.
    for source, target in [
        (runtime_engine, "mule_tracking"),
        (readonly_engine, "mule_tracking"),
        (runtime_engine, "postgres"),
        (migrated_engine, "mule_tracking"),
    ]:
        engine = make_engine(source.url.set(database=target).render_as_string(hide_password=False))
        try:
            with pytest.raises(DBAPIError), engine.connect():
                pass
        finally:
            engine.dispose()
    tracking = make_engine(os.environ["MULE_TEST_TRACKING_DATABASE_URL"])
    try:
        with tracking.connect() as connection:
            assert connection.scalar(text("SELECT current_user")) == "mule_tracking"
        engine = make_engine(
            tracking.url.set(database=migrated_engine.url.database).render_as_string(
                hide_password=False
            )
        )
        try:
            with pytest.raises(DBAPIError), engine.connect():
                pass
        finally:
            engine.dispose()
    finally:
        tracking.dispose()
    with pytest.raises(DBAPIError), runtime_engine.begin() as connection:
        connection.execute(text("SET ROLE mule_migration"))


def create_lease(factory, *, seconds=60):
    with unit_of_work(factory) as session:
        job = JobRepository(session).create(
            actor_id="synthetic-worker",
            operation="score",
            idempotency_key=uuid4(),
            request={"synthetic": True},
        )
        lease = JobRepository(session).acquire(job.id, "worker-a", seconds=seconds)
    return lease


def test_lease_renewal_replacement_and_stale_publish(db, runtime_engine):
    runtime = session_factory(runtime_engine)
    lease = create_lease(runtime)
    with unit_of_work(runtime) as session:
        renewed = JobRepository(session).renew(lease, seconds=120)
        assert renewed.expires_at > lease.expires_at
    with pytest.raises(LeaseLost), unit_of_work(runtime) as session:
        JobRepository(session).acquire(lease.job_id, "worker-b")
    with unit_of_work(db) as session:
        session.execute(
            update(Job)
            .where(Job.id == lease.job_id)
            .values(lease_expires_at=func.clock_timestamp() - text("interval '1 second'"))
        )
    with pytest.raises(LeaseLost), unit_of_work(runtime) as session:
        JobRepository(session).renew(lease)
    with unit_of_work(runtime) as session:
        replacement = JobRepository(session).acquire(lease.job_id, "worker-b")
    assert replacement.token == lease.token + 1
    called = []
    with pytest.raises(LeaseLost):
        JobService(runtime).publish(
            lease, CONTEXT, lambda session: called.append(True), result_reference="queue:stale"
        )
    assert not called
    JobService(runtime).publish(
        replacement, CONTEXT, lambda session: None, result_reference="queue:synthetic"
    )
    with db() as session:
        assert session.get(Job, lease.job_id).state == "SUCCEEDED"
        assert count(session, JobAttempt) == 2 and count(session, AuditEvent) == 1


def test_lease_expiring_during_publication_rolls_back_results_and_audit(db, runtime_engine):
    runtime = session_factory(runtime_engine)
    lease = create_lease(runtime)

    def write(session):
        # Simulate expiry at the precise failure boundary, without a timing-dependent sleep.
        session.execute(
            update(Job)
            .where(Job.id == lease.job_id)
            .values(lease_expires_at=func.clock_timestamp() - text("interval '1 second'"))
        )

    with pytest.raises(LeaseLost):
        JobService(runtime).publish(lease, CONTEXT, write, result_reference="queue:expired")
    with db() as session:
        assert session.get(Job, lease.job_id).state == "RUNNING"
        assert count(session, AuditEvent) == count(session, Outbox) == 0


def test_publication_lock_prevents_replacement_until_commit(db, runtime_engine):
    runtime = session_factory(runtime_engine)
    lease = create_lease(runtime)
    entered, release, replacing = Event(), Event(), Event()

    def publish():
        def write(session):
            entered.set()
            assert release.wait(timeout=10)

        JobService(runtime).publish(lease, CONTEXT, write, result_reference="queue:locked")

    def replace():
        assert entered.wait(timeout=10)
        replacing.set()
        try:
            with unit_of_work(runtime) as session:
                JobRepository(session).acquire(lease.job_id, "worker-b")
        except LeaseLost:
            return "rejected"
        return "unexpected"

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(publish)
        assert entered.wait(timeout=10)
        second = pool.submit(replace)
        assert replacing.wait(timeout=10)
        release.set()
        first.result(timeout=15)
        assert second.result(timeout=15) == "rejected"


def test_privileged_retry_is_idempotent_and_audited(db, runtime_engine):
    runtime = session_factory(runtime_engine)
    lease = create_lease(runtime)
    with unit_of_work(db) as session:
        session.execute(
            update(Job)
            .where(Job.id == lease.job_id)
            .values(state="FAILED", lease_owner=None, lease_expires_at=None)
        )
    service = JobService(runtime)
    key = uuid4()
    values = dict(
        permissions=frozenset({"job:retry"}),
        reason_reference="reason:synthetic",
        idempotency_key=key,
    )
    service.retry(lease.job_id, CONTEXT, **values)
    service.retry(lease.job_id, CONTEXT, **values)
    with pytest.raises(PersistenceConflict):
        service.retry(lease.job_id, CONTEXT, **{**values, "reason_reference": "reason:changed"})
    with pytest.raises(AccessDenied):
        service.retry(lease.job_id, CONTEXT, **{**values, "permissions": frozenset()})
    with db() as session:
        assert session.get(Job, lease.job_id).state == "PENDING"
        assert count(session, AuditEvent) == count(session, Outbox) == 1


@pytest.mark.parametrize("audit_fails", [False, True])
def test_queue_publication_and_audit_commit_together(db, runtime_engine, audit_fails):
    lineage = seed(db)
    runtime = session_factory(runtime_engine)
    lease = create_lease(runtime)
    queue_id = uuid4()

    class FailingAudit(AuditService):
        def append(self, session, context, **values):
            super().append(session, context, **values)
            raise RuntimeError("Synthetic failure after audit append")

    service = JobService(runtime, FailingAudit() if audit_fails else AuditService())

    def write(session):
        queue = QueueSnapshot(
            id=queue_id,
            run_id=lineage.run_id,
            cohort_id=uuid4(),
            policy_hash="f" * 64,
            published_version=1,
            published_at=func.clock_timestamp(),
        )
        member = QueueMember(
            queue_id=queue_id,
            run_id=lineage.run_id,
            score_id=lineage.score_id,
            record_key="synthetic-record",
            rank=1,
        )
        Repositories(session).publish_queue(queue, [member])

    if audit_fails:
        with pytest.raises(RuntimeError):
            service.publish(lease, CONTEXT, write, result_reference=f"queue:{queue_id}")
    else:
        service.publish(lease, CONTEXT, write, result_reference=f"queue:{queue_id}")
    with db() as session:
        expected = 0 if audit_fails else 1
        assert count(session, QueueSnapshot) == count(session, QueueMember) == expected
        assert count(session, AuditEvent) == count(session, Outbox) == expected
        assert session.get(Job, lease.job_id).state == ("RUNNING" if audit_fails else "SUCCEEDED")


def test_connection_restart_and_pinned_case_artifact(db, migrated_engine):
    lineage = seed(db)
    migrated_engine.dispose()
    with db() as session:
        reference, record_key = Repositories(session).case_artifact(lineage.case_id, SCOPES)
        assert reference.digest == "e" * 64 and record_key == "synthetic-record"
        with pytest.raises(AccessDenied):
            Repositories(session).case_artifact(lineage.case_id, frozenset())
        assert session.get(ScoreRun, lineage.run_id).snapshot_id == lineage.artifact_id


def test_queue_membership_constraints_keyset_pagination_and_explain(db, record_testsuite_property):
    lineage = seed(db)
    queue_id = uuid4()
    with unit_of_work(db) as session:
        session.add(
            QueueSnapshot(
                id=queue_id,
                run_id=lineage.run_id,
                cohort_id=uuid4(),
                policy_hash="f" * 64,
                published_version=1,
                published_at=func.clock_timestamp(),
            )
        )
        session.flush()
        scores = [
            {
                "id": uuid4(),
                "run_id": lineage.run_id,
                "record_key": f"scale-{i}",
                "raw_score": 0.5,
                "contract_payload": {},
            }
            for i in range(10000)
        ]
        session.execute(ScoreRow.__table__.insert(), scores)
        session.execute(
            QueueMember.__table__.insert(),
            [
                {
                    "queue_id": queue_id,
                    "run_id": lineage.run_id,
                    "score_id": row["id"],
                    "record_key": row["record_key"],
                    "rank": i + 1,
                }
                for i, row in enumerate(scores)
            ],
        )
    with db() as session:
        page = Repositories(session).queue_page(queue_id, after_rank=5000, limit=50)
        assert [row.rank for row in page] == list(range(5001, 5051))
        session.execute(text("ANALYZE queue_members"))
        plan = session.scalar(
            text(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT * FROM queue_members WHERE queue_id=:id AND rank > 5000 ORDER BY rank LIMIT 50"
            ),
            {"id": queue_id},
        )
        assert plan[0]["Plan"]["Actual Rows"] == 50
        assert "Index" in str(plan) and "queue_id" in str(plan)
        record_testsuite_property("synthetic_queue_explain", json.dumps(plan))
    with pytest.raises(IntegrityError), unit_of_work(db) as session:
        session.add(
            QueueMember(
                queue_id=queue_id,
                run_id=lineage.run_id,
                score_id=lineage.score_id,
                record_key="wrong-record",
                rank=10001,
            )
        )
    with pytest.raises(IntegrityError), unit_of_work(db) as session:
        session.add(
            QueueMember(
                queue_id=queue_id,
                run_id=lineage.run_id,
                score_id=lineage.score_id,
                record_key="synthetic-record",
                rank=1,
            )
        )
