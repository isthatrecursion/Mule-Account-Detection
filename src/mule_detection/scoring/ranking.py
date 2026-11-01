"""Versioned global ranking; percentiles describe cohort position only."""

from dataclasses import dataclass
from typing import Any

from mule_detection.domain.contracts.common import canonical_hash
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.settings import read_yaml


@dataclass(frozen=True)
class ReviewPolicy:
    version: str
    digest: str
    top_k: int
    sort_version: str = "score_desc_key_asc_v1"

    @classmethod
    def load(cls, path: Any) -> "ReviewPolicy":
        value = read_yaml(path)
        if (
            value.get("sort") != ["raw_score_desc", "record_key_asc"]
            or value.get("percentile", {}).get("formula") != "100 * (N - rank) / (N - 1)"
            or value.get("percentile", {}).get("singleton") != 100
            or type(value.get("top_k")) is not int
            or not 1 <= value["top_k"] <= 500
        ):
            raise DomainError(ErrorCode.CONFIGURATION_INVALID)
        return cls(value["policy_version"], canonical_hash(value), value["top_k"])


def rank_scores(scores: dict[str, float], policy: ReviewPolicy) -> list[dict[str, Any]]:
    from mule_detection.scoring.result_validator import validate_scores

    validate_scores(scores, tuple(scores))
    size = len(scores)
    return [
        {
            "record_key": key,
            "raw_score": float(value),
            "rank": rank,
            "percentile": 100.0 if size == 1 else 100.0 * (size - rank) / (size - 1),
            "cohort_size": size,
            "selected": rank <= min(policy.top_k, size),
            "sort_policy": policy.sort_version,
        }
        for rank, (key, value) in enumerate(
            sorted(scores.items(), key=lambda item: (-item[1], item[0])), 1
        )
    ]
