"""Encrypted content-addressed JSON snapshots with authorized, digest-checked reads.

The local adapter is for approved small frames. Schema conversion/Parquet is deferred until
validated. Storage keys come from external secrets; storage ACLs and backup policy are required.
"""

import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mule_detection.application.context import ExecutionContext
from mule_detection.persistence.errors import AccessDenied


@dataclass(frozen=True)
class ArtifactRef:
    digest: str
    schema_id: str
    row_count: int
    access_scope: str

    @property
    def uri(self) -> str:
        return f"artifact:sha256:{self.digest}"


class ArtifactStore:
    def __init__(
        self,
        root: Path,
        key: bytes,
        authorize: Callable[[ExecutionContext, str, str], bool],
        *,
        max_bytes: int = 134217728,
    ) -> None:
        if len(key) != 32:
            raise ValueError("An externally supplied 256-bit artifact key is required")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._cipher = AESGCM(key)
        self.authorize = authorize
        self.max_bytes = max_bytes

    def _path(self, digest: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("Invalid artifact identity")
        path = self.root / digest[:2] / (digest + ".enc")
        if not path.resolve().is_relative_to(self.root):
            raise AccessDenied()
        return path

    def _check(self, context: ExecutionContext, scope: str, action: str) -> None:
        if not self.authorize(context, scope, action):
            raise AccessDenied()

    def put(
        self,
        records: Mapping[str, Mapping[str, object]],
        *,
        schema_id: str,
        access_scope: str,
        context: ExecutionContext,
    ) -> ArtifactRef:
        self._check(context, access_scope, "write")
        payload = json.dumps(
            {
                "format": "snapshot_json_v1",
                "schema_id": schema_id,
                "access_scope": access_scope,
                "records": records,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        if len(payload) > self.max_bytes:
            raise ValueError("Artifact exceeds configured size")
        digest = sha256(payload).hexdigest()
        ref = ArtifactRef(digest, schema_id, len(records), access_scope)
        path = self._path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        nonce = os.urandom(12)
        encrypted = nonce + self._cipher.encrypt(nonce, payload, digest.encode())
        # Hard-link publication is atomic and refuses replacement, even with concurrent writers.
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            try:
                os.link(temporary, path)
                path.chmod(0o600)
            except FileExistsError:
                self._read(ref)  # Existing data must be authentic, never silently replaced.
        finally:
            temporary.unlink()
        return ref

    def _read(self, reference: ArtifactRef) -> dict[str, object]:
        path = self._path(reference.digest)
        if path.stat().st_size > self.max_bytes + 28:
            raise ValueError("Artifact exceeds configured size")
        encrypted = path.read_bytes()
        payload = self._cipher.decrypt(encrypted[:12], encrypted[12:], reference.digest.encode())
        if sha256(payload).hexdigest() != reference.digest:
            raise ValueError("Artifact digest mismatch")
        value = json.loads(payload)
        if (
            value["format"] != "snapshot_json_v1"
            or value["schema_id"] != reference.schema_id
            or value["access_scope"] != reference.access_scope
            or len(value["records"]) != reference.row_count
        ):
            raise ValueError("Artifact metadata mismatch")
        records: dict[str, object] = value["records"]
        return records

    def observation(
        self,
        reference: ArtifactRef,
        record_key: str,
        context: ExecutionContext,
    ) -> object:
        self._check(context, reference.access_scope, "read")
        return self._read(reference)[record_key]
