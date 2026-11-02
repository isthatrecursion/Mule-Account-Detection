"""Exact model-scale additive contributions, never percentile explanations."""

from typing import Any

import numpy as np
from threadpoolctl import threadpool_limits  # type: ignore[import-untyped]

from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.training.model_factory import FittedCandidate


def contributions(fitted: FittedCandidate, frame: Any) -> dict[str, Any]:
    matrix = fitted.matrix(frame)
    count = fitted.features.n_features_out_
    mapping = fitted.features.transformed_features_
    if [item["index"] for item in mapping] != list(range(count)):
        raise DomainError(ErrorCode.SCHEMA_MISMATCH)
    with threadpool_limits(limits=fitted.threads):
        if hasattr(fitted.estimator, "booster_"):
            booster = fitted.estimator.booster_
            values = booster.predict(matrix, pred_contrib=True, num_threads=fitted.threads)
            values = values.toarray() if hasattr(values, "toarray") else np.asarray(values)
            raw = np.asarray(booster.predict(matrix, raw_score=True, num_threads=fitted.threads))
            method = "TREE_SHAP_RAW_MARGIN"
        else:
            dense = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
            values = np.column_stack(
                [
                    dense * fitted.estimator.coef_[0],
                    np.full(len(frame), fitted.estimator.intercept_[0]),
                ]
            )
            raw = np.asarray(fitted.estimator.decision_function(matrix))
            method = "LINEAR_LOG_ODDS"
    if (
        values.shape != (len(frame), count + 1)
        or not np.isfinite(values).all()
        or not np.isfinite(raw).all()
    ):
        raise DomainError(ErrorCode.SCORE_STATE_INVALID)
    if not np.allclose(values.sum(axis=1), raw, atol=1e-8, rtol=1e-8):
        raise DomainError(ErrorCode.SCORE_STATE_INVALID)
    return {
        "values": values[:, :-1].tolist(),
        "base_values": values[:, -1].tolist(),
        "raw_margins": raw.tolist(),
        "mapping": mapping,
        "scale": "raw_margin",
        "method": method,
        "atol": 1e-8,
        "rtol": 1e-8,
    }
