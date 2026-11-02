"""Foundation contracts and security properties over the synthetic HTTP boundary."""

import io
import json
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from ui import dto, enums
from ui.auth import LoginRequired
from ui.components.pager import CursorPager
from ui.components.score import score_values
from ui.components.time_fmt import format_time
from ui.copy import FORBIDDEN_PHRASES, LABELS, MESSAGES, find_forbidden
from ui.errors import ApiFailure, ContractError
from ui.logging_setup import configure_logging
from ui.mock.backend import create_workspace, fixture_case, fixture_config, identity
from ui.permissions import build_navigation

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "kind",
    [
        enums.Freshness,
        enums.PublicationEvent,
        enums.CaseState,
        enums.JobState,
        enums.IngestionStatus,
        enums.DataTier,
        enums.ModelTier,
        enums.DictionaryStatus,
    ],
)
def test_enum_unknown_and_accessible_presentation(kind):
    assert kind("future_value") == kind.UNKNOWN
    for value in kind:
        assert value.presentation.label and value.presentation.explanation
        assert value.value in value.presentation.marker
        assert value.presentation.color_token != "green"


def test_approved_copy_and_forbidden_scanner():
    for phrase in FORBIDDEN_PHRASES:
        assert phrase in find_forbidden(phrase.upper())
    assert not find_forbidden(" ".join([*LABELS.values(), *MESSAGES.values()]))


@pytest.mark.parametrize(
    "change",
    [
        {"display_timezone": "invalid-zone"},
        {"verify_tls": False},
        {"read_timeout": 0},
        {"page_size": 101},
        {"max_poll_seconds": 3},
        {"environment": "qualified"},
        {"environment": "unexpected"},
        {"api_base_url": "http://remote.example"},
    ],
)
def test_invalid_settings_rejected(change):
    with pytest.raises(ValidationError):
        fixture_config(**change)


def test_settings_fingerprint_excludes_secrets():
    assert (
        fixture_config().fingerprint()
        == fixture_config(gateway_service_token="x" * 40).fingerprint()
    )
    assert (
        fixture_config().fingerprint()
        != fixture_config(display_timezone="Asia/Kolkata").fingerprint()
    )


def test_logs_discard_sensitive_payloads_and_exception_text():
    stream = io.StringIO()
    logger = configure_logging(stream)
    try:
        raise ValueError("private-token-note")
    except ValueError:
        logger.exception(
            "private-token-note",
            extra={
                "page": "queue",
                "action": "fetch",
                "status": 503,
                "request_id": str(uuid4()),
                "Authorization": "private-token-note",
                "note": "private-token-note",
                "feature_value": 1234,
            },
        )
    logger.info(
        "private-token-note",
        extra={"page": "private-token-note", "request_id": "private-token-note"},
    )
    assert "private-token-note" not in stream.getvalue()
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert all("feature_value" not in item and 1234 not in item.values() for item in events)
    assert json.loads(stream.getvalue().splitlines()[0])["status"] == 503
    logger.handlers = []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: c.pop("case_id"),
        lambda c: c["score"].update(raw_score=float("nan")),
        lambda c: c["score"].update(assessed_as_of="2026-10-31T06:00:00"),
        lambda c: c["score"].update(freshness="UNAVAILABLE"),
        lambda c: c.update(case_version=-1),
    ],
)
def test_malformed_contracts_fail_without_input_leak(mutation):
    case = fixture_case()
    mutation(case)
    with pytest.raises(ContractError) as error:
        dto.parse(dto.CaseDetail, case)
    assert str(error.value) == "CONTRACT"


def test_future_enum_does_not_fabricate_a_score():
    case = fixture_case()
    case["score"]["freshness"] = "FUTURE"
    value = dto.parse(dto.CaseDetail, case)
    assert value.score.freshness == enums.Freshness.UNKNOWN
    assert score_values(value.score.raw_score, 1, 100, value.score.freshness) == ("—", "—", "—")
    assert score_values(0, 1, 100, "COMPLETE")[0] == "0"


def test_timezone_and_cursor_version_filter_binding():
    assert "11:30:00 +0530 [Asia/Kolkata]" in format_time("2026-10-31T06:00:00Z", "Asia/Kolkata")
    assert format_time("2026-10-31T06:00:00") == "Unknown timezone"
    pager = CursorPager()
    pager.bind("v1", {})
    pager.advance({"after_rank": 25, "after_key": "r25"})
    pager.bind("v1", {})
    assert pager.cursor
    pager.bind("v1", {"state": "QUEUED"})
    assert not pager.cursor and not pager.previous
    pager.advance({"after_rank": 1})
    pager.bind("v2", {})
    assert not pager.cursor


def test_mock_ties_stable_paging_and_all_read_contracts():
    workspace, backend = create_workspace()
    workspace.authenticate()
    api = workspace.api
    assert len(backend.cases) == 200
    assert api.list_queues().items[0].queue_version == UUID(identity("queue"))
    first = api.get_queue(UUID(identity("queue")))
    assert first.total == 50 and len(first.items) == 25
    assert first.items[0].raw_score == first.items[1].raw_score
    second = api.get_queue(first.queue_version, **first.next.model_dump())
    assert len(second.items) == 25 and not second.next
    assert not {r.case_id for r in first.items}.intersection(r.case_id for r in second.items)
    for index in (1, 2, 3, 4, 5, 6, 200):
        case_id = UUID(identity(f"case-{index}"))
        api.get_case(case_id)
        api.get_evidence(case_id)
        for kind in ("reviews", "scores", "audit"):
            api.get_history(case_id, kind)
    assert api.get_batch(UUID(identity("batch"))).state == enums.IngestionStatus.ACCEPTED
    assert api.model(UUID(identity("model"))).tier == enums.ModelTier.RESEARCH
    assert api.health().state == "ready"


@pytest.mark.parametrize(
    "status,code",
    [
        (403, "DENIED"),
        (404, "NOT_FOUND"),
        (409, "CONFLICT"),
        (422, "INVALID"),
        (429, "RATE_LIMITED"),
        (500, "UNAVAILABLE"),
        ("timeout", "UNAVAILABLE"),
        ("connection", "UNAVAILABLE"),
    ],
)
def test_faults_are_safe_and_reads_have_bounded_retries(status, code):
    workspace, backend = create_workspace()
    path = "/v1/cases/" + identity("case-1")
    backend.inject("GET", path, status, status, status)
    with pytest.raises(ApiFailure) as error:
        workspace.api.get_case(UUID(identity("case-1")))
    assert error.value.code == code
    assert len(backend.calls) == (3 if status in (429, 500, "timeout", "connection") else 1)
    assert UUID(error.value.request_id)


def test_401_never_retries_and_requires_gateway_login():
    workspace, backend = create_workspace()
    backend.inject("GET", "/v1/me", 401)
    with pytest.raises(LoginRequired):
        workspace.authenticate()
    assert len(backend.calls) == 1


def test_uncertain_write_reuses_key_payload_and_same_actor_recovery():
    workspace, backend = create_workspace()
    workspace.authenticate()
    path = "/v1/cases/" + identity("case-1") + "/assignment"
    pending = workspace.begin("Assign", path, {"expected_version": 0})
    backend.inject("POST", path, "after_commit_timeout")
    with pytest.raises(ApiFailure):
        workspace.submit()
    assert pending.state == "UNKNOWN" and len(backend.effects) == 1
    result = workspace.submit()
    assert workspace.submit() == result and len(backend.effects) == 1
    pending.state, pending.result = "UNKNOWN", None
    retained = workspace.suspend()
    assert not workspace.identity and workspace.pending is None
    resumed, _ = create_workspace()
    resumed.authenticate()
    assert resumed.restore_pending(retained)
    assert resumed.pending.key == pending.key and resumed.pending.payload == pending.payload
    other, _ = create_workspace(subject="another-user")
    other.authenticate()
    assert not other.restore_pending(retained) and other.pending is None
    scoped, _ = create_workspace(scope="another-scope")
    scoped.authenticate()
    assert not scoped.restore_pending(retained)


def test_navigation_and_direct_bypass_are_denied_by_service():
    workspace, _ = create_workspace(permissions=("job:read",))
    workspace.authenticate()
    assert build_navigation(workspace.identity) == ["Operations"]
    with pytest.raises(ApiFailure) as error:
        workspace.api.get_case(UUID(identity("case-1")))
    assert error.value.status == 403


def test_mock_write_contracts_and_stale_version_conflict():
    workspace, backend = create_workspace()
    workspace.authenticate()
    api, case = workspace.api, UUID(identity("case-1"))
    assigned = api.assign(case, dto.AssignmentRequest(expected_version=0), key=uuid4())
    api.start_review(
        case, dto.VersionedRequest(expected_version=assigned.case_version), key=uuid4()
    )
    api.review(
        case,
        dto.ReviewRequest(
            expected_version=2,
            conclusion="NEEDS_MORE_INFORMATION",
            note="<script>literal text</script>",
        ),
        key=uuid4(),
    )
    api.reopen(case, dto.ReopenRequest(expected_version=3, reason="New evidence"), key=uuid4())
    with pytest.raises(ApiFailure) as error:
        api.assign(case, dto.AssignmentRequest(expected_version=0), key=uuid4())
    assert error.value.status == 409
    assert len(api.get_history(case, "reviews").items) == 4
    requests = [
        api.intake(b"synthetic", "{}", "fixture.csv", key=uuid4()),
        api.score(
            dto.ScoreSubmission(batch_id=UUID(identity("batch")), bundle_digest="a" * 64),
            key=uuid4(),
        ),
        api.train(dto.TrainingSubmission(batch_id=UUID(identity("batch"))), key=uuid4()),
        api.export(
            dto.ExportRequest(queue_version=UUID(identity("queue")), reason="Fixture test"),
            key=uuid4(),
        ),
    ]
    for job in requests:
        assert api.get_job(job.job_id).state == enums.JobState.PENDING
    backend.jobs[str(requests[0].job_id)]["state"] = "FAILED"
    api.retry_job(requests[0].job_id, dto.RetryRequest(reason="Fixture retry"), key=uuid4())
    backend.jobs[str(requests[-1].job_id)]["state"] = "SUCCEEDED"
    assert api.download(requests[-1].job_id).startswith(b"case_id,")


def test_request_schemas_match_saved_openapi():
    schemas = json.loads((ROOT / "contracts/api_openapi_v1.json").read_text())["components"][
        "schemas"
    ]
    for frontend, backend in (
        (dto.AssignmentRequest, "Assignment"),
        (dto.VersionedRequest, "StartReview"),
        (dto.ReviewRequest, "Review"),
        (dto.ReopenRequest, "Reopen"),
        (dto.ScoreSubmission, "ScoreSubmission"),
        (dto.TrainingSubmission, "TrainingSubmission"),
        (dto.RetryRequest, "Retry"),
        (dto.ExportRequest, "ExportSubmission"),
    ):
        own = frontend.model_json_schema()
        assert own.get("required", []) == schemas[backend].get("required", [])
        # FastAPI omits null defaults in its OpenAPI output; constraints must match.
        for field in own["properties"].values():
            if field.get("default", "absent") is None:
                field.pop("default")
        assert own["properties"] == schemas[backend]["properties"]


def test_mock_responses_match_saved_backend_schemas():
    # Import only in tests: the UI itself never imports backend modules.
    from mule_detection.api.dto import CaseView, EvidenceView, QueueView

    workspace, backend = create_workspace()
    CaseView.model_validate(backend.read("/v1/cases/" + identity("case-1"), {}))
    EvidenceView.model_validate(backend.read("/v1/cases/" + identity("case-1") + "/evidence", {}))
    QueueView.model_validate(backend.read("/v1/queues/" + identity("queue") + "/cases", {}))


def test_gallery_all_components_and_mock_banner(monkeypatch):
    monkeypatch.setenv("MAD_UI_FIXTURE_ENTRY", "gallery")
    app = AppTest.from_file(str(ROOT / "ui/mock/entry.py"), default_timeout=30).run()
    assert not app.exception
    assert any("MOCK DATA" in w.value for w in app.warning)
    text = " ".join(t.value for t in app.text)
    for marker in ("[CORRECTED]", "[RECONCILED]", "[QUEUED]", "[FAILED]", "[UNKNOWN]"):
        assert marker in text
    assert any(m.value == "—" for m in app.metric)
    assert any("Meaning unverified" in t.value for t in app.caption)


def test_normal_runtime_rejects_mock_config(monkeypatch):
    from ui import runtime
    from ui.config import UiConfigurationError

    monkeypatch.setattr("ui.runtime.UiConfig.load", lambda root: fixture_config())
    with pytest.raises(UiConfigurationError):
        runtime.create_workspace()


def test_unavailable_component_renders_only_dashes():
    app = AppTest.from_string(
        'from ui.components.score import render_score\nrender_score(None, None, None, "UNAVAILABLE")'
    ).run()
    assert not app.exception
    assert [m.value for m in app.metric] == ["—", "—", "—"]
    assert all("low" not in w.value.lower() for w in app.warning)


def test_expiry_gate_retains_draft_without_replaying_it(monkeypatch):
    workspace, backend = create_workspace()
    workspace.authenticate()
    pending = workspace.begin(
        "Assign", "/v1/cases/" + identity("case-1") + "/assignment", {"expected_version": 0}
    )
    backend.inject("GET", "/v1/me", 401)
    monkeypatch.setattr("ui.runtime.create_workspace", lambda: workspace)
    app = AppTest.from_file(str(ROOT / "ui/app.py"), default_timeout=30).run()
    assert not app.exception
    assert app.session_state["recovery_pending"].key == pending.key
    assert not app.table and not workspace.identity
    resumed, resumed_backend = create_workspace()
    monkeypatch.setattr("ui.runtime.create_workspace", lambda: resumed)
    next(b for b in app.button if b.label == "Resume authenticated session").click().run()
    assert not app.exception
    assert resumed.pending.key == pending.key
    assert not any(method == "POST" for method, _ in resumed_backend.calls)


def test_contract_error_keeps_request_reference_and_unknown_write():
    workspace, _ = create_workspace()
    workspace.authenticate()
    request_id = str(uuid4())
    workspace.api._client.close()
    workspace.api._client = httpx.Client(
        base_url=workspace.api.config.api_base_url,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"unsafe_note": "private"}, headers={"X-Request-ID": request_id}
            )
        ),
    )
    pending = workspace.begin(
        "Assign", "/v1/cases/" + identity("case-1") + "/assignment", {"expected_version": 0}
    )
    with pytest.raises(ContractError) as error:
        workspace.submit()
    assert error.value.request_id == request_id
    assert pending.state == "UNKNOWN"


def test_fixture_tokens_are_not_interchangeable_between_stores():
    first, _ = create_workspace(subject="one")
    second, second_backend = create_workspace(subject="two")
    token = first.api.provider.credential().token.get_secret_value()
    response = second_backend(
        httpx.Request(
            "GET",
            second.api.config.api_base_url + "/v1/me",
            headers={"Authorization": "Bearer " + token},
        )
    )
    assert response.status_code == 401
    first.authenticate()
    second.authenticate()
    assert first.identity["actor_id"] != second.identity["actor_id"]
