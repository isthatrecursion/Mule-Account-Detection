"""Ephemeral signing material used only by explicitly isolated test applications."""

import json
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from mule_detection.api.auth import AuthConfig


class SigningAuthority:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        public.update(kid="test-key", alg="RS256", use="sig")
        self.config = AuthConfig(
            issuer="https://isolated.example.test",
            audience="review-api-test",
            static_jwks={"keys": [public]},
            isolated_test=True,
            clock_skew_seconds=0,
            groups={
                f"{role}-{scope}": {"roles": [role], "scopes": [scope]}
                for role in ("analyst", "reviewer", "operator", "engineer", "auditor")
                for scope in ("synthetic-team", "other-team")
            },
        )

    def token(self, role="analyst", scope="synthetic-team", subject=None, **changes):
        claims = {
            "iss": self.config.issuer,
            "aud": self.config.audience,
            "sub": subject or role,
            "iat": int(time.time()) - 1,
            "exp": int(time.time()) + 3600,
            "groups": [f"{role}-{scope}"],
        }
        claims.update(changes)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "test-key"})

    def headers(self, role="analyst", scope="synthetic-team", subject=None, **changes):
        return {"Authorization": "Bearer " + self.token(role, scope, subject, **changes)}
