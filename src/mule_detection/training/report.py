"""Authenticated encrypted run evidence with explicit incomplete/failed states.

This stores candidate research evidence, not registry-approved inference bundles.
Callers must authorize access and protect the root/key. No serialized model is
deserialized by evaluation; it reconstructs metrics from authenticated JSON.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mule_detection.domain.errors import DomainError, ErrorCode


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def encode(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def environment_identity(root: Path) -> dict[str, Any]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True
        ).stdout
    )
    paths = [
        *sorted((root / "src/mule_detection").rglob("*.py")),
        root / "pyproject.toml",
        *sorted(root.glob("requirements*.lock")),
        *sorted((root / "config").rglob("*.yaml")),
    ]
    return {
        "code_revision": revision,
        "dirty_tree": dirty,
        "source_sha256": {str(p.relative_to(root)): sha256(p.read_bytes()) for p in paths},
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in (
                "numpy",
                "pandas",
                "scikit-learn",
                "lightgbm",
                "scipy",
                "joblib",
                "threadpoolctl",
            )
        },
    }


class RunStore:
    def __init__(self, root: Path, key: bytes) -> None:
        if len(key) != 32:
            raise DomainError(ErrorCode.CONFIGURATION_INVALID)
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cipher = AESGCM(key)

    def path(self, run_id: UUID, name: str) -> Path:
        if not isinstance(run_id, UUID) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", name):
            raise DomainError(ErrorCode.INVALID_ARGUMENTS)
        path = self.root / str(run_id) / name
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise DomainError(ErrorCode.INVALID_ARGUMENTS)
        return path

    def state(self, run_id: UUID) -> dict[str, Any]:
        try:
            value: dict[str, Any] = json.loads(self.path(run_id, "state.json").read_bytes())
            return value
        except (OSError, ValueError):
            raise DomainError(ErrorCode.LINEAGE_INVALID) from None

    def begin(self, run_id: UUID, request_hash: str) -> bool:
        directory = self.path(run_id, "state.json").parent
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            state = self.state(run_id)
            if state.get("request_hash") != request_hash or state.get("status") != "SUCCEEDED":
                raise DomainError(ErrorCode.IDENTITY_CONFLICT) from None
            return False
        self._state(run_id, {"status": "RUNNING", "request_hash": request_hash})
        return True

    def _state(self, run_id: UUID, value: dict[str, Any]) -> None:
        temporary = self.path(run_id, f"state-{uuid4().hex}.tmp")
        self._write(temporary, encode(value))
        os.replace(temporary, self.path(run_id, "state.json"))

    @staticmethod
    def _write(path: Path, payload: bytes) -> None:
        with path.open("xb") as stream:
            path.chmod(0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    def put(self, run_id: UUID, name: str, payload: bytes) -> dict[str, Any]:
        if self.state(run_id)["status"] != "RUNNING":
            raise DomainError(ErrorCode.WORKFLOW_INVALID)
        nonce = os.urandom(12)
        encrypted = nonce + self.cipher.encrypt(nonce, payload, f"{run_id}/{name}".encode())
        path = self.path(run_id, name + ".enc")
        self._write(path, encrypted)
        return {"file": name + ".enc", "sha256": sha256(encrypted), "bytes": len(encrypted)}

    def put_json(self, run_id: UUID, name: str, value: Any) -> dict[str, Any]:
        return self.put(run_id, name, encode(value))

    def _read(self, run_id: UUID, metadata: dict[str, Any]) -> bytes:
        path = self.path(run_id, metadata["file"])
        payload = path.read_bytes()
        if len(payload) != metadata["bytes"] or sha256(payload) != metadata["sha256"]:
            raise DomainError(ErrorCode.HASH_MISMATCH)
        name = metadata["file"].removesuffix(".enc")
        try:
            return self.cipher.decrypt(payload[:12], payload[12:], f"{run_id}/{name}".encode())
        except Exception:
            raise DomainError(ErrorCode.HASH_MISMATCH) from None

    def finish(self, run_id: UUID, manifest: dict[str, Any]) -> None:
        # Verify all persisted artifacts before exposing a completed pointer.
        for metadata in manifest["files"].values():
            self._read(run_id, metadata)
        reference = self.put_json(run_id, "manifest.json", manifest)
        self._state(run_id, {**self.state(run_id), "status": "SUCCEEDED", "manifest": reference})

    def fail(self, run_id: UUID) -> None:
        state = self.state(run_id)
        if state["status"] == "RUNNING":
            self._state(
                run_id, {**state, "status": "FAILED", "reason": "TRAINING_OR_EVALUATION_FAILED"}
            )

    def manifest(self, run_id: UUID) -> dict[str, Any]:
        state = self.state(run_id)
        if state["status"] != "SUCCEEDED":
            raise DomainError(ErrorCode.WORKFLOW_INVALID)
        manifest: dict[str, Any] = json.loads(self._read(run_id, state["manifest"]))
        if manifest.get("run_id") != str(run_id) or manifest.get("request_hash") != state.get(
            "request_hash"
        ):
            raise DomainError(ErrorCode.LINEAGE_INVALID)
        for metadata in manifest["files"].values():
            self._read(run_id, metadata)
        return manifest

    def json(self, run_id: UUID, name: str, manifest: dict[str, Any]) -> Any:
        return json.loads(self._read(run_id, manifest["files"][name]))
