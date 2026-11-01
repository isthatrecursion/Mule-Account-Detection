"""Independent append-only approval, using a separately provisioned DB identity."""

from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from mule_detection.application.audit_service import AuditService
from mule_detection.application.context import ExecutionContext
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.domain.contracts.common import canonical_hash
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.domain.model_lifecycle import require_transition
from mule_detection.persistence.errors import AccessDenied
from mule_detection.persistence.models import ModelDecision, RegistryCandidate
from mule_detection.registry.promotion_policy import PromotionEvidence, promotion_gate


def latest_decision(session: Session, candidate_id: UUID, environment: str) -> ModelDecision | None:
    return session.scalar(
        select(ModelDecision)
        .where(ModelDecision.candidate_id == candidate_id, ModelDecision.environment == environment)
        .order_by(ModelDecision.version.desc())
        .limit(1)
    )


class ModelApprovalService:
    def __init__(
        self, factory: Callable[[], Session], authorize: Callable[[ExecutionContext, str], bool]
    ) -> None:
        self.factory, self.authorize = factory, authorize

    def decide(
        self,
        candidate_id: UUID,
        environment: str,
        target: str,
        context: ExecutionContext,
        *,
        reason: str,
        idempotency_key: UUID,
    ) -> UUID:
        if not self.authorize(context, "model:approve"):
            raise AccessDenied()
        if not reason.strip():
            raise DomainError(ErrorCode.CONTRACT_INVALID)
        request_hash = canonical_hash(
            {
                "candidate": str(candidate_id),
                "environment": environment,
                "target": target,
                "reason": reason,
            }
        )
        with unit_of_work(self.factory) as session:
            candidate = session.scalar(
                select(RegistryCandidate)
                .where(RegistryCandidate.id == candidate_id)
                .with_for_update()
            )
            if candidate is None or candidate.registration_state != "REGISTERED":
                raise DomainError(ErrorCode.LINEAGE_INVALID)
            previous_request = session.scalar(
                select(ModelDecision).where(
                    ModelDecision.actor_id == context.actor_id,
                    ModelDecision.idempotency_key == idempotency_key,
                )
            )
            if previous_request:
                if previous_request.request_hash != request_hash:
                    raise DomainError(ErrorCode.IDENTITY_CONFLICT)
                return previous_request.id
            if candidate.retired:
                raise DomainError(ErrorCode.WORKFLOW_INVALID)
            previous = latest_decision(session, candidate_id, environment)
            require_transition(
                previous.state if previous else "CANDIDATE",
                target,
                trainer=candidate.trainer_id,
                reviewer=context.actor_id,
            )
            evidence = PromotionEvidence.model_validate(candidate.evidence_payload["promotion"])
            gate = promotion_gate(
                evidence, digest=candidate.bundle_digest, environment=environment, target=target
            )
            if gate["status"] != "PASSED":
                raise DomainError(ErrorCode.CONTRACT_INVALID)
            decision = ModelDecision(
                candidate_id=candidate_id,
                environment=environment,
                version=previous.version + 1 if previous else 1,
                state=target,
                actor_id=context.actor_id,
                reason_reference=reason,
                evidence_payload=gate,
                request_hash=request_hash,
                idempotency_key=idempotency_key,
            )
            session.add(decision)
            session.flush()
            if target in {"REJECTED", "RETIRED"}:
                candidate.retired = True
            AuditService().append(
                session,
                context,
                action="model:approve",
                entity_reference=f"candidate:{candidate_id}",
                entity_version=decision.version,
                request_hash=request_hash,
                reason_reference=reason,
                idempotency_key=idempotency_key,
            )
            return decision.id
