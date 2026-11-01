"""Container-only UI entry: protected config first, then private-network Streamlit."""

import json
import os
import sys
from pathlib import Path

from ui.config import UiConfig, UiConfigurationError


def main() -> int:
    try:
        config = UiConfig.load(Path.cwd())
        if config.mock_mode or config.environment not in {"research", "staging", "qualified"}:
            raise UiConfigurationError()
    except UiConfigurationError:
        print(json.dumps({"error": {"code": "UI_IDENTITY_CONFIGURATION_REQUIRED"}}))
        return 3
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(Path(__file__).with_name("app.py")),
            "--server.address=0.0.0.0",
            "--server.port=8501",
            "--server.headless=true",
            "--server.fileWatcherType=none",
            "--server.enableXsrfProtection=true",
            "--server.enableCORS=true",
            "--browser.gatherUsageStats=false",
            "--client.showErrorDetails=none",
            "--client.showSidebarNavigation=false",
            f"--server.maxUploadSize={max(1, config.max_upload_bytes // 1048576)}",
        ],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
