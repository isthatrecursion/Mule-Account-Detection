"""Training-only fitting and immutable inference for research feature snapshots.

Application services must verify accepted input, membership and source coverage
before invoking this numerical component. It cannot certify those facts itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Self

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from sklearn.base import BaseEstimator, TransformerMixin  # type: ignore[import-untyped]
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
from sklearn.impute import SimpleImputer  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import OneHotEncoder  # type: ignore[import-untyped]
from sklearn.utils.validation import check_is_fitted  # type: ignore[import-untyped]

from mule_detection.domain.contracts.common import parse_contract
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.domain.feature_policy import FeaturePolicy
from mule_detection.features.exclusion_report import exclusion_report
from mule_detection.features.semantic_cleanup import (
    SemanticCleaner,
    SemanticRules,
    missing_value_mask,
)
from mule_detection.features.signature import (
    align_input,
    frame_fingerprint,
    input_signature,
    transformed_mapping,
)
from mule_detection.features.transformers import PolicyExclusion, StructuralPruner
from mule_detection.settings import read_yaml


class FeaturePipeline(TransformerMixin, BaseEstimator):  # type: ignore[misc]  # scikit-learn has no bundled typing.
    def __init__(
        self,
        policy: FeaturePolicy,
        semantic_version: str = "legacy_research_v1",
        data_tier: str = "research",
        semantic_rules: SemanticRules | None = None,
    ) -> None:
        self.policy = policy
        self.semantic_version = semantic_version
        self.data_tier = data_tier
        self.semantic_rules = semantic_rules

    @classmethod
    def from_repository(cls, root: Path) -> Self:
        return cls(
            parse_contract(FeaturePolicy, read_yaml(root / "config/feature_policy.yaml")),
            semantic_rules=SemanticRules.from_file(root / "config/semantic_rules.yaml"),
        )

    def fit(self, X: pd.DataFrame, y: Any = None) -> Self:
        if X.empty or not all(isinstance(c, str) for c in X.columns):
            raise DomainError(ErrorCode.VALUE_INVALID)
        # Construct locally, then install complete fitted state only after all checks pass.
        gate = PolicyExclusion(self.policy)
        clean = SemanticCleaner(self.semantic_version, self.data_tier, self.semantic_rules)
        prune = StructuralPruner(self.policy.missingness_threshold)
        selected = prune.fit_transform(clean.fit_transform(gate.fit_transform(X)))
        categorical = selected.select_dtypes(include=["object", "category"]).columns.tolist()
        numeric = [column for column in selected if column not in categorical]
        encoder = ColumnTransformer(
            transformers=[
                ("numeric", SimpleImputer(strategy="median", add_indicator=False), numeric),
                (
                    "categorical",
                    Pipeline(
                        [
                            ("imputer", SimpleImputer(strategy="most_frequent")),
                            ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=True)),
                        ]
                    ),
                    categorical,
                ),
            ],
            sparse_threshold=0.3,
        )
        encoder.fit(selected)
        mapping = transformed_mapping(encoder)
        reference: dict[str, Any] = {}
        for column in prune.keep_columns_:
            if column not in X:  # Generated legacy date indicator is versioned separately.
                continue
            observed = X[column].dropna()
            if pd.api.types.is_numeric_dtype(X[column]):
                values, counts = np.unique(observed.to_numpy(dtype=float), return_counts=True)
                if not np.isfinite(values).all():
                    raise DomainError(ErrorCode.VALUE_INVALID)
                reference[column] = {
                    "kind": "numeric",
                    "values": values.tolist(),
                    "counts": counts.tolist(),
                }
            else:
                reference[column] = {
                    "kind": "categorical",
                    "counts": {str(k): int(v) for k, v in observed.value_counts().items()},
                }
            reference[column]["missing_count"] = int(X[column].isna().sum())
            reference[column]["training_rows"] = len(X)
        training_hash = frame_fingerprint(X)
        self.steps_ = Pipeline([("policy", gate), ("semantic", clean), ("prune", prune)])
        self.semantic_rules_ = clean.rules_
        self.transformer_ = encoder
        self.input_signature_ = input_signature(X)
        self.keep_columns_ = list(prune.keep_columns_)
        self.dropped_ = prune.dropped_
        self.transformed_features_ = mapping
        self.n_features_out_ = len(mapping)
        self.n_features_in_ = len(X.columns)
        self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        self.training_fingerprint_ = training_hash
        self.reference_statistics_ = reference
        self.exclusion_report_ = exclusion_report(
            self.policy, self.dropped_, self.keep_columns_, training_hash
        )
        return self

    def transform(self, X: pd.DataFrame) -> Any:
        check_is_fitted(self, "transformer_")
        aligned = align_input(X, self.input_signature_)
        if len(aligned) == 0:
            return np.empty((0, self.n_features_out_), dtype=float)
        selected = self.steps_.transform(aligned)
        result = self.transformer_.transform(selected)
        if result.shape[1] != self.n_features_out_:
            raise DomainError(ErrorCode.SCHEMA_MISMATCH)
        values = result.data if hasattr(result, "tocsr") else result
        if not np.isfinite(values).all():
            raise DomainError(ErrorCode.VALUE_INVALID)
        return result

    def missing_mask(self, X: pd.DataFrame) -> pd.DataFrame:
        check_is_fitted(self, "transformer_")
        return missing_value_mask(align_input(X, self.input_signature_), self.semantic_rules_)

    def get_feature_names_out(self, input_features: Any = None) -> Any:
        check_is_fitted(self, "transformer_")
        if input_features is not None and list(input_features) != list(self.feature_names_in_):
            raise DomainError(ErrorCode.SCHEMA_MISMATCH)
        return np.asarray([item["name"] for item in self.transformed_features_], dtype=object)
