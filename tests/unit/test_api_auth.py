import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("jwt")

from mule_detection.api.auth import AuthConfig, AuthenticationRequired, TokenVerifier
from tests.api_helpers import SigningAuthority


@pytest.fixture
def authority():
    return SigningAuthority()


def test_verified_claims_only_and_server_role_mapping(authority):
    verifier = TokenVerifier(authority.config, "test")
    principal = verifier.verify(
        "Bearer " + authority.token(roles=["operator"], scopes=["other-team"])
    )
    assert principal.roles == {"analyst"} and principal.scopes == {"synthetic-team"}
    assert "batch:intake" not in principal.permissions
    assert principal.actor_id.startswith("oidc:")
    with pytest.raises(ValueError):
        TokenVerifier(authority.config, "research")


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": "wrong"},
        {"iss": "https://wrong.test"},
        {"exp": 1},
        {"iat": int(time.time()) + 3600},
        {"nbf": int(time.time()) + 3600},
        {"groups": "operator-synthetic-team"},
        {"sub": ""},
    ],
)
def test_bad_claims_denied(authority, changes):
    with pytest.raises(AuthenticationRequired):
        TokenVerifier(authority.config, "test").verify("Bearer " + authority.token(**changes))


def test_altered_unsigned_unknown_key_and_missing_tokens(authority):
    import jwt

    verifier = TokenVerifier(authority.config, "test")
    token = authority.token()
    altered = token.split(".")
    altered[1] = altered[1][:-3] + "AAA"
    unsigned = jwt.encode({"sub": "attacker"}, key="", algorithm="none")
    unknown = jwt.encode(
        {"sub": "attacker"}, authority.key, algorithm="RS256", headers={"kid": "unknown"}
    )
    for invalid in (
        None,
        "Basic abc",
        "Bearer " + ".".join(altered),
        "Bearer " + unsigned,
        "Bearer " + unknown,
    ):
        with pytest.raises(AuthenticationRequired):
            verifier.verify(invalid)


def test_normal_startup_has_no_test_trust_fallback(tmp_path, authority):
    with pytest.raises(ValueError, match="requires complete OIDC"):
        AuthConfig.load(tmp_path, "research")
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "oidc.json").write_text(authority.config.model_dump_json())
    with pytest.raises(ValueError, match="requires complete OIDC"):
        AuthConfig.load(tmp_path, "test")


def test_combined_groups_keep_permissions_bound_to_their_own_scopes(authority):
    token = authority.token(groups=["analyst-synthetic-team", "operator-other-team"])
    principal = TokenVerifier(authority.config, "test").verify("Bearer " + token)
    assert principal.for_permission("case:read").scopes == {"synthetic-team"}
    assert principal.for_permission("batch:intake").scopes == {"other-team"}


def test_application_factory_requires_real_trust_and_isolates_injection(tmp_path, authority):
    from types import SimpleNamespace

    from mule_detection.api.app import create_app
    from mule_detection.settings import Settings

    settings = Settings(
        environment="test",
        root_path=tmp_path,
        database_url="postgresql+psycopg://schema@localhost/mule_test_only",
        mlflow_uri="http://localhost:5000",
        runtime_policy_path="config/test.yaml",
    )
    with pytest.raises(ValueError, match="requires complete OIDC"):
        create_app(settings)
    with pytest.raises(ValueError, match="restricted to isolated"):
        create_app(
            settings.model_copy(update={"environment": "research"}),
            lambda _: (authority.config, SimpleNamespace()),
        )
