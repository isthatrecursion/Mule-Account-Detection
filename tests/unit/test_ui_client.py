import time
from uuid import UUID, uuid4

import httpx
import pytest

from tests.ui_helpers import config
from ui.api_client import ApiClient, ApiFailure
from ui.auth import LoginRequired, UserCredential
from ui.components.freshness import display_score, freshness_text
from ui.config import UiConfigurationError
from ui.mock.backend import STAMP, fixture_case
from ui.state import SessionCache, Workspace


def principal(actor="oidc:test", scopes=None):
    return {
        "actor_id": actor,
        "roles": ["analyst"],
        "permissions": ["case:read"],
        "scopes": scopes or ["one"],
        "permission_scopes": {"case:read": scopes or ["one"]},
        "expires_at": int(time.time()) + 300,
    }


class Provider:
    closed = False

    def credential(self):
        from pydantic import SecretStr

        if self.closed:
            raise LoginRequired()
        return UserCredential(
            "oidc:test", int(time.time()) + 3600, "binding", SecretStr("fixture-token-never-log")
        )

    def logout(self):
        self.closed = True


def workspace(handler):
    client = ApiClient(
        config(),
        Provider(),
        client=httpx.Client(
            base_url="https://api.example.test", transport=httpx.MockTransport(handler)
        ),
    )
    value = Workspace(client)
    value.authenticate()
    return value


def test_pending_timeout_retry_and_double_submit_have_one_effect():
    effects, calls = {}, []

    def handler(request):
        if request.url.path == "/v1/me":
            return httpx.Response(200, json=principal())
        key = request.headers["Idempotency-Key"]
        calls.append(key)
        if key not in effects:
            effects[key] = {
                "event_id": str(uuid4()),
                "case_id": request.url.path.split("/")[3],
                "case_version": 3,
            }
            raise httpx.ReadTimeout("secret note must not leak")
        return httpx.Response(200, json=effects[key])

    session = workspace(handler)
    pending = session.begin(
        "Review", f"/v1/cases/{uuid4()}/reviews", {"expected_version": 2, "note": "private draft"}
    )
    with pytest.raises(ApiFailure) as error:
        session.submit()
    assert error.value.code == "UNAVAILABLE" and pending.state == "UNKNOWN"
    with pytest.raises(ValueError):
        session.begin("new", pending.path, {})
    result = session.submit()
    assert session.submit() == result
    assert len(effects) == 1 and calls == [str(pending.key)] * 2
    assert pending.payload["note"] == "private draft"


def test_conflict_fetches_latest_without_creating_a_fresh_key():
    case = uuid4()

    def handler(request):
        if request.url.path == "/v1/me":
            return httpx.Response(200, json=principal())
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    **fixture_case(),
                    "case_id": str(case),
                    "case_version": 4,
                    "state": "REVIEWED",
                },
            )
        return httpx.Response(409, json={"unsafe": "private note"})

    session = workspace(handler)
    pending = session.begin("Review", f"/v1/cases/{case}/reviews", {"expected_version": 2})
    with pytest.raises(ApiFailure):
        session.submit()
    assert pending.state == "CONFLICT" and pending.latest["case_version"] == 4
    key = pending.key
    with pytest.raises(ApiFailure):
        session.submit()
    assert pending.key == key


def test_actor_scope_cache_ttl_isolation_and_invalidation(monkeypatch):
    cache = SessionCache()
    clock = [1.0]
    monkeypatch.setattr("ui.state.time.monotonic", lambda: clock[0])
    first = cache.read("actor1:scopeA", "evidence", "score1", {}, 5, lambda: {"note": "A"})
    first["note"] = "changed"
    assert cache.read("actor1:scopeA", "evidence", "score1", {}, 5, lambda: None) == {"note": "A"}
    assert cache.read("actor2:scopeB", "evidence", "score1", {}, 5, lambda: {"note": "B"}) == {
        "note": "B"
    }
    clock[0] = 7
    assert cache.read("actor1:scopeA", "evidence", "score1", {}, 5, lambda: {"note": "new"}) == {
        "note": "new"
    }
    cache.clear()
    assert not cache._values


@pytest.mark.parametrize(
    "status,code",
    [
        (403, "DENIED"),
        (404, "NOT_FOUND"),
        (409, "CONFLICT"),
        (422, "INVALID"),
        (503, "UNAVAILABLE"),
        (302, "UNAVAILABLE"),
    ],
)
def test_http_errors_never_include_server_payload(status, code):
    def handler(request):
        return httpx.Response(
            status,
            json={"secret": "token=private-note database-password"},
            headers={"X-Request-ID": "injected-private"},
        )

    client = ApiClient(
        config(),
        Provider(),
        client=httpx.Client(
            base_url="https://api.example.test", transport=httpx.MockTransport(handler)
        ),
    )
    with pytest.raises(ApiFailure) as error:
        client.case(uuid4())
    assert str(error.value) == code and UUID(error.value.request_id)


def test_session_logout_scope_change_and_expired_identity_clear_private_state():
    current = [principal()]
    session = workspace(lambda req: httpx.Response(200, json=current[0]))
    session.pending = session.begin("Review", f"/v1/cases/{uuid4()}/reviews", {"note": "private"})
    current[0] = principal(scopes=["different"])
    session.authenticate()
    assert session.pending is None
    session.logout()
    assert not session.identity and not session.jobs and session.api.provider.closed
    with pytest.raises(LoginRequired):
        session.api.case(uuid4())


def test_polling_is_bounded_and_queue_version_moves_only_explicitly(monkeypatch):
    calls = []

    def handler(request):
        if request.url.path == "/v1/me":
            return httpx.Response(200, json=principal())
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "job_id": request.url.path.split("/")[3],
                "state": "PENDING",
                "kind": "score",
                "created_at": STAMP,
                "attempts": [],
                "result": None,
            },
        )

    session = workspace(handler)
    identity = str(uuid4())
    session.poll(identity)
    session.poll(identity)
    assert len(calls) == 1
    old, new = str(uuid4()), str(uuid4())
    session.choose_queue(old)
    session.cursor = {"after_rank": 10, "after_key": "r10"}
    session.choose_queue(old)
    assert session.cursor
    session.choose_queue(new)
    assert not session.cursor and session.queue_version == new


@pytest.mark.parametrize(
    "state", ["COMPLETE", "BUFFERING", "PROVISIONAL_HIGHER", "STALE", "UNAVAILABLE"]
)
def test_freshness_is_explicit_without_color(state):
    text = freshness_text(state, "2026-01-01T00:00:00Z")
    assert "2026-01-01" in text and len(text) > 40
    assert display_score({"freshness": "UNAVAILABLE", "raw_score": None}) == "—"
    assert display_score({"freshness": "COMPLETE", "raw_score": 0.0}) == "0"


def test_no_configuration_or_browser_token_fallback(tmp_path):
    with pytest.raises(UiConfigurationError):
        config().load(tmp_path)
    with pytest.raises(ValueError):
        config().model_copy().model_validate(
            {**config().model_dump(), "api_base_url": "http://untrusted.example"}
        )
