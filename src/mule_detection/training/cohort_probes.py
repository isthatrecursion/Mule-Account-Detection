"""Cohort diagnostics never establish causal feature meaning or fraud validity."""

from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.metrics import balanced_accuracy_score  # type: ignore[import-untyped]
from sklearn.model_selection import StratifiedKFold  # type: ignore[import-untyped]
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]


def cohort_probes(X: Any, labels: Any, cohorts: list[str], *, seed: int) -> dict[str, Any]:
    if len(cohorts) != len(X) or not cohorts:
        raise ValueError("Cohort membership is required")
    missing = X.isna()
    groups = sorted(set(cohorts))
    counts = {
        group: {
            "rows": cohorts.count(group),
            "positives": int(np.asarray(labels)[np.asarray(cohorts) == group].sum()),
        }
        for group in groups
    }
    rates = [missing.loc[np.asarray(cohorts) == group].mean() for group in groups]
    gaps = {
        str(column): float(max(row[column] for row in rates) - min(row[column] for row in rates))
        for column in X
    }
    report: dict[str, Any] = {
        "cohort_counts": counts,
        "maximum_missingness_gap_by_feature": gaps,
        "mixed_class_cohorts": sum(0 < row["positives"] < row["rows"] for row in counts.values()),
        "limitations": "Associations and source predictability are diagnostics; target/cohort confounding prevents causal interpretation.",
    }
    if len(groups) < 2 or min(cohorts.count(group) for group in groups) < 2:
        report["source_predictability"] = {
            "status": "UNAVAILABLE",
            "reason": "INSUFFICIENT_COHORTS",
        }
        return report
    # Bounded, predeclared source-proxy probe: only row missingness count/fraction.
    # Standardization is fitted separately inside each probe training fold.
    summary = np.column_stack([missing.sum(axis=1).to_numpy(), missing.mean(axis=1).to_numpy()])
    predicted = np.empty(len(X), dtype=object)
    for train, valid in StratifiedKFold(
        min(3, min(cohorts.count(g) for g in groups)), shuffle=True, random_state=seed
    ).split(summary, cohorts):
        model = make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=1000, random_state=seed)
        )
        model.fit(summary[train], np.asarray(cohorts)[train])
        predicted[valid] = model.predict(summary[valid])
    report["source_predictability"] = {
        "status": "DIAGNOSTIC_ONLY",
        "probe_features": ["missing_cell_count", "missing_cell_fraction"],
        "balanced_accuracy": float(balanced_accuracy_score(cohorts, predicted)),
    }
    return report
