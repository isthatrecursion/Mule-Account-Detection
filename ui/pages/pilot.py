"""Read-only denominators and label maturity; no population inference from reviewed samples."""

import streamlit as st

from ui.components.deployment import render_decision
from ui.components.status_views import forbidden, render_error
from ui.copy import LABELS
from ui.errors import ApiFailure, ContractError
from ui.extensions import PilotMetric
from ui.state import Workspace


def metric_rows(metrics: list[PilotMetric]) -> list[dict[str, str]]:
    return [
        {
            "Metric": metric.name,
            "Data status": "[AVAILABLE]" if metric.state == "PASSED" else "[" + metric.state + "]",
            "Numerator": str(metric.numerator) if metric.numerator is not None else "Not supplied",
            "Denominator": str(metric.denominator)
            if metric.denominator is not None
            else "Not supplied",
            "Labels available": str(metric.labels_available)
            if metric.labels_available is not None
            else "Not supplied",
            "Label denominator": str(metric.labels_eligible)
            if metric.labels_eligible is not None
            else "Not supplied",
            "Outcome maturity": metric.outcome_maturity,
            "Reasons": "; ".join(metric.reasons) or "None supplied",
        }
        for metric in metrics
    ]


def render(workspace: Workspace) -> None:
    st.header("Pilot metrics")
    if (
        not workspace.api.config.mock_mode
        or "Pilot metrics" not in workspace.api.config.extension_pages
    ):
        st.info(LABELS["extension"])
        return
    if not workspace.allowed("audit:read"):
        forbidden()
        return
    st.caption("Synthetic preview · Live pilot-metrics integration pending.")
    try:
        decision = workspace.api.extension("deployment-status").decision
        data = workspace.api.extension("pilot-metrics")
        if decision is None or data.decision_record_id != decision.record_id:
            raise ContractError()
        render_decision(decision)
        st.caption(
            "Read-only extension. Reviewed-sample findings and eligible-population workload counts are shown separately."
        )
        st.caption(
            "Data status reports supplied metric availability. Deployment approval is shown in the decision record above."
        )
        for population in ("ELIGIBLE_POPULATION", "REVIEWED_SAMPLE"):
            st.subheader(population.replace("_", " ").capitalize())
            metrics = [metric for metric in data.metrics if metric.population == population]
            if metrics:
                st.table(metric_rows(metrics), hide_index=True)
            else:
                st.info("No metrics are supplied for this population.")
            for metric in metrics:
                if metric.freshness_counts or metric.corrected_count is not None:
                    st.text(
                        metric.name
                        + " · Freshness counts: "
                        + str(metric.freshness_counts)
                        + " · Corrected publications: "
                        + str(
                            metric.corrected_count
                            if metric.corrected_count is not None
                            else "Not supplied"
                        )
                    )
    except ApiFailure as error:
        if error.status == 404:
            st.info(LABELS["extension"])
        else:
            render_error(error)
