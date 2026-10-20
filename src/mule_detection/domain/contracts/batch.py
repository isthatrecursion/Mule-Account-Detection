from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator

from mule_detection.domain.contracts.common import (
    Contract,
    Digest,
    Nonnegative,
    Text,
    UtcTime,
    violation,
)
from mule_detection.domain.errors import ErrorCode


class BatchManifest(Contract):
    VERSION = "batch_manifest_v1"
    contract_version: Literal["batch_manifest_v1"]
    batch_id: UUID
    source_id: Text
    schema_id: Literal["research_v1", "qualified_snapshot_v1", "synthetic_snapshot_v1"]
    created_at: UtcTime
    observation_cutoff: UtcTime | None
    expected_row_count: Nonnegative
    checksum: Digest
    feature_policy_version: Text
    data_tier: Literal["research", "qualified", "synthetic"]
    owner_reference: Text
    producing_job: Text
    provenance_limitations: tuple[Text, ...]

    @model_validator(mode="after")
    def provenance(self) -> Self:
        tiers = {
            "research_v1": "research",
            "qualified_snapshot_v1": "qualified",
            "synthetic_snapshot_v1": "synthetic",
        }
        if tiers[self.schema_id] != self.data_tier:
            raise violation(ErrorCode.CONTRACT_INVALID)
        if self.data_tier == "qualified" and self.observation_cutoff is None:
            raise violation(ErrorCode.CUTOFF_MISMATCH)
        if self.observation_cutoff and self.observation_cutoff > self.created_at:
            raise violation(ErrorCode.CUTOFF_MISMATCH)
        if self.data_tier == "research" and not self.provenance_limitations:
            raise violation(ErrorCode.CONTRACT_INVALID)
        return self
