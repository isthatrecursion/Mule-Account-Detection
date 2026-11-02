"""Protected deployment configuration. Browser state cannot select endpoints or trust."""

import hashlib
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class UiConfigurationError(Exception):
    def __str__(self) -> str:
        return "Workspace startup requires API and identity gateway configuration."


class UiConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    environment: str = "research"
    api_base_url: str
    api_issuer: str
    api_audience: str = Field(min_length=1)
    gateway_url: str
    gateway_issuer: str
    gateway_audience: str
    gateway_jwks_url: str
    gateway_service_token: SecretStr
    login_url: str
    max_upload_bytes: int = Field(default=134217728, gt=0, le=2147483648)
    max_batch_rows: int = Field(default=100000, gt=0, le=1000000)
    poll_seconds: int = Field(default=5, ge=3, le=60)
    cache_seconds: int = Field(default=5, ge=1, le=15)
    verify_tls: Literal[True] = True
    connect_timeout: float = Field(default=3, gt=0, le=30)
    read_timeout: float = Field(default=20, gt=0, le=120)
    write_timeout: float = Field(default=60, gt=0, le=180)
    display_timezone: str = "UTC"
    max_poll_seconds: int = Field(default=300, ge=3, le=3600)
    page_size: int = Field(default=25, ge=1, le=100)
    mock_mode: bool = False
    late_data_context: bool = False
    show_deployment_status: bool = False
    grafana_base_url: str | None = None
    monitored_sources: tuple[str, ...] = ()
    extension_pages: tuple[
        Literal[
            "Models", "Source health", "Evidence reports", "Pilot metrics", "Retraining proposals"
        ],
        ...,
    ] = ()

    @model_validator(mode="after")
    def trust(self) -> "UiConfig":
        if self.grafana_base_url:
            grafana = urlsplit(self.grafana_base_url)
            if (
                grafana.scheme != "https"
                or not grafana.hostname
                or grafana.username
                or grafana.password
                or grafana.query
                or grafana.fragment
            ):
                raise ValueError("A fixed HTTPS Grafana origin is required")
        try:
            ZoneInfo(self.display_timezone)
        except (ValueError, KeyError):
            raise ValueError("A recognized display timezone is required") from None
        if self.mock_mode and self.environment not in {"local", "test"}:
            raise ValueError("Fixtures require an isolated local or test environment")
        if self.max_poll_seconds < self.poll_seconds:
            raise ValueError("The polling deadline must include at least one interval")
        for name in (
            "api_base_url",
            "api_issuer",
            "gateway_url",
            "gateway_issuer",
            "gateway_jwks_url",
            "login_url",
        ):
            url = urlsplit(getattr(self, name))
            local_api = (
                name == "api_base_url"
                and self.environment in {"local", "test", "research"}
                and url.hostname in {"127.0.0.1", "localhost", "::1"}
                and url.scheme == "http"
            )
            if (
                not url.hostname
                or url.username
                or url.password
                or url.fragment
                or url.query
                or url.scheme != "https"
                and not local_api
            ):
                raise ValueError("Trusted HTTPS endpoints are required")
        if len(self.gateway_service_token.get_secret_value()) < 32:
            raise ValueError("A protected gateway service credential is required")
        if self.environment not in {"local", "test", "research", "staging", "qualified"}:
            raise ValueError("Unsupported workspace environment")
        return self

    def fingerprint(self) -> str:
        public = self.model_dump(mode="json", exclude={"gateway_service_token"})
        return hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()

    @classmethod
    def load(cls, root: Path) -> "UiConfig":
        try:
            return cls.model_validate_json((root / "secrets/ui.json").read_bytes())
        except Exception:
            raise UiConfigurationError() from None
