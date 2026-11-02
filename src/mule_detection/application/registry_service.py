"""Durable registration intent precedes recoverable external registry writes."""

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from mule_detection.application.audit_service import AuditService
from mule_detection.application.context import ExecutionContext
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.persistence.errors import AccessDenied
from mule_detection.persistence.models import ModelRef, RegistryCandidate
from mule_detection.registry.bundle_loader import BundleLoader
from mule_detection.registry.bundle_writer import BundleStore
from mule_detection.registry.mlflow_adapter import RegistryBackend
from mule_detection.registry.promotion_policy import PromotionEvidence


class RegistryService:
    def __init__(
        self,
        factory: Callable[[], Session],
        store: BundleStore,
        backend: RegistryBackend,
        authorize: Callable[[ExecutionContext, str], bool],
    ) -> None:
        self.factory, self.store, self.backend, self.authorize = factory, store, backend, authorize

    def create_candidate(self, digest: str, name: str, context: ExecutionContext) -> UUID:
        if not self.authorize(context, "model:train"):
            raise AccessDenied()
        manifest = self.store.inspect(digest)
        if (
            manifest["trainer_id"] != context.actor_id
            or not manifest["contract"]["research_only"]
            or manifest["data_tier"] not in {"research", "synthetic"}
        ):
            raise DomainError(ErrorCode.CONTRACT_INVALID)
        BundleLoader(self.store, lambda *_: False).verify_candidate(digest)
        with unit_of_work(self.factory) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": "candidate:" + digest},
            )
            previous = session.scalar(
                select(RegistryCandidate).where(RegistryCandidate.bundle_digest == digest)
            )
            if previous:
                if previous.registry_name != name or previous.trainer_id != context.actor_id:
                    raise DomainError(ErrorCode.IDENTITY_CONFLICT)
                return previous.id
            evidence = PromotionEvidence(
                data_tier=manifest["data_tier"],
                bound_bundle_digest=digest,
                unresolved_critical=("COHORT_CONFOUNDING", "UNCERTIFIED_SOURCE_AND_LABELS"),
            )
            candidate = RegistryCandidate(
                bundle_digest=digest,
                training_run_id=UUID(manifest["training_run_id"]),
                trainer_id=context.actor_id,
                data_tier=manifest["data_tier"],
                registry_name=name,
                evidence_payload={
                    "manifest": manifest,
                    "promotion": evidence.model_dump(mode="json"),
                },
            )
            session.add(candidate)
            session.flush()
            AuditService().append(
                session,
                context,
                action="model:candidate",
                entity_reference=f"candidate:{candidate.id}",
                request_hash=digest,
            )
            return candidate.id

    def synchronize(self, candidate_id: UUID, context: ExecutionContext) -> dict[str, Any]:
        if not self.authorize(context, "model:train"):
            raise AccessDenied()
        # A short-lived session-level advisory lock serializes network attempts.
        with self.factory() as lock_session:
            lock_session.execute(
                text("SELECT pg_advisory_lock(hashtextextended(:key,0))"),
                {"key": str(candidate_id)},
            )
            try:
                with unit_of_work(self.factory) as session:
                    candidate = session.get(RegistryCandidate, candidate_id)
                    if candidate is None or candidate.trainer_id != context.actor_id:
                        raise AccessDenied()
                    name, digest = candidate.registry_name, candidate.bundle_digest
                    state = candidate.registration_state
                    if state == "REGISTERED":
                        return {
                            "candidate_id": str(candidate_id),
                            "state": state,
                            "version": candidate.remote_version,
                            "digest": digest,
                        }
                    candidate.registration_state = "IN_FLIGHT"
                try:
                    found = self.backend.lookup(name, str(candidate_id))
                    if found is None and state != "PENDING":
                        raise DomainError(ErrorCode.WORKFLOW_INVALID)
                    if found is None:
                        manifest = self.store.inspect(digest)
                        lineage = json.loads(
                            self.store.read(
                                digest, "lineage.json", manifest["files"]["lineage.json"]
                            )
                        )
                        metric = lineage["diagnostic_metrics"]
                        found = self.backend.register(
                            name,
                            str(candidate_id),
                            digest,
                            self.store.path(digest),
                            {
                                key: float(metric[key])
                                for key in ("average_precision", "roc_auc")
                                if metric[key] is not None
                            },
                            {
                                **{
                                    key: str(lineage[key])
                                    for key in (
                                        "dataset_hash",
                                        "split_hash",
                                        "config_hash",
                                        "selection_hash",
                                        "training_rows",
                                    )
                                },
                                **{
                                    "selected_" + key: str(value)
                                    for key, value in lineage["selected_spec"].items()
                                },
                            },
                        )
                    if found["bundle_digest"] != digest:
                        raise DomainError(ErrorCode.HASH_MISMATCH)
                    with unit_of_work(self.factory) as session:
                        candidate = session.get(RegistryCandidate, candidate_id)
                        assert candidate is not None
                        model = ModelRef(
                            bundle_digest=digest,
                            registry_name=name,
                            registry_version=found["version"],
                            tier="research_demo",
                        )
                        session.add(model)
                        session.flush()
                        (
                            candidate.model_ref_id,
                            candidate.remote_run_id,
                            candidate.remote_version,
                        ) = model.id, found["run_id"], found["version"]
                        candidate.registration_state = "REGISTERED"
                        AuditService().append(
                            session,
                            context,
                            action="model:register",
                            entity_reference=f"candidate:{candidate_id}",
                            request_hash=digest,
                            after_reference=f"registry:{name}/{found['version']}",
                        )
                    return {
                        "candidate_id": str(candidate_id),
                        "state": "REGISTERED",
                        "version": found["version"],
                        "digest": digest,
                    }
                except Exception:
                    with unit_of_work(self.factory) as session:
                        candidate = session.get(RegistryCandidate, candidate_id)
                        assert candidate is not None
                        if candidate.registration_state != "REGISTERED":
                            candidate.registration_state = "UNCERTAIN"
                    raise
            finally:
                lock_session.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"),
                    {"key": str(candidate_id)},
                )
