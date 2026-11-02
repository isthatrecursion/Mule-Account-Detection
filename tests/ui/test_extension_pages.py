import pytest
from streamlit.testing.v1 import AppTest

from tests.ui.helpers import rendered_text, screen
from ui.extensions import Gate
from ui.mock.backend import create_workspace, fixture_config
from ui.pages.extensions import monitoring_url


@pytest.mark.parametrize(
    "page", ["Models", "Source health", "Evidence reports", "Retraining proposals"]
)
def test_disabled_extension_is_explicitly_unavailable(page):
    code = (
        "from ui.mock.backend import create_workspace\nfrom ui.pages.extensions import render\nworkspace,_=create_workspace()\nworkspace.authenticate()\nrender(workspace,page="
        + repr(page)
        + ")"
    )
    app = AppTest.from_string(code).run()
    assert not app.exception and "Not available in this build" in rendered_text(app)


@pytest.mark.parametrize(
    "page", ["Models", "Source health", "Evidence reports", "Retraining proposals"]
)
def test_enabled_extensions_are_read_only_and_mock_backed(monkeypatch, page):
    app, _, _ = screen(monkeypatch, page, config=fixture_config(extension_pages=(page,)))
    app.run()
    assert not app.exception and "Proposed API contract" in rendered_text(app)
    assert all(b.label not in {"Approve", "Promote", "Rollback"} for b in app.button)
    if page in {"Models", "Evidence reports"}:
        tables = " ".join(str(t.value.to_dict()) for t in app.table)
        assert "BLOCKED" in tables and "Qualified independent" in tables
        if page == "Evidence reports":
            assert "NOT_RUN" in tables and "SYNTHETIC_ENGINEERING" in rendered_text(app)


def test_missing_gate_evidence_never_passes():
    assert Gate(name="Missing", state="PASSED").state == "NOT_RUN"
    gate = Gate(name="Zero denominator", state="PASSED", numerator=0, denominator=0, trials=1)
    assert gate.state == "NOT_RUN" and gate.reasons


def test_monitoring_links_only_use_configured_source_and_environment():
    url = monitoring_url("https://grafana.example.test", "research", "source-1", ("source-1",))
    assert url.endswith("var-environment=research&var-source=source-1")
    assert (
        monitoring_url("https://grafana.example.test", "research", "private-note", ("source-1",))
        is None
    )
    assert monitoring_url("javascript:alert(1)", "research", "source-1", ("source-1",)) is None
    assert (
        monitoring_url(
            "https://grafana.example.test",
            "research",
            "source?token=secret",
            ("source?token=secret",),
        )
        is None
    )


def test_normal_client_does_not_call_unapproved_extension_route():
    workspace, backend = create_workspace()
    workspace.api.config = fixture_config().model_copy(update={"mock_mode": False})
    from ui.errors import NotFound

    with pytest.raises(NotFound):
        workspace.api.extension("models")
    assert not backend.calls
