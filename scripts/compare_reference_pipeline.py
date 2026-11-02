"""Compare Phase 5 against the untouched reference; never score the saved holdout.

Default input is synthetic. --with-research-data is a local approved-machine
comparison with aggregate public evidence only. Private fold membership and
predictions are not written to the evidence directory.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold

from mule_detection.features.artifacts import digest, runtime_identity, write_json
from mule_detection.features.inputs import research_frame
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.ingestion.partition_guard import development_batch
from mule_detection.ingestion.research_adapter import ResearchAdapter

ROOT = Path(__file__).resolve().parents[1]


def load_reference():
    spec = importlib.util.spec_from_file_location(
        "phase5_reference", ROOT / "scripts/pre_architecture_verification.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic():
    rng = np.random.default_rng(42)
    n = 200
    frame = pd.DataFrame(
        {
            "number": rng.normal(size=n),
            "missing": rng.normal(size=n),
            "category_under_score": rng.choice(["a_b", "c_d", "e_f"], size=n),
            "F3888": rng.choice(["1900-01-01", "2020-01-01", "2021-01-01"], size=n),
            "F3893": rng.choice(["RETAIL", "BUSINESS"], size=n),
            "F3894": rng.integers(10, 110, size=n).astype(float),
            "constant": np.ones(n),
        }
    )
    frame.loc[::4, "missing"] = np.nan
    frame["duplicate"] = frame["number"]
    target = (frame["number"].to_numpy() + rng.normal(size=n) > 1.2).astype(int)
    return frame, target, tuple(f"synthetic-{i:04d}" for i in range(n))


def matrix_delta(left, right):
    if left.shape != right.shape:
        raise AssertionError("Transformed matrix dimensions differ")
    difference = left - right
    values = difference.data if hasattr(difference, "tocsr") else np.asarray(difference)
    return float(np.max(np.abs(values))) if values.size else 0.0


def top_keys(keys, scores, k):
    return [keys[i] for i in sorted(range(len(keys)), key=lambda i: (-scores[i], keys[i]))[:k]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--with-research-data", action="store_true")
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    destination = (ROOT / args.output_dir).resolve()
    if (
        destination.exists()
        or not destination.is_relative_to(ROOT / "artifacts/phase5")
        or args.threads < 1
    ):
        parser.error("Choose a new directory under artifacts/phase5 and positive thread count")
    destination.mkdir(parents=True)
    reference = load_reference()
    adapter = ResearchAdapter.from_repository(ROOT)
    guard = None
    source = {"mode": "synthetic", "private_rows_written": False}
    if args.with_research_data:
        batch, guard = development_batch(
            adapter, ROOT / "DataSet__1_.csv", ROOT / "eda/holdout_split_indices.csv"
        )
        keys, target = batch.record_keys, batch.labels
        # Preserve the reference pandas parser's dtype inference, then verify that
        # every selected row/key matches the independently hash-validated adapter.
        data = pd.read_csv(ROOT / "DataSet__1_.csv")
        references = [item.original_reference for item in batch.restricted_lineage]
        development = data.set_index(reference.INDEX).loc[references].reset_index()
        del data
        frame = development.drop(columns=list(reference.HARD_BLOCKLIST))
        np.testing.assert_array_equal(development[reference.TARGET].to_numpy(), target)
        assert list(frame.columns) == list(batch.predictors)
        packaged_frame = research_frame(batch, guard)
        source.update(
            {
                "mode": "research_development_only",
                "dataset_sha256": batch.dataset_sha256,
                "split_sha256": batch.split_sha256,
                "excluded_holdout_rows": batch.excluded_holdout_count,
            }
        )
        del batch, development
        gc.collect()
    else:
        frame, target, keys = synthetic()
        packaged_frame = frame.copy()
    config = {**reference.MODEL_CONFIG, "n_jobs": args.threads}
    tolerance = {"matrix_atol": 0.0, "prediction_atol": 1e-12, "metric_atol": 1e-12, "rtol": 0.0}
    # Freeze these before fitting, not after observing comparison differences.
    write_json(
        destination / "protocol.json",
        {"tolerance": tolerance, "model_config": config, "folds": 5, "seed": 42, "source": source},
    )
    scores = [np.full(len(frame), np.nan), np.full(len(frame), np.nan)]
    membership = np.zeros(len(frame), dtype=int)
    folds = []
    for fold, (train, valid) in enumerate(
        StratifiedKFold(n_splits=5, shuffle=True, random_state=42).split(frame, target), 1
    ):
        if guard:
            for indexes in (train, valid):
                guard.assert_development(
                    [keys[i] for i in indexes], source["dataset_sha256"], source["split_sha256"]
                )
        old = reference.FoldSafePreprocessor().fit(frame.iloc[train])
        new = FeaturePipeline.from_repository(ROOT).fit(packaged_frame.iloc[train])
        assert old.keep_columns_ == new.keep_columns_ and old.dropped_ == new.dropped_
        train_matrices = (
            old.transform(frame.iloc[train]),
            new.transform(packaged_frame.iloc[train]),
        )
        valid_matrices = (
            old.transform(frame.iloc[valid]),
            new.transform(packaged_frame.iloc[valid]),
        )
        train_delta = matrix_delta(*train_matrices)
        valid_delta = matrix_delta(*valid_matrices)
        assert max(train_delta, valid_delta) <= tolerance["matrix_atol"]
        for index in range(2):
            model = lgb.LGBMClassifier(**config, random_state=42 + fold)
            model.fit(train_matrices[index], target[train])
            scores[index][valid] = model.predict_proba(valid_matrices[index])[:, 1]
        delta = float(np.max(np.abs(scores[0][valid] - scores[1][valid])))
        assert delta <= tolerance["prediction_atol"]
        membership[valid] += 1
        report = {
            "fold": fold,
            "train_rows": len(train),
            "validation_rows": len(valid),
            "selected_columns": old.keep_columns_,
            "dropped": new.dropped_,
            "training_fingerprint": new.training_fingerprint_,
            "train_membership_sha256": hashlib.sha256(
                "\n".join(keys[i] for i in train).encode()
            ).hexdigest(),
            "validation_membership_sha256": hashlib.sha256(
                "\n".join(keys[i] for i in valid).encode()
            ).hexdigest(),
            "train_matrix_max_delta": train_delta,
            "validation_matrix_max_delta": valid_delta,
            "prediction_max_delta": delta,
        }
        folds.append(report)
        write_json(destination / f"fold_{fold}.json", report)
        print(f"fold {fold}: matrix parity exact; prediction delta {delta:.3g}", flush=True)
        del old, new, train_matrices, valid_matrices, model
        gc.collect()
    assert (membership == 1).all() and all(np.isfinite(score).all() for score in scores)
    metrics = [
        {
            "average_precision": float(average_precision_score(target, score)),
            "roc_auc": float(roc_auc_score(target, score)),
            "top_k": [reference.top_k_metrics(target, score, k) for k in (25, 50, 100)],
        }
        for score in scores
    ]
    for name in ("average_precision", "roc_auc"):
        assert abs(metrics[0][name] - metrics[1][name]) <= tolerance["metric_atol"]
    overlap = {
        str(k): top_keys(keys, scores[0], k) == top_keys(keys, scores[1], k) for k in (25, 50, 100)
    }
    assert all(overlap.values()) and metrics[0]["top_k"] == metrics[1]["top_k"]
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    report = {
        "result": "PASSED",
        "checked_at": datetime.now(UTC).isoformat(),
        "executed_command": subprocess.list2cmdline([sys.executable, *sys.argv]),
        "code_revision": revision,
        "source": source,
        "runtime": runtime_identity(),
        "platform": platform.platform(),
        "source_sha256": {
            str(path.relative_to(ROOT)): digest(path)
            for path in [
                Path(__file__),
                ROOT / "scripts/pre_architecture_verification.py",
                *sorted((ROOT / "src/mule_detection/features").glob("*.py")),
                ROOT / "config/feature_policy.yaml",
                ROOT / "config/semantic_rules.yaml",
            ]
        },
        "eligible_rows": len(frame),
        "positive_count": int(target.sum()),
        "oof_coverage_exactly_once": True,
        "prediction_max_delta": float(np.max(np.abs(scores[0] - scores[1]))),
        "metrics_reference": metrics[0],
        "metrics_packaged": metrics[1],
        "top_k_membership_equal": overlap,
        "fold_reports": len(folds),
        "tolerance": tolerance,
        "limitations": [
            "Development diagnostics only; extraction cohort and target remain confounded.",
            "No holdout fitting, tuning or scoring.",
            "No production validation or model approval.",
            "Per-record predictions/membership remain in memory; only hashes and aggregates saved.",
        ],
    }
    write_json(destination / "report.json", report)
    print(json.dumps({"result": "PASSED", "report": str(destination / "report.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
