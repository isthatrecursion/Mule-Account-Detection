"""One settings boundary: environment > opt-in dotenv > secrets directory > YAML."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlsplit

import yaml
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from mule_detection.domain.errors import DomainError, ErrorCode

Environment = Literal["local", "test", "research", "staging", "qualified"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MULE_",
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )
    environment: Environment
    root_path: Path = Field(repr=False)
    database_url: SecretStr
    mlflow_uri: SecretStr
    artifact_root: Path = Path("var/artifacts")
    review_policy_path: Path = Path("config/review_policy.yaml")
    permissions_path: Path = Path("config/permissions.yaml")
    runtime_policy_path: Path
    max_upload_bytes: int = Field(default=134217728, gt=0, le=2147483648)
    max_batch_rows: int = Field(default=100000, gt=0, le=1000000)
    worker_count: int = Field(default=1, gt=0, le=32)
    batch_cadence_seconds: int = Field(default=86400, gt=0)
    reconciliation_scan_seconds: int = Field(default=60, gt=0, le=60)
    allowed_lateness_seconds: int = Field(default=600, gt=0)
    # A requested loader restriction, never an authoritative approval/validation record.
    model_tier: Literal["research_demo", "approved_for_shadow", "approved_for_pilot"] = (
        "research_demo"
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return env_settings, dotenv_settings, file_secret_settings, init_settings

    @model_validator(mode="after")
    def validate_boundaries(self) -> Self:
        root = self.root_path.resolve()
        object.__setattr__(self, "root_path", root)
        for name in (
            "artifact_root",
            "review_policy_path",
            "permissions_path",
            "runtime_policy_path",
        ):
            path = getattr(self, name)
            resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError("Configured paths must remain inside the application root")
            object.__setattr__(self, name, resolved)
        database = urlsplit(self.database_url.get_secret_value())
        tracking = urlsplit(self.mlflow_uri.get_secret_value())
        if (
            database.scheme != "postgresql+psycopg"
            or not database.hostname
            or not database.path.strip("/")
        ):
            raise ValueError("A PostgreSQL database endpoint is required")
        if tracking.scheme not in ("http", "https") or not tracking.hostname:
            raise ValueError("An HTTP(S) tracking endpoint is required")
        if self.environment in ("qualified", "staging") and self.model_tier == "research_demo":
            raise ValueError("Research model restriction is incompatible with this environment")
        if self.environment in ("local", "test", "research") and self.model_tier != "research_demo":
            raise ValueError("Research environments require research model restrictions")
        return self

    def fingerprint(self) -> str:
        # Secret endpoints are omitted, rather than weakly hashed or displayed.
        public = self.model_dump(mode="json", exclude={"database_url", "mlflow_uri"})
        public["policy_hashes"] = {
            str(path.relative_to(self.root_path)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (self.review_policy_path, self.permissions_path, self.runtime_policy_path)
        }
        return hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()


def read_yaml(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Configuration exceeds the allowed size")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Configuration must be a string-keyed mapping")
    return value


def load_settings(
    root: Path,
    *,
    environment: str | None = None,
    config_path: Path | None = None,
    dotenv_path: Path | None = None,
    secrets_dir: Path | None = None,
) -> Settings:
    """Load safely; public errors never include raw validation input or credentials.

    Environment selection is an explicit argument or MULE_ENVIRONMENT, then local.
    Conflicting selectors fail. Secrets must not appear in committed YAML.
    """
    try:
        root = root.resolve()
        env_selection = os.environ.get("MULE_ENVIRONMENT")
        if environment and env_selection and environment != env_selection:
            raise ValueError("Conflicting environment selectors")
        selected = environment or env_selection or "local"
        if selected not in {"local", "test", "research", "staging", "qualified"}:
            raise ValueError("Unknown environment")
        config = config_path or Path("config/environments") / f"{selected}.yaml"
        config = (root / config).resolve()
        if not config.is_relative_to(root):
            raise ValueError("Configuration must remain inside the application root")
        document = read_yaml(config)
        if document.get("environment", selected) != selected:
            raise ValueError("Environment file contradicts the selected environment")
        runtime = document.get("runtime", {})
        if not isinstance(runtime, dict):
            raise ValueError("Runtime configuration must be a mapping")
        if {"database_url", "mlflow_uri"}.intersection(runtime):
            raise ValueError("Inject endpoint settings through environment or secret files")
        policy_name = "qualified" if selected in ("qualified", "staging") else "research"
        init: dict[str, Any] = {
            **runtime,
            "environment": selected,
            "root_path": root,
            "runtime_policy_path": f"config/environments/{policy_name}.yaml",
            "_env_file": dotenv_path,
            "_secrets_dir": secrets_dir,
        }
        settings = Settings(**init)
        if settings.root_path != root or settings.environment != selected:
            raise ValueError("Root and environment cannot be replaced by another settings source")
        policy = read_yaml(settings.runtime_policy_path)
        if (
            policy["environment"] != policy_name
            or policy["tier_authority"]["dashboard_request_or_environment_override_allowed"]
            or policy["automatic_account_action_enabled"]
            or settings.model_tier not in policy["allowed_model_tiers"]
        ):
            raise ValueError("Runtime policy contradicts environment restrictions")
        if policy_name == "qualified":
            gates = policy["approval_predicate"]
            if (
                not gates["all_critical_dependencies_closed"]
                or not gates["independent_approver_required"]
                or gates["self_approval_allowed"]
                or gates["research_bundle_allowed"]
                or gates["alias_change_implies_qualification"]
            ):
                raise ValueError("Qualified approval policy cannot waive research boundaries")
        for path in (settings.review_policy_path, settings.permissions_path):
            read_yaml(path)
        settings.artifact_root.mkdir(parents=True, exist_ok=True)
        # Probe actual write permission, not just os.access on Windows ACLs.
        with tempfile.TemporaryFile(dir=settings.artifact_root):
            pass
        return settings
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        raise DomainError(ErrorCode.CONFIGURATION_INVALID) from None
