from typing import Literal, Self
from uuid import UUID

from pydantic import Field, StrictFloat, model_validator

from mule_detection.domain.contracts.common import Contract, Positive, Text, UtcTime, violation
from mule_detection.domain.contracts.snapshot import SourceCoverage
from mule_detection.domain.errors import ErrorCode


class ScoreRow(Contract):
    VERSION = "score_v1"
    contract_version: Literal["score_v1"]
    run_id: UUID
    record_key: Text
    snapshot_id: UUID
    bundle_id: UUID
    data_tier: Literal["research", "qualified", "synthetic"]
    raw_score: StrictFloat | None
    rank: Positive | None
    percentile: StrictFloat | None = Field(ge=0, le=100)
    cohort_id: UUID | None
    evidence_reference: Text | None
    assessed_as_of: UtcTime | None
    published_at: UtcTime | None
    source_coverage: tuple[SourceCoverage, ...]
    completeness: Literal["COMPLETE", "INCOMPLETE", "UNKNOWN"]
    freshness: Literal["COMPLETE", "BUFFERING", "PROVISIONAL_HIGHER", "STALE", "UNAVAILABLE"]
    publication_event: Literal["RECONCILED", "CORRECTED"] | None
    baseline_score_id: UUID | None
    provenance_limitations: tuple[Text, ...]

    @model_validator(mode="after")
    def score_rules(self) -> Self:
        if self.freshness == "UNAVAILABLE":
            if (
                any(
                    value is not None
                    for value in (
                        self.raw_score,
                        self.rank,
                        self.percentile,
                        self.assessed_as_of,
                        self.published_at,
                        self.cohort_id,
                        self.evidence_reference,
                        self.baseline_score_id,
                        self.publication_event,
                    )
                )
                or self.completeness == "COMPLETE"
            ):
                raise violation(ErrorCode.SCORE_STATE_INVALID)
            return self
        if any(
            value is None
            for value in (
                self.raw_score,
                self.rank,
                self.percentile,
                self.cohort_id,
                self.published_at,
                self.evidence_reference,
            )
        ):
            raise violation(ErrorCode.SCORE_STATE_INVALID)
        if self.assessed_as_of is None:
            if (
                self.data_tier != "research"
                or not self.provenance_limitations
                or self.freshness != "STALE"
                or self.completeness != "UNKNOWN"
            ):
                raise violation(ErrorCode.SCORE_STATE_INVALID)
        elif self.published_at and self.assessed_as_of > self.published_at:
            raise violation(ErrorCode.SCORE_STATE_INVALID)
        if self.freshness == "COMPLETE" and (
            self.completeness != "COMPLETE"
            or not self.source_coverage
            or any(
                c.status != "COMPLETE" or c.window_end != self.assessed_as_of
                for c in self.source_coverage
            )
        ):
            raise violation(ErrorCode.SCORE_STATE_INVALID)
        if self.freshness == "PROVISIONAL_HIGHER" and (
            self.completeness != "INCOMPLETE" or self.baseline_score_id is None
        ):
            raise violation(ErrorCode.SCORE_STATE_INVALID)
        return self
