"""Durable intake/model jobs, with no local model or dataset processing."""

import json
from typing import Any
from uuid import UUID

import streamlit as st

from ui.components.actions import send
from ui.components.badges import render_badge
from ui.components.status_views import loading, render_error
from ui.components.time_fmt import format_time
from ui.enums import IngestionStatus, JobState
from ui.errors import ApiFailure
from ui.state import Workspace

FINDINGS = {
    "SCHEMA_HEADER": "CSV columns do not match the registered source schema.",
    "CHECKSUM_MISMATCH": "The file bytes do not match the declared checksum.",
    "INTAKE_METADATA_CONFLICT": "These file bytes already have different registered scope or provenance.",
    "CONFOUNDED_RESEARCH_COHORTS": "Research cohorts and labels are confounded; qualified use remains blocked.",
    "UNVERIFIED_RESEARCH_PROVENANCE": "Research provenance is unverified.",
    "QUALIFIED_SOURCE_NOT_CERTIFIED": "The source is not certified for qualified use.",
}


def finding_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Current intake API exposes codes only; never fill missing rule facts by guessing."""
    return [
        {
            "Rule ID": str(code),
            "Rule version": "Not supplied",
            "Severity": "Not supplied",
            "Affected count": "Not supplied",
            "Safe message": FINDINGS.get(
                str(code),
                "Check the registered source and manifest before submitting corrected data.",
            ),
            "Blocks": "Not supplied",
        }
        for code in result.get("finding_codes", [])
    ]


def submit_upload(workspace: Workspace, content: bytes, manifest: bytes, filename: str) -> None:
    """Validate upload bounds and JSON metadata only; validation of rows stays in the API."""
    if not content or len(content) > workspace.api.config.max_upload_bytes or len(manifest) > 16384:
        raise ValueError("Upload size is outside the configured limits")
    declaration = json.loads(manifest)
    if not isinstance(declaration, dict):
        raise ValueError("A manifest object is required")
    declared = json.dumps(declaration, ensure_ascii=True, separators=(",", ":"))
    if len(declared) > 16384:
        raise ValueError("Manifest exceeds the metadata limit")
    workspace.begin(
        "Batch intake", "/v1/batches", None, content=content, manifest=declared, filename=filename
    )


def render_job(workspace: Workspace, job_id: str, disabled: bool) -> None:
    with st.container(border=True):
        st.text("Job: " + job_id)
        manual = st.button("Refresh job status", key="poll_" + job_id)
        try:
            job = workspace.poll(job_id, force=manual)
        except ApiFailure as error:
            render_error(error)
            return
        render_badge("Job", JobState(job["state"]))
        st.text("Operation: " + job["kind"])
        st.text("Created: " + format_time(job["created_at"], workspace.api.config.display_timezone))
        if job["state"] in {"SUCCEEDED", "FAILED"}:
            st.caption("Automatic polling stopped: job is terminal.")
        elif (
            workspace.clock() - workspace.poll_started[job_id]
            >= workspace.api.config.max_poll_seconds
        ):
            st.info(
                "Automatic polling reached its time limit. Use Refresh job status for a single update."
            )
        else:
            st.caption(
                f"Checking every {workspace.api.config.poll_seconds} seconds, for at most {workspace.api.config.max_poll_seconds} seconds."
            )
        for attempt in job.get("attempts", []):
            st.text(
                "Attempt: "
                + str(attempt.get("attempt", "Not supplied"))
                + " · Started: "
                + format_time(attempt.get("started_at"), workspace.api.config.display_timezone)
            )
        result = job.get("result") or {}
        for label, field in (
            ("Batch", "batch_id"),
            ("Resolved model", "model_id"),
            ("Published queue", "queue_id"),
            ("Bundle digest", "bundle_digest"),
        ):
            if result.get(field):
                st.text(label + ": " + str(result[field]))
        if result.get("outcome"):
            render_badge("Ingestion", IngestionStatus(result["outcome"]))
            if result["outcome"] in {"QUARANTINED", "REJECTED", "FAILED"}:
                st.warning(
                    "No scores were published by this intake operation. Correct the source or manifest using the findings before submitting a new batch."
                )
        if result.get("queue_id") and workspace.allowed("queue:read"):
            if st.button("Open published queue", key="job_queue_" + job_id):
                workspace.choose_queue(result["queue_id"])
                st.session_state["navigate_to"] = "Review queue"
                st.rerun()
        findings = finding_rows(result)
        if findings:
            st.warning(
                "Validation findings require attention. Rule details absent from the API are marked Not supplied."
            )
            st.table(findings, hide_index=True)
        if result.get("error_code"):
            st.error(
                "Job failed. Code: "
                + ("JOB_FAILED" if result["error_code"] == "JOB_FAILED" else "UNKNOWN")
                + ". Resolve the dependency before an authorized retry."
            )
        if workspace.allowed("job:retry"):
            with st.form("retry_" + job_id):
                reason = st.text_input("Retry reason", max_chars=200)
                if st.form_submit_button(
                    "Request authorized retry", disabled=disabled or job["state"] != "FAILED"
                ):
                    if not reason.strip():
                        st.error("Enter a reason for retrying.")
                    else:
                        workspace.begin(
                            "Job retry", f"/v1/jobs/{UUID(job_id)}/retry", {"reason": reason}
                        )
                        send(workspace)
                        st.rerun()


def render(workspace: Workspace) -> None:
    config = workspace.api.config
    st.header("Intake & operations")
    st.caption(
        f"Workspace limits: {config.max_upload_bytes:,} upload bytes · {config.max_batch_rows:,} rows. API validation is authoritative."
    )
    st.info(
        "Research intake accepts development rows only. Holdout rows must never be submitted for scoring. The API enforces eligibility."
    )
    disabled = bool(
        workspace.pending and workspace.pending.state in {"PENDING", "UNKNOWN", "CONFLICT"}
    )
    task_names = []
    if workspace.allowed("batch:intake"):
        task_names.append("Data intake")
    if workspace.allowed("score:submit") or workspace.allowed("train:submit"):
        task_names.append("Scoring / training")
    task_names.append("Jobs")
    panels = dict(zip(task_names, st.tabs(task_names), strict=True))
    if workspace.allowed("batch:intake"):
        with panels["Data intake"], st.form("intake"):
            source = st.file_uploader("Feature batch CSV", type=["csv"])
            manifest = st.file_uploader("Declared batch manifest JSON", type=["json"])
            if st.form_submit_button("Submit batch", disabled=disabled):
                if source is None or manifest is None:
                    st.error("Choose both a CSV batch and its declared manifest.")
                elif source.size > config.max_upload_bytes or manifest.size > 16384:
                    st.error("The selected upload exceeds the workspace limits.")
                else:
                    try:
                        submit_upload(
                            workspace, source.getvalue(), manifest.getvalue(), source.name
                        )
                    except (ValueError, UnicodeError):
                        st.error("Choose a valid manifest JSON object within the metadata limit.")
                    else:
                        send(workspace)
                        st.rerun()
    if workspace.allowed("score:submit") or workspace.allowed("train:submit"):
        with panels["Scoring / training"]:
            choices = [
                name
                for name, p in (("Scoring", "score:submit"), ("Training", "train:submit"))
                if workspace.allowed(p)
            ]
            st.caption(
                "The API requires an approved immutable bundle digest for scoring. Resolved model identity is read-only when supplied in the job result."
            )
            operation = st.selectbox("Job type", choices)
            if workspace.accepted_batches:
                batches = [*reversed(workspace.accepted_batches), "Enter batch ID"]
                chosen = st.selectbox(
                    "Accepted batch",
                    batches,
                    format_func=lambda value: (
                        "Accepted in this session · " + value[:8]
                        if value != "Enter batch ID"
                        else value
                    ),
                )
                if chosen == "Enter batch ID":
                    batch = st.text_input("Accepted batch ID")
                else:
                    batch = chosen
                    st.caption("Selected batch: " + batch)
            else:
                batch = st.text_input(
                    "Accepted batch ID",
                    help="An accepted intake from this session is selected automatically when available.",
                )
            with st.form("model_job"):
                with st.expander("Scoring bundle", expanded=operation == "Scoring"):
                    bundle = st.text_input(
                        "Approved immutable bundle digest (scoring only)",
                        max_chars=64,
                        help="Approved-bundle discovery is not supplied by the API. Obtain the exact digest from the deployment owner.",
                    )
                if st.form_submit_button("Submit job", disabled=disabled):
                    try:
                        payload = {"batch_id": str(UUID(batch))}
                        if operation == "Scoring":
                            if len(bundle) != 64 or any(
                                c not in "0123456789abcdef" for c in bundle
                            ):
                                raise ValueError()
                            payload["bundle_digest"] = bundle
                    except ValueError:
                        st.error("Enter a valid accepted batch ID and, for scoring, bundle digest.")
                    else:
                        path = "/v1/scoring-runs" if operation == "Scoring" else "/v1/training-runs"
                        try:
                            with loading():
                                accepted = workspace.api.get_batch(UUID(batch))
                            if accepted.state != IngestionStatus.ACCEPTED:
                                st.warning(
                                    "This batch is not accepted. Resolve intake findings before submitting a model job."
                                )
                            else:
                                workspace.begin(operation, path, payload)
                                send(workspace)
                                st.rerun()
                        except ApiFailure as error:
                            render_error(error)
    with panels["Jobs"]:
        st.subheader("Durable jobs")
        with st.form("reconnect_job"):
            identity = st.text_input(
                "Reconnect to job ID", value=str(st.query_params.get("job", ""))
            )
            if st.form_submit_button("Reconnect"):
                try:
                    value = str(UUID(identity))
                    workspace.reconnect_job(value)
                    st.query_params["job"] = value
                    st.rerun()
                except ValueError:
                    st.error("Enter a valid job ID.")
        if not workspace.jobs:
            st.info(
                "No connected jobs. Submit an authorized operation or reconnect using its job ID."
            )
        for job_id in workspace.jobs[-20:]:
            render_job(workspace, job_id, disabled)
