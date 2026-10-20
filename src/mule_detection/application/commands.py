"""Typed requests and explicit Phase 1 dispatch boundary."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from mule_detection import __version__
from mule_detection.application.context import ExecutionContext
from mule_detection.domain.clock import Clock
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.settings import Settings


@dataclass(frozen=True)
class CommandRequest:
    operation: str
    config_path: Path | None = None
    manifest_path: Path | None = None
    run_id: UUID | None = None
    batch_id: UUID | None = None
    model_version: str | None = None
    source_id: str | None = None
    scenario_path: Path | None = None
    mode: str | None = None


def dispatch(
    request: CommandRequest,
    settings: Settings,
    context: ExecutionContext,
    clock: Clock,
) -> dict[str, Any]:
    if request.operation == "health":
        return {
            "status": "foundation_only",
            "version": __version__,
            "environment": settings.environment,
            "correlation_id": str(context.correlation_id),
            "checked_at": clock.now().isoformat(),
            "config_fingerprint": settings.fingerprint(),
            "operational_readiness": "NOT_IMPLEMENTED",
            "qualified_approval": "NOT_GRANTED",
        }
    raise DomainError(ErrorCode.UNSUPPORTED_OPERATION, str(context.correlation_id))
