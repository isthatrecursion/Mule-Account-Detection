"""Hash-bound research adapter. No training, holdout scoring, or account certification."""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from mule_detection.domain.contracts.common import parse_contract
from mule_detection.domain.contracts.snapshot import FeatureValue
from mule_detection.domain.contracts.tabular import ColumnRule, TabularSchema
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.domain.feature_policy import FeaturePolicy
from mule_detection.domain.identity import research_record_key
from mule_detection.settings import read_yaml


def file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def parse_cell(raw: str, rule: ColumnRule, missing_tokens: tuple[str, ...]) -> FeatureValue:
    if raw in missing_tokens:
        if rule.missing == "forbidden":
            raise DomainError(ErrorCode.VALUE_INVALID)
        return None
    if rule.logical_type == "categorical":
        return raw
    try:
        if rule.logical_type == "integer":
            # Integer columns cannot silently round floating-point identifiers or counts.
            import re

            if not re.fullmatch(r"-?[0-9]+", raw):
                raise ValueError
            return int(raw)
        value = float(raw)
        if not np.isfinite(value):
            raise ValueError
        return value
    except ValueError:
        raise DomainError(ErrorCode.VALUE_INVALID) from None


@dataclass(frozen=True)
class RestrictedLineage:
    original_reference: int
    extraction_month: str | None


@dataclass(frozen=True)
class ResearchBatch:
    record_keys: tuple[str, ...]
    predictors: Mapping[str, NDArray[Any]] = field(repr=False)
    logical_types: Mapping[str, str]
    labels: NDArray[Any] = field(repr=False)
    restricted_lineage: tuple[RestrictedLineage, ...] = field(repr=False)
    dataset_sha256: str
    split_sha256: str
    feature_policy_hash: str
    excluded_holdout_count: int
    data_tier: Literal["research"] = field(default="research", init=False)
    account_id: None = field(default=None, init=False)
    observation_cutoff: None = field(default=None, init=False)
    provenance_limitation: str = field(
        default="Historical account identity, cutoff, event provenance and label maturity are unverified",
        init=False,
    )


@dataclass(frozen=True)
class ResearchAdapter:
    # Constructed by trusted application configuration, never a client-provided expected hash.
    schema: TabularSchema
    feature_policy: FeaturePolicy
    trusted_dataset_sha256: str
    trusted_split_sha256: str
    expected_development_rows: int

    @classmethod
    def from_repository(cls, root: Path) -> ResearchAdapter:
        import json

        reference = json.loads((root / "docs/reference_manifest.json").read_text(encoding="utf-8"))
        hashes = reference["reference_environment"]["input_sha256"]
        adapter = cls(
            parse_contract(
                TabularSchema, read_yaml(root / "config/schema_registry/research_v1.yaml")
            ),
            parse_contract(FeaturePolicy, read_yaml(root / "config/feature_policy.yaml")),
            hashes["dataset"],
            hashes["split_register"],
            7265,
        )
        if adapter.feature_policy.historical_register_sha256 != hashes["exclusion_register"]:
            raise DomainError(ErrorCode.HASH_MISMATCH)
        return adapter

    def adapt(self, dataset: Path, split_register: Path) -> ResearchBatch:
        before = (file_digest(dataset), file_digest(split_register))
        if before != (self.trusted_dataset_sha256, self.trusted_split_sha256):
            raise DomainError(ErrorCode.HASH_MISMATCH)
        with split_register.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.reader(stream)
            if next(reader, []) != ["account_id", "split", "target"]:
                raise DomainError(ErrorCode.SPLIT_MISMATCH)
            splits = list(reader)
        feature_rules = [rule for rule in self.schema.columns if rule.role == "predictor"]
        self.feature_policy.assert_predictors([rule.name for rule in feature_rules])
        values: dict[str, list[FeatureValue]] = {rule.name: [] for rule in feature_rules}
        keys: list[str] = []
        labels: list[int] = []
        lineage: list[RestrictedLineage] = []
        seen: set[int] = set()
        holdout_count = 0
        row_count = 0
        with dataset.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.reader(stream)
            header = self.schema.validate_header(next(reader, []))
            for index, cells in enumerate(reader):
                row_count += 1
                if len(cells) != len(header) or index >= len(splits) or len(splits[index]) != 3:
                    raise DomainError(ErrorCode.SPLIT_MISMATCH)
                raw = dict(zip(header, cells, strict=True))
                split_reference, partition, split_label = splits[index]
                if (
                    raw["Unnamed: 0"] != split_reference
                    or raw["F3924"] != split_label
                    or partition not in ("dev", "holdout")
                    or split_label not in ("0", "1")
                ):
                    raise DomainError(ErrorCode.SPLIT_MISMATCH)
                key = research_record_key(before[0], split_reference)
                reference = int(split_reference)
                if reference in seen:
                    raise DomainError(ErrorCode.IDENTITY_CONFLICT)
                seen.add(reference)
                if partition == "holdout":
                    holdout_count += 1
                    continue
                parsed = {
                    rule.name: parse_cell(raw.get(rule.name, ""), rule, self.schema.missing_tokens)
                    for rule in self.schema.columns
                }
                for rule in feature_rules:
                    values[rule.name].append(parsed[rule.name])
                keys.append(key)
                labels.append(int(split_label))
                month = parsed["F2230"]
                lineage.append(
                    RestrictedLineage(reference, str(month) if month is not None else None)
                )
        if row_count != len(splits) or len(keys) != self.expected_development_rows:
            raise DomainError(ErrorCode.SPLIT_MISMATCH)
        if (file_digest(dataset), file_digest(split_register)) != before:
            raise DomainError(ErrorCode.HASH_MISMATCH)
        arrays: dict[str, NDArray[Any]] = {}
        for rule in feature_rules:
            column = values.pop(rule.name)
            dtype: Any = object
            if rule.logical_type == "number":
                dtype = np.float64
            elif rule.logical_type == "integer" and all(
                isinstance(value, int) and -(2**63) <= value < 2**63 for value in column
            ):
                dtype = np.int64
            # Nullable/out-of-range integers stay exact Python integers plus None, never float-rounded.
            array = np.asarray(column, dtype=dtype)
            array.setflags(write=False)
            arrays[rule.name] = array
        label_array = np.asarray(labels, dtype=np.int8)
        label_array.setflags(write=False)
        return ResearchBatch(
            tuple(keys),
            MappingProxyType(arrays),
            MappingProxyType({rule.name: rule.logical_type for rule in feature_rules}),
            label_array,
            tuple(lineage),
            before[0],
            before[1],
            self.feature_policy.fingerprint,
            holdout_count,
        )
