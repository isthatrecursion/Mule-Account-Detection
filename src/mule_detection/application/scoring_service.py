"""Idempotent accepted-input jobs, frozen inputs, explicit retries and corrections."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from mule_detection.application.audit_service import AuditService
from mule_detection.application.context import ExecutionContext
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.domain.contracts.common import canonical_hash
from mule_detection.domain.contracts.scoring import ScoringRequest
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.features.signature import align_input
from mule_detection.persistence.artifacts import ArtifactStore
from mule_detection.persistence.errors import AccessDenied, PersistenceConflict
from mule_detection.persistence.job_repository import JobRepository
from mule_detection.persistence.models import (
    Dataset,
    Job,
    ModelPin,
    QueueHead,
    QueueSnapshot,
    RegistryCandidate,
    ScoreRow,
    ScoreRun,
    ScoringAttempt,
    ScoringTask,
)
from mule_detection.persistence.repositories import Repositories
from mule_detection.registry.bundle_loader import BundleLoader
from mule_detection.registry.model_resolver import ModelResolver, eligible
from mule_detection.scoring.preflight import ResearchPreflight
from mule_detection.scoring.ranking import ReviewPolicy
from mule_detection.scoring.storage import records_from_frame, reference, register_artifact


class ScoringService:
    def __init__(
        self,
        factory: Callable[[], Session],
        preflight: ResearchPreflight,
        artifacts: ArtifactStore,
        resolver: ModelResolver,
        loader: BundleLoader,
        policy: ReviewPolicy,
        authorize: Callable[[ExecutionContext, str], bool],
        *,
        chunk_rows: int = 128,
        lease_seconds: int = 300,
    ) -> None:
        if not 1 <= chunk_rows <= 128 or not 1 <= lease_seconds <= 3600:
            raise DomainError(ErrorCode.CONFIGURATION_INVALID)
        self.factory, self.preflight, self.artifacts = factory, preflight, artifacts
        self.resolver, self.loader, self.policy, self.authorize = (
            resolver,
            loader,
            policy,
            authorize,
        )
        self.chunk_rows, self.lease_seconds = chunk_rows, lease_seconds

    def _authority(
        self, context: ExecutionContext, environment: str, *, correction: bool = False
    ) -> None:
        if (
            not self.authorize(context, "score:run")
            or (correction and not self.authorize(context, "score:correct"))
            or environment not in {"local", "test", "research"}
            or context.environment not in {"local", "test", "research"}
        ):
            raise AccessDenied()

    def create(self, request: ScoringRequest, context: ExecutionContext) -> dict[str, str]:
        self._authority(context, request.environment, correction=bool(request.affected_keys))
        try:
            return self._create(request, context)
        except Exception as error:
            self._preflight_failure(request, context, error)
            raise

    def _preflight_failure(
        self, request: ScoringRequest, context: ExecutionContext, error: Exception
    ) -> None:
        intent = request.model_dump(mode="json")
        identity = uuid5(NAMESPACE_URL, canonical_hash(intent))
        code = error.code.value if isinstance(error, DomainError) else "PREFLIGHT_REJECTED"
        with unit_of_work(self.factory) as session:
            job = JobRepository(session).create(
                actor_id=context.actor_id,
                operation="score:preflight",
                idempotency_key=identity,
                request=intent,
            )
            if job.state == "PENDING":
                lease = JobRepository(session).acquire(job.id, "preflight", seconds=60)
                job = JobRepository(session).require_active(lease)
                session.add(
                    ScoringAttempt(
                        job_id=job.id,
                        fencing_token=lease.token,
                        actor_id=context.actor_id,
                        environment=context.environment,
                        state="FAILED",
                        error_code=code,
                    )
                )
                job.state, job.result_reference = "FAILED", code
                job.lease_owner = job.lease_expires_at = None
                AuditService().append(
                    session,
                    context,
                    action="score:preflight_failed",
                    entity_reference=f"job:{job.id}",
                    request_hash=job.request_hash,
                    reason_reference=code,
                )

    def _create(self, request: ScoringRequest, context: ExecutionContext) -> dict[str, str]:
        intent = canonical_hash(
            {
                **request.model_dump(mode="json"),
                "affected_keys": sorted(request.affected_keys),
                "review_policy_hash": self.policy.digest,
                "feature_policy_hash": self.preflight.training.adapter.feature_policy.fingerprint,
            }
        )
        # Historical retries retrieve the original identity even after revocation.
        # Unpublished execution still rechecks every prerequisite at run/publication.
        with unit_of_work(self.factory) as session:
            previous = session.scalar(
                select(ScoringTask)
                .join(Job, Job.id == ScoringTask.job_id)
                .where(
                    Job.actor_id == context.actor_id,
                    ScoringTask.manifest["intent_hash"].astext == intent,
                )
            )
            if previous is not None:
                return self._identity(previous)
        data, validation_id = self.preflight.load(request.batch_id, context)
        bundle = self.loader.store.inspect(request.bundle_digest)
        contract = bundle["contract"]
        if (
            not contract["research_only"]
            or contract["output_scale"] != "review_priority"
            or contract["contribution_scale"] != "raw_margin"
            or contract["feature_policy_hash"]
            != self.preflight.training.adapter.feature_policy.fingerprint
        ):
            raise DomainError(ErrorCode.FEATURE_FORBIDDEN)
        import json

        signature = json.loads(
            self.loader.store.read(
                request.bundle_digest,
                "input_signature.json",
                bundle["files"]["input_signature.json"],
            )
        )
        align_input(data.X, signature)  # No transformation before all prerequisites pass.
        if not self.resolver.authorized(request.bundle_digest, request.environment):
            raise DomainError(ErrorCode.CONTRACT_INVALID)
        # Check runtime and saved fixture before staging a logical scoring job.
        self.loader.load(request.bundle_digest, request.environment)
        payload = {
            **request.model_dump(mode="json"),
            "affected_keys": sorted(request.affected_keys),
            "content_hash": data.dataset_hash,
            "split_hash": data.split_hash,
            "validation_id": str(validation_id),
            "feature_policy_hash": contract["feature_policy_hash"],
            "review_policy_hash": self.policy.digest,
        }
        digest = canonical_hash(payload)
        request_key = uuid5(NAMESPACE_URL, "score-request:" + digest)
        # Serialize the entire create path, including immutable artifact registration.
        with unit_of_work(self.factory) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": context.actor_id + ":score:" + digest},
            )
            job = JobRepository(session).create(
                actor_id=context.actor_id,
                operation="score",
                idempotency_key=request_key,
                request=payload,
            )
            existing = session.get(ScoringTask, job.id)
            if existing:
                return self._identity(existing)
            accepted = Repositories(session).get_accepted_batch(request.batch_id)
            if accepted.accepted_validation_id != validation_id:
                raise PersistenceConflict()
            candidate = session.scalar(
                select(RegistryCandidate)
                .where(RegistryCandidate.bundle_digest == request.bundle_digest)
                .with_for_update()
            )
            if candidate is None or candidate.model_ref_id is None:
                raise DomainError(ErrorCode.LINEAGE_INVALID)
            decision = eligible(session, candidate, request.environment)
            cohort = uuid5(
                NAMESPACE_URL,
                "cohort:" + str(request.batch_id) + canonical_hash({"keys": sorted(data.keys)}),
            )
            parent_rows: dict[str, Any] = {}
            if request.replay_of:
                parent = session.scalar(
                    select(ScoringTask).where(ScoringTask.run_id == request.replay_of)
                )
                parent_run = session.get(ScoreRun, request.replay_of)
                if (
                    parent is None
                    or parent.state != "COMPLETE"
                    or parent_run is None
                    or parent.environment != request.environment
                    or parent_run.actor_id != context.actor_id
                    or parent_run.model_id != candidate.model_ref_id
                    or parent_run.policy_hash != self.policy.digest
                ):
                    raise DomainError(ErrorCode.LINEAGE_INVALID)
                cohort = parent.cohort_id
                parent_rows = {
                    row.record_key: {
                        "score": row.raw_score,
                        "score_id": str(row.id),
                        "snapshot_id": row.contract_payload["snapshot_id"],
                    }
                    for row in session.scalars(
                        select(ScoreRow).where(ScoreRow.run_id == request.replay_of)
                    )
                }
                if set(parent_rows) != set(data.keys):
                    raise DomainError(ErrorCode.SPLIT_MISMATCH)
            if not set(request.affected_keys) <= set(data.keys):
                raise DomainError(ErrorCode.SPLIT_MISMATCH)
            head = session.get(QueueHead, (cohort, request.environment))
            prior_queue = session.get(QueueSnapshot, head.queue_id) if head else None
            if request.replay_of and (
                prior_queue is None or prior_queue.run_id != request.replay_of
            ):
                raise PersistenceConflict()
            selected = set(request.affected_keys) if request.affected_keys else set(data.keys)
            shards = []
            snapshots = {}
            for start in range(0, len(data.keys), self.chunk_rows):
                keys = data.keys[start : start + self.chunk_rows]
                new_keys = tuple(k for k in keys if k in selected)
                if not new_keys:
                    continue
                positions = [start + offset for offset, key in enumerate(keys) if key in selected]
                ref = self.artifacts.put(
                    records_from_frame(data.X.iloc[positions], new_keys),
                    schema_id="research_features_v1",
                    access_scope="research",
                    context=context,
                )
                artifact_id = register_artifact(session, ref)
                shards.append({"artifact_id": str(artifact_id), "keys": list(new_keys)})
                snapshots.update({key: str(artifact_id) for key in new_keys})
            for key, row in parent_rows.items():
                if key not in selected:
                    snapshots[key] = row["snapshot_id"]
            index = self.artifacts.put(
                {key: {"snapshot_id": value} for key, value in snapshots.items()},
                schema_id="cohort_index_v1",
                access_scope="research",
                context=context,
            )
            snapshot_id = register_artifact(session, index)
            run = Repositories(session).create_run(
                actor_id=context.actor_id,
                idempotency_key=request_key,
                batch_id=request.batch_id,
                model_id=candidate.model_ref_id,
                policy_hash=self.policy.digest,
                snapshot_id=snapshot_id,
            )
            manifest = {
                "intent_hash": intent,
                "request": payload,
                "input_chunks": shards,
                "keys": list(data.keys),
                "snapshots": snapshots,
                "signature": signature,
                "bundle_id": contract["bundle_id"],
                "dictionary_version": contract["dictionary_version"],
                "feature_policy_hash": contract["feature_policy_hash"],
                "transformed_signature": contract["transformed_signature"],
                "data_tier": data.data_tier,
                "top_k": self.policy.top_k,
                "sort_policy": self.policy.sort_version,
                "review_policy_version": self.policy.version,
                "chunk_rows": self.chunk_rows,
                "parent_rows": parent_rows,
                "correction": bool(request.affected_keys),
                "unchanged": {k: v for k, v in parent_rows.items() if k not in selected},
                "expected_input_hash": index.digest,
            }
            task = ScoringTask(
                job_id=job.id,
                run_id=run.id,
                cohort_id=cohort,
                environment=request.environment,
                predecessor_queue_id=head.queue_id if head else None,
                parent_run_id=request.replay_of,
                manifest=manifest,
            )
            session.add(task)
            session.add(
                ModelPin(
                    job_id=job.id,
                    candidate_id=candidate.id,
                    decision_id=decision.id,
                    environment=request.environment,
                    bundle_digest=request.bundle_digest,
                    registry_version=str(candidate.remote_version),
                    deployment_version=head.version if head else 0,
                )
            )
            session.flush()
            AuditService().append(
                session,
                context,
                action="score:create",
                entity_reference=f"run:{run.id}",
                request_hash=digest,
            )
            return self._identity(task)

    @staticmethod
    def _identity(task: ScoringTask) -> dict[str, str]:
        return {"job_id": str(task.job_id), "run_id": str(task.run_id), "state": task.state}

    def task(self, job_id: UUID, context: ExecutionContext) -> ScoringTask:
        with unit_of_work(self.factory) as session:
            task = session.get(ScoringTask, job_id)
            job = session.get(Job, job_id)
            if task is None or job is None or job.actor_id != context.actor_id:
                raise AccessDenied()
            self._authority(context, task.environment, correction=bool(task.manifest["correction"]))
            return task

    def run(
        self,
        job_id: UUID,
        context: ExecutionContext,
        *,
        owner: str = "local-score-worker",
        fault: Callable[[str], None] | None = None,
    ) -> dict[str, str]:
        task = self.task(job_id, context)
        if task.state == "COMPLETE":
            return self.result(job_id, context)
        with unit_of_work(self.factory) as session:
            job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
            assert job is not None
            if job.state == "FAILED":
                job.state = "PENDING"
                AuditService().append(
                    session,
                    context,
                    action="job:retry",
                    entity_reference=f"job:{job_id}",
                    request_hash=job.request_hash,
                    reason_reference="FULL_UNPUBLISHED_RESTART",
                )
            lease = JobRepository(session).acquire(job_id, owner, seconds=self.lease_seconds)
            session.add(
                ScoringAttempt(
                    job_id=job_id,
                    fencing_token=lease.token,
                    actor_id=context.actor_id,
                    environment=task.environment,
                    state="RUNNING",
                    error_code=None,
                )
            )
        try:
            self.verify_current(task, context)
            from mule_detection.application.publication_service import PublicationService
            from mule_detection.scoring.worker import ScoreWorker

            prepared = ScoreWorker(self).stage(task, lease, context, fault=fault)
            return PublicationService(self).publish(task, lease, prepared, context, fault=fault)
        except Exception as error:
            with unit_of_work(self.factory) as session:
                job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
                if (
                    job
                    and job.state == "RUNNING"
                    and job.fencing_token == lease.token
                    and job.lease_owner == owner
                ):
                    job.state = "FAILED"
                    job.lease_owner = job.lease_expires_at = None
                attempt = session.get(ScoringAttempt, (job_id, lease.token))
                if job and attempt is not None and attempt.state == "RUNNING":
                    attempt.state, attempt.error_code = (
                        "FAILED",
                        error.code.value if isinstance(error, DomainError) else "SCORING_FAILED",
                    )
                    AuditService().append(
                        session,
                        context,
                        action="score:failed",
                        entity_reference=f"job:{job_id}",
                        request_hash=job.request_hash,
                        reason_reference=attempt.error_code,
                        entity_version=lease.token,
                    )
            raise

    def verify_current(
        self, task: ScoringTask, context: ExecutionContext, session: Session | None = None
    ) -> None:
        self._authority(context, task.environment, correction=bool(task.manifest["correction"]))
        manifest: Any = task.manifest
        request_data: Any = manifest["request"]
        self.preflight.validate_keys(
            tuple(manifest["keys"]), request_data["content_hash"], request_data["split_hash"]
        )
        if request_data["review_policy_hash"] != self.policy.digest:
            raise DomainError(ErrorCode.FEATURE_FORBIDDEN)

        def check(db: Session) -> None:
            run = db.get(ScoreRun, task.run_id)
            assert run is not None
            job = db.get(Job, task.job_id)
            if (
                job is None
                or job.actor_id != context.actor_id
                or run.actor_id != context.actor_id
                or job.request_hash != canonical_hash(request_data)
                or str(run.batch_id) != request_data["batch_id"]
                or run.policy_hash != request_data["review_policy_hash"]
                or task.environment != request_data["environment"]
            ):
                raise DomainError(ErrorCode.LINEAGE_INVALID)
            batch = Repositories(db).get_accepted_batch(run.batch_id)
            dataset = db.get(Dataset, batch.dataset_id)
            request: Any = task.manifest["request"]
            if (
                dataset is None
                or dataset.content_hash != request["content_hash"]
                or str(batch.accepted_validation_id) != request["validation_id"]
                or dataset.data_tier != "research"
            ):
                raise DomainError(ErrorCode.LINEAGE_INVALID)
            pin = self.resolver.revalidate(db, task.job_id)
            candidate = db.get(RegistryCandidate, pin.candidate_id)
            if (
                pin.bundle_digest != request["bundle_digest"]
                or candidate is None
                or candidate.model_ref_id != run.model_id
            ):
                raise DomainError(ErrorCode.LINEAGE_INVALID)
            protected: Any = candidate.evidence_payload["manifest"]
            if (
                manifest["bundle_id"] != protected["contract"]["bundle_id"]
                or manifest["feature_policy_hash"] != protected["contract"]["feature_policy_hash"]
                or manifest["dictionary_version"] != protected["contract"]["dictionary_version"]
                or manifest["transformed_signature"]
                != protected["contract"]["transformed_signature"]
                or canonical_hash({"columns": manifest["signature"]})
                != protected["contract"]["input_signature"]
            ):
                raise DomainError(ErrorCode.LINEAGE_INVALID)
            ref = reference(db, run.snapshot_id)
            if ref.digest != task.manifest["expected_input_hash"]:
                raise DomainError(ErrorCode.HASH_MISMATCH)

        if session is not None:
            check(session)
        else:
            with unit_of_work(self.factory) as db:
                check(db)

    def result(self, job_id: UUID, context: ExecutionContext) -> dict[str, str]:
        task = self.task(job_id, context)
        with unit_of_work(self.factory) as session:
            queue = session.scalar(select(QueueSnapshot).where(QueueSnapshot.run_id == task.run_id))
            return {
                **self._identity(task),
                "queue_id": str(queue.id) if queue else "",
                "queue_version": str(queue.published_version) if queue else "",
            }
