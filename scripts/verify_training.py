"""Record Phase 6 verification; public checks use synthetic data only."""

from __future__ import annotations

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

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def redact(value, connections):
    from sqlalchemy.engine import make_url

    for name, content in connections.items():
        if name.endswith("_URL"):
            value = value.replace(content, "[REDACTED_ENDPOINT]")
            password = make_url(content).password
            if password:
                value = value.replace(password, "[REDACTED]")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--connections-file", type=Path)
    args = parser.parse_args()
    destination = (ROOT / args.output_dir).resolve()
    if destination.exists() or not destination.is_relative_to(ROOT / "artifacts/phase6"):
        parser.error("Select a new directory under artifacts/phase6")
    destination.mkdir(parents=True)
    if sys.platform == "win32":
        work = ROOT / "scratch" / ("phase6_" + uuid4().hex)
        work.mkdir(parents=True)
    else:
        work = Path(tempfile.mkdtemp(prefix="mule-phase6-"))
    env = {key: value for key, value in os.environ.items() if not key.startswith("MULE_")}
    env.update(TEMP=str(work), TMP=str(work), TMPDIR=str(work), PYTHONUTF8="1")
    if args.connections_file:
        selected = json.loads(args.connections_file.read_text())
        allowed = {
            "MULE_TEST_ENVIRONMENT",
            "MULE_TEST_DATABASE_URL",
            "MULE_TEST_RUNTIME_DATABASE_URL",
            "MULE_TEST_READONLY_DATABASE_URL",
            "MULE_TEST_TRACKING_DATABASE_URL",
        }
        if set(selected) - allowed or selected.get("MULE_TEST_ENVIRONMENT") != "test":
            parser.error("Only explicit dedicated test connection variables are allowed")
        from urllib.parse import urlsplit

        for name in (
            "MULE_TEST_DATABASE_URL",
            "MULE_TEST_RUNTIME_DATABASE_URL",
            "MULE_TEST_READONLY_DATABASE_URL",
        ):
            parsed = urlsplit(selected[name])
            if (
                parsed.scheme != "postgresql+psycopg"
                or not parsed.hostname
                or not parsed.path.lstrip("/").startswith("mule_test_")
                or parsed.query
                or parsed.fragment
            ):
                parser.error("Explicit dedicated mule_test_* PostgreSQL endpoints are required")
        env.update(selected)
    python = sys.executable
    commands = [
        [python, "-m", "pip", "check"],
        [python, "-m", "ruff", "check", "."],
        [python, "-m", "ruff", "format", "--check", "."],
        [python, "-m", "mypy", "--cache-dir", str(work / "mypy"), "src/mule_detection"],
        [
            python,
            "-m",
            "pytest",
            "-m",
            "not benchmark" if args.connections_file else "not postgres and not benchmark",
            "--basetemp",
            str(work / "pytest"),
            "--junitxml",
            str(destination / "pytest.xml"),
            "-q",
        ],
        [python, "scripts/generate_contract_schemas.py", "--check"],
        [python, "scripts/generate_research_schema.py", "--check"],
        [python, "scripts/validate_phase0.py"],
        [
            python,
            "scripts/run_training_experiment.py",
            "--output-dir",
            str(destination / "synthetic_parity"),
        ],
        [python, "-m", "build", "--no-isolation", "--outdir", str(destination / "dist")],
    ]
    results = []
    sources = [
        *sorted((ROOT / "src/mule_detection").rglob("*.py")),
        ROOT / "pyproject.toml",
        Path(__file__),
        ROOT / "scripts/run_training_experiment.py",
        ROOT / "config/model_candidates.yaml",
        ROOT / "config/evaluation_policy.yaml",
        ROOT / "tests/unit/test_training.py",
        ROOT / "tests/integration/test_training.py",
        ROOT / "config/semantic_rules.yaml",
        ROOT / "config/feature_policy.yaml",
    ]
    identities = {str(p.relative_to(ROOT)): sha256(p) for p in sources}
    for index, command in enumerate(commands, 1):
        started = datetime.now(UTC).isoformat()
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        log = destination / f"check_{index:02d}.txt"
        log.write_text(
            (completed.stdout + completed.stderr)
            if not args.connections_file
            else redact(completed.stdout + completed.stderr, selected),
            encoding="utf-8",
        )
        results.append(
            {
                "command": subprocess.list2cmdline(command),
                "started_at": started,
                "exit_code": completed.returncode,
                "result": "PASSED" if completed.returncode == 0 else "FAILED",
                "evidence": str(log.relative_to(ROOT)),
            }
        )
        print(
            f"{index}/{len(commands)}: {results[-1]['result']} {subprocess.list2cmdline(command)}",
            flush=True,
        )
    unchanged = identities == {str(p.relative_to(ROOT)): sha256(p) for p in sources}
    report = {
        "result": "PASSED"
        if unchanged and all(item["exit_code"] == 0 for item in results)
        else "FAILED",
        "checked_at": datetime.now(UTC).isoformat(),
        "code_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip(),
        "dirty_tree": bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        ),
        "source_sha256": identities,
        "sources_unchanged_during_checks": unchanged,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in ("numpy", "pandas", "scikit-learn", "lightgbm", "joblib", "scipy")
            },
        },
        "checks": results,
        "scope": "Synthetic Phase 6 verification; no real data, holdout scoring, model approval or qualified-use acceptance",
    }
    (destination / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (destination / "checksums.json").write_text(
        json.dumps(
            {
                str(p.relative_to(destination)): sha256(p)
                for p in sorted(destination.rglob("*"))
                if p.is_file()
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0 if report["result"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
