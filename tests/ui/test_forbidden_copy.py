import pytest

from tests.ui.helpers import rendered_text, screen
from ui.copy import find_forbidden
from ui.mock.backend import fixture_config, identity


@pytest.mark.parametrize(
    "page",
    [
        "Review queue",
        "Case evidence",
        "History",
        "Operations",
        "Exports",
        "Models",
        "Evidence reports",
        "Retraining proposals",
        "Source health",
        "Pilot metrics",
    ],
)
def test_authored_pages_do_not_overclaim(monkeypatch, page):
    config = fixture_config(
        extension_pages=(
            "Models",
            "Evidence reports",
            "Retraining proposals",
            "Source health",
            "Pilot metrics",
        ),
        show_deployment_status=True,
    )
    app, workspace, _ = screen(monkeypatch, page, config=config)
    workspace.selected_case = identity("case-1")
    app.run()
    assert not app.exception
    assert not find_forbidden(rendered_text(app))
