import json
import shutil
from dataclasses import replace
from unittest.mock import Mock

import pytest

from mule_detection.domain.contracts.common import parse_contract
from mule_detection.domain.contracts.events import TransactionEvent, validate_event_progress
from mule_detection.domain.contracts.jobs import validate_job_transition
from mule_detection.domain.contracts.registry import CONTRACTS, resolve_contract
from mule_detection.domain.contracts.tabular import ColumnRule
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.domain.feature_policy import FeaturePolicy
from mule_detection.ingestion.research_adapter import parse_cell
from tests.contracts.helpers import FIXTURES, ROOT, payload, synthetic_research

FAILURES = json.loads((ROOT / "tests/fixtures/contracts/failure_cases.json").read_text())
INVALID_ENUMS = json.loads((ROOT / "tests/fixtures/contracts/invalid_enums.json").read_text())


@pytest.mark.parametrize("case", INVALID_ENUMS, ids=lambda case: case["version"])
def test_independent_status_enums_cannot_be_interchanged(case):
    data = payload(case["version"])
    target = data
    for step in case["path"][:-1]:
        target = target[step]
    target[case["path"][-1]] = case["value"]
    with pytest.raises(DomainError) as result:
        resolve_contract(case["version"], data)
    assert result.value.code == ErrorCode.CONTRACT_INVALID


def test_schema_directory_contains_exactly_the_registered_versions():
    assert {p.name for p in (ROOT / "contracts").glob("*.schema.json")} == {
        f"{version}.schema.json" for version in CONTRACTS
    }


def test_regeneration_cannot_silently_rewrite_a_frozen_schema(tmp_path, monkeypatch):
    from scripts import generate_contract_schemas as generator

    shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    files = generator.generated_schemas()
    name = "batch_manifest_v1.schema.json"
    before = (tmp_path / "contracts" / name).read_text()
    files[name] = before.replace('"BatchManifest"', '"ChangedContract"')
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    monkeypatch.setattr(generator, "generated_schemas", lambda: files)
    monkeypatch.setattr("sys.argv", ["generate_contract_schemas.py"])
    assert generator.main() == 1
    assert (tmp_path / "contracts" / name).read_text() == before


@pytest.mark.parametrize("version", CONTRACTS)
def test_minimal_fixture_roundtrips_and_schema_is_frozen(version):
    model = resolve_contract(version, payload(version))
    assert resolve_contract(version, model.model_dump_json()) == model
    expected = json.dumps(CONTRACTS[version].model_json_schema(), sort_keys=True, indent=2) + "\n"
    assert (ROOT / "contracts" / f"{version}.schema.json").read_text() == expected


@pytest.mark.parametrize("version", CONTRACTS)
@pytest.mark.parametrize("mutation", ["missing", "wrong_type", "extra", "unknown_version"])
def test_every_contract_rejects_mutated_boundary_without_publication(version, mutation):
    data = payload(version)
    field = next(key for key in data if key != "contract_version")
    expected = ErrorCode.CONTRACT_INVALID
    if mutation == "missing":
        del data[field]
    elif mutation == "wrong_type":
        data[field] = 123
    elif mutation == "extra":
        data["request_controlled_approval_actor"] = "SYNTHETIC_SECRET"
    else:
        data["contract_version"] = "https://untrusted.invalid/code.py"
        expected = ErrorCode.CONTRACT_VERSION
    publisher = Mock()
    with pytest.raises(DomainError) as result:
        accepted = resolve_contract(version, data)
        publisher(accepted)
    assert result.value.code == expected
    assert "SYNTHETIC_SECRET" not in json.dumps(result.value.public())
    publisher.assert_not_called()


def exercise_failure(scenario, tmp_path):
    data = payload("batch_manifest_v1")
    version = "batch_manifest_v1"
    if scenario == "missing_id":
        del data["batch_id"]
    elif scenario == "unknown_version":
        data["contract_version"] = "batch_manifest_v999"
    elif scenario == "naive_timestamp":
        data["created_at"] = "2026-01-02T00:00:00"
    elif scenario == "malformed_timestamp":
        data["created_at"] = "SYNTHETIC_SECRET"
    elif scenario == "negative_count":
        data["expected_row_count"] = -1
    elif scenario == "duplicate_json_key":
        return resolve_contract(version, '{"batch_id":"a","batch_id":"b"}')
    elif scenario == "target_predictor":
        return parse_contract(FeaturePolicy, payload("feature_policy_v1")).assert_predictors(
            ["F3924"]
        )
    elif scenario == "numeric_coercion":
        rule = ColumnRule(
            name="S1", logical_type="number", role="predictor", required=True, missing="imputable"
        )
        return parse_cell("SYNTHETIC_SECRET", rule, ("",))
    elif scenario.startswith("research_"):

        def change(header, rows, splits):
            if scenario == "research_split":
                splits[0][2] = "1"
            elif scenario == "research_duplicate":
                rows[1][0] = splits[1][0] = "1"

        adapter, dataset, split = synthetic_research(tmp_path, change=change)
        if scenario == "research_hash":
            adapter = replace(adapter, trusted_dataset_sha256="f" * 64)
        return adapter.adapt(dataset, split)
    elif scenario == "source_conflict":
        version = "source_registry_v1"
        data = payload(version)
        other = dict(data["sources"][0], source_id="synthetic-other")
        data["sources"].append(other)
    elif scenario == "unknown_qualified_cutoff":
        data.update(
            schema_id="qualified_snapshot_v1", data_tier="qualified", observation_cutoff=None
        )
    elif scenario == "uncertified_prose":
        version = "evidence_v1"
        data = payload(version)
        data["observations"][0]["display_name"] = "Unsupported behavioral story"
    elif scenario == "label_correction_link":
        version = "label_v1"
        data = payload(version)
        data["version"] = 2
    elif scenario == "missing_bundle_artifact":
        version = "model_bundle_v1"
        data = payload(version)
        data["artifact_digests"].pop("pipeline")
    elif scenario == "unavailable_zero":
        version = "score_v1"
        data = payload(version)
        data.update(freshness="UNAVAILABLE", raw_score=0.0)
    elif scenario in ("epoch_reset", "future_event"):
        event = parse_contract(TransactionEvent, payload("event_v1"))
        data = payload("event_v1")
        if scenario == "future_event":
            data["event_time"] = "2026-01-01T00:10:00Z"
        return validate_event_progress(
            parse_contract(TransactionEvent, data),
            previous=event,
            approved_epoch="epoch-1",
            max_clock_skew_seconds=30,
        )
    elif scenario == "contradictory_count":
        version = "completeness_v1"
        data = payload(version)
        data["expected_count"] = 2
    elif scenario == "terminal_job":
        return validate_job_transition("SUCCEEDED", "RUNNING")
    else:
        raise AssertionError("Unknown fixture scenario")
    return resolve_contract(version, data)


@pytest.mark.parametrize("case", FAILURES, ids=lambda case: case["scenario"])
def test_error_catalog_is_exercised_with_specific_safe_codes(case, tmp_path):
    with pytest.raises(DomainError) as result:
        exercise_failure(case["scenario"], tmp_path)
    assert result.value.code.value == case["expected_code"]
    assert "SYNTHETIC_SECRET" not in json.dumps(result.value.public())
    assert result.value.__suppress_context__ or result.value.__cause__ is None


def test_catalog_covers_every_phase2_code_and_every_registered_model():
    foundation = {
        "INVALID_ARGUMENTS",
        "CONFIGURATION_INVALID",
        "UNSUPPORTED_OPERATION",
        "INTERNAL_ERROR",
    }
    assert {case["expected_code"] for case in FAILURES} == {
        code.value for code in ErrorCode
    } - foundation
    assert set(FIXTURES) == set(CONTRACTS)


def test_schema_resolution_does_not_load_paths_urls_or_unknown_versions():
    for version in ("../../local.py", "https://untrusted.invalid/schema", "unknown_v1"):
        with pytest.raises(DomainError) as result:
            resolve_contract(version, {})
        assert result.value.code == ErrorCode.CONTRACT_VERSION


def test_nonfinite_and_invalid_json_do_not_leak():
    for raw, expected in [("{", "CONTRACT_INVALID"), ('{"raw_score":NaN}', "VALUE_INVALID")]:
        with pytest.raises(DomainError) as result:
            resolve_contract("score_v1", raw)
        assert result.value.code.value == expected
