"""Clean synthetic service journey, invoked only by the explicit development demo."""

import json
from dataclasses import dataclass, field

from ui.mock.backend import MockBackend, create_workspace, fixture_config, identity
from ui.mock.extensions import LateTimeline
from ui.pages.operations import submit_upload
from ui.state import Workspace


@dataclass
class DemoSession:
    workspace: Workspace
    backend: MockBackend
    timeline: LateTimeline
    receipts: list[dict[str, str]] = field(default_factory=list)
    stage: str = "Ready"

    def process(self, operation: str) -> str:
        if operation == "Validate synthetic batch":
            manifest = json.dumps(
                {
                    "source_id": "synthetic-source",
                    "data_tier": "research",
                    "provenance_limitations": [
                        "Generated fixture; development demonstration only."
                    ],
                }
            ).encode()
            submit_upload(self.workspace, b"F1\n1\n", manifest, "generated-synthetic.csv")
        elif operation == "Publish synthetic queue":
            self.workspace.begin(
                "Scoring",
                "/v1/scoring-runs",
                {"batch_id": identity("batch"), "bundle_digest": "a" * 64},
            )
        else:
            raise ValueError("Unsupported demo operation")
        result = self.workspace.submit()
        job_id = str(result["job_id"])
        self.backend.complete_job(job_id)
        job = self.workspace.poll(job_id, force=True)
        if job["state"] != "SUCCEEDED":
            raise ValueError("Synthetic job did not complete")
        self.workspace.pending = None
        self.receipts.append({"operation": operation, "job_id": job_id, "state": job["state"]})
        self.stage = operation
        return job_id

    def advance(self, stage: str) -> str:
        case_id = self.timeline.advance(stage)
        self.stage = stage
        self.workspace.cache.clear()
        return case_id


def create_demo() -> DemoSession:
    config = fixture_config(
        extension_pages=(
            "Models",
            "Retraining proposals",
            "Evidence reports",
            "Source health",
            "Pilot metrics",
        ),
        late_data_context=True,
        show_deployment_status=True,
    )
    workspace, backend = create_workspace(config=config)
    timeline = LateTimeline(backend)
    workspace.now = lambda: timeline.now
    return DemoSession(workspace, backend, timeline)


def render_controls(demo: DemoSession) -> None:
    import streamlit as st

    if not demo.workspace.identity:
        return
    with st.sidebar.expander("Developer demo tools", expanded=False):
        _render_controls(demo)


def _render_controls(demo: DemoSession) -> None:
    import streamlit as st

    disabled = bool(
        demo.workspace.pending
        and demo.workspace.pending.state in {"PENDING", "UNKNOWN", "CONFLICT"}
    )
    st.caption("Synthetic demo controls · No real data or worker")
    st.text("Stage: " + demo.stage)
    for operation in ("Validate synthetic batch", "Publish synthetic queue"):
        if st.button(operation, key="demo_" + operation, disabled=disabled):
            job = demo.process(operation)
            st.query_params["job"] = job
            st.session_state["navigate_to"] = "Operations"
            st.rerun()
    stage = st.selectbox(
        "Simulated late-data stage",
        ["BUFFERING", "STALE", "PROVISIONAL_HIGHER", "CORRECTED", "RECONCILED"],
    )
    if st.button("Publish next synthetic assessment"):
        demo.advance(stage)
        st.session_state["navigate_to"] = "Review queue"
        st.rerun()
    if st.button("Process pending synthetic jobs", disabled=disabled):
        for job_id in demo.workspace.jobs:
            if demo.backend.jobs[job_id]["state"] == "PENDING":
                demo.backend.complete_job(job_id)
                demo.workspace.poll(job_id, force=True)
        st.rerun()
    selected = demo.workspace.selected_case
    reviewable = bool(selected and demo.backend.cases.get(selected, {}).get("state") == "IN_REVIEW")
    if st.button("Simulate next review acknowledgement loss", disabled=disabled or not reviewable):
        demo.backend.inject(
            "POST", "/v1/cases/" + str(selected) + "/reviews", "after_commit_timeout"
        )
        demo.stage = "Next review acknowledgement will be lost once"
        st.rerun()
    if st.button("Open original reviewed case"):
        demo.workspace.selected_case = demo.timeline.original_id
        st.session_state["navigate_to"] = "History"
        st.rerun()
