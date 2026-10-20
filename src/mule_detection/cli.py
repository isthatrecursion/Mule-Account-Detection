"""Thin CLI adapter. Exit 2=arguments, 3=config, 4=unsupported, 1=internal error."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import NoReturn
from uuid import UUID

from mule_detection import __version__
from mule_detection.application.commands import CommandRequest, dispatch
from mule_detection.application.context import ExecutionContext
from mule_detection.application.logging import configure_logging
from mule_detection.domain.clock import MonotonicTimer, SystemClock
from mule_detection.domain.errors import EXIT_CODES, DomainError, ErrorCode
from mule_detection.settings import load_settings


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        error = DomainError(ErrorCode.INVALID_ARGUMENTS)
        self.exit(2, json.dumps({"error": error.public()}) + "\n")


def parser() -> argparse.ArgumentParser:
    result = SafeArgumentParser(prog="mule-detection", description=__doc__)
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("--root", type=Path, default=Path.cwd())
    result.add_argument(
        "--environment", choices=["local", "test", "research", "staging", "qualified"]
    )
    result.add_argument("--settings", type=Path)
    result.add_argument("--dotenv", type=Path)
    result.add_argument("--secrets-dir", type=Path)
    commands = result.add_subparsers(dest="operation", required=True)
    commands.add_parser("health", help="Check configuration only; no operational readiness claim")
    validate = commands.add_parser("validate-batch")
    validate.add_argument("--manifest", type=Path, required=True)
    train = commands.add_parser("train")
    train.add_argument("--config", type=Path, required=True)
    train.add_argument("--mode", choices=["research", "qualified"], required=True)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--run-id", type=UUID, required=True)
    score = commands.add_parser("score")
    score.add_argument("--batch-id", type=UUID, required=True)
    score.add_argument("--model-version", required=True)
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--source", required=True)
    replay = commands.add_parser("replay")
    replay.add_argument("--scenario", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    context = ExecutionContext.create(
        "local-cli", args.environment or os.getenv("MULE_ENVIRONMENT", "local")
    )
    logger = configure_logging()
    timer = MonotonicTimer()
    extra = {"event": "command_started", "correlation_id": str(context.correlation_id)}
    logger.info("", extra=extra)
    try:
        settings = load_settings(
            args.root,
            environment=args.environment,
            config_path=args.settings,
            dotenv_path=args.dotenv,
            secrets_dir=args.secrets_dir,
        )
        logger.info(
            "",
            extra={
                **extra,
                "event": "configuration_loaded",
                "config_fingerprint": settings.fingerprint(),
            },
        )
        request = CommandRequest(
            operation=args.operation,
            config_path=getattr(args, "config", None),
            manifest_path=getattr(args, "manifest", None),
            run_id=getattr(args, "run_id", None),
            batch_id=getattr(args, "batch_id", None),
            model_version=getattr(args, "model_version", None),
            source_id=getattr(args, "source", None),
            scenario_path=getattr(args, "scenario", None),
            mode=getattr(args, "mode", None),
        )
        result = dispatch(request, settings, context, SystemClock())
        logger.info(
            "",
            extra={
                **extra,
                "event": "command_completed",
                "duration_seconds": timer.elapsed_seconds(),
            },
        )
        print(json.dumps(result))
        return 0
    except DomainError as error:
        failure = error
        failure.correlation_id = str(context.correlation_id)
    except Exception:
        # Sensitive exception content/tracebacks are deliberately excluded from ordinary output.
        failure = DomainError(ErrorCode.INTERNAL_ERROR, str(context.correlation_id))
    logger.error("", extra={**extra, "event": "command_failed", "error_code": failure.code.value})
    print(json.dumps({"error": failure.public()}))
    return EXIT_CODES[failure.code]


if __name__ == "__main__":
    raise SystemExit(main())
