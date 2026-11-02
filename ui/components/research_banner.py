"""Tiers are supplied by the API; this component has no tier-changing widget."""

import streamlit as st

from ui.copy import LABELS
from ui.enums import DataTier, ModelTier


def render_research(
    data_tier: str | None,
    model_tier: str | None = None,
    *,
    in_sample: bool = False,
    compact: bool = False,
) -> None:
    if (
        DataTier(data_tier or "UNKNOWN") == DataTier.RESEARCH
        or ModelTier(model_tier or "UNKNOWN") == ModelTier.RESEARCH
    ):
        (st.caption if compact else st.warning)(LABELS["research"])
    elif DataTier(data_tier or "UNKNOWN") == DataTier.UNKNOWN:
        st.warning("Data tier is not supplied or recognized. Qualification is not established.")
    if in_sample:
        st.info(LABELS["in_sample"])
