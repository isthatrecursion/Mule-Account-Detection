from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from sklearn.base import clone
from sklearn.exceptions import NotFittedError

from mule_detection.domain.contracts.common import parse_contract
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.domain.feature_policy import FeaturePolicy
from mule_detection.domain.validation_policy import IntakeRejected
from mule_detection.features.artifacts import digest, load_pipeline, save_pipeline
from mule_detection.features.inputs import research_frame
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.features.preprocessor import FoldSafePreprocessor
from mule_detection.features.semantic_cleanup import SemanticCleaner, SemanticRules
from mule_detection.features.transformers import PolicyExclusion, StructuralPruner
from mule_detection.ingestion.partition_guard import PartitionGuard
from mule_detection.settings import read_yaml
from tests.contracts.helpers import synthetic_research

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def policy():
    return parse_contract(FeaturePolicy, read_yaml(ROOT / "config/feature_policy.yaml"))


@pytest.fixture
def frame():
    n = 20
    numeric = np.arange(n, dtype=float)
    numeric[2] = np.nan
    return pd.DataFrame(
        {
            "amount_under_score": numeric,
            "duplicate": numeric.copy(),
            "all_null": np.full(n, np.nan),
            "constant": np.ones(n),
            "ninety_percent": [1.0, 2.0] + [np.nan] * 18,
            "category_under_score": ["a_b", "c_d", np.nan, "c_d"] * 5,
            "F3888": ["1900-01-01", "2020-01-01", "2021-01-01", "bad"] * 5,
            "F3893": ["RETAIL", "BUSINESS"] * 10,
            "F3894": [12.0, 120.0, 18.0, 100.0, 101.0] * 4,
        }
    )


def dense(value):
    return value.toarray() if hasattr(value, "toarray") else value


def original():
    spec = importlib.util.spec_from_file_location(
        "legacy_reference", ROOT / "scripts/pre_architecture_verification.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FoldSafePreprocessor


def test_reference_parity_and_threshold(policy, frame):
    reference = original()().fit(frame)
    extracted = FoldSafePreprocessor().fit(frame)
    pipeline = FeaturePipeline(policy).fit(frame)
    assert pipeline.keep_columns_ == extracted.keep_columns_ == reference.keep_columns_
    assert pipeline.dropped_ == reference.dropped_
    assert pipeline.dropped_["high_missingness"] == ["ninety_percent"]
    assert pipeline.dropped_["zero_variance"] == ["all_null", "constant"]
    assert pipeline.dropped_["exact_duplicate"] == ["duplicate"]
    np.testing.assert_array_equal(
        dense(pipeline.transform(frame)), dense(reference.transform(frame))
    )
    np.testing.assert_array_equal(
        dense(extracted.transform(frame)), dense(reference.transform(frame))
    )
    assert pipeline.exclusion_report_["historical_registered_candidate_count"] == 2521
    assert len(pipeline.keep_columns_) != 2521


def test_validation_never_changes_fitted_state(policy, frame):
    pipeline = FeaturePipeline(policy).fit(frame)
    before = json.dumps(
        {
            "stats": pipeline.reference_statistics_,
            "drops": pipeline.dropped_,
            "map": pipeline.transformed_features_,
        },
        sort_keys=True,
    )
    medians = pipeline.transformer_.named_transformers_["numeric"].statistics_.copy()
    validation = frame.copy()
    validation["amount_under_score"] = 1e12
    validation["category_under_score"] = "never_seen"
    validation["all_null"] = np.arange(len(validation), dtype=float)
    pipeline.transform(validation)
    assert (
        json.dumps(
            {
                "stats": pipeline.reference_statistics_,
                "drops": pipeline.dropped_,
                "map": pipeline.transformed_features_,
            },
            sort_keys=True,
        )
        == before
    )
    np.testing.assert_array_equal(
        pipeline.transformer_.named_transformers_["numeric"].statistics_, medians
    )
    # This assertion detects accidental fitting on train + validation.
    combined = FeaturePipeline(policy).fit(pd.concat([frame, validation]))
    assert "all_null" not in combined.dropped_["zero_variance"]
    assert combined.reference_statistics_ != pipeline.reference_statistics_


def test_cloning_independent_fit(policy, frame):
    pipeline = FeaturePipeline(policy).fit(frame)
    other = clone(pipeline)
    assert not hasattr(other, "transformer_")
    changed = frame.copy()
    changed["amount_under_score"] = 2.0
    other.fit(changed)
    assert other.dropped_ != pipeline.dropped_
    for component in (
        PolicyExclusion(policy),
        SemanticCleaner(),
        StructuralPruner(),
        FoldSafePreprocessor(),
    ):
        assert clone(component).get_params() == component.get_params()


def test_signature_mapping_unknown_categories_and_empty(policy, frame):
    pipeline = FeaturePipeline(policy).fit(frame)
    normal = dense(pipeline.transform(frame))
    np.testing.assert_array_equal(normal, dense(pipeline.transform(frame[frame.columns[::-1]])))
    assert pipeline.transform(frame.iloc[:0]).shape == (0, normal.shape[1])
    mapping = pipeline.transformed_features_
    names = pipeline.get_feature_names_out()
    assert len(mapping) == normal.shape[1] == len(names)
    assert [m["index"] for m in mapping] == list(range(normal.shape[1]))
    category_positions = [m["index"] for m in mapping if m["raw_feature"] == "category_under_score"]
    assert len(category_positions) == 2
    validation = frame.copy()
    validation["category_under_score"] = "unknown_with_underscores"
    assert not dense(pipeline.transform(validation))[:, category_positions].any()
    for bad in (
        frame.drop(columns="duplicate"),
        frame.assign(unexpected=0),
        frame.assign(amount_under_score="bad"),
        pd.concat([frame, frame[["constant"]]], axis=1),
    ):
        with pytest.raises(DomainError):
            pipeline.transform(bad)


def test_forbidden_and_unfitted_and_no_features(policy, frame):
    with pytest.raises(NotFittedError):
        FeaturePipeline(policy).transform(frame)
    for forbidden in ("F3924", "F2230", "account_id", "record_key", "F3912"):
        with pytest.raises(DomainError) as caught:
            FeaturePipeline(policy).fit(frame.assign(**{forbidden: 1}))
        assert caught.value.code == ErrorCode.FEATURE_FORBIDDEN
    for invalid in (pd.DataFrame({"constant": [1, 1]}), frame.iloc[:0]):
        with pytest.raises(DomainError):
            FeaturePipeline(policy).fit(invalid)
    with pytest.raises(DomainError):
        FeaturePipeline(policy, data_tier="qualified").fit(frame)
    with pytest.raises(DomainError):
        FeaturePipeline(policy, semantic_version="made_up").fit(frame)


def test_cleanup_preserves_raw_observation_and_masks(policy, frame):
    raw = frame.copy(deep=True)
    pipeline = FeaturePipeline(policy).fit(frame)
    mask = pipeline.missing_mask(frame)
    assert mask.loc[0, "F3888"] and mask.loc[3, "F3888"]
    assert mask.loc[0, "F3894"]  # Retail age 12
    assert not mask.loc[1, "F3894"]  # Business legacy value preserved
    assert not mask.loc[2, "F3894"] and not mask.loc[3, "F3894"]
    pd.testing.assert_frame_equal(raw, frame)
    assert pipeline.reference_statistics_["amount_under_score"]["missing_count"] == 1


def test_folds_choose_their_own_columns(policy, frame):
    other = frame.copy()
    other["amount_under_score"] = 1.0
    a = FeaturePipeline(policy).fit(frame)
    b = FeaturePipeline(policy).fit(other)
    assert "amount_under_score" in a.keep_columns_
    assert "amount_under_score" not in b.keep_columns_
    assert a.training_fingerprint_ != b.training_fingerprint_


def test_sparse_and_numeric_only_mapping(policy):
    for frame in (
        pd.DataFrame(
            {"number": np.arange(50.0), "cat_under_score": [f"value_{i}" for i in range(50)]}
        ),
        pd.DataFrame({"number": [1.0, 2.0, np.nan, 5.0]}),
        pd.DataFrame({"cat": ["a", "b", "a", "b"]}),
    ):
        pipeline = FeaturePipeline(policy).fit(frame)
        assert pipeline.transform(frame).shape[1] == len(pipeline.transformed_features_)
        assert len(pipeline.get_feature_names_out()) == pipeline.n_features_out_


def test_trusted_roundtrip_immutable_and_tamper_rejection(policy, frame, tmp_path):
    pipeline = FeaturePipeline(policy).fit(frame)
    directory, expected = save_pipeline(
        pipeline, tmp_path, split_fingerprint="a" * 64, code_identity="synthetic-test"
    )
    before = {p.name: digest(p) for p in directory.iterdir()}
    loaded = load_pipeline(directory, allowed_root=tmp_path, expected_digest=expected)
    for _ in range(3):
        np.testing.assert_array_equal(
            dense(pipeline.transform(frame)), dense(loaded.transform(frame))
        )
    assert before == {p.name: digest(p) for p in directory.iterdir()}
    with pytest.raises(DomainError):
        load_pipeline(directory, allowed_root=tmp_path / "another-root", expected_digest=expected)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    (directory / "pipeline.joblib").write_bytes(b"replaced")
    with pytest.raises(DomainError):
        load_pipeline(directory, allowed_root=tmp_path, expected_digest=expected)
    # Even a replacement manifest cannot alter the independently pinned identity.
    manifest["files"]["pipeline.joblib"] = {
        "bytes": 8,
        "sha256": digest(directory / "pipeline.joblib"),
    }
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(DomainError):
        load_pipeline(directory, allowed_root=tmp_path, expected_digest=expected)


def test_qualified_incomplete_source_is_not_numerically_certified(policy, frame):
    # This feature implementation intentionally supports research only. A source
    # gap cannot be made qualified/complete by filling its cells with zero.
    with pytest.raises(DomainError):
        FeaturePipeline(policy, data_tier="qualified").fit(frame.fillna(0))


def test_semantic_configuration_is_version_bound(frame):
    pipeline = FeaturePipeline.from_repository(ROOT).fit(frame)
    assert pipeline.semantic_rules_ == SemanticRules.from_file(ROOT / "config/semantic_rules.yaml")
    with pytest.raises(ValidationError):
        SemanticRules(date_legacy_max_year=1960)
    with pytest.raises(ValidationError):
        SemanticRules(qualified_use_allowed=True)
    with pytest.raises(DomainError):
        pipeline.fit(frame.assign(F3888_IS_LEGACY=0))


def test_research_intake_conversion_preserves_missingness_and_membership(tmp_path):
    adapter, dataset, split = synthetic_research(tmp_path)
    batch = adapter.adapt(dataset, split)
    guard = PartitionGuard.from_verified(batch)
    predictors = research_frame(batch, guard)
    assert list(predictors) == ["F1", "F2", "F3886"]
    assert predictors.shape[0] == 3 and pd.isna(predictors.loc[2, "F1"])
    assert predictors["F2"].dtype == np.dtype("int64")
    FeaturePipeline(adapter.feature_policy).fit_transform(predictors)
    with pytest.raises(IntakeRejected, match="RESEARCH_PARTITION_FORBIDDEN"):
        research_frame(replace(batch, record_keys=(*batch.record_keys[:-1], "holdout-key")), guard)
    nullable = dict(batch.predictors)
    nullable["F3886"] = np.asarray(["a", None, "b"], dtype=object)
    normalized = research_frame(replace(batch, predictors=nullable), guard)
    assert pd.isna(normalized.loc[1, "F3886"])
    nullable["F2"] = np.asarray([2**60 + 1, None, 2], dtype=object)
    with pytest.raises(DomainError):
        research_frame(replace(batch, predictors=nullable), guard)


def test_runtime_mismatch_blocks_deserialization(policy, frame, tmp_path, monkeypatch):
    import mule_detection.features.artifacts as artifacts

    directory, expected = save_pipeline(
        FeaturePipeline(policy).fit(frame),
        tmp_path,
        split_fingerprint="a" * 64,
        code_identity="synthetic-test",
    )
    monkeypatch.setattr(artifacts, "runtime_identity", lambda: {"python": "incompatible"})

    def forbidden_load(*args, **kwargs):
        pytest.fail("Deserialization ran before runtime validation")

    monkeypatch.setattr(artifacts.joblib, "load", forbidden_load)
    with pytest.raises(DomainError) as caught:
        load_pipeline(directory, allowed_root=tmp_path, expected_digest=expected)
    assert caught.value.code == ErrorCode.LINEAGE_INVALID
