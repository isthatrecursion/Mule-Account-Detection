"""Capture/compare synthetic test-database state across an operator-run server restart."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from mule_detection.persistence.models import Base
from mule_detection.persistence.sqlalchemy import make_engine

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connections-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stage", choices=["before", "after"], required=True)
    args = parser.parse_args()
    config = json.loads(args.connections_file.read_text())
    if config.get("MULE_TEST_ENVIRONMENT") != "test":
        parser.error("An explicit test environment is required")
    destination = (ROOT / args.output_dir).resolve()
    if not destination.is_relative_to(ROOT / "artifacts/phase3"):
        parser.error("Evidence must be under artifacts/phase3")
    engine = make_engine(config["MULE_TEST_DATABASE_URL"])
    if not (engine.url.database or "").startswith("mule_test_") or engine.url.query:
        parser.error("A dedicated test database without URL options is required")
    state = {}
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            actual = connection.scalar(text("SELECT current_database()"))
            if actual != engine.url.database:
                parser.error("The connected database differs from the guarded test name")
            connection.execute(text("SET TIME ZONE 'UTC'"))
            for table in sorted(Base.metadata.tables):
                records = sorted(
                    connection.scalars(text(f'SELECT to_jsonb(t)::text FROM "{table}" t'))
                )
                state[table] = {
                    "count": len(records),
                    "sha256": hashlib.sha256("\n".join(records).encode()).hexdigest(),
                }
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            version = connection.scalar(text("SELECT version()"))
            server_started_at = str(connection.scalar(text("SELECT pg_postmaster_start_time()")))
    finally:
        engine.dispose()
    snapshot = {"database": actual, "revision": revision, "tables": state}
    destination.mkdir(parents=True, exist_ok=True)
    record = {
        "captured_at": datetime.now(UTC).isoformat(),
        "postgresql_version": version,
        "server_started_at": server_started_at,
        "snapshot": snapshot,
    }
    with (destination / f"{args.stage}.json").open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
    if args.stage == "before":
        print(
            "Synthetic state captured; restart the dedicated PostgreSQL server before comparison."
        )
        return 0
    previous = json.loads((destination / "before.json").read_text())
    passed = previous["snapshot"] == snapshot and previous["server_started_at"] != server_started_at
    report = {
        "pass_fail": "PASSED" if passed else "FAILED",
        "scope": "Committed synthetic table state survives operator-run PostgreSQL restart",
        "executed_at": datetime.now(UTC).isoformat(),
        "before": "before.json",
        "after": "after.json",
        "tables_checked": len(state),
        "revision": revision,
        "server_restart_observed": previous["server_started_at"] != server_started_at,
    }
    with (destination / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    manifest = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(destination.glob("*.json"))
    }
    with (destination / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
    print(f"{report['pass_fail']}: restart comparison across {len(state)} synthetic tables")
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
