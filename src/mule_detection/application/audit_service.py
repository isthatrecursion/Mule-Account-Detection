"""Trusted server actor/time plus references only; no free-form note/row payloads."""

from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from mule_detection.application.context import ExecutionContext
from mule_detection.domain.clock import Clock, SystemClock
from mule_detection.persistence.audit_repository import AuditRepository
from mule_detection.persistence.models import AuditEvent

AUDITED_ACTIONS = frozenset(
    {
        "model:approve",
        "queue:publish",
        "case:assign",
        "case:review",
        "case:reopen",
        "case:correct",
        "export:authorize",
        "job:retry",
    }
)


class AuditService:
    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or SystemClock()

    def append(
        self,
        session: Session,
        context: ExecutionContext,
        *,
        action: str,
        entity_reference: str,
        request_hash: str,
        entity_version: int | None = None,
        before_reference: str | None = None,
        after_reference: str | None = None,
        reason_reference: str | None = None,
        idempotency_key: UUID | None = None,
    ) -> UUID:
        if action not in AUDITED_ACTIONS or not context.actor_id:
            raise ValueError("A supported action and trusted actor are required")
        event = AuditEvent(
            id=uuid4(),
            created_at=self.clock.now(),
            actor_id=context.actor_id,
            action=action,
            entity_reference=entity_reference,
            entity_version=entity_version,
            correlation_id=context.correlation_id,
            request_hash=request_hash,
            idempotency_key=idempotency_key or uuid4(),
            before_reference=before_reference,
            after_reference=after_reference,
            reason_reference=reason_reference,
        )
        AuditRepository(session).append(event)
        return event.id
