from typing import Literal
from uuid import UUID

from mule_detection.domain.contracts.common import Contract, Text, UtcTime
from mule_detection.domain.errors import DomainError, ErrorCode


class Job(Contract):
    VERSION = "job_v1"
    contract_version: Literal["job_v1"]
    job_id: UUID
    correlation_id: UUID
    actor_id: Text
    state: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED"]
    created_at: UtcTime
    data_tier: Literal["research", "qualified", "synthetic"]


JOB_TRANSITIONS = frozenset(
    {("PENDING", "RUNNING"), ("RUNNING", "SUCCEEDED"), ("RUNNING", "FAILED")}
)


def validate_job_transition(current: str, target: str) -> None:
    if (current, target) not in JOB_TRANSITIONS:
        raise DomainError(ErrorCode.WORKFLOW_INVALID)
