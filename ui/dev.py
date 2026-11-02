"""Explicit loopback-only synthetic preview: python -m ui.dev [--workspace]."""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", action="store_true")
    parser.add_argument(
        "--demo", action="store_true", help="Clean synthetic acceptance walkthrough"
    )
    parser.add_argument(
        "--extensions", action="store_true", help="Show proposed read-only extension fixtures"
    )
    parser.add_argument(
        "--late-stage",
        choices=["COMPLETE", "BUFFERING", "STALE", "PROVISIONAL_HIGHER", "CORRECTED", "RECONCILED"],
    )
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    if (args.extensions or args.late_stage) and not (args.workspace or args.demo):
        parser.error("Extension/timeline previews require --workspace")
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535")
    environment = {
        **os.environ,
        "MAD_UI_FIXTURE_ENTRY": "demo"
        if args.demo
        else "workspace"
        if args.workspace
        else "gallery",
        "MAD_UI_FIXTURE_EXTENSIONS": "1" if args.extensions else "0",
        "MAD_UI_FIXTURE_LATE_STAGE": args.late_stage or "",
    }
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(Path(__file__).parent / "mock" / "entry.py"),
            "--server.address=127.0.0.1",
            f"--server.port={args.port}",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
        ],
        env=environment,
        check=True,
    )


if __name__ == "__main__":
    main()
