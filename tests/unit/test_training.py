from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from mule_detection.domain.contracts.labels import QualifiedLabel
from mule_detection.domain.errors import DomainError
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.ingestion.partition_guard import PartitionGuard
from mule_detection.training.calibration import fit_calibration
from mule_detection.training.evaluation_policy import (
    ModelSpec,
    QualificationEvidence,
    TrainingConfig,
    require_mode,
)
from mule_detection.training.label_selector import LabelSnapshot, select_training_labels
from mule_detection.training.metrics import bootstrap_intervals, ranking_metrics
from mule_detection.training.model_factory import fit_candidate
from mule_detection.training.report import RunStore
from mule_detection.training.runner import TrainingInput, evaluate_run, run_experiment
from mule_detection.training.search import (
    FrozenSelection,
    require_acceptance_release,
    select_configuration,
)
from mule_detection.training.splits import (
    TemporalRecord,
    Window,
    research_folds,
    temporal_partitions,
)
from mule_detection.training.subgroup_report import subgroup_report

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 20, tzinfo=UTC)


@pytest.fixture
def training_data():
    rng = np.random.default_rng(42)
    count = 80
    X = pd.DataFrame(
        {
            "amount": rng.normal(size=count),
            "optional": rng.normal(size=count),
            "category_under_score": ["a_b", "c_d"] * (count // 2),
            "proxy": rng.normal(size=count),
        }
    )
    X.loc[::4, "optional"] = np.nan
    y = (X["amount"].to_numpy() > 0).astype(int)
    keys = tuple(f"synthetic-key-{i:04d}" for i in range(count))
    guard = PartitionGuard("a" * 64, "b" * 64, frozenset(keys))
    return TrainingInput(
        X,
        y,
        keys,
        guard,
        "a" * 64,
        "b" * 64,
        "synthetic",
        tuple("source-a" if i % 2 else "source-b" for i in range(count)),
        "synthetic-accepted-validation",
        {},
    )


@pytest.fixture
def config():
    return TrainingConfig(
        outer_folds=2,
        inner_folds=2,
        bootstrap_repetitions=20,
        candidates=(
            ModelSpec(name="logistic", family="logistic"),
            ModelSpec(name="tree", family="lightgbm", n_estimators=5),
        ),
    )


def test_hand_calculated_metrics_ties_and_undefined():
    metric = ranking_metrics(["b", "a", "c"], [1, 0, 1], [0.8, 0.8, 0.1], (1, 2, 50))
    assert metric["average_precision"] == pytest.approx(7 / 12)
    assert metric["roc_auc"] == 0.25
    assert metric["top_k"][0]["precision"] == 0
    assert metric["top_k"][1]["precision"] == 0.5
    assert metric["top_k"][1]["recall"] == 0.5
    assert metric["top_k"][1]["lift"] == 0.75
    assert metric["top_k"][2]["k_effective"] == 3
    for keys, labels, scores in (([], [], []), (["a"], [0], [0.1]), (["a"], [1], [0.1])):
        result = ranking_metrics(keys, labels, scores, (1,))
        assert result["average_precision"] is None and result["roc_auc"] is None
    with pytest.raises(DomainError):
        ranking_metrics(["a"], [1], [np.nan], (1,))


def test_group_bootstrap_reports_invalid_resamples():
    result = bootstrap_intervals(
        ["a", "b", "c", "d"],
        [0, 0, 1, 1],
        [0.1, 0.2, 0.8, 0.9],
        ["negative", "negative", "positive", "positive"],
        repetitions=40,
        seed=42,
        ks=(2,),
    )
    interval = result["intervals"]["average_precision"]
    assert interval["valid_resamples"] + interval["invalid_resamples"] == 40
    assert interval["invalid_resamples"] > 0
    assert result["group_count"] == 2


def label(version=1, **changes):
    value = dict(
        contract_version="label_v1",
        label_id=uuid4(),
        record_key="r1",
        account_id="account1",
        value=1,
        label_source="adjudicator",
        event_at=NOW - timedelta(days=4),
        observed_at=NOW - timedelta(days=3),
        available_at=NOW - timedelta(days=3),
        mature_at=NOW - timedelta(days=2),
        status="ADJUDICATED",
        adjudication_reference="approved-outcome",
        negative_policy_reference=None,
        version=version,
        supersedes=None,
    )
    value.update(changes)
    return QualifiedLabel(**value)


def test_labels_are_selected_as_of_without_future_correction_leakage():
    first = label()
    future = label(
        2,
        value=0,
        observed_at=NOW + timedelta(days=1),
        available_at=NOW + timedelta(days=1),
        mature_at=NOW + timedelta(days=1),
        supersedes=first.label_id,
    )
    snapshot = LabelSnapshot("r1", "account1", NOW - timedelta(days=6), NOW - timedelta(days=5))
    selected, counts = select_training_labels((snapshot,), (first, future), NOW)
    assert selected["r1"].value == 1 and counts["corrected"] == 0
    selected, counts = select_training_labels((snapshot,), (first, future), NOW + timedelta(days=2))
    assert selected["r1"].value == 0 and counts["corrected"] == 1
    immature = label(
        2,
        supersedes=first.label_id,
        available_at=NOW,
        observed_at=NOW,
        mature_at=NOW + timedelta(days=2),
    )
    selected, counts = select_training_labels((snapshot,), (first, immature), NOW)
    assert selected == {} and counts["immature"] == 1
    selected, counts = select_training_labels(
        (replace(snapshot, snapshot_at=NOW, available_at=NOW),), (first,), NOW
    )
    assert selected == {} and counts["feature_after_outcome"] == 1


def temporal_fixture():
    windows = tuple(
        Window(
            name,
            NOW + timedelta(days=i * 10),
            NOW + timedelta(days=i * 10 + 3),
            NOW + timedelta(days=i * 10 + 7),
        )
        for i, name in enumerate(("train", "tuning", "calibration", "final_acceptance"))
    )
    records = tuple(
        TemporalRecord(
            f"{w.name}-{j}",
            f"account-{i}-{j}",
            frozenset({f"group-{i}-{j}"}),
            w.start + timedelta(days=1),
            j % 2,
            w.end,
            w.end,
        )
        for i, w in enumerate(windows)
        for j in range(4)
    )
    return windows, records


def test_temporal_splits_purge_connected_groups_and_maturity():
    windows, records = temporal_fixture()
    result = temporal_partitions(
        records, windows, feature_lookback=timedelta(days=2), outcome_window=timedelta(days=1)
    )
    assert all(row["rows"] == 4 for row in result["counts"].values())
    changed = list(records)
    changed[0] = replace(changed[0], entity_groups=frozenset({"linked"}))
    changed[4] = replace(changed[4], entity_groups=frozenset({"linked"}))
    result = temporal_partitions(
        tuple(changed),
        windows,
        feature_lookback=timedelta(days=2),
        outcome_window=timedelta(days=1),
    )
    assert result["exclusion_reasons"]["train-0"] == "CROSS_PARTITION_CONNECTED_ENTITY"
    assert result["exclusion_reasons"]["tuning-0"] == "CROSS_PARTITION_CONNECTED_ENTITY"
    with pytest.raises(DomainError):
        temporal_partitions(
            records,
            (windows[0], replace(windows[1], start=windows[0].end), *windows[2:]),
            feature_lookback=timedelta(days=2),
            outcome_window=timedelta(days=1),
        )
    with pytest.raises(DomainError):
        temporal_partitions(
            tuple(replace(r, label_mature_at=NOW + timedelta(days=100)) for r in records),
            windows,
            feature_lookback=timedelta(0),
            outcome_window=timedelta(0),
        )


def test_research_split_membership_and_holdout_rejection(training_data):
    data = training_data
    folds = research_folds(data.keys, data.target, 5, 42)
    assert sorted(key for fold in folds for key in fold.validation_keys) == sorted(data.keys)
    assert all(not set(fold.train_keys) & set(fold.validation_keys) for fold in folds)
    with pytest.raises(DomainError):
        research_folds(data.keys, np.zeros(len(data.keys)), 5, 42)
    with pytest.raises(Exception, match="RESEARCH_PARTITION_FORBIDDEN"):
        data.guard.assert_development(("held-out-key",), data.dataset_hash, data.split_hash)


def test_numeric_scaling_and_candidate_rows_match(training_data):
    data = training_data
    prototype = FeaturePipeline.from_repository(ROOT)
    fitted = fit_candidate(
        prototype,
        ModelSpec(name="logistic", family="logistic"),
        data.X,
        data.target,
        seed=42,
        threads=1,
    )
    base = fitted.features.transform(data.X)
    matrix = fitted.matrix(data.X)
    np.testing.assert_array_equal(base[:, fitted.numeric_stop :], matrix[:, fitted.numeric_stop :])
    before = fitted.scaler.scale_.copy()
    validation = data.X.copy()
    validation["amount"] = 1e12
    fitted.predict_score(validation)
    np.testing.assert_array_equal(before, fitted.scaler.scale_)
    assert not hasattr(prototype, "transformer_")


def test_sparse_numeric_scaling_does_not_densify(training_data):
    from scipy import sparse

    data = training_data
    frame = data.X.copy()
    frame["category_under_score"] = [f"unique_category_{i}" for i in range(len(frame))]
    fitted = fit_candidate(
        FeaturePipeline.from_repository(ROOT),
        ModelSpec(name="sparse_logistic", family="logistic"),
        frame,
        data.target,
        seed=42,
        threads=1,
    )
    matrix = fitted.matrix(frame)
    assert sparse.issparse(matrix)
    unscaled = fitted.features.transform(frame)
    np.testing.assert_array_equal(
        unscaled[:, fitted.numeric_stop :].toarray(), matrix[:, fitted.numeric_stop :].toarray()
    )
    assert np.isfinite(fitted.predict_score(frame)).all()


def test_unconverged_fit_cannot_publish_success(training_data, config, tmp_path):
    broken = config.model_copy(
        update={"candidates": (ModelSpec(name="unfinished", family="logistic", max_iter=1),)}
    )
    store, run_id = RunStore(tmp_path, b"x" * 32), uuid4()
    with pytest.raises(DomainError):
        run_experiment(
            training_data,
            FeaturePipeline.from_repository(ROOT),
            broken,
            store,
            run_id,
            actor_id="engineer",
            environment={},
        )
    assert store.state(run_id)["status"] == "FAILED"


def test_inner_search_never_receives_outer_validation(training_data):
    data = training_data
    train = data.X.iloc[:60]
    keys = data.keys[:60]
    specs = (
        ModelSpec(name="logistic_a", family="logistic", C=0.1),
        ModelSpec(name="logistic_b", family="logistic", C=1),
    )
    selected, report = select_configuration(
        train,
        data.target[:60],
        keys,
        FeaturePipeline.from_repository(ROOT),
        specs,
        folds=2,
        seed=42,
        threads=1,
    )
    assert selected in specs and len(report["trials"]) == 2
    assert all(
        set(f["train_keys"]) | set(f["validation_keys"]) == set(keys)
        for f in report["inner_splits"]
    )


def test_end_to_end_encrypted_candidates_replay_and_evaluation(training_data, config, tmp_path):
    store = RunStore(tmp_path, b"x" * 32)
    run_id = uuid4()
    prototype = FeaturePipeline.from_repository(ROOT)
    result = run_experiment(
        training_data,
        prototype,
        config,
        store,
        run_id,
        actor_id="engineer",
        environment={"test": True},
    )
    assert result["status"] == "SUCCEEDED" and not result["qualified_promotion_allowed"]
    assert set(result["metrics"]) == {"lightgbm", "logistic"}
    manifest = store.manifest(run_id)
    splits = store.json(run_id, "splits.json", manifest)
    expected = {key for fold in splits for key in fold["validation_keys"]}
    for name in result["metrics"]:
        rows = store.json(run_id, name + "_oof.json", manifest)
        assert {row["record_key"] for row in rows} == expected
    assert all(b"synthetic-key" not in p.read_bytes() for p in (tmp_path / str(run_id)).iterdir())
    assert (
        run_experiment(
            training_data,
            prototype,
            config,
            store,
            run_id,
            actor_id="engineer",
            environment={"test": True},
        )
        == result
    )
    with pytest.raises(DomainError):
        run_experiment(
            training_data,
            prototype,
            config.model_copy(update={"seed": 43}),
            store,
            run_id,
            actor_id="engineer",
            environment={"test": True},
        )
    with pytest.raises(DomainError):
        evaluate_run(store, run_id, actor_id="other")
    state_path = store.path(run_id, "state.json")
    original_state = state_path.read_bytes()
    changed_state = json.loads(original_state)
    changed_state["request_hash"] = "f" * 64
    state_path.write_text(json.dumps(changed_state))
    with pytest.raises(DomainError):
        evaluate_run(store, run_id, actor_id="engineer")
    state_path.write_bytes(original_state)
    path = store.path(run_id, "logistic_oof.json.enc")
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(DomainError):
        evaluate_run(store, run_id, actor_id="engineer")


def test_failure_remains_failed_with_partial_fold_evidence(training_data, config, tmp_path):
    store, run_id = RunStore(tmp_path, b"x" * 32), uuid4()

    def fail():
        raise RuntimeError("Synthetic publication failure")

    with pytest.raises(RuntimeError):
        run_experiment(
            training_data,
            FeaturePipeline.from_repository(ROOT),
            config,
            store,
            run_id,
            actor_id="engineer",
            environment={},
            before_finalize=fail,
        )
    assert store.state(run_id)["status"] == "FAILED"
    assert store.path(run_id, "logistic_fold_1.json.enc").exists()
    with pytest.raises(DomainError):
        evaluate_run(store, run_id, actor_id="engineer")


def test_ablation_and_small_subgroup_are_not_fairness_certification(
    training_data, config, tmp_path
):
    data = replace(
        training_data,
        approved_subgroups={
            key: "small" if i < 4 else "large" for i, key in enumerate(training_data.keys)
        },
    )
    config = config.model_copy(
        update={
            "candidates": (config.candidates[0],),
            "ablation_features": ("proxy",),
            "ablation_approval_reference": "synthetic-policy",
            "subgroup_approval_reference": "synthetic-group-definition",
        }
    )
    store, run_id = RunStore(tmp_path, b"x" * 32), uuid4()
    result = run_experiment(
        data,
        FeaturePipeline.from_repository(ROOT),
        config,
        store,
        run_id,
        actor_id="engineer",
        environment={},
    )
    assert set(result["metrics"]) == {"logistic", "logistic_ablated"}
    report = store.json(run_id, "report.json", store.manifest(run_id))
    subgroups = report["candidates"]["logistic"]["subgroups"]
    assert subgroups["fairness_certified"] is False
    assert next(s for s in subgroups["slices"] if s["group"] == "small")["metrics"] is None
    assert (
        subgroup_report(
            [],
            [],
            [],
            {},
            approval_reference=None,
            minimum_rows=5,
            minimum_positives=2,
            k=5,
            seed=42,
            research=True,
        )["status"]
        == "BLOCKED"
    )


def test_qualified_mode_and_acceptance_guards(config):
    with pytest.raises(DomainError):
        require_mode("qualified_temporal", "research", QualificationEvidence())
    with pytest.raises(DomainError):
        require_mode("qualified_temporal", "qualified", QualificationEvidence())
    args = dict(
        release_hash="b" * 64,
        expected_config_hash="a" * 64,
        expected_policy_hash="c" * 64,
        label_release_at=NOW,
        inspected_release_hashes=frozenset(),
    )
    with pytest.raises(DomainError):
        require_acceptance_release(None, **args)
    frozen = FrozenSelection(
        config_hash="a" * 64,
        feature_policy_hash="c" * 64,
        data_hash="d" * 64,
        selected_spec=config.candidates[0],
        frozen_at=NOW - timedelta(days=1),
    )
    require_acceptance_release(frozen, **args)
    with pytest.raises(DomainError):
        require_acceptance_release(
            frozen, **{**args, "inspected_release_hashes": frozenset({"b" * 64})}
        )


def test_calibration_needs_qualified_disjoint_fit_and_validation():
    evidence = QualificationEvidence(
        **{
            name: "approved-synthetic-reference"
            for name in QualificationEvidence.model_fields
            if name != "unresolved_critical_dependencies"
        }
    )
    keys = tuple(f"fit-{i}" for i in range(20))
    valid = tuple(f"valid-{i}" for i in range(20))
    arguments = dict(
        forbidden_keys=frozenset({"training"}),
        fit_groups=frozenset({"fit"}),
        validation_groups=frozenset({"valid"}),
        forbidden_groups=frozenset({"training"}),
        evidence=evidence,
    )
    values = np.linspace(-1, 1, 20)
    labels = (values > 0).astype(int)
    with pytest.raises(DomainError):
        fit_calibration(
            keys, values, labels, valid, values, labels, data_tier="research", **arguments
        )
    result = fit_calibration(
        keys, values, labels, valid, values, labels, data_tier="qualified", **arguments
    )
    assert 0 <= result.manifest["validation_brier"] <= 1
    assert (result.probability(values) >= 0).all()
    with pytest.raises(DomainError):
        fit_calibration(
            keys, values, labels, keys, values, labels, data_tier="qualified", **arguments
        )
