from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import StrictFloat, StrictInt, StrictStr, model_validator

from mule_detection.domain.contracts.common import (
    Contract,
    Nonnegative,
    Text,
    UtcTime,
    ValueModel,
    violation,
)
from mule_detection.domain.errors import DomainError, ErrorCode

FeatureValue = StrictFloat | StrictInt | StrictStr | None


class SourceCoverage(ValueModel):
    source_id: Text
    source_partition: Text
    window_start: UtcTime
    window_end: UtcTime
    complete_through: UtcTime | None
    expected_count: Nonnegative | None
    received_count: Nonnegative
    sequence_gaps: Nonnegative
    heartbeat_at: UtcTime | None
    status: Literal["COMPLETE", "INCOMPLETE", "UNKNOWN"]

    @model_validator(mode="after")
    def complete_evidence(self) -> Self:
        if self.window_end <= self.window_start:
            raise violation(ErrorCode.CUTOFF_MISMATCH)
        if self.status == "COMPLETE" and (
            self.complete_through is None
            or self.complete_through < self.window_end
            or self.expected_count is None
            or self.received_count != self.expected_count
            or self.sequence_gaps != 0
            or self.heartbeat_at is None
            or self.heartbeat_at < self.window_end
        ):
            raise violation(ErrorCode.COMPLETENESS_INVALID)
        return self


class QualifiedSnapshot(Contract):
    VERSION = "qualified_snapshot_v1"
    contract_version: Literal["qualified_snapshot_v1"]
    snapshot_id: UUID
    record_key: UUID
    account_id: Text
    source_id: Text
    source_contract_version: Text
    identity_approval_reference: Text
    snapshot_at: UtcTime
    observation_start: UtcTime
    observation_cutoff: UtcTime
    available_at: UtcTime
    features: dict[Text, FeatureValue]
    source_coverage: tuple[SourceCoverage, ...]
    correction_of: UUID | None

    @model_validator(mode="after")
    def cutoffs(self) -> Self:
        forbidden = {
            "account_id",
            "record_key",
            "snapshot_id",
            "source_id",
            "label",
            "target",
            "Unnamed: 0",
            "F3924",
            "F2230",
            "F3912",
            "F3287",
            "F3290",
            "F3611",
            "F3614",
        }
        if forbidden.intersection(self.features):
            raise violation(ErrorCode.FEATURE_FORBIDDEN)
        if (
            not self.observation_start
            < self.observation_cutoff
            <= self.available_at
            <= self.snapshot_at
        ):
            raise violation(ErrorCode.CUTOFF_MISMATCH)
        if (
            not self.features
            or not self.source_coverage
            or any(c.source_id != self.source_id for c in self.source_coverage)
        ):
            raise violation(ErrorCode.SOURCE_CONFLICT)
        if any(
            c.window_start != self.observation_start or c.window_end != self.observation_cutoff
            for c in self.source_coverage
        ):
            raise violation(ErrorCode.CUTOFF_MISMATCH)
        return self


class SourceDefinition(ValueModel):
    source_id: Text
    contract_version: Text
    approval_reference: Text
    feature_ids: tuple[Text, ...]
    required_partitions: tuple[Text, ...]
    observation_rule: Literal["cutoff_at_snapshot"]
    availability_rule: Literal["available_by_snapshot"]
    max_clock_skew_seconds: Nonnegative

    @model_validator(mode="after")
    def required_coverage(self) -> Self:
        if (
            not self.feature_ids
            or not self.required_partitions
            or len(self.required_partitions) != len(set(self.required_partitions))
        ):
            raise violation(ErrorCode.SOURCE_CONFLICT)
        return self


class SourceRegistry(Contract):
    VERSION = "source_registry_v1"
    contract_version: Literal["source_registry_v1"]
    sources: tuple[SourceDefinition, ...]

    @model_validator(mode="after")
    def no_conflicts(self) -> Self:
        if len({s.source_id for s in self.sources}) != len(self.sources):
            raise violation(ErrorCode.SOURCE_CONFLICT)
        features = [f for source in self.sources for f in source.feature_ids]
        if len(features) != len(set(features)):
            raise violation(ErrorCode.SOURCE_CONFLICT)
        return self


class JoinedSnapshot(ValueModel):
    account_id: Text
    snapshot_at: UtcTime
    source_snapshot_ids: tuple[UUID, ...]
    features: dict[Text, FeatureValue]
    source_coverage: tuple[SourceCoverage, ...]
    completeness: Literal["COMPLETE", "INCOMPLETE"]


def merge_snapshots(
    snapshots: tuple[QualifiedSnapshot, ...], registry: SourceRegistry
) -> JoinedSnapshot:
    if not snapshots:
        raise DomainError(ErrorCode.SOURCE_CONFLICT)
    first = snapshots[0]
    by_source = {s.source_id: s for s in registry.sources}
    if {s.source_id for s in snapshots} != set(by_source) or len(snapshots) != len(by_source):
        raise DomainError(ErrorCode.SOURCE_CONFLICT)
    features: dict[str, FeatureValue] = {}
    coverage: list[SourceCoverage] = []
    for item in sorted(snapshots, key=lambda snapshot: snapshot.source_id):
        source = by_source[item.source_id]
        if item.account_id != first.account_id or item.snapshot_at != first.snapshot_at:
            raise DomainError(ErrorCode.IDENTITY_CONFLICT)
        if (item.observation_start, item.observation_cutoff) != (
            first.observation_start,
            first.observation_cutoff,
        ):
            raise DomainError(ErrorCode.CUTOFF_MISMATCH)
        if (
            item.observation_cutoff != item.snapshot_at
            or source.contract_version != item.source_contract_version
        ):
            raise DomainError(ErrorCode.CUTOFF_MISMATCH)
        if set(item.features) != set(source.feature_ids) or set(features).intersection(
            item.features
        ):
            raise DomainError(ErrorCode.SOURCE_CONFLICT)
        if source.approval_reference != item.identity_approval_reference:
            raise DomainError(ErrorCode.SOURCE_CONFLICT)
        partitions = [coverage.source_partition for coverage in item.source_coverage]
        if len(partitions) != len(set(partitions)) or set(partitions) != set(
            source.required_partitions
        ):
            raise DomainError(ErrorCode.COMPLETENESS_INVALID)
        features.update(item.features)
        coverage.extend(item.source_coverage)
    return JoinedSnapshot(
        account_id=first.account_id,
        snapshot_at=first.snapshot_at,
        source_snapshot_ids=tuple(
            item.snapshot_id for item in sorted(snapshots, key=lambda snapshot: snapshot.source_id)
        ),
        features=features,
        source_coverage=tuple(coverage),
        completeness="COMPLETE" if all(c.status == "COMPLETE" for c in coverage) else "INCOMPLETE",
    )
