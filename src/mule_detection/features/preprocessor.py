"""Extracted legacy reference algorithm. Use FeaturePipeline at application boundaries.

Selection order, cleanup and encoder defaults deliberately preserve the historical
benchmark. This low-level comparator does not authorize data or exclude metadata.
"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from sklearn.base import BaseEstimator, TransformerMixin  # type: ignore[import-untyped]
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
from sklearn.impute import SimpleImputer  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import OneHotEncoder  # type: ignore[import-untyped]


def _series_digest(series: pd.Series) -> bytes:
    values = pd.util.hash_pandas_object(series, index=False).values.tobytes()
    return hashlib.blake2b(str(series.dtype).encode("utf-8") + values, digest_size=16).digest()


class FoldSafePreprocessor(BaseEstimator, TransformerMixin):  # type: ignore[misc]  # scikit-learn has no bundled typing.
    """Fit structural selection, imputation, and encoding on one training fold."""

    def __init__(self, missing_threshold: float = 0.90) -> None:
        self.missing_threshold = missing_threshold

    @staticmethod
    def _semantic_clean(frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        if "F3888" in frame:
            parsed = pd.to_datetime(frame["F3888"], errors="coerce")
            legacy = parsed.dt.year.le(1950)
            frame["F3888_IS_LEGACY"] = legacy.astype("int8")
            frame["F3888"] = parsed.where(~legacy).map(
                lambda value: value.toordinal() if pd.notna(value) else np.nan
            )
        if {"F3893", "F3894"}.issubset(frame.columns):
            invalid_age = frame["F3893"].eq("RETAIL") & (
                frame["F3894"].lt(18) | frame["F3894"].gt(100)
            )
            frame.loc[invalid_age, "F3894"] = np.nan
        return frame

    def fit(self, frame: pd.DataFrame, y: Any = None) -> FoldSafePreprocessor:
        frame = self._semantic_clean(frame)
        zero_variance = [column for column in frame if frame[column].nunique(dropna=True) <= 1]
        candidates = frame.drop(columns=zero_variance)
        high_missingness = candidates.columns[
            candidates.isna().mean().ge(self.missing_threshold)
        ].tolist()
        candidates = candidates.drop(columns=high_missingness)

        canonical_by_digest: dict[bytes, str] = {}
        duplicates: list[str] = []
        for column in candidates:
            digest = _series_digest(candidates[column])
            canonical = canonical_by_digest.get(digest)
            if canonical is not None and candidates[column].equals(candidates[canonical]):
                duplicates.append(column)
            else:
                canonical_by_digest[digest] = column

        self.dropped_ = {
            "zero_variance": zero_variance,
            "high_missingness": high_missingness,
            "exact_duplicate": duplicates,
        }
        dropped = set(zero_variance + high_missingness + duplicates)
        self.keep_columns_ = [column for column in frame if column not in dropped]
        selected = frame[self.keep_columns_]
        categorical = selected.select_dtypes(include=["object", "category"]).columns.tolist()
        numeric = [column for column in selected if column not in categorical]

        self.transformer_ = ColumnTransformer(
            transformers=[
                (
                    "numeric",
                    SimpleImputer(strategy="median", add_indicator=False),
                    numeric,
                ),
                (
                    "categorical",
                    Pipeline(
                        steps=[
                            ("imputer", SimpleImputer(strategy="most_frequent")),
                            (
                                "encoder",
                                OneHotEncoder(handle_unknown="ignore", sparse_output=True),
                            ),
                        ]
                    ),
                    categorical,
                ),
            ],
            sparse_threshold=0.3,
        )
        self.transformer_.fit(selected)
        return self

    def transform(self, frame: pd.DataFrame) -> Any:
        frame = self._semantic_clean(frame)
        return self.transformer_.transform(frame[self.keep_columns_])

    def fit_transform(self, frame: pd.DataFrame, y: Any = None, **fit_params: Any) -> Any:
        return self.fit(frame).transform(frame)
