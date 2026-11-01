"""Streamlit entrypoint. Rendering is driven entirely by authenticated API responses."""

from functools import partial
from pathlib import Path

import streamlit as st

from ui import runtime
from ui.api_client import ApiFailure
from ui.auth import LoginRequired
from ui.components.actions import pending
from ui.components.deployment import render as render_deployment
from ui.components.status_views import render_error
from ui.config import UiConfig, UiConfigurationError
from ui.copy import LABELS
from ui.logging_setup import configure_logging
from ui.pages import case_detail, exports, extensions, history, operations, pilot, queue
from ui.performance import timed_render
from ui.permissions import build_navigation, navigation_groups
from ui.state import Workspace


def render() -> None:
    configure_logging()
    st.set_page_config(page_title="Evidence Review", page_icon="◈", layout="wide")
    st.html(
        "<style>.stMainBlockContainer {padding-top: 4rem;} section[data-testid='stSidebar'] .stButton button {justify-content: flex-start;}</style>"
    )
    st.sidebar.subheader("Evidence Review")
    st.sidebar.caption("Analyst workspace")
    if st.session_state.get("reauth_required"):
        st.warning("Your identity expired. Sign in through the gateway, then resume this session.")
        st.caption(
            "An unresolved request is retained privately and can resume only for the same verified actor and scope."
        )
        try:
            st.link_button("Sign in", UiConfig.load(Path.cwd()).login_url)
        except UiConfigurationError:
            st.caption("Shared login is blocked until organization identity settings are supplied.")
        if st.button("Discard pending request and sign out"):
            st.session_state.clear()
            st.session_state["logged_out"] = True
            st.query_params.clear()
            st.rerun()
        if st.button("Resume authenticated session"):
            try:
                resumed = runtime.create_workspace()
                resumed.authenticate()
                resumed.restore_pending(st.session_state.get("recovery_pending"))
                st.session_state.clear()
                st.session_state["workspace"] = resumed
                st.session_state["handle_fingerprint"] = runtime.handle_fingerprint()
                st.rerun()
            except (LoginRequired, UiConfigurationError):
                st.error("A new authenticated gateway session is required.")
            except ApiFailure as error:
                render_error(error)
        return
    if st.session_state.get("logged_out"):
        st.info("You are signed out. Sign in through the organization’s identity gateway.")
        try:
            st.link_button("Sign in", UiConfig.load(Path.cwd()).login_url)
        except UiConfigurationError:
            st.caption("The identity integration is awaiting protected deployment configuration.")
        return
    workspace: Workspace | None = st.session_state.get("workspace")
    try:
        if workspace is None:
            workspace = runtime.create_workspace()
            st.session_state["workspace"] = workspace
            st.session_state["handle_fingerprint"] = runtime.handle_fingerprint()
        elif st.session_state.get("handle_fingerprint") != runtime.handle_fingerprint():
            raise LoginRequired()
        old = workspace.fingerprint
        workspace.authenticate()
        if old and old != workspace.fingerprint:
            st.session_state.clear()
            st.session_state["workspace"] = workspace
            st.session_state["handle_fingerprint"] = runtime.handle_fingerprint()
            st.rerun()
        renderers = {
            "Review queue": queue.render,
            "Case evidence": case_detail.render,
            "History": history.render,
            "Operations": operations.render,
            "Exports": exports.render,
        }
        renderers.update(
            {
                name: partial(extensions.render, page=name)
                for name in workspace.api.config.extension_pages
            }
        )
        renderers["Pilot metrics"] = pilot.render
        choices = {
            name: renderers[name]
            for name in build_navigation(
                workspace.identity,
                workspace.api.config.extension_pages,
                mock_mode=workspace.api.config.mock_mode,
            )
        }
        if workspace.api.config.mock_mode:
            st.caption(LABELS["mock"])
        render_deployment(workspace)
        if not choices:
            st.warning("This identity has no workspace actions in its current API scope.")
            return
        target = st.session_state.pop("navigate_to", None)
        if target in choices:
            st.session_state["page"] = target
        if st.session_state.get("page") not in choices:
            st.session_state["page"] = next(iter(choices))
        page = st.session_state["page"]
        for group, names in navigation_groups(list(choices)).items():
            if group.startswith("Preview"):
                with st.sidebar.expander(group, expanded=page in names):
                    render_navigation(names, page)
            else:
                st.sidebar.caption(group)
                with st.sidebar:
                    render_navigation(names, page)
        with st.sidebar.expander("Session"):
            st.text(workspace.identity["actor_id"])
            st.caption("Display timezone: " + workspace.api.config.display_timezone)
            if st.button("Sign out", key="logout"):
                workspace.logout()
                st.session_state.clear()
                st.session_state["logged_out"] = True
                st.query_params.clear()
                st.rerun()
        pending(workspace)
        if workspace.last_result:
            result = workspace.last_result
            with st.sidebar.expander("Last action"):
                st.caption(
                    "Last persisted action: "
                    + str(result.get("event_id") or result.get("job_id") or "Acknowledged")
                )

        if page in {"Operations", "Exports"} and st.query_params.get("job"):
            try:
                value = str(st.query_params["job"])
                if page == "Exports":
                    if value not in workspace.job_views:
                        exports.reconnect_export(workspace, value)
                else:
                    workspace.reconnect_job(value)
            except ValueError:
                st.error("The reconnect job ID is invalid. Enter a valid job ID below.")
        job_kind = "export" if page == "Exports" else None
        polling = page in {"Operations", "Exports"} and workspace.polling_active(job_kind)

        @st.fragment(run_every=workspace.api.config.poll_seconds if polling else None)
        def content() -> None:
            assert workspace is not None
            try:
                before = workspace.fingerprint
                workspace.authenticate()
                if before != workspace.fingerprint:
                    st.session_state.clear()
                    st.session_state["workspace"] = workspace
                    st.session_state["handle_fingerprint"] = runtime.handle_fingerprint()
                    st.rerun()
                with timed_render(
                    {
                        "Review queue": "queue",
                        "Case evidence": "case",
                        "History": "history",
                        "Operations": "operations",
                        "Exports": "exports",
                    }.get(page, "app")
                ):
                    choices[page](workspace)
                if page in {"Operations", "Exports"} and polling != workspace.polling_active(
                    job_kind
                ):
                    st.rerun()  # Recreate the fragment without a timer at terminal/deadline.
            except ApiFailure as error:
                render_error(error)
            except LoginRequired:
                retained = workspace.suspend()
                st.session_state.clear()
                st.session_state["recovery_pending"] = retained
                st.session_state["reauth_required"] = True
                st.query_params.clear()
                st.rerun()
            except Exception:
                st.error("The API returned an unexpected response. Reload this view.")

        content()
    except UiConfigurationError:
        st.warning(
            "Workspace configuration is incomplete. Shared login is blocked until organization identity settings are supplied."
        )
        st.info(
            "Contact the deployment owner to configure the API and approved per-user token gateway."
        )
    except LoginRequired:
        retained = workspace.suspend() if workspace else None
        st.session_state.clear()
        st.session_state["recovery_pending"] = retained
        st.session_state["reauth_required"] = True
        st.query_params.clear()
        st.rerun()
    except ApiFailure as error:
        if workspace:
            workspace.cache.clear()
        render_error(error)


def render_navigation(names: list[str], page: str) -> None:
    for name in names:
        if st.button(
            name,
            key="nav_" + name,
            width="stretch",
            type="primary" if name == page else "secondary",
        ):
            st.session_state["page"] = name
            st.rerun()


if __name__ == "__main__":
    render()
