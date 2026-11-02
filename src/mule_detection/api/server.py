"""Optional API executable. Trust configuration is mandatory for HTTP and worker processes."""

import argparse
import json
from pathlib import Path
from uuid import UUID

from mule_detection.settings import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--environment",
        choices=("local", "test", "research", "staging", "qualified"),
        default="research",
    )
    parser.add_argument("--worker-once", action="store_true")
    parser.add_argument("--job-id", type=UUID)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.job_id and not args.worker_once:
        parser.error("--job-id requires --worker-once")
    try:
        settings = load_settings(
            args.root, environment=args.environment, secrets_dir=args.root / "secrets"
        )
        if args.worker_once:
            from mule_detection.api.auth import AuthConfig
            from mule_detection.api.bootstrap import build_service

            service = build_service(
                settings, AuthConfig.load(settings.root_path, settings.environment)
            )
            identity = service.run_one(args.job_id)
            print(json.dumps({"job_id": str(identity) if identity else None}))
        else:
            import uvicorn

            from mule_detection.api.app import create_app

            uvicorn.run(
                create_app(settings),
                host=args.host,
                port=args.port,
                access_log=False,
                server_header=False,
            )
        return 0
    except Exception:
        print(json.dumps({"error": {"code": "API_STARTUP_OR_WORKER_FAILED"}}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
