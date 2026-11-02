from pathlib import Path

from streamlit.testing.v1 import AppTest

from ui.mock.backend import create_workspace

ROOT = Path(__file__).resolve().parents[2]


def screen(monkeypatch, page="Review queue", **settings):
    workspace, backend = create_workspace(**settings)
    monkeypatch.setattr("ui.runtime.create_workspace", lambda: workspace)
    app = AppTest.from_file(str(ROOT / "ui/app.py"), default_timeout=30)
    app.session_state["page"] = page
    return app, workspace, backend


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception


def input_value(app, label, value):
    next(widget for widget in app.text_input if widget.label == label).set_value(value)


def rendered_text(app):
    return " ".join(
        str(item.value)
        for kind in ("text", "caption", "warning", "info", "error", "header", "subheader", "metric")
        for item in app.get(kind)
    )
