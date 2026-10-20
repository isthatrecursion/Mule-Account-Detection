"""Immutable execution identity, propagated to later service and job calls."""

from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass(frozen=True)
class ExecutionContext:
    actor_id: str
    environment: str
    correlation_id: UUID

    @classmethod
    def create(cls, actor_id: str, environment: str) -> "ExecutionContext":
        return cls(actor_id=actor_id, environment=environment, correlation_id=uuid4())
