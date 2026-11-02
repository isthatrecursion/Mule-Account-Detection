"""Factual anonymous-field evidence with training-only reference statistics."""

import math
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.explanations.contributions import contributions
from mule_detection.training.model_factory import FittedCandidate


def build_evidence(fitted: FittedCandidate, frame: Any) -> list[dict[str, Any]]:
    output = contributions(fitted, frame)
    mask = fitted.features.missing_mask(frame)
    references = fitted.features.reference_statistics_
    results = []
    for row, (_, observed) in enumerate(frame.iterrows()):
        aggregates: dict[str, float] = {}
        encoded = []
        for item, value in zip(output["mapping"], output["values"][row], strict=True):
            raw = item["raw_feature"]
            aggregates[raw] = aggregates.get(raw, 0.0) + value
            encoded.append({**item, "contribution": value})
        facts = []
        for raw, value in aggregates.items():
            derived = raw not in frame.columns
            imputed = not derived and bool(mask.iloc[row][raw])
            observed_value = None if derived or imputed else observed[raw]
            if isinstance(observed_value, np.generic):
                observed_value = observed_value.item()
            if observed_value is not None and pd.isna(observed_value):
                observed_value = None
            fact: dict[str, Any] = {
                "raw_feature": raw,
                "display_name": raw,
                "meaning_status": "UNVERIFIED",
                "observed_value": observed_value,
                "value_status": "DERIVED" if derived else "IMPUTED" if imputed else "OBSERVED",
                "contribution": value,
                "reference_percentile": None,
                "category_frequency": None,
                "unseen_category": None,
            }
            reference = references.get(raw)
            if observed_value is not None and reference:
                if reference["kind"] == "numeric" and isinstance(observed_value, (int, float)):
                    denominator = sum(reference["counts"])
                    fact["reference_percentile"] = (
                        (
                            100.0
                            * sum(
                                n
                                for v, n in zip(
                                    reference["values"], reference["counts"], strict=True
                                )
                                if v <= observed_value
                            )
                            / denominator
                        )
                        if denominator
                        else None
                    )
                elif reference["kind"] == "categorical":
                    frequency = reference["counts"].get(str(observed_value), 0)
                    fact["category_frequency"] = frequency / reference["training_rows"]
                    fact["unseen_category"] = frequency == 0
            facts.append(fact)
        base = float(output["base_values"][row])
        margin = float(output["raw_margins"][row])
        if not math.isclose(base + sum(aggregates.values()), margin, abs_tol=1e-8, rel_tol=1e-8):
            raise DomainError(ErrorCode.SCORE_STATE_INVALID)
        results.append(
            {
                "evidence_version": "factual_contributions_v1",
                "scale": output["scale"],
                "method": output["method"],
                "base_value": base,
                "raw_margin": margin,
                "encoded_detail": encoded,
                "raw_aggregates": facts,
                "positive": sorted(
                    (v for v in facts if v["contribution"] > 0),
                    key=lambda v: (-v["contribution"], v["raw_feature"]),
                )[:5],
                "negative": sorted(
                    (v for v in facts if v["contribution"] < 0),
                    key=lambda v: (v["contribution"], v["raw_feature"]),
                )[:5],
                "interpretation": "MODEL_ASSOCIATION_ONLY_NOT_CAUSAL_OR_CERTIFIED_BEHAVIOR",
            }
        )
    return results
