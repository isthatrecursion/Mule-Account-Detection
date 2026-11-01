import io
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mule_detection.domain.identity import research_record_key
from mule_detection.domain.validation_policy import IntakeRejected, assert_qualified_promotion
from mule_detection.ingestion.intake import SourceProfile
from mule_detection.ingestion.partition_guard import development_batch
from mule_detection.ingestion.quality_report import quality_report
from mule_detection.ingestion.validator import CheckedBatch
from mule_detection.persistence.raw_store import RawStore, StagedRaw
from tests.contracts.helpers import synthetic_research


def test_raw_store_hash_recheck_immutable_encryption_and_boundaries(tmp_path):
    store = RawStore(tmp_path / "root", b"x" * 32)
    staged = store.stage(io.BytesIO(b"synthetic-content"))
    store.staging_path(staged.stage_id).write_bytes(b"tampered-content!")
    with pytest.raises(IntakeRejected):
        store.finalize(staged)
    good = store.stage(io.BytesIO(b"synthetic-content"))
    store.finalize(good)
    first = store.object_path(good.digest).read_bytes()
    repeated = store.stage(io.BytesIO(b"synthetic-content"))
    store.finalize(repeated)
    assert store.object_path(good.digest).read_bytes() == first
    assert store.read(good.digest) == b"synthetic-content"
    with pytest.raises(IntakeRejected):
        store.object_path("../../escape")
    with pytest.raises(IntakeRejected):
        store.staging_path("../escape")
    with pytest.raises(IntakeRejected):
        store.finalize(StagedRaw(good.stage_id, good.digest, 100))


def test_fragmented_compressed_header_is_rejected(tmp_path):
    class OneByte(io.BytesIO):
        def read(self, n=-1):
            return super().read(1)

    with pytest.raises(IntakeRejected, match="COMPRESSED_INPUT"):
        RawStore(tmp_path, b"x" * 32).stage(OneByte(b"\x1f\x8bcompressed"))


def test_direct_worker_partition_guard_blocks_holdout_unknown_and_wrong_split(tmp_path):
    adapter, dataset, split = synthetic_research(tmp_path)
    batch, guard = development_batch(adapter, dataset, split)
    for keys, digest, split_hash in [
        ((research_record_key(batch.dataset_sha256, 3),), batch.dataset_sha256, batch.split_sha256),
        (("unknown",), batch.dataset_sha256, batch.split_sha256),
        (batch.record_keys, "0" * 64, batch.split_sha256),
        (batch.record_keys, batch.dataset_sha256, "0" * 64),
        ((batch.record_keys[0], batch.record_keys[0]), batch.dataset_sha256, batch.split_sha256),
    ]:
        with pytest.raises(IntakeRejected):
            guard.assert_development(keys, digest, split_hash)
    guard.assert_development(batch.record_keys, batch.dataset_sha256, batch.split_sha256)


def test_training_quality_is_authorized_subset_and_not_default(tmp_path):
    adapter, dataset, split = synthetic_research(tmp_path)
    batch, _ = development_batch(adapter, dataset, split)
    profile = SourceProfile(
        source_id="research",
        schema_id="research_v1",
        data_tier="research",
        policy_version=adapter.feature_policy.policy_version,
        access_scope="research",
        columns=adapter.schema.columns,
        identity_columns=("Unnamed: 0",),
    )
    checked = CheckedBatch(
        [],
        records=[
            {name: values[i] for name, values in batch.predictors.items()}
            for i in range(len(batch.record_keys))
        ],
        labels=batch.labels.tolist(),
        cohort=[str(r.extraction_month) for r in batch.restricted_lineage],
    )
    ordinary = quality_report(checked, profile)
    assert "restricted_training_diagnostics" not in ordinary
    training = quality_report(checked, profile, training_diagnostics=True)
    assert training["authorized_rows"] == 3
    assert (
        sum(
            sum(group["class_counts"].values())
            for group in training["restricted_training_diagnostics"].values()
        )
        == 3
    )
    assert "HOLDOUT_ONLY" not in json.dumps(training)
    with pytest.raises(IntakeRejected):
        assert_qualified_promotion({"qualified_promotion_allowed": False})


def test_shipped_profiles_use_registered_policy_and_private_split_location():
    from mule_detection.domain.contracts.common import parse_contract
    from mule_detection.domain.feature_policy import FeaturePolicy
    from mule_detection.settings import read_yaml

    root = Path(__file__).resolve().parents[2]
    config = read_yaml(root / "config/ingestion.yaml")
    policy = parse_contract(FeaturePolicy, read_yaml(root / "config/feature_policy.yaml"))
    for document in config["sources"]:
        profile = SourceProfile.model_validate(document)
        assert profile.policy_version == policy.policy_version
        assert profile.data_tier == "synthetic"
    assert (root / config["research_split_register"]).resolve().is_relative_to(root)


def test_uncertified_profile_cannot_enable_range_or_qualified_rules():
    with pytest.raises(ValidationError):
        SourceProfile(
            source_id="fake",
            schema_id="qualified_snapshot_v1",
            data_tier="qualified",
            policy_version="v1",
            access_scope="test",
            identity_columns=("record_key",),
            columns=(
                {
                    "name": "record_key",
                    "logical_type": "categorical",
                    "role": "lineage",
                    "required": True,
                    "missing": "forbidden",
                },
            ),
        )
