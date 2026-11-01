"""UI-owned HTTP contracts; no backend package is imported into the frontend.

Names mirror api_openapi_v1.json. Opaque JSON subdocuments remain explicitly typed
as mappings where OpenAPI does not yet specify their full schema.
"""

from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from ui.enums import (
    CaseState,
    DataTier,
    DictionaryStatus,
    Freshness,
    IngestionStatus,
    JobState,
    ModelTier,
    PublicationEvent,
)
from ui.errors import ContractError

Finite = Annotated[float, Field(allow_inf_nan=False)]
Nonnegative = Annotated[int, Field(ge=0, strict=True)]


class Response(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class Request(Response):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Me(Response):
    actor_id: str = Field(min_length=1)
    roles: list[str]
    permissions: list[str]
    scopes: list[str]
    permission_scopes: dict[str, list[str]]
    role_scopes: dict[str, list[str]] = Field(default_factory=dict)
    expires_at: int = Field(strict=True)


class QueueVersionInfo(Response):
    queue_version: UUID
    cohort_id: UUID
    version: Nonnegative
    published_at: AwareDatetime | None = None


class QueueVersions(Response):
    items: list[QueueVersionInfo]


class QueueCursor(Response):
    after_rank: Nonnegative
    after_key: str


class QueueRow(Response):
    case_id: UUID
    record_key: str
    rank: Annotated[int, Field(ge=1, strict=True)] | None
    raw_score: Finite | None
    percentile: Annotated[Finite, Field(ge=0, le=100)] | None = None
    state: CaseState
    case_version: Nonnegative
    assignee: str | None
    freshness: Freshness

    @model_validator(mode="after")
    def score_state(self) -> Self:
        check_score(self.freshness, self.raw_score, self.rank, self.percentile)
        return self


class QueuePage(Response):
    queue_version: UUID
    version: Nonnegative
    total: Nonnegative
    items: list[QueueRow]
    next: QueueCursor | None
    model_version: str | None = None
    bundle_digest: str | None = None
    batch_id: UUID | None = None


def check_score(
    freshness: Freshness, score: float | None, rank: int | None, percentile: float | None
) -> None:
    if freshness == Freshness.UNAVAILABLE:
        if any(v is not None for v in (score, rank, percentile)):
            raise ValueError("Unavailable assessments cannot carry a score or rank")
    elif freshness != Freshness.UNKNOWN and (score is None or rank is None):
        raise ValueError("Published ranked assessments require score and rank")


class ScoreVersion(Response):
    data_tier: DataTier
    raw_score: Finite | None
    rank: Annotated[int, Field(ge=1, strict=True)] | None
    percentile: Annotated[Finite, Field(ge=0, le=100)] | None
    freshness: Freshness
    completeness: str
    assessed_as_of: AwareDatetime | None
    published_at: AwareDatetime | None = None
    source_coverage: list[dict[str, Any]] = Field(default_factory=list)
    publication_event: PublicationEvent | None = None
    baseline_score_id: UUID | None = None
    provenance_limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def score_state(self) -> Self:
        check_score(self.freshness, self.raw_score, self.rank, self.percentile)
        if self.freshness == Freshness.UNAVAILABLE and self.completeness == "COMPLETE":
            raise ValueError("An unavailable assessment cannot claim complete coverage")
        if self.freshness == Freshness.UNAVAILABLE and any(
            value is not None
            for value in (
                self.assessed_as_of,
                self.published_at,
                self.publication_event,
                self.baseline_score_id,
            )
        ):
            raise ValueError("An unavailable assessment cannot claim a published assessment")
        if self.assessed_as_of and self.published_at and self.assessed_as_of > self.published_at:
            raise ValueError("Assessment cutoff cannot follow publication")
        return self


class CaseDetail(Response):
    case_id: UUID
    record_key: str
    state: CaseState
    case_version: Nonnegative
    assignee: str | None
    conclusion: str | None
    score_id: UUID
    score: ScoreVersion
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


class Contribution(Response):
    raw_feature: str
    observed_value: Any = None
    value_status: str | None = None
    meaning_status: DictionaryStatus = DictionaryStatus.UNVERIFIED
    contribution: Finite
    reference_percentile: Finite | None = None
    category_frequency: Finite | None = None
    unseen_category: bool | None = None
    encoded_detail: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceFacts(Response):
    scale: str
    base_value: Finite
    raw_margin: Finite
    raw_aggregates: list[Contribution]
    encoded_detail: list[dict[str, Any]] = Field(default_factory=list)


class EvidencePayload(Response):
    case_id: UUID
    score_id: UUID
    dictionary_version: str
    facts: EvidenceFacts | None
    limitations: list[str]


class HistoryItem(Response):
    # History is a mixed API collection: score, review and audit shapes differ.
    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)
    created_at: AwareDatetime | None = None
    event_id: UUID | None = None
    score_id: UUID | None = None
    action: str | None = None
    note: str | None = Field(default=None, repr=False)


class HistoryPage(Response):
    items: list[HistoryItem]
    next: Nonnegative | None


class Enqueued(Response):
    job_id: UUID
    state: JobState


class JobStatus(Enqueued):
    kind: str
    created_at: AwareDatetime
    attempts: list[dict[str, Any]]
    result: dict[str, Any] | None


class BatchStatus(Response):
    batch_id: UUID
    state: IngestionStatus
    validation_id: UUID | None
    created_at: AwareDatetime


class Mutation(Response):
    event_id: UUID
    case_id: UUID
    case_version: Nonnegative


class Health(Response):
    state: str


class ModelInfo(Response):
    model_id: UUID
    bundle_digest: str
    tier: ModelTier
    registry_version: str


class VersionedRequest(Request):
    expected_version: Nonnegative


class AssignmentRequest(VersionedRequest):
    assignee: str | None = Field(default=None, max_length=100)


CONCLUSIONS = ("NEEDS_MORE_INFORMATION", "NO_FURTHER_REVIEW", "REFER_FOR_ADJUDICATION")


class ReviewRequest(VersionedRequest):
    # This closed list is published in the saved OpenAPI Review schema.
    conclusion: Literal["NEEDS_MORE_INFORMATION", "NO_FURTHER_REVIEW", "REFER_FOR_ADJUDICATION"]
    note: str | None = Field(default=None, min_length=1, max_length=4000, repr=False)

    @model_validator(mode="after")
    def control_characters(self) -> Self:
        if self.note and any(ord(c) < 32 and c not in "\t\r\n" for c in self.note):
            raise ValueError("Unsupported control character")
        return self


class ReopenRequest(AssignmentRequest):
    reason: str | None = Field(default=None, min_length=1, max_length=4000, repr=False)

    @model_validator(mode="after")
    def control_characters(self) -> Self:
        if self.reason and any(ord(c) < 32 and c not in "\t\r\n" for c in self.reason):
            raise ValueError("Unsupported control character")
        return self


class ScoreSubmission(Request):
    batch_id: UUID
    bundle_digest: str = Field(pattern="^[0-9a-f]{64}$")


class TrainingSubmission(Request):
    batch_id: UUID


class RetryRequest(Request):
    reason: str = Field(min_length=1, max_length=200, repr=False)


class ExportRequest(Request):
    queue_version: UUID
    columns: tuple[Literal["case_id", "rank", "raw_score", "state", "record_key", "note"], ...] = (
        "case_id",
        "rank",
        "raw_score",
        "state",
    )
    state: Literal["QUEUED", "ASSIGNED", "IN_REVIEW", "REVIEWED"] | None = None
    reason: str = Field(min_length=1, max_length=200, repr=False)


def parse[T: BaseModel](model: type[T], value: object, request_id: str | None = None) -> T:
    try:
        return model.model_validate(value)
    except (ValidationError, ValueError, TypeError):
        raise ContractError(request_id) from None
