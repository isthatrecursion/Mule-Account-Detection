"""Opt-in wrapper around the existing synthetic PostgreSQL/API/worker journey."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("MULE_TEST_UI_REAL_JOURNEY") != "1",
        reason="Opt-in: requires dedicated test PostgreSQL, synthetic worker assets and signing fixtures",
    ),
]


def test_real_api_worker_journey(tmp_path):
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/integration/test_ui_journey.py",
            "-q",
            "--tb=no",
            "--basetemp=" + str(tmp_path / "real"),
        ],
        cwd=root,
        capture_output=True,
        timeout=2400,
        check=False,
    )
    assert result.returncode == 0, (
        "Real-stack journey failed; inspect the dedicated integration runner's protected evidence. Raw output is suppressed."
    )
