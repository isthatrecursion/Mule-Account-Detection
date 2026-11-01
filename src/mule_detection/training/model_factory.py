"""Bounded model factories and training-fitted scaling of numeric columns only."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
from scipy import sparse  # type: ignore[import-untyped]
from sklearn.base import clone  # type: ignore[import-untyped]
from sklearn.exceptions import ConvergenceWarning  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]
from threadpoolctl import threadpool_limits  # type: ignore[import-untyped]

from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.training.evaluation_policy import ModelSpec


@dataclass
class FittedCandidate:
    features: FeaturePipeline
    estimator: Any
    scaler: Any
    numeric_stop: int
    threads: int

    def matrix(self, X: Any) -> Any:
        matrix = self.features.transform(X)
        if self.scaler is None or self.numeric_stop == 0:
            return matrix
        stop = self.numeric_stop
        numeric = self.scaler.transform(matrix[:, :stop])
        if sparse.issparse(matrix):
            return sparse.hstack([numeric, matrix[:, stop:]], format="csr")
        return np.hstack([numeric, matrix[:, stop:]])

    def predict_score(self, X: Any) -> Any:
        with threadpool_limits(limits=self.threads):
            return self.estimator.predict_proba(self.matrix(X))[:, 1]


def fit_candidate(
    prototype: FeaturePipeline,
    spec: ModelSpec,
    X: Any,
    target: Any,
    *,
    seed: int,
    threads: int,
) -> FittedCandidate:
    features = clone(prototype).fit(X)
    matrix = features.transform(X)
    scaler = None
    stop = int(features.transformer_.output_indices_["numeric"].stop)
    if spec.family == "logistic":
        if stop:
            scaler = StandardScaler(with_mean=False).fit(matrix[:, :stop])
            scaled = scaler.transform(matrix[:, :stop])
            matrix = (
                sparse.hstack([scaled, matrix[:, stop:]], format="csr")
                if sparse.issparse(matrix)
                else np.hstack([scaled, matrix[:, stop:]])
            )
        estimator: Any = LogisticRegression(
            C=spec.C,
            max_iter=spec.max_iter,
            solver="liblinear",
            class_weight="balanced",
            random_state=seed,
        )
    else:
        estimator = lgb.LGBMClassifier(
            objective="binary",
            n_estimators=spec.n_estimators,
            learning_rate=spec.learning_rate,
            num_leaves=spec.num_leaves,
            scale_pos_weight=10.0,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            n_jobs=threads,
            verbosity=-1,
            random_state=seed,
        )
    with threadpool_limits(limits=threads), warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        try:
            estimator.fit(matrix, target)
        except ConvergenceWarning:
            raise DomainError(ErrorCode.VALUE_INVALID) from None
    return FittedCandidate(features, estimator, scaler, stop, threads)
