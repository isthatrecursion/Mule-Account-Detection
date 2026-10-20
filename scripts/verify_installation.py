"""Install a wheel and hashed runtime lock in a fresh environment, then import outside checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SMOKE = """
import importlib.metadata as metadata
import json
import pathlib
import re
import sys
import mule_detection
import numpy, pandas, scipy, sklearn, lightgbm
from mule_detection.persistence.models import Base
from mule_detection.persistence.artifacts import ArtifactStore
from mule_detection.application.review_service import ReviewService
from mule_detection.application.job_service import JobService
assert len(Base.metadata.tables) == 18
assert all((ArtifactStore, ReviewService, JobService))
assert pathlib.Path(mule_detection.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve())
assert mule_detection.__version__ == '0.1.0'
expected = dict(re.findall(r'^([a-zA-Z0-9_.-]+)==([^\\s;]+)', pathlib.Path(sys.argv[1]).read_text(), re.M))
observed = {name: metadata.version(name) for name in expected}
assert observed == expected, {'expected': expected, 'observed': observed}
print(json.dumps({'status': 'PASSED', 'package_file': mule_detection.__file__, 'runtime_versions': observed}))
"""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    destination = args.output_dir.resolve()
    if destination.exists() or not destination.is_relative_to(ROOT / "artifacts/phase1"):
        parser.error("Choose a new output directory under artifacts/phase1")
    destination.mkdir(parents=True)
    work = ROOT / "scratch" / ("install_" + uuid4().hex)
    work.mkdir(parents=True)
    target = work / "environment"
    interpreter = target / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    lock = ROOT / (
        "requirements-windows.lock" if sys.platform == "win32" else "requirements-linux.lock"
    )
    environment = {key: value for key, value in os.environ.items() if not key.startswith("MULE_")}
    environment.update(
        TEMP=str(work),
        TMP=str(work),
        TMPDIR=str(work),
        PIP_DISABLE_PIP_VERSION_CHECK="1",
        PYTHONUTF8="1",
    )
    commands = [
        [sys.executable, "-m", "venv", str(target)],
        [
            str(interpreter),
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "--only-binary=:all:",
            "-r",
            str(lock),
        ],
        [str(interpreter), "-m", "pip", "install", "--no-deps", str(wheel)],
        [str(interpreter), "-m", "pip", "check"],
        [str(interpreter), "-c", SMOKE, str(lock)],
        [str(interpreter), "-m", "mule_detection.cli", "--help"],
    ]
    checks = []
    for number, command in enumerate(commands, 1):
        result = subprocess.run(
            command,
            cwd=work,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        evidence = destination / f"check_{number:02d}.txt"
        evidence.write_text(result.stdout + result.stderr, encoding="utf-8")
        checks.append(
            {"command": command, "exit_code": result.returncode, "evidence": evidence.name}
        )
        print(
            f"{'PASSED' if result.returncode == 0 else 'FAILED'}: fresh install check {number}",
            flush=True,
        )
        if result.returncode:
            break
    report = {
        "scope": "Fresh runtime lock installation and wheel import outside source checkout",
        "executed_at": datetime.now(UTC).isoformat(),
        "executed_command": subprocess.list2cmdline(
            [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
        ),
        "environment": {"python": sys.version, "platform": platform.platform()},
        "wheel": {"path": str(wheel), "sha256": digest(wheel)},
        "lock": {"path": lock.name, "sha256": digest(lock)},
        "script_sha256": digest(Path(__file__).resolve()),
        "checks": checks,
        "pass_fail": "PASSED"
        if len(checks) == len(commands) and all(c["exit_code"] == 0 for c in checks)
        else "FAILED",
    }
    (destination / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (destination / "manifest.json").write_text(
        json.dumps({p.name: digest(p) for p in destination.iterdir() if p.is_file()}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return int(report["pass_fail"] != "PASSED")


if __name__ == "__main__":
    raise SystemExit(main())
