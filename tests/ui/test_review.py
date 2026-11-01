from uuid import UUID, uuid4

import pytest

from tests.ui.helpers import click, rendered_text, screen
from ui import dto
from ui.errors import ApiFailure
from ui.mock.backend import identity


def reviewing(monkeypatch, **options):
    app, workspace, backend = screen(monkeypatch, "Case evidence", **options)
    workspace.authenticate()
    case = backend.cases[identity("case-1")]
    case.update(state="IN_REVIEW", case_version=2, assignee=workspace.identity["actor_id"])
    workspace.selected_case = case["case_id"]
    return app, workspace, backend, case


def test_lost_acknowledgement_rerun_retry_create_one_review(monkeypatch):
    app, workspace, backend, case = reviewing(monkeypatch)
    path = f"/v1/cases/{case['case_id']}/reviews"
    backend.inject("POST", path, "after_commit_timeout")
    app.run()
    app.text_area[0].set_value("Private fixture note")
    click(app, "Save review")
    pending = workspace.pending
    assert pending.state == "UNKNOWN" and len(backend.histories[case["case_id"]]) == 1
    assert pending.history and pending.latest["state"] == "REVIEWED"
    app.run()
    assert workspace.pending.key == pending.key and len(backend.effects) == 1
    click(app, "Check outcome / retry the same request")
    assert workspace.pending is None and len(backend.histories[case["case_id"]]) == 1
    assert workspace.last_result["event_id"] in rendered_text(app)
    app.run()
    assert len(backend.effects) == 1


def test_stale_write_conflict_requires_deliberate_new_action(monkeypatch):
    app, workspace, backend, case = reviewing(monkeypatch)
    app.run()
    workspace.begin(
        "Review",
        f"/v1/cases/{case['case_id']}/reviews",
        {"expected_version": 1, "conclusion": "NEEDS_MORE_INFORMATION"},
    )
    key = workspace.pending.key
    with pytest.raises(ApiFailure) as error:
        workspace.submit()
    assert error.value.status == 409
    app.run()
    assert "Submitted version: 1" in rendered_text(app) and "Latest version: 2" in rendered_text(
        app
    )
    assert workspace.pending.key == key and not backend.effects
    click(app, "I reviewed the latest state; prepare a new action")
    assert workspace.pending is None and any(b.label == "Save review" for b in app.button)


def test_reopen_requires_reason_and_appends_to_original_score(monkeypatch):
    app, workspace, backend, case = reviewing(monkeypatch)
    app.run()
    click(app, "Save review")
    original_score = case["score_id"]
    click(app, "Reopen case")
    assert len(backend.histories[case["case_id"]]) == 1
    assert "Enter a reason" in rendered_text(app)
    app.text_area[0].set_value("Corrected evidence requires review")
    click(app, "Reopen case")
    assert len(backend.histories[case["case_id"]]) == 2
    assert all(event["score_id"] == original_score for event in backend.histories[case["case_id"]])
    assert case["state"] == "ASSIGNED"


def test_missing_permission_and_other_assignee_are_denied(monkeypatch):
    app, workspace, backend, case = reviewing(monkeypatch, permissions=("case:read",))
    app.run()
    assert not any(b.label == "Save review" for b in app.button)
    with pytest.raises(ApiFailure) as error:
        workspace.api.review(
            UUID(case["case_id"]),
            dto.ReviewRequest(expected_version=2, conclusion="NEEDS_MORE_INFORMATION"),
            key=uuid4(),
        )
    assert error.value.status == 403
    other, session, service, second_case = reviewing(monkeypatch)
    second_case["assignee"] = "another-actor"
    other.run()
    assert not any(b.label == "Save review" for b in other.button)
    with pytest.raises(ApiFailure) as error:
        session.api.review(
            UUID(second_case["case_id"]),
            dto.ReviewRequest(expected_version=2, conclusion="NEEDS_MORE_INFORMATION"),
            key=uuid4(),
        )
    assert error.value.status == 403
