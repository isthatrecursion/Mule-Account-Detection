"""Bounded immutable-input scoring; retries restart under a fresh fencing token."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from mule_detection.application.context import ExecutionContext
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.domain.contracts.common import canonical_hash
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.persistence.artifacts import ArtifactRef
from mule_detection.persistence.job_repository import JobRepository, Lease
from mule_detection.persistence.models import ScoreRun, ScoringChunk, ScoringTask
from mule_detection.scoring.ranking import rank_scores
from mule_detection.scoring.result_validator import collect_scores
from mule_detection.scoring.storage import frame_from_records, reference, register_artifact

if TYPE_CHECKING:
    from mule_detection.application.scoring_service import ScoringService


class ScoreWorker:
    def __init__(self, service: ScoringService) -> None:
        self.service = service

    def stage(
        self,
        task: ScoringTask,
        lease: Lease,
        context: ExecutionContext,
        *,
        fault: Callable[[str], None] | None = None,
    ) -> ArtifactRef:
        service = self.service
        manifest: Any = task.manifest
        loaded = service.loader.load(manifest["request"]["bundle_digest"], task.environment)
        callback = fault or (lambda _: None)
        for index, chunk in enumerate(manifest["input_chunks"]):
            service.verify_current(task, context)
            with unit_of_work(service.factory) as session:
                JobRepository(session).renew(lease, seconds=service.lease_seconds)
                ref = reference(session, chunk["artifact_id"])
            records = service.artifacts.records(ref, context)
            keys = tuple(chunk["keys"])
            if set(records) != set(keys):
                raise DomainError(ErrorCode.COUNT_INVALID)
            frame = frame_from_records(records, keys, manifest["signature"])
            scores = loaded.predict_score(frame)
            values = collect_scores(zip(keys, scores, strict=True), keys)
            result = service.artifacts.put(
                {k: {"raw_score": v} for k, v in values.items()},
                schema_id="score_chunk_v1",
                access_scope="research",
                context=context,
            )
            with unit_of_work(service.factory) as session:
                JobRepository(session).require_active(lease)
                identity = register_artifact(session, result)
                session.add(
                    ScoringChunk(
                        job_id=task.job_id,
                        fencing_token=lease.token,
                        chunk_index=index,
                        artifact_id=identity,
                        membership_hash=canonical_hash({"keys": list(keys)}),
                        row_count=len(keys),
                    )
                )
            callback(f"chunk:{index + 1}")
        all_scores: list[tuple[str, float]] = []
        with unit_of_work(service.factory) as session:
            JobRepository(session).require_active(lease)
            chunks = list(
                session.scalars(
                    select(ScoringChunk)
                    .where(
                        ScoringChunk.job_id == task.job_id,
                        ScoringChunk.fencing_token == lease.token,
                    )
                    .order_by(ScoringChunk.chunk_index)
                )
            )
            if len(chunks) != len(manifest["input_chunks"]):
                raise DomainError(ErrorCode.COUNT_INVALID)
            for index, chunk_row in enumerate(chunks):
                expected = manifest["input_chunks"][index]["keys"]
                if (
                    chunk_row.chunk_index != index
                    or chunk_row.row_count != len(expected)
                    or chunk_row.membership_hash != canonical_hash({"keys": expected})
                ):
                    raise DomainError(ErrorCode.COUNT_INVALID)
                stored: Any = service.artifacts.records(
                    reference(session, chunk_row.artifact_id), context
                )
                if set(stored) != set(expected):
                    raise DomainError(ErrorCode.COUNT_INVALID)
                all_scores.extend((key, stored[key]["raw_score"]) for key in expected)
            all_scores.extend((k, row["score"]) for k, row in manifest["unchanged"].items())
            run = session.get(ScoreRun, task.run_id)
            assert run is not None
            index_records: Any = service.artifacts.records(
                reference(session, run.snapshot_id), context
            )
            if set(index_records) != set(manifest["keys"]) or any(
                index_records[k]["snapshot_id"] != manifest["snapshots"][k] for k in index_records
            ):
                raise DomainError(ErrorCode.LINEAGE_INVALID)
        scores = collect_scores(all_scores, tuple(manifest["keys"]))
        ranked = rank_scores(scores, service.policy)
        selected = [row["record_key"] for row in ranked if row["selected"]]
        by_snapshot: dict[str, list[str]] = {}
        for key in selected:
            by_snapshot.setdefault(manifest["snapshots"][key], []).append(key)
        explanation_refs: dict[str, str] = {}
        for snapshot, group_keys in by_snapshot.items():
            with unit_of_work(service.factory) as session:
                JobRepository(session).renew(lease, seconds=service.lease_seconds)
                ref = reference(session, snapshot)
            source: Any = service.artifacts.records(ref, context)
            for start in range(0, len(group_keys), service.chunk_rows):
                part = tuple(group_keys[start : start + service.chunk_rows])
                explanation = loaded.explain(
                    frame_from_records(source, part, manifest["signature"])
                )
                if len(explanation["evidence"]) != len(part) or len(explanation["scores"]) != len(
                    part
                ):
                    raise DomainError(ErrorCode.COUNT_INVALID)
                evidence = {}
                for key, score, value in zip(
                    part, explanation["scores"], explanation["evidence"], strict=True
                ):
                    if not math.isclose(score, scores[key], abs_tol=1e-12, rel_tol=0):
                        raise DomainError(ErrorCode.LINEAGE_INVALID)
                    evidence[key] = {
                        **value,
                        "snapshot_id": snapshot,
                        "bundle_digest": manifest["request"]["bundle_digest"],
                        "feature_policy_hash": manifest["feature_policy_hash"],
                        "dictionary_version": manifest["dictionary_version"],
                    }
                artifact = service.artifacts.put(
                    evidence,
                    schema_id="contribution_evidence_v1",
                    access_scope="research",
                    context=context,
                )
                with unit_of_work(service.factory) as session:
                    JobRepository(session).require_active(lease)
                    identity = register_artifact(session, artifact)
                explanation_refs.update({key: str(identity) for key in part})
                callback("evidence")
        prepared = {
            row["record_key"]: {
                **row,
                "snapshot_id": manifest["snapshots"][row["record_key"]],
                "baseline_score_id": manifest["parent_rows"]
                .get(row["record_key"], {})
                .get("score_id"),
                "explanation_artifact_id": explanation_refs.get(row["record_key"]),
                "bundle_digest": manifest["request"]["bundle_digest"],
                "fencing_token": lease.token,
            }
            for row in ranked
        }
        callback("ranked")
        result = service.artifacts.put(
            prepared, schema_id="ranked_result_v1", access_scope="research", context=context
        )
        with unit_of_work(service.factory) as session:
            JobRepository(session).require_active(lease)
            register_artifact(session, result)
        return result
