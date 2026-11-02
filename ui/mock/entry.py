"""Private preview entry. The normal launcher never reads this development flag."""

import os

import streamlit as st

from ui import app, runtime
from ui.mock.backend import create_workspace, fixture_config
from ui.pages import _gallery
from ui.state import Workspace


def preview_workspace() -> Workspace:
    enabled = os.environ.get("MAD_UI_FIXTURE_EXTENSIONS") == "1"
    stage = os.environ.get("MAD_UI_FIXTURE_LATE_STAGE", "")
    config = fixture_config(
        extension_pages=("Models", "Retraining proposals", "Evidence reports", "Source health")
        if enabled
        else (),
        late_data_context=bool(stage),
    )
    workspace, backend = create_workspace(config=config)
    if stage:
        from ui.mock.extensions import LateTimeline

        timeline = LateTimeline(backend)
        if stage != "COMPLETE":
            timeline.advance(stage)
        workspace.now = lambda: timeline.now
    return workspace


def render() -> None:
    mode = os.environ.get("MAD_UI_FIXTURE_ENTRY")
    if mode not in {"gallery", "workspace", "demo"}:
        st.error("Use python -m ui.dev for an explicit local fixture preview.")
        return
    if mode == "gallery":
        st.set_page_config(page_title="Evidence Review · Fixtures", layout="wide")
        _gallery.render(fixture_config())
    else:
        # Overrides exist only during this isolated render, never in normal runtime.
        original = runtime.create_workspace
        try:
            if mode == "demo":
                from ui.mock.demo import create_demo, render_controls

                demo = st.session_state.get("synthetic_demo")
                if demo is None:
                    demo = create_demo()
                    st.session_state["synthetic_demo"] = demo
                runtime.create_workspace = lambda: demo.workspace
            else:
                runtime.create_workspace = preview_workspace
            app.render()
            if mode == "demo":
                assert demo is not None
                render_controls(demo)
        finally:
            runtime.create_workspace = original


if __name__ == "__main__":
    render()
