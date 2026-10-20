"""Narrow PostgreSQL adapters. Flushes are allowed; commits belong to services."""

import json
from collections.abc import Sequence
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from mule_detection.persistence.artifacts import ArtifactRef
from mule_detection.persistence.errors import AccessDenied, PersistenceConflict
from mule_detection.persistence.models import (
    Artifact,
    Batch,
    Case,
    Dataset,
    Job,
    QueueMember,
    QueueSnapshot,
    ScoreRow,
    ScoreRun,
    ValidationReport,
)


def fingerprint(request: object) -> str:
    """Callers pass canonical JSON-compatible primitives, never arbitrary repr()."""
    return sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def insert_once[T: (Job, ScoreRun)](
    session: Session,
    model: type[T],
    values: dict[str, object],
    *,
    constraint: str,
    identity: dict[str, object],
    request_hash: str,
) -> T:
    """A conflict waits for the winner, then READ COMMITTED sees its committed fingerprint.

    Only the named idempotency constraint is handled. FK/check/other unique failures propagate.
    The request hash must include every immutable business parameter, computed by the service.
    """
    session.execute(insert(model).values(**values).on_conflict_do_nothing(constraint=constraint))
    record = session.scalars(select(model).filter_by(**identity)).one()
    if record.request_hash != request_hash:
        raise PersistenceConflict()
    return record


class Repositories:
    def __init__(self, session: Session) -> None:
        self.session = session

    def register_dataset(
        self,
        *,
        content_hash: str,
        raw_uri: str,
        schema_id: str,
        data_tier: str,
        row_count: int,
    ) -> Dataset:
        values = dict(
            content_hash=content_hash,
            raw_uri=raw_uri,
            schema_id=schema_id,
            data_tier=data_tier,
            row_count=row_count,
        )
        self.session.execute(
            insert(Dataset)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_datasets_content_hash")
        )
        record = self.session.scalars(
            select(Dataset).where(Dataset.content_hash == content_hash)
        ).one()
        if any(getattr(record, name) != value for name, value in values.items()):
            raise PersistenceConflict()
        return record

    def register_batch(self, *, batch_id: UUID, dataset_id: UUID, manifest_hash: str) -> Batch:
        # The manifest fingerprint includes the supplied batch identity. Handle ONLY that
        # explicit primary-key conflict; another manifest identity violation must surface.
        self.session.execute(
            insert(Batch)
            .values(
                id=batch_id,
                dataset_id=dataset_id,
                manifest_hash=manifest_hash,
            )
            .on_conflict_do_nothing(constraint="pk_batches")
        )
        record = self.session.get(Batch, batch_id)
        if (
            record is None
            or record.dataset_id != dataset_id
            or record.manifest_hash != manifest_hash
        ):
            raise PersistenceConflict()
        return record

    def get_accepted_batch(self, batch_id: UUID) -> Batch:
        batch = self.session.scalars(
            select(Batch)
            .join(ValidationReport, Batch.accepted_validation_id == ValidationReport.id)
            .where(
                Batch.id == batch_id,
                Batch.status == "ACCEPTED",
                ValidationReport.outcome == "ACCEPTED",
            )
        ).one_or_none()
        if batch is None:
            raise PersistenceConflict()
        return batch

    def case_artifact(self, case_id: UUID, scopes: frozenset[str]) -> tuple[ArtifactRef, str]:
        row = self.session.execute(
            select(Artifact, ScoreRow.record_key)
            .select_from(Case)
            .join(ScoreRow, Case.score_id == ScoreRow.id)
            .join(ScoreRun, ScoreRow.run_id == ScoreRun.id)
            .join(Artifact, ScoreRun.snapshot_id == Artifact.id)
            .where(
                Case.id == case_id, Case.access_scope.in_(scopes), Artifact.access_scope.in_(scopes)
            )
        ).one_or_none()
        if row is None:
            raise AccessDenied()
        artifact, record_key = row
        return ArtifactRef(
            artifact.digest, artifact.schema_id, artifact.row_count, artifact.access_scope
        ), record_key

    def create_run(
        self,
        *,
        actor_id: str,
        idempotency_key: UUID,
        batch_id: UUID,
        model_id: UUID,
        policy_hash: str,
        snapshot_id: UUID,
    ) -> ScoreRun:
        self.get_accepted_batch(batch_id)
        identity: dict[str, object] = {
            "actor_id": actor_id,
            "operation": "score",
            "idempotency_key": idempotency_key,
        }
        request_hash = fingerprint(
            {
                "batch_id": str(batch_id),
                "model_id": str(model_id),
                "policy_hash": policy_hash,
                "snapshot_id": str(snapshot_id),
            }
        )
        return insert_once(
            self.session,
            ScoreRun,
            {
                **identity,
                "batch_id": batch_id,
                "model_id": model_id,
                "policy_hash": policy_hash,
                "snapshot_id": snapshot_id,
                "request_hash": request_hash,
            },
            constraint="uq_run_request",
            identity=identity,
            request_hash=request_hash,
        )

    def publish_queue(self, queue: QueueSnapshot, members: Sequence[QueueMember]) -> None:
        """A service must fence its worker and append publication audit in the same UoW."""
        self.session.add(queue)
        self.session.flush()
        self.session.add_all(members)
        self.session.flush()

    def queue_page(
        self, queue_id: UUID, *, after_rank: int = 0, limit: int = 100
    ) -> list[QueueMember]:
        if after_rank < 0 or not 1 <= limit <= 500:
            raise ValueError("Invalid pagination bounds")
        return list(
            self.session.scalars(
                select(QueueMember)
                .where(QueueMember.queue_id == queue_id, QueueMember.rank > after_rank)
                .order_by(QueueMember.rank)
                .limit(limit)
            )
        )
