"""Record a new synthetic-only Phase 3 verification run; credentials never enter evidence."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--with-reference",
        action="store_true",
        help="Approved local machine only; verify preserved reference hashes",
    )
    parser.add_argument(
        "--connections-file", type=Path, help="Ignored local JSON containing MULE_TEST_* variables"
    )
    args = parser.parse_args()
    destination = (ROOT / args.output_dir).resolve()
    if not destination.is_relative_to(ROOT / "artifacts/phase3") or destination.exists():
        parser.error("Use a new directory under artifacts/phase3")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("MULE_")}
    selected = {key: value for key, value in os.environ.items() if key.startswith("MULE_TEST_")}
    if args.connections_file:
        selected.update(json.loads(args.connections_file.read_text()))
    allowed = {
        "MULE_TEST_ENVIRONMENT",
        "MULE_TEST_DATABASE_URL",
        "MULE_TEST_RUNTIME_DATABASE_URL",
        "MULE_TEST_READONLY_DATABASE_URL",
        "MULE_TEST_TRACKING_DATABASE_URL",
    }
    if set(selected) - allowed or selected.get("MULE_TEST_ENVIRONMENT") != "test":
        parser.error("Only explicit test environment and test connection variables are permitted")
    sensitive = []
    for name in (
        "MULE_TEST_DATABASE_URL",
        "MULE_TEST_RUNTIME_DATABASE_URL",
        "MULE_TEST_READONLY_DATABASE_URL",
    ):
        value = selected.get(name, "")
        parsed = make_url(value)
        if (
            parsed.drivername != "postgresql+psycopg"
            or not (parsed.database or "").startswith("mule_test_")
            or parsed.query
        ):
            parser.error("Dedicated mule_test_* PostgreSQL endpoints are required")
        sensitive.extend([value, parsed.password or ""])
    environment.update(selected)
    environment["PYTHONUTF8"] = "1"
    destination.mkdir(parents=True)
    if sys.platform == "win32":
        temporary = ROOT / "scratch" / ("phase3_" + uuid4().hex)
        temporary.mkdir(parents=True)
    else:
        temporary = Path(tempfile.mkdtemp(prefix="mule-phase3-"))
    environment.update(TMP=str(temporary), TEMP=str(temporary), TMPDIR=str(temporary))
    python = sys.executable
    commands = [
        [python, "-m", "pip", "check"],
        [python, "-m", "ruff", "check", "."],
        [python, "-m", "ruff", "format", "--check", "."],
        [python, "-m", "mypy", "src/mule_detection"],
        [
            python,
            "-m",
            "pytest",
            "-m",
            "not benchmark",
            "-q",
            "--tb=short",
            "--basetemp",
            str(temporary / "pytest"),
            "--junitxml",
            str(destination / "pytest.xml"),
        ],
        [python, "scripts/generate_contract_schemas.py", "--check"],
        [python, "scripts/generate_research_schema.py", "--check"],
        [python, "scripts/validate_phase0.py"],
        [python, "-m", "build", "--no-isolation", "--outdir", str(destination / "dist")],
    ]
    if args.with_reference:
        commands.append([python, "scripts/reference_manifest.py", "--verify"])
    results = []
    for index, command in enumerate(commands, 1):
        started = datetime.now(UTC).isoformat()
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        output = result.stdout + result.stderr
        for secret in sensitive:
            if secret:
                output = output.replace(secret, "[REDACTED]")
        filename = f"check_{index:02d}.txt"
        (destination / filename).write_text(output, encoding="utf-8")
        results.append(
            {
                "command": command,
                "executed_at": started,
                "exit_code": result.returncode,
                "result": "PASSED" if result.returncode == 0 else "FAILED",
                "evidence": filename,
            }
        )
        print(f"{results[-1]['result']}: {' '.join(command[1:])}", flush=True)
    sources = [
        ROOT / name
        for name in (
            "pyproject.toml",
            "alembic.ini",
            "compose.yaml",
            "compose.local.yaml",
            ".env.example",
            ".gitignore",
        )
    ]
    for pattern in (
        "src/**/*.py",
        "migrations/**/*.py",
        "migrations/*.mako",
        "docker/**/*",
        "tests/**/*.py",
        "tests/fixtures/**/*",
        "scripts/verify_persistence.py",
        "scripts/verify_persistence_restart.py",
        "scripts/init_local_secrets.py",
        "scripts/configure_local_database.py",
        "scripts/create_test_database.py",
        "config/**/*.yaml",
        "requirements-*.lock",
        ".github/workflows/*.yml",
    ):
        sources.extend(path for path in ROOT.glob(pattern) if path.is_file())
    fingerprints = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(set(sources))
        if path.is_file()
    }
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    state = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    report = {
        "scope": "Phase 3 synthetic PostgreSQL persistence; no model training/scoring or qualified approval",
        "executed_at": datetime.now(UTC).isoformat(),
        "build_revision": revision.stdout.strip(),
        "working_tree_dirty": bool(state.stdout.strip()),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in (
                    "SQLAlchemy",
                    "alembic",
                    "psycopg",
                    "cryptography",
                    "pytest",
                    "ruff",
                    "mypy",
                )
            },
        },
        "source_hashes": fingerprints,
        "source_manifest_sha256": hashlib.sha256(
            json.dumps(fingerprints, sort_keys=True).encode()
        ).hexdigest(),
        "checks": results,
        "pass_fail": "PASSED" if all(row["exit_code"] == 0 for row in results) else "FAILED",
        "remote_CI": "NOT_RUN",
        "qualified_approval": "NOT_GRANTED",
    }
    (destination / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    manifest = {
        path.relative_to(destination).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return int(report["pass_fail"] != "PASSED")


if __name__ == "__main__":
    raise SystemExit(main())
