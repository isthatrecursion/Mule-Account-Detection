"""Write ignored local connection secret files; never print credentials or overwrite files."""

import argparse
import json
import re
from pathlib import Path

from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=55432)
    parser.add_argument("--test-database", default="mule_test_local")
    parser.add_argument("--test-config", default="test_connections.json")
    args = parser.parse_args()
    if (
        not 1 <= args.port <= 65535
        or re.fullmatch(r"mule_test_[a-z0-9_]+", args.test_database) is None
        or Path(args.test_config).name != args.test_config
    ):
        parser.error(
            "A valid local port, test database name and simple config filename are required"
        )
    secrets = ROOT / "secrets"

    def url(role: str, database: str, *, driver: str = "postgresql+psycopg") -> str:
        secret_name = "postgres_admin_password" if role == "postgres" else role + "_password"
        password = (secrets / secret_name).read_text().strip()
        return URL.create(
            driver,
            username=role,
            password=password,
            host="127.0.0.1",
            port=args.port,
            database=database,
        ).render_as_string(hide_password=False)

    values = {
        "runtime_database_url": url("mule_runtime", "mule_operational"),
        "tracking_database_url": url("mule_tracking", "mule_tracking"),
        "migration_database_url": url("mule_migration", "mule_operational"),
        "test_admin_database_url": url("postgres", "postgres", driver="postgresql"),
        args.test_config: json.dumps(
            {
                "MULE_TEST_ENVIRONMENT": "test",
                "MULE_TEST_DATABASE_URL": url("mule_migration", args.test_database),
                "MULE_TEST_RUNTIME_DATABASE_URL": url("mule_runtime", args.test_database),
                "MULE_TEST_READONLY_DATABASE_URL": url("mule_readonly", args.test_database),
                "MULE_TEST_TRACKING_DATABASE_URL": url("mule_tracking", "mule_tracking"),
            }
        ),
    }
    for name, value in values.items():
        with (secrets / name).open("x", encoding="utf-8") as stream:
            stream.write(value)
        (secrets / name).chmod(0o600)
    print("Local connection files written under ignored secrets; credentials omitted.")


if __name__ == "__main__":
    main()
