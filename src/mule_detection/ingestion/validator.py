"""Stable rule phases: schema, identity/count/type, then time/source/feature separation."""

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mule_detection.domain.contracts.batch import BatchManifest
from mule_detection.domain.contracts.common import Digest, Nonnegative, ValueModel, utc
from mule_detection.domain.errors import DomainError
from mule_detection.domain.feature_policy import FeaturePolicy
from mule_detection.domain.validation_policy import (
    Finding,
    IntakeRejected,
    error,
    promotion_blockers,
)
from mule_detection.ingestion.intake import SourceProfile
from mule_detection.ingestion.partition_guard import development_batch
from mule_detection.ingestion.research_adapter import ResearchAdapter, parse_cell


class DeclaredBatch(ValueModel):
    manifest: BatchManifest
    byte_count: Nonnegative
    logical_schema_signature: Digest


@dataclass
class CheckedBatch:
    findings: list[Finding]
    row_count: int = 0
    signature: str | None = None
    records: list[dict[str, Any]] = field(default_factory=list, repr=False)
    labels: list[object] = field(default_factory=list, repr=False)
    cohort: list[str] = field(default_factory=list, repr=False)
    split_hash: str | None = None
    type_errors: dict[str, int] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return not any(f.severity == "ERROR" for f in self.findings)


def validate(
    path: Path,
    declaration: DeclaredBatch,
    profile: SourceProfile,
    policy: FeaturePolicy,
    *,
    digest: str,
    byte_count: int,
    max_rows: int,
    research_adapter: ResearchAdapter | None = None,
    split_path: Path | None = None,
) -> CheckedBatch:
    manifest = declaration.manifest
    result = CheckedBatch([])
    if (
        manifest.schema_id != profile.schema_id
        or manifest.source_id != profile.source_id
        or manifest.data_tier != profile.data_tier
        or manifest.feature_policy_version != profile.policy_version
        or profile.policy_version != policy.policy_version
        or declaration.logical_schema_signature != profile.signature
    ):
        result.findings.append(error("SCHEMA_VERSION_MISMATCH"))
        return result
    try:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, [])
            if profile.data_tier == "research" and research_adapter:
                header = research_adapter.schema.validate_header(header)
            names = [c.name for c in profile.columns]
            if len(set(header)) != len(header) or set(header) != set(names):
                result.findings.append(error("SCHEMA_HEADER"))
                return result
            result.signature = profile.signature
            raw_rows: list[dict[str, str]] = []
            for cells in reader:
                result.row_count += 1
                if result.row_count > max_rows:
                    raise IntakeRejected("ROW_LIMIT")
                if len(cells) != len(header):
                    raise IntakeRejected("CSV_SHAPE")
                raw_rows.append(dict(zip(header, cells, strict=True)))
    except (UnicodeError, csv.Error):
        result.findings.append(error("CSV_INVALID"))
        return result
    except IntakeRejected as exc:
        result.findings.append(error(exc.code))
        return result
    except DomainError as exc:
        result.findings.append(error(exc.code.value))
        return result
    if (
        digest != manifest.checksum
        or byte_count != declaration.byte_count
        or result.row_count != manifest.expected_row_count
        or (profile.expected_dataset_hash and digest != profile.expected_dataset_hash)
    ):
        result.findings.append(error("MANIFEST_MISMATCH"))
    identities = [tuple(row[c] for c in profile.identity_columns) for row in raw_rows]
    bad = len(identities) - len(set(identities))
    if bad or any(any(not cell for cell in key) for key in identities):
        result.findings.append(error("DUPLICATE_OR_MISSING_IDENTITY", max(bad, 1)))
    if not result.accepted:
        return result
    if profile.data_tier == "research":
        if research_adapter is None or split_path is None:
            result.findings.append(error("TRUSTED_SPLIT_REQUIRED"))
            return result
        try:
            batch, _ = development_batch(research_adapter, path, split_path)
            result.records = [
                {
                    name: values[i].item() if hasattr(values[i], "item") else values[i]
                    for name, values in batch.predictors.items()
                }
                for i in range(len(batch.record_keys))
            ]
            result.labels = batch.labels.tolist()
            result.cohort = [r.extraction_month or "unavailable" for r in batch.restricted_lineage]
            result.split_hash = batch.split_sha256
        except DomainError as exc:
            result.findings.append(error(exc.code.value))
            return result
    else:
        type_errors = 0
        for raw in raw_rows:
            parsed: dict[str, Any] = {}
            for rule in profile.columns:
                try:
                    parsed[rule.name] = parse_cell(raw[rule.name], rule, profile.missing_tokens)
                except DomainError:
                    type_errors += 1
                    result.type_errors[rule.name] = result.type_errors.get(rule.name, 0) + 1
            result.records.append(parsed)
        if type_errors:
            result.findings.append(error("CELL_TYPE_OR_MISSING", type_errors))
            return result
        for raw in raw_rows:
            try:
                cutoff = utc(raw[profile.cutoff_column]) if profile.cutoff_column else None
                available = (
                    utc(raw[profile.availability_column]) if profile.availability_column else None
                )
                snapshot = utc(raw[profile.snapshot_column]) if profile.snapshot_column else None
                if (
                    (cutoff and cutoff != manifest.observation_cutoff)
                    or (available and snapshot and available > snapshot)
                    or (snapshot and snapshot > manifest.created_at)
                    or (cutoff and snapshot and cutoff > snapshot)
                ):
                    raise ValueError
            except (ValueError, DomainError):
                result.findings.append(error("INCOMPATIBLE_TIMESTAMP"))
                break
        if any(
            any(row[c] in profile.missing_tokens for c in profile.required_source_columns)
            for row in raw_rows
        ):
            result.findings.append(error("REQUIRED_SOURCE_UNAVAILABLE"))
        if profile.certified_ranges:
            violations = sum(
                1
                for row in result.records
                for name, (lo, hi) in profile.certified_ranges.items()
                if row.get(name) is not None and not lo <= float(row[name]) <= hi
            )
            if violations:
                result.findings.append(error("CERTIFIED_RANGE", violations))
    predictors = [c.name for c in profile.columns if c.role == "predictor"]
    try:
        policy.assert_predictors(predictors)
    except DomainError:
        result.findings.append(error("FEATURE_LABEL_SEPARATION"))
    if profile.data_tier != "research":
        result.records = [{c: row[c] for c in predictors} for row in result.records]
    for name, categories in profile.approved_categories.items():
        unknown = sum(
            row.get(name) is not None and row.get(name) not in categories for row in result.records
        )
        if unknown:
            result.findings.append(
                Finding(
                    rule_id="APPROVED_CATEGORY_DRIFT",
                    severity="WARNING",
                    count=unknown,
                    remediation="Review category drift with the source owner.",
                )
            )
    result.findings.extend(promotion_blockers(profile.data_tier, profile.certified))
    return result
