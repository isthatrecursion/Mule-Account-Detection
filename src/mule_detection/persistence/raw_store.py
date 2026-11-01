"""Bounded private staging and encrypted, non-overwriting content publication.

Staging plaintext needs protected directory ACLs. Final objects are authenticated ciphertext.
No path supplied by a caller is ever used as an object/staging filename.
"""

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mule_detection.domain.validation_policy import IntakeRejected


@dataclass(frozen=True)
class StagedRaw:
    stage_id: UUID
    digest: str
    byte_count: int


class RawStore:
    def __init__(self, root: Path, key: bytes, *, max_bytes: int = 134217728) -> None:
        if len(key) != 32 or max_bytes <= 0:
            raise ValueError("A protected store and 256-bit key are required")
        self.root = root.resolve()
        self.cipher = AESGCM(key)
        self.max_bytes = max_bytes
        for name in ("staging", "objects"):
            directory = self.root / name
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)
            self._inside(directory)

    def _inside(self, path: Path) -> Path:
        if not path.resolve().is_relative_to(self.root) or path.is_symlink():
            raise IntakeRejected("STORAGE_BOUNDARY")
        return path

    def staging_path(self, stage_id: UUID) -> Path:
        if not isinstance(stage_id, UUID):
            raise IntakeRejected("STORAGE_BOUNDARY")
        return self._inside(self.root / "staging" / f"{stage_id}.part")

    def object_path(self, digest: str) -> Path:
        if re.fullmatch("[a-f0-9]{64}", digest) is None:
            raise IntakeRejected("STORAGE_BOUNDARY")
        return self._inside(self.root / "objects" / f"{digest}.enc")

    def stage(self, stream: BinaryIO, *, stage_id: UUID | None = None) -> StagedRaw:
        identity = stage_id or uuid4()
        path = self.staging_path(identity)
        digest = hashlib.sha256()
        size = 0
        first = True
        with path.open("xb") as destination:
            path.chmod(0o600)
            while chunk := stream.read(min(1024 * 1024, self.max_bytes + 1)):
                size += len(chunk)
                if size > self.max_bytes:
                    raise IntakeRejected("BYTE_LIMIT")
                if first and chunk.startswith((b"\x1f\x8b", b"PK\x03\x04", b"BZh", b"\xfd7zXZ")):
                    raise IntakeRejected("COMPRESSED_INPUT")
                first = False
                digest.update(chunk)
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        # A stream may return fewer bytes than requested, including a one-byte first chunk.
        with path.open("rb") as source:
            if source.read(8).startswith(
                (b"\x1f\x8b", b"PK", b"BZh", b"\xfd7zXZ", b"\x28\xb5\x2f\xfd")
            ):
                raise IntakeRejected("COMPRESSED_INPUT")
        return StagedRaw(identity, digest.hexdigest(), size)

    def read(self, digest: str) -> bytes:
        path = self.object_path(digest)
        if path.stat().st_size > self.max_bytes + 28:
            raise IntakeRejected("BYTE_LIMIT")
        data = path.read_bytes()
        payload = self.cipher.decrypt(data[:12], data[12:], digest.encode())
        if hashlib.sha256(payload).hexdigest() != digest:
            raise IntakeRejected("HASH_MISMATCH")
        return payload

    def finalize(self, staged: StagedRaw) -> str:
        target = self.object_path(staged.digest)
        path = self.staging_path(staged.stage_id)
        if path.exists():
            if path.stat().st_size != staged.byte_count or staged.byte_count > self.max_bytes:
                raise IntakeRejected("BYTE_LIMIT")
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != staged.digest:
                raise IntakeRejected("HASH_MISMATCH")
            nonce = os.urandom(12)
            encrypted = nonce + self.cipher.encrypt(nonce, payload, staged.digest.encode())
            temporary = self._inside(self.root / "objects" / f"{uuid4()}.tmp")
            try:
                with temporary.open("xb") as destination:
                    temporary.chmod(0o600)
                    destination.write(encrypted)
                    destination.flush()
                    os.fsync(destination.fileno())
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    self.read(staged.digest)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            self.read(staged.digest)  # Recovery after publication but before DB acknowledgement.
        return f"raw:sha256:{staged.digest}"

    def discard_stage(self, stage_id: UUID) -> None:
        self.staging_path(stage_id).unlink(missing_ok=True)
