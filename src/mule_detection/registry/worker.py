"""One-request, credential-free, resource-limited trusted bundle worker.

Run as a module. Input/output is private JSON over pipes; model bytes never enter
the parent process. Container/host ACLs remain the OS permission boundary.
"""

from __future__ import annotations

import importlib.metadata
import io
import json
import os
import sys
from typing import Any

import joblib  # type: ignore[import-untyped]
import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from mule_detection.domain.contracts.common import canonical_hash
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.registry.bundle_writer import BundleStore
from mule_detection.training.model_factory import FittedCandidate


def limit_resources() -> None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64),
                ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD),
                ("min_working", ctypes.c_size_t),
                ("max_working", ctypes.c_size_t),
                ("active", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class Counters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "read_ops",
                    "write_ops",
                    "other_ops",
                    "read_bytes",
                    "write_bytes",
                    "other_bytes",
                )
            ]

        class Limits(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", Counters),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        handle = kernel.CreateJobObjectW(None, None)
        limits = Limits()
        limits.basic.flags = 0x100 | 0x8 | 0x2  # process memory, active count, CPU time
        limits.basic.active = 1
        limits.basic.process_time = 120 * 10_000_000
        limits.process_memory = 8 * 1024**3
        if (
            not handle
            or not kernel.SetInformationJobObject(
                handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            )
            or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess())
        ):
            raise RuntimeError("Worker resource confinement unavailable")
        # OS closes the handle on worker exit; do not end the containing job.
    else:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
        resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3, 8 * 1024**3))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def restore(store: BundleStore, digest: str) -> FittedCandidate:
    manifest = store.inspect(digest)
    contract = manifest["contract"]
    import platform

    versions = {
        name: importlib.metadata.version(name)
        for name in contract["runtime_versions"]
        if name != "python"
    }
    versions["python"] = platform.python_version()
    if versions != contract["runtime_versions"]:
        raise DomainError(ErrorCode.LINEAGE_INVALID)

    def raw(name: str) -> bytes:
        return store.read(digest, name, manifest["files"][name])

    signature = json.loads(raw("input_signature.json"))
    transformed = json.loads(raw("transformed_features.json"))
    if (
        canonical_hash({"columns": signature}) != contract["input_signature"]
        or canonical_hash({"features": transformed}) != contract["transformed_signature"]
    ):
        raise DomainError(ErrorCode.SCHEMA_MISMATCH)
    features = joblib.load(io.BytesIO(raw("pipeline.joblib")))
    model = joblib.load(io.BytesIO(raw("model.joblib")))
    if not isinstance(features, FeaturePipeline) or set(model) != {
        "estimator",
        "scaler",
        "numeric_stop",
        "threads",
    }:
        raise DomainError(ErrorCode.LINEAGE_INVALID)
    if (
        features.input_signature_ != signature
        or features.transformed_features_ != transformed
        or features.training_fingerprint_ != contract["training_fingerprint"]
        or features.policy.fingerprint != contract["feature_policy_hash"]
        or model["numeric_stop"] != features.transformer_.output_indices_["numeric"].stop
        or model["estimator"].n_features_in_ != features.n_features_out_
    ):
        raise DomainError(ErrorCode.LINEAGE_INVALID)
    fitted = FittedCandidate(
        features, model["estimator"], model["scaler"], model["numeric_stop"], model["threads"]
    )
    fixture = json.loads(raw("validation_fixture.json"))
    frame = pd.read_json(io.StringIO(fixture["frame_table"]), orient="table")
    np.testing.assert_allclose(
        fitted.predict_score(frame),
        fixture["predictions"],
        atol=fixture["atol"],
        rtol=fixture["rtol"],
    )
    return fitted


def main() -> int:
    try:
        payload = sys.stdin.buffer.read(64 * 1024 * 1024 + 1)
        if len(payload) > 64 * 1024 * 1024:
            raise DomainError(ErrorCode.VALUE_INVALID)
        request = json.loads(payload)
        limit_resources()
        # The parent passes no database/tracking credentials. Remove residual
        # application overrides before trusted executable artifacts are loaded.
        for name in list(os.environ):
            if name.startswith(("MULE_", "MLFLOW_", "AWS_", "AZURE_")):
                os.environ.pop(name)
        from pathlib import Path

        store = BundleStore(Path(request["root"]), bytes.fromhex(request["key"]))
        fitted = restore(store, request["digest"])
        response: dict[str, Any] = {"ok": True}
        if request["operation"] in {"predict", "explain"}:
            frame = pd.read_json(io.StringIO(request["frame_table"]), orient="table")
            response["scores"] = fitted.predict_score(frame).tolist()
            if request["operation"] == "explain":
                from mule_detection.explanations.evidence_builder import build_evidence

                response["evidence"] = build_evidence(fitted, frame)
        elif request["operation"] != "verify":
            raise DomainError(ErrorCode.INVALID_ARGUMENTS)
        print(json.dumps(response, allow_nan=False))
        return 0
    except Exception:
        print('{"ok":false,"code":"BUNDLE_VERIFICATION_FAILED"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
