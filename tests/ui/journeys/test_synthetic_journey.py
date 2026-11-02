from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.ui.helpers import click, input_value, rendered_text, screen
from ui.mock.backend import identity
from ui.pages.exports import authorized_download

ROOT = Path(__file__).resolve().parents[3]


def test_clean_demo_upload_to_export_and_late_correction(monkeypatch):
    monkeypatch.setenv("MAD_UI_FIXTURE_ENTRY", "demo")
    app = AppTest.from_file(str(ROOT / "ui/mock/entry.py"), default_timeout=30).run()
    assert not app.exception
    demo = app.session_state["synthetic_demo"]
    click(app, "Validate synthetic batch")
    assert demo.receipts[-1]["state"] == "SUCCEEDED"
    assert "[ACCEPTED]" in rendered_text(app)
    click(app, "Publish synthetic queue")
    next(b for b in app.sidebar.button if b.label == "Review queue").click().run()
    click(app, "Open case")
    selected = demo.workspace.selected_case
    score = demo.workspace.pinned_scores[selected]
    click(app, "Assign case")
    click(app, "Start review")
    click(app, "Simulate next review acknowledgement loss")
    app.text_area[0].set_value("Synthetic journey note")
    click(app, "Save review")
    key = demo.workspace.pending.key
    app.run()
    assert demo.workspace.pending.key == key
    click(app, "Check outcome / retry the same request")
    assert demo.workspace.pending is None
    assert len(demo.backend.histories[selected]) == 3
    next(b for b in app.sidebar.button if b.label == "History").click().run()
    assert "Synthetic journey note" in rendered_text(app)
    next(b for b in app.sidebar.button if b.label == "Exports").click().run()
    input_value(app, "Export reason", "Synthetic acceptance walkthrough")
    app.checkbox[0].check()
    click(app, "Authorize export")
    export = demo.workspace.last_result["job_id"]
    click(app, "Process pending synthetic jobs")
    assert b"case_id" in authorized_download(demo.workspace, export, demo.workspace.fingerprint)
    assert demo.backend.jobs[export]["state"] == "SUCCEEDED"
    next(s for s in app.sidebar.selectbox if s.label == "Simulated late-data stage").set_value(
        "CORRECTED"
    )
    click(app, "Publish next synthetic assessment")
    assert "newer queue" in rendered_text(app)
    click(app, "Open original reviewed case")
    assert "Synthetic journey note" in rendered_text(app)
    assert demo.backend.cases[selected]["score_id"] == score


@pytest.mark.parametrize(
    "fault,code",
    [
        (403, "DENIED"),
        (409, "CONFLICT"),
        (429, "RATE_LIMITED"),
        (500, "UNAVAILABLE"),
        ("connection", "UNAVAILABLE"),
    ],
)
def test_queue_failure_variants_are_safe_and_retry_bounded(monkeypatch, fault, code):
    app, _, backend = screen(monkeypatch)
    backend.inject("GET", "/v1/queues", fault, fault, fault)
    app.run()
    assert not app.exception and code in rendered_text(app)
    assert not app.table


def test_quarantine_and_new_unavailable_record_are_explicit(monkeypatch):
    app, workspace, backend = screen(monkeypatch, "Case evidence")
    workspace.selected_case = identity("case-200")
    app.run()
    assert not app.exception and all(m.value == "—" for m in app.metric)
