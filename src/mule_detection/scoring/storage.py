"""Authorized encrypted artifacts and deterministic metadata identities."""

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pandas as pd  # type: ignore[import-untyped]
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.persistence.artifacts import ArtifactRef
from mule_detection.persistence.models import Artifact


def register_artifact(session: Session, ref: ArtifactRef) -> UUID:
    identity = uuid5(NAMESPACE_URL, "scoring-artifact:" + ref.digest)
    session.execute(
        insert(Artifact)
        .values(
            id=identity,
            digest=ref.digest,
            uri=ref.uri,
            schema_id=ref.schema_id,
            row_count=ref.row_count,
            access_scope=ref.access_scope,
        )
        .on_conflict_do_nothing(constraint="uq_artifacts_digest")
    )
    from sqlalchemy import select

    existing = session.scalar(select(Artifact).where(Artifact.digest == ref.digest))
    if (
        existing is None
        or existing.schema_id != ref.schema_id
        or existing.row_count != ref.row_count
        or existing.access_scope != ref.access_scope
        or existing.uri != ref.uri
    ):
        raise DomainError(ErrorCode.LINEAGE_INVALID)
    return existing.id


def reference(session: Session, identity: UUID | str) -> ArtifactRef:
    row = session.get(Artifact, UUID(str(identity)))
    if row is None:
        raise DomainError(ErrorCode.LINEAGE_INVALID)
    return ArtifactRef(row.digest, row.schema_id, row.row_count, row.access_scope)


def records_from_frame(frame: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    clean = frame.astype(object).where(pd.notna(frame), None)
    return dict(zip(keys, clean.to_dict(orient="records"), strict=True))


def frame_from_records(
    records: dict[str, Any], keys: tuple[str, ...], signature: list[dict[str, str]]
) -> Any:
    frame = pd.DataFrame([records[key] for key in keys], columns=[s["name"] for s in signature])
    for item in signature:
        column = item["name"]
        frame[column] = (
            frame[column].astype(object)
            if item["kind"] == "categorical"
            else pd.to_numeric(frame[column]).astype(float)
        )
    return frame
