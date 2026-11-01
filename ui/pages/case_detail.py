"""Factual evidence only: anonymous features never become invented business narratives."""

from typing import Any
from uuid import UUID

import streamlit as st

from ui.components.actions import review_forms
from ui.components.contribution_chart import render_contributions
from ui.components.freshness import render as render_freshness
from ui.components.late_context import render_context
from ui.components.provenance_header import render_provenance
from ui.components.research_banner import render_research
from ui.components.score import render_score
from ui.components.status_views import loading
from ui.copy import readable
from ui.dto import EvidencePayload
from ui.errors import ApiFailure, ContractError
from ui.state import Workspace


def render(workspace: Workspace) -> None:
    heading, back, history_link = st.columns([2, 1, 1], vertical_alignment="center")
    heading.header("Case evidence")
    if workspace.allowed("queue:read") and back.button("Back to queue"):
        st.session_state["navigate_to"] = "Review queue"
        st.rerun()
    if workspace.selected_case and history_link.button("View case history"):
        st.session_state["navigate_to"] = "History"
        st.rerun()
    lookup = st.sidebar if workspace.selected_case else st
    with lookup.expander("Open by case ID", expanded=not bool(workspace.selected_case)):
        raw = st.text_input(
            "Case ID",
            value=workspace.selected_case or str(st.query_params.get("case", "")),
            key="case_lookup_" + str(workspace.selected_case),
        )
    try:
        identity = UUID(raw)
    except ValueError:
        st.info("Open a case from the queue or enter a case ID.")
        return
    if workspace.selected_case != str(identity):
        workspace.selected_record = workspace.selected_queue = None
    workspace.selected_case = str(identity)
    with loading():
        case = workspace.api.case(identity)  # Workflow version is fresh; assessment is immutable.
    pinned = workspace.pinned_scores.setdefault(str(identity), case["score_id"])
    if pinned != case["score_id"] or case["case_id"] != str(identity):
        raise ContractError()
    score = case["score"]
    st.text("Record: " + str(case.get("record_key") or workspace.selected_record or "Not supplied"))
    st.caption(
        "State: "
        + readable(case["state"])
        + " · Assignee: "
        + (
            "You"
            if case.get("assignee") == workspace.identity["actor_id"]
            else str(case.get("assignee") or "Unassigned")
        )
    )
    render_research(
        score.get("data_tier"),
        score.get("model_tier"),
        in_sample=score.get("in_sample") is True,
        compact=True,
    )
    if score.get("freshness") != "PROVISIONAL_HIGHER":
        render_score(
            score.get("raw_score"),
            score.get("rank"),
            score.get("percentile"),
            score.get("freshness", "UNKNOWN"),
        )
    render_freshness(score, workspace.api.config.display_timezone)
    context = None
    if workspace.api.config.late_data_context:
        try:
            context = workspace.api.extension("case-context", identity)
            if str(context.case_id) != case["case_id"] or str(context.score_id) != pinned:
                raise ContractError()
        except ApiFailure as error:
            if error.status != 404:
                raise
            st.caption("Extended source and baseline context is not available in this build.")
    if case.get("newer_assessment_available"):
        st.info("A newer assessment exists. This case retains the score and evidence shown above.")
        if st.button("Inspect assessment history"):
            st.session_state["navigate_to"] = "History"
            st.rerun()
    evidence = workspace.cache.read(
        workspace.fingerprint,
        "evidence",
        case["score_id"],
        {},
        workspace.api.config.cache_seconds,
        lambda: workspace.api.evidence(identity),
    )
    if evidence["case_id"] != case["case_id"] or evidence["score_id"] != pinned:
        raise ContractError()
    review_panel, evidence_panel = st.columns([1, 2], gap="large")
    with review_panel:
        with st.container(border=True):
            st.subheader("Review workflow")
            review_forms(workspace, case)
            if case.get("assignee") and case["assignee"] != workspace.identity["actor_id"]:
                st.info("This case is assigned to another actor.")
            elif case["state"] == "REVIEWED":
                st.caption("Review recorded. Inspect history for the saved decision.")
            elif not workspace.allowed("case:review") and not workspace.allowed("case:assign"):
                st.caption("Your current permissions allow evidence viewing only.")
    with evidence_panel:
        render_context(score, context, workspace.api.config.display_timezone, workspace.now())
        _render_evidence(workspace, case, evidence)


def _render_evidence(workspace: Workspace, case: dict[str, Any], evidence: dict[str, Any]) -> None:
    facts = evidence.get("facts")
    if not facts:
        st.info("Detailed contributions are unavailable for this selected assessment.")
    else:
        st.subheader("Observed model evidence")
        parsed = EvidencePayload.model_validate(evidence)
        assert parsed.facts is not None
        render_contributions(parsed.facts)
    with st.expander("Assessment provenance"):
        st.caption("Workflow version: " + str(case["case_version"]))
        st.text("Assignee actor: " + str(case.get("assignee") or "Unassigned"))
        render_provenance(case, workspace.api.config.display_timezone)
        limitations = list(
            dict.fromkeys(
                [
                    *(case["score"].get("provenance_limitations") or []),
                    *evidence.get("limitations", []),
                ]
            )
        )
        for limitation in limitations:
            st.text(str(limitation))
        if case.get("newer_score_id"):
            st.text("Newer score: " + str(case["newer_score_id"]))
