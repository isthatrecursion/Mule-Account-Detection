"""Bounded HTTP input contracts; callers cannot supply actors, permissions or paths."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mule_detection.domain.contracts.labels import QualifiedLabel


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Assignment(Input):
    expected_version: int = Field(ge=0, strict=True)
    assignee: str | None = Field(default=None, max_length=100)


class StartReview(Input):
    expected_version: int = Field(ge=0, strict=True)


class Review(StartReview):
    conclusion: Literal["NEEDS_MORE_INFORMATION", "NO_FURTHER_REVIEW", "REFER_FOR_ADJUDICATION"]
    note: str | None = Field(default=None, min_length=1, max_length=4000)

    @field_validator("note")
    @classmethod
    def safe_note(cls, value: str | None) -> str | None:
        if value is not None and any(ord(c) < 32 and c not in "\t\r\n" for c in value):
            raise ValueError("Unsupported control character")
        return value


class ScoreSubmission(Input):
    batch_id: UUID
    bundle_digest: str = Field(pattern="^[0-9a-f]{64}$")


class Reopen(Assignment):
    reason: str | None = Field(default=None, min_length=1, max_length=4000)

    @field_validator("reason")
    @classmethod
    def safe_reason(cls, value: str | None) -> str | None:
        return Review.safe_note(value)


class TrainingSubmission(Input):
    batch_id: UUID


class Retry(Input):
    reason: str = Field(min_length=1, max_length=200)


class ExportSubmission(Input):
    queue_version: UUID
    columns: tuple[Literal["case_id", "rank", "raw_score", "state", "record_key", "note"], ...] = (
        "case_id",
        "rank",
        "raw_score",
        "state",
    )
    state: Literal["QUEUED", "ASSIGNED", "IN_REVIEW", "REVIEWED"] | None = None
    reason: str = Field(min_length=1, max_length=200)


class OutcomeSubmission(Input):
    source_id: str = Field(min_length=1, max_length=100)
    known_as_of: datetime
    labels: tuple[QualifiedLabel, ...] = Field(min_length=1, max_length=1000)


class ErrorDetail(Input):
    code: str
    request_id: UUID


class ErrorResponse(Input):
    error: ErrorDetail


class Enqueued(Input):
    job_id: UUID
    state: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED"]


class JobView(Enqueued):
    kind: Literal["intake", "score", "train", "export"]
    created_at: datetime
    attempts: list[dict[str, Any]]
    result: dict[str, Any] | None


class BatchView(Input):
    batch_id: UUID
    state: str
    validation_id: UUID | None
    created_at: datetime


class QueueCursor(Input):
    after_rank: int
    after_key: str


class QueueItem(Input):
    case_id: UUID
    record_key: str
    rank: int
    raw_score: float | None
    state: str
    case_version: int
    assignee: str | None
    freshness: str
    percentile: float | None = None


class QueueView(Input):
    queue_version: UUID
    version: int
    total: int
    items: list[QueueItem]
    next: QueueCursor | None
    model_version: str | None = None
    bundle_digest: str | None = None
    batch_id: UUID | None = None


class CaseView(Input):
    case_id: UUID
    record_key: str
    state: str
    case_version: int
    assignee: str | None
    conclusion: str | None
    score_id: UUID
    score: dict[str, Any]
    run_id: UUID
    batch_id: UUID
    model_id: UUID
    bundle_digest: str | None
    policy_hash: str
    dictionary_version: str | None
    snapshot_id: UUID
    queue_version: UUID | None
    newer_assessment_available: bool
    newer_score_id: UUID | None


class MutationView(Input):
    event_id: UUID
    case_id: UUID
    case_version: int


class HistoryView(Input):
    items: list[dict[str, Any]]
    next: int | None


class EvidenceView(Input):
    case_id: UUID
    score_id: UUID
    dictionary_version: str
    facts: dict[str, Any] | None
    limitations: list[str]


class OutcomeView(Input):
    submission_id: UUID
    count: int


class ModelView(Input):
    model_id: UUID
    bundle_digest: str
    tier: str
    registry_version: str
