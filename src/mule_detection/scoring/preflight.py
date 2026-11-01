"""Accepted research parsing reused with score authority, never training authority."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from mule_detection.application.context import ExecutionContext
from mule_detection.application.training_service import TrainingService
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.training.runner import TrainingInput


@dataclass(frozen=True)
class ResearchPreflight:
    training: TrainingService
    authorize: Any

    def validate_keys(self, keys: tuple[str, ...], dataset_hash: str, split_hash: str) -> None:
        import csv

        from mule_detection.domain.identity import research_record_key
        from mule_detection.ingestion.research_adapter import file_digest

        if (
            dataset_hash != self.training.adapter.trusted_dataset_sha256
            or split_hash != self.training.adapter.trusted_split_sha256
            or file_digest(self.training.split_path) != split_hash
        ):
            raise DomainError(ErrorCode.SPLIT_MISMATCH)
        with self.training.split_path.open(newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.reader(stream))[1:]
        expected = tuple(
            research_record_key(dataset_hash, row[0])
            for row in rows
            if len(row) == 3 and row[1] == "dev"
        )
        if len(keys) != len(set(keys)) or set(keys) != set(expected):
            raise DomainError(ErrorCode.SPLIT_MISMATCH)

    def load(self, batch_id: UUID, context: ExecutionContext) -> tuple[TrainingInput, UUID]:
        source = self.training
        reader = TrainingService(
            source.factory,
            source.raw_store,
            source.store,
            source.adapter,
            source.split_path,
            source.root,
            authorize=lambda ctx, _: self.authorize(ctx, "score:run"),
        )
        data, validation = reader.accepted_input(batch_id, context)
        data.guard.assert_development(data.keys, data.dataset_hash, data.split_hash)
        self.validate_keys(data.keys, data.dataset_hash, data.split_hash)
        return data, validation
