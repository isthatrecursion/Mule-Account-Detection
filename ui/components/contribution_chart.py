"""Signed raw-field contributions, with all essential values also visible as text."""

import math
from typing import Any

import streamlit as st

from ui.dto import EvidenceFacts


def chart_spec(facts: EvidenceFacts) -> dict[str, Any]:
    return {
        "mark": "bar",
        "data": {
            "values": [
                {"Field": row.raw_feature, "Contribution": row.contribution}
                for row in facts.raw_aggregates
            ]
        },
        "encoding": {
            "y": {"field": "Field", "type": "nominal", "sort": None},
            "x": {
                "field": "Contribution",
                "type": "quantitative",
                "title": "Signed contribution (raw-margin scale)",
            },
            "color": {"value": "#617485"},
        },
    }


def render_contributions(facts: EvidenceFacts) -> None:
    st.caption(
        "Contributions show model associations, not causation, criminal intent or certified banking behavior."
    )
    st.text(
        f"Base value: {facts.base_value:g} · Raw output: {facts.raw_margin:g} · Scale: {facts.scale}"
    )
    st.caption("Base + contributions = raw model output (ranking scale, not probability).")
    if not math.isclose(
        facts.base_value + sum(row.contribution for row in facts.raw_aggregates),
        facts.raw_margin,
        rel_tol=1e-8,
        abs_tol=1e-8,
    ):
        st.warning(
            "Data-quality warning: supplied contributions do not reconcile with the supplied raw output. Treat this explanation as inconsistent and contact the deployment owner."
        )
    if not facts.raw_aggregates:
        st.info("No field contributions are supplied for this assessment.")
        return
    st.vega_lite_chart(
        chart_spec(facts),
        width="stretch",
        alt="Signed field contributions around zero. Every value is listed in the following table.",
    )
    st.table(
        [
            {
                "Field": row.raw_feature,
                "Meaning": row.meaning_status.value,
                "Signed contribution": row.contribution,
                "Observed value": str(row.observed_value)
                if row.observed_value is not None
                else "—",
                "Value status": row.value_status or "Not supplied",
                "Reference percentile": row.reference_percentile,
                "Category frequency": row.category_frequency,
                "Unseen category": row.unseen_category,
            }
            for row in facts.raw_aggregates
        ],
        hide_index=True,
    )
    st.caption(
        "Meaning unverified unless dictionary status is CERTIFIED. No business meaning is inferred from field IDs."
    )
    if facts.encoded_detail:
        with st.expander("Encoded contribution detail"):
            st.text(str(facts.encoded_detail))
    for row in facts.raw_aggregates:
        if row.encoded_detail:
            with st.expander("Encoded detail: " + row.raw_feature):
                st.text(str(row.encoded_detail))
