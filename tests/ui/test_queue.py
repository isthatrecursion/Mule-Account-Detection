from uuid import UUID

import pytest

from tests.ui.helpers import click, rendered_text, screen
from ui.copy import find_forbidden
from ui.mock.backend import identity


def queue_cases(app):
    return {
        str(b.key).removeprefix("open_case_")
        for b in app.button
        if str(b.key).startswith("open_case_")
    }


def test_new_publication_keeps_cursor_and_membership_until_deliberate_refresh(monkeypatch):
    app, workspace, backend = screen(monkeypatch)
    app.run()
    first = queue_cases(app)
    click(app, "Next page")
    second = queue_cases(app)
    assert len(first | second) == 50 and not first & second
    old_cursor = dict(workspace.cursor)
    new_version = backend.publish_queue()
    app.run()
    assert workspace.queue_version == identity("queue") and workspace.cursor == old_cursor
    assert "A newer queue is available" in rendered_text(app)
    assert queue_cases(app) == second
    click(app, "Previous page")
    assert queue_cases(app) == first
    click(app, "Open newer queue")
    assert workspace.queue_version == new_version and not workspace.cursor


@pytest.mark.parametrize("count", [0, 1])
def test_empty_and_single_cohort(monkeypatch, count):
    app, _, backend = screen(monkeypatch)
    backend.queue_members[identity("queue")] = [identity("case-1")] if count else []
    backend.cases[identity("case-1")]["score"]["percentile"] = 100
    app.run()
    assert not app.exception
    if count:
        assert "100.00" in [v.value for v in app.text]
    else:
        assert not app.table and "No records match" in rendered_text(app)
    assert not find_forbidden(rendered_text(app))


def test_filters_are_server_side_and_opened_context_is_recorded(monkeypatch):
    app, workspace, backend = screen(monkeypatch)
    backend.cases[identity("case-1")]["record_key"] = "opaque-" + "x" * 50
    app.run()
    click(app, "Open case")
    assert workspace.selected_record == "opaque-" + "x" * 50
    assert workspace.selected_queue == identity("queue")
    next(b for b in app.sidebar.button if b.label == "Review queue").click().run()
    next(s for s in app.selectbox if s.label == "Case state filter").set_value("REVIEWED").run()
    assert not app.table and "0 matching cases" in rendered_text(app)
    with pytest.raises(ValueError):
        workspace.api.get_queue(UUID(identity("queue")), freshness="STALE")


def test_unknown_freshness_suppresses_queue_score(monkeypatch):
    app, _, backend = screen(monkeypatch)
    backend.cases[identity("case-1")]["score"]["freshness"] = "FUTURE"
    app.run()
    values = [v.value for v in app.text]
    assert values[:4] == ["—", backend.cases[identity("case-1")]["record_key"], "—", "—"]
