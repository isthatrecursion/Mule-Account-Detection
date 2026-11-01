"""Serialize final fitting per frozen training run and retain the original candidate."""

from uuid import UUID

from sqlalchemy import select, text

from mule_detection.application.context import ExecutionContext
from mule_detection.application.registry_service import RegistryService
from mule_detection.application.training_service import TrainingService
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.persistence.errors import AccessDenied
from mule_detection.persistence.models import RegistryCandidate
from mule_detection.registry.bundle_writer import write_bundle
from mule_detection.training.final_fit import fit_frozen_research


class BundleService:
    def __init__(self, training: TrainingService, registry: RegistryService) -> None:
        self.training, self.registry = training, registry

    def build(
        self, batch_id: UUID, run_id: UUID, name: str, context: ExecutionContext
    ) -> dict[str, object]:
        if not self.registry.authorize(context, "model:train"):
            raise AccessDenied()
        data, _ = self.training.accepted_input(batch_id, context)
        with self.registry.factory() as session:
            session.execute(
                text("SELECT pg_advisory_lock(hashtextextended(:key,0))"),
                {"key": "final-fit:" + str(run_id)},
            )
            try:
                existing = session.scalar(
                    select(RegistryCandidate).where(RegistryCandidate.training_run_id == run_id)
                )
                if existing:
                    if existing.trainer_id != context.actor_id or existing.registry_name != name:
                        raise AccessDenied()
                    candidate_id = existing.id
                else:
                    manifest = self.training.store.manifest(run_id)
                    if manifest["actor_id"] != context.actor_id:
                        raise AccessDenied()
                    fitted, lineage = fit_frozen_research(
                        data,
                        FeaturePipeline.from_repository(self.training.root),
                        self.training.store,
                        run_id,
                    )
                    if lineage["trainer_id"] != context.actor_id:
                        raise AccessDenied()
                    digest = write_bundle(
                        fitted,
                        lineage,
                        data.X.iloc[:3],
                        self.registry.store,
                        root=self.training.root,
                    )
                    candidate_id = self.registry.create_candidate(digest, name, context)
            finally:
                session.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"),
                    {"key": "final-fit:" + str(run_id)},
                )
        return self.registry.synchronize(candidate_id, context)
