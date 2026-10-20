import pytest

from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.settings import load_settings


def test_resolves_paths_and_redacts_endpoints(app_root, monkeypatch):
    monkeypatch.setenv(
        "MULE_DATABASE_URL", "postgresql+psycopg://user:PRIVATE_PASSWORD@localhost/mule_test_unit"
    )
    settings = load_settings(app_root)
    assert settings.artifact_root == app_root / "var/artifacts"
    assert settings.review_policy_path.is_absolute()
    assert "PRIVATE_PASSWORD" not in repr(settings)
    assert len(settings.fingerprint()) == 64


@pytest.mark.parametrize(
    "name,value",
    [
        ("MULE_MAX_UPLOAD_BYTES", "-1"),
        ("MULE_MAX_BATCH_ROWS", "0"),
        ("MULE_MODEL_TIER", "approved_for_pilot"),
        ("MULE_DATABASE_URL", "INVALID_SECRET"),
        ("MULE_MLFLOW_URI", "INVALID_SECRET"),
        ("MULE_ARTIFACT_ROOT", "../escape"),
        ("MULE_RECONCILIATION_SCAN_SECONDS", "120"),
    ],
)
def test_invalid_settings_fail_safely(app_root, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(DomainError) as result:
        load_settings(app_root)
    assert result.value.code == ErrorCode.CONFIGURATION_INVALID
    assert value not in str(result.value)


def test_missing_mandatory_endpoint(app_root, monkeypatch):
    monkeypatch.delenv("MULE_DATABASE_URL")
    with pytest.raises(DomainError):
        load_settings(app_root)


def test_env_overrides_explicit_dotenv_and_yaml(app_root, monkeypatch):
    dotenv = app_root / ".env"
    dotenv.write_text("MULE_MAX_UPLOAD_BYTES=256\n")
    monkeypatch.setenv("MULE_MAX_UPLOAD_BYTES", "512")
    assert load_settings(app_root, dotenv_path=dotenv).max_upload_bytes == 512
    monkeypatch.delenv("MULE_MAX_UPLOAD_BYTES")
    assert load_settings(app_root, dotenv_path=dotenv).max_upload_bytes == 256
    assert load_settings(app_root).max_upload_bytes == 134217728


def test_secret_files_supply_endpoints(app_root, monkeypatch):
    monkeypatch.delenv("MULE_DATABASE_URL")
    directory = app_root / "secrets"
    directory.mkdir()
    (directory / "MULE_DATABASE_URL").write_text(
        "postgresql+psycopg://test@localhost/mule_test_unit"
    )
    assert load_settings(app_root, secrets_dir=directory).database_url


def test_unknown_environment_and_conflicting_selector(app_root, monkeypatch):
    with pytest.raises(DomainError):
        load_settings(app_root, environment="unknown")
    monkeypatch.setenv("MULE_ENVIRONMENT", "qualified")
    with pytest.raises(DomainError):
        load_settings(app_root, environment="local")


def test_qualified_rejects_research_setting(app_root):
    with pytest.raises(DomainError):
        load_settings(app_root, environment="qualified")


def test_qualified_settings_do_not_grant_approval(app_root, monkeypatch):
    monkeypatch.setenv("MULE_MODEL_TIER", "approved_for_shadow")
    settings = load_settings(app_root, environment="qualified")
    assert settings.environment == "qualified"
    assert not hasattr(settings, "approved")


def test_policy_cannot_waive_self_approval(app_root, monkeypatch):
    monkeypatch.setenv("MULE_MODEL_TIER", "approved_for_shadow")
    policy = app_root / "config/environments/qualified.yaml"
    policy.write_text(
        policy.read_text().replace("self_approval_allowed: false", "self_approval_allowed: true")
    )
    with pytest.raises(DomainError):
        load_settings(app_root, environment="qualified")


def test_unwritable_artifact_directory(app_root):
    target = app_root / "var"
    target.write_text("synthetic-file-blocking-directory")
    with pytest.raises(DomainError):
        load_settings(app_root)


def test_yaml_endpoints_forbidden(app_root):
    config = app_root / "config/environments/local.yaml"
    config.write_text("runtime:\n  database_url: secret\n")
    with pytest.raises(DomainError):
        load_settings(app_root)
