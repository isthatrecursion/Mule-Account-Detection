"""Thin CLI adapter. Exit 2=arguments, 3=config, 4=unsupported, 1=internal error."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, NoReturn
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
    validate.add_argument("--request-id", type=UUID, required=True)
    validate.add_argument("--format", default="csv")
    validate.add_argument("--filename", default="upload.csv")
    validate.add_argument("--replay-of", type=UUID)
    recover = commands.add_parser("recover-intake")
    recover.add_argument("--apply", action="store_true")
    recover.add_argument("--delete-orphans", action="store_true")
    recover.add_argument("--retention-seconds", type=int, default=86400)
    train = commands.add_parser("train")
    train.add_argument("--config", type=Path, required=True)
    train.add_argument("--mode", choices=["research", "qualified_temporal"], required=True)
    train.add_argument("--batch-id", type=UUID, required=True)
    train.add_argument("--run-id", type=UUID, required=True)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--run-id", type=UUID, required=True)
    bundle = commands.add_parser("package-model")
    bundle.add_argument("--batch-id", type=UUID, required=True)
    bundle.add_argument("--run-id", type=UUID, required=True)
    bundle.add_argument("--name", required=True)
    approve = commands.add_parser("approve-model")
    approve.add_argument("--candidate-id", type=UUID, required=True)
    approve.add_argument("--target-environment", required=True)
    approve.add_argument(
        "--target",
        choices=[
            "RESEARCH_DEMO",
            "APPROVED_FOR_SHADOW",
            "APPROVED_FOR_PILOT",
            "REJECTED",
            "RETIRED",
        ],
        required=True,
    )
    approve.add_argument("--reason", required=True)
    approve.add_argument("--request-id", type=UUID, required=True)
    for operation in ("deploy-model", "rollback-model"):
        deploy = commands.add_parser(operation)
        deploy.add_argument("--candidate-id", type=UUID, required=True)
        deploy.add_argument("--target-environment", required=True)
        deploy.add_argument("--alias", required=True)
        deploy.add_argument("--expected-version", type=int, required=True)
        deploy.add_argument("--reason", required=True)
    registration = commands.add_parser("reconcile-model")
    registration.add_argument("--candidate-id", type=UUID, required=True)
    mirror = commands.add_parser("reconcile-model-alias")
    mirror.add_argument("--target-environment", required=True)
    mirror.add_argument("--alias", required=True)
    score = commands.add_parser("score")
    score.add_argument("--batch-id", type=UUID, required=True)
    score.add_argument("--model-version", required=True)
    score.add_argument("--target-environment", default="research")
    score.add_argument("--replay-id", type=UUID)
    score.add_argument("--replay-of", type=UUID)
    score.add_argument("--affected-key", action="append", default=[])
    score.add_argument("--enqueue-only", action="store_true")
    scoring_job = commands.add_parser("score-job")
    scoring_job.add_argument("--job-id", type=UUID, required=True)
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
    result: dict[str, Any]
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
        if args.operation in {"validate-batch", "recover-intake"}:
            from mule_detection.application.ingest_bootstrap import build_ingest
            from mule_detection.application.intake_recovery import IntakeRecovery

            service = build_ingest(settings)
            if args.operation == "recover-intake":
                recovered = IntakeRecovery(service.factory, service.store).run(
                    context,
                    apply=args.apply,
                    delete_orphans=args.delete_orphans,
                    retention_seconds=args.retention_seconds,
                )
                print(json.dumps(recovered))
                return 0
            if args.manifest.stat().st_size > 262144:
                raise DomainError(ErrorCode.CONTRACT_INVALID)

            def unique_metadata(pairs: list[tuple[str, object]]) -> dict[str, object]:
                value: dict[str, object] = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError("Duplicate metadata key")
                    value[key] = item
                return value

            try:
                metadata = json.loads(
                    args.manifest.read_text(encoding="utf-8"), object_pairs_hook=unique_metadata
                )
            except (ValueError, UnicodeError):
                metadata = {"invalid_metadata": True}
            intake_result = service.ingest(
                sys.stdin.buffer,
                metadata,
                context,
                idempotency_key=args.request_id,
                filename=args.filename,
                file_format=args.format,
                replay_of=args.replay_of,
            )
            print(intake_result.model_dump_json())
            return 0 if intake_result.outcome == "ACCEPTED" else 5
        if args.operation in {
            "package-model",
            "approve-model",
            "deploy-model",
            "rollback-model",
            "reconcile-model",
            "reconcile-model-alias",
        }:
            from mule_detection.application.registry_bootstrap import build_approval, build_registry

            if args.operation == "approve-model":
                decision = build_approval(settings).decide(
                    args.candidate_id,
                    args.target_environment,
                    args.target,
                    context,
                    reason=args.reason,
                    idempotency_key=args.request_id,
                )
                result = {"decision_id": str(decision)}
            else:
                bundles, resolver, loader = build_registry(settings)
                if args.operation == "package-model":
                    result = bundles.build(args.batch_id, args.run_id, args.name, context)
                elif args.operation == "reconcile-model":
                    result = bundles.registry.synchronize(args.candidate_id, context)
                elif args.operation == "reconcile-model-alias":
                    resolver.reconcile_alias(args.target_environment, args.alias, context)
                    result = {"state": "MIRROR_RECONCILED"}
                else:
                    version = resolver.deploy(
                        args.candidate_id,
                        args.target_environment,
                        args.alias,
                        context,
                        expected_version=args.expected_version,
                        reason=args.reason,
                        loader=loader,
                        rollback=args.operation == "rollback-model",
                    )
                    result = {"deployment_version": version}
            print(json.dumps(result))
            return 0
        if args.operation in {"score", "score-job"}:
            from mule_detection.application.scoring_bootstrap import build_scoring
            from mule_detection.domain.contracts.common import parse_contract
            from mule_detection.domain.contracts.scoring import ScoringRequest

            if args.operation == "score":
                score_request = parse_contract(
                    ScoringRequest,
                    {
                        "batch_id": str(args.batch_id),
                        "bundle_digest": args.model_version,
                        "environment": args.target_environment,
                        "replay_id": str(args.replay_id) if args.replay_id else None,
                        "replay_of": str(args.replay_of) if args.replay_of else None,
                        "affected_keys": args.affected_key,
                    },
                )
                scoring_service = build_scoring(settings)
                result = scoring_service.create(score_request, context)
                if not args.enqueue_only:
                    result = scoring_service.run(UUID(result["job_id"]), context)
            else:
                scoring_service = build_scoring(settings)
                result = scoring_service.run(args.job_id, context)
            print(json.dumps(result))
            return 0
        if args.operation in {"train", "evaluate"}:
            from mule_detection.application.training_bootstrap import build_training
            from mule_detection.settings import read_yaml
            from mule_detection.training.evaluation_policy import TrainingConfig, require_mode

            if args.operation == "train":
                # Validate mode before building database/key adapters.
                require_mode(args.mode, "research")
                config_path = (settings.root_path / args.config).resolve()
                if not config_path.is_relative_to(settings.root_path):
                    raise DomainError(ErrorCode.INVALID_ARGUMENTS)
                try:
                    config = TrainingConfig.model_validate(read_yaml(config_path))
                except (OSError, ValueError):
                    raise DomainError(ErrorCode.CONFIGURATION_INVALID) from None
                if config.mode != args.mode:
                    raise DomainError(ErrorCode.CONTRACT_INVALID)
                result = build_training(settings).train(args.batch_id, args.run_id, config, context)
            else:
                result = build_training(settings).evaluate(args.run_id, context)
            print(json.dumps(result))
            return 0
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
