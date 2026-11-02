import hashlib
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.ui_helpers import config
from ui.auth import GatewayTokenProvider, LoginRequired


def gateway(changes=None):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public.update(kid="gateway-test", alg="RS256")
    seen, binding = [], [None]

    def handler(request):
        seen.append(request)
        if request.url.path == "/keys":
            return httpx.Response(200, json={"keys": [public]})
        body = json.loads(request.content)
        if request.url.path.endswith("logout"):
            binding[0] = "revoked"
            return httpx.Response(200, json={})
        if binding[0] is not None and binding[0] != body["session_binding"]:
            return httpx.Response(401)
        binding[0] = body["session_binding"]
        token = "opaque-api-audience-access-token-test"
        claims = {
            "iss": config().gateway_issuer,
            "aud": config().gateway_audience,
            "sub": "analyst",
            "exp": int(time.time()) + 45,
            "iat": int(time.time()) - 1,
            "jti": "test-assertion",
            "session_binding": body["session_binding"],
            "api_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            "api_issuer": config().api_issuer,
            "api_audience": config().api_audience,
            "api_expires_at": int(time.time()) + 300,
        }
        claims.update(changes or {})
        assertion = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "gateway-test"})
        return httpx.Response(200, json={"access_token": token, "assertion": assertion})

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_signed_backchannel_session_binding_logout_and_no_impersonation():
    client, seen = gateway()
    provider = GatewayTokenProvider(
        config(), "valid_opaque_handle_32_characters_long", client=client
    )
    credential = provider.credential()
    assert credential.actor_id.startswith("oidc:") and credential.binding == provider.binding
    assert "opaque-api" not in repr(credential)
    another = GatewayTokenProvider(
        config(), "valid_opaque_handle_32_characters_long", client=client
    )
    with pytest.raises(LoginRequired):
        another.credential()
    provider.logout()
    with pytest.raises(LoginRequired):
        provider.credential()
    assert not any("email" in r.headers or "X-Role" in r.headers for r in seen)


@pytest.mark.parametrize(
    "changes",
    [
        {"session_binding": "another-user"},
        {"api_audience": "wrong"},
        {"api_issuer": "https://other.test"},
        {"api_token_sha256": "wrong"},
        {"exp": 1},
        {"aud": "other-ui"},
        {"iss": "https://other.test"},
        {"api_expires_at": 1},
    ],
)
def test_spoofed_expired_or_wrong_audience_gateway_assertions_fail_closed(changes):
    client, _ = gateway(changes)
    with pytest.raises(LoginRequired):
        GatewayTokenProvider(
            config(), "opaque_handle_32_characters_minimum", client=client
        ).credential()


def test_email_header_is_not_a_gateway_session():
    with pytest.raises(LoginRequired):
        GatewayTokenProvider(config(), "analyst@example.test")
