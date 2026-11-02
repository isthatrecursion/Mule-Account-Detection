"""Compare supplied immutable facts; never invent unavailable historical evidence."""

from typing import Any

import streamlit as st

from ui.components.score import score_values
from ui.components.time_fmt import format_time
from ui.dto import EvidenceFacts, parse


def comparison_rows(
    before: dict[str, Any], after: dict[str, Any], timezone: str = "UTC"
) -> list[dict[str, str]]:
    def facts(item: dict[str, Any]) -> dict[str, Any]:
        score = item.get("score") or item
        values = score_values(
            score.get("raw_score"),
            score.get("rank"),
            score.get("percentile"),
            score.get("freshness", "UNKNOWN"),
        )
        return {
            "Score ID": item.get("score_id"),
            "Model ID": item.get("model_id"),
            "Queue version": item.get("queue_version"),
            "Review-priority score": values[0],
            "Rank": values[1],
            "Freshness": score.get("freshness"),
            "Publication event": score.get("publication_event"),
            "Assessed as of": format_time(score.get("assessed_as_of"), timezone),
        }

    first, second = facts(before), facts(after)
    return [
        {
            "Field": key,
            "Earlier": str(value) if value is not None else "Not supplied",
            "Later": str(second[key]) if second[key] is not None else "Not supplied",
            "Change": "Changed" if value != second[key] else "Unchanged",
        }
        for key, value in first.items()
    ]


def render_comparison(before: dict[str, Any], after: dict[str, Any], timezone: str = "UTC") -> None:
    st.table(comparison_rows(before, after, timezone), hide_index=True)
    st.caption(
        "Different model versions can use different ranking scales. A change does not establish a change in an adjudicated outcome."
    )
    if not (before.get("facts") and after.get("facts")):
        st.info(
            "Historical contributor comparison is unavailable in this response. Original case evidence remains pinned to its selected assessment."
        )
    else:
        first = parse(EvidenceFacts, before["facts"])
        second = parse(EvidenceFacts, after["facts"])
        old = {row.raw_feature: row.contribution for row in first.raw_aggregates}
        new = {row.raw_feature: row.contribution for row in second.raw_aggregates}
        st.table(
            [
                {
                    "Field ID": field,
                    "Earlier signed contribution": old.get(field),
                    "Later signed contribution": new.get(field),
                    "Change": "Changed" if old.get(field) != new.get(field) else "Unchanged",
                    "Meaning": "Meaning unverified",
                }
                for field in sorted(set(old) | set(new))
            ],
            hide_index=True,
        )
