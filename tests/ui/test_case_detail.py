from tests.ui.helpers import click, rendered_text, screen
from ui.copy import find_forbidden
from ui.mock.backend import fixture_evidence, identity


def case_screen(monkeypatch, index=1):
    app, workspace, backend = screen(monkeypatch, "Case evidence")
    workspace.selected_case = identity(f"case-{index}")
    return app, workspace, backend


def test_factual_evidence_imputation_signed_values_and_research(monkeypatch):
    app, _, _ = case_screen(monkeypatch)
    app.run()
    assert not app.exception
    text = rendered_text(app)
    assert "Research demonstration" in text and "Base + contributions" in text
    assert "Meaning unverified" in text
    table = str(next(t.value for t in app.table if "Field" in t.value.columns).to_dict())
    assert "F3888" in table and "IMPUTED" in table and "UNVERIFIED" in table
    assert not find_forbidden(text)


def test_unavailable_and_newer_assessment_do_not_replace_selected_score(monkeypatch):
    app, workspace, backend = case_screen(monkeypatch, 200)
    app.run()
    assert not app.exception and [m.value for m in app.metric] == ["—", "—", "—"]
    second, session, service = case_screen(monkeypatch, 2)
    second.run()
    pinned = session.pinned_scores[identity("case-2")]
    assert "A newer assessment exists" in rendered_text(second)
    click(second, "Inspect assessment history")
    assert session.pinned_scores[identity("case-2")] == pinned


def test_mismatched_evidence_is_rejected_before_contributions(monkeypatch):
    app, workspace, backend = case_screen(monkeypatch)
    evidence = fixture_evidence(backend.cases[identity("case-1")])
    evidence["score_id"] = identity("wrong-score")
    monkeypatch.setattr(workspace.api, "evidence", lambda case: evidence)
    app.run()
    assert "CONTRACT" in rendered_text(app) and not any(
        "Field" in t.value.columns for t in app.table
    )


def test_reconciliation_warning_and_unseen_category_are_visible(monkeypatch):
    app, workspace, backend = case_screen(monkeypatch)
    evidence = fixture_evidence(backend.cases[identity("case-1")])
    evidence["facts"]["raw_margin"] = 99
    evidence["facts"]["raw_aggregates"][0].update(
        observed_value="<script>literal</script>", unseen_category=True, category_frequency=0
    )
    monkeypatch.setattr(workspace.api, "evidence", lambda case: evidence)
    app.run()
    assert not app.exception and "do not reconcile" in rendered_text(app)
    assert next(t.value for t in app.table if "Field" in t.value.columns).iloc[0]["Unseen category"]
    assert "<script>literal</script>" in str(
        next(t.value for t in app.table if "Field" in t.value.columns).to_dict()
    )


def test_server_cannot_silently_change_a_pinned_case_score(monkeypatch):
    app, workspace, backend = case_screen(monkeypatch)
    app.run()
    original = workspace.pinned_scores[identity("case-1")]
    backend.cases[identity("case-1")]["score_id"] = identity("changed")
    app.run()
    assert "CONTRACT" in rendered_text(app) and not app.metric
    assert workspace.pinned_scores[identity("case-1")] == original
