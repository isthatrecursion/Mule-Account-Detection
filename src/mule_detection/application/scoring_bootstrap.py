"""Local-only scored research composition; qualified adapters remain gated."""

from mule_detection.application.context import ExecutionContext
from mule_detection.application.registry_bootstrap import build_registry
from mule_detection.application.scoring_service import ScoringService
from mule_detection.persistence.artifacts import ArtifactStore
from mule_detection.scoring.preflight import ResearchPreflight
from mule_detection.scoring.ranking import ReviewPolicy
from mule_detection.settings import Settings


def build_scoring(settings: Settings) -> ScoringService:
    bundles, resolver, loader = build_registry(settings)
    training = bundles.training

    def authorize(context: ExecutionContext, action: str) -> bool:
        return (
            context.actor_id == "local-cli"
            and context.environment in {"local", "test", "research"}
            and action in {"score:run", "score:read", "score:correct"}
        )

    key = bytes.fromhex((settings.root_path / "secrets/artifact_key").read_text().strip())
    return ScoringService(
        training.factory,
        ResearchPreflight(training, authorize),
        ArtifactStore(
            settings.artifact_root / "scoring",
            key,
            lambda context, scope, action: scope == "research" and authorize(context, "score:run"),
        ),
        resolver,
        loader,
        ReviewPolicy.load(settings.root_path / "config/review_policy.yaml"),
        authorize,
    )
