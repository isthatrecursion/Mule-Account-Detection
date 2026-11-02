"""Explicit evaluation purposes and fail-closed qualification evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from mule_detection.domain.contracts.common import ValueModel, canonical_hash
from mule_detection.domain.errors import DomainError, ErrorCode

LIMITATIONS = (
    "Extraction cohort and target are confounded; research diagnostics are not production evidence.",
    "Pooled OOF scores come from different fitted models and may have different scales.",
    "Configuration selection uses development data; final independent acceptance is not performed.",
    "Research output is review priority, never a calibrated fraud probability.",
)


class ModelSpec(ValueModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    family: Literal["logistic", "lightgbm"]
    C: float = Field(default=1.0, gt=0, le=100)
    max_iter: int = Field(default=1000, ge=1, le=10000)
    n_estimators: int = Field(default=300, ge=1, le=2000)
    learning_rate: float = Field(default=0.05, gt=0, le=1)
    num_leaves: int = Field(default=15, ge=2, le=128)


class TrainingConfig(ValueModel):
    config_version: Literal["research_training_v1"] = "research_training_v1"
    mode: Literal["research", "qualified_temporal"] = "research"
    outer_folds: int = Field(default=5, ge=2, le=10)
    inner_folds: int = Field(default=3, ge=2, le=5)
    seed: int = Field(default=42, ge=0, le=2**31 - 100)
    threads: int = Field(default=2, ge=1, le=8)
    top_k: tuple[int, ...] = (25, 50, 100)
    bootstrap_repetitions: int = Field(default=200, ge=20, le=2000)
    selection_metric: Literal["mean_inner_average_precision"] = "mean_inner_average_precision"
    candidates: tuple[ModelSpec, ...]
    ablation_features: tuple[str, ...] = ()
    ablation_approval_reference: str | None = None
    subgroup_approval_reference: str | None = None
    minimum_subgroup_rows: int = Field(default=30, ge=5)
    minimum_subgroup_positives: int = Field(default=5, ge=2)

    @model_validator(mode="after")
    def coherent(self) -> TrainingConfig:
        if (
            not self.candidates
            or len(self.candidates) > 8
            or len({c.name for c in self.candidates}) != len(self.candidates)
            or not self.top_k
            or any(k <= 0 for k in self.top_k)
            or len(set(self.top_k)) != len(self.top_k)
            or (self.ablation_features and not self.ablation_approval_reference)
        ):
            raise ValueError("Invalid experiment policy")
        return self

    @property
    def fingerprint(self) -> str:
        return canonical_hash(self)


class QualificationEvidence(ValueModel):
    """Construct from trusted source/approval records, never a CLI request flag."""

    identity_reference: str | None = None
    dictionary_reference: str | None = None
    feature_availability_reference: str | None = None
    mature_label_reference: str | None = None
    representative_prevalence_reference: str | None = None
    mixed_class_period_reference: str | None = None
    policy_approval_reference: str | None = None
    unresolved_critical_dependencies: tuple[str, ...] = ()

    def require_qualified(self) -> None:
        values = self.model_dump(exclude={"unresolved_critical_dependencies"})
        if self.unresolved_critical_dependencies or not all(values.values()):
            raise DomainError(ErrorCode.CONTRACT_INVALID)


def require_mode(mode: str, data_tier: str, evidence: QualificationEvidence | None = None) -> None:
    if mode == "research" and data_tier in {"research", "synthetic"}:
        return
    if mode != "qualified_temporal" or data_tier != "qualified" or evidence is None:
        raise DomainError(ErrorCode.CONTRACT_INVALID)
    evidence.require_qualified()
