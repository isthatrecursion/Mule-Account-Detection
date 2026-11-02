"""Local-only composition; shared access requires the later authenticated API."""

from mule_detection.application.ingest_bootstrap import build_ingest
from mule_detection.application.training_service import TrainingService
from mule_detection.settings import Settings
from mule_detection.training.report import RunStore


def build_training(settings: Settings) -> TrainingService:
    intake = build_ingest(settings)
    assert intake.research_adapter is not None and intake.trusted_split is not None
    key = bytes.fromhex(
        (settings.root_path / "secrets/artifact_key").read_text(encoding="ascii").strip()
    )
    return TrainingService(
        intake.factory,
        intake.store,
        RunStore(settings.artifact_root / "training", key),
        intake.research_adapter,
        intake.trusted_split,
        settings.root_path,
        authorize=lambda context, action: (
            context.actor_id == "local-cli"
            and context.environment in {"local", "test", "research"}
            and action == "model:train"
        ),
    )
