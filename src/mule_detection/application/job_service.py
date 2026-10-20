"""Transaction boundary for worker result callbacks and privileged retries."""

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from mule_detection.application.audit_service import AuditService
from mule_detection.application.context import ExecutionContext
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.persistence.errors import AccessDenied, PersistenceConflict
from mule_detection.persistence.job_repository import JobRepository, Lease
from mule_detection.persistence.models import AuditEvent, Job
from mule_detection.persistence.repositories import fingerprint

T = TypeVar("T")


class JobService:
    def __init__(self, factory: Callable[[], Session], audit: AuditService | None = None) -> None:
        self.factory = factory
        self.audit = audit or AuditService()

    def publish(
        self,
        lease: Lease,
        context: ExecutionContext,
        write_result: Callable[[Session], T],
        *,
        result_reference: str,
    ) -> T:
        with unit_of_work(self.factory) as session:

            def write() -> T:
                result = write_result(session)
                self.audit.append(
                    session,
                    context,
                    action="queue:publish",
                    entity_reference=result_reference,
                    entity_version=lease.token,
                    request_hash=fingerprint({"job": str(lease.job_id), "token": lease.token}),
                    after_reference=result_reference,
                )
                return result

            return JobRepository(session).publish(lease, write, result_reference=result_reference)

    def retry(
        self,
        job_id: UUID,
        context: ExecutionContext,
        *,
        permissions: frozenset[str],
        reason_reference: str,
        idempotency_key: UUID,
    ) -> None:
        if "job:retry" not in permissions:
            raise AccessDenied()
        with unit_of_work(self.factory) as session:
            lock_key = f"{context.actor_id}:job:retry:{idempotency_key}"
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": lock_key}
            )
            request_hash = fingerprint({"job": str(job_id), "reason": reason_reference})
            previous = session.scalar(
                select(AuditEvent).where(
                    AuditEvent.actor_id == context.actor_id,
                    AuditEvent.action == "job:retry",
                    AuditEvent.idempotency_key == idempotency_key,
                )
            )
            if previous is not None:
                if previous.request_hash != request_hash:
                    raise PersistenceConflict()
                return
            job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if job is None or job.state != "FAILED":
                raise PersistenceConflict()
            job.state = "PENDING"
            job.lease_owner = None
            job.lease_expires_at = None
            job.fencing_token += 1
            self.audit.append(
                session,
                context,
                action="job:retry",
                entity_reference=f"job:{job_id}",
                entity_version=job.fencing_token,
                reason_reference=reason_reference,
                request_hash=request_hash,
                idempotency_key=idempotency_key,
            )
