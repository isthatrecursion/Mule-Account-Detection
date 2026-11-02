import copy
from uuid import UUID, uuid4

import pytest

from tests.ui.helpers import click, rendered_text, screen
from ui import dto
from ui.copy import find_forbidden
from ui.mock.backend import fixture_config
from ui.mock.extensions import LateTimeline, assessment


@pytest.mark.parametrize("terminal", ["CORRECTED", "RECONCILED"])
def test_ten_minute_timeline_keeps_original_review_and_versions(monkeypatch, terminal):
    app, workspace, backend = screen(
        monkeypatch, "Case evidence", config=fixture_config(late_data_context=True)
    )
    timeline = LateTimeline(backend)
    workspace.now = lambda: timeline.now
    workspace.authenticate()
    original = copy.deepcopy(backend.cases[timeline.original_id]["score"])
    workspace.selected_case = timeline.original_id
    workspace.api.assign(
        UUID(timeline.original_id), dto.AssignmentRequest(expected_version=0), key=uuid4()
    )
    workspace.api.start_review(
        UUID(timeline.original_id), dto.VersionedRequest(expected_version=1), key=uuid4()
    )
    workspace.api.review(
        UUID(timeline.original_id),
        dto.ReviewRequest(expected_version=2, conclusion="NEEDS_MORE_INFORMATION"),
        key=uuid4(),
    )
    review = copy.deepcopy(backend.histories[timeline.original_id])
    app.run()
    assert not app.exception
    for stage in ("BUFFERING", "STALE", "PROVISIONAL_HIGHER", terminal):
        case_id = timeline.advance(stage)
        workspace.selected_case = case_id
        next(widget for widget in app.text_input if widget.label == "Case ID").set_value(
            case_id
        ).run()
        assert not app.exception
        text = rendered_text(app)
        assert "[" + stage + "]" in text
        assert not find_forbidden(text)
        if stage == "PROVISIONAL_HIGHER":
            assert "no adverse-action authority" in text
            assert "Authoritative last complete assessment" in text
            assert "7 minutes since original assessment" in text
    assert backend.cases[timeline.original_id]["score"] == original
    assert backend.histories[timeline.original_id] == review
    assert (
        workspace.pinned_scores[timeline.original_id]
        == backend.cases[timeline.original_id]["score_id"]
    )


def test_queue_correction_notice_retains_opened_version(monkeypatch):
    app, workspace, backend = screen(monkeypatch, config=fixture_config(late_data_context=True))
    timeline = LateTimeline(backend)
    app.run()
    old = workspace.queue_version
    timeline.advance("CORRECTED")
    app.run()
    assert workspace.queue_version == old and "Queue movement: 0 entered, 0 left" in rendered_text(
        app
    )
    click(app, "Open newer queue")
    assert workspace.queue_version != old


def test_unavailable_current_and_retained_complete_assessment_stay_separate(monkeypatch):
    app, workspace, backend = screen(
        monkeypatch, "Case evidence", config=fixture_config(late_data_context=True)
    )
    from ui.mock.backend import identity

    workspace.selected_case = identity("case-200")
    backend.extension_payloads["case-context/" + workspace.selected_case]["baseline"] = assessment(
        backend.cases[identity("case-1")]
    )
    app.run()
    assert not app.exception
    assert "Retained last complete assessment" in rendered_text(app)
    assert [metric.value for metric in app.metric][:3] == ["—", "—", "—"]
    assert [metric.value for metric in app.metric][-3:] == ["1", "1", "100.00"]
