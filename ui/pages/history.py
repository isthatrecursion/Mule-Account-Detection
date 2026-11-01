"""API-filtered immutable histories; sensitive text is rendered as text, never HTML."""

from uuid import UUID

import streamlit as st

from ui.components.comparison import render_comparison
from ui.components.status_views import empty, loading
from ui.components.time_fmt import format_time
from ui.copy import readable
from ui.errors import ApiFailure, ContractError
from ui.state import Workspace


def render(workspace: Workspace) -> None:
    st.header("Assessment & review history")
    if workspace.selected_case:
        if workspace.allowed("case:read") and st.button("Back to case evidence"):
            st.session_state["navigate_to"] = "Case evidence"
            st.rerun()
        st.caption("Case: " + workspace.selected_case)
    with st.expander("Open history by case ID", expanded=not bool(workspace.selected_case)):
        value = st.text_input(
            "Case ID for history",
            value=workspace.selected_case or str(st.query_params.get("case", "")),
            key="history_lookup_" + str(workspace.selected_case),
        )
    try:
        identity = UUID(value)
    except ValueError:
        st.info("Select a case to view its immutable history.")
        return
    if workspace.selected_case != str(identity):
        workspace.selected_record = workspace.selected_queue = None
    workspace.selected_case = str(identity)
    kinds = (["reviews", "scores"] if workspace.allowed("case:read") else []) + (
        ["audit"] if workspace.allowed("audit:read") else []
    )
    kind = st.selectbox(
        "History type",
        kinds,
        format_func=lambda v: {
            "reviews": "Review decisions",
            "scores": "Assessments",
            "audit": "Audit events",
        }[v],
    )
    offset_key = str(identity) + ":" + kind
    after = workspace.history_after.get(offset_key, 0)
    version = ""
    if workspace.allowed("case:read"):
        case = workspace.api.case(identity)
        version = (
            str(case["case_version"])
            + ":"
            + case["score_id"]
            + ":"
            + str(case.get("newer_score_id"))
        )
    with loading():
        page = workspace.cache.read(
            workspace.fingerprint,
            "history:" + str(identity),
            version,
            {"kind": kind, "after": after},
            workspace.api.config.cache_seconds,
            lambda: workspace.api.history(identity, kind, after),
        )
    st.caption("Earlier events retain their original assessment. Later corrections append history.")
    if kind == "reviews" and not workspace.allowed("note:read"):
        st.info("Review notes and reopen reasons: Not permitted to view.")
    if not page["items"]:
        empty()
    for event in page["items"]:
        with st.container(border=True):
            action = {
                "case:assign": "Case assigned",
                "case:start_review": "Review started",
                "case:review": "Review recorded" if event.get("conclusion") else "Review activity",
                "case:reopen": "Case reopened",
            }.get(
                str(event.get("action")),
                readable(
                    str(
                        event.get("action")
                        or ("Assessment published" if kind == "scores" else "Event recorded")
                    )
                ),
            )
            st.text(action)
            st.caption(
                format_time(
                    event.get("created_at") or event.get("assessed_as_of"),
                    workspace.api.config.display_timezone,
                )
                + " · Actor: "
                + (
                    "You"
                    if event.get("actor_id") == workspace.identity["actor_id"]
                    else str(event.get("actor_id") or "Not supplied")
                )
            )
            if event.get("conclusion"):
                st.text("Conclusion: " + readable(event["conclusion"]))
            if kind == "scores":
                st.text(
                    "Rank: "
                    + str(event.get("rank") if event.get("rank") is not None else "—")
                    + " · Priority: "
                    + str(event.get("raw_score") if event.get("raw_score") is not None else "—")
                    + " · Freshness: "
                    + readable(str(event.get("freshness") or "Unknown"))
                )
            if event.get("selected"):
                st.caption("Selected assessment for the opened case.")
            elif kind == "scores" and event.get("queue_version"):
                if st.button(
                    "Inspect queue version " + str(event["version"]),
                    key="history_queue_" + event["score_id"],
                ):
                    workspace.choose_queue(event["queue_version"])
                    st.session_state["navigate_to"] = "Review queue"
                    st.rerun()
            if workspace.allowed("note:read") and event.get("note") is not None:
                st.text(
                    ("Reopen reason: " if event.get("action") == "case:reopen" else "Review note: ")
                    + event["note"]
                )
            elif event.get("action") == "case:reopen":
                st.caption("A reason is unavailable in this API response or was not recorded.")
            with st.expander("Event details"):
                for key in (
                    "event_id",
                    "score_id",
                    "model_id",
                    "case_version",
                    "version",
                    "queue_version",
                    "action",
                    "actor_id",
                ):
                    if key in event:
                        st.text(key.replace("_", " ") + ": " + str(event[key]))
    if kind == "scores" and len(page["items"]) > 1:
        st.caption(
            "Compare published ranks and raw priorities above. Different model versions may use different score scales; changes do not establish changed criminal behavior."
        )
    if kind == "scores" and len(page["items"]) > 1:
        st.subheader("Compare published assessments")
        options = list(range(len(page["items"])))

        def assessment_label(i: int) -> str:
            item = page["items"][i]
            return (
                format_time(
                    item.get("assessed_as_of") or item.get("created_at"),
                    workspace.api.config.display_timezone,
                )
                + " · version "
                + str(item.get("version", "Unknown"))
                + " · "
                + str(item.get("score_id", "Unknown"))[:8]
            )

        st.caption("Comparison is limited to the assessments on this page.")
        earlier = st.selectbox(
            "Earlier assessment on this page",
            options,
            format_func=assessment_label,
        )
        later = st.selectbox(
            "Later assessment on this page",
            options,
            index=len(options) - 1,
            format_func=assessment_label,
        )
        if st.button("Compare selected assessments", disabled=earlier == later):
            first, second = page["items"][earlier], page["items"][later]
            if workspace.api.config.late_data_context:
                try:
                    context = workspace.api.extension("case-context", identity)
                    if str(context.case_id) != str(identity):
                        raise ContractError()
                    enriched = {
                        str(item.score_id): item.model_dump(mode="json")
                        for item in (context.baseline, context.corrected)
                        if item is not None
                    }
                    first = enriched.get(str(first.get("score_id")), first)
                    second = enriched.get(str(second.get("score_id")), second)
                except ApiFailure as error:
                    if error.status != 404:
                        raise
            render_comparison(first, second, workspace.api.config.display_timezone)
    left, right = st.columns(2)
    if left.button("Earlier history", disabled=after == 0):
        workspace.history_after[offset_key] = max(0, after - 20)
        st.rerun()
    if right.button("Later history", disabled=page.get("next") is None):
        workspace.history_after[offset_key] = page["next"]
        st.rerun()
