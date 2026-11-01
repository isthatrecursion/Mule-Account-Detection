"""Display server-owned use decisions without turning them into UI promotion controls."""

import streamlit as st

from ui.components.research_banner import render_research
from ui.errors import ApiFailure, ContractError
from ui.extensions import DeploymentDecision
from ui.state import Workspace


def render_decision(decision: DeploymentDecision) -> None:
    if decision.mode == "SHADOW":
        st.warning("Shadow pilot: recommendations only, no account actions")
    elif decision.mode == "BLOCKED":
        st.warning("Deployment use: BLOCKED")
    else:
        st.info("Server-declared use: " + decision.mode)
    st.text("Decision record: " + str(decision.record_id) + " · Revision: " + decision.revision)
    render_research(decision.data_tier, decision.model_tier)
    st.text("Approved by: " + (decision.approved_by or "Not supplied"))
    st.text("Recorded allowed actions: " + (", ".join(decision.allowed_actions) or "None supplied"))
    st.caption("The API still checks current permissions and scope for every action.")
    for dependency in decision.blocking_dependencies:
        st.text("BLOCKED dependency: " + dependency)
    if decision.stopping_conditions:
        with st.expander("Stopping conditions"):
            for condition in decision.stopping_conditions:
                st.text(condition)


def render(workspace: Workspace) -> None:
    if not workspace.api.config.show_deployment_status:
        with st.sidebar.expander("Workspace status"):
            st.caption("Deployment approval: Not supplied by the API.")
        return
    try:
        decision = workspace.api.extension("deployment-status").decision
        if decision is None:
            raise ContractError()
        if decision.mode == "BLOCKED":
            st.warning("Deployment use: BLOCKED")
        elif decision.mode == "SHADOW":
            st.warning("Shadow pilot: recommendations only, no account actions")
        else:
            st.caption("Use: " + decision.mode + " · Recommendations only")
        with st.sidebar.expander("Workspace status"):
            render_decision(decision)
    except ApiFailure:
        st.warning(
            "Deployment status is unavailable. Approved use is not established in this view."
        )
