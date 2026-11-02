"""Explicit immutable model identity; replay creates a new linked logical run."""

from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator

from mule_detection.domain.contracts.common import Contract, Digest, Text


class ScoringRequest(Contract):
    VERSION = "scoring_request_v1"
    contract_version: Literal["scoring_request_v1"] = "scoring_request_v1"
    batch_id: UUID
    bundle_digest: Digest
    environment: Literal["local", "test", "research", "staging", "qualified"]
    replay_id: UUID | None = None
    replay_of: UUID | None = None
    affected_keys: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def linked_replay(self) -> Self:
        if (self.replay_id is None) != (self.replay_of is None):
            raise ValueError("Replay identity and predecessor must be supplied together")
        if self.affected_keys and (
            self.replay_of is None or len(set(self.affected_keys)) != len(self.affected_keys)
        ):
            raise ValueError(
                "Correction requires unique affected keys and an explicit predecessor/event"
            )
        return self
