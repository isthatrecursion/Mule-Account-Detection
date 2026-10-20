from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mule_detection.application.context import ExecutionContext
from mule_detection.persistence.artifacts import ArtifactStore
from mule_detection.persistence.errors import AccessDenied


def test_immutable_encrypted_authorized_historical_observations(tmp_path):
    context = ExecutionContext.create("synthetic", "test")
    key = AESGCM.generate_key(bit_length=256)

    def allow(actor, scope, action):
        return actor.actor_id == "synthetic" and scope == "team-a"

    store = ArtifactStore(tmp_path, key, allow)
    older = store.put(
        {"record": {"value": "SYNTHETIC_PRIVATE_VALUE"}},
        schema_id="synthetic_v1",
        access_scope="team-a",
        context=context,
    )
    newer = store.put(
        {"record": {"value": "changed"}},
        schema_id="synthetic_v1",
        access_scope="team-a",
        context=context,
    )
    assert older.digest != newer.digest
    assert store.observation(older, "record", context) == {"value": "SYNTHETIC_PRIVATE_VALUE"}
    files = list(tmp_path.rglob("*.enc"))
    assert all(b"SYNTHETIC_PRIVATE_VALUE" not in path.read_bytes() for path in files)
    assert (
        store.put(
            {"record": {"value": "SYNTHETIC_PRIVATE_VALUE"}},
            schema_id="synthetic_v1",
            access_scope="team-a",
            context=context,
        )
        == older
    )
    denied = ExecutionContext.create("unauthorized", "test")
    with pytest.raises(AccessDenied):
        store.observation(older, "record", denied)
    with pytest.raises(AccessDenied):
        store.observation(replace(older, access_scope="team-b"), "record", context)


def test_authorization_before_io_and_path_tamper_detection(tmp_path):
    context = ExecutionContext.create("test", "test")
    key = AESGCM.generate_key(bit_length=256)
    store = ArtifactStore(tmp_path, key, lambda *args: True)
    ref = store.put(
        {"a": {"S1": 1}}, schema_id="synthetic_v1", access_scope="test", context=context
    )
    with pytest.raises(ValueError):
        store.observation(replace(ref, digest="../escape"), "a", context)
    with pytest.raises(ValueError):
        store.observation(replace(ref, row_count=7), "a", context)
    denied = ArtifactStore(tmp_path, key, lambda *args: False)
    with pytest.raises(AccessDenied):
        denied.observation(replace(ref, digest="invalid"), "a", context)
    file = next(tmp_path.rglob("*.enc"))
    file.write_bytes(file.read_bytes()[:-1] + b"x")
    with pytest.raises(InvalidTag):
        store.observation(ref, "a", context)


def test_artifact_limits_and_no_nan(tmp_path):
    context = ExecutionContext.create("test", "test")
    store = ArtifactStore(
        tmp_path, AESGCM.generate_key(bit_length=256), lambda *args: True, max_bytes=10
    )
    with pytest.raises(ValueError):
        store.put({"a": {"S1": 1}}, schema_id="test", access_scope="test", context=context)
    with pytest.raises(ValueError):
        store.put(
            {"a": {"S1": float("nan")}}, schema_id="test", access_scope="test", context=context
        )
    assert not list(Path(tmp_path).rglob("*.enc"))
