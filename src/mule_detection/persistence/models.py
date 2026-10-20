"""Operational metadata only. Wide observations live in encrypted immutable artifacts."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Identity:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )


class Dataset(Identity, Base):
    __tablename__ = "datasets"
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    raw_uri: Mapped[str]
    schema_id: Mapped[str]
    data_tier: Mapped[str]
    row_count: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (
        CheckConstraint("row_count >= 0", name="row_count"),
        CheckConstraint("data_tier IN ('research','qualified','synthetic')", name="tier"),
    )


class Batch(Identity, Base):
    __tablename__ = "batches"
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id"))
    manifest_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(default="RECEIVED")
    accepted_validation_id: Mapped[UUID | None]
    # Deferred to allow report creation then acceptance in one transaction.
    __table_args__ = (
        ForeignKeyConstraint(
            ["accepted_validation_id", "id"],
            ["validation_reports.id", "validation_reports.batch_id"],
            name="fk_batch_accepted_validation",
            use_alter=True,
        ),
        CheckConstraint("status IN ('RECEIVED','ACCEPTED','QUARANTINED')", name="status"),
        CheckConstraint(
            "(status = 'ACCEPTED') = (accepted_validation_id IS NOT NULL)", name="acceptance"
        ),
    )


class ValidationReport(Identity, Base):
    __tablename__ = "validation_reports"
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("batches.id"))
    rules_hash: Mapped[str] = mapped_column(String(64))
    findings_uri: Mapped[str]
    outcome: Mapped[str]
    __table_args__ = (
        UniqueConstraint("batch_id", "rules_hash"),
        UniqueConstraint("id", "batch_id"),
        CheckConstraint("outcome IN ('ACCEPTED','REJECTED')", name="outcome"),
    )


class ModelRef(Identity, Base):
    __tablename__ = "model_refs"
    bundle_digest: Mapped[str] = mapped_column(String(64), unique=True)
    registry_name: Mapped[str]
    registry_version: Mapped[str]
    tier: Mapped[str]
    __table_args__ = (
        UniqueConstraint("registry_name", "registry_version"),
        CheckConstraint(
            "tier IN ('research_demo','approved_for_shadow','approved_for_pilot')", name="tier"
        ),
    )


class Job(Identity, Base):
    __tablename__ = "jobs"
    actor_id: Mapped[str]
    operation: Mapped[str]
    idempotency_key: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(default="PENDING")
    lease_owner: Mapped[str | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fencing_token: Mapped[int] = mapped_column(BigInteger, default=0)
    result_reference: Mapped[str | None]
    __table_args__ = (
        UniqueConstraint("actor_id", "operation", "idempotency_key", name="uq_job_request"),
        CheckConstraint("state IN ('PENDING','RUNNING','SUCCEEDED','FAILED')", name="state"),
        CheckConstraint("fencing_token >= 0", name="fence"),
        CheckConstraint("(lease_owner IS NULL) = (lease_expires_at IS NULL)", name="lease_pair"),
        Index("ix_jobs_state_lease", "state", "lease_expires_at"),
    )


class JobAttempt(Identity, Base):
    __tablename__ = "job_attempts"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    fencing_token: Mapped[int] = mapped_column(BigInteger)
    owner: Mapped[str]
    __table_args__ = (UniqueConstraint("job_id", "fencing_token"),)


class Artifact(Identity, Base):
    __tablename__ = "artifacts"
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    uri: Mapped[str] = mapped_column(unique=True)
    schema_id: Mapped[str]
    row_count: Mapped[int] = mapped_column(BigInteger)
    access_scope: Mapped[str]
    __table_args__ = (CheckConstraint("row_count >= 0", name="row_count"),)


class ScoreRun(Identity, Base):
    __tablename__ = "score_runs"
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("batches.id"))
    model_id: Mapped[UUID] = mapped_column(ForeignKey("model_refs.id"))
    policy_hash: Mapped[str] = mapped_column(String(64))
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"))
    actor_id: Mapped[str]
    operation: Mapped[str] = mapped_column(default="score")
    idempotency_key: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("actor_id", "operation", "idempotency_key", name="uq_run_request"),
    )


class ScoreRow(Identity, Base):
    __tablename__ = "score_rows"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("score_runs.id"))
    record_key: Mapped[str]
    raw_score: Mapped[float | None] = mapped_column(Float)
    contract_payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("run_id", "record_key"),
        UniqueConstraint("id", "run_id", "record_key"),
        CheckConstraint(
            "raw_score IS NULL OR (raw_score > '-Infinity'::float8 "
            "AND raw_score < 'Infinity'::float8)",
            name="finite_score",
        ),
    )


class Evidence(Identity, Base):
    __tablename__ = "evidence"
    score_id: Mapped[UUID] = mapped_column(ForeignKey("score_rows.id"), unique=True)
    dictionary_version: Mapped[str]
    structured_evidence: Mapped[dict[str, object]] = mapped_column(JSONB)


class QueueSnapshot(Identity, Base):
    __tablename__ = "queue_snapshots"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("score_runs.id"))
    cohort_id: Mapped[UUID]
    policy_hash: Mapped[str] = mapped_column(String(64))
    published_version: Mapped[int]
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("cohort_id", "published_version"),
        UniqueConstraint("id", "run_id"),
        CheckConstraint("published_version > 0", name="version"),
    )


class QueueMember(Base):
    __tablename__ = "queue_members"
    queue_id: Mapped[UUID] = mapped_column(primary_key=True)
    record_key: Mapped[str] = mapped_column(primary_key=True)
    rank: Mapped[int]
    score_id: Mapped[UUID]
    run_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("queue_id", "rank"),
        ForeignKeyConstraint(
            ["queue_id", "run_id"], ["queue_snapshots.id", "queue_snapshots.run_id"]
        ),
        ForeignKeyConstraint(
            ["score_id", "run_id", "record_key"],
            ["score_rows.id", "score_rows.run_id", "score_rows.record_key"],
        ),
        CheckConstraint("rank > 0", name="rank"),
    )


class Case(Identity, Base):
    __tablename__ = "cases"
    subject_key: Mapped[str]
    score_id: Mapped[UUID] = mapped_column(ForeignKey("score_rows.id"))
    access_scope: Mapped[str]
    state: Mapped[str] = mapped_column(default="QUEUED")
    assignee: Mapped[str | None]
    version: Mapped[int] = mapped_column(Integer, default=0)
    conclusion: Mapped[str | None]
    __table_args__ = (
        CheckConstraint("version >= 0", name="version"),
        CheckConstraint("state IN ('QUEUED','ASSIGNED','IN_REVIEW','REVIEWED')", name="state"),
        Index("ix_cases_scope_state_assignee", "access_scope", "state", "assignee"),
        Index("ix_cases_subject_time", "subject_key", "created_at"),
    )


class ReviewEvent(Identity, Base):
    __tablename__ = "review_events"
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"))
    case_version: Mapped[int]
    actor_id: Mapped[str]
    operation: Mapped[str]
    action: Mapped[str]
    idempotency_key: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    target_state: Mapped[str]
    conclusion: Mapped[str | None]
    note_reference: Mapped[str | None]
    __table_args__ = (
        UniqueConstraint("actor_id", "operation", "idempotency_key", name="uq_review_request"),
        UniqueConstraint("case_id", "case_version"),
        Index("ix_review_case_time", "case_id", "created_at"),
    )


class Approval(Identity, Base):
    __tablename__ = "approvals"
    model_id: Mapped[UUID] = mapped_column(ForeignKey("model_refs.id"))
    actor_id: Mapped[str]
    decision: Mapped[str]
    evidence_reference: Mapped[str]
    supersedes_id: Mapped[UUID | None] = mapped_column(ForeignKey("approvals.id"), unique=True)


class Label(Identity, Base):
    __tablename__ = "labels"
    subject_key: Mapped[str]
    outcome: Mapped[str]
    maturity: Mapped[str]
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_id: Mapped[UUID | None] = mapped_column(ForeignKey("labels.id"), unique=True)
    __table_args__ = (Index("ix_labels_subject_known", "subject_key", "known_at"),)


class AuditEvent(Identity, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[str]
    action: Mapped[str]
    entity_reference: Mapped[str]
    entity_version: Mapped[int | None]
    correlation_id: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[UUID] = mapped_column(default=uuid4)
    before_reference: Mapped[str | None]
    after_reference: Mapped[str | None]
    reason_reference: Mapped[str | None]
    __table_args__ = (
        UniqueConstraint("actor_id", "action", "idempotency_key", name="uq_audit_action_request"),
        Index("ix_audit_entity_time", "entity_reference", "created_at"),
    )


class Outbox(Identity, Base):
    __tablename__ = "outbox"
    audit_id: Mapped[UUID] = mapped_column(ForeignKey("audit_events.id"), unique=True)
    payload_reference: Mapped[str]
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
