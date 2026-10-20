from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Literal, Self

from pydantic import Field, StrictFloat, model_validator

from mule_detection.domain.contracts.common import (
    Contract,
    Digest,
    Text,
    ValueModel,
    canonical_hash,
    violation,
)
from mule_detection.domain.contracts.models import ModelBundle
from mule_detection.domain.contracts.snapshot import FeatureValue
from mule_detection.domain.errors import DomainError, ErrorCode


class Exclusion(ValueModel):
    feature_id: Text
    reason: Text


class FeaturePolicy(Contract):
    VERSION = "feature_policy_v1"
    contract_version: Literal["feature_policy_v1"]
    policy_version: Text
    approval_context: Text
    historical_register_sha256: Digest
    historical_register_count: Literal[1404]
    permanent_exclusions: tuple[Exclusion, ...]
    missingness_threshold: StrictFloat = Field(gt=0, le=1)

    @model_validator(mode="after")
    def mandatory_exclusions(self) -> Self:
        ids = [item.feature_id for item in self.permanent_exclusions]
        required = {"Unnamed: 0", "F3924", "F2230", "F3912", "F3287", "F3290", "F3611", "F3614"}
        if len(ids) != len(set(ids)) or not required <= set(ids):
            raise violation(ErrorCode.FEATURE_FORBIDDEN)
        return self

    @property
    def fingerprint(self) -> str:
        return canonical_hash(self)

    def assert_predictors(self, columns: Sequence[str]) -> None:
        reserved = {
            "account_id",
            "record_key",
            "research_record_id",
            "snapshot_id",
            "source_id",
            "label",
            "target",
        }
        if ({item.feature_id for item in self.permanent_exclusions} | reserved).intersection(
            columns
        ):
            raise DomainError(ErrorCode.FEATURE_FORBIDDEN)
        if len(columns) != len(set(columns)):
            raise DomainError(ErrorCode.SCHEMA_MISMATCH)


class FoldExclusions(ValueModel):
    fit_partition: Literal["train"]
    training_fingerprint: Digest
    feature_policy_hash: Digest
    exclusions: tuple[Exclusion, ...]


def validate_bundle_policy(bundle: ModelBundle, policy: FeaturePolicy) -> None:
    if (
        bundle.feature_policy_version != policy.policy_version
        or bundle.feature_policy_hash != policy.fingerprint
    ):
        raise DomainError(ErrorCode.LINEAGE_INVALID)


def derive_structural_exclusions(
    training: Mapping[str, Sequence[FeatureValue]], policy: FeaturePolicy
) -> FoldExclusions:
    """Training-only contract reference; Phase 5 must establish historical pipeline parity."""
    policy.assert_predictors(list(training))
    lengths = {len(values) for values in training.values()}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) == 0:
        raise DomainError(ErrorCode.VALUE_INVALID)
    exclusions: list[Exclusion] = []
    seen: set[tuple[FeatureValue, ...]] = set()
    normalized: dict[str, list[FeatureValue]] = {}
    for column, values in training.items():
        if any(isinstance(v, float) and not math.isfinite(v) for v in values if v is not None):
            raise DomainError(ErrorCode.VALUE_INVALID)
        normalized[column] = list(values)
        observed = [value for value in values if value is not None]
        reason = None
        if len(set(observed)) <= 1:
            reason = "zero_variance"
        elif 1 - len(observed) / len(values) > policy.missingness_threshold:
            reason = "high_missingness"
        elif tuple(values) in seen:
            reason = "exact_duplicate"
        if reason:
            exclusions.append(Exclusion(feature_id=column, reason=reason))
        else:
            seen.add(tuple(values))
    return FoldExclusions(
        fit_partition="train",
        training_fingerprint=canonical_hash(normalized),
        feature_policy_hash=policy.fingerprint,
        exclusions=tuple(exclusions),
    )
