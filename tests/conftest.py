from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from mule_detection.domain.clock import ManualClock
from tests.factories import FIXED_TIME, require_test_database, snapshots


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith("MULE_") and not name.startswith("MULE_TEST_"):
            monkeypatch.delenv(name)


@pytest.fixture
def clock():
    return ManualClock(FIXED_TIME)


@pytest.fixture
def synthetic_batch():
    return snapshots()


@pytest.fixture
def app_root(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1]
    shutil.copytree(source / "config", tmp_path / "config")
    monkeypatch.setenv(
        "MULE_DATABASE_URL", "postgresql+psycopg://test_user@localhost/mule_test_unit"
    )
    monkeypatch.setenv("MULE_MLFLOW_URI", "http://127.0.0.1:5000")
    return tmp_path


@pytest.fixture
def test_database_url():
    value = os.environ.get("MULE_TEST_DATABASE_URL")
    if value is None:
        pytest.fail("MULE_TEST_DATABASE_URL is required for explicit PostgreSQL tests")
    return require_test_database(value)
