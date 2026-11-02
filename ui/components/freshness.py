"""Freshness is independent of score magnitude and understandable without color."""

from typing import Any

import streamlit as st

from ui.components.badges import render_badge
from ui.components.score import score_values
from ui.components.time_fmt import format_time
from ui.enums import Freshness, PublicationEvent

LABELS = {
    "COMPLETE": "Complete assessment — required source coverage is complete.",
    "BUFFERING": "Buffering — late or incomplete source data is awaiting reconciliation.",
    "PROVISIONAL_HIGHER": "Provisional escalation — pending reconciliation; retained complete assessment remains authoritative.",
    "STALE": "Stale assessment — its original cutoff is retained; freshness is not established.",
    "UNAVAILABLE": "Assessment unavailable — no usable published score. Check source status before interpretation.",
}


def freshness_text(state: str, cutoff: Any = None, timezone: str = "UTC") -> str:
    return (
        "["
        + Freshness(state).value
        + "] "
        + LABELS.get(state, "Unknown assessment status — no score is implied.")
        + " Assessed as of: "
        + format_time(cutoff, timezone)
        + "."
    )


def render(score: dict[str, Any], timezone: str = "UTC") -> None:
    state = str(score.get("freshness") or "UNAVAILABLE")
    message = freshness_text(state, score.get("assessed_as_of"), timezone)
    (st.info if state == "COMPLETE" else st.warning)(message)
    if score.get("publication_event"):
        render_badge("Publication event", PublicationEvent(score["publication_event"]))
    if score.get("reason"):
        st.text("Source reason: " + str(score["reason"]))
    with st.expander("Source coverage details"):
        st.caption("Source completeness: " + str(score.get("completeness") or "UNKNOWN"))
        if score.get("source_coverage"):
            coverage = [
                {
                    key: format_time(value, timezone)
                    if key in {"window_start", "window_end", "complete_through", "heartbeat_at"}
                    else value
                    for key, value in row.items()
                }
                for row in score["source_coverage"]
            ]
            st.table(coverage, hide_index=True, width="stretch")
    if state == "PROVISIONAL_HIGHER":
        st.text(
            "Authoritative baseline score: " + str(score.get("baseline_score_id") or "Not supplied")
        )


def display_score(score: dict[str, Any]) -> str:
    return score_values(
        score.get("raw_score"),
        score.get("rank"),
        score.get("percentile"),
        str(score.get("freshness", "UNKNOWN")),
    )[0]
