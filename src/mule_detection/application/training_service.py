"""Training starts only from accepted published data under server-owned authority."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from mule_detection.application.audit_service import AuditService
from mule_detection.application.context import ExecutionContext
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.features.inputs import research_frame
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.ingestion.partition_guard import PartitionGuard
from mule_detection.ingestion.research_adapter import ResearchAdapter
from mule_detection.persistence.errors import AccessDenied, PersistenceConflict
from mule_detection.persistence.models import Dataset
from mule_detection.persistence.raw_store import RawStore
from mule_detection.persistence.repositories import Repositories
from mule_detection.training.evaluation_policy import TrainingConfig, require_mode
from mule_detection.training.report import RunStore, environment_identity
from mule_detection.training.runner import TrainingInput, evaluate_run, run_experiment


class TrainingService:
    def __init__(
        self,
        factory: Callable[[], Session],
        raw_store: RawStore,
        store: RunStore,
        adapter: ResearchAdapter,
        split_path: Path,
        root: Path,
        authorize: Callable[[ExecutionContext, str], bool],
    ) -> None:
        self.factory, self.raw_store, self.store = factory, raw_store, store
        self.adapter, self.split_path, self.root = adapter, split_path, root
        self.authorize = authorize

    def accepted_input(
        self, batch_id: UUID, context: ExecutionContext
    ) -> tuple[TrainingInput, UUID]:
        if not self.authorize(context, "model:train"):
            raise AccessDenied()
        # Current trusted adapter is research-only. No request can elevate its tier.
        with unit_of_work(self.factory) as session:
            batch = Repositories(session).get_accepted_batch(batch_id)
            dataset = session.get(Dataset, batch.dataset_id)
            if (
                dataset is None
                or dataset.data_tier != "research"
                or dataset.content_hash != self.adapter.trusted_dataset_sha256
            ):
                raise DomainError(ErrorCode.CONTRACT_INVALID)
            if dataset.raw_uri != f"raw:sha256:{dataset.content_hash}":
                raise DomainError(ErrorCode.LINEAGE_INVALID)
            validation_id = batch.accepted_validation_id
            content_hash = dataset.content_hash
        payload = self.raw_store.read(content_hash)
        # The adapter accepts paths; temporary plaintext stays inside protected
        # application storage and is removed when parsing finishes, even on error.
        staging = self.store.root / "input-staging"
        staging.mkdir(exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(dir=staging, suffix=".csv", delete=False) as stream:
            temporary = Path(stream.name)
            temporary.chmod(0o600)
            stream.write(payload)
        try:
            verified = self.adapter.adapt(temporary, self.split_path)
        finally:
            temporary.unlink(missing_ok=True)
        guard = PartitionGuard.from_verified(verified)
        prototype = FeaturePipeline.from_repository(self.root)
        if prototype.policy.fingerprint != verified.feature_policy_hash:
            raise DomainError(ErrorCode.LINEAGE_INVALID)
        data = TrainingInput(
            research_frame(verified, guard),
            verified.labels,
            verified.record_keys,
            guard,
            verified.dataset_sha256,
            verified.split_sha256,
            verified.data_tier,
            tuple(item.extraction_month or "UNKNOWN" for item in verified.restricted_lineage),
            f"batch:{batch_id}/validation:{validation_id}",
            {},
        )

        assert validation_id is not None
        return data, validation_id

    def train(
        self, batch_id: UUID, run_id: UUID, config: TrainingConfig, context: ExecutionContext
    ) -> dict[str, Any]:
        require_mode(config.mode, "research")
        data, validation_id = self.accepted_input(batch_id, context)
        prototype = FeaturePipeline.from_repository(self.root)

        def finalize() -> None:
            if not self.authorize(context, "model:train"):
                raise AccessDenied()
            with unit_of_work(self.factory) as session:
                current = Repositories(session).get_accepted_batch(batch_id)
                if current.accepted_validation_id != validation_id:
                    raise PersistenceConflict()
                AuditService().append(
                    session,
                    context,
                    action="model:train",
                    entity_reference=f"training:{run_id}",
                    after_reference=f"candidate:{run_id}",
                    request_hash=config.fingerprint,
                    idempotency_key=run_id,
                )

        return run_experiment(
            data,
            prototype,
            config,
            self.store,
            run_id,
            actor_id=context.actor_id,
            environment=environment_identity(self.root),
            before_finalize=finalize,
        )

    def evaluate(self, run_id: UUID, context: ExecutionContext) -> dict[str, Any]:
        if not self.authorize(context, "model:train"):
            raise AccessDenied()
        return evaluate_run(self.store, run_id, actor_id=context.actor_id)
