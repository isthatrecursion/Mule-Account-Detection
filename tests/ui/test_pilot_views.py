from tests.ui.helpers import rendered_text, screen
from ui.extensions import DeploymentDecision, PilotMetric
from ui.mock.backend import fixture_config, identity


def test_server_shadow_decision_and_metric_denominators_are_visible(monkeypatch):
    app, _, backend = screen(
        monkeypatch,
        "Pilot metrics",
        config=fixture_config(extension_pages=("Pilot metrics",), show_deployment_status=True),
    )
    record = backend.extension_payloads["deployment-status"]["decision"]
    record["mode"] = "SHADOW"
    app.run()
    assert (
        not app.exception
        and "Shadow pilot: recommendations only, no account actions" in rendered_text(app)
    )
    assert str(record["record_id"]) in rendered_text(app)
    assert record["allowed_actions"][0] in rendered_text(app)
    assert all(
        {
            "Numerator",
            "Denominator",
            "Labels available",
            "Label denominator",
            "Outcome maturity",
        }.issubset(table.value.columns)
        for table in app.table
    )
    tables = " ".join(str(table.value.to_dict()) for table in app.table)
    assert "BLOCKED" in tables and "Qualified mature" in tables
    assert "Mature labels / eligible records" in tables


def test_missing_denominators_and_labels_do_not_become_success():
    metric = PilotMetric(
        metric_id="adjudicated_yield",
        name="Yield",
        population="REVIEWED_SAMPLE",
        numerator=0,
        denominator=0,
        labels_available=0,
        labels_eligible=100,
        state="PASSED",
    )
    assert metric.state == "NOT_RUN"
    decision = DeploymentDecision(
        record_id=identity("decision"),
        revision="v1",
        mode="PILOT",
        data_tier="research",
        model_tier="research_demo",
    )
    assert decision.mode == "BLOCKED" and not decision.allowed_actions
    decision = DeploymentDecision(
        record_id=identity("decision"),
        revision="v2",
        mode="PILOT",
        data_tier="research",
        model_tier="research_demo",
        approved_by="fixture-reviewer",
    )
    assert decision.mode == "BLOCKED"


def test_decision_binding_mismatch_is_rejected(monkeypatch):
    app, _, backend = screen(
        monkeypatch, "Pilot metrics", config=fixture_config(extension_pages=("Pilot metrics",))
    )
    backend.extension_payloads["pilot-metrics"]["decision_record_id"] = identity("another-decision")
    app.run()
    assert "CONTRACT" in rendered_text(app) and not app.table
