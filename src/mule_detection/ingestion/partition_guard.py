"""Server-bound development membership is checked again at worker boundaries."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mule_detection.domain.validation_policy import IntakeRejected
from mule_detection.ingestion.research_adapter import ResearchAdapter, ResearchBatch


@dataclass(frozen=True)
class PartitionGuard:
    dataset_hash: str
    split_hash: str
    _development: frozenset[str] = field(repr=False)

    @classmethod
    def from_verified(cls, batch: ResearchBatch) -> "PartitionGuard":
        return cls(batch.dataset_sha256, batch.split_sha256, frozenset(batch.record_keys))

    def assert_development(self, keys: Sequence[str], dataset_hash: str, split_hash: str) -> None:
        if (
            dataset_hash != self.dataset_hash
            or split_hash != self.split_hash
            or len(keys) != len(set(keys))
            or not set(keys) <= self._development
        ):
            raise IntakeRejected("RESEARCH_PARTITION_FORBIDDEN")


def development_batch(
    adapter: ResearchAdapter, dataset: Path, trusted_split: Path
) -> tuple[ResearchBatch, PartitionGuard]:
    batch = adapter.adapt(dataset, trusted_split)
    guard = PartitionGuard.from_verified(batch)
    guard.assert_development(batch.record_keys, batch.dataset_sha256, batch.split_sha256)
    adapter.feature_policy.assert_predictors(list(batch.predictors))
    return batch, guard
