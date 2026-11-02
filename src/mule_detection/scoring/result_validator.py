"""Fail closed before ranking or publication."""

import math
from collections.abc import Iterable

from mule_detection.domain.errors import DomainError, ErrorCode


def collect_scores(
    rows: Iterable[tuple[str, float]], expected: tuple[str, ...]
) -> dict[str, float]:
    scores = {}
    for key, score in rows:
        if key in scores:
            raise DomainError(ErrorCode.IDENTITY_CONFLICT)
        scores[key] = score
    validate_scores(scores, expected)
    return scores


def validate_scores(scores: dict[str, float], expected: tuple[str, ...]) -> None:
    if len(expected) != len(set(expected)) or set(scores) != set(expected):
        raise DomainError(ErrorCode.COUNT_INVALID)
    if any(
        type(v) not in {int, float} or not math.isfinite(v) or not 0 <= v <= 1
        for v in scores.values()
    ):
        raise DomainError(ErrorCode.SCORE_STATE_INVALID)
