from typing import Literal, Self

from pydantic import StrictBool, model_validator

from mule_detection.domain.contracts.common import Contract, Digest, Text, ValueModel, violation
from mule_detection.domain.errors import DomainError, ErrorCode


class ColumnRule(ValueModel):
    name: Text
    logical_type: Literal["number", "integer", "categorical"]
    role: Literal["predictor", "label", "lineage", "forbidden"]
    required: StrictBool
    missing: Literal["imputable", "forbidden"]


class TabularSchema(Contract):
    VERSION = "tabular_schema_v1"
    contract_version: Literal["tabular_schema_v1"]
    schema_id: Literal["research_v1"]
    source_dictionary_sha256: Digest
    raw_header_aliases: dict[str, Text]
    reorder: Literal["canonicalize_to_registry_order"]
    missing_tokens: tuple[str, ...]
    columns: tuple[ColumnRule, ...]

    @model_validator(mode="after")
    def roles_and_names(self) -> Self:
        names = [rule.name for rule in self.columns]
        if len(names) != len(set(names)):
            raise violation(ErrorCode.SCHEMA_MISMATCH)
        if any(
            alias != "" or canonical != "Unnamed: 0"
            for alias, canonical in self.raw_header_aliases.items()
        ):
            raise violation(ErrorCode.SCHEMA_MISMATCH)
        by_name = {rule.name: rule for rule in self.columns}
        if any(name not in by_name for name in ("Unnamed: 0", "F3924", "F2230")):
            raise violation(ErrorCode.SCHEMA_MISMATCH)
        if (
            by_name["F3924"].role != "label"
            or by_name["Unnamed: 0"].role != "lineage"
            or by_name["F2230"].role != "lineage"
        ):
            raise violation(ErrorCode.FEATURE_FORBIDDEN)
        return self

    def validate_header(self, header: list[str]) -> list[str]:
        header = [self.raw_header_aliases.get(name, name) for name in header]
        expected = {c.name for c in self.columns}
        required = {c.name for c in self.columns if c.required}
        if (
            len(header) != len(set(header))
            or not required <= set(header)
            or not set(header) <= expected
        ):
            raise DomainError(ErrorCode.SCHEMA_MISMATCH)
        return header
