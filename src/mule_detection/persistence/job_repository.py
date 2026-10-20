"""Database-clock leases. Publication holds the job lock through the business transaction."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypeVar
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from mule_detection.persistence.errors import LeaseLost
from mule_detection.persistence.models import Job, JobAttempt
from mule_detection.persistence.repositories import fingerprint, insert_once

T = TypeVar("T")


@dataclass(frozen=True)
class Lease:
    job_id: UUID
    owner: str
    token: int
    expires_at: datetime


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, *, actor_id: str, operation: str, idempotency_key: UUID, request: object
    ) -> Job:
        request_hash = fingerprint(request)
        identity: dict[str, object] = {
            "actor_id": actor_id,
            "operation": operation,
            "idempotency_key": idempotency_key,
        }
        return insert_once(
            self.session,
            Job,
            {**identity, "request_hash": request_hash},
            constraint="uq_job_request",
            identity=identity,
            request_hash=request_hash,
        )

    @staticmethod
    def _duration(seconds: int) -> timedelta:
        if not 1 <= seconds <= 3600:
            raise ValueError("Lease duration must be between 1 and 3600 seconds")
        return timedelta(seconds=seconds)

    def acquire(self, job_id: UUID, owner: str, *, seconds: int = 60) -> Lease:
        if not owner:
            raise ValueError("Lease owner is required")
        duration = self._duration(seconds)
        row = self.session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                or_(
                    Job.state == "PENDING",
                    and_(
                        Job.state == "RUNNING",
                        Job.lease_expires_at <= func.clock_timestamp(),
                    ),
                ),
            )
            .values(
                state="RUNNING",
                lease_owner=owner,
                lease_expires_at=func.clock_timestamp() + duration,
                fencing_token=Job.fencing_token + 1,
            )
            .returning(Job.fencing_token, Job.lease_expires_at)
        ).one_or_none()
        if row is None:
            raise LeaseLost()
        self.session.add(JobAttempt(job_id=job_id, fencing_token=row[0], owner=owner))
        self.session.flush()
        return Lease(job_id, owner, row[0], row[1])

    def renew(self, lease: Lease, *, seconds: int = 60) -> Lease:
        duration = self._duration(seconds)
        expiry = self.session.execute(
            update(Job)
            .where(
                Job.id == lease.job_id,
                Job.state == "RUNNING",
                Job.lease_owner == lease.owner,
                Job.fencing_token == lease.token,
                Job.lease_expires_at > func.clock_timestamp(),
            )
            .values(lease_expires_at=func.clock_timestamp() + duration)
            .returning(Job.lease_expires_at)
        ).scalar_one_or_none()
        if expiry is None:
            raise LeaseLost()
        return Lease(lease.job_id, lease.owner, lease.token, expiry)

    def require_active(self, lease: Lease) -> Job:
        # Lock first, then read wall time. A waiter must not validate against a pre-lock timestamp.
        job = self.session.scalars(
            select(Job)
            .where(Job.id == lease.job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        now = self.session.scalar(select(func.clock_timestamp()))
        if (
            job is None
            or job.state != "RUNNING"
            or job.lease_owner != lease.owner
            or job.fencing_token != lease.token
            or job.lease_expires_at is None
            or now is None
            or job.lease_expires_at <= now
        ):
            raise LeaseLost()
        return job

    def publish(self, lease: Lease, write_result: Callable[[], T], *, result_reference: str) -> T:
        """Callback writes only through this session, never external effects/commits.

        Outer UoW rolls back all result writes if the final lease validation fails.
        A replacement cannot acquire until this transaction releases the job row lock.
        """
        self.require_active(lease)
        result = write_result()
        self.session.flush()
        job = self.require_active(lease)
        job.state = "SUCCEEDED"
        job.result_reference = result_reference
        job.lease_owner = None
        job.lease_expires_at = None
        self.session.flush()
        return result
