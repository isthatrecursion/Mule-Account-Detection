"""Pinned, server-ordered queue with directly associated case actions."""

from typing import Any
from uuid import UUID

import streamlit as st

from ui.components.score import score_values
from ui.components.status_views import empty, loading
from ui.copy import readable
from ui.errors import ApiFailure, ContractError
from ui.state import Workspace


def render(workspace: Workspace) -> None:
    st.header("Review queue")
    with loading():
        heads = workspace.api.queues().get("items", [])
    if not heads:
        st.info("No published queue is available in your current scope.")
        return
    if workspace.queue_version is None:
        workspace.choose_queue(heads[0]["queue_version"], heads[0]["cohort_id"])
    version = workspace.queue_version
    assert version is not None
    options = {
        h["queue_version"]: f"Cohort {h['cohort_id'][:8]} · version {h['version']}" for h in heads
    }
    options.setdefault(version, "Opened historical queue · " + version[:8])
    with st.expander("Queue version and display options"):
        selected = st.selectbox(
            "Published queue version",
            list(options),
            index=list(options).index(version),
            format_func=lambda v: options[v],
        )
        if selected != version:
            head: dict[str, Any] = next((h for h in heads if h["queue_version"] == selected), {})
            workspace.choose_queue(selected, head.get("cohort_id"))
            st.rerun()
        sizes = sorted({10, 25, 50, 100, workspace.api.config.page_size})
        st.session_state.setdefault(
            "queue_limit", workspace.queue_filters.get("limit", workspace.api.config.page_size)
        )
        limit = st.selectbox("Page size", sizes, key="queue_limit")
        st.caption("Pinned queue: " + version)
        st.caption(
            "Published order is fixed. Matching count reflects scope and filters; full cohort size and ranking-policy details are not supplied."
        )
    newest = next((h for h in heads if h["cohort_id"] == workspace.queue_cohort), None)
    if newest and newest["queue_version"] != version:
        st.info("A newer queue is available. This view still uses the opened version.")
        if workspace.api.config.late_data_context:
            try:
                movement = workspace.api.extension("queue-context", UUID(newest["queue_version"]))
                if str(movement.queue_version) != newest["queue_version"]:
                    raise ContractError()
                if movement.entered_count is not None and movement.left_count is not None:
                    st.caption(
                        f"Queue movement: {movement.entered_count} entered, {movement.left_count} left the published membership."
                    )
            except ApiFailure as error:
                if error.status != 404:
                    raise
        if st.button("Open newer queue", key="new_queue"):
            workspace.choose_queue(newest["queue_version"], newest["cohort_id"])
            st.rerun()

    st.session_state.setdefault("queue_owner", workspace.queue_filters.get("owner", "All cases"))
    st.session_state.setdefault("queue_state", workspace.queue_filters.get("state_label", "All"))
    state_col, owner_col = st.columns(2)
    with owner_col:
        owner = st.selectbox(
            "Assignment",
            ["All cases", "Assigned to me", "Unassigned (queued)", "Actor ID"],
            key="queue_owner",
        )
    with state_col:
        if owner == "Unassigned (queued)":
            st.session_state["queue_state"] = "QUEUED"
        state = st.selectbox(
            "Case state filter",
            ["All", "QUEUED", "ASSIGNED", "IN_REVIEW", "REVIEWED"],
            key="queue_state",
            format_func=readable,
            disabled=owner == "Unassigned (queued)",
        )
    assignee = None
    if owner == "Assigned to me":
        assignee = workspace.identity["actor_id"]
    elif owner == "Actor ID":
        st.session_state.setdefault("queue_actor", workspace.queue_filters.get("actor", ""))
        with st.expander("Exact assignee", expanded=True):
            assignee = (
                st.text_input("Assignee filter (actor ID)", max_chars=100, key="queue_actor")
                or None
            )
    if owner == "Unassigned (queued)":
        st.caption("Showing queued cases awaiting assignment.")
    filters = {
        "state": "QUEUED" if owner == "Unassigned (queued)" else None if state == "All" else state,
        "assignee": assignee,
        "limit": limit,
    }
    old = {key: workspace.queue_filters.get(key) for key in filters}
    if old != filters:
        workspace.cursor, workspace.previous_cursors = {}, []
    workspace.queue_filters = {
        **filters,
        "owner": owner,
        "state_label": state,
        "actor": assignee if owner == "Actor ID" else "",
    }
    params = {**filters, **workspace.cursor}
    page = workspace.cache.read(
        workspace.fingerprint,
        "queue",
        version,
        params,
        workspace.api.config.cache_seconds,
        lambda: workspace.api.queue(UUID(version), **params),
    )
    st.caption(
        f"{page['total']} matching cases · {options[version]} · Model {page.get('model_version') or 'Unknown'}"
    )
    st.caption(
        "Priority is a ranking score. Percentile is position in this cohort, not a probability."
    )
    incomplete = {
        r["freshness"]
        for r in page["items"]
        if r["freshness"] in {"STALE", "BUFFERING", "PROVISIONAL_HIGHER", "UNAVAILABLE"}
    }
    if incomplete:
        st.warning(
            "This page includes "
            + ", ".join("[" + value + "]" for value in sorted(incomplete))
            + ". Open a case for its original cutoff and source context."
        )

    widths = [0.5, 1.8, 0.9, 0.9, 1.6, 1.3, 1]
    if not page["items"]:
        empty()
    else:
        for row in page["items"]:
            raw, rank, percentile = score_values(
                row.get("raw_score"), row.get("rank"), row.get("percentile"), row["freshness"]
            )
            with st.container(border=True):
                cols = st.columns(widths, vertical_alignment="center")
                for col, label in zip(
                    cols,
                    [
                        "Rank",
                        "Record",
                        "Priority",
                        "Percentile",
                        "Review / assignee",
                        "Freshness",
                        "Action",
                    ],
                    strict=True,
                ):
                    col.caption(label)
                cols[0].text(rank)
                record = str(row["record_key"])
                cols[1].text(record[:24] + ("…" if len(record) > 24 else ""))
                cols[2].text(raw)
                cols[3].text(percentile)
                cols[4].text(readable(row["state"]))
                actor = row.get("assignee")
                cols[4].caption(
                    "You" if actor == workspace.identity["actor_id"] else actor or "Unassigned"
                )
                cols[5].text(readable(row["freshness"]))
                if cols[6].button(
                    "Open case",
                    key="open_case_" + row["case_id"],
                    help="Open record " + record,
                    disabled=not workspace.allowed("case:read"),
                ):
                    workspace.open_case(row["case_id"], record, version)
                    st.query_params["case"] = row["case_id"]
                    st.session_state["navigate_to"] = "Case evidence"
                    st.rerun()
    left, right = st.columns(2)
    if left.button("Previous page", disabled=not workspace.previous_cursors):
        workspace.cursor = workspace.previous_cursors.pop()
        st.rerun()
    if right.button("Next page", disabled=page.get("next") is None):
        workspace.previous_cursors.append(dict(workspace.cursor))
        workspace.cursor = page["next"]
        st.rerun()
