"""Conservative recovery: publish tracked objects; delete only aged, unreferenced staging."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from mule_detection.application.audit_service import AuditService
from mule_detection.application.context import ExecutionContext
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.persistence.models import IntakeRequest, RawPublication
from mule_detection.persistence.raw_store import RawStore, StagedRaw
from mule_detection.persistence.repositories import fingerprint


class IntakeRecovery:
    def __init__(self, factory: Callable[[], Session], store: RawStore) -> None:
        self.factory = factory
        self.store = store

    def run(
        self,
        context: ExecutionContext,
        *,
        apply: bool = False,
        delete_orphans: bool = False,
        retention_seconds: int = 86400,
    ) -> dict[str, int]:
        if context.environment not in {"local", "test", "research"} or retention_seconds < 3600:
            raise ValueError("Local recovery requires at least one hour retention")
        cutoff = datetime.now(UTC) - timedelta(seconds=retention_seconds)
        counts = {"recoverable": 0, "published": 0, "abandoned": 0, "orphans": 0, "removed": 0}
        with unit_of_work(self.factory) as session:
            pending = list(
                session.scalars(
                    select(RawPublication)
                    .join(IntakeRequest)
                    .where(
                        RawPublication.state == "STAGED",
                        RawPublication.created_at < cutoff,
                        IntakeRequest.actor_id == context.actor_id,
                    )
                )
            )
            objects = [(p.id, p.digest, p.byte_count) for p in pending]
        for identity, digest, byte_count in objects:
            counts["recoverable"] += 1
            if apply:
                self.store.finalize(StagedRaw(identity, digest, byte_count))
                with unit_of_work(self.factory) as session:
                    publication = session.get(RawPublication, identity)
                    assert publication is not None
                    publication.state = "PUBLISHED"
                    AuditService().append(
                        session,
                        context,
                        action="intake:recover",
                        entity_reference=f"publication:{identity}",
                        request_hash=digest,
                    )
                self.store.discard_stage(identity)
                counts["published"] += 1
        with unit_of_work(self.factory) as session:
            abandoned = list(
                session.scalars(
                    select(IntakeRequest)
                    .where(
                        IntakeRequest.actor_id == context.actor_id,
                        IntakeRequest.created_at < cutoff,
                        IntakeRequest.state.in_(["RECEIVED", "VALIDATING"]),
                    )
                    .with_for_update()
                )
            )
            counts["abandoned"] = len(abandoned)
            if apply:
                for intake in abandoned:
                    intake.state = "FAILED"
                    AuditService().append(
                        session,
                        context,
                        action="intake:recover",
                        entity_reference=f"intake:{intake.id}",
                        request_hash=intake.request_hash,
                    )
        for path in (self.store.root / "staging").glob("*.part"):
            try:
                identity = UUID(path.stem)
            except ValueError:
                continue
            if datetime.fromtimestamp(path.stat().st_mtime, UTC) >= cutoff:
                continue
            with unit_of_work(self.factory) as session:
                # Include all actors' records, not merely those visible to this operator.
                receipt = session.get(IntakeRequest, identity)
                if session.get(RawPublication, identity) or (
                    receipt
                    and (
                        receipt.state not in {"FAILED", "QUARANTINED"}
                        or receipt.actor_id != context.actor_id
                    )
                ):
                    continue
                counts["orphans"] += 1
                if apply and delete_orphans:
                    self.store.discard_stage(identity)
                    AuditService().append(
                        session,
                        context,
                        action="intake:cleanup",
                        entity_reference=f"staging:{identity}",
                        request_hash=fingerprint({"retention": retention_seconds}),
                    )
                    counts["removed"] += 1
        return counts
