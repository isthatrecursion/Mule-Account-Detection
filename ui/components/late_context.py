"""Freshness context and separate provisional/baseline panels with explicit ages."""

from datetime import UTC, datetime
from typing import Any

import streamlit as st

from ui.components.comparison import render_comparison
from ui.components.score import render_score
from ui.components.time_fmt import format_time
from ui.enums import Freshness
from ui.extensions import ExtensionPayload


def assessment_age(value: str | datetime | None, now: datetime) -> str:
    if value is None:
        return "Age unknown"
    stamp = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if stamp.tzinfo is None or now.tzinfo is None:
        return "Age unknown"
    seconds = (now - stamp).total_seconds()
    return (
        "Timestamp is in the future"
        if seconds < 0
        else f"{int(seconds // 60)} minutes since original assessment"
    )


def render_context(
    score: dict[str, Any],
    context: ExtensionPayload | None,
    timezone: str,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(UTC)
    state = Freshness(score.get("freshness", "UNKNOWN"))
    if state in {Freshness.BUFFERING, Freshness.STALE, Freshness.PROVISIONAL_HIGHER}:
        st.caption(
            assessment_age(score.get("assessed_as_of"), now)
            + ". Original assessment time is retained."
        )
    if context and context.sources:
        for source in context.sources:
            st.text("Source: " + source.source_id)
            st.text(
                "Oldest open gap: "
                + (
                    str(source.oldest_open_gap_seconds) + " seconds"
                    if source.oldest_open_gap_seconds is not None
                    else "Not supplied"
                )
            )
            st.text(
                "Reconciliation: "
                + (
                    "Pending"
                    if source.pending_reconciliation is True
                    else "No pending reconciliation reported"
                    if source.pending_reconciliation is False
                    else "Not supplied"
                )
            )
            st.text("Last complete through: " + format_time(source.complete_through, timezone))
    elif state != Freshness.COMPLETE:
        st.caption("Gap age and pending-reconciliation status are not supplied in this response.")
    if state == Freshness.PROVISIONAL_HIGHER:
        provisional, baseline = st.columns(2)
        with provisional:
            st.subheader("Separate provisional escalation")
            st.warning("Incomplete data, no adverse-action authority. Reconciliation is pending.")
            render_score(score.get("raw_score"), score.get("rank"), score.get("percentile"), state)
        with baseline:
            st.subheader("Authoritative last complete assessment")
            if (
                context
                and context.baseline
                and context.baseline.score.freshness == Freshness.COMPLETE
            ):
                retained = context.baseline.score
                st.text("Score ID: " + str(context.baseline.score_id))
                st.text(assessment_age(retained.assessed_as_of, now))
                st.text(
                    "Original assessed as of: " + format_time(retained.assessed_as_of, timezone)
                )
                render_score(
                    retained.raw_score, retained.rank, retained.percentile, retained.freshness
                )
            else:
                st.info(
                    "Baseline details are unavailable. The baseline ID does not supply a numeric assessment."
                )
    elif (
        state == Freshness.UNAVAILABLE
        and context
        and context.baseline
        and context.baseline.score.freshness == Freshness.COMPLETE
    ):
        retained = context.baseline.score
        st.subheader("Retained last complete assessment")
        st.warning(
            "The current assessment is unavailable. This separate historical assessment retains its original cutoff."
        )
        st.text("Score ID: " + str(context.baseline.score_id))
        st.text("Original assessed as of: " + format_time(retained.assessed_as_of, timezone))
        st.text(assessment_age(retained.assessed_as_of, now))
        render_score(retained.raw_score, retained.rank, retained.percentile, retained.freshness)
    elif context and context.baseline and context.corrected:
        st.subheader("Previous and corrected publication")
        render_comparison(
            context.baseline.model_dump(mode="json"),
            context.corrected.model_dump(mode="json"),
            timezone,
        )
        if st.button("Inspect correction history", key="late_history"):
            st.session_state["navigate_to"] = "History"
            st.rerun()
