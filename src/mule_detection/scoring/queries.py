"""Pinned queue navigation and explicit unavailable assessments."""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select

from mule_detection.application.context import ExecutionContext
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.domain.contracts.common import ValueModel
from mule_detection.domain.contracts.scores import ScoreRow as ScoreDTO
from mule_detection.persistence.errors import AccessDenied
from mule_detection.persistence.models import (
    Evidence,
    QueueHead,
    QueueSnapshot,
    ScoreRow,
    ScoreRun,
    ScoringTask,
)
from mule_detection.scoring.storage import reference

if TYPE_CHECKING:
    from mule_detection.application.scoring_service import ScoringService


class AssessmentView(ValueModel):
    record_key: str
    score: ScoreDTO | None
    state_reasons: tuple[str, ...]
    opened_queue_id: UUID | None
    active_queue_id: UUID | None
    newer_assessment_available: bool
    last_complete_score_id: UUID | None


class ScoreQueries:
    def __init__(self, service: "ScoringService") -> None:
        self.service = service

    def assessment(
        self,
        cohort: UUID,
        record_key: str,
        environment: str,
        context: ExecutionContext,
        *,
        opened_queue_id: UUID | None = None,
    ) -> AssessmentView:
        if not self.service.authorize(context, "score:read"):
            raise AccessDenied()
        with unit_of_work(self.service.factory) as session:
            head = session.get(QueueHead, (cohort, environment))
            identity = opened_queue_id or (head.queue_id if head else None)
            queue = session.get(QueueSnapshot, identity) if identity else None
            row = None
            if queue:
                run = session.get(ScoreRun, queue.run_id)
                if queue.cohort_id != cohort or run is None or run.actor_id != context.actor_id:
                    raise AccessDenied()
                task = session.scalar(select(ScoringTask).where(ScoringTask.run_id == run.id))
                if task is None or task.state != "COMPLETE" or task.environment != environment:
                    raise AccessDenied()
                row = session.scalar(
                    select(ScoreRow).where(
                        ScoreRow.run_id == queue.run_id, ScoreRow.record_key == record_key
                    )
                )
            last = session.scalar(
                select(ScoreRow.id)
                .join(ScoreRun)
                .join(QueueSnapshot, QueueSnapshot.run_id == ScoreRun.id)
                .join(ScoringTask, ScoringTask.run_id == ScoreRun.id)
                .where(
                    QueueSnapshot.cohort_id == cohort,
                    ScoringTask.environment == environment,
                    ScoreRun.actor_id == context.actor_id,
                    ScoreRow.record_key == record_key,
                    ScoreRow.contract_payload["freshness"].astext == "COMPLETE",
                )
                .order_by(ScoreRow.created_at.desc())
                .limit(1)
            )
            return AssessmentView(
                record_key=record_key,
                score=ScoreDTO.model_validate(row.contract_payload) if row else None,
                state_reasons=("RESEARCH_CUTOFF_UNKNOWN",)
                if row
                else ("NO_USABLE_PUBLISHED_ASSESSMENT",),
                opened_queue_id=identity,
                active_queue_id=head.queue_id if head else None,
                newer_assessment_available=bool(head and identity and head.queue_id != identity),
                last_complete_score_id=last,
            )

    def evidence(self, score_id: UUID, context: ExecutionContext) -> dict[str, Any]:
        if not self.service.authorize(context, "score:read"):
            raise AccessDenied()
        with unit_of_work(self.service.factory) as session:
            row = session.get(ScoreRow, score_id)
            run = session.get(ScoreRun, row.run_id) if row else None
            evidence = session.scalar(select(Evidence).where(Evidence.score_id == score_id))
            task = (
                session.scalar(select(ScoringTask).where(ScoringTask.run_id == run.id))
                if run
                else None
            )
            if (
                row is None
                or run is None
                or run.actor_id != context.actor_id
                or evidence is None
                or task is None
                or task.state != "COMPLETE"
            ):
                raise AccessDenied()
            metadata: Any = evidence.structured_evidence
            identity = metadata["explanation_artifact_id"]
            facts = (
                self.service.artifacts.observation(
                    reference(session, identity), row.record_key, context
                )
                if identity
                else None
            )
            return {"score_id": str(score_id), "lineage": metadata, "facts": facts}
