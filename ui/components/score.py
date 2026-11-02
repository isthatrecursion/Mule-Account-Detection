"""Missing/unknown assessment values never become zero or reassuring scores."""

import math

import streamlit as st

from ui.copy import LABELS
from ui.enums import Freshness


def score_values(
    raw_score: float | None,
    rank: int | None,
    percentile: float | None,
    freshness: str,
    cohort_size: int | None = None,
) -> tuple[str, str, str]:
    if Freshness(freshness) in {Freshness.UNAVAILABLE, Freshness.UNKNOWN}:
        return "—", "—", "—"
    score = f"{raw_score:.6g}" if raw_score is not None and math.isfinite(raw_score) else "—"
    ranked = str(rank) if rank is not None and rank > 0 else "—"
    position = (
        f"{percentile:.2f}"
        if percentile is not None
        and math.isfinite(percentile)
        and 0 <= percentile <= 100
        and cohort_size != 0
        else "—"
    )
    return score, ranked, position


def render_score(
    raw_score: float | None,
    rank: int | None,
    percentile: float | None,
    freshness: str,
    cohort_size: int | None = None,
) -> None:
    values = score_values(raw_score, rank, percentile, freshness, cohort_size)
    columns = st.columns(3)
    for column, label, value in zip(
        columns, (LABELS["score"], "Rank", "Cohort percentile"), values, strict=True
    ):
        column.metric(label, value)
    st.caption(LABELS["percentile"])
    if Freshness(freshness) in {Freshness.UNAVAILABLE, Freshness.UNKNOWN}:
        st.warning(LABELS["unavailable"])
