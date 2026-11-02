"""Only independently authorized bundle identities enter the executable worker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from typing import Any

from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.registry.bundle_writer import BundleStore


class BundleLoader:
    def __init__(self, store: BundleStore, authorize: Callable[[str, str], bool]) -> None:
        self.store, self.authorize = store, authorize

    def _worker(self, digest: str, operation: str, frame: Any = None) -> dict[str, Any]:
        self.store.inspect(digest)
        request = {
            "root": str(self.store.root),
            "key": self.store.key.hex(),
            "digest": digest,
            "operation": operation,
        }
        if frame is not None:
            request["frame_table"] = frame.to_json(orient="table", index=False)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "TMPDIR"}
        }
        environment.update(
            PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2"
        )
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NO_WINDOW
        else:
            creation_flags = 0
        with tempfile.TemporaryDirectory(dir=self.store.root, prefix=".worker-") as work:
            try:
                completed = subprocess.run(
                    [sys.executable, "-I", "-m", "mule_detection.registry.worker"],
                    input=json.dumps(request),
                    capture_output=True,
                    text=True,
                    cwd=work,
                    env=environment,
                    timeout=150,
                    creationflags=creation_flags,
                )
                response: dict[str, Any] = json.loads(completed.stdout)
                if completed.returncode or not response.get("ok"):
                    raise DomainError(ErrorCode.LINEAGE_INVALID)
                return response
            except (OSError, ValueError, subprocess.TimeoutExpired):
                raise DomainError(ErrorCode.LINEAGE_INVALID) from None

    def verify_candidate(self, digest: str) -> None:
        """Internal packaging check; does not grant inference authorization."""
        self._worker(digest, "verify")

    def load(self, digest: str, environment: str) -> LoadedBundle:
        if not self.authorize(digest, environment):
            raise DomainError(ErrorCode.CONTRACT_INVALID)
        self._worker(digest, "verify")
        return LoadedBundle(self, digest, environment)


class LoadedBundle:
    def __init__(self, loader: BundleLoader, digest: str, environment: str) -> None:
        self.loader, self.digest, self.environment = loader, digest, environment

    def predict_score(self, frame: Any) -> Any:
        if not self.loader.authorize(self.digest, self.environment):
            raise DomainError(ErrorCode.CONTRACT_INVALID)
        return self.loader._worker(self.digest, "predict", frame)["scores"]

    def explain(self, frame: Any) -> dict[str, Any]:
        if not self.loader.authorize(self.digest, self.environment):
            raise DomainError(ErrorCode.CONTRACT_INVALID)
        return self.loader._worker(self.digest, "explain", frame)
