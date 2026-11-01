"""Lifecycle authorization belongs to the operational control plane."""

from typing import Literal

from mule_detection.domain.errors import DomainError, ErrorCode

ModelState = Literal[
    "CANDIDATE", "RESEARCH_DEMO", "APPROVED_FOR_SHADOW", "APPROVED_FOR_PILOT", "REJECTED", "RETIRED"
]
TRANSITIONS: dict[str, frozenset[str]] = {
    "CANDIDATE": frozenset({"RESEARCH_DEMO", "APPROVED_FOR_SHADOW", "REJECTED", "RETIRED"}),
    "RESEARCH_DEMO": frozenset({"REJECTED", "RETIRED"}),
    "APPROVED_FOR_SHADOW": frozenset({"APPROVED_FOR_PILOT", "REJECTED", "RETIRED"}),
    "APPROVED_FOR_PILOT": frozenset({"REJECTED", "RETIRED"}),
    "REJECTED": frozenset(),
    "RETIRED": frozenset(),
}


def require_transition(current: str, target: str, *, trainer: str, reviewer: str) -> None:
    if target not in TRANSITIONS.get(current, frozenset()):
        raise DomainError(ErrorCode.WORKFLOW_INVALID)
    if target in {"APPROVED_FOR_SHADOW", "APPROVED_FOR_PILOT"} and trainer == reviewer:
        raise DomainError(ErrorCode.CONTRACT_INVALID)
