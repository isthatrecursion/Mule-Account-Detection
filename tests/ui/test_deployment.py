import importlib.util
from pathlib import Path

import pytest

from ui.auth import LoginRequired
from ui.runtime import create_workspace

ROOT = Path(__file__).resolve().parents[2]


def test_deployment_contract_has_private_services_and_secret_boundaries():
    spec = importlib.util.spec_from_file_location(
        "verify_ui_deployment", ROOT / "scripts/verify_ui_deployment.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.verify(ROOT)["static_deployment_contract"] == "PASSED"


def test_direct_ui_bypass_and_spoofed_headers_do_not_supply_identity(monkeypatch):
    from types import SimpleNamespace

    from tests.ui_helpers import config

    monkeypatch.setattr("ui.runtime.UiConfig.load", lambda root: config())
    monkeypatch.setattr(
        "ui.runtime.st.context",
        SimpleNamespace(
            headers={
                "X-User": "reviewer",
                "X-Email": "reviewer@example.test",
                "Authorization": "Bearer forged",
            }
        ),
    )
    with pytest.raises(LoginRequired):
        create_workspace()
