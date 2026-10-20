from typing import Literal, Self

from pydantic import model_validator

from mule_detection.domain.contracts.common import Contract, Text, ValueModel, violation
from mule_detection.domain.errors import ErrorCode


class DictionaryEntry(ValueModel):
    feature_id: Text
    status: Literal["UNVERIFIED", "PROVISIONAL", "CERTIFIED"]
    display_name: Text | None
    unit: Text | None
    source_table: Text | None
    calculation_window: Text | None
    availability_rule: Text | None
    sensitivity: Text
    approval_reference: Text | None

    @model_validator(mode="after")
    def certification(self) -> Self:
        if self.status == "CERTIFIED" and any(
            getattr(self, field) is None
            for field in (
                "display_name",
                "unit",
                "source_table",
                "calculation_window",
                "availability_rule",
                "approval_reference",
            )
        ):
            raise violation(ErrorCode.DICTIONARY_UNCERTIFIED)
        return self


class FeatureDictionary(Contract):
    VERSION = "feature_dictionary_v1"
    contract_version: Literal["feature_dictionary_v1"]
    dictionary_version: Text
    known_feature_ids: tuple[Text, ...]
    entries: tuple[DictionaryEntry, ...]

    @model_validator(mode="after")
    def known_entries(self) -> Self:
        ids = [e.feature_id for e in self.entries]
        if len(ids) != len(set(ids)) or len(self.known_feature_ids) != len(
            set(self.known_feature_ids)
        ):
            raise violation(ErrorCode.DICTIONARY_UNCERTIFIED)
        if not set(ids) <= set(self.known_feature_ids):
            raise violation(ErrorCode.DICTIONARY_UNCERTIFIED)
        return self

    def display(self, feature_id: str) -> str:
        for entry in self.entries:
            if (
                entry.feature_id == feature_id
                and entry.status == "CERTIFIED"
                and entry.display_name
            ):
                return entry.display_name
        return feature_id
