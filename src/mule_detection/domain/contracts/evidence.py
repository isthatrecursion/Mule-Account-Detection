from typing import Literal, Self
from uuid import UUID

from pydantic import Field, StrictFloat, model_validator

from mule_detection.domain.contracts.common import Contract, Text, ValueModel, violation
from mule_detection.domain.contracts.feature_dictionary import FeatureDictionary
from mule_detection.domain.contracts.models import ModelBundle
from mule_detection.domain.contracts.snapshot import FeatureValue
from mule_detection.domain.errors import DomainError, ErrorCode


class Observation(ValueModel):
    feature_id: Text
    raw_value: FeatureValue
    contribution: StrictFloat
    direction: Literal["POSITIVE", "NEGATIVE", "ZERO"]
    reference_percentile: StrictFloat | None = Field(ge=0, le=100)
    dictionary_status: Literal["UNVERIFIED", "PROVISIONAL", "CERTIFIED"]
    display_name: Text

    @model_validator(mode="after")
    def truthful_display(self) -> Self:
        direction = (
            "POSITIVE" if self.contribution > 0 else "NEGATIVE" if self.contribution < 0 else "ZERO"
        )
        if self.direction != direction:
            raise violation(ErrorCode.LINEAGE_INVALID)
        if self.dictionary_status != "CERTIFIED" and self.display_name != self.feature_id:
            raise violation(ErrorCode.DICTIONARY_UNCERTIFIED)
        return self


class Evidence(Contract):
    VERSION = "evidence_v1"
    contract_version: Literal["evidence_v1"]
    evidence_id: UUID
    record_key: Text
    bundle_id: UUID
    dictionary_version: Text
    contribution_scale: Literal["raw_margin", "review_priority", "calibrated_probability"]
    base_value: StrictFloat
    reference_context: Text
    observations: tuple[Observation, ...]


def validate_evidence(
    evidence: Evidence, dictionary: FeatureDictionary, bundle: ModelBundle
) -> None:
    if (
        evidence.bundle_id != bundle.bundle_id
        or evidence.contribution_scale != bundle.contribution_scale
        or evidence.dictionary_version != bundle.dictionary_version
        or evidence.dictionary_version != dictionary.dictionary_version
    ):
        raise DomainError(ErrorCode.LINEAGE_INVALID)
    entries = {entry.feature_id: entry for entry in dictionary.entries}
    for observation in evidence.observations:
        entry = entries.get(observation.feature_id)
        status = entry.status if entry else "UNVERIFIED"
        if (
            observation.dictionary_status != status
            or observation.display_name != dictionary.display(observation.feature_id)
        ):
            raise DomainError(ErrorCode.DICTIONARY_UNCERTIFIED)
