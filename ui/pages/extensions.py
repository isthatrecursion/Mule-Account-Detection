"""Read-only, flag-gated ASSUMPTION viewers for future backend contracts."""

import re
from urllib.parse import urlencode, urlsplit

import streamlit as st

from ui.components.research_banner import render_research
from ui.components.status_views import forbidden, render_error
from ui.components.time_fmt import format_time
from ui.copy import LABELS
from ui.errors import ApiFailure
from ui.extensions import Gate
from ui.state import Workspace

ROUTES = {
    "Models": "models",
    "Retraining proposals": "proposals",
    "Evidence reports": "reports",
    "Source health": "source-health",
}


def gate_rows(gates: list[Gate]) -> list[dict[str, str]]:
    return [
        {
            "Gate": gate.name,
            "Outcome": "[" + gate.state + "]",
            "Reasons": "; ".join(gate.reasons) or "Not supplied",
            "Numerator": str(gate.numerator) if gate.numerator is not None else "Not supplied",
            "Denominator": str(gate.denominator)
            if gate.denominator is not None
            else "Not supplied",
            "Trials": str(gate.trials) if gate.trials is not None else "Not supplied",
        }
        for gate in gates
    ]


def monitoring_url(
    base: str | None, environment: str, source: str, allowed_sources: tuple[str, ...]
) -> str | None:
    destination = urlsplit(base or "")
    if (
        destination.scheme != "https"
        or not destination.hostname
        or destination.username
        or destination.password
        or destination.query
        or destination.fragment
        or environment not in {"local", "test", "research", "staging", "qualified"}
    ):
        return None
    if (
        not base
        or source not in allowed_sources
        or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", source)
    ):
        return None
    return (
        base.rstrip("/")
        + "/d/source-health?"
        + urlencode({"var-environment": environment, "var-source": source})
    )


def render(workspace: Workspace, *, page: str) -> None:
    st.header(page)
    if (
        not workspace.api.config.mock_mode
        or page not in workspace.api.config.extension_pages
        or page not in ROUTES
    ):
        st.info(LABELS["extension"])
        return
    if not workspace.allowed("audit:read"):
        forbidden()
        return
    st.caption(
        "Synthetic preview · Read-only extension · Proposed API contract · Live integration pending."
    )
    try:
        data = workspace.api.extension(ROUTES[page])
    except ApiFailure as error:
        if error.status == 404:
            st.info(LABELS["extension"])
        else:
            render_error(error)
        return
    st.text("Response revision: " + data.revision)
    if page == "Models":
        if not data.models:
            st.info("No model governance records are supplied.")
        for model in data.models:
            render_research(model.data_tier, model.model_tier)
            for label, value in (
                ("Environment", model.environment),
                ("Active bundle", model.bundle_digest),
                ("Model tier", model.model_tier),
                ("Approval state", model.approval_state),
                ("Requester", model.requester),
                ("Reviewer", model.reviewer),
            ):
                st.text(label + ": " + str(value or "Not supplied"))
            if model.requester and model.requester == model.reviewer:
                st.warning(
                    "Requester and reviewer are the same identity; separation of duties is not established."
                )
            st.table(gate_rows(model.gates), hide_index=True)
            for event in model.events:
                st.text(str(event))
    elif page == "Retraining proposals":
        for proposal in data.proposals:
            st.text("Proposal: " + str(proposal.proposal_id))
            st.text("Trigger: " + proposal.trigger)
            st.text("Status: " + proposal.status)
            st.text(
                "Supporting reports: "
                + ", ".join(str(value) for value in proposal.supporting_report_ids)
            )
        if not data.proposals:
            st.info("No retraining proposals are supplied.")
    elif page == "Evidence reports":
        for report in data.reports:
            st.text("Report: " + str(report.report_id))
            st.text("Scenario fingerprint: " + report.scenario_fingerprint)
            st.warning("Evidence class: " + report.evidence_class)
            st.subheader("During-delay disagreement")
            st.table(gate_rows([report.during_delay_disagreement]), hide_index=True)
            st.subheader("Final consistency")
            st.table(gate_rows([report.final_consistency]), hide_index=True)
            st.table(gate_rows(report.gates), hide_index=True)
        if not data.reports:
            st.info("No replay or acceptance evidence is supplied.")
    elif page == "Source health":
        for source in data.sources:
            st.text("Source: " + source.source_id)
            st.text(
                "Complete through: "
                + format_time(source.complete_through, workspace.api.config.display_timezone)
            )
            st.text(
                "Oldest open gap: "
                + (
                    str(source.oldest_open_gap_seconds) + " seconds"
                    if source.oldest_open_gap_seconds is not None
                    else "Not supplied"
                )
            )
            st.text(
                "Reconciliation pending: "
                + str(
                    source.pending_reconciliation
                    if source.pending_reconciliation is not None
                    else "Not supplied"
                )
            )
            link = monitoring_url(
                workspace.api.config.grafana_base_url,
                workspace.api.config.environment,
                source.source_id,
                workspace.api.config.monitored_sources,
            )
            if link:
                st.link_button("Open source dashboard", link)
            else:
                st.caption("An approved monitoring link is not configured for this source.")
