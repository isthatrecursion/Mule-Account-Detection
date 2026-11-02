"""Behavior regressions for the investigation layout and contextual actions."""

import pytest

from tests.ui.helpers import click, input_value, rendered_text, screen
from tests.ui.test_operations import intake
from tests.ui.test_queue import queue_cases
from ui.errors import ApiFailure
from ui.mock.backend import create_workspace, identity
from ui.pages.exports import authorized_download, reconnect_export
from ui.permissions import build_navigation, navigation_groups


def test_case_row_opens_exact_record_and_back_restores_page_and_filters(monkeypatch):
    app, workspace, backend = screen(monkeypatch)
    app.run()
    click(app, "Next page")
    cases = queue_cases(app)
    cursor = dict(workspace.cursor)
    target = next(b for b in app.button if str(b.key).startswith("open_case_"))
    case_id = str(target.key).removeprefix("open_case_")
    target.click().run()
    assert not app.exception and workspace.selected_case == case_id
    assert workspace.selected_record == backend.cases[case_id]["record_key"]
    assert workspace.selected_queue == identity("queue")
    assert not any(s.label == "Case to open" for s in app.selectbox)
    click(app, "Back to queue")
    assert workspace.cursor == cursor and queue_cases(app) == cases


def test_assignment_shortcuts_are_server_filtered_and_survive_case_navigation(monkeypatch):
    app, workspace, backend = screen(monkeypatch)
    workspace.authenticate()
    case = backend.cases[identity("case-3")]
    case.update(assignee=workspace.identity["actor_id"], state="ASSIGNED")
    app.run()
    next(s for s in app.selectbox if s.label == "Assignment").set_value("Assigned to me").run()
    assert queue_cases(app) == {case["case_id"]}
    click(app, "Open case")
    click(app, "Back to queue")
    assert queue_cases(app) == {case["case_id"]}
    assert workspace.queue_filters["assignee"] == workspace.identity["actor_id"]
    next(s for s in app.selectbox if s.label == "Assignment").set_value("Unassigned (queued)").run()
    assert case["case_id"] not in queue_cases(app)
    assert workspace.queue_filters["state"] == "QUEUED"


def test_navigation_separates_preview_and_live_and_honors_permissions():
    workspace, _ = create_workspace()
    workspace.authenticate()
    preview = ("Models", "Source health", "Pilot metrics")
    live = build_navigation(workspace.identity, preview)
    assert not set(preview).intersection(live)
    groups = navigation_groups(build_navigation(workspace.identity, preview, mock_mode=True))
    assert groups["Investigation"] == ["Review queue", "Case evidence", "History", "Exports"]
    assert groups["Operations"] == ["Operations"]
    assert groups["Preview · Synthetic only"] == list(preview)
    limited, _ = create_workspace(permissions=("job:read",))
    limited.authenticate()
    assert build_navigation(limited.identity, preview, mock_mode=True) == ["Operations"]


def test_case_context_and_review_render_before_detailed_evidence(monkeypatch):
    app, workspace, _ = screen(monkeypatch, "Case evidence")
    workspace.selected_case = identity("case-1")
    app.run()
    assert not app.exception
    assert any(b.label == "Assign case" for b in app.button)
    provenance = next(e for e in app.expander if e.label == "Assessment provenance")
    assert not provenance.proto.expanded
    text = rendered_text(app)
    assert text.count("Published at:") == 1
    assert text.count("Source completeness:") == 1
    assert sum("Contributions show model associations" in c.value for c in app.caption) == 1


def test_export_mixed_jobs_reconnect_and_no_preliminary_download(monkeypatch):
    app, workspace, backend = screen(monkeypatch, "Exports")
    intake_id = intake(workspace)
    workspace.pending = None
    workspace.choose_queue(identity("queue"))
    app.run()
    assert not any(b.label == "Refresh export status" for b in app.button)
    assert "No export jobs are connected" in rendered_text(app)
    input_value(app, "Export reason", "Usability verification")
    app.checkbox[0].check()
    click(app, "Authorize export")
    export_id = workspace.last_result["job_id"]
    backend.complete_job(export_id)
    click(app, "Refresh export status")
    assert len([b for b in app.button if b.label == "Refresh export status"]) == 1
    assert workspace.polling_active() and not workspace.polling_active("export")
    assert not any(path.endswith("/download") for _, path in backend.calls)
    assert not any(b.label == "Fetch authorized download" for b in app.button)
    assert b"case_id" in authorized_download(workspace, export_id, workspace.fingerprint)
    assert sum(path.endswith("/download") for _, path in backend.calls) == 1
    workspace.jobs.remove(export_id)
    input_value(app, "Export job ID", export_id)
    click(app, "Reconnect export")
    assert export_id in workspace.jobs
    with pytest.raises(ValueError):
        reconnect_export(workspace, intake_id)
    backend.export_expired.add(export_id)
    with pytest.raises(ApiFailure):
        authorized_download(workspace, export_id, workspace.fingerprint)


def test_reconnect_rejects_unrelated_or_invalid_job_without_attaching(monkeypatch):
    app, workspace, backend = screen(monkeypatch, "Exports")
    job_id = intake(workspace)
    workspace.pending = None
    workspace.jobs.clear()
    app.run()
    for value in ("invalid", job_id, identity("missing-job")):
        input_value(app, "Export job ID", value)
        click(app, "Reconnect export")
        assert not workspace.jobs and not any(
            b.label == "Refresh export status" for b in app.button
        )


def test_accepted_batch_handoff_and_logout_clear_context(monkeypatch):
    app, workspace, backend = screen(monkeypatch, "Operations")
    job = intake(workspace)
    workspace.pending = None
    backend.complete_job(job)
    workspace.poll(job, force=True)
    app.run()
    batch = next(s for s in app.selectbox if s.label == "Accepted batch")
    assert batch.value == identity("batch")
    input_value(app, "Approved immutable bundle digest (scoring only)", "a" * 64)
    click(app, "Submit job")
    assert workspace.last_result["job_id"] != job
    workspace.queue_filters = {"assignee": "private-actor"}
    click(app, "Sign out")
    assert not workspace.accepted_batches and not workspace.queue_filters


def test_export_defaults_to_queue_state_and_exact_version(monkeypatch):
    app, workspace, backend = screen(monkeypatch, "Exports")
    workspace.choose_queue(identity("queue"))
    workspace.queue_filters = {"state": "REVIEWED"}
    app.run()
    assert next(s for s in app.selectbox if s.label == "Queue to export").value == identity("queue")
    assert (
        next(s for s in app.selectbox if s.label == "Export case state filter").value == "REVIEWED"
    )
    input_value(app, "Export reason", "Reviewed cases only")
    app.checkbox[0].check()
    click(app, "Authorize export")
    request = backend.export_requests[workspace.last_result["job_id"]]
    assert request["state"] == "REVIEWED" and request["queue_version"] == identity("queue")


def test_queue_only_reader_cannot_open_case(monkeypatch):
    app, _, _ = screen(monkeypatch, permissions=("queue:read",))
    app.run()
    actions = [b for b in app.button if str(b.key).startswith("open_case_")]
    assert actions and all(b.disabled for b in actions)
