"""Destructive fixtures require explicit test opt-in and a dedicated database identity."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from mule_detection.persistence.models import Base
from mule_detection.persistence.sqlalchemy import make_engine, session_factory
from tests.factories import require_test_database

ROOT = Path(__file__).resolve().parents[2]


def guarded_url(variable: str) -> str:
    if os.environ.get("MULE_TEST_ENVIRONMENT") != "test":
        pytest.fail("MULE_TEST_ENVIRONMENT=test is required before database setup/reset")
    value = os.environ.get(variable)
    if value is None:
        pytest.fail(f"{variable} is required for PostgreSQL tests")
    return require_test_database(value)


@pytest.fixture(scope="session")
def migrated_engine():
    engine = make_engine(guarded_url("MULE_TEST_DATABASE_URL"))
    with engine.begin() as connection:
        actual = connection.scalar(text("SELECT current_database()"))
        assert actual == engine.url.database and actual.startswith("mule_test_")
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db(migrated_engine):
    # Guard again immediately before each destructive operation.
    assert guarded_url("MULE_TEST_DATABASE_URL")
    with migrated_engine.begin() as connection:
        actual = connection.scalar(text("SELECT current_database()"))
        assert actual == migrated_engine.url.database and actual.startswith("mule_test_")
        tables = ", ".join('"' + name + '"' for name in Base.metadata.tables)
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    return session_factory(migrated_engine)


@pytest.fixture
def runtime_engine(migrated_engine):
    engine = make_engine(guarded_url("MULE_TEST_RUNTIME_DATABASE_URL"))
    assert engine.url.database == migrated_engine.url.database
    yield engine
    engine.dispose()


@pytest.fixture
def readonly_engine(migrated_engine):
    engine = make_engine(guarded_url("MULE_TEST_READONLY_DATABASE_URL"))
    assert engine.url.database == migrated_engine.url.database
    yield engine
    engine.dispose()
