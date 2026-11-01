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
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.features.inputs import research_frame
from mule_detection.features.artifacts import save_pipeline, load_pipeline
from mule_detection.training.runner import run_experiment, evaluate_run
from mule_detection.training.model_factory import fit_candidate
from mule_detection.application.training_service import TrainingService
from mule_detection.registry.bundle_loader import BundleLoader
from mule_detection.registry.model_resolver import ModelResolver
from mule_detection.application.model_approval_service import ModelApprovalService
from mule_detection.application.scoring_service import ScoringService
from mule_detection.application.publication_service import PublicationService
from mule_detection.explanations.contributions import contributions
from mule_detection.scoring.ranking import rank_scores
assert {'datasets', 'batches', 'score_runs', 'score_rows', 'audit_events',
        'intake_requests', 'raw_publications', 'intake_contents', 'registry_candidates',
        'model_decisions', 'model_deployments', 'model_pins', 'scoring_tasks',
        'scoring_chunks', 'scoring_attempts', 'queue_heads'} <= set(Base.metadata.tables)
assert all((ArtifactStore, ReviewService, JobService, FeaturePipeline,
            research_frame, save_pipeline, load_pipeline, run_experiment,
            evaluate_run, fit_candidate, TrainingService, BundleLoader, ModelResolver, ModelApprovalService,
            ScoringService, PublicationService, contributions, rank_scores))
assert pathlib.Path(mule_detection.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve())
assert mule_detection.__version__ == '0.1.0'
expected = dict(re.findall(r'^([a-zA-Z0-9_.-]+)==([^\\s;]+)', pathlib.Path(sys.argv[1]).read_text(), re.M))
observed = {name: metadata.version(name) for name in expected}
assert observed == expected, {'expected': expected, 'observed': observed}
print(json.dumps({'status': 'PASSED', 'package_file': mule_detection.__file__, 'runtime_versions': observed}))
"""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


API_SMOKE = """
import tempfile, time
from types import SimpleNamespace
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from mule_detection.api.app import create_app
from mule_detection.api.auth import AuthConfig
from mule_detection.api.service import ApiService
from mule_detection.settings import Settings
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
public.update(kid='installed-test', alg='RS256')
with tempfile.TemporaryDirectory() as directory:
    settings = Settings(environment='test', root_path=pathlib.Path(directory),
        database_url='postgresql+psycopg://schema@localhost/mule_test_installed',
        mlflow_uri='http://localhost:5000', runtime_policy_path='config/test.yaml')
    try:
        create_app(settings)
    except ValueError:
        pass
    else:
        raise AssertionError('Missing trust must fail closed')
    auth = AuthConfig(issuer='https://installed.example.test', audience='installed-api',
        isolated_test=True, static_jwks={'keys': [public]},
        groups={'review': {'roles': ['analyst'], 'scopes': ['installed-test']}})
    service = SimpleNamespace(remember=lambda principal: None, ready=lambda: True)
    claims = {'iss': auth.issuer, 'aud': auth.audience, 'sub': 'installed-analyst',
        'iat': int(time.time())-1, 'exp': int(time.time())+300, 'groups': ['review']}
    token = jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'installed-test'})
    with TestClient(create_app(settings, lambda _: (auth, service))) as http:
        assert http.get('/v1/me').status_code == 401
        result = http.get('/v1/me', headers={'Authorization': 'Bearer '+token})
        assert result.status_code == 200 and result.json()['roles'] == ['analyst']
        assert http.get('/health/ready').status_code == 200
assert pathlib.Path(ApiService.__module__.replace('.', '/')).name == 'service'
print(json.dumps({'api_wheel': 'PASSED', 'signed_token_http': 'PASSED', 'missing_trust': 'BLOCKED'}))
"""


UI_SMOKE = """
import numpy as np
import pyarrow as pa
import ui
from streamlit.testing.v1 import AppTest
assert np.__version__ == '1.26.4' and pa.__version__ == '25.0.1'
assert pa.array(np.array([1., 2.])).to_pylist() == [1., 2.]
assert pathlib.Path(ui.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve())
app = AppTest.from_file(str(pathlib.Path(ui.__file__).with_name('app.py')), default_timeout=30).run()
assert not app.exception
assert any('Shared login is blocked' in value.value for value in app.warning)
print(json.dumps({'ui_wheel': 'PASSED', 'blocked_normal_identity': 'PASSED', 'numpy_arrow_runtime': 'PASSED'}))
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--ui", action="store_true", help="Verify the locked Streamlit workspace outside checkout"
    )
    parser.add_argument(
        "--api", action="store_true", help="Verify the separate API lock and HTTP factory"
    )
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    destination = args.output_dir.resolve()
    phase = "phase10" if args.ui else "phase9" if args.api else "phase1"
    if destination.exists() or not destination.is_relative_to(ROOT / "artifacts" / phase):
        parser.error("Choose a new output directory under artifacts/" + phase)
    destination.mkdir(parents=True)
    work = ROOT / "scratch" / ("install_" + uuid4().hex)
    work.mkdir(parents=True)
    target = work / "environment"
    interpreter = target / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    platform_name = "windows" if sys.platform == "win32" else "linux"
    lock = ROOT / (
        "requirements-"
        + ("ui-" if args.ui else "api-" if args.api else "")
        + platform_name
        + ".lock"
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
        [
            str(interpreter),
            "-c",
            SMOKE + (API_SMOKE if args.api or args.ui else "") + (UI_SMOKE if args.ui else ""),
            str(lock),
        ],
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
