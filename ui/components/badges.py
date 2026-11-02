"""Category and text marker carry status even when color is removed."""

import streamlit as st

from ui.enums import DisplayEnum


def badge_text(category: str, state: DisplayEnum) -> str:
    presentation = state.presentation
    return f"{category}: {presentation.marker} {presentation.label} — {presentation.explanation}"


def render_badge(category: str, state: DisplayEnum) -> None:
    st.text(badge_text(category, state))
