"""Component catalogue callable only from an explicit isolated fixture entrypoint."""

import streamlit as st

from ui.components import (
    badges,
    contribution_chart,
    freshness,
    provenance_header,
    research_banner,
    score,
    status_views,
)
from ui.components.pager import CursorPager, render_pager
from ui.config import UiConfig
from ui.copy import LABELS
from ui.dto import EvidencePayload
from ui.enums import (
    CaseState,
    DataTier,
    DictionaryStatus,
    Freshness,
    IngestionStatus,
    JobState,
    ModelTier,
    PublicationEvent,
)
from ui.mock.backend import fixture_case, fixture_evidence


def render(config: UiConfig) -> None:
    if not config.mock_mode or config.environment not in {"local", "test"}:
        raise ValueError("The component gallery is development-only")
    st.title("Evidence Review · Component gallery")
    st.warning(LABELS["mock"])
    st.caption("Frontend foundations · FE-0–FE-4 · Display timezone: " + config.display_timezone)
    st.header("Assessment states")
    for state in Freshness:
        with st.expander(
            state.value, expanded=state in {Freshness.COMPLETE, Freshness.UNAVAILABLE}
        ):
            case = fixture_case(
                {
                    Freshness.STALE: 2,
                    Freshness.BUFFERING: 3,
                    Freshness.PROVISIONAL_HIGHER: 4,
                    Freshness.UNAVAILABLE: 200,
                    Freshness.UNKNOWN: 200,
                }.get(state, 1)
            )
            case["score"]["freshness"] = state.value
            freshness.render(case["score"], config.display_timezone)
            score.render_score(
                case["score"]["raw_score"],
                case["score"]["rank"],
                case["score"]["percentile"],
                state.value,
                200,
            )
    st.header("Independent status categories")
    for category, enum in (
        ("Publication event", PublicationEvent),
        ("Case workflow", CaseState),
        ("Job", JobState),
        ("Ingestion", IngestionStatus),
        ("Data tier", DataTier),
        ("Model tier", ModelTier),
        ("Dictionary", DictionaryStatus),
    ):
        with st.expander(category):
            for member in enum:
                badges.render_badge(category, member)
    st.header("Provenance and evidence")
    provenance_header.render_provenance(fixture_case(), config.display_timezone)
    research_banner.render_research("research", in_sample=True)
    evidence = EvidencePayload.model_validate(fixture_evidence(fixture_case()))
    assert evidence.facts is not None
    contribution_chart.render_contributions(evidence.facts)
    st.header("Paging")
    pager = st.session_state.setdefault("gallery_pager", CursorPager())
    pager.bind("fixture-queue-v1", {})
    st.text("Version: " + pager.version + " · Cursor: " + str(pager.cursor))
    render_pager(
        pager,
        {"after_rank": 25, "after_key": "synthetic-0025"} if not pager.cursor else None,
        key="gallery",
    )
    st.header("Read and failure states")
    with status_views.loading():
        st.caption("Loading state uses a labeled progress indicator.")
    status_views.empty()
    status_views.forbidden()
    status_views.conflict()
    status_views.unavailable()
