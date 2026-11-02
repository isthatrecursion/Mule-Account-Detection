import pytest

from tests.ui.helpers import click, input_value, rendered_text, screen
from ui.mock.backend import create_workspace, fixture_config, identity
from ui.pages.operations import finding_rows, submit_upload


def intake(workspace):
    workspace.authenticate()
    submit_upload(workspace, b"F1\n1\n", b'{"source_id":"synthetic"}', "fixture.csv")
    return workspace.submit()["job_id"]


def test_upload_validation_and_duplicate_submit():
    workspace, backend = create_workspace()
    workspace.authenticate()
    for content, manifest in (
        (b"", b"{}"),
        (b"data", b"[]"),
        (b"data", b"not JSON"),
        (b"data", b"x" * 16385),
    ):
        with pytest.raises(ValueError):
            submit_upload(workspace, content, manifest, "fixture.csv")
    assert not backend.effects
    job = intake(workspace)
    assert workspace.submit()["job_id"] == job and len(backend.effects) == 1


def test_polling_stops_at_deadline_and_terminal_but_manual_refresh_works():
    workspace, backend = create_workspace(config=fixture_config(poll_seconds=3, max_poll_seconds=6))
    tick = [0.0]
    workspace.clock = lambda: tick[0]
    job = intake(workspace)
    workspace.poll(job)
    calls = len(backend.calls)
    tick[0] = 6
    assert not workspace.polling_active()
    workspace.poll(job)
    assert len(backend.calls) == calls
    backend.complete_job(job)
    assert workspace.poll(job, force=True)["state"] == "SUCCEEDED"
    calls = len(backend.calls)
    tick[0] = 50
    workspace.poll(job)
    assert len(backend.calls) == calls


def test_query_job_reconnect_and_quarantine_are_visible_without_raw_rows(monkeypatch):
    app, workspace, backend = screen(monkeypatch, "Operations")
    job = intake(workspace)
    backend.complete_job(job, outcome="QUARANTINED", codes=["SCHEMA_HEADER"])
    backend.jobs[job]["result"]["raw_rows"] = "PRIVATE-RAW-ROW"
    workspace.jobs.clear()
    app.query_params["job"] = job
    app.run()
    assert not app.exception and workspace.jobs == [job]
    text = rendered_text(app)
    assert "[SUCCEEDED]" in text and "[QUARANTINED]" in text
    assert "No scores were published" in text and "PRIVATE-RAW-ROW" not in text
    assert any("SCHEMA_HEADER" in str(table.value) for table in app.table)
    assert not workspace.polling_active()


def test_retry_visibility_state_guard_and_persisted_id(monkeypatch):
    app, workspace, backend = screen(monkeypatch, "Operations")
    job = intake(workspace)
    app.run()
    assert next(b for b in app.button if b.label == "Request authorized retry").disabled
    backend.complete_job(job, state="FAILED")
    click(app, "Refresh job status")
    assert not next(b for b in app.button if b.label == "Request authorized retry").disabled
    input_value(app, "Retry reason", "Dependency restored")
    click(app, "Request authorized retry")
    assert workspace.last_result["job_id"] == job
    assert workspace.pending is None
    other, limited, limited_backend = screen(
        monkeypatch, "Operations", permissions=("batch:intake", "batch:read", "job:read")
    )
    limited_job = intake(limited)
    limited_backend.complete_job(limited_job, state="FAILED")
    other.run()
    assert not any(b.label == "Request authorized retry" for b in other.button)


def test_scoring_requires_accepted_batch_and_exact_bundle(monkeypatch):
    app, workspace, backend = screen(monkeypatch, "Operations")
    app.run()
    input_value(app, "Accepted batch ID", identity("batch"))
    input_value(app, "Approved immutable bundle digest (scoring only)", "a" * 64)
    backend.batch_state = "QUARANTINED"
    click(app, "Submit job")
    assert not backend.effects and "not accepted" in rendered_text(app)
    backend.batch_state = "ACCEPTED"
    click(app, "Submit job")
    assert len(backend.effects) == 1 and workspace.last_result["job_id"]


def test_missing_finding_metadata_is_not_invented():
    row = finding_rows({"finding_codes": ["UNRECOGNIZED_RULE"]})[0]
    assert row["Affected count"] == "Not supplied" and row["Blocks"] == "Not supplied"
    assert "registered source" in row["Safe message"]


def test_invalid_query_job_is_safe(monkeypatch):
    app, _, _ = screen(monkeypatch, "Operations")
    app.query_params["job"] = "invalid"
    app.run()
    assert not app.exception and "job ID is invalid" in rendered_text(app)
