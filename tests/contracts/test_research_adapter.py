from dataclasses import FrozenInstanceError, replace

import numpy as np
import pytest

from mule_detection.domain.contracts.common import parse_contract
from mule_detection.domain.contracts.models import ModelBundle
from mule_detection.domain.contracts.tabular import TabularSchema
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.domain.feature_policy import (
    FeaturePolicy,
    derive_structural_exclusions,
    validate_bundle_policy,
)
from mule_detection.domain.identity import research_record_key
from tests.contracts.helpers import payload, synthetic_research


def test_only_development_rows_and_predictors_are_emitted(tmp_path):
    adapter, dataset, split = synthetic_research(tmp_path)
    batch = adapter.adapt(dataset, split)
    assert list(batch.predictors) == ["F1", "F2", "F3886"]
    assert batch.predictors["F2"].dtype == np.dtype("int64")
    assert batch.logical_types["F2"] == "integer"
    assert batch.labels.tolist() == [0, 1, 0]
    assert batch.excluded_holdout_count == 1
    assert batch.record_keys == tuple(
        research_record_key(batch.dataset_sha256, row) for row in [1, 2, 4]
    )
    assert research_record_key(batch.dataset_sha256, 3) not in batch.record_keys
    assert list(batch.predictors["F3886"]) == ["NA", "Savings", "UNKNOWN"]
    assert np.isnan(batch.predictors["F1"][-1])  # Only explicitly imputable blank cells become NaN.
    assert [row.original_reference for row in batch.restricted_lineage] == [1, 2, 4]
    assert (
        batch.account_id is None
        and batch.observation_cutoff is None
        and batch.data_tier == "research"
    )
    assert "SYN_A" not in repr(batch)
    with pytest.raises(FrozenInstanceError):
        batch.data_tier = "qualified"
    with pytest.raises(ValueError):
        batch.labels[0] = 1
    with pytest.raises(TypeError):
        batch.predictors["F3924"] = batch.labels


def test_reordering_normalizes_to_server_schema_order(tmp_path):
    adapter, dataset, split = synthetic_research(tmp_path, reorder=True)
    batch = adapter.adapt(dataset, split)
    assert list(batch.predictors) == ["F1", "F2", "F3886"]
    assert batch.labels.tolist() == [0, 1, 0]


def test_large_integer_predictors_are_not_rounded_to_float(tmp_path):
    exact = 2**60 + 1

    def change(header, rows, splits):
        rows[0][2] = str(exact)

    adapter, dataset, split = synthetic_research(tmp_path, change=change)
    batch = adapter.adapt(dataset, split)
    assert int(batch.predictors["F2"][0]) == exact


def test_physical_blank_index_header_and_declared_na_marker_are_explicit(tmp_path):
    def change(header, rows, splits):
        header[0] = ""
        rows[0][1] = "NA"

    adapter, dataset, split = synthetic_research(tmp_path, change=change)
    schema = adapter.schema.model_dump()
    schema["missing_tokens"] = ["", "NA", "nan", "NaN"]
    adapter = replace(adapter, schema=parse_contract(TabularSchema, schema))
    batch = adapter.adapt(dataset, split)
    assert np.isnan(batch.predictors["F1"][0])
    assert batch.predictors["F3886"][0] is None
    assert batch.restricted_lineage[0].original_reference == 1


def test_blank_alias_cannot_hide_duplicate_row_reference_header(tmp_path):
    def change(header, rows, splits):
        header[1] = ""

    adapter, dataset, split = synthetic_research(tmp_path, change=change)
    with pytest.raises(DomainError) as result:
        adapter.adapt(dataset, split)
    assert result.value.code == ErrorCode.SCHEMA_MISMATCH


def test_bundle_policy_is_bound_to_canonical_content_and_version():
    policy = parse_contract(FeaturePolicy, payload("feature_policy_v1"))
    data = payload("model_bundle_v1")
    data["feature_policy_hash"] = policy.fingerprint
    validate_bundle_policy(parse_contract(ModelBundle, data), policy)
    with pytest.raises(DomainError) as result:
        validate_bundle_policy(
            parse_contract(ModelBundle, dict(data, feature_policy_hash="b" * 64)), policy
        )
    assert result.value.code == ErrorCode.LINEAGE_INVALID


@pytest.mark.parametrize(
    "case,expected",
    [
        ("extra", ErrorCode.SCHEMA_MISMATCH),
        ("duplicate", ErrorCode.SCHEMA_MISMATCH),
        ("missing", ErrorCode.SCHEMA_MISMATCH),
        ("numeric", ErrorCode.VALUE_INVALID),
        ("split_target", ErrorCode.SPLIT_MISMATCH),
        ("split_partition", ErrorCode.SPLIT_MISMATCH),
        ("missing_row", ErrorCode.SPLIT_MISMATCH),
    ],
)
def test_bad_inputs_are_findings_not_silent_coercion(tmp_path, case, expected):
    def change(header, rows, splits):
        if case == "extra":
            header.append("SYNTHETIC_EXTRA")
            for row in rows:
                row.append("secret")
        elif case == "duplicate":
            header[1] = header[2]
        elif case == "missing":
            header.pop(1)
            for row in rows:
                row.pop(1)
        elif case == "numeric":
            rows[0][1] = "SYNTHETIC_SECRET"
        elif case == "split_target":
            splits[0][2] = "1"
        elif case == "split_partition":
            splits[0][1] = "acceptance"
        else:
            splits.pop()

    adapter, dataset, split = synthetic_research(tmp_path, change=change)
    with pytest.raises(DomainError) as result:
        adapter.adapt(dataset, split)
    assert result.value.code == expected
    assert "SYNTHETIC_SECRET" not in str(result.value)


def test_input_fingerprint_is_checked_before_emission(tmp_path):
    adapter, dataset, split = synthetic_research(tmp_path)
    with dataset.open("a") as stream:
        stream.write("corruption")
    with pytest.raises(DomainError) as result:
        adapter.adapt(dataset, split)
    assert result.value.code == ErrorCode.HASH_MISMATCH


def test_research_identity_is_namespaced_and_canonical():
    assert research_record_key("a" * 64, 42) == research_record_key("A" * 64, "00042")
    assert research_record_key("a" * 64, 42) != research_record_key("b" * 64, 42)
    for invalid in (True, -1, "4.2", "", " 42"):
        with pytest.raises(DomainError):
            research_record_key("a" * 64, invalid)


def test_permanent_policy_is_separate_from_fold_fitted_selection():
    policy = parse_contract(FeaturePolicy, payload("feature_policy_v1"))
    training = {"S1": [1.0, 2.0, 3.0], "S2": [1.0, 2.0, 3.0], "S3": [None, None, 5.0]}
    validation = {"S1": [None, None, None]}
    learned = derive_structural_exclusions(training, policy)
    validation["S1"] = [99.0, 1.0, None]
    assert derive_structural_exclusions(training, policy) == learned
    assert {item.feature_id for item in learned.exclusions} == {"S2", "S3"}
    assert learned.fit_partition == "train"
    modified = payload("feature_policy_v1")
    modified["policy_version"] = "research_features_v2"
    assert parse_contract(FeaturePolicy, modified).fingerprint != policy.fingerprint
    for column in ("F3924", "Unnamed: 0", "F2230", "account_id"):
        with pytest.raises(DomainError) as result:
            policy.assert_predictors([column])
        assert result.value.code == ErrorCode.FEATURE_FORBIDDEN
