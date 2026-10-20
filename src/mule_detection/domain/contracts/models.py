from typing import Literal, Self
from uuid import UUID

from pydantic import StrictBool, model_validator

from mule_detection.domain.contracts.common import Contract, Digest, Text, violation
from mule_detection.domain.errors import ErrorCode


class ModelBundle(Contract):
    VERSION = "model_bundle_v1"
    contract_version: Literal["model_bundle_v1"]
    bundle_id: UUID
    artifact_digests: dict[Text, Digest]
    input_signature: Digest
    transformed_signature: Digest
    training_fingerprint: Digest
    feature_policy_version: Text
    feature_policy_hash: Digest
    runtime_versions: dict[Text, Text]
    output_scale: Literal["raw_margin", "review_priority", "calibrated_probability"]
    contribution_scale: Literal["raw_margin", "review_priority", "calibrated_probability"]
    research_only: StrictBool
    model_tier: Literal["research_demo", "candidate"]
    model_card_reference: Text
    dictionary_version: Text
    calibration_approval_reference: Text | None

    @model_validator(mode="after")
    def bundle_rules(self) -> Self:
        if (
            not {"model", "pipeline", "peer_reference", "model_card"}
            <= self.artifact_digests.keys()
            or not self.runtime_versions
        ):
            raise violation(ErrorCode.LINEAGE_INVALID)
        if self.research_only != (self.model_tier == "research_demo"):
            raise violation(ErrorCode.LINEAGE_INVALID)
        if self.output_scale == "calibrated_probability" and (
            self.research_only or not self.calibration_approval_reference
        ):
            raise violation(ErrorCode.LINEAGE_INVALID)
        return self
