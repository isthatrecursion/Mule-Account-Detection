"""Scoped application boundary shared by HTTP and separately started durable workers."""

from __future__ import annotations

import csv
import io
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO, cast
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, text, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from mule_detection.api.auth import Principal
from mule_detection.api.dto import ExportSubmission, OutcomeSubmission
from mule_detection.application.audit_service import AuditService
from mule_detection.application.context import ExecutionContext
from mule_detection.application.review_service import ReviewResult, ReviewService
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.domain.contracts.labels import QualifiedLabel, select_label_as_of
from mule_detection.persistence.artifacts import ArtifactStore
from mule_detection.persistence.errors import AccessDenied, PersistenceConflict
from mule_detection.persistence.job_repository import JobRepository
from mule_detection.persistence.models import (
    ApiIdentity,
    ApiTask,
    AuditEvent,
    Batch,
    BatchAccess,
    Case,
    CaseNote,
    Evidence,
    ExportRecord,
    Job,
    JobAttempt,
    Label,
    ModelRef,
    OutcomeContract,
    QueueCase,
    QueueHead,
    QueueMember,
    QueueSnapshot,
    ReviewEvent,
    ScoreRow,
    ScoreRun,
)
from mule_detection.persistence.models import (
    OutcomeSubmission as Submission,
)
from mule_detection.persistence.raw_store import RawStore
from mule_detection.persistence.repositories import fingerprint
from mule_detection.scoring.storage import reference, register_artifact
from mule_detection.settings import Settings


class NotFound(Exception):
    pass


class ApiService:
    def __init__(
        self,
        settings: Settings,
        factory: Callable[[], Session],
        artifacts: ArtifactStore,
        raw: RawStore,
        *,
        policy_hash: str,
        sources: dict[str, str],
        handlers: dict[str, Callable[..., dict[str, Any]]] | None = None,
        outcome_sources: dict[str, dict[str, Any]] | None = None,
        evidence_store: ArtifactStore | None = None,
    ) -> None:
        self.settings, self.factory, self.artifacts, self.raw = settings, factory, artifacts, raw
        self.policy_hash, self.sources = policy_hash, sources
        self.handlers = handlers or {}
        self.outcome_sources = outcome_sources or {}
        self.evidence_store = evidence_store or artifacts

    def context(self, principal: Principal, correlation: UUID | None = None) -> ExecutionContext:
        return ExecutionContext(
            principal.actor_id, self.settings.environment, correlation or uuid4()
        )

    def remember(self, principal: Principal) -> None:
        # A disabled identity cannot re-enable itself. Only verified grants are refreshed.
        with unit_of_work(self.factory) as session:
            session.execute(
                insert(ApiIdentity)
                .values(
                    actor_id=principal.actor_id,
                    grants=principal.payload(),
                    valid_until=datetime.fromtimestamp(principal.expires_at, UTC),
                    disabled=False,
                )
                .on_conflict_do_update(
                    index_elements=[ApiIdentity.actor_id],
                    set_={
                        "grants": principal.payload(),
                        "valid_until": datetime.fromtimestamp(principal.expires_at, UTC),
                    },
                )
            )
            identity = session.get(ApiIdentity, principal.actor_id)
            if identity is None or identity.disabled:
                raise AccessDenied()

    def ready(self) -> bool:
        try:
            with self.factory() as session:
                if session.scalar(text("SELECT version_num FROM alembic_version")) != "0009":
                    return False
                session.scalar(text("SELECT 1"))
            for root in (self.raw.root / "staging", self.artifacts.root, self.evidence_store.root):
                probe = root / f"ready-{uuid4()}"
                nonce = os.urandom(12)
                try:
                    with probe.open("xb") as stream:
                        stream.write(self.raw.cipher.encrypt(nonce, b"readiness", b"ready"))
                        stream.flush()
                        os.fsync(stream.fileno())
                    if self.raw.cipher.decrypt(nonce, probe.read_bytes(), b"ready") != b"readiness":
                        return False
                finally:
                    probe.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    @staticmethod
    def case_in(session: Session, identity: UUID, principal: Principal) -> Case:
        case = session.scalar(
            select(Case).where(Case.id == identity, Case.access_scope.in_(principal.scopes))
        )
        if case is None:
            raise NotFound()
        return case

    @staticmethod
    def batch_in(session: Session, identity: UUID, principal: Principal) -> tuple[Batch, str]:
        row = session.execute(
            select(Batch, BatchAccess.access_scope)
            .join(BatchAccess, BatchAccess.batch_id == Batch.id)
            .where(Batch.id == identity, BatchAccess.access_scope.in_(principal.scopes))
        ).one_or_none()
        if row is None:
            raise NotFound()
        return row[0], row[1]

    @staticmethod
    def queue_in(
        session: Session, identity: UUID, principal: Principal
    ) -> tuple[QueueSnapshot, str]:
        row = session.execute(
            select(QueueSnapshot, BatchAccess.access_scope)
            .join(ScoreRun, ScoreRun.id == QueueSnapshot.run_id)
            .join(BatchAccess, BatchAccess.batch_id == ScoreRun.batch_id)
            .where(QueueSnapshot.id == identity, BatchAccess.access_scope.in_(principal.scopes))
        ).one_or_none()
        if row is None:
            raise NotFound()
        return row[0], row[1]

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        scope: str,
        principal: Principal,
        key: UUID,
        correlation: UUID,
    ) -> dict[str, Any]:
        permission = {
            "intake": "batch:intake",
            "score": "score:submit",
            "train": "train:submit",
            "export": "export:create",
        }[kind]
        principal.require(permission)
        if scope not in principal.for_permission(permission).scopes:
            raise AccessDenied()
        with unit_of_work(self.factory) as session:
            job = JobRepository(session).create(
                actor_id=principal.actor_id,
                operation="api:" + kind,
                idempotency_key=key,
                request=payload,
            )
            if session.get(ApiTask, job.id) is None:
                session.add(
                    ApiTask(
                        job_id=job.id,
                        kind=kind,
                        access_scope=scope,
                        request=payload,
                        authorization={
                            "principal": principal.payload(),
                            "policy_hash": self.policy_hash,
                        },
                        result=None,
                    )
                )
                AuditService().append(
                    session,
                    self.context(principal, correlation),
                    action="api:enqueue",
                    entity_reference=f"job:{job.id}",
                    request_hash=job.request_hash,
                    idempotency_key=uuid4(),
                )
            return {"job_id": str(job.id), "state": job.state}

    def upload(
        self,
        stream: BinaryIO,
        declaration: dict[str, Any],
        filename: str,
        principal: Principal,
        key: UUID,
        correlation: UUID,
    ) -> dict[str, Any]:
        from mule_detection.ingestion.intake import safe_filename

        principal.require("batch:intake")
        principal = principal.for_permission("batch:intake")
        manifest = declaration.get("manifest", {})
        scope = (
            self.sources.get(str(manifest.get("source_id"))) if isinstance(manifest, dict) else None
        )
        if scope is None or scope not in principal.scopes:
            raise AccessDenied()
        name = safe_filename(filename)
        stage_id = uuid4()
        try:
            staged = self.raw.stage(stream, stage_id=stage_id)
            self.raw.finalize(staged)
        finally:
            self.raw.discard_stage(stage_id)
        return self.enqueue(
            "intake",
            {"digest": staged.digest, "declaration": declaration, "filename": name},
            scope,
            principal,
            key,
            correlation,
        )

    def submit_model_work(
        self, kind: str, payload: dict[str, Any], principal: Principal, key: UUID, correlation: UUID
    ) -> dict[str, Any]:
        principal = principal.for_permission("score:submit" if kind == "score" else "train:submit")
        with self.factory() as session:
            batch, scope = self.batch_in(session, UUID(payload["batch_id"]), principal)
            if batch.status != "ACCEPTED":
                raise PersistenceConflict()
        return self.enqueue(kind, payload, scope, principal, key, correlation)

    def batch(self, identity: UUID, principal: Principal) -> dict[str, Any]:
        principal.require("batch:read")
        principal = principal.for_permission("batch:read")
        with self.factory() as session:
            batch, _ = self.batch_in(session, identity, principal)
            return {
                "batch_id": str(batch.id),
                "state": batch.status,
                "validation_id": str(batch.accepted_validation_id)
                if batch.accepted_validation_id
                else None,
                "created_at": batch.created_at,
            }

    def job(self, identity: UUID, principal: Principal) -> dict[str, Any]:
        with self.factory() as session:
            job, task = self.job_in(session, identity, principal)
            attempts = session.execute(
                select(JobAttempt.fencing_token, JobAttempt.created_at)
                .where(JobAttempt.job_id == job.id)
                .order_by(JobAttempt.fencing_token.desc())
                .limit(20)
            ).all()
            return {
                "job_id": str(job.id),
                "state": job.state,
                "kind": task.kind,
                "created_at": job.created_at,
                "attempts": [{"attempt": a, "started_at": b} for a, b in attempts],
                "result": task.result,
            }

    @staticmethod
    def job_in(session: Session, identity: UUID, principal: Principal) -> tuple[Job, ApiTask]:
        row = session.execute(
            select(Job, ApiTask)
            .join(ApiTask, ApiTask.job_id == Job.id)
            .where(Job.id == identity, ApiTask.access_scope.in_(principal.scopes))
        ).one_or_none()
        if row is None:
            raise NotFound()
        job, task = row
        permission = {
            "intake": "batch:read",
            "score": "job:read",
            "train": "job:read",
            "export": "export:create",
        }[task.kind]
        principal.require(permission)
        if task.access_scope not in principal.for_permission(permission).scopes:
            raise NotFound()
        if job.actor_id != principal.actor_id and "job:read" not in principal.permissions:
            raise NotFound()
        return job, task

    def retry(
        self, identity: UUID, principal: Principal, key: UUID, reason: str, correlation: UUID
    ) -> dict[str, Any]:
        principal.require("job:retry")
        principal = principal.for_permission("job:retry")
        with unit_of_work(self.factory) as session:
            job, task = self.job_in(session, identity, principal)
            locked_job = session.scalar(select(Job).where(Job.id == job.id).with_for_update())
            assert locked_job is not None
            job = locked_job
            # A retry may refresh only the original actor's still-allowed work.
            if job.actor_id != principal.actor_id:
                raise AccessDenied()
            required = {
                "intake": "batch:intake",
                "score": "score:submit",
                "train": "train:submit",
                "export": "export:create",
            }[task.kind]
            principal.require(required)
            digest = fingerprint({"job_id": str(identity), "reason": reason})
            previous = session.scalar(
                select(AuditEvent).where(
                    AuditEvent.actor_id == principal.actor_id,
                    AuditEvent.action == "job:retry",
                    AuditEvent.idempotency_key == key,
                )
            )
            if previous:
                if previous.request_hash != digest:
                    raise PersistenceConflict()
                return {"job_id": str(identity), "state": job.state}
            if job.state != "FAILED":
                raise PersistenceConflict()
            task.authorization = {"principal": principal.payload(), "policy_hash": self.policy_hash}
            job.state, job.result_reference = "PENDING", None
            job.fencing_token += 1
            AuditService().append(
                session,
                self.context(principal, correlation),
                action="job:retry",
                entity_reference=f"job:{identity}",
                request_hash=digest,
                idempotency_key=key,
                reason_reference="reason:sha256:" + fingerprint(reason),
            )
            return {"job_id": str(identity), "state": job.state}

    def queues(self, principal: Principal) -> dict[str, Any]:
        principal.require("queue:read")
        principal = principal.for_permission("queue:read")
        with self.factory() as session:
            rows = session.execute(
                select(QueueHead, QueueSnapshot)
                .join(QueueSnapshot, QueueSnapshot.id == QueueHead.queue_id)
                .join(ScoreRun, ScoreRun.id == QueueSnapshot.run_id)
                .join(BatchAccess, BatchAccess.batch_id == ScoreRun.batch_id)
                .where(
                    BatchAccess.access_scope.in_(principal.scopes),
                    QueueHead.environment == self.settings.environment,
                )
                .order_by(QueueHead.cohort_id)
                .limit(100)
            )
            return {
                "items": [
                    {
                        "queue_version": str(q.id),
                        "cohort_id": str(h.cohort_id),
                        "version": h.version,
                        "published_at": q.published_at,
                    }
                    for h, q in rows
                ]
            }

    def materialize(self, session: Session, queue_id: UUID, scope: str) -> None:
        # One case per immutable selected assessment. Never repoint an opened case.
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "api:queue:" + str(queue_id)},
        )
        members = session.scalars(select(QueueMember).where(QueueMember.queue_id == queue_id)).all()
        for member in members:
            if session.get(QueueCase, (queue_id, member.record_key)) is None:
                case = Case(
                    id=uuid4(),
                    subject_key=member.record_key,
                    score_id=member.score_id,
                    access_scope=scope,
                    state="QUEUED",
                    version=0,
                )
                session.add(case)
                session.flush()
                session.add(
                    QueueCase(queue_id=queue_id, record_key=member.record_key, case_id=case.id)
                )
        session.flush()

    def queue(
        self,
        identity: UUID,
        principal: Principal,
        limit: int = 50,
        after_rank: int | None = None,
        after_key: str | None = None,
        state: str | None = None,
        assignee: str | None = None,
    ) -> dict[str, Any]:
        principal.require("queue:read")
        principal = principal.for_permission("queue:read")
        with unit_of_work(self.factory) as session:
            queue, scope = self.queue_in(session, identity, principal)
            self.materialize(session, identity, scope)
            query = (
                select(QueueMember, Case, ScoreRow)
                .join(
                    QueueCase,
                    (QueueCase.queue_id == QueueMember.queue_id)
                    & (QueueCase.record_key == QueueMember.record_key),
                )
                .join(Case, Case.id == QueueCase.case_id)
                .join(ScoreRow, ScoreRow.id == QueueMember.score_id)
                .where(QueueMember.queue_id == identity, Case.access_scope.in_(principal.scopes))
            )
            if state:
                query = query.where(Case.state == state)
            if assignee:
                query = query.where(Case.assignee == assignee)
            count = session.scalar(select(func.count()).select_from(query.subquery()))
            if after_rank is not None and after_key is not None:
                query = query.where(
                    or_(
                        QueueMember.rank > after_rank,
                        (QueueMember.rank == after_rank) & (QueueMember.record_key > after_key),
                    )
                )
            rows = session.execute(
                query.order_by(QueueMember.rank, QueueMember.record_key).limit(limit + 1)
            ).all()
            page = rows[:limit]
            run = session.get(ScoreRun, queue.run_id)
            model = session.get(ModelRef, run.model_id) if run else None
            return {
                "queue_version": str(identity),
                "version": queue.published_version,
                "model_version": model.registry_version if model else None,
                "bundle_digest": model.bundle_digest if model else None,
                "batch_id": str(run.batch_id) if run else None,
                "total": count,
                "items": [
                    {
                        "case_id": str(c.id),
                        "record_key": m.record_key,
                        "rank": m.rank,
                        "raw_score": s.raw_score,
                        "state": c.state,
                        "case_version": c.version,
                        "assignee": c.assignee,
                        "freshness": s.contract_payload.get("freshness", "UNAVAILABLE"),
                        "percentile": s.contract_payload.get("percentile"),
                    }
                    for m, c, s in page
                ],
                "next": {"after_rank": page[-1][0].rank, "after_key": page[-1][0].record_key}
                if len(rows) > limit
                else None,
            }

    def case(self, identity: UUID, principal: Principal) -> dict[str, Any]:
        principal.require("case:read")
        principal = principal.for_permission("case:read")
        with self.factory() as session:
            case = self.case_in(session, identity, principal)
            score = session.get(ScoreRow, case.score_id)
            assert score is not None
            run = session.get(ScoreRun, score.run_id)
            assert run is not None
            model = session.get(ModelRef, run.model_id)
            evidence = session.scalar(select(Evidence).where(Evidence.score_id == score.id))
            opened = session.scalar(
                select(QueueSnapshot)
                .join(QueueCase, QueueCase.queue_id == QueueSnapshot.id)
                .where(QueueCase.case_id == identity)
            )
            latest = None
            if opened:
                latest = session.scalar(
                    select(ScoreRow.id)
                    .join(QueueMember, QueueMember.score_id == ScoreRow.id)
                    .join(QueueSnapshot, QueueSnapshot.id == QueueMember.queue_id)
                    .join(ScoreRun, ScoreRun.id == QueueSnapshot.run_id)
                    .join(BatchAccess, BatchAccess.batch_id == ScoreRun.batch_id)
                    .where(
                        QueueSnapshot.cohort_id == opened.cohort_id,
                        QueueSnapshot.published_version > opened.published_version,
                        ScoreRow.record_key == case.subject_key,
                        BatchAccess.access_scope.in_(principal.scopes),
                    )
                    .order_by(QueueSnapshot.published_version.desc())
                    .limit(1)
                )
            payload = score.contract_payload
            safe = {
                key: payload.get(key)
                for key in (
                    "data_tier",
                    "raw_score",
                    "rank",
                    "percentile",
                    "assessed_as_of",
                    "published_at",
                    "source_coverage",
                    "completeness",
                    "freshness",
                    "publication_event",
                    "baseline_score_id",
                    "provenance_limitations",
                )
            }
            return {
                "case_id": str(case.id),
                "record_key": case.subject_key,
                "state": case.state,
                "case_version": case.version,
                "assignee": case.assignee,
                "conclusion": case.conclusion,
                "score_id": str(score.id),
                "score": safe,
                "run_id": str(run.id),
                "batch_id": str(run.batch_id),
                "model_id": str(run.model_id),
                "bundle_digest": model.bundle_digest if model else None,
                "policy_hash": run.policy_hash,
                "dictionary_version": evidence.dictionary_version if evidence else None,
                "snapshot_id": payload.get("snapshot_id", str(run.snapshot_id)),
                "queue_version": str(opened.id) if opened else None,
                "newer_assessment_available": latest is not None,
                "newer_score_id": str(latest) if latest else None,
            }

    def evidence(self, identity: UUID, principal: Principal, correlation: UUID) -> dict[str, Any]:
        principal.require("case:read")
        principal = principal.for_permission("case:read")
        with self.factory() as session:
            case = self.case_in(session, identity, principal)
            evidence = session.scalar(select(Evidence).where(Evidence.score_id == case.score_id))
            if evidence is None:
                raise NotFound()
            metadata = evidence.structured_evidence
            artifact_id = metadata.get("explanation_artifact_id")
            facts = (
                self.evidence_store.observation(
                    reference(session, UUID(str(artifact_id))),
                    case.subject_key,
                    self.context(principal, correlation),
                )
                if artifact_id
                else None
            )
            # Explicit metadata allowlist; private artifact locators never leave the boundary.
            return {
                "case_id": str(identity),
                "score_id": str(case.score_id),
                "dictionary_version": evidence.dictionary_version,
                "facts": facts,
                "limitations": metadata.get("limitations", []),
            }

    def transition(
        self,
        identity: UUID,
        principal: Principal,
        key: UUID,
        correlation: UUID,
        expected: int,
        target: str,
        *,
        assignee: str | None = None,
        conclusion: str | None = None,
        note: str | None = None,
        reopen: bool = False,
    ) -> dict[str, Any]:
        principal.require(
            "case:reopen" if reopen else "case:assign" if target == "ASSIGNED" else "case:review"
        )
        principal = principal.for_permission(
            "case:reopen" if reopen else "case:assign" if target == "ASSIGNED" else "case:review"
        )
        with self.factory() as session:
            case = self.case_in(session, identity, principal)
            scope, score_id = case.access_scope, case.score_id
            if target == "ASSIGNED":
                assignee = assignee or principal.actor_id
                if (
                    scope not in principal.role_scopes.get("reviewer", frozenset())
                    and assignee != principal.actor_id
                ):
                    raise AccessDenied()
                identity_record = session.get(ApiIdentity, assignee)
                if (
                    identity_record is None
                    or identity_record.disabled
                    or scope not in identity_record.grants.get("scopes", [])
                    or "case:review" not in identity_record.grants.get("permissions", [])
                ):
                    raise AccessDenied()
        ref = (
            self.artifacts.put(
                {"note": {"text": note}},
                schema_id="case_note_v1",
                access_scope=scope,
                context=self.context(principal, correlation),
            )
            if note
            else None
        )

        def atomic_note(session: Session, result: ReviewResult) -> None:
            if ref:
                artifact_id = register_artifact(session, ref)
                session.add(
                    CaseNote(
                        review_id=result.event_id,
                        case_id=identity,
                        score_id=score_id,
                        artifact_id=artifact_id,
                    )
                )

        def ownership(current: Case) -> bool:
            if reopen != (current.state == "REVIEWED"):
                return False
            return target == "ASSIGNED" or current.assignee == principal.actor_id

        result = ReviewService(self.factory).transition(
            case_id=identity,
            expected_version=expected,
            target=target,
            idempotency_key=key,
            context=self.context(principal, correlation),
            permissions=principal.permissions,
            scopes=principal.scopes,
            assignee=assignee,
            conclusion=conclusion,
            note_reference="note:sha256:" + ref.digest if ref else None,
            before_commit=atomic_note,
            authorize_case=ownership,
        )
        return {
            "event_id": str(result.event_id),
            "case_id": str(result.case_id),
            "case_version": result.case_version,
        }

    def history(
        self,
        identity: UUID,
        principal: Principal,
        kind: str,
        after: int,
        limit: int,
        correlation: UUID,
    ) -> dict[str, Any]:
        principal.require("audit:read" if kind == "audit" else "case:read")
        principal = principal.for_permission("audit:read" if kind == "audit" else "case:read")
        with self.factory() as session:
            case = self.case_in(session, identity, principal)
            if kind == "audit":
                rows = session.scalars(
                    select(AuditEvent)
                    .where(AuditEvent.entity_reference == f"case:{identity}")
                    .order_by(AuditEvent.created_at, AuditEvent.id)
                    .offset(after)
                    .limit(limit + 1)
                ).all()
                items = [
                    {
                        "event_id": str(r.id),
                        "action": r.action,
                        "case_version": r.entity_version,
                        "created_at": r.created_at,
                        "actor_id": r.actor_id,
                    }
                    for r in rows[:limit]
                ]
            elif kind == "scores":
                opened = session.scalar(
                    select(QueueSnapshot)
                    .join(QueueCase, QueueCase.queue_id == QueueSnapshot.id)
                    .where(QueueCase.case_id == identity)
                )
                query = (
                    select(ScoreRow, QueueSnapshot)
                    .join(QueueMember, QueueMember.score_id == ScoreRow.id)
                    .join(QueueSnapshot, QueueSnapshot.id == QueueMember.queue_id)
                    .join(ScoreRun, ScoreRun.id == QueueSnapshot.run_id)
                    .join(BatchAccess, BatchAccess.batch_id == ScoreRun.batch_id)
                    .where(
                        ScoreRow.record_key == case.subject_key,
                        BatchAccess.access_scope.in_(principal.scopes),
                    )
                )
                if opened is None:
                    query = query.where(ScoreRow.id == case.score_id)
                else:
                    query = query.where(QueueSnapshot.cohort_id == opened.cohort_id)
                score_rows = session.execute(
                    query.order_by(QueueSnapshot.published_version, ScoreRow.id)
                    .offset(after)
                    .limit(limit + 1)
                ).all()
                items = [
                    {
                        "score_id": str(s.id),
                        "queue_version": str(q.id),
                        "version": q.published_version,
                        "raw_score": s.raw_score,
                        "selected": s.id == case.score_id,
                        "rank": s.contract_payload.get("rank"),
                        "freshness": s.contract_payload.get("freshness", "UNAVAILABLE"),
                        "assessed_as_of": s.contract_payload.get("assessed_as_of"),
                        "model_id": str(cast(ScoreRun, session.get(ScoreRun, s.run_id)).model_id),
                    }
                    for s, q in score_rows[:limit]
                ]
                return {"items": items, "next": after + limit if len(score_rows) > limit else None}
            else:
                reviews = session.scalars(
                    select(ReviewEvent)
                    .where(ReviewEvent.case_id == identity)
                    .order_by(ReviewEvent.case_version, ReviewEvent.id)
                    .offset(after)
                    .limit(limit + 1)
                ).all()
                items = []
                for r in reviews[:limit]:
                    item: dict[str, Any] = {
                        "event_id": str(r.id),
                        "case_version": r.case_version,
                        "action": r.action,
                        "actor_id": r.actor_id,
                        "conclusion": r.conclusion,
                        "created_at": r.created_at,
                        "score_id": str(case.score_id),
                    }
                    if "note:read" in principal.permissions:
                        note = session.scalar(select(CaseNote).where(CaseNote.review_id == r.id))
                        if note:
                            item["note"] = cast(
                                dict[str, Any],
                                self.artifacts.observation(
                                    reference(session, note.artifact_id),
                                    "note",
                                    self.context(principal, correlation),
                                ),
                            )["text"]
                    items.append(item)
                rows = reviews  # type: ignore[assignment]
            return {"items": items, "next": after + limit if len(rows) > limit else None}

    def export(
        self, request: ExportSubmission, principal: Principal, key: UUID, correlation: UUID
    ) -> dict[str, Any]:
        principal.require("export:create")
        principal = principal.for_permission("export:create")
        # PII and notes are never enabled implicitly by the reviewer role.
        if set(request.columns) & {"record_key", "note"}:
            principal.require("export:sensitive")
        if not request.columns or len(set(request.columns)) != len(request.columns):
            raise ValueError("Unique export columns are required")
        payload = request.model_dump(mode="json")
        with unit_of_work(self.factory) as session:
            queue, scope = self.queue_in(session, request.queue_version, principal)
            self.materialize(session, queue.id, scope)
            job = JobRepository(session).create(
                actor_id=principal.actor_id,
                operation="api:export",
                idempotency_key=key,
                request=payload,
            )
            if session.get(ApiTask, job.id) is None:
                page = session.execute(
                    select(QueueMember, Case, ScoreRow, ScoreRun, ModelRef)
                    .join(
                        QueueCase,
                        (QueueCase.queue_id == QueueMember.queue_id)
                        & (QueueCase.record_key == QueueMember.record_key),
                    )
                    .join(Case, Case.id == QueueCase.case_id)
                    .join(ScoreRow, ScoreRow.id == QueueMember.score_id)
                    .join(ScoreRun, ScoreRun.id == ScoreRow.run_id)
                    .join(ModelRef, ModelRef.id == ScoreRun.model_id)
                    .where(
                        QueueMember.queue_id == queue.id,
                        Case.access_scope.in_(principal.scopes),
                        Case.state == request.state if request.state else true(),
                    )
                    .order_by(QueueMember.rank, QueueMember.record_key)
                ).all()
                snapshot = [
                    {
                        "case_id": str(c.id),
                        "rank": m.rank,
                        "raw_score": s.raw_score,
                        "state": c.state,
                        "batch_id": str(run.batch_id),
                        "run_id": str(run.id),
                        "bundle_digest": model.bundle_digest,
                        "policy_hash": run.policy_hash,
                        "assessed_as_of": s.contract_payload.get("assessed_as_of"),
                        "freshness": s.contract_payload.get("freshness", "UNAVAILABLE"),
                        "queue_version": str(queue.id),
                    }
                    for m, c, s, run, model in page
                ]
                if set(request.columns) & {"record_key", "note"}:
                    if scope not in principal.permission_scopes.get(
                        "export:sensitive", frozenset()
                    ):
                        raise AccessDenied()
                    for exported, (member, case, _, _, _) in zip(snapshot, page, strict=True):
                        if "record_key" in request.columns:
                            exported["record_key"] = member.record_key
                        if "note" in request.columns:
                            note = session.scalar(
                                select(CaseNote)
                                .join(ReviewEvent, ReviewEvent.id == CaseNote.review_id)
                                .where(CaseNote.case_id == case.id)
                                .order_by(ReviewEvent.case_version.desc())
                                .limit(1)
                            )
                            exported["note"] = (
                                cast(
                                    dict[str, Any],
                                    self.artifacts.observation(
                                        reference(session, note.artifact_id),
                                        "note",
                                        self.context(principal, correlation),
                                    ),
                                )["text"]
                                if note
                                else None
                            )
                session.add(
                    ApiTask(
                        job_id=job.id,
                        kind="export",
                        access_scope=scope,
                        request=payload,
                        authorization={
                            "principal": principal.payload(),
                            "policy_hash": self.policy_hash,
                        },
                    )
                )
                snapshot_ref = self.artifacts.put(
                    {"snapshot": {"rows": snapshot}},
                    schema_id="export_snapshot_v1",
                    access_scope=scope,
                    context=self.context(principal, correlation),
                )
                snapshot_id = register_artifact(session, snapshot_ref)
                session.add(
                    ExportRecord(
                        job_id=job.id,
                        queue_id=queue.id,
                        expires_at=datetime.now(UTC) + timedelta(minutes=10),
                        snapshot=[{"artifact_id": str(snapshot_id)}],
                    )
                )
                AuditService().append(
                    session,
                    self.context(principal, correlation),
                    action="export:authorize",
                    entity_reference=f"job:{job.id}",
                    request_hash=job.request_hash,
                    reason_reference="reason:sha256:" + fingerprint(request.reason),
                )
            return {"job_id": str(job.id), "state": job.state}

    @staticmethod
    def csv_value(value: Any) -> Any:
        if isinstance(value, str):
            index = 0
            while index < len(value) and (value[index].isspace() or value[index] == "\ufeff"):
                index += 1
            stripped = value[index:]
            if value.startswith(("\t", "\r", "\n")) or stripped.startswith(("=", "+", "-", "@")):
                return "'" + value
        return value

    def export_worker(self, task: ApiTask, principal: Principal) -> dict[str, Any]:
        with self.factory() as session:
            record = session.get(ExportRecord, task.job_id)
            if record is None or record.expires_at <= datetime.now(UTC):
                raise AccessDenied()
            columns = list(task.request["columns"]) + [
                "queue_version",
                "batch_id",
                "run_id",
                "bundle_digest",
                "policy_hash",
                "assessed_as_of",
                "freshness",
            ]
            output = io.StringIO(newline="")
            writer = csv.writer(output)
            writer.writerow(columns)
            frozen = cast(
                dict[str, Any],
                self.artifacts.observation(
                    reference(session, UUID(str(record.snapshot[0]["artifact_id"]))),
                    "snapshot",
                    self.context(principal),
                ),
            )
            rows = frozen["rows"]
            for row in rows:
                writer.writerow([self.csv_value(row.get(c)) for c in columns])
        ref = self.artifacts.put(
            {"export": {"csv": output.getvalue()}},
            schema_id="export_v1",
            access_scope=task.access_scope,
            context=self.context(principal),
        )
        return {"artifact": ref, "rows": len(rows)}

    def download(self, identity: UUID, principal: Principal, correlation: UUID) -> str:
        principal.require("export:create")
        principal = principal.for_permission("export:create")
        with unit_of_work(self.factory) as session:
            job, task = self.job_in(session, identity, principal)
            record = session.get(ExportRecord, identity)
            if set(task.request.get("columns", [])) & {"record_key", "note"}:
                principal.require("export:sensitive")
                if task.access_scope not in principal.permission_scopes.get(
                    "export:sensitive", frozenset()
                ):
                    raise NotFound()
            if (
                job.actor_id != principal.actor_id
                or job.state != "SUCCEEDED"
                or record is None
                or record.artifact_id is None
                or record.expires_at <= datetime.now(UTC)
            ):
                raise NotFound()
            payload = self.artifacts.observation(
                reference(session, record.artifact_id),
                "export",
                self.context(principal, correlation),
            )
            AuditService().append(
                session,
                self.context(principal, correlation),
                action="export:download",
                entity_reference=f"job:{identity}",
                request_hash=fingerprint({"job": str(identity)}),
            )
            return str(cast(dict[str, Any], payload)["csv"])

    def outcomes(
        self, request: OutcomeSubmission, principal: Principal, key: UUID, correlation: UUID
    ) -> dict[str, Any]:
        principal.require("label:submit")
        principal = principal.for_permission("label:submit")
        source = self.outcome_sources.get(request.source_id)
        if (
            not source
            or source.get("owner") != principal.actor_id
            or not source.get("approval")
            or source.get("scope") not in principal.scopes
            or not source.get("identity_map")
        ):
            raise AccessDenied()
        now = datetime.now(UTC)
        if request.known_as_of.utcoffset() is None or request.known_as_of > now:
            raise ValueError("Invalid outcome cutoff")
        digest = fingerprint(request.model_dump(mode="json"))
        with unit_of_work(self.factory) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": "outcome-source:" + request.source_id},
            )
            previous = session.scalar(
                select(Submission).where(
                    Submission.actor_id == principal.actor_id, Submission.idempotency_key == key
                )
            )
            if previous:
                if previous.request_hash != digest:
                    raise PersistenceConflict()
                return {"submission_id": str(previous.id), "count": len(request.labels)}
            submission = Submission(
                id=uuid4(),
                actor_id=principal.actor_id,
                source_id=request.source_id,
                idempotency_key=key,
                request_hash=digest,
                known_as_of=request.known_as_of,
                provenance={
                    "approval": source["approval"],
                    "selection": "review_selected",
                    "population_recall_evidence": False,
                },
            )
            session.add(submission)
            session.flush()
            for label in sorted(request.labels, key=lambda item: (item.record_key, item.version)):
                if (
                    label.label_source != request.source_id
                    or label.status == "UNREVIEWED"
                    or source["identity_map"].get(label.record_key) != label.account_id
                    or max(label.available_at, label.observed_at, label.mature_at)
                    > request.known_as_of
                ):
                    raise ValueError("Outcome source or maturity is invalid")
                # Serialize identity history across approved sources, not just within this manifest.
                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                    {"key": "label-identity:" + label.record_key},
                )
                records = session.scalars(
                    select(OutcomeContract)
                    .join(Label, Label.id == OutcomeContract.label_id)
                    .where(Label.subject_key == label.record_key)
                    .order_by(Label.known_at)
                ).all()
                latest_known = session.scalar(
                    select(func.max(Label.known_at)).where(Label.subject_key == label.record_key)
                )
                if latest_known and request.known_as_of < latest_known:
                    raise ValueError("Outcome knowledge cannot move backwards")
                history = tuple(QualifiedLabel.model_validate(r.payload) for r in records) + (
                    label,
                )
                selected = select_label_as_of(history, request.known_as_of)
                if selected is None:
                    raise ValueError("A mature outcome is required")
                session.add(
                    Label(
                        id=label.label_id,
                        subject_key=label.record_key,
                        outcome=str(label.value),
                        maturity=label.status,
                        known_at=request.known_as_of,
                        supersedes_id=label.supersedes,
                    )
                )
                session.flush()
                session.add(
                    OutcomeContract(
                        label_id=label.label_id,
                        submission_id=submission.id,
                        payload=label.model_dump(mode="json"),
                    )
                )
                session.flush()
            AuditService().append(
                session,
                self.context(principal, correlation),
                action="label:ingest",
                entity_reference=f"outcome:{submission.id}",
                request_hash=digest,
                idempotency_key=key,
            )
            return {"submission_id": str(submission.id), "count": len(request.labels)}

    def labels_as_of(self, subject_key: str, cutoff: datetime) -> QualifiedLabel | None:
        with self.factory() as session:
            contracts = session.scalars(
                select(OutcomeContract)
                .join(Label, Label.id == OutcomeContract.label_id)
                .where(Label.subject_key == subject_key, Label.known_at <= cutoff)
            ).all()
            return select_label_as_of(
                tuple(QualifiedLabel.model_validate(c.payload) for c in contracts), cutoff
            )

    def model(self, identity: UUID, principal: Principal) -> dict[str, Any]:
        principal.require("case:read")
        principal = principal.for_permission("case:read")
        with self.factory() as session:
            row = session.scalar(
                select(ModelRef)
                .join(ScoreRun, ScoreRun.model_id == ModelRef.id)
                .join(BatchAccess, BatchAccess.batch_id == ScoreRun.batch_id)
                .where(ModelRef.id == identity, BatchAccess.access_scope.in_(principal.scopes))
                .limit(1)
            )
            if row is None:
                raise NotFound()
            return {
                "model_id": str(row.id),
                "bundle_digest": row.bundle_digest,
                "tier": row.tier,
                "registry_version": row.registry_version,
            }

    def run_one(self, job_id: UUID | None = None) -> UUID | None:
        # Session-level advisory slots bound all workers sharing this database.
        with self.factory() as slots:
            for slot in range(self.settings.worker_count):
                key = "mule-api-worker-slot:" + str(slot)
                acquired = slots.scalar(
                    text("SELECT pg_try_advisory_lock(hashtextextended(:key,0))"), {"key": key}
                )
                if acquired:
                    try:
                        return self._run_one(job_id)
                    finally:
                        slots.execute(
                            text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"),
                            {"key": key},
                        )
            return None

    def _run_one(self, job_id: UUID | None = None) -> UUID | None:
        """A process restart resumes durable tasks; no model work runs in the HTTP process."""
        from mule_detection.persistence.errors import LeaseLost

        with unit_of_work(self.factory) as session:
            query = (
                select(Job)
                .join(ApiTask, ApiTask.job_id == Job.id)
                .where(
                    or_(
                        Job.state == "PENDING",
                        (Job.state == "RUNNING") & (Job.lease_expires_at <= func.clock_timestamp()),
                    )
                )
            )
            if job_id:
                query = query.where(Job.id == job_id)
            job = session.scalar(
                query.order_by(Job.created_at).with_for_update(skip_locked=True).limit(1)
            )
            if job is None:
                return None
            lease = JobRepository(session).acquire(
                job.id, "api-worker:" + str(uuid4()), seconds=3600
            )
            task = session.get(ApiTask, job.id)
            assert task is not None
            session.expunge(task)
        from threading import Event, Thread

        stop = Event()

        def heartbeat() -> None:
            while not stop.wait(45):
                try:
                    with unit_of_work(self.factory) as session:
                        JobRepository(session).renew(lease, seconds=3600)
                except Exception:
                    return  # Publication will independently reject an expired/lost lease.

        pulse = Thread(target=heartbeat, daemon=True)
        pulse.start()
        try:
            principal = self.worker_principal(task)
            if task.kind == "export":
                result = self.export_worker(task, principal)
            else:
                handler = self.handlers.get(task.kind)
                if handler is None:
                    raise AccessDenied()
                result = handler(task, principal, self.context(principal))
            self.worker_principal(
                task
            )  # Revocation/expiry and policy checked again before acknowledgement.
            with unit_of_work(self.factory) as session:

                def publish() -> None:
                    self.worker_principal(task, session)
                    current = session.get(ApiTask, task.job_id)
                    assert current is not None
                    safe = dict(result)
                    if task.kind == "export":
                        ref = safe.pop("artifact")
                        record = session.get(ExportRecord, task.job_id)
                        assert record is not None
                        record.artifact_id = register_artifact(session, ref)
                        safe["download"] = f"/v1/exports/{task.job_id}/download"
                    if "batch_id" in safe and safe["batch_id"]:
                        batch_id = UUID(safe["batch_id"])
                        existing = session.get(BatchAccess, batch_id)
                        if existing is not None and existing.access_scope != task.access_scope:
                            raise AccessDenied()
                        if existing is None:
                            session.add(
                                BatchAccess(batch_id=batch_id, access_scope=task.access_scope)
                            )
                    if safe.get("queue_id"):
                        self.materialize(session, UUID(safe["queue_id"]), task.access_scope)
                    current.result = safe
                    AuditService().append(
                        session,
                        self.context(principal),
                        action="api:job_complete",
                        entity_reference=f"job:{task.job_id}",
                        request_hash=fingerprint(safe),
                    )
                    self.worker_principal(task, session)

                JobRepository(session).publish(
                    lease, publish, result_reference=f"api-result:{task.job_id}"
                )
        except LeaseLost:
            raise
        except Exception:
            # Dependency diagnostics stay in protected operations telemetry, never in job DTOs.
            with unit_of_work(self.factory) as session:
                job = JobRepository(session).require_active(lease)
                job.state, job.lease_owner, job.lease_expires_at = "FAILED", None, None
                current = session.get(ApiTask, task.job_id)
                assert current is not None
                current.result = {"error_code": "JOB_FAILED"}
                AuditService().append(
                    session,
                    ExecutionContext(job.actor_id, self.settings.environment, uuid4()),
                    action="api:job_failed",
                    entity_reference=f"job:{task.job_id}",
                    request_hash=fingerprint({"error_code": "JOB_FAILED"}),
                )
        finally:
            stop.set()
            pulse.join(timeout=1)
        return task.job_id

    def worker_principal(self, task: ApiTask, session: Session | None = None) -> Principal:
        if session is None:
            with self.factory() as owned:
                return self.worker_principal(task, owned)
        principal = Principal.restore(task.authorization["principal"])
        required = {
            "intake": "batch:intake",
            "score": "score:submit",
            "train": "train:submit",
            "export": "export:create",
        }[task.kind]
        if (
            task.authorization["policy_hash"] != self.policy_hash
            or principal.expires_at <= time.time()
        ):
            raise AccessDenied()
        current = session.scalar(
            select(ApiIdentity)
            .where(ApiIdentity.actor_id == principal.actor_id)
            .with_for_update(read=True)
        )
        if (
            current is None
            or current.disabled
            or current.valid_until <= datetime.now(UTC)
            or not principal.permissions <= set(current.grants["permissions"])
            or task.access_scope not in current.grants["permission_scopes"].get(required, [])
            or task.access_scope not in principal.permission_scopes.get(required, frozenset())
        ):
            raise AccessDenied()
        return principal
