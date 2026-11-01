"""Authorized-subset aggregates. Unknown category values and labels are never public samples."""

import math
from collections import Counter
from typing import Any

from mule_detection.ingestion.intake import SourceProfile
from mule_detection.ingestion.validator import CheckedBatch


def missing(value: object) -> bool:
    return value is None or isinstance(value, float) and math.isnan(value)


def quality_report(
    checked: CheckedBatch, profile: SourceProfile, *, training_diagnostics: bool = False
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for column in profile.columns:
        if column.role != "predictor":
            continue
        values = [r.get(column.name) for r in checked.records]
        observed = [v for v in values if not missing(v)]
        allowed = profile.approved_categories.get(column.name, ())
        fields[column.name] = {
            "missing": len(values) - len(observed),
            "type_errors": checked.type_errors.get(column.name, 0),
            "constant": bool(observed) and len(set(observed)) == 1,
            "zero": int(sum(v == 0 for v in observed)),
            "approved_category_counts": {c: observed.count(c) for c in allowed},
            "unknown_category_count": sum(v not in allowed for v in observed) if allowed else 0,
        }
    report: dict[str, Any] = {
        "version": "quality_v1",
        "authorized_rows": len(checked.records),
        "fields": fields,
        "type_error_count": sum(
            f.count for f in checked.findings if f.rule_id == "CELL_TYPE_OR_MISSING"
        ),
        "source_coverage": "certified" if profile.certified else "unverified",
        "split_hash": checked.split_hash,
    }
    report["table"] = [{"field": name, **values} for name, values in fields.items()]
    if training_diagnostics and checked.labels:
        groups: dict[str, Any] = {}
        for cohort in sorted(set(checked.cohort)):
            indices = [i for i, value in enumerate(checked.cohort) if value == cohort]
            groups[cohort] = {
                "class_counts": dict(Counter(str(checked.labels[i]) for i in indices)),
                "missing_by_field": {
                    name: sum(missing(checked.records[i].get(name)) for i in indices)
                    for name in fields
                },
            }
        report["restricted_training_diagnostics"] = groups
    return report
