import io
import json

from ui.cache import SessionCache
from ui.logging_setup import configure_logging
from ui.mock.backend import create_workspace, identity
from ui.performance import timed_render


def test_cache_binds_actor_scope_filters_and_version_and_copies_values():
    tick = [0.0]
    cache = SessionCache(lambda: tick[0])

    def read(actor="a", scope="one", version="v1", params=None, note="first"):
        return cache.cached_get(
            "history:case",
            params or {},
            actor_fingerprint=actor,
            scope_fingerprint=scope,
            data_version=version,
            ttl_seconds=5,
            load=lambda: {"note": note},
        )

    assert read()["note"] == "first"
    assert read(note="changed")["note"] == "first"
    assert read(actor="b", note="second")["note"] == "second"
    assert read(scope="two", note="scoped")["note"] == "scoped"
    assert read(version="v2", note="published")["note"] == "published"
    assert read(params={"kind": "audit"}, note="audit")["note"] == "audit"
    read()["note"] = "mutated"
    assert read()["note"] == "first"
    tick[0] = 6
    assert read(note="fresh")["note"] == "fresh"


def test_auth_writes_and_missing_versions_are_never_cached():
    cache = SessionCache()
    for endpoint, version in (("me", "v1"), ("write", "v1"), ("evidence", "")):
        for value in (1, 2):
            assert cache.read("actor", endpoint, version, {}, 5, lambda value=value: value) == value
    assert not cache._values


def test_accepted_write_invalidates_private_read_entries():
    workspace, _ = create_workspace()
    workspace.authenticate()
    workspace.cache.read(workspace.fingerprint, "queue", "v1", {}, 5, lambda: {"count": 1})
    workspace.begin(
        "Assign", "/v1/cases/" + identity("case-1") + "/assignment", {"expected_version": 0}
    )
    workspace.submit()
    assert not workspace.cache._values


def test_render_timing_uses_safe_fixed_fields():
    stream = io.StringIO()
    logger = configure_logging(stream)
    ticks = iter((10.0, 10.125))
    with timed_render("history", lambda: next(ticks)):
        pass
    result = json.loads(stream.getvalue())
    assert result["duration_ms"] == 125 and result["page"] == "history"
    assert set(result) == {"event", "action", "page", "duration_ms"}
    logger.handlers = []
