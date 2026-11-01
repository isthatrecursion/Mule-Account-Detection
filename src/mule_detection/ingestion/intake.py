"""Server-owned source profiles. Client manifests cannot select code or filesystem paths."""

import re
from typing import Literal, Self

from pydantic import Field, model_validator

from mule_detection.domain.contracts.common import Digest, Text, ValueModel
from mule_detection.domain.contracts.tabular import ColumnRule
from mule_detection.domain.validation_policy import IntakeRejected
from mule_detection.ingestion.fingerprints import schema_signature


class SourceProfile(ValueModel):
    source_id: Text
    schema_id: Literal["synthetic_snapshot_v1", "qualified_snapshot_v1", "research_v1"]
    data_tier: Literal["synthetic", "qualified", "research"]
    policy_version: Text
    access_scope: Text
    columns: tuple[ColumnRule, ...]
    identity_columns: tuple[Text, ...]
    missing_tokens: tuple[str, ...] = ("",)
    certified: bool = False
    required_source_columns: tuple[Text, ...] = ()
    cutoff_column: str | None = None
    availability_column: str | None = None
    snapshot_column: str | None = None
    certified_ranges: dict[str, tuple[float, float]] = Field(default_factory=dict)
    approved_categories: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    expected_dataset_hash: Digest | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        names = [c.name for c in self.columns]
        if len(set(names)) != len(names) or not self.identity_columns:
            raise ValueError("Invalid server profile")
        refs = set(self.identity_columns) | set(self.required_source_columns)
        refs |= {
            c for c in (self.cutoff_column, self.availability_column, self.snapshot_column) if c
        }
        if not refs <= set(names) or any(not c.required for c in self.columns if c.name in refs):
            raise ValueError("Profile references must name required columns")
        if any(c.role == "predictor" for c in self.columns if c.name in refs):
            raise ValueError("Identity, source and time metadata cannot be predictors")
        if self.schema_id != f"{self.data_tier}_snapshot_v1" and self.schema_id != "research_v1":
            raise ValueError("Profile tier mismatch")
        if self.schema_id == "research_v1" and self.data_tier != "research":
            raise ValueError("Profile tier mismatch")
        if self.data_tier == "qualified" and not all(
            (
                self.cutoff_column,
                self.availability_column,
                self.snapshot_column,
                self.required_source_columns,
                self.certified,
            )
        ):
            raise ValueError("Qualified profiles require certified temporal/source rules")
        if self.certified_ranges and not self.certified:
            raise ValueError("Uncertified range rules are forbidden")
        if any(lo > hi for lo, hi in self.certified_ranges.values()):
            raise ValueError("Invalid certified range")
        predictors = {c.name for c in self.columns if c.role == "predictor"}
        numeric = {c.name for c in self.columns if c.logical_type in {"number", "integer"}}
        if not set(self.certified_ranges) <= predictors & numeric:
            raise ValueError("Certified ranges must name numeric predictors")
        if not set(self.approved_categories) <= predictors:
            raise ValueError("Category rules must name predictors")
        return self

    @property
    def signature(self) -> str:
        return schema_signature([(c.name, c.logical_type) for c in self.columns])


def safe_filename(value: str) -> str:
    # Display metadata only. The value is never used as a storage name.
    name = value.replace("\\", "/").split("/")[-1]
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", name)[:100] or "upload.csv"


def check_format(value: str) -> None:
    if value != "csv":
        raise IntakeRejected("UNSUPPORTED_FORMAT")
