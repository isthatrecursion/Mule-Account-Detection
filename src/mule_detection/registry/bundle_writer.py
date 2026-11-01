"""Encrypted immutable model bundles; published identity is SHA-256(bundle.json)."""

from __future__ import annotations

import importlib.metadata
import io
import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import joblib  # type: ignore[import-untyped]
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mule_detection.domain.contracts.common import canonical_hash
from mule_detection.domain.contracts.models import ModelBundle
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.features.artifacts import runtime_identity
from mule_detection.training.model_factory import FittedCandidate
from mule_detection.training.report import encode, environment_identity, sha256

FILES = frozenset(
    {
        "pipeline.joblib",
        "model.joblib",
        "input_signature.json",
        "transformed_features.json",
        "reference_statistics.json",
        "model_card.md",
        "environment.json",
        "validation_fixture.json",
        "lineage.json",
        "feature_policy.json",
    }
)


class BundleStore:
    def __init__(self, root: Path, key: bytes) -> None:
        if len(key) != 32:
            raise DomainError(ErrorCode.CONFIGURATION_INVALID)
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.key = key

    def path(self, digest: str) -> Path:
        if re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            raise DomainError(ErrorCode.INVALID_ARGUMENTS)
        path = self.root / digest
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise DomainError(ErrorCode.INVALID_ARGUMENTS)
        return path

    def inspect(self, digest: str) -> dict[str, Any]:
        directory = self.path(digest)
        path = directory / "bundle.json"
        try:
            payload = path.read_bytes()
            if path.is_symlink() or sha256(payload) != digest:
                raise DomainError(ErrorCode.HASH_MISMATCH)
            manifest: dict[str, Any] = json.loads(payload)
            contract = ModelBundle.model_validate(manifest["contract"])
            if manifest["format"] != "inference_bundle_v1" or set(manifest["files"]) != FILES:
                raise DomainError(ErrorCode.LINEAGE_INVALID)
            for logical, name in {
                "model": "model.joblib",
                "pipeline": "pipeline.joblib",
                "peer_reference": "reference_statistics.json",
                "model_card": "model_card.md",
            }.items():
                if (
                    contract.artifact_digests[logical]
                    != manifest["files"][name]["plaintext_sha256"]
                ):
                    raise DomainError(ErrorCode.LINEAGE_INVALID)
            for name, meta in manifest["files"].items():
                self.read(digest, name, meta)
            if (
                contract.input_signature != manifest["input_signature_hash"]
                or contract.transformed_signature != manifest["transformed_signature_hash"]
            ):
                raise DomainError(ErrorCode.LINEAGE_INVALID)
            return manifest
        except (OSError, ValueError, KeyError, TypeError):
            raise DomainError(ErrorCode.LINEAGE_INVALID) from None

    def read(self, digest: str, name: str, metadata: dict[str, Any]) -> bytes:
        if name not in FILES or metadata["file"] != name + ".enc":
            raise DomainError(ErrorCode.LINEAGE_INVALID)
        path = self.path(digest) / metadata["file"]
        if path.is_symlink() or not path.resolve().is_relative_to(self.path(digest)):
            raise DomainError(ErrorCode.HASH_MISMATCH)
        payload = path.read_bytes()
        if sha256(payload) != metadata["sha256"] or len(payload) != metadata["bytes"]:
            raise DomainError(ErrorCode.HASH_MISMATCH)
        try:
            plain = AESGCM(self.key).decrypt(payload[:12], payload[12:], name.encode())
        except Exception:
            raise DomainError(ErrorCode.HASH_MISMATCH) from None
        if sha256(plain) != metadata["plaintext_sha256"]:
            raise DomainError(ErrorCode.HASH_MISMATCH)
        return plain


def write_bundle(
    fitted: FittedCandidate,
    lineage: dict[str, Any],
    fixture: Any,
    store: BundleStore,
    *,
    root: Path,
    dictionary_version: str = "research_dictionary_v1",
) -> str:
    # A fresh prediction fixture proves the pipeline/model pairing before publication.
    expected = fitted.predict_score(fixture).tolist()
    binary = io.BytesIO()
    joblib.dump(fitted.features, binary, compress=3)
    pipeline = binary.getvalue()
    binary = io.BytesIO()
    joblib.dump(
        {
            "estimator": fitted.estimator,
            "scaler": fitted.scaler,
            "numeric_stop": fitted.numeric_stop,
            "threads": fitted.threads,
        },
        binary,
        compress=3,
    )
    model = binary.getvalue()
    features = fitted.features
    documents = {
        "pipeline.joblib": pipeline,
        "model.joblib": model,
        "input_signature.json": encode(features.input_signature_),
        "transformed_features.json": encode(features.transformed_features_),
        "reference_statistics.json": encode(features.reference_statistics_),
        "feature_policy.json": encode(features.policy.model_dump(mode="json")),
        "model_card.md": (
            b"# Research inference bundle\n\nRanking only; qualified promotion BLOCKED.\nFinal-fit demo outputs are in-sample.\nExtraction cohort and target remain confounded.\nNo automatic account actions.\n"
        ),
        "environment.json": encode(environment_identity(root)),
        "validation_fixture.json": encode(
            {
                "frame_table": fixture.to_json(orient="table", index=False),
                "predictions": expected,
                "atol": 1e-12,
                "rtol": 0.0,
                "scope": "IN_SAMPLE_PARITY_ONLY",
            }
        ),
        "lineage.json": encode(lineage),
    }
    staging = store.root / (".staging-" + uuid4().hex)
    staging.mkdir(mode=0o700)
    files = {}
    for name, payload in documents.items():
        nonce = os.urandom(12)
        encrypted = nonce + AESGCM(store.key).encrypt(nonce, payload, name.encode())
        with (staging / (name + ".enc")).open("xb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        files[name] = {
            "file": name + ".enc",
            "sha256": sha256(encrypted),
            "plaintext_sha256": sha256(payload),
            "bytes": len(encrypted),
        }
    contract = ModelBundle(
        contract_version="model_bundle_v1",
        bundle_id=uuid5(NAMESPACE_URL, sha256(pipeline) + sha256(model)),
        artifact_digests={
            "pipeline": sha256(pipeline),
            "model": sha256(model),
            "peer_reference": sha256(documents["reference_statistics.json"]),
            "model_card": sha256(documents["model_card.md"]),
        },
        input_signature=canonical_hash({"columns": features.input_signature_}),
        transformed_signature=canonical_hash({"features": features.transformed_features_}),
        training_fingerprint=features.training_fingerprint_,
        feature_policy_version=features.policy.policy_version,
        feature_policy_hash=features.policy.fingerprint,
        runtime_versions={
            **runtime_identity()["packages"],
            "python": runtime_identity()["python"],
            "lightgbm": importlib.metadata.version("lightgbm"),
        },
        output_scale="review_priority",
        contribution_scale="raw_margin",
        research_only=True,
        model_tier="research_demo",
        model_card_reference="model_card.md",
        dictionary_version=dictionary_version,
        calibration_approval_reference=None,
    )
    manifest = {
        "format": "inference_bundle_v1",
        "contract": contract.model_dump(mode="json"),
        "files": files,
        "input_signature_hash": contract.input_signature,
        "transformed_signature_hash": contract.transformed_signature,
        "training_run_id": lineage["training_run_id"],
        "trainer_id": lineage["trainer_id"],
        "data_tier": lineage["data_tier"],
        "lineage_hash": sha256(documents["lineage.json"]),
    }
    payload = encode(manifest)
    digest = sha256(payload)
    with (staging / "bundle.json").open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    staging.rename(store.path(digest))
    store.inspect(digest)
    from mule_detection.registry.bundle_loader import BundleLoader

    BundleLoader(store, lambda *_: False).verify_candidate(digest)
    return digest
