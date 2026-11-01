"""Local registry credentials are service-owned; no analyst-supplied model paths."""

from sqlalchemy.engine import make_url

from mule_detection.application.bundle_service import BundleService
from mule_detection.application.model_approval_service import ModelApprovalService
from mule_detection.application.registry_service import RegistryService
from mule_detection.application.training_bootstrap import build_training
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.persistence.sqlalchemy import make_engine, session_factory
from mule_detection.registry.bundle_loader import BundleLoader
from mule_detection.registry.bundle_writer import BundleStore
from mule_detection.registry.mlflow_adapter import MlflowBackend
from mule_detection.registry.model_resolver import ModelResolver
from mule_detection.settings import Settings


def build_registry(settings: Settings) -> tuple[BundleService, ModelResolver, BundleLoader]:
    training = build_training(settings)
    secrets = settings.root_path / "secrets"
    backend = MlflowBackend(
        settings.mlflow_uri.get_secret_value(),
        (secrets / "mlflow_username").read_text().strip(),
        (secrets / "mlflow_password").read_text().strip(),
    )
    store = BundleStore(
        settings.artifact_root / "bundles",
        bytes.fromhex((secrets / "artifact_key").read_text().strip()),
    )
    registry = RegistryService(
        training.factory,
        store,
        backend,
        lambda context, action: (
            context.actor_id == "local-cli"
            and context.environment in {"local", "test", "research"}
            and action == "model:train"
        ),
    )
    resolver = ModelResolver(
        training.factory,
        backend,
        lambda context, action: (
            context.actor_id == "local-cli"
            and context.environment in {"local", "test", "research"}
            and action in {"model:deploy", "model:resolve"}
        ),
    )
    return BundleService(training, registry), resolver, BundleLoader(store, resolver.authorized)


def build_approval(settings: Settings) -> ModelApprovalService:
    if settings.environment not in {"local", "test", "research"}:
        raise DomainError(ErrorCode.CONFIGURATION_INVALID)
    # Explicit separate control-plane secret. Never fall back to runtime or put
    # migration/administrator credentials in an application approval process.
    path = settings.root_path / "secrets/model_approval_database_url"
    value = path.read_text().strip()
    if make_url(value).username != "mule_model_approver":
        raise DomainError(ErrorCode.CONFIGURATION_INVALID)
    return ModelApprovalService(
        session_factory(make_engine(value)),
        lambda context, action: context.actor_id == "local-cli" and action == "model:approve",
    )
