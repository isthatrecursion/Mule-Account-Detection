"""Composition root. Service-owned adapters receive verified task authority, never CLI identity."""

import json
from typing import Any
from uuid import UUID

from mule_detection.api.auth import ROLE_PERMISSIONS, AuthConfig, Principal
from mule_detection.api.service import ApiService
from mule_detection.application.context import ExecutionContext
from mule_detection.persistence.artifacts import ArtifactStore
from mule_detection.persistence.models import ApiTask
from mule_detection.persistence.sqlalchemy import make_engine, session_factory
from mule_detection.settings import Settings


def build_service(settings: Settings, auth: AuthConfig) -> ApiService:
    from mule_detection.application.ingest_bootstrap import build_ingest
    from mule_detection.domain.contracts.common import canonical_hash
    from mule_detection.persistence.raw_store import RawStore

    # Qualified adapters still require the separate source qualification work in the roadmap.
    intake = build_ingest(settings)
    key = bytes.fromhex((settings.root_path / "secrets/artifact_key").read_text().strip())
    factory = session_factory(make_engine(settings.database_url.get_secret_value()))

    def storage_authority(
        context: ExecutionContext, scope: str, action: str, *, evidence: bool = False
    ) -> bool:
        from datetime import UTC, datetime

        from mule_detection.persistence.models import ApiIdentity

        with factory() as session:
            identity = session.get(ApiIdentity, context.actor_id)
            return bool(
                identity
                and not identity.disabled
                and identity.valid_until > datetime.now(UTC)
                and (
                    scope in identity.grants.get("scopes", [])
                    or evidence
                    and scope == "research"
                    and "case:read" in identity.grants.get("permissions", [])
                )
            )

    outcomes_path = settings.root_path / "secrets/outcome_sources.json"
    outcomes = json.loads(outcomes_path.read_bytes()) if outcomes_path.exists() else {}
    service = ApiService(
        settings,
        factory,
        ArtifactStore(settings.artifact_root / "api", key, storage_authority),
        RawStore(settings.artifact_root / "api-uploads", key, max_bytes=settings.max_upload_bytes),
        policy_hash=canonical_hash(
            {
                "auth": auth.model_dump(mode="json"),
                "roles": {r: sorted(p) for r, p in ROLE_PERMISSIONS.items()},
            }
        ),
        sources={name: profile.access_scope for name, profile in intake.profiles.items()},
        outcome_sources=outcomes,
        evidence_store=ArtifactStore(
            settings.artifact_root / "scoring",
            key,
            lambda context, scope, action: storage_authority(context, scope, action, evidence=True),
        ),
    )

    def checked(task: ApiTask, principal: Principal, permission: str) -> bool:
        current = service.worker_principal(task)
        current.require(permission)
        if current.actor_id != principal.actor_id:
            return False
        if task.kind in {"score", "train"}:
            with factory() as session:
                service.batch_in(session, UUID(str(task.request["batch_id"])), current)
        return True

    def ingest(task: ApiTask, principal: Principal, context: ExecutionContext) -> dict[str, Any]:
        import io

        from mule_detection.application.ingest_service import IngestService

        adapter = IngestService(
            factory,
            intake.store,
            intake.profiles,
            intake.policy,
            authorize=lambda ctx, scope, action: (
                scope in principal.scopes and checked(task, principal, "batch:intake")
            ),
            max_rows=settings.max_batch_rows,
            research_adapter=intake.research_adapter,
            trusted_split=intake.trusted_split,
        )
        result = adapter.ingest(
            io.BytesIO(service.raw.read(str(task.request["digest"]))),
            task.request["declaration"],
            context,
            idempotency_key=task.job_id,
            filename=str(task.request["filename"]),
        )
        return {
            "batch_id": str(result.batch_id) if result.batch_id else None,
            "outcome": result.outcome,
            "row_count": result.row_count,
            "finding_codes": list(result.finding_codes),
        }

    def training(task: ApiTask, principal: Principal, context: ExecutionContext) -> dict[str, Any]:
        from mule_detection.application.training_bootstrap import build_training
        from mule_detection.application.training_service import TrainingService
        from mule_detection.settings import read_yaml
        from mule_detection.training.evaluation_policy import TrainingConfig

        base = build_training(settings)
        adapter = TrainingService(
            factory,
            base.raw_store,
            base.store,
            base.adapter,
            base.split_path,
            base.root,
            authorize=lambda ctx, action: checked(task, principal, "train:submit"),
        )
        config = TrainingConfig.model_validate(
            read_yaml(settings.root_path / "config/model_candidates.yaml")
        )
        adapter.train(UUID(str(task.request["batch_id"])), task.job_id, config, context)
        return {"training_run_id": str(task.job_id), "state": "CANDIDATE_ONLY"}

    def scoring(task: ApiTask, principal: Principal, context: ExecutionContext) -> dict[str, Any]:
        from mule_detection.application.registry_bootstrap import build_registry
        from mule_detection.application.scoring_service import ScoringService
        from mule_detection.domain.contracts.scoring import ScoringRequest
        from mule_detection.registry.model_resolver import ModelResolver
        from mule_detection.scoring.preflight import ResearchPreflight
        from mule_detection.scoring.ranking import ReviewPolicy

        bundles, base_resolver, loader = build_registry(settings)

        def authorize(ctx: ExecutionContext, action: str) -> bool:
            return checked(task, principal, "score:submit")

        resolver = ModelResolver(factory, base_resolver.backend, authorize)
        adapter = ScoringService(
            factory,
            ResearchPreflight(bundles.training, authorize),
            ArtifactStore(
                settings.artifact_root / "scoring",
                key,
                lambda ctx, scope, action: (
                    scope == "research" and checked(task, principal, "score:submit")
                ),
            ),
            resolver,
            loader,
            ReviewPolicy.load(settings.review_policy_path),
            authorize,
        )
        request = ScoringRequest.model_validate(
            {**task.request, "environment": settings.environment}
        )
        identity = adapter.create(request, context)
        return adapter.run(UUID(identity["job_id"]), context)

    service.handlers = {"intake": ingest, "score": scoring, "train": training}
    return service
