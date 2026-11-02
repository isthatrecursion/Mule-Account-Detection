"""Operational metadata only. Wide observations live in encrypted immutable artifacts."""

from datetime import datetime
from typing import Any
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
    published: Mapped[bool] = mapped_column(default=False)
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
    validation_id: Mapped[UUID | None]
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
        ForeignKeyConstraint(
            ["validation_id", "batch_id"],
            ["validation_reports.id", "validation_reports.batch_id"],
            name="fk_run_validation",
        ),
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


class ScoringTask(Base):
    __tablename__ = "scoring_tasks"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("score_runs.id"), unique=True)
    cohort_id: Mapped[UUID]
    environment: Mapped[str]
    predecessor_queue_id: Mapped[UUID | None] = mapped_column(ForeignKey("queue_snapshots.id"))
    parent_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("score_runs.id"))
    manifest: Mapped[dict[str, object]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(default="STAGED")
    __table_args__ = (CheckConstraint("state IN ('STAGED','COMPLETE')", name="state"),)


class ScoringChunk(Base):
    __tablename__ = "scoring_chunks"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("scoring_tasks.job_id"), primary_key=True)
    fencing_token: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chunk_index: Mapped[int] = mapped_column(primary_key=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"))
    membership_hash: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int]
    __table_args__ = (
        CheckConstraint("row_count >= 0 AND chunk_index >= 0 AND fencing_token > 0", name="counts"),
    )


class ScoringAttempt(Base):
    __tablename__ = "scoring_attempts"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    fencing_token: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_id: Mapped[str]
    environment: Mapped[str]
    state: Mapped[str]
    error_code: Mapped[str | None]
    __table_args__ = (CheckConstraint("state IN ('RUNNING','FAILED','SUCCEEDED')", name="state"),)


class QueueHead(Base):
    __tablename__ = "queue_heads"
    cohort_id: Mapped[UUID] = mapped_column(primary_key=True)
    environment: Mapped[str] = mapped_column(primary_key=True)
    queue_id: Mapped[UUID] = mapped_column(ForeignKey("queue_snapshots.id"))
    version: Mapped[int]
    __table_args__ = (CheckConstraint("version > 0", name="version"),)


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


class RegistryCandidate(Identity, Base):
    __tablename__ = "registry_candidates"
    bundle_digest: Mapped[str] = mapped_column(String(64), unique=True)
    training_run_id: Mapped[UUID]
    trainer_id: Mapped[str]
    data_tier: Mapped[str]
    registry_name: Mapped[str]
    registration_state: Mapped[str] = mapped_column(default="PENDING")
    remote_run_id: Mapped[str | None]
    remote_version: Mapped[str | None]
    model_ref_id: Mapped[UUID | None] = mapped_column(ForeignKey("model_refs.id"), unique=True)
    evidence_payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    retired: Mapped[bool] = mapped_column(default=False)
    __table_args__ = (
        CheckConstraint(
            "registration_state IN ('PENDING','IN_FLIGHT','UNCERTAIN','REGISTERED')",
            name="registration_state",
        ),
    )


class ModelDecision(Identity, Base):
    __tablename__ = "model_decisions"
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("registry_candidates.id"))
    environment: Mapped[str]
    version: Mapped[int]
    state: Mapped[str]
    actor_id: Mapped[str]
    reason_reference: Mapped[str]
    evidence_payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    request_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("candidate_id", "environment", "version"),
        UniqueConstraint("actor_id", "idempotency_key"),
        CheckConstraint(
            "state IN ('RESEARCH_DEMO','APPROVED_FOR_SHADOW','APPROVED_FOR_PILOT','REJECTED','RETIRED')",
            name="state",
        ),
    )


class ModelDeployment(Identity, Base):
    __tablename__ = "model_deployments"
    environment: Mapped[str]
    alias: Mapped[str]
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("registry_candidates.id"))
    version: Mapped[int]
    __table_args__ = (
        UniqueConstraint("environment", "alias"),
        CheckConstraint("version > 0", name="version"),
    )


class ModelPin(Base):
    __tablename__ = "model_pins"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("registry_candidates.id"))
    decision_id: Mapped[UUID] = mapped_column(ForeignKey("model_decisions.id"))
    environment: Mapped[str]
    bundle_digest: Mapped[str] = mapped_column(String(64))
    registry_version: Mapped[str]
    deployment_version: Mapped[int]


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


class IntakeRequest(Identity, Base):
    __tablename__ = "intake_requests"
    actor_id: Mapped[str]
    operation_scope: Mapped[str]
    idempotency_key: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    correlation_id: Mapped[UUID]
    original_filename: Mapped[str]
    declaration: Mapped[dict[str, object]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(default="RECEIVED")
    observed: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    batch_id: Mapped[UUID | None] = mapped_column(ForeignKey("batches.id"))
    replay_of: Mapped[UUID | None] = mapped_column(ForeignKey("intake_requests.id"))
    __table_args__ = (
        UniqueConstraint(
            "actor_id", "operation_scope", "idempotency_key", name="uq_intake_request"
        ),
        CheckConstraint(
            "state IN ('RECEIVED','VALIDATING','ACCEPTED','QUARANTINED','FAILED')", name="state"
        ),
        Index("ix_intake_state_created", "state", "created_at"),
    )


class RawPublication(Identity, Base):
    __tablename__ = "raw_publications"
    intake_id: Mapped[UUID] = mapped_column(ForeignKey("intake_requests.id"))
    kind: Mapped[str]
    digest: Mapped[str] = mapped_column(String(64))
    byte_count: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(default="STAGED")
    __table_args__ = (
        CheckConstraint("kind IN ('RAW','REPORT')", name="kind"),
        CheckConstraint("state IN ('STAGED','PUBLISHED')", name="state"),
        CheckConstraint("byte_count >= 0", name="bytes"),
        Index("ix_publication_intake", "intake_id"),
    )


class IntakeContent(Identity, Base):
    __tablename__ = "intake_contents"
    digest: Mapped[str] = mapped_column(String(64))
    access_scope: Mapped[str]
    metadata_hash: Mapped[str] = mapped_column(String(64))
    original_intake_id: Mapped[UUID] = mapped_column(ForeignKey("intake_requests.id"))
    __table_args__ = (UniqueConstraint("digest", "access_scope", name="uq_intake_content"),)


class ApiIdentity(Base):
    __tablename__ = "api_identities"
    actor_id: Mapped[str] = mapped_column(primary_key=True)
    grants: Mapped[dict[str, Any]] = mapped_column(JSONB)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    disabled: Mapped[bool] = mapped_column(default=False)


class ApiTask(Base):
    __tablename__ = "api_tasks"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    kind: Mapped[str]
    access_scope: Mapped[str]
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    authorization: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    __table_args__ = (CheckConstraint("kind IN ('intake','score','train','export')", name="kind"),)


class BatchAccess(Base):
    __tablename__ = "batch_access"
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("batches.id"), primary_key=True)
    access_scope: Mapped[str]


class QueueCase(Base):
    __tablename__ = "queue_cases"
    queue_id: Mapped[UUID] = mapped_column(ForeignKey("queue_snapshots.id"), primary_key=True)
    record_key: Mapped[str] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"), unique=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["queue_id", "record_key"], ["queue_members.queue_id", "queue_members.record_key"]
        ),
    )


class CaseNote(Identity, Base):
    __tablename__ = "case_notes"
    review_id: Mapped[UUID] = mapped_column(ForeignKey("review_events.id"), unique=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"))
    score_id: Mapped[UUID] = mapped_column(ForeignKey("score_rows.id"))
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"))


class OutcomeSubmission(Identity, Base):
    __tablename__ = "outcome_submissions"
    actor_id: Mapped[str]
    source_id: Mapped[str]
    idempotency_key: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    known_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("actor_id", "idempotency_key"),)


class OutcomeContract(Base):
    __tablename__ = "outcome_contracts"
    label_id: Mapped[UUID] = mapped_column(ForeignKey("labels.id"), primary_key=True)
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("outcome_submissions.id"))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)


class ExportRecord(Base):
    __tablename__ = "export_records"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    queue_id: Mapped[UUID] = mapped_column(ForeignKey("queue_snapshots.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    snapshot: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
