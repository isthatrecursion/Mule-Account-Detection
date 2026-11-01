"""Audited export authorization followed by actor-scoped, expiring download."""

from functools import partial
from uuid import UUID

import streamlit as st

from ui.auth import LoginRequired
from ui.components.actions import send
from ui.components.badges import render_badge
from ui.components.status_views import forbidden, render_error
from ui.components.time_fmt import format_time
from ui.dto import ExportRequest
from ui.enums import JobState
from ui.errors import ApiFailure
from ui.state import Workspace


def reconnect_export(workspace: Workspace, value: str) -> None:
    """Resolve authorization and job kind before attaching an export to this session."""
    job_id = str(UUID(value))
    job = workspace.api.job(UUID(job_id))
    if job["kind"] != "export":
        raise ValueError("This job is not an export")
    workspace.reconnect_job(job_id)
    workspace.job_views[job_id] = job
    workspace.last_poll[job_id] = workspace.clock()


def authorized_download(workspace: Workspace, job_id: str, fingerprint: str) -> bytes:
    if not fingerprint or workspace.fingerprint != fingerprint or not workspace.identity:
        raise LoginRequired()
    workspace.api.get_me()
    return workspace.api.download(UUID(job_id))


def render(workspace: Workspace) -> None:
    st.header("Authorized exports")
    if not workspace.allowed("export:create"):
        forbidden()
        return
    st.caption("Choose a queue and export scope. Downloads expire ten minutes after the request.")
    with st.expander("Reconnect export by job ID"):
        with st.form("reconnect_export"):
            reconnect_id = st.text_input("Export job ID")
            if st.form_submit_button("Reconnect export"):
                try:
                    reconnect_export(workspace, reconnect_id)
                    st.query_params["job"] = reconnect_id
                    st.rerun()
                except ValueError:
                    st.error(
                        "Enter a valid export job ID. Jobs for other operations cannot be connected here."
                    )
                except ApiFailure as error:
                    render_error(error)
    options: dict[str, str] = {}
    if workspace.allowed("queue:read"):
        options = {
            h["queue_version"]: f"Cohort {h['cohort_id'][:8]} · version {h['version']}"
            for h in workspace.api.queues().get("items", [])
        }
    if workspace.queue_version and workspace.queue_version not in options:
        options[workspace.queue_version] = "Opened queue · " + workspace.queue_version[:8]
    with st.form("export_queue"):
        if options:
            queue = st.selectbox(
                "Queue to export",
                list(options),
                index=list(options).index(workspace.queue_version)
                if workspace.queue_version in options
                else 0,
                format_func=lambda value: options[value],
            )
            st.caption("Queue version to export: " + queue)
        else:
            queue = st.text_input(
                "Queue version to export",
                value=workspace.queue_version or "",
                help="Queue discovery is unavailable in your scope. Enter an authorized queue version.",
            )
        columns = ["case_id", "rank", "raw_score", "state"]
        if workspace.allowed("export:sensitive"):
            columns += ["record_key", "note"]
        selected = st.multiselect(
            "Columns", columns, default=["case_id", "rank", "raw_score", "state"]
        )
        state = st.selectbox(
            "Export case state filter",
            ["All", "QUEUED", "ASSIGNED", "IN_REVIEW", "REVIEWED"],
            index=["All", "QUEUED", "ASSIGNED", "IN_REVIEW", "REVIEWED"].index(
                workspace.queue_filters.get("state") or "All"
            ),
        )
        reason = st.text_input("Export reason", max_chars=200)
        st.text(
            "Effective export scopes: "
            + ", ".join(workspace.identity["permission_scopes"].get("export:create", []))
        )
        with st.expander("Export provenance and protection"):
            st.caption(
                "The server freezes the authorized queue, scope, filters and columns, adds provenance and escapes spreadsheet formulas."
            )
        confirmed = st.checkbox(
            "I confirm this queue version, filter, columns and authorized scope"
        )
        disabled = bool(
            workspace.pending and workspace.pending.state in {"PENDING", "UNKNOWN", "CONFLICT"}
        )
        if st.form_submit_button("Authorize export", disabled=disabled):
            try:
                if not confirmed or not reason.strip() or not selected:
                    raise ValueError()
                request = ExportRequest.model_validate(
                    dict(
                        queue_version=queue,
                        columns=selected,
                        state=None if state == "All" else state,
                        reason=reason,
                    )
                )
            except ValueError:
                st.error(
                    "Choose a valid queue version, columns and reason, then confirm the displayed scope."
                )
            else:
                workspace.begin(
                    "Export",
                    "/v1/exports",
                    request.model_dump(mode="json"),
                )
                send(workspace)
                st.rerun()
    export_count = 0
    for job_id in workspace.jobs[-20:]:
        try:
            known = workspace.job_views.get(job_id)
            if known is not None and known["kind"] != "export":
                continue
            job = workspace.poll(job_id)
            if job["kind"] != "export":
                continue
            export_count += 1
            manual = st.button("Refresh export status", key="export_refresh_" + job_id)
            job = workspace.poll(job_id, force=manual)
            with st.container(border=True):
                st.text("Export job: " + job_id)
                render_badge("Export job", JobState(job["state"]))
                st.text(
                    "Requested at: "
                    + format_time(job["created_at"], workspace.api.config.display_timezone)
                )
                receipt = workspace.export_receipts.get(job_id)
                if receipt:
                    st.text("Requested queue version: " + str(receipt["queue_version"]))
                    st.text("Requested columns: " + ", ".join(receipt["columns"]))
                    st.text("Requested state filter: " + str(receipt.get("state") or "All"))
                else:
                    st.caption(
                        "This session has no original request receipt. Verify the exported provenance columns; request scope details are not returned by this job endpoint."
                    )
                if workspace.clock() - workspace.poll_started[
                    job_id
                ] >= workspace.api.config.max_poll_seconds and job["state"] not in {
                    "SUCCEEDED",
                    "FAILED",
                }:
                    st.info(
                        "Automatic polling reached its limit. Refresh export status for a single update."
                    )
                if job["state"] == "SUCCEEDED":
                    st.caption(
                        "The file includes server-frozen provenance. Exact expiry and model/policy metadata are not returned separately in this job response."
                    )
                    st.download_button(
                        "Download CSV",
                        data=partial(authorized_download, workspace, job_id, workspace.fingerprint),
                        file_name="review-" + job_id + ".csv",
                        mime="text/csv",
                        key="download_" + job_id,
                        on_click="ignore",
                    )
                elif job["state"] == "FAILED":
                    st.warning(
                        "The export failed. Resolve its dependency and request a new export with confirmed scope."
                    )
        except ApiFailure as error:
            render_error(error)
            if error.status in {403, 404}:
                st.info(
                    "Download is expired, unavailable or outside your current authorization. Review the scope and request a new export."
                )
    if not export_count:
        st.info(
            "No export jobs are connected. Request an export above or use Reconnect export by job ID."
        )
