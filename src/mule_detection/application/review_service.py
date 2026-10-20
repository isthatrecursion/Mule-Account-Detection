"""Transactional workflow mutations. Authentication supplies context/permissions/scopes later."""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from mule_detection.application.audit_service import AuditService
from mule_detection.application.context import ExecutionContext
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.domain.contracts.reviews import ReviewRequest, validate_review_transition
from mule_detection.persistence.errors import AccessDenied, PersistenceConflict
from mule_detection.persistence.models import Case, ReviewEvent
from mule_detection.persistence.repositories import fingerprint


@dataclass(frozen=True)
class ReviewResult:
    event_id: UUID
    case_id: UUID
    case_version: int


class ReviewService:
    def __init__(self, factory: Callable[[], Session], audit: AuditService | None = None) -> None:
        self.factory = factory
        self.audit = audit or AuditService()

    def review(
        self,
        request: ReviewRequest,
        context: ExecutionContext,
        *,
        permissions: frozenset[str],
        scopes: frozenset[str],
    ) -> ReviewResult:
        return self.transition(
            case_id=request.case_id,
            expected_version=request.expected_case_version,
            target="REVIEWED",
            idempotency_key=request.idempotency_key,
            context=context,
            permissions=permissions,
            scopes=scopes,
            conclusion=request.conclusion,
            note_reference=request.note_reference,
        )

    def transition(
        self,
        *,
        case_id: UUID,
        expected_version: int,
        target: str,
        idempotency_key: UUID,
        context: ExecutionContext,
        permissions: frozenset[str],
        scopes: frozenset[str],
        conclusion: str | None = None,
        note_reference: str | None = None,
        assignee: str | None = None,
    ) -> ReviewResult:
        operation = {
            "ASSIGNED": "case:assign",
            "IN_REVIEW": "case:review",
            "REVIEWED": "case:review",
        }.get(target)
        if operation is None or not context.actor_id:
            raise AccessDenied()
        if target == "REVIEWED" and conclusion not in {
            "NEEDS_MORE_INFORMATION",
            "NO_FURTHER_REVIEW",
            "REFER_FOR_ADJUDICATION",
        }:
            raise ValueError("A supported conclusion is required")
        if target != "REVIEWED" and conclusion is not None:
            raise ValueError("A conclusion belongs only to a review")
        request_hash = fingerprint(
            {
                "case_id": str(case_id),
                "expected_version": expected_version,
                "target": target,
                "conclusion": conclusion,
                "note_reference": note_reference,
                "assignee": assignee,
            }
        )
        with unit_of_work(self.factory) as session:
            # Serialize this idempotency scope before changing the case. Hash collisions only wait.
            lock_key = f"{context.actor_id}:case:transition:{idempotency_key}"
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": lock_key}
            )
            case = session.get(Case, case_id)
            if case is None or case.access_scope not in scopes:
                raise AccessDenied()
            previous = session.scalars(
                select(ReviewEvent).where(
                    ReviewEvent.actor_id == context.actor_id,
                    ReviewEvent.operation == "case:transition",
                    ReviewEvent.idempotency_key == idempotency_key,
                )
            ).one_or_none()
            if previous is not None:
                if previous.request_hash != request_hash:
                    raise PersistenceConflict()
                # Replay never grants access after scope/permission revocation.
                required = previous.action
                if required not in permissions:
                    raise AccessDenied()
                return ReviewResult(previous.id, previous.case_id, previous.case_version)
            if case.version != expected_version:
                raise PersistenceConflict()
            validate_review_transition(case.state, target, permissions)
            if case.state == "REVIEWED":
                operation = "case:reopen"
            changed = session.execute(
                update(Case)
                .where(
                    Case.id == case_id,
                    Case.version == expected_version,
                    Case.state == case.state,
                    Case.access_scope.in_(scopes),
                )
                .values(
                    state=target,
                    version=Case.version + 1,
                    conclusion=conclusion,
                    assignee=assignee if target == "ASSIGNED" else case.assignee,
                )
                .returning(Case.version)
            ).scalar_one_or_none()
            if changed is None:
                raise PersistenceConflict()
            event = self.append_review(
                session,
                case_id=case_id,
                case_version=changed,
                actor_id=context.actor_id,
                operation="case:transition",
                action=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                target_state=target,
                conclusion=conclusion,
                note_reference=note_reference,
            )
            self.audit.append(
                session,
                context,
                action=operation,
                entity_reference=f"case:{case_id}",
                entity_version=changed,
                request_hash=request_hash,
                before_reference=f"case:{case_id}:v{expected_version}",
                after_reference=f"review:{event.id}",
                reason_reference=note_reference,
            )
            result = ReviewResult(event.id, case_id, changed)
        return result

    @staticmethod
    def append_review(session: Session, **values: object) -> ReviewEvent:
        event = ReviewEvent(id=uuid4(), **values)
        session.add(event)
        session.flush()
        return event
