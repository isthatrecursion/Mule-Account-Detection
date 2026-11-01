"""Show immutable context before interpretation-sensitive evidence."""

from typing import Any

import streamlit as st

from ui.components.time_fmt import format_time


def render_provenance(case: dict[str, Any], timezone: str = "UTC") -> None:
    score = case.get("score") or {}
    for label, key in (
        ("Observation cutoff", "observation_cutoff"),
        ("Published at", "published_at"),
    ):
        st.text(label + ": " + format_time(score.get(key), timezone))
    for label, key in (
        ("Selected score", "score_id"),
        ("Model", "model_id"),
        ("Bundle", "bundle_digest"),
        ("Batch", "batch_id"),
        ("Policy", "policy_hash"),
        ("Dictionary", "dictionary_version"),
        ("Feature snapshot", "snapshot_id"),
        ("Queue", "queue_version"),
    ):
        st.text(label + ": " + str(case.get(key) or "Not supplied"))
