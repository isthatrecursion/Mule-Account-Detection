"""Resolve database-authorized immutable identities and pin them to durable jobs."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from mule_detection.application.audit_service import AuditService
from mule_detection.application.context import ExecutionContext
from mule_detection.application.model_approval_service import latest_decision
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.persistence.errors import AccessDenied, PersistenceConflict
from mule_detection.persistence.models import Job, ModelDeployment, ModelPin, RegistryCandidate
from mule_detection.registry.bundle_loader import BundleLoader
from mule_detection.registry.mlflow_adapter import RegistryBackend


def eligible(session: Session, candidate: RegistryCandidate, environment: str) -> Any:
    decision = latest_decision(session, candidate.id, environment)
    permitted = (
        {"RESEARCH_DEMO"}
        if environment in {"local", "test", "research"}
        else {"APPROVED_FOR_SHADOW", "APPROVED_FOR_PILOT"}
        if environment in {"staging", "qualified"}
        else set()
    )
    if (
        candidate.retired
        or candidate.registration_state != "REGISTERED"
        or decision is None
        or decision.state not in permitted
    ):
        raise DomainError(ErrorCode.CONTRACT_INVALID)
    if environment in {"staging", "qualified"} and candidate.data_tier != "qualified":
        raise DomainError(ErrorCode.CONTRACT_INVALID)
    return decision


class ModelResolver:
    def __init__(
        self,
        factory: Callable[[], Session],
        backend: RegistryBackend,
        authorize: Callable[[ExecutionContext, str], bool],
    ) -> None:
        self.factory, self.backend, self.authorize = factory, backend, authorize

    def authorized(self, digest: str, environment: str) -> bool:
        with unit_of_work(self.factory) as session:
            candidate = session.scalar(
                select(RegistryCandidate).where(RegistryCandidate.bundle_digest == digest)
            )
            if candidate is None:
                return False
            try:
                eligible(session, candidate, environment)
            except DomainError:
                return False
            return True

    def deploy(
        self,
        candidate_id: UUID,
        environment: str,
        alias: str,
        context: ExecutionContext,
        *,
        expected_version: int,
        reason: str,
        loader: BundleLoader,
        rollback: bool = False,
    ) -> int:
        if (
            not self.authorize(context, "model:deploy")
            or not reason.strip()
            or (
                environment in {"staging", "qualified"}
                and context.environment not in {"staging", "qualified"}
            )
        ):
            raise AccessDenied()
        # Fixture health before changing the future-selection pointer.
        with unit_of_work(self.factory) as session:
            candidate = session.get(RegistryCandidate, candidate_id)
            if candidate is None:
                raise DomainError(ErrorCode.LINEAGE_INVALID)
            eligible(session, candidate, environment)
            digest = candidate.bundle_digest
        loader.load(digest, environment)
        with unit_of_work(self.factory) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"deploy:{environment}:{alias}"},
            )
            candidate = session.scalar(
                select(RegistryCandidate)
                .where(RegistryCandidate.id == candidate_id)
                .with_for_update()
            )
            assert candidate is not None
            eligible(session, candidate, environment)
            current = session.scalar(
                select(ModelDeployment)
                .where(ModelDeployment.environment == environment, ModelDeployment.alias == alias)
                .with_for_update()
            )
            if (current.version if current else 0) != expected_version:
                raise PersistenceConflict()
            previous = str(current.candidate_id) if current else None
            if current:
                current.candidate_id = candidate_id
                current.version += 1
            else:
                current = ModelDeployment(
                    environment=environment, alias=alias, candidate_id=candidate_id, version=1
                )
                session.add(current)
            AuditService().append(
                session,
                context,
                action="model:rollback" if rollback else "model:deploy",
                entity_reference=f"deployment:{environment}:{alias}",
                entity_version=current.version,
                request_hash=digest,
                before_reference=previous,
                after_reference=str(candidate_id),
                reason_reference=reason,
            )
            version = current.version
        # External alias is a recoverable mirror; failures do not undo the audited
        # authoritative DB selection. reconcile_alias can repair it idempotently.
        self.reconcile_alias(environment, alias, context)
        return version

    def reconcile_alias(self, environment: str, alias: str, context: ExecutionContext) -> None:
        if not self.authorize(context, "model:deploy") or (
            environment in {"staging", "qualified"}
            and context.environment not in {"staging", "qualified"}
        ):
            raise AccessDenied()
        with unit_of_work(self.factory) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"deploy:{environment}:{alias}"},
            )
            deployment = session.scalar(
                select(ModelDeployment).where(
                    ModelDeployment.environment == environment, ModelDeployment.alias == alias
                )
            )
            if deployment is None:
                raise DomainError(ErrorCode.LINEAGE_INVALID)
            candidate = session.get(RegistryCandidate, deployment.candidate_id)
            assert candidate is not None
            eligible(session, candidate, environment)
            self.backend.set_alias(
                candidate.registry_name, environment + "-" + alias, str(candidate.remote_version)
            )
            AuditService().append(
                session,
                context,
                action="model:alias_reconcile",
                entity_reference=f"deployment:{environment}:{alias}",
                entity_version=deployment.version,
                request_hash=candidate.bundle_digest,
                after_reference=f"registry:{candidate.registry_name}/{candidate.remote_version}",
                reason_reference="DB_AUTHORITY_RECONCILIATION",
            )

    def pin(
        self, job_id: UUID, environment: str, alias: str, context: ExecutionContext
    ) -> ModelPin:
        if not self.authorize(context, "model:resolve"):
            raise AccessDenied()
        with unit_of_work(self.factory) as session:
            job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if job is None or job.actor_id != context.actor_id:
                raise AccessDenied()
            previous = session.get(ModelPin, job_id)
            if previous:
                if previous.environment != environment:
                    raise PersistenceConflict()
                candidate = session.get(RegistryCandidate, previous.candidate_id)
                assert candidate is not None
                eligible(session, candidate, environment)
                return previous
            deployment = session.scalar(
                select(ModelDeployment).where(
                    ModelDeployment.environment == environment, ModelDeployment.alias == alias
                )
            )
            if deployment is None:
                raise DomainError(ErrorCode.LINEAGE_INVALID)
            candidate = session.get(RegistryCandidate, deployment.candidate_id)
            assert candidate is not None
            decision = eligible(session, candidate, environment)
            pin = ModelPin(
                job_id=job_id,
                candidate_id=candidate.id,
                decision_id=decision.id,
                environment=environment,
                bundle_digest=candidate.bundle_digest,
                registry_version=str(candidate.remote_version),
                deployment_version=deployment.version,
            )
            session.add(pin)
            session.flush()
            return pin

    def revalidate(self, session: Session, job_id: UUID) -> ModelPin:
        """Call inside Phase 8's publication transaction; lock retirement/decision scope."""
        pin = session.get(ModelPin, job_id)
        if pin is None:
            raise DomainError(ErrorCode.LINEAGE_INVALID)
        candidate = session.scalar(
            select(RegistryCandidate)
            .where(RegistryCandidate.id == pin.candidate_id)
            .with_for_update()
        )
        if (
            candidate is None
            or candidate.bundle_digest != pin.bundle_digest
            or candidate.remote_version != pin.registry_version
        ):
            raise DomainError(ErrorCode.LINEAGE_INVALID)
        eligible(session, candidate, pin.environment)
        return pin
