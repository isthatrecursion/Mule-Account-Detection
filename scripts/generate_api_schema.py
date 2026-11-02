"""Generate the HTTP contract using an isolated, non-serving schema-only application."""

import argparse
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from mule_detection.api.app import create_app
from mule_detection.api.auth import AuthConfig
from mule_detection.api.service import ApiService
from mule_detection.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def schema():
    with tempfile.TemporaryDirectory(dir=ROOT / "scratch") as directory:
        settings = Settings(
            environment="test",
            root_path=Path(directory),
            database_url="postgresql+psycopg://schema@localhost/mule_test_schema_only",
            mlflow_uri="http://localhost:5000",
            runtime_policy_path="config/test.yaml",
        )
        auth = AuthConfig(
            issuer="https://schema.example.test",
            audience="schema-only",
            isolated_test=True,
            static_jwks={"keys": []},
            groups={"schema": {"roles": ["analyst"], "scopes": ["schema-only"]}},
        )
        app = create_app(settings, lambda _: (auth, cast(ApiService, SimpleNamespace())))
        return app.openapi()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    (ROOT / "scratch").mkdir(exist_ok=True)
    path = ROOT / "contracts/api_openapi_v1.json"
    value = json.dumps(schema(), sort_keys=True, indent=2) + "\n"
    if args.check:
        if not path.exists() or path.read_text(encoding="utf-8") != value:
            raise SystemExit("HTTP contract snapshot differs")
    else:
        path.write_text(value, encoding="utf-8")
    print("PASSED: HTTP contract snapshot")


if __name__ == "__main__":
    main()
