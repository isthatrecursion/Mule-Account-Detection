"""Local CLI composition; source profiles and split paths are server-owned configuration."""

from pathlib import Path

from mule_detection.application.ingest_service import IngestService
from mule_detection.domain.contracts.common import parse_contract
from mule_detection.domain.feature_policy import FeaturePolicy
from mule_detection.ingestion.intake import SourceProfile
from mule_detection.ingestion.research_adapter import ResearchAdapter
from mule_detection.persistence.raw_store import RawStore
from mule_detection.persistence.sqlalchemy import make_engine, session_factory
from mule_detection.settings import Settings, read_yaml


def build_ingest(settings: Settings) -> IngestService:
    if settings.environment not in {"local", "test", "research"}:
        raise ValueError("Shared ingestion requires authenticated source authority")
    root = settings.root_path
    config = read_yaml(root / "config/ingestion.yaml")
    profiles = [SourceProfile.model_validate(p) for p in config["sources"]]
    policy = parse_contract(FeaturePolicy, read_yaml(root / "config/feature_policy.yaml"))
    adapter = ResearchAdapter.from_repository(root)
    research = SourceProfile(
        source_id="registered-research",
        schema_id="research_v1",
        data_tier="research",
        policy_version=policy.policy_version,
        access_scope="research-development",
        columns=adapter.schema.columns,
        identity_columns=("Unnamed: 0",),
        missing_tokens=adapter.schema.missing_tokens,
        expected_dataset_hash=adapter.trusted_dataset_sha256,
    )
    profiles.append(research)
    if len({p.source_id for p in profiles}) != len(profiles):
        raise ValueError("Duplicate server source registration")
    key_path = root / "secrets/artifact_key"
    if not key_path.resolve().is_relative_to(root):
        raise ValueError("Invalid key location")
    key = bytes.fromhex(key_path.read_text(encoding="ascii").strip())
    split_path = (root / Path(config["research_split_register"])).resolve()
    if not split_path.is_relative_to(root):
        raise ValueError("Split register must remain in controlled storage")
    # This adapter is local-only. A future API must inject authenticated server scopes.
    return IngestService(
        session_factory(make_engine(settings.database_url.get_secret_value())),
        RawStore(settings.artifact_root / "intake", key, max_bytes=settings.max_upload_bytes),
        {p.source_id: p for p in profiles},
        policy,
        authorize=lambda context, scope, action: (
            context.actor_id == "local-cli" and context.environment in {"local", "test", "research"}
        ),
        max_rows=settings.max_batch_rows,
        research_adapter=adapter,
        trusted_split=split_path,
    )
