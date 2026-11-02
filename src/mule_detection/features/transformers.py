"""Cloneable components; every learned selection is fitted on training rows only."""

from __future__ import annotations

from typing import Any, Self

import pandas as pd  # type: ignore[import-untyped]
from sklearn.base import BaseEstimator, TransformerMixin  # type: ignore[import-untyped]
from sklearn.utils.validation import check_is_fitted  # type: ignore[import-untyped]

from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.domain.feature_policy import FeaturePolicy
from mule_detection.features.preprocessor import _series_digest


class PolicyExclusion(TransformerMixin, BaseEstimator):  # type: ignore[misc]  # scikit-learn has no bundled typing.
    """Reject forbidden predictors; intake is responsible for separating metadata."""

    def __init__(self, policy: FeaturePolicy) -> None:
        self.policy = policy

    def fit(self, X: pd.DataFrame, y: Any = None) -> Self:
        self.policy.assert_predictors(list(X.columns))
        self.fitted_ = True
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        check_is_fitted(self, "fitted_")
        self.policy.assert_predictors(list(X.columns))
        return X.copy()


class StructuralPruner(TransformerMixin, BaseEstimator):  # type: ignore[misc]  # scikit-learn has no bundled typing.
    def __init__(self, missing_threshold: float = 0.90) -> None:
        self.missing_threshold = missing_threshold

    def fit(self, X: pd.DataFrame, y: Any = None) -> Self:
        if not 0 < self.missing_threshold <= 1 or X.empty or X.columns.duplicated().any():
            raise DomainError(ErrorCode.VALUE_INVALID)
        zero = [column for column in X if X[column].nunique(dropna=True) <= 1]
        candidates = X.drop(columns=zero)
        missing = candidates.columns[candidates.isna().mean().ge(self.missing_threshold)].tolist()
        candidates = candidates.drop(columns=missing)
        canonical: dict[bytes, str] = {}
        duplicates: list[str] = []
        for column in candidates:
            digest = _series_digest(candidates[column])
            previous = canonical.get(digest)
            if previous is not None and candidates[column].equals(candidates[previous]):
                duplicates.append(column)
            else:
                canonical[digest] = column
        self.dropped_ = {
            "zero_variance": zero,
            "high_missingness": missing,
            "exact_duplicate": duplicates,
        }
        dropped = set(zero + missing + duplicates)
        self.keep_columns_ = [column for column in X if column not in dropped]
        if not self.keep_columns_:
            raise DomainError(ErrorCode.VALUE_INVALID)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        check_is_fitted(self, "keep_columns_")
        if not set(self.keep_columns_) <= set(X.columns):
            raise DomainError(ErrorCode.SCHEMA_MISMATCH)
        return X.loc[:, self.keep_columns_].copy()
