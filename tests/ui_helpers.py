"""Isolated signed user credentials; no fixture identity can be selected in the normal UI."""

import hashlib
import time

from pydantic import SecretStr

from ui.auth import LoginRequired, UserCredential
from ui.config import UiConfig


def config(**changes):
    return UiConfig(
        api_base_url="https://api.example.test",
        api_issuer="https://isolated.example.test",
        api_audience="review-api-test",
        gateway_url="https://gateway.example.test/session",
        gateway_issuer="https://gateway.example.test",
        gateway_audience="workspace-test",
        gateway_jwks_url="https://gateway.example.test/keys",
        gateway_service_token=SecretStr("fixture-service-credential-32-bytes-only"),
        login_url="https://gateway.example.test/login",
        **changes,
    )


class SignedProvider:
    def __init__(
        self, authority, role="analyst", scope="synthetic-team", subject=None, groups=None
    ):
        self.actor = (
            "oidc:"
            + hashlib.sha256(
                (authority.config.issuer + "\0" + (subject or role)).encode()
            ).hexdigest()
        )
        self.token = SecretStr(
            authority.token(role, scope, subject, **({"groups": groups} if groups else {}))
        )
        self.binding = "isolated-test-binding"
        self.expires = int(time.time()) + 3500
        self.closed = False

    def credential(self):
        if self.closed or self.expires <= time.time():
            raise LoginRequired()
        # API /me expires_at equals the token's 3600-second lifetime.
        return UserCredential(self.actor, int(time.time()) + 3600, self.binding, self.token)

    def logout(self):
        self.closed = True
