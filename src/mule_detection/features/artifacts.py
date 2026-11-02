"""Trusted internal feature artifacts, finalized by an independently recorded digest.

Joblib can execute code. Callers must protect the root and expected digest through
registry approval (Phase 7). These are never analyst upload/download endpoints.
Training statistics are confidential: use approved encrypted storage/ACLs.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
from pathlib import Path
from typing import Any
from uuid import uuid4

import joblib  # type: ignore[import-untyped]
from sklearn.utils.validation import check_is_fitted  # type: ignore[import-untyped]

from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.features.pipeline import FeaturePipeline


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def runtime_identity() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "scipy", "scikit-learn", "joblib")
        },
    }


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def save_pipeline(
    pipeline: FeaturePipeline,
    root: Path,
    *,
    split_fingerprint: str,
    code_identity: str,
) -> tuple[Path, str]:
    check_is_fitted(pipeline, "transformer_")
    if len(split_fingerprint) != 64 or any(c not in "0123456789abcdef" for c in split_fingerprint):
        raise DomainError(ErrorCode.LINEAGE_INVALID)
    if not code_identity.strip():
        raise DomainError(ErrorCode.LINEAGE_INVALID)
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    staging = root / (".staging-" + uuid4().hex)
    staging.mkdir()
    with (staging / "pipeline.joblib").open("xb") as stream:
        joblib.dump(pipeline, stream, compress=3)
        stream.flush()
        os.fsync(stream.fileno())
    documents = {
        "input_signature.json": pipeline.input_signature_,
        "transformed_features.json": pipeline.transformed_features_,
        "exclusions.json": pipeline.exclusion_report_,
        "reference_statistics.json": pipeline.reference_statistics_,
        "feature_policy.json": pipeline.policy.model_dump(mode="json"),
        "semantic_rules.json": pipeline.semantic_rules_.model_dump(mode="json"),
    }
    for name, content in documents.items():
        write_json(staging / name, content)
    files = {
        path.name: {"sha256": digest(path), "bytes": path.stat().st_size}
        for path in staging.iterdir()
    }
    manifest = {
        "format": "feature_pipeline_v1",
        "files": files,
        "runtime": runtime_identity(),
        "training_fingerprint": pipeline.training_fingerprint_,
        "split_fingerprint": split_fingerprint,
        "code_identity": code_identity,
        "semantic_version": pipeline.semantic_version,
        "data_tier": pipeline.data_tier,
        "feature_policy_hash": pipeline.policy.fingerprint,
    }
    # Manifest is last; consumers never scan staging directories.
    write_json(staging / "manifest.json", manifest)
    manifest_digest = digest(staging / "manifest.json")
    published = root / manifest_digest
    staging.rename(published)  # No overwrite of an existing immutable publication.
    return published, manifest_digest


def load_pipeline(directory: Path, *, allowed_root: Path, expected_digest: str) -> FeaturePipeline:
    root, directory = allowed_root.resolve(), directory.resolve()
    if not directory.is_relative_to(root) or directory.name != expected_digest:
        raise DomainError(ErrorCode.HASH_MISMATCH)
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink() or digest(manifest_path) != expected_digest:
        raise DomainError(ErrorCode.HASH_MISMATCH)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_files = {
        "pipeline.joblib",
        "input_signature.json",
        "transformed_features.json",
        "exclusions.json",
        "reference_statistics.json",
        "feature_policy.json",
        "semantic_rules.json",
    }
    if manifest["format"] != "feature_pipeline_v1" or set(manifest["files"]) != expected_files:
        raise DomainError(ErrorCode.LINEAGE_INVALID)
    if manifest["runtime"] != runtime_identity():
        raise DomainError(ErrorCode.LINEAGE_INVALID)
    for name, metadata in manifest["files"].items():
        path = directory / name
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(directory)
            or path.stat().st_size != metadata["bytes"]
            or digest(path) != metadata["sha256"]
        ):
            raise DomainError(ErrorCode.HASH_MISMATCH)
    loaded = joblib.load(directory / "pipeline.joblib")
    if not isinstance(loaded, FeaturePipeline):
        raise DomainError(ErrorCode.LINEAGE_INVALID)
    if (
        loaded.training_fingerprint_ != manifest["training_fingerprint"]
        or loaded.policy.fingerprint != manifest["feature_policy_hash"]
        or loaded.semantic_version != manifest["semantic_version"]
        or loaded.data_tier != manifest["data_tier"]
    ):
        raise DomainError(ErrorCode.LINEAGE_INVALID)
    return loaded
