"""Normal composition accepts only an opaque gateway session, never browser identity claims."""

import hashlib
from pathlib import Path

import streamlit as st

from ui.api_client import ApiClient
from ui.auth import GatewayTokenProvider, LoginRequired
from ui.config import UiConfig
from ui.state import Workspace


def handle_fingerprint() -> str:
    handle = st.context.headers.get("X-Mule-Session", "")
    return hashlib.sha256(handle.encode()).hexdigest()


def create_workspace() -> Workspace:
    config = UiConfig.load(Path.cwd())
    if config.mock_mode:
        from ui.config import UiConfigurationError

        raise UiConfigurationError()
    handle = st.context.headers.get("X-Mule-Session", "")
    if not handle:
        raise LoginRequired()
    return Workspace(ApiClient(config, GatewayTokenProvider(config, handle)))
