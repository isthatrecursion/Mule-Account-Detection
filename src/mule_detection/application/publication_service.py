"""Fence, revalidate, CAS the queue head and publish all business effects atomically."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import func, select, text

from mule_detection.application.audit_service import AuditService
from mule_detection.application.context import ExecutionContext
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.domain.contracts.scores import ScoreRow as ScoreDTO
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.persistence.artifacts import ArtifactRef
from mule_detection.persistence.errors import PersistenceConflict
from mule_detection.persistence.job_repository import JobRepository, Lease
from mule_detection.persistence.models import (
    Evidence,
    QueueHead,
    QueueMember,
    QueueSnapshot,
    ScoreRow,
    ScoringAttempt,
    ScoringTask,
)
from mule_detection.scoring.ranking import rank_scores
from mule_detection.scoring.result_validator import validate_scores
from mule_detection.scoring.storage import reference

if TYPE_CHECKING:
    from mule_detection.application.scoring_service import ScoringService


class PublicationService:
    def __init__(self, scoring: ScoringService) -> None:
        self.scoring = scoring

    def publish(
        self,
        task: ScoringTask,
        lease: Lease,
        prepared: ArtifactRef,
        context: ExecutionContext,
        *,
        fault: Callable[[str], None] | None = None,
    ) -> dict[str, str]:
        service = self.scoring
        service._authority(context, task.environment, correction=bool(task.manifest["correction"]))
        callback = fault or (lambda _: None)
        manifest: Any = task.manifest
        if prepared.schema_id != "ranked_result_v1" or prepared.access_scope != "research":
            raise DomainError(ErrorCode.LINEAGE_INVALID)
        callback("before_publish")
        # Authenticate staged scores and evidence before holding publication locks.
        rows: Any = service.artifacts.records(prepared, context)
        scores = {key: row["raw_score"] for key, row in rows.items()}
        validate_scores(scores, tuple(manifest["keys"]))
        canonical = rank_scores(scores, service.policy)
        with unit_of_work(service.factory) as session:
            from mule_detection.domain.contracts.common import canonical_hash
            from mule_detection.persistence.models import ScoringChunk

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
            staged_scores = {key: value["score"] for key, value in manifest["unchanged"].items()}
            for index, chunk in enumerate(chunks):
                expected_keys = manifest["input_chunks"][index]["keys"]
                values: Any = service.artifacts.records(
                    reference(session, chunk.artifact_id), context
                )
                if (
                    chunk.chunk_index != index
                    or chunk.row_count != len(expected_keys)
                    or chunk.membership_hash != canonical_hash({"keys": expected_keys})
                    or set(values) != set(expected_keys)
                    or set(values) & set(staged_scores)
                ):
                    raise DomainError(ErrorCode.COUNT_INVALID)
                staged_scores.update({key: value["raw_score"] for key, value in values.items()})
            if staged_scores != scores:
                raise DomainError(ErrorCode.LINEAGE_INVALID)
            cache: dict[str, Any] = {}
            for expected in canonical:
                key = expected["record_key"]
                row = rows[key]
                if (
                    any(row.get(name) != value for name, value in expected.items())
                    or row.get("fencing_token") != lease.token
                    or row.get("bundle_digest") != manifest["request"]["bundle_digest"]
                    or row.get("snapshot_id") != manifest["snapshots"][key]
                ):
                    raise DomainError(ErrorCode.LINEAGE_INVALID)
                if expected["selected"]:
                    identity = row.get("explanation_artifact_id")
                    if not identity:
                        raise DomainError(ErrorCode.LINEAGE_INVALID)
                    if identity not in cache:
                        cache[identity] = service.artifacts.records(
                            reference(session, identity), context
                        )
                    evidence = cache[identity][key]
                    if (
                        evidence["snapshot_id"] != row["snapshot_id"]
                        or evidence["bundle_digest"] != row["bundle_digest"]
                        or evidence["feature_policy_hash"] != manifest["feature_policy_hash"]
                        or evidence["dictionary_version"] != manifest["dictionary_version"]
                        or evidence["scale"] != "raw_margin"
                        or canonical_hash(
                            {
                                "features": [
                                    {k: v[k] for k in ("index", "name", "raw_feature")}
                                    for v in evidence["encoded_detail"]
                                ]
                            }
                        )
                        != manifest["transformed_signature"]
                        or any(
                            v["display_name"] != v["raw_feature"]
                            or v["meaning_status"] != "UNVERIFIED"
                            for v in evidence["raw_aggregates"]
                        )
                        or not math.isclose(
                            sum(v["contribution"] for v in evidence["encoded_detail"]),
                            sum(v["contribution"] for v in evidence["raw_aggregates"]),
                            abs_tol=1e-8,
                            rel_tol=1e-8,
                        )
                        or not math.isclose(
                            evidence["base_value"]
                            + sum(v["contribution"] for v in evidence["raw_aggregates"]),
                            evidence["raw_margin"],
                            abs_tol=1e-8,
                            rel_tol=1e-8,
                        )
                    ):
                        raise DomainError(ErrorCode.LINEAGE_INVALID)
        with unit_of_work(service.factory) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"queue:{task.cohort_id}:{task.environment}"},
            )
            repository = JobRepository(session)
            repository.require_active(lease)
            current = session.get(ScoringTask, task.job_id)
            if current is None or current.state != "STAGED" or current.manifest != task.manifest:
                raise PersistenceConflict()
            service.verify_current(current, context, session)
            head = session.get(QueueHead, (task.cohort_id, task.environment))
            if (head.queue_id if head else None) != task.predecessor_queue_id:
                raise PersistenceConflict()
            now = session.scalar(select(func.clock_timestamp()))
            version = head.version + 1 if head else 1
            queue_id = uuid4()
            queue = QueueSnapshot(
                id=queue_id,
                run_id=task.run_id,
                cohort_id=task.cohort_id,
                policy_hash=service.policy.digest,
                published_version=version,
                published_at=now,
            )
            # Child FK insertion follows a flush of score/queue parent identities.
            session.add(queue)
            score_rows = []
            evidences = []
            members = []
            for key, row in rows.items():
                score_id = uuid5(NAMESPACE_URL, f"score:{task.run_id}:{key}")
                dto = ScoreDTO(
                    contract_version="score_v1",
                    run_id=task.run_id,
                    record_key=key,
                    snapshot_id=UUID(row["snapshot_id"]),
                    bundle_id=UUID(manifest["bundle_id"]),
                    data_tier="research",
                    raw_score=float(row["raw_score"]),
                    rank=row["rank"],
                    percentile=float(row["percentile"]),
                    cohort_id=task.cohort_id,
                    evidence_reference=f"score-evidence:{score_id}",
                    assessed_as_of=None,
                    published_at=now,
                    source_coverage=(),
                    completeness="UNKNOWN",
                    freshness="STALE",
                    publication_event="CORRECTED"
                    if manifest["correction"]
                    else "RECONCILED"
                    if task.parent_run_id
                    else None,
                    baseline_score_id=UUID(row["baseline_score_id"])
                    if row["baseline_score_id"]
                    else None,
                    provenance_limitations=(
                        "RESEARCH_OBSERVATION_AND_AVAILABILITY_CUTOFF_UNKNOWN",
                        "COHORT_CONFOUNDING",
                        "IN_SAMPLE_DEMONSTRATION",
                    ),
                )
                score_rows.append(
                    ScoreRow(
                        id=score_id,
                        run_id=task.run_id,
                        record_key=key,
                        raw_score=float(row["raw_score"]),
                        contract_payload=dto.model_dump(mode="json"),
                    )
                )
                evidences.append(
                    Evidence(
                        score_id=score_id,
                        dictionary_version=manifest["dictionary_version"],
                        structured_evidence={
                            "evidence_version": "factual_contributions_v1",
                            "bundle_digest": row["bundle_digest"],
                            "feature_policy_hash": manifest["feature_policy_hash"],
                            "review_policy_hash": service.policy.digest,
                            "sort_policy": service.policy.sort_version,
                            "cohort_size": len(rows),
                            "snapshot_id": row["snapshot_id"],
                            "explanation_artifact_id": row["explanation_artifact_id"],
                            "explanation_status": "AVAILABLE"
                            if row["selected"]
                            else "NOT_SELECTED_FOR_EXPLANATION",
                            "source_score_id": row["baseline_score_id"],
                            "reconciliation_event_id": manifest["request"]["replay_id"],
                            "output_scale": "review_priority",
                            "meaning_status": "UNVERIFIED",
                        },
                    )
                )
                if row["selected"]:
                    members.append(
                        QueueMember(
                            queue_id=queue_id,
                            record_key=key,
                            rank=row["rank"],
                            score_id=score_id,
                            run_id=task.run_id,
                        )
                    )
            session.add_all(score_rows)
            session.flush()
            session.add_all(evidences)
            session.add_all(members)
            if head:
                head.queue_id, head.version = queue_id, version
            else:
                session.add(
                    QueueHead(
                        cohort_id=task.cohort_id,
                        environment=task.environment,
                        queue_id=queue_id,
                        version=version,
                    )
                )
            current.state = "COMPLETE"
            attempt = session.get(ScoringAttempt, (task.job_id, lease.token))
            if attempt is None:
                raise DomainError(ErrorCode.LINEAGE_INVALID)
            attempt.state = "SUCCEEDED"
            AuditService().append(
                session,
                context,
                action="queue:publish",
                entity_reference=f"queue:{queue_id}",
                entity_version=version,
                request_hash=prepared.digest,
                before_reference=str(task.predecessor_queue_id)
                if task.predecessor_queue_id
                else None,
                after_reference=f"run:{task.run_id}",
                reason_reference="CORRECTION"
                if manifest["correction"]
                else "COMPLETE_RESEARCH_RANKING",
            )
            callback("before_commit")
            repository.publish(lease, lambda: None, result_reference=f"queue:{queue_id}")
        callback("after_commit")
        return service.result(task.job_id, context)
