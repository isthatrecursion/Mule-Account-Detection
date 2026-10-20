import pytest

from tests.integration.conftest import guarded_url


def test_database_reset_guard_requires_explicit_test_environment(monkeypatch):
    monkeypatch.setenv(
        "MULE_TEST_DATABASE_URL", "postgresql+psycopg://test@localhost/mule_test_guard"
    )
    monkeypatch.delenv("MULE_TEST_ENVIRONMENT", raising=False)
    with pytest.raises(pytest.fail.Exception):
        guarded_url("MULE_TEST_DATABASE_URL")
    monkeypatch.setenv("MULE_TEST_ENVIRONMENT", "qualified")
    with pytest.raises(pytest.fail.Exception):
        guarded_url("MULE_TEST_DATABASE_URL")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://test@localhost/mule_operational",
        "postgresql+psycopg://test@localhost/mule_tracking",
        "postgresql+psycopg://test@localhost/mule_test_safe?options=unsafe",
    ],
)
def test_database_reset_guard_rejects_operational_or_overridden_targets(monkeypatch, url):
    monkeypatch.setenv("MULE_TEST_ENVIRONMENT", "test")
    monkeypatch.setenv("MULE_TEST_DATABASE_URL", url)
    with pytest.raises(ValueError):
        guarded_url("MULE_TEST_DATABASE_URL")
