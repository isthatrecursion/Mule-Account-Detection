"""Backchannel user-token resolution with signed, session-bound gateway assertions."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
import jwt
from pydantic import SecretStr

from ui.config import UiConfig


class LoginRequired(Exception):
    def __str__(self) -> str:
        return "Sign in again through the identity gateway."


@dataclass(frozen=True)
class UserCredential:
    actor_id: str
    expires_at: int
    binding: str
    token: SecretStr = field(repr=False)


class UserTokenProvider(Protocol):
    def credential(self) -> UserCredential: ...
    def logout(self) -> None: ...


class GatewayTokenProvider:
    """Opaque handles have no authority until the gateway proves their bound identity.

    Deployment must strip client-supplied X-Mule-Session, isolate direct UI access,
    and bind each gateway session to one workspace binding server-side.
    """

    def __init__(
        self,
        config: UiConfig,
        handle: str,
        *,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not 32 <= len(handle) <= 512 or not all(c.isalnum() or c in "-_" for c in handle):
            raise LoginRequired()
        self.config = config
        self._clock = clock
        self._handle = SecretStr(handle)
        self.binding = secrets.token_urlsafe(32)
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(10, connect=3),
            verify=True,
            follow_redirects=False,
            trust_env=False,
        )
        self._current: UserCredential | None = None
        self._verified_until = 0.0
        self._closed = False

    def _exchange(self, operation: str) -> httpx.Response:
        return self._client.post(
            self.config.gateway_url.rstrip("/") + "/" + operation,
            headers={
                "Authorization": "Bearer " + self.config.gateway_service_token.get_secret_value()
            },
            json={
                "session_handle": self._handle.get_secret_value(),
                "session_binding": self.binding,
                "audience": self.config.api_audience,
            },
        )

    def credential(self) -> UserCredential:
        if self._closed:
            raise LoginRequired()
        if self._current and self._clock() < min(
            self._verified_until, self._current.expires_at - 5
        ):
            return self._current
        try:
            response = self._exchange("resolve")
            if response.status_code != 200 or len(response.content) > 32768:
                raise LoginRequired()
            value = response.json()
            token, assertion = value["access_token"], value["assertion"]
            if (
                not isinstance(token, str)
                or len(token) > 8192
                or not isinstance(assertion, str)
                or len(assertion) > 8192
            ):
                raise LoginRequired()
            header = jwt.get_unverified_header(assertion)
            if header.get("alg") not in {"RS256", "ES256"} or any(
                k in header for k in ("jku", "x5u", "crit")
            ):
                raise LoginRequired()
            if not isinstance(header.get("kid"), str) or not 1 <= len(header["kid"]) <= 200:
                raise LoginRequired()
            keys = self._client.get(self.config.gateway_jwks_url)
            if keys.status_code != 200 or len(keys.content) > 1048576:
                raise LoginRequired()
            entries = keys.json()["keys"]
            if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
                raise LoginRequired()
            matches = [
                k
                for k in entries
                if k.get("kid") == header.get("kid")
                and "d" not in k
                and k.get("use", "sig") == "sig"
                and "verify" in k.get("key_ops", ["verify"])
            ]
            if len(matches) != 1:
                raise LoginRequired()
            key = jwt.PyJWK.from_dict(matches[0])
            if key.algorithm_name != header["alg"]:
                raise LoginRequired()
            claims = jwt.decode(
                assertion,
                key.key,
                algorithms=[header["alg"]],
                issuer=self.config.gateway_issuer,
                audience=self.config.gateway_audience,
                options={
                    "require": [
                        "exp",
                        "iat",
                        "sub",
                        "jti",
                        "session_binding",
                        "api_token_sha256",
                        "api_issuer",
                        "api_audience",
                        "api_expires_at",
                    ]
                },
            )
            now = self._clock()
            if (
                claims["session_binding"] != self.binding
                or claims["api_issuer"] != self.config.api_issuer
                or claims["api_audience"] != self.config.api_audience
                or claims["exp"] > now + 60
                or claims["api_token_sha256"] != hashlib.sha256(token.encode()).hexdigest()
                or not now + 5 < claims["api_expires_at"] <= now + 3600
                or not isinstance(claims["sub"], str)
                or not claims["sub"]
            ):
                raise LoginRequired()
            actor = (
                "oidc:"
                + hashlib.sha256(
                    (self.config.api_issuer + "\0" + claims["sub"]).encode()
                ).hexdigest()
            )
            if self._current and actor != self._current.actor_id:
                raise LoginRequired()
            self._current = UserCredential(
                actor, int(claims["api_expires_at"]), self.binding, SecretStr(token)
            )
            self._verified_until = min(now + 30, float(claims["exp"]))
            return self._current
        except Exception:
            self._current = None
            raise LoginRequired() from None

    def logout(self) -> None:
        try:
            self._exchange("logout")
        except Exception:
            pass
        finally:
            self._closed = True
            self._current = None
            self._client.close()


def effective_identity(value: dict[str, Any], credential: UserCredential) -> dict[str, Any]:
    if (
        value.get("actor_id") != credential.actor_id
        or not isinstance(value.get("expires_at"), int)
        or value["expires_at"] > credential.expires_at
        or value["expires_at"] <= time.time()
        or not isinstance(value.get("permission_scopes"), dict)
    ):
        raise LoginRequired()
    for name in ("roles", "permissions", "scopes"):
        if not isinstance(value.get(name), list) or not all(
            isinstance(v, str) for v in value[name]
        ):
            raise LoginRequired()
    return value
