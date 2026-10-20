"""Record Phase 2 checks. Real-data adaptation is opt-in and writes aggregate evidence only."""

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


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def check_reference_adapter() -> dict[str, object]:
    from mule_detection.ingestion.research_adapter import ResearchAdapter

    adapter = ResearchAdapter.from_repository(ROOT)
    batch = adapter.adapt(ROOT / "DataSet__1_.csv", ROOT / "eda/holdout_split_indices.csv")
    expected = (
        len(batch.record_keys) == 7265
        and batch.excluded_holdout_count == 1817
        and len(batch.predictors) == 3917
        and int(batch.labels.sum()) == 65
        and batch.account_id is None
        and batch.observation_cutoff is None
        and not {"Unnamed: 0", "F3924", "F2230", "F3912"}.intersection(batch.predictors)
    )
    if not expected:
        raise RuntimeError("Reference adapter aggregate check failed")
    return {
        "development_rows": len(batch.record_keys),
        "development_positives": int(batch.labels.sum()),
        "excluded_holdout_rows": batch.excluded_holdout_count,
        "predictor_columns_before_fold_pruning": len(batch.predictors),
        "dataset_sha256": batch.dataset_sha256,
        "split_sha256": batch.split_sha256,
        "feature_policy_hash": batch.feature_policy_hash,
        "data_tier": batch.data_tier,
        "observation_cutoff": None,
        "verified_account_identity": False,
        "training_or_scoring_performed": False,
        "private_rows_written": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--with-research-data", action="store_true")
    args = parser.parse_args()
    destination = args.output_dir.resolve()
    if destination.exists() or not destination.is_relative_to(ROOT / "artifacts/phase2"):
        parser.error("Select a new evidence directory under artifacts/phase2")
    destination.mkdir(parents=True)
    if sys.platform == "win32":
        work = ROOT / "scratch" / ("phase2_" + uuid4().hex)
        work.mkdir(parents=True)
    else:
        work = Path(tempfile.mkdtemp(prefix="mule-phase2-"))
    env = {key: value for key, value in os.environ.items() if not key.startswith("MULE_")}
    env.update(TEMP=str(work), TMP=str(work), TMPDIR=str(work), PYTHONUTF8="1")
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
            str(work / "pytest"),
            "--junitxml",
            str(destination / "pytest.xml"),
            "-q",
        ],
        [python, "scripts/generate_contract_schemas.py", "--check"],
        [python, "scripts/generate_research_schema.py", "--check"],
        [python, "scripts/validate_phase0.py"],
        [python, "-m", "build", "--no-isolation", "--outdir", str(destination / "dist")],
    ]
    if args.with_research_data:
        commands.append([python, "scripts/reference_manifest.py", "--verify"])
    checks = []
    for number, command in enumerate(commands, 1):
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        path = destination / f"check_{number:02d}.txt"
        path.write_text(result.stdout + result.stderr, encoding="utf-8")
        checks.append(
            {"executed_command": command, "exit_code": result.returncode, "evidence": path.name}
        )
        print(
            f"{'PASSED' if result.returncode == 0 else 'FAILED'}: {' '.join(command[1:])}",
            flush=True,
        )
    adapter_result: dict[str, object] = {"status": "NOT_RUN (synthetic-only mode)"}
    if args.with_research_data:
        try:
            adapter_result = {"status": "PASSED", **check_reference_adapter()}
            print("PASSED: reference research adapter (aggregate-only)", flush=True)
        except Exception:
            # Raw values and parser tracebacks are deliberately absent from exported evidence.
            adapter_result = {
                "status": "FAILED",
                "safe_message": "Reference adaptation failed; inspect the contract locally",
            }
            print("FAILED: reference research adapter", flush=True)
    source_files = [
        ROOT / name
        for name in (
            "pyproject.toml",
            ".github/workflows/checks.yml",
            "docs/reference_manifest.json",
            "scripts/generate_contract_schemas.py",
            "scripts/generate_research_schema.py",
            "scripts/verify_contracts.py",
        )
    ]
    for pattern in (
        "src/**/*.py",
        "src/**/py.typed",
        "tests/**/*.py",
        "tests/fixtures/**/*",
        "config/**/*.yaml",
        "contracts/*.json",
        "requirements-*.lock",
    ):
        source_files.extend(p for p in ROOT.glob(pattern) if p.is_file())
    sources = {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(set(source_files))}
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False
    )
    state = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=False
    )
    success = (
        all(check["exit_code"] == 0 for check in checks) and adapter_result["status"] != "FAILED"
    )
    report = {
        "scope": "Phase 2 contracts and integrated foundation; no source/model qualification, model fitting, scoring or deployment",
        "executed_at": datetime.now(UTC).isoformat(),
        "executed_command": subprocess.list2cmdline(
            [python, str(Path(__file__).resolve()), *sys.argv[1:]]
        ),
        "build_revision": revision.stdout.strip() if revision.returncode == 0 else "UNKNOWN",
        "working_tree_dirty": bool(state.stdout.strip()),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in (
                    "pydantic",
                    "pydantic-core",
                    "numpy",
                    "PyYAML",
                    "pytest",
                    "mypy",
                    "ruff",
                )
            },
        },
        "source_hashes": sources,
        "source_manifest_sha256": hashlib.sha256(
            json.dumps(sources, sort_keys=True).encode()
        ).hexdigest(),
        "input_hash": digest(ROOT / "tests/fixtures/contracts/minimal_valid.json"),
        "config_hash": hashlib.sha256(
            json.dumps(
                {k: v for k, v in sources.items() if k.startswith("config/")}, sort_keys=True
            ).encode()
        ).hexdigest(),
        "expected": "All implemented contract and prior foundation checks pass; schema drift rejected; research-only adapter emits saved development membership",
        "observed": {
            "successful_checks": sum(check["exit_code"] == 0 for check in checks),
            "checks": len(checks),
        },
        "checks": checks,
        "research_adapter": adapter_result,
        "pass_fail": "PASSED" if success else "FAILED",
        "remote_CI": "NOT_RUN",
        "reviewer": "PENDING_OWNER_REVIEW",
        "external_dependencies": "OPEN",
        "qualified_approval": "NOT_GRANTED",
    }
    (destination / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    files = {
        p.relative_to(destination).as_posix(): digest(p)
        for p in sorted(destination.rglob("*"))
        if p.is_file()
    }
    (destination / "manifest.json").write_text(json.dumps(files, indent=2) + "\n", encoding="utf-8")
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
