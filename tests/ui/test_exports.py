import csv
import io
from uuid import UUID, uuid4

import pytest

from tests.ui.helpers import click, input_value, rendered_text, screen
from ui import dto
from ui.auth import LoginRequired
from ui.errors import ApiFailure
from ui.mock.backend import create_workspace, identity
from ui.pages.exports import authorized_download


def test_export_confirmation_scope_receipt_and_frozen_rows(monkeypatch):
    app, workspace, backend = screen(monkeypatch, "Exports")
    workspace.choose_queue(identity("queue"))
    app.run()
    input_value(app, "Export reason", "Synthetic review export")
    click(app, "Authorize export")
    assert not backend.export_requests and "confirm" in rendered_text(app)
    app.checkbox[0].check()
    click(app, "Authorize export")
    job = workspace.last_result["job_id"]
    requested = backend.export_requests[job]
    assert requested["queue_version"] == identity("queue")
    assert requested["columns"] == ["case_id", "rank", "raw_score", "state"]
    assert workspace.export_receipts[job] == requested
    backend.complete_job(job)
    backend.cases[identity("case-1")]["state"] = "REVIEWED"
    click(app, "Refresh export status")
    assert "Requested queue version: " + identity("queue") in rendered_text(app)
    assert not any(path.endswith("/download") for _, path in backend.calls)
    data = authorized_download(workspace, job, workspace.fingerprint)
    rows = list(csv.DictReader(io.StringIO(data.decode())))
    assert rows[0]["state"] == "QUEUED" and rows[0]["queue_version"] == identity("queue")
    backend.export_expired.add(job)
    with pytest.raises(ApiFailure) as expired:
        authorized_download(workspace, job, workspace.fingerprint)
    assert expired.value.status == 404
    assert not any(b.label == "Fetch authorized download" for b in app.button)
    assert any(b.label == "Authorize export" for b in app.button)


def test_export_permission_and_expiry_are_checked_per_download():
    workspace, backend = create_workspace()
    workspace.authenticate()
    job = workspace.api.export(
        dto.ExportRequest(queue_version=UUID(identity("queue")), reason="Fixture export"),
        key=uuid4(),
    )
    backend.complete_job(str(job.job_id))
    with pytest.raises(LoginRequired):
        authorized_download(workspace, str(job.job_id), "different-identity")
    backend.export_expired.add(str(job.job_id))
    with pytest.raises(ApiFailure) as error:
        authorized_download(workspace, str(job.job_id), workspace.fingerprint)
    assert error.value.status == 404
    denied, _ = create_workspace(permissions=("case:read",))
    with pytest.raises(ApiFailure) as error:
        denied.api.export(
            dto.ExportRequest(queue_version=UUID(identity("queue")), reason="Denied"), key=uuid4()
        )
    assert error.value.status == 403


def test_export_sensitive_columns_require_separate_grant():
    workspace, _ = create_workspace()
    with pytest.raises(ApiFailure) as error:
        workspace.api.export(
            dto.ExportRequest(
                queue_version=UUID(identity("queue")),
                reason="Denied sensitive export",
                columns=("case_id", "note"),
            ),
            key=uuid4(),
        )
    assert error.value.status == 403
