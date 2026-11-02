"""Explicit submits retain one actor-bound request identity until acknowledged."""

from typing import Any
from uuid import UUID

import streamlit as st

from ui.api_client import ApiFailure
from ui.components.status_views import render_error
from ui.components.time_fmt import format_time
from ui.copy import LABELS, readable
from ui.dto import CONCLUSIONS
from ui.state import Workspace


def send(workspace: Workspace) -> None:
    try:
        result = workspace.submit()
        workspace.pending = None
        if result.get("job_id"):
            st.query_params["job"] = result["job_id"]
        st.success("API acknowledged the action.")
        st.text(
            "Persisted action: "
            + str(result.get("event_id") or result.get("job_id") or result.get("submission_id"))
        )
    except ApiFailure as error:
        render_error(error)


def pending(workspace: Workspace) -> None:
    action = workspace.pending
    if not action or action.state in {"ACKNOWLEDGED", "REJECTED"}:
        return
    st.warning("Pending action: " + action.action + " · " + action.state)
    st.caption("Request identity: " + str(action.key))
    st.text(
        "Submitted at: " + format_time(action.created_at, workspace.api.config.display_timezone)
    )
    if action.state == "CONFLICT":
        st.info(
            "Compare your fetched version with the latest API state. Your action was not reapplied."
        )
        st.text("Submitted version: " + str((action.payload or {}).get("expected_version")))
        if action.original:
            st.text(
                "Opened state: "
                + str(action.original.get("state"))
                + " · Assignee: "
                + str(action.original.get("assignee") or "Unassigned")
            )
        if action.history:
            st.text(
                "Newest observed event: "
                + str(action.history[-1].get("event_id") or "Not supplied")
            )
        if action.latest:
            st.text("Latest version: " + str(action.latest.get("case_version")))
            st.text("Latest state: " + str(action.latest.get("state")))
            st.text("Latest assignee: " + str(action.latest.get("assignee") or "Unassigned"))
        if st.button("I reviewed the latest state; prepare a new action", key="resolve_conflict"):
            if action.path.startswith("/v1/cases/"):
                workspace.form_cases.pop(action.path.split("/")[3], None)
            workspace.pending = None
            workspace.cache.clear()
            st.rerun()
    else:
        st.info(
            "Outcome unknown. Current case and recent history are checked when available; they cannot prove which request committed. Only the same-key API acknowledgement resolves this request."
        )
        if action.latest:
            st.text("Latest observed case version: " + str(action.latest.get("case_version")))
        if st.button("Check current outcome", key="check_pending"):
            workspace.check_pending()
            st.rerun()
        if st.button("Check outcome / retry the same request", key="retry_pending"):
            send(workspace)
            st.rerun()


def review_forms(workspace: Workspace, case: dict[str, Any]) -> None:
    case_id, version = UUID(case["case_id"]), case["case_version"]
    opened = workspace.form_cases.setdefault(
        str(case_id),
        {"case_version": version, "state": case["state"], "assignee": case.get("assignee")},
    )
    if opened["case_version"] != version:
        st.warning(
            "The case changed while this form was open. Review the differences before a new action."
        )
        st.text(
            f"Opened version {opened['case_version']} · {opened['state']} · {opened['assignee'] or 'Unassigned'}"
        )
        st.text(
            f"Latest version {version} · {case['state']} · {case.get('assignee') or 'Unassigned'}"
        )
        if st.button(
            "Review latest case state and reset draft", key="form_refresh_" + str(case_id)
        ):
            workspace.form_cases.pop(str(case_id), None)
            st.rerun()
        return
    disabled = bool(
        workspace.pending and workspace.pending.state in {"PENDING", "UNKNOWN", "CONFLICT"}
    )
    mine = case.get("assignee") == workspace.identity["actor_id"]
    state = case["state"]
    if state == "QUEUED" and workspace.allowed("case:assign"):
        with st.form("assign_" + str(case_id) + ":" + str(version), border=False):
            submitted = st.form_submit_button("Assign case", disabled=disabled, type="primary")
            with st.expander("Assign to another actor"):
                assignee = st.text_input("Assignee actor ID (blank assigns to me)", max_chars=100)
            if submitted:
                workspace.begin(
                    "Assignment",
                    f"/v1/cases/{case_id}/assignment",
                    {"expected_version": version, "assignee": assignee or None},
                )
                send(workspace)
                st.rerun()
    if state == "ASSIGNED" and mine and workspace.allowed("case:review"):
        with st.form("start_" + str(case_id) + ":" + str(version), border=False):
            if st.form_submit_button("Start review", disabled=disabled, type="primary"):
                workspace.begin(
                    "Start review",
                    f"/v1/cases/{case_id}/start-review",
                    {"expected_version": version},
                )
                send(workspace)
                st.rerun()
    if state == "IN_REVIEW" and mine and workspace.allowed("case:review"):
        with st.form(
            "review_" + str(case_id) + ":" + str(version), clear_on_submit=False, border=False
        ):
            conclusion = st.selectbox(
                "Review conclusion",
                CONCLUSIONS,
                format_func=readable,
            )
            note = st.text_area("Review note", max_chars=4000)
            st.caption(LABELS["conclusion"])
            if st.form_submit_button("Save review", disabled=disabled, type="primary"):
                workspace.begin(
                    "Review",
                    f"/v1/cases/{case_id}/reviews",
                    {"expected_version": version, "conclusion": conclusion, "note": note or None},
                )
                send(workspace)
                st.rerun()
    if state == "REVIEWED" and workspace.allowed("case:reopen"):
        with st.form("reopen_" + str(case_id) + ":" + str(version), border=False):
            reason = st.text_area("Reason for reopening", max_chars=4000)
            if st.form_submit_button("Reopen case", disabled=disabled):
                if not reason.strip():
                    st.error("Enter a reason for reopening.")
                else:
                    workspace.begin(
                        "Reopen",
                        f"/v1/cases/{case_id}/reopen",
                        {"expected_version": version, "reason": reason},
                    )
                    send(workspace)
                    st.rerun()
