"""Fail-closed workspace launcher; protected deployment settings precede UI startup."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from ui.config import UiConfig, UiConfigurationError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    try:
        config = UiConfig.load(args.root.resolve())
        if config.mock_mode:
            raise UiConfigurationError()
    except UiConfigurationError:
        print(json.dumps({"error": {"code": "UI_IDENTITY_CONFIGURATION_REQUIRED"}}))
        return 3
    if not 1 <= args.port <= 65535:
        return 2
    environment = dict(os.environ)
    environment["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW
    else:
        creation_flags = 0
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(Path(__file__).with_name("app.py")),
            "--server.address=127.0.0.1",
            f"--server.port={args.port}",
            "--server.headless=true",
            "--server.enableXsrfProtection=true",
            "--server.enableCORS=true",
            "--client.showSidebarNavigation=false",
            f"--server.maxUploadSize={max(1, config.max_upload_bytes // 1048576)}",
        ],
        cwd=args.root.resolve(),
        env=environment,
        creationflags=creation_flags,
    )


if __name__ == "__main__":
    raise SystemExit(main())
