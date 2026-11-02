"""Display vocabulary follows the API; unknown future values remain explicit."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Self


class DisplayEnum(StrEnum):
    @classmethod
    def _missing_(cls, value: object) -> Self:
        return cls("UNKNOWN")

    @property
    def presentation(self) -> "Presentation":
        return Presentation(
            self.value.replace("_", " ").capitalize(),
            EXPLANATIONS.get(self.value, "The server has not supplied a recognized status."),
            "neutral" if self.value == "UNKNOWN" else "attention",
            "[" + self.value + "]",
        )


@dataclass(frozen=True)
class Presentation:
    label: str
    explanation: str
    color_token: str
    marker: str


class Freshness(DisplayEnum):
    COMPLETE = "COMPLETE"
    BUFFERING = "BUFFERING"
    PROVISIONAL_HIGHER = "PROVISIONAL_HIGHER"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class PublicationEvent(DisplayEnum):
    # These are separate from freshness in score_v1, not additional freshness states.
    RECONCILED = "RECONCILED"
    CORRECTED = "CORRECTED"
    UNKNOWN = "UNKNOWN"


class CaseState(DisplayEnum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    IN_REVIEW = "IN_REVIEW"
    REVIEWED = "REVIEWED"
    UNKNOWN = "UNKNOWN"


class JobState(DisplayEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class IngestionStatus(DisplayEnum):
    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class DataTier(DisplayEnum):
    RESEARCH = "research"
    QUALIFIED = "qualified"
    SYNTHETIC = "synthetic"
    UNKNOWN = "UNKNOWN"


class ModelTier(DisplayEnum):
    RESEARCH = "research_demo"
    CANDIDATE = "candidate"
    UNKNOWN = "UNKNOWN"


class DictionaryStatus(DisplayEnum):
    UNVERIFIED = "UNVERIFIED"
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    UNKNOWN = "UNKNOWN"


EXPLANATIONS = {
    "COMPLETE": "Required source coverage is complete for the stated assessment time.",
    "BUFFERING": "Incomplete source data is awaiting reconciliation.",
    "PROVISIONAL_HIGHER": "Incomplete data produced a separate provisional escalation.",
    "STALE": "The retained assessment keeps its original cutoff; freshness is not established.",
    "UNAVAILABLE": "No usable complete assessment is available; no score is implied.",
    "RECONCILED": "A later publication reconciles previously incomplete source data.",
    "CORRECTED": "A later publication corrects earlier evidence; history is retained.",
    "QUEUED": "The case is waiting for assignment.",
    "ASSIGNED": "An analyst is assigned; review has not started.",
    "IN_REVIEW": "The assigned analyst is reviewing this assessment.",
    "REVIEWED": "A workflow conclusion was recorded; it does not create an outcome label.",
    "PENDING": "The durable job is waiting for a worker.",
    "RUNNING": "A worker is processing the durable job.",
    "SUCCEEDED": "The job completed; inspect its separate validation or publication result.",
    "FAILED": "The job failed; inspect the safe error and permitted recovery action.",
    "RECEIVED": "The intake request has been received.",
    "VALIDATING": "The batch is being checked against its source contract.",
    "ACCEPTED": "The batch passed the applicable intake gate.",
    "QUARANTINED": "The batch requires correction or investigation before use.",
    "REJECTED": "The intake request was rejected by the applicable gate.",
    "research": "Research demonstrations require the stated limitations to remain visible.",
    "research_demo": "The model is a research demonstration, not deployment approval.",
    "candidate": "The model is a candidate; this tier does not imply approval.",
    "qualified": "This server-declared tier does not itself grant deployment approval.",
    "synthetic": "Generated fixtures contain no real account records.",
    "UNVERIFIED": "The field's business meaning has not been verified.",
    "PROVISIONAL": "The proposed field meaning is awaiting certification.",
    "CERTIFIED": "The dictionary reports a certified field meaning.",
}
