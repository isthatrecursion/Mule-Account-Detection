"""Versioned legacy cleanup; no inferred production semantics."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Self

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from sklearn.base import BaseEstimator, TransformerMixin  # type: ignore[import-untyped]
from sklearn.utils.validation import check_is_fitted  # type: ignore[import-untyped]

from mule_detection.domain.contracts.common import ValueModel
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.settings import read_yaml


class SemanticRules(ValueModel):
    """A change to legacy constants requires a new implemented policy version."""

    policy_version: Literal["legacy_research_v1"] = "legacy_research_v1"
    certification_status: Literal["UNVERIFIED"] = "UNVERIFIED"
    qualified_use_allowed: Literal[False] = False
    date_legacy_max_year: Literal[1950] = 1950
    retail_value: Literal["RETAIL"] = "RETAIL"
    retail_min_age: Literal[18] = 18
    retail_max_age: Literal[100] = 100

    @classmethod
    def from_file(cls, path: Path) -> Self:
        return cls.model_validate(read_yaml(path))


def semantic_clean(frame: pd.DataFrame, rules: SemanticRules) -> pd.DataFrame:
    frame = frame.copy()
    if "F3888_IS_LEGACY" in frame:
        raise DomainError(ErrorCode.FEATURE_FORBIDDEN)
    if "F3888" in frame:
        parsed = pd.to_datetime(frame["F3888"], errors="coerce")
        legacy = parsed.dt.year.le(rules.date_legacy_max_year)
        frame["F3888_IS_LEGACY"] = legacy.astype("int8")
        frame["F3888"] = parsed.where(~legacy).map(
            lambda value: value.toordinal() if pd.notna(value) else np.nan
        )
    if {"F3893", "F3894"}.issubset(frame.columns):
        invalid = frame["F3893"].eq(rules.retail_value) & (
            frame["F3894"].lt(rules.retail_min_age) | frame["F3894"].gt(rules.retail_max_age)
        )
        frame.loc[invalid, "F3894"] = np.nan
    return frame


class SemanticCleaner(TransformerMixin, BaseEstimator):  # type: ignore[misc]  # scikit-learn has no bundled typing.
    def __init__(
        self,
        version: str = "legacy_research_v1",
        data_tier: str = "research",
        rules: SemanticRules | None = None,
    ) -> None:
        self.version = version
        self.data_tier = data_tier
        self.rules = rules

    def fit(self, X: pd.DataFrame, y: Any = None) -> Self:
        # Certified rules must be implemented as a separately reviewed version;
        # neither a request flag nor a claimed approval string can certify legacy rules.
        if self.version != "legacy_research_v1" or self.data_tier != "research":
            raise DomainError(ErrorCode.DICTIONARY_UNCERTIFIED)
        self.rules_ = self.rules if self.rules is not None else SemanticRules()
        self.fitted_ = True
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        check_is_fitted(self, "fitted_")
        return semantic_clean(X, self.rules_)


def missing_value_mask(frame: pd.DataFrame, rules: SemanticRules) -> pd.DataFrame:
    """Includes legacy-invalid cells separately from the original raw observations."""
    return semantic_clean(frame, rules).isna()
