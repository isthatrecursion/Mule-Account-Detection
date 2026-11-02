"""Verified OIDC identities. No request header can grant a role or case scope."""

import hashlib
import json
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
from pydantic import BaseModel, ConfigDict, Field, model_validator


class AuthenticationRequired(Exception):
    pass


class Grant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    roles: frozenset[str]
    scopes: frozenset[str]
    permissions: frozenset[str] = frozenset()


ROLE_PERMISSIONS = {
    "analyst": {"queue:read", "case:read", "case:assign", "case:review", "note:read"},
    "reviewer": {
        "queue:read",
        "case:read",
        "case:assign",
        "case:review",
        "case:reopen",
        "note:read",
        "audit:read",
        "export:create",
        "label:submit",
    },
    "engineer": {"model:train", "job:read", "batch:read", "train:submit"},
    "operator": {"batch:intake", "batch:read", "score:submit", "job:read", "job:retry"},
    "auditor": {"audit:read"},
}


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    algorithms: tuple[str, ...] = ("RS256",)
    jwks_url: str | None = None
    static_jwks: dict[str, Any] | None = None
    isolated_test: bool = False
    groups_claim: str = "groups"
    groups: dict[str, Grant]
    clock_skew_seconds: int = Field(default=30, ge=0, le=60)
    cache_seconds: int = Field(default=300, ge=1, le=300)

    @model_validator(mode="after")
    def trusted_configuration(self) -> "AuthConfig":
        if (
            not self.algorithms
            or not set(self.algorithms) <= {"RS256", "ES256"}
            or not self.groups
            or not self.issuer.startswith("https://")
        ):
            raise ValueError("OIDC trust configuration is required")
        if self.static_jwks is not None:
            if not self.isolated_test or self.jwks_url is not None:
                raise ValueError("Static signing keys are restricted to isolated tests")
        elif not self.jwks_url or not self.jwks_url.startswith("https://"):
            raise ValueError("An HTTPS JWKS source is required")
        for grant in self.groups.values():
            if not grant.roles or not grant.roles <= ROLE_PERMISSIONS.keys() or not grant.scopes:
                raise ValueError("Explicit supported roles and scopes are required")
            if not grant.permissions <= {"export:sensitive"} or (
                grant.permissions and "reviewer" not in grant.roles
            ):
                raise ValueError("Sensitive exports require an explicit reviewer grant")
        return self

    @classmethod
    def load(cls, root: Path, environment: str) -> "AuthConfig":
        try:
            config = cls.model_validate_json((root / "secrets/oidc.json").read_bytes())
            if config.isolated_test or config.static_jwks is not None:
                raise ValueError()
            return config
        except Exception:
            raise ValueError("API startup requires complete OIDC trust configuration") from None


@dataclass(frozen=True)
class Principal:
    actor_id: str
    roles: frozenset[str]
    permissions: frozenset[str]
    scopes: frozenset[str]
    expires_at: int
    permission_scopes: dict[str, frozenset[str]]
    role_scopes: dict[str, frozenset[str]]

    def require(self, permission: str) -> None:
        from mule_detection.persistence.errors import AccessDenied

        if permission not in self.permissions:
            raise AccessDenied()

    def payload(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "roles": sorted(self.roles),
            "permissions": sorted(self.permissions),
            "scopes": sorted(self.scopes),
            "expires_at": self.expires_at,
            "permission_scopes": {p: sorted(s) for p, s in self.permission_scopes.items()},
            "role_scopes": {r: sorted(s) for r, s in self.role_scopes.items()},
        }

    def for_permission(self, permission: str) -> "Principal":
        from dataclasses import replace

        self.require(permission)
        return replace(
            self, scopes=self.scopes & self.permission_scopes.get(permission, frozenset())
        )

    @classmethod
    def restore(cls, value: dict[str, Any]) -> "Principal":
        return cls(
            value["actor_id"],
            frozenset(value["roles"]),
            frozenset(value["permissions"]),
            frozenset(value["scopes"]),
            value["expires_at"],
            {p: frozenset(s) for p, s in value["permission_scopes"].items()},
            {r: frozenset(s) for r, s in value["role_scopes"].items()},
        )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


class TokenVerifier:
    def __init__(self, config: AuthConfig, environment: str) -> None:
        if config.isolated_test and environment != "test":
            raise ValueError("Test identity configuration requires a test application")
        self.config = config
        self._keys: dict[str, Any] = {}
        self._until = 0.0
        self._last_refresh = -100.0
        self._lock = threading.Lock()

    def _key(self, kid: str, algorithm: str) -> Any:
        now = time.monotonic()
        with self._lock:
            if now >= self._until or (kid not in self._keys and now - self._last_refresh >= 30):
                raw = self.config.static_jwks
                if raw is None:
                    assert self.config.jwks_url is not None
                    opener = urllib.request.build_opener(NoRedirect())
                    with opener.open(self.config.jwks_url, timeout=5) as response:
                        data = response.read(1_048_577)
                    if len(data) > 1_048_576:
                        raise AuthenticationRequired()
                    raw = json.loads(data)
                entries = raw.get("keys", [])
                if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
                    raise AuthenticationRequired()
                keys = {}
                for item in entries:
                    if (
                        item.get("use", "sig") != "sig"
                        or "d" in item
                        or ("key_ops" in item and "verify" not in item["key_ops"])
                    ):
                        continue
                    entry_kid = item.get("kid")
                    if not isinstance(entry_kid, str) or entry_kid in keys:
                        raise AuthenticationRequired()
                    keys[entry_kid] = jwt.PyJWK.from_dict(item)
                self._keys = keys
                self._until = now + self.config.cache_seconds
                self._last_refresh = now
            key = self._keys.get(kid)
            if key is None or key.algorithm_name != algorithm:
                raise AuthenticationRequired()
            return key.key

    def verify(self, authorization: str | None) -> Principal:
        try:
            if (
                not authorization
                or not authorization.startswith("Bearer ")
                or len(authorization) > 8192
            ):
                raise AuthenticationRequired()
            token = authorization[7:]
            header = jwt.get_unverified_header(token)
            algorithm, kid = header.get("alg"), header.get("kid")
            if (
                algorithm not in self.config.algorithms
                or not isinstance(kid, str)
                or len(kid) > 200
                or any(k in header for k in ("jku", "x5u", "crit"))
            ):
                raise AuthenticationRequired()
            claims = jwt.decode(
                token,
                self._key(kid, algorithm),
                algorithms=list(self.config.algorithms),
                issuer=self.config.issuer,
                audience=self.config.audience,
                leeway=self.config.clock_skew_seconds,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            subject, groups = claims["sub"], claims.get(self.config.groups_claim, [])
            if (
                not isinstance(subject, str)
                or not 1 <= len(subject) <= 512
                or not isinstance(groups, list)
                or len(groups) > 100
                or not all(isinstance(g, str) for g in groups)
            ):
                raise AuthenticationRequired()
            grants = [self.config.groups[g] for g in groups if g in self.config.groups]
            roles = frozenset(r for grant in grants for r in grant.roles)
            scopes = frozenset(s for grant in grants for s in grant.scopes)
            permissions = frozenset(
                p for role in roles for p in ROLE_PERMISSIONS[role]
            ) | frozenset(p for grant in grants for p in grant.permissions)
            actor = (
                "oidc:" + hashlib.sha256((self.config.issuer + "\0" + subject).encode()).hexdigest()
            )
            role_scopes = {
                r: frozenset(s for g in grants if r in g.roles for s in g.scopes) for r in roles
            }
            permission_scopes = {
                p: frozenset(s for r in roles if p in ROLE_PERMISSIONS[r] for s in role_scopes[r])
                for p in permissions
            }
            for grant in grants:
                for permission in grant.permissions:
                    permission_scopes[permission] = (
                        permission_scopes.get(permission, frozenset()) | grant.scopes
                    )
            return Principal(
                actor,
                roles,
                permissions,
                scopes,
                int(claims["exp"]),
                permission_scopes,
                role_scopes,
            )
        except Exception:
            raise AuthenticationRequired() from None
