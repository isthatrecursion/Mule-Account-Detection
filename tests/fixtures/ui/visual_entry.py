"""Explicit local synthetic rehearsal entrypoint. Never imported by the normal UI launcher."""

import json
import os
import time
from pathlib import Path

import streamlit as st
from pydantic import SecretStr

from ui import runtime
from ui.api_client import ApiClient
from ui.app import render
from ui.auth import LoginRequired, UserCredential
from ui.config import UiConfig
from ui.state import Workspace

if os.environ.get("MULE_TEST_ENVIRONMENT") != "test" or not os.environ.get(
    "MULE_TEST_UI_STATE_FILE"
):
    raise RuntimeError("An explicit isolated test rehearsal is required")
private = Path(os.environ["MULE_TEST_UI_STATE_FILE"]).resolve()
root = Path(__file__).resolve().parents[3]
if not private.is_relative_to(root / "scratch"):
    raise RuntimeError("Test state must remain in private scratch storage")
data = json.loads(private.read_bytes())


class FixtureProvider:
    closed = False

    def credential(self):
        if self.closed or data["expires_at"] <= time.time():
            raise LoginRequired()
        return UserCredential(
            data["actor_id"], data["expires_at"], "isolated-visual", SecretStr(data["token"])
        )

    def logout(self):
        self.closed = True


def create():
    settings = UiConfig(
        environment="test",
        api_base_url=data["api_base_url"],
        api_issuer="https://isolated.example.test",
        api_audience="review-api-test",
        gateway_url="https://gateway.example.test/session",
        gateway_issuer="https://gateway.example.test",
        gateway_audience="test-ui",
        gateway_jwks_url="https://gateway.example.test/keys",
        gateway_service_token=SecretStr("isolated-test-only-service-credential"),
        login_url="https://gateway.example.test/login",
    )
    result = Workspace(ApiClient(settings, FixtureProvider()))
    result.queue_version = data["queue_version"]
    result.selected_case = data["case_id"]
    return result


runtime.create_workspace = create
if "page" not in st.session_state:
    st.session_state["page"] = data.get("start_page", "Review queue")
render()
st.caption("ISOLATED SYNTHETIC REHEARSAL · NO ORGANIZATION LOGIN · NO REAL ACCOUNT DATA")
