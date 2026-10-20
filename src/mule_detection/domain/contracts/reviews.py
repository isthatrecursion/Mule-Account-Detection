from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from mule_detection.domain.contracts.common import Contract, Nonnegative, Text
from mule_detection.domain.errors import DomainError, ErrorCode


class ReviewRequest(Contract):
    VERSION = "review_v1"
    contract_version: Literal["review_v1"]
    case_id: UUID
    expected_case_version: Nonnegative
    conclusion: Literal["NEEDS_MORE_INFORMATION", "NO_FURTHER_REVIEW", "REFER_FOR_ADJUDICATION"]
    note_reference: Text | None
    idempotency_key: UUID


@dataclass(frozen=True)
class AuthoredReview:
    request: ReviewRequest
    actor_id: str
    correlation_id: UUID


REVIEW_TRANSITIONS = {
    ("QUEUED", "ASSIGNED"): "case:assign",
    ("ASSIGNED", "IN_REVIEW"): "case:review",
    ("IN_REVIEW", "REVIEWED"): "case:review",
    ("REVIEWED", "ASSIGNED"): "case:reopen",
}


def validate_review_transition(current: str, target: str, permissions: frozenset[str]) -> None:
    required = REVIEW_TRANSITIONS.get((current, target))
    if required is None or required not in permissions:
        raise DomainError(ErrorCode.WORKFLOW_INVALID)
