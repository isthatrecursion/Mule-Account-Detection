"""Run implemented Phase 1 checks and save an immutable, synthetic-only evidence run."""

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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--with-reference",
        action="store_true",
        help="Local approved-machine check; never required in CI",
    )
    args = parser.parse_args()
    destination = (ROOT / args.output_dir).resolve()
    if not destination.is_relative_to(ROOT / "artifacts/phase1") or destination.exists():
        parser.error("Use a new run directory under artifacts/phase1")
    destination.mkdir(parents=True)
    if sys.platform == "win32":
        temporary = ROOT / "scratch" / ("phase1_" + uuid4().hex)
        temporary.mkdir(parents=True)
    else:
        # WSL's mounted Windows filesystem cannot reliably support fd-capture tempfiles.
        temporary = Path(tempfile.mkdtemp(prefix="mule-phase1-"))
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
            "not postgres and not benchmark",
            "--basetemp",
            str(temporary / "pytest"),
            "--junitxml",
            str(destination / "pytest.xml"),
            "-q",
        ],
        [python, "scripts/validate_phase0.py"],
        [python, "-m", "mule_detection.cli", "--help"],
        [python, "-m", "build", "--no-isolation", "--outdir", str(destination / "dist")],
    ]
    if args.with_reference:
        commands.append([python, "scripts/reference_manifest.py", "--verify"])
    results = []
    environment = {key: value for key, value in os.environ.items() if not key.startswith("MULE_")}
    environment["PYTHONUTF8"] = "1"
    environment.update(TMP=str(temporary), TEMP=str(temporary), TMPDIR=str(temporary))
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
        output = destination / f"check_{index:02d}.txt"
        output.write_text(result.stdout + result.stderr, encoding="utf-8")
        results.append(
            {
                "command": command,
                "executed_at": started,
                "exit_code": result.returncode,
                "result": "PASSED" if result.returncode == 0 else "FAILED",
                "evidence": output.name,
            }
        )
        print(f"{results[-1]['result']}: {' '.join(command[1:])}", flush=True)
    sources = [
        ROOT / "pyproject.toml",
        ROOT / ".gitignore",
        ROOT / ".dockerignore",
        ROOT / ".env.example",
    ]
    for pattern in (
        "src/**/*.py",
        "src/**/py.typed",
        "config/**/*.yaml",
        "tests/**/*.py",
        "tests/fixtures/**/*",
        "requirements-*.lock",
        ".github/workflows/*.yml",
    ):
        sources.extend(path for path in ROOT.glob(pattern) if path.is_file())
    sources.extend(
        ROOT / name
        for name in (
            "scripts/reference_manifest.py",
            "scripts/verify_foundation.py",
            "scripts/verify_installation.py",
            "scripts/validate_phase0.py",
            "docs/reference_manifest.json",
            "docs/development.md",
        )
    )
    fingerprints = {
        path.relative_to(ROOT).as_posix(): sha256(path)
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
        "scope": "Phase 1 foundation checks; no model/data qualification or human approval",
        "executed_at": datetime.now(UTC).isoformat(),
        "executed_command": subprocess.list2cmdline(
            [python, str(Path(__file__).resolve()), *sys.argv[1:]]
        ),
        "build_revision": revision.stdout.strip() if revision.returncode == 0 else "UNKNOWN",
        "working_tree_dirty": bool(state.stdout.strip()) if state.returncode == 0 else "UNKNOWN",
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in (
                    "pip",
                    "setuptools",
                    "wheel",
                    "pip-tools",
                    "build",
                    "pydantic-settings",
                    "ruff",
                    "mypy",
                    "pytest",
                    "numpy",
                    "pandas",
                    "scipy",
                    "scikit-learn",
                    "lightgbm",
                )
            },
        },
        "input_policy": "synthetic fixtures only; optional reference check hashes approved local evidence without training/scoring",
        "source_hashes": fingerprints,
        "source_manifest_sha256": hashlib.sha256(
            json.dumps(fingerprints, sort_keys=True).encode()
        ).hexdigest(),
        "checks": results,
        "pass_fail": "PASSED" if all(row["exit_code"] == 0 for row in results) else "FAILED",
        "remote_CI": "NOT_RUN",
        "reviewer": "PENDING_OWNER_REVIEW",
        "qualified_approval": "NOT_GRANTED",
    }
    (destination / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    manifests = {
        path.relative_to(destination).as_posix(): sha256(path)
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifests, indent=2) + "\n", encoding="utf-8"
    )
    return int(report["pass_fail"] != "PASSED")


if __name__ == "__main__":
    raise SystemExit(main())
