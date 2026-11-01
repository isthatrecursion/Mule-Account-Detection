"""Headless Streamlit interactions over a signed-credential HTTP boundary."""

import ast
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from mule_detection.api.auth import TokenVerifier
from tests.api_helpers import SigningAuthority
from tests.ui_helpers import SignedProvider, config
from ui.api_client import ApiClient
from ui.state import Workspace

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def browser(monkeypatch):
    authority = SigningAuthority()
    verifier = TokenVerifier(authority.config, "test")
    queue, case, score, model, batch = [str(uuid4()) for _ in range(5)]
    state = {
        "case_id": case,
        "record_key": "r1",
        "conclusion": None,
        "run_id": str(uuid4()),
        "case_version": 0,
        "state": "QUEUED",
        "assignee": None,
        "score_id": score,
        "model_id": model,
        "bundle_digest": "a" * 64,
        "batch_id": batch,
        "policy_hash": "b" * 64,
        "dictionary_version": "anonymous_v1",
        "snapshot_id": str(uuid4()),
        "queue_version": queue,
        "newer_assessment_available": False,
        "newer_score_id": None,
        "score": {
            "data_tier": "research",
            "raw_score": 0.25,
            "rank": 1,
            "percentile": 99.0,
            "freshness": "STALE",
            "completeness": "UNKNOWN",
            "assessed_as_of": None,
        },
    }
    events, effects = [], {}

    def handler(request):
        principal = verifier.verify(request.headers.get("Authorization"))
        if request.url.path == "/v1/me":
            return httpx.Response(200, json=principal.payload())
        if "case:read" not in principal.permissions or "synthetic-team" not in principal.scopes:
            return httpx.Response(403)
        if request.url.path == "/v1/queues":
            return httpx.Response(
                200, json={"items": [{"queue_version": queue, "cohort_id": batch, "version": 1}]}
            )
        if request.url.path == f"/v1/queues/{queue}/cases":
            return httpx.Response(
                200,
                json={
                    "queue_version": queue,
                    "version": 1,
                    "total": 1,
                    "items": [
                        {
                            "case_id": case,
                            "record_key": "r1",
                            "rank": 1,
                            "raw_score": 0.25,
                            "percentile": 99,
                            "state": state["state"],
                            "case_version": state["case_version"],
                            "assignee": state["assignee"],
                            "freshness": "STALE",
                        }
                    ],
                    "next": None,
                    "model_version": "1",
                },
            )
        if request.method == "POST":
            payload = json.loads(request.content)
            key = request.headers["Idempotency-Key"]
            if key in effects:
                return httpx.Response(200, json=effects[key])
            if payload["expected_version"] != state["case_version"]:
                return httpx.Response(409)
            state["case_version"] += 1
            action = request.url.path.split("/")[-1]
            state["state"] = {
                "assignment": "ASSIGNED",
                "start-review": "IN_REVIEW",
                "reviews": "REVIEWED",
                "reopen": "ASSIGNED",
            }[action]
            state["assignee"] = principal.actor_id
            event = {
                "event_id": str(uuid4()),
                "case_id": case,
                "case_version": state["case_version"],
                "score_id": score,
                "action": "case:reopen" if action == "reopen" else "case:review",
            }
            if payload.get("note"):
                event["note"] = payload["note"]
            if payload.get("reason"):
                event["note"] = payload["reason"]
            events.append(event)
            effects[key] = {k: event[k] for k in ("event_id", "case_id", "case_version")}
            return httpx.Response(200, json=effects[key])
        if request.url.path.endswith("/evidence"):
            return httpx.Response(
                200,
                json={
                    "case_id": case,
                    "score_id": score,
                    "dictionary_version": "anonymous_v1",
                    "facts": {
                        "scale": "log_odds",
                        "base_value": -0.4,
                        "raw_margin": 0.25,
                        "raw_aggregates": [
                            {
                                "raw_feature": "F123",
                                "observed_value": "<script>bad</script>",
                                "value_status": "OBSERVED",
                                "meaning_status": "UNVERIFIED",
                                "contribution": 0.65,
                            }
                        ],
                    },
                    "limitations": [],
                },
            )
        if request.url.path.endswith("/history"):
            return httpx.Response(200, json={"items": events, "next": None})
        return httpx.Response(200, json=state)

    transport = httpx.MockTransport(handler)

    def make(role="analyst", scope="synthetic-team"):
        workspace = Workspace(
            ApiClient(
                config(),
                SignedProvider(authority, role, scope),
                client=httpx.Client(base_url=config().api_base_url, transport=transport),
            )
        )
        monkeypatch.setattr("ui.runtime.create_workspace", lambda: workspace)
        return AppTest.from_file(str(ROOT / "ui/app.py"), default_timeout=20), workspace

    return make, state, events


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()


def test_analyst_queue_evidence_assignment_review_and_history(browser):
    make, state, events = browser
    app, workspace = make()
    app.run()
    assert not app.exception
    assert "Review queue" in app.header[0].value
    click(app, "Open case")
    assert not app.exception
    assert any("Stale assessment" in warning.value for warning in app.warning)
    assert any("UNVERIFIED" in str(frame.value) for frame in app.table)
    click(app, "Assign case")
    click(app, "Start review")
    app.text_area[0].set_value("<script>private note Ω</script>")
    click(app, "Save review")
    assert state["state"] == "REVIEWED" and len(events) == 3
    next(b for b in app.sidebar.button if b.label == "History").click().run()
    assert not app.exception
    assert any("<script>private note Ω</script>" in item.value for item in app.text)
    assert workspace.last_result["event_id"] == events[-1]["event_id"]


def test_reviewer_reopen_reason_is_persisted_and_displayed(browser):
    make, state, events = browser
    app, workspace = make("reviewer")
    state["state"], state["case_version"] = "REVIEWED", 3
    workspace.selected_case = state["case_id"]
    app.session_state["page"] = "Case evidence"
    app.run()
    app.text_area[0].set_value("Later corrected evidence requires review")
    click(app, "Reopen case")
    next(b for b in app.sidebar.button if b.label == "History").click().run()
    assert any("Reopen reason: Later corrected evidence" in text.value for text in app.text)


def test_operator_navigation_and_direct_scope_denial(browser):
    make, _, _ = browser
    app, workspace = make("operator")
    app.run()
    assert [b.label for b in app.sidebar.button if str(b.key).startswith("nav_")] == ["Operations"]
    assert len(app.get("file_uploader")) == 2
    assert not app.exception
    other, _ = make("analyst", "other-team")
    other.run()
    assert any("permissions" in value.value for value in other.error)


def test_unavailable_score_and_logout_clear_private_widgets(browser):
    make, state, _ = browser
    app, workspace = make()
    state["score"].update(freshness="UNAVAILABLE", raw_score=None, rank=None, percentile=None)
    workspace.selected_case = state["case_id"]
    app.session_state["page"] = "Case evidence"
    app.run()
    assert app.metric[0].value == "—"
    click(app, "Sign out")
    assert not workspace.identity and workspace.pending is None
    assert not app.table and not app.text_area


def test_missing_identity_configuration_renders_blocked_page(monkeypatch):
    from ui.config import UiConfigurationError

    def blocked():
        raise UiConfigurationError()

    monkeypatch.setattr("ui.runtime.create_workspace", blocked)
    app = AppTest.from_file(str(ROOT / "ui/app.py")).run()
    assert not app.exception
    assert any("Shared login is blocked" in value.value for value in app.warning)


def test_changed_case_requires_review_before_a_new_form_action(browser):
    make, state, events = browser
    app, workspace = make()
    state.update(state="IN_REVIEW", case_version=2, assignee=workspace.api.provider.actor)
    workspace.selected_case = state["case_id"]
    app.session_state["page"] = "Case evidence"
    app.run()
    state["case_version"] = 3
    app.run()
    assert any("case changed" in item.value for item in app.warning)
    assert not any(button.label == "Save review" for button in app.button)
    assert not events
    click(app, "Review latest case state and reset draft")
    assert any(button.label == "Save review" for button in app.button)


def test_api_downtime_and_expired_identity_are_safe_ui_states(browser, monkeypatch):
    from ui.api_client import ApiFailure

    make, _, _ = browser
    app, workspace = make()

    def unavailable():
        raise ApiFailure("UNAVAILABLE")

    monkeypatch.setattr(workspace.api, "queues", unavailable)
    app.run()
    assert not app.exception and any("unavailable" in e.value for e in app.error)
    workspace.api.provider.closed = True
    app.run()
    assert not app.exception and not app.table
    assert not workspace.identity


def test_ui_modules_never_import_database_or_model_adapters():
    forbidden = (
        "mule_detection.persistence",
        "mule_detection.training",
        "mule_detection.registry",
        "mule_detection.scoring",
        "sqlalchemy",
        "psycopg",
        "joblib",
        "lightgbm",
    )
    for path in (ROOT / "ui").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(forbidden)
            if isinstance(node, ast.Import):
                assert not any(name.name.startswith(forbidden) for name in node.names)
