import copy
from uuid import UUID, uuid4

from tests.ui.helpers import click, rendered_text, screen
from ui import dto
from ui.mock.backend import fixture_config, identity
from ui.mock.extensions import LateTimeline


def test_original_review_lineage_and_comparison_survive_correction(monkeypatch):
    app, workspace, backend = screen(
        monkeypatch, "History", config=fixture_config(late_data_context=True)
    )
    timeline = LateTimeline(backend)
    workspace.authenticate()
    case = UUID(timeline.original_id)
    workspace.api.assign(case, dto.AssignmentRequest(expected_version=0), key=uuid4())
    workspace.api.start_review(case, dto.VersionedRequest(expected_version=1), key=uuid4())
    workspace.api.review(
        case,
        dto.ReviewRequest(
            expected_version=2, conclusion="NEEDS_MORE_INFORMATION", note="Original note"
        ),
        key=uuid4(),
    )
    original = copy.deepcopy(backend.histories[str(case)])
    timeline.advance("CORRECTED")
    workspace.selected_case = str(case)
    app.run()
    assert not app.exception and "Original note" in rendered_text(app)
    next(s for s in app.selectbox if s.label == "History type").set_value("scores").run()
    click(app, "Compare selected assessments")
    assert any("Earlier" in table.value.columns for table in app.table)
    assert any("Field ID" in table.value.columns for table in app.table)
    assert backend.histories[str(case)] == original
    assert workspace.pinned_scores == {}  # Comparing history does not repin/open a case.


def test_history_notes_denied_and_paging_is_bounded(monkeypatch):
    app, workspace, backend = screen(monkeypatch, "History", permissions=("case:read",))
    workspace.selected_case = identity("case-1")
    backend.histories[workspace.selected_case] = [
        {"event_id": identity(f"history-{i}"), "note": "Private note", "action": "case:review"}
        for i in range(25)
    ]
    app.run()
    assert "Not permitted to view" in rendered_text(app) and "Private note" not in rendered_text(
        app
    )
    assert next(b for b in app.button if b.label == "Later history").disabled is False
    click(app, "Later history")
    assert workspace.history_after[workspace.selected_case + ":reviews"] == 20
