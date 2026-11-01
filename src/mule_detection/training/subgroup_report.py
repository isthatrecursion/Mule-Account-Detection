"""Approved group reporting with explicit denominators and uncertainty limits."""

import hashlib
import json
from typing import Any

from mule_detection.training.metrics import bootstrap_intervals, ranking_metrics


def subgroup_report(
    keys: list[str],
    labels: Any,
    scores: Any,
    groups: dict[str, str],
    *,
    approval_reference: str | None,
    minimum_rows: int,
    minimum_positives: int,
    k: int,
    seed: int,
    research: bool,
) -> dict[str, Any]:
    if not approval_reference or not groups:
        return {
            "status": "BLOCKED",
            "reason": "APPROVED_GROUP_DEFINITIONS_UNAVAILABLE",
            "fairness_certified": False,
        }
    ordered = sorted(range(len(keys)), key=lambda i: (-float(scores[i]), keys[i]))[
        : min(k, len(keys))
    ]
    selected = {keys[i] for i in ordered}
    slices = []
    for group in sorted(set(groups.values())):
        indices = [i for i, key in enumerate(keys) if groups.get(key) == group]
        group_keys = [keys[i] for i in indices]
        metric = ranking_metrics(
            group_keys, [labels[i] for i in indices], [scores[i] for i in indices], (k,)
        )
        insufficient = len(indices) < minimum_rows or metric["positives"] < minimum_positives
        row: dict[str, Any] = {
            "group": group,
            "rows": len(indices),
            "positives": metric["positives"],
            "selected_in_global_queue": len(selected.intersection(group_keys)),
            "status": "INCONCLUSIVE_SMALL_SAMPLE"
            if insufficient
            else "INCONCLUSIVE_CONFOUNDING"
            if research
            else "REVIEW_REQUIRED",
            "metrics": None if insufficient else metric,
        }
        if not insufficient:
            row["uncertainty"] = bootstrap_intervals(
                group_keys,
                [labels[i] for i in indices],
                [scores[i] for i in indices],
                group_keys,
                repetitions=100,
                seed=seed,
                ks=(k,),
            )
        slices.append(row)
    return {
        "status": "INCONCLUSIVE" if research else "REVIEW_REQUIRED",
        "approval_reference": approval_reference,
        "group_definition_hash": hashlib.sha256(
            json.dumps(groups, sort_keys=True).encode()
        ).hexdigest(),
        "unmapped_rows": sum(key not in groups for key in keys),
        "slices": slices,
        "fairness_certified": False,
    }
