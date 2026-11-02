"""Platt calibration is available only with qualified, disjoint fit/evaluation inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.special import expit  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.metrics import brier_score_loss  # type: ignore[import-untyped]

from mule_detection.domain.contracts.common import canonical_hash
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.training.evaluation_policy import QualificationEvidence, require_mode
from mule_detection.training.metrics import ranking_metrics


@dataclass(frozen=True)
class CalibrationResult:
    coefficient: float
    intercept: float
    manifest: dict[str, Any]

    def probability(self, scores: Any) -> Any:
        values = np.asarray(scores, dtype=float)
        if not np.isfinite(values).all():
            raise DomainError(ErrorCode.VALUE_INVALID)
        return expit(self.coefficient * values + self.intercept)


def fit_calibration(
    fit_keys: tuple[str, ...],
    fit_scores: Any,
    fit_labels: Any,
    validation_keys: tuple[str, ...],
    validation_scores: Any,
    validation_labels: Any,
    *,
    forbidden_keys: frozenset[str],
    fit_groups: frozenset[str],
    validation_groups: frozenset[str],
    forbidden_groups: frozenset[str],
    evidence: QualificationEvidence,
    data_tier: str,
    seed: int = 42,
) -> CalibrationResult:
    require_mode("qualified_temporal", data_tier, evidence)
    if (
        not fit_groups
        or not validation_groups
        or set(fit_keys) & (set(validation_keys) | forbidden_keys)
        or set(validation_keys) & forbidden_keys
        or fit_groups & (validation_groups | forbidden_groups)
        or validation_groups & forbidden_groups
    ):
        raise DomainError(ErrorCode.SPLIT_MISMATCH)
    for keys, labels, scores in (
        (fit_keys, fit_labels, fit_scores),
        (validation_keys, validation_labels, validation_scores),
    ):
        if (
            len(keys) < 10
            or ranking_metrics(list(keys), labels, scores, (1,))["average_precision"] is None
        ):
            raise DomainError(ErrorCode.LABEL_HISTORY_INVALID)
    model = LogisticRegression(random_state=seed, solver="lbfgs").fit(
        np.asarray(fit_scores).reshape(-1, 1), fit_labels
    )
    coefficient, intercept = float(model.coef_[0, 0]), float(model.intercept_[0])
    probability = expit(coefficient * np.asarray(validation_scores) + intercept)
    reliability = []
    for index in range(10):
        mask = (probability >= index / 10) & (
            probability < (index + 1) / 10 if index < 9 else probability <= 1
        )
        reliability.append(
            {
                "bin": index,
                "rows": int(mask.sum()),
                "mean_probability": float(probability[mask].mean()) if mask.any() else None,
                "positive_rate": float(np.asarray(validation_labels)[mask].mean())
                if mask.any()
                else None,
            }
        )
    manifest = {
        "method": "platt_v1",
        "output_scale": "calibrated_probability",
        "seed": seed,
        "coefficient": coefficient,
        "intercept": intercept,
        "fit_input_hash": canonical_hash(
            {
                "keys": fit_keys,
                "scores": np.asarray(fit_scores).tolist(),
                "labels": np.asarray(fit_labels).tolist(),
            }
        ),
        "validation_input_hash": canonical_hash(
            {
                "keys": validation_keys,
                "scores": np.asarray(validation_scores).tolist(),
                "labels": np.asarray(validation_labels).tolist(),
            }
        ),
        "fit_membership_hash": canonical_hash({"keys": fit_keys}),
        "validation_membership_hash": canonical_hash({"keys": validation_keys}),
        "qualification_hash": canonical_hash(evidence),
        "validation_brier": float(brier_score_loss(validation_labels, probability)),
        "validation_reliability": reliability,
    }
    return CalibrationResult(coefficient, intercept, manifest)
