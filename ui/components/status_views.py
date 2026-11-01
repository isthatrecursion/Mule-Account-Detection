"""Static safe error wording; server messages never enter error presentations."""

from collections.abc import Iterator
from contextlib import contextmanager

import streamlit as st

from ui.errors import ApiFailure, Conflict, Forbidden, ServerUnavailable


@contextmanager
def loading() -> Iterator[None]:
    with st.spinner("Loading authorized API data…"):
        yield


def empty() -> None:
    st.info("No records match this view. Check the selected version and filters.")


def render_error(error: ApiFailure) -> None:
    st.error(error.safe_message)
    st.text("Code: " + error.code + " · Request ID: " + (error.request_id or "Not available"))


def forbidden() -> None:
    render_error(Forbidden())


def conflict() -> None:
    render_error(Conflict())


def unavailable() -> None:
    render_error(ServerUnavailable("UNAVAILABLE"))
