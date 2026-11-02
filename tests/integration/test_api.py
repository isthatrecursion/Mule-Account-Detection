"""Real HTTP, signed tokens, runtime database grants and separately restarted workers."""

import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

pytest.importorskip("fastapi")
pytest.importorskip("jwt")
from fastapi.testclient import TestClient

from mule_detection.api.app import create_app
from mule_detection.api.service import ApiService
from mule_detection.application.ingest_service import IngestService
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.persistence.artifacts import ArtifactStore
from mule_detection.persistence.models import (
    ApiTask,
    AuditEvent,
    BatchAccess,
    Case,
    CaseNote,
    ExportRecord,
    Job,
    Label,
    OutcomeContract,
    QueueHead,
    QueueMember,
    QueueSnapshot,
    ReviewEvent,
)
from mule_detection.persistence.raw_store import RawStore
from mule_detection.persistence.sqlalchemy import session_factory
from mule_detection.settings import Settings
from tests.api_helpers import SigningAuthority
from tests.integration.test_ingestion import CONTENT, declaration
from tests.integration.test_ingestion import intake as intake
from tests.integration.test_persistence import seed

pytestmark = pytest.mark.postgres


@pytest.fixture
def api(db, runtime_engine, tmp_path):
    authority = SigningAuthority()
    settings = Settings(
        environment="test",
        root_path=tmp_path,
        database_url=runtime_engine.url.render_as_string(hide_password=False),
        mlflow_uri="http://localhost:5000",
        runtime_policy_path="config/test.yaml",
        max_upload_bytes=65536,
    )
    factory = session_factory(runtime_engine)
    service = ApiService(
        settings,
        factory,
        ArtifactStore(tmp_path / "snapshots", b"a" * 32, lambda *_: True),
        RawStore(tmp_path / "uploads", b"b" * 32, max_bytes=65536),
        policy_hash="a" * 64,
        sources={"synthetic-csv": "synthetic-team"},
    )

    def client():
        return TestClient(
            create_app(settings, lambda _: (authority.config, service)),
            raise_server_exceptions=False,
        )

    with client() as http:
        yield service, http, authority, client


def seed_queue(db, *, scope="synthetic-team"):
    lineage = seed(db)
    with unit_of_work(db) as session:
        session.add(BatchAccess(batch_id=lineage.batch_id, access_scope=scope))
        queue = QueueSnapshot(
            id=uuid4(),
            run_id=lineage.run_id,
            cohort_id=uuid4(),
            policy_hash="f" * 64,
            published_version=1,
            published_at=datetime.now(UTC),
        )
        session.add(queue)
        session.flush()
        session.add(
            QueueMember(
                queue_id=queue.id,
                record_key="synthetic-record",
                rank=1,
                score_id=lineage.score_id,
                run_id=lineage.run_id,
            )
        )
        session.add(
            QueueHead(cohort_id=queue.cohort_id, environment="test", queue_id=queue.id, version=1)
        )
        return lineage, queue.id


def post(http, path, headers, payload, key=None):
    return http.post(
        path, headers={**headers, "Idempotency-Key": str(key or uuid4())}, json=payload
    )


def opened(api, db):
    service, http, authority, _ = api
    lineage, queue = seed_queue(db)
    headers = authority.headers()
    response = http.get(f"/v1/queues/{queue}/cases", headers=headers)
    assert response.status_code == 200, response.text
    return lineage, queue, UUID(response.json()["items"][0]["case_id"]), headers


def test_http_auth_scope_and_safe_readiness(api, db):
    service, http, authority, _ = api
    lineage, queue, case, headers = opened(api, db)
    assert http.get("/health/live").status_code == 200
    assert http.get("/health/ready").status_code == 200
    assert (
        http.get("/v1/me", headers={"X-Actor-ID": "admin", "X-Role": "reviewer"}).status_code == 401
    )
    for headers_bad in (authority.headers(aud="wrong"), authority.headers(exp=1)):
        assert http.get("/v1/me", headers=headers_bad).status_code == 401
    assert http.get(f"/v1/cases/{case}", headers=authority.headers("operator")).status_code == 403
    assert (
        http.get(f"/v1/cases/{case}", headers=authority.headers(scope="other-team")).status_code
        == 404
    )
    assert (
        http.get(
            f"/v1/queues/{queue}/cases", headers=authority.headers(scope="other-team")
        ).status_code
        == 404
    )
    assert http.get("/v1/queues", headers=authority.headers(scope="other-team")).json() == {
        "items": []
    }
    assert (
        http.get(
            f"/v1/batches/{lineage.batch_id}", headers=authority.headers("operator", "other-team")
        ).status_code
        == 404
    )
    details = http.get(f"/v1/cases/{case}", headers=headers)
    assert details.status_code == 200
    assert details.json()["score_id"] == str(lineage.score_id)
    assert "artifact:" not in details.text and "raw_uri" not in details.text
    assert http.get(f"/v1/queues/{queue}/cases?after_rank=1", headers=headers).status_code == 422
    assert http.get(f"/v1/queues/{queue}/cases?limit=101", headers=headers).status_code == 422
    assert http.get(f"/v1/queues/{queue}/cases?state=bogus", headers=headers).status_code == 422
    assert (
        http.get(f"/v1/queues/{queue}/cases?state=REVIEWED", headers=headers).json()["total"] == 0
    )
    service.ready = lambda: False
    response = http.get("/health/ready")
    assert response.status_code == 503 and UUID(response.json()["error"]["request_id"])


def test_review_atomic_note_idempotency_ownership_and_corrections(api, db):
    service, http, authority, _ = api
    _, queue, case, analyst = opened(api, db)
    base = f"/v1/cases/{case}"
    key = uuid4()
    assigned = post(http, base + "/assignment", analyst, {"expected_version": 0}, key)
    assert assigned.status_code == 200, assigned.text
    assert (
        post(http, base + "/assignment", analyst, {"expected_version": 0}, key).json()
        == assigned.json()
    )
    assert (
        post(http, base + "/assignment", analyst, {"expected_version": 1}, key).status_code == 409
    )
    assert (
        post(
            http,
            base + "/start-review",
            authority.headers(subject="second"),
            {"expected_version": 1},
        ).status_code
        == 403
    )
    assert post(http, base + "/start-review", analyst, {"expected_version": 0}).status_code == 409
    assert post(http, base + "/start-review", analyst, {"expected_version": 1}).status_code == 200
    review = {
        "expected_version": 2,
        "conclusion": "REFER_FOR_ADJUDICATION",
        "note": "=private Ω\nsecond line",
    }
    key = uuid4()
    completed = post(http, base + "/reviews", analyst, review, key)
    assert completed.status_code == 200, completed.text
    assert post(http, base + "/reviews", analyst, review, key).json() == completed.json()
    assert (
        post(http, base + "/reviews", analyst, {**review, "note": "changed"}, key).status_code
        == 409
    )
    with db() as session:
        assert session.scalar(select(func.count()).select_from(CaseNote)) == 1
        assert session.scalar(select(func.count()).select_from(Label)) == 0
        assert session.scalar(select(func.count()).select_from(ReviewEvent)) == 3
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_reference == f"case:{case}")
            )
            == 3
        )
    history = http.get(base + "/history?limit=2", headers=analyst).json()
    assert history["next"] == 2
    latest = http.get(base + "/history?after=2", headers=analyst).json()["items"][0]
    assert latest["note"] == review["note"]
    audit = http.get(base + "/history?kind=audit", headers=authority.headers("auditor"))
    assert audit.status_code == 200 and "private" not in audit.text and "note" not in audit.text
    assert http.get(base + "/history", headers=authority.headers("auditor")).status_code == 403
    assert post(http, base + "/reopen", analyst, {"expected_version": 3}).status_code == 403
    assert (
        post(
            http, base + "/reopen", authority.headers("reviewer"), {"expected_version": 3}
        ).status_code
        == 200
    )
    assert (
        http.get(f"/v1/queues/{queue}/cases", headers=analyst).json()["items"][0]["state"]
        == "ASSIGNED"
    )


def test_concurrent_case_versions_one_winner(api, db):
    _, http, authority, _ = api
    _, _, case, _ = opened(api, db)

    def assign(subject):
        return post(
            http,
            f"/v1/cases/{case}/assignment",
            authority.headers(subject=subject),
            {"expected_version": 0},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(assign, ("one", "two"))) == [200, 409]


def test_durable_upload_restart_real_ingestion_and_restricted_jobs(api, intake, db):
    service, http, authority, new_client = api
    headers = authority.headers("operator")
    key = uuid4()
    upload_headers = {
        **headers,
        "Content-Type": "application/octet-stream",
        "Idempotency-Key": str(key),
        "X-Batch-Manifest": json.dumps(declaration(intake)),
    }
    response = http.post("/v1/batches", headers=upload_headers, content=CONTENT)
    assert response.status_code == 202, response.text
    identity = UUID(response.json()["job_id"])
    assert (
        http.post("/v1/batches", headers=upload_headers, content=CONTENT).json() == response.json()
    )
    assert (
        http.post("/v1/batches", headers=upload_headers, content=CONTENT + b"extra").status_code
        == 409
    )
    assert post(http, "/v1/training-runs", headers, {"batch_id": str(uuid4())}).status_code == 403
    assert http.get(f"/v1/jobs/{identity}", headers=authority.headers("analyst")).status_code == 403
    # A separate service instance reloads durable task/upload state and calls the real ingestion service.
    restarted = ApiService(
        service.settings,
        service.factory,
        service.artifacts,
        service.raw,
        policy_hash=service.policy_hash,
        sources=service.sources,
    )

    def handle(task, principal, context):
        adapter = IngestService(
            intake.factory,
            intake.store,
            intake.profiles,
            intake.policy,
            authorize=lambda ctx, scope, action: scope in principal.scopes,
            max_rows=20,
        )
        result = adapter.ingest(
            io.BytesIO(restarted.raw.read(task.request["digest"])),
            task.request["declaration"],
            context,
            idempotency_key=task.job_id,
        )
        return {"batch_id": str(result.batch_id), "outcome": result.outcome}

    restarted.handlers["intake"] = handle
    assert restarted.run_one(identity) == identity
    with new_client() as second_http:
        status = second_http.get(f"/v1/jobs/{identity}", headers=headers).json()
    assert status["state"] == "SUCCEEDED", status
    assert status["result"]["outcome"] == "ACCEPTED"
    assert restarted.run_one(identity) is None
    batch = status["result"]["batch_id"]
    assert http.get(f"/v1/batches/{batch}", headers=headers).status_code == 200
    assert (
        http.get(
            f"/v1/batches/{batch}", headers=authority.headers("operator", "other-team")
        ).status_code
        == 404
    )
    assert len(status["attempts"]) == 1
    with db() as session:
        task = session.get(ApiTask, identity)
        assert "Bearer" not in json.dumps(task.authorization)


def test_upload_limits_safe_errors_and_worker_failure(api, db):
    service, http, authority, _ = api
    headers = {
        **authority.headers("operator"),
        "Idempotency-Key": str(uuid4()),
        "Content-Type": "application/octet-stream",
        "X-Batch-Manifest": '{"manifest":{"source_id":"synthetic-csv"}}',
    }
    assert http.post("/v1/batches", headers=headers, content=b"a" * 65537).status_code == 413
    response = http.post("/v1/batches", headers=headers, content=b"r1\n")
    identity = UUID(response.json()["job_id"])

    def fail(*args):
        raise RuntimeError("postgresql://secret:password@private/ sensitive-row")

    service.handlers["intake"] = fail
    service.run_one(identity)
    status = http.get(f"/v1/jobs/{identity}", headers=authority.headers("operator"))
    assert status.json()["state"] == "FAILED" and "password" not in status.text
    retried = post(
        http,
        f"/v1/jobs/{identity}/retry",
        authority.headers("operator"),
        {"reason": "dependency restored"},
    )
    assert retried.status_code == 202
    assert (
        post(
            http,
            "/v1/exports",
            authority.headers("reviewer"),
            {"queue_version": "bad", "reason": "password"},
        ).status_code
        == 422
    )
    assert (
        post(http, "/v1/exports", authority.headers("reviewer"), {"reason": "password"}).json()[
            "error"
        ]["code"]
        == "INVALID_REQUEST"
    )


def test_export_snapshot_actor_scope_expiry_and_csv(api, db):
    service, http, authority, _ = api
    _, queue, case, analyst = opened(api, db)
    reviewer = authority.headers("reviewer")
    key = uuid4()
    payload = {"queue_version": str(queue), "reason": "approved review"}
    response = post(http, "/v1/exports", reviewer, payload, key)
    assert response.status_code == 202, response.text
    assert post(http, "/v1/exports", reviewer, payload, key).json() == response.json()
    assert (
        post(http, "/v1/exports", reviewer, {**payload, "state": "REVIEWED"}, key).status_code
        == 409
    )
    assert (
        post(http, "/v1/exports", reviewer, {**payload, "columns": ["record_key"]}).status_code
        == 403
    )
    job_id = UUID(response.json()["job_id"])
    # Live case changes after authorization do not alter the exported snapshot.
    post(http, f"/v1/cases/{case}/assignment", analyst, {"expected_version": 0})
    service.run_one(job_id)
    path = f"/v1/exports/{job_id}/download"
    result = http.get(path, headers=reviewer)
    assert result.status_code == 200, result.text
    rows = list(csv.DictReader(io.StringIO(result.text)))
    assert rows[0]["state"] == "QUEUED" and rows[0]["queue_version"] == str(queue)
    assert "record_key" not in rows[0] and "note" not in rows[0]
    assert (
        http.get(path, headers=authority.headers("reviewer", subject="another")).status_code == 404
    )
    assert http.get(path, headers=authority.headers("reviewer", "other-team")).status_code == 404
    with unit_of_work(db) as session:
        session.get(ExportRecord, job_id).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert http.get(path, headers=reviewer).status_code == 404
    values = ["=SUM(1,1)", " +cmd", "-1", "@x", "\ttext", "\rline", "Ω\nsecond line", -2.5, 3]
    out = io.StringIO(newline="")
    csv.writer(out).writerow([service.csv_value(v) for v in values])
    read = next(csv.reader(io.StringIO(out.getvalue())))
    assert all(read[i].startswith("'") for i in range(6))
    assert read[6:] == ["Ω\nsecond line", "-2.5", "3"]


@pytest.mark.parametrize("condition", ["policy", "disabled", "expired"])
def test_revoked_expired_and_policy_changed_tasks_fail_closed(api, db, condition):
    service, http, authority, _ = api
    headers = {
        **authority.headers("operator"),
        "Idempotency-Key": str(uuid4()),
        "Content-Type": "application/octet-stream",
        "X-Batch-Manifest": '{"manifest":{"source_id":"synthetic-csv"}}',
    }
    response = http.post("/v1/batches", headers=headers, content=b"r1\n")
    identity = UUID(response.json()["job_id"])
    called = []
    service.handlers["intake"] = lambda *args: called.append(True) or {}
    if condition == "policy":
        service.policy_hash = "changed"
    else:
        from mule_detection.persistence.models import ApiIdentity

        with unit_of_work(db) as session:
            task = session.get(ApiTask, identity)
            if condition == "disabled":
                session.get(
                    ApiIdentity, task.authorization["principal"]["actor_id"]
                ).disabled = True
            else:
                task.authorization = {
                    **task.authorization,
                    "principal": {**task.authorization["principal"], "expires_at": 1},
                }
    service.run_one(identity)
    assert not called
    with db() as session:
        assert session.get(Job, identity).state == "FAILED"


def test_outcomes_approved_owner_maturity_and_asof(api, db):
    service, http, authority, _ = api
    reviewer = authority.headers("reviewer")
    actor = http.get("/v1/me", headers=reviewer).json()["actor_id"]
    service.outcome_sources["adjudicator"] = {
        "owner": actor,
        "scope": "synthetic-team",
        "approval": "test-approved-source",
        "identity_map": {"r1": "account1"},
    }
    cutoff = datetime.now(UTC) - timedelta(days=2)
    label = {
        "contract_version": "label_v1",
        "label_id": str(uuid4()),
        "record_key": "r1",
        "account_id": "account1",
        "value": 1,
        "label_source": "adjudicator",
        "event_at": (cutoff - timedelta(days=10)).isoformat(),
        "observed_at": (cutoff - timedelta(days=8)).isoformat(),
        "available_at": (cutoff - timedelta(days=7)).isoformat(),
        "mature_at": (cutoff - timedelta(days=1)).isoformat(),
        "status": "ADJUDICATED",
        "adjudication_reference": "test-decision",
        "negative_policy_reference": None,
        "version": 1,
        "supersedes": None,
    }
    payload = {"source_id": "adjudicator", "known_as_of": cutoff.isoformat(), "labels": [label]}
    assert (
        post(
            http, "/v1/outcomes", authority.headers("reviewer", subject="intruder"), payload
        ).status_code
        == 403
    )
    key = uuid4()
    response = post(http, "/v1/outcomes", reviewer, payload, key)
    assert response.status_code == 200, response.text
    assert post(http, "/v1/outcomes", reviewer, payload, key).json() == response.json()
    assert (
        post(
            http,
            "/v1/outcomes",
            reviewer,
            {**payload, "known_as_of": datetime.now(UTC).isoformat()},
            key,
        ).status_code
        == 409
    )
    assert service.labels_as_of("r1", cutoff - timedelta(seconds=1)) is None
    assert service.labels_as_of("r1", cutoff).value == 1
    correction = {
        **label,
        "label_id": str(uuid4()),
        "version": 2,
        "supersedes": label["label_id"],
        "value": 0,
        "available_at": (cutoff + timedelta(days=1)).isoformat(),
    }
    corrected = {**payload, "known_as_of": datetime.now(UTC).isoformat(), "labels": [correction]}
    assert post(http, "/v1/outcomes", reviewer, corrected).status_code == 200
    assert service.labels_as_of("r1", cutoff).value == 1
    assert service.labels_as_of("r1", datetime.now(UTC)).value == 0
    with db() as session:
        assert session.scalar(select(func.count()).select_from(Label)) == 2
        assert session.scalar(select(func.count()).select_from(OutcomeContract)) == 2


def test_scoped_combined_roles_do_not_cross_grant_actions(api, db):
    _, http, authority, _ = api
    lineage, queue, case, _ = opened(api, db)
    combined = authority.headers(groups=["analyst-synthetic-team", "operator-other-team"])
    assert http.get(f"/v1/cases/{case}", headers=combined).status_code == 200
    assert (
        post(
            http,
            "/v1/scoring-runs",
            combined,
            {"batch_id": str(lineage.batch_id), "bundle_digest": "d" * 64},
        ).status_code
        == 404
    )
    assert http.get(f"/v1/batches/{lineage.batch_id}", headers=combined).status_code == 404


def test_pinned_queue_keyset_and_newer_case_assessment(api, db):
    from mule_detection.persistence.models import ScoreRow
    from mule_detection.persistence.repositories import Repositories

    service, http, authority, _ = api
    lineage, queue = seed_queue(db)
    headers = authority.headers()
    with unit_of_work(db) as session:
        for index in (2, 3):
            score = ScoreRow(
                id=uuid4(),
                run_id=lineage.run_id,
                record_key=f"r{index}",
                raw_score=0.5,
                contract_payload={},
            )
            session.add(score)
            session.flush()
            session.add(
                QueueMember(
                    queue_id=queue,
                    record_key=score.record_key,
                    rank=index,
                    score_id=score.id,
                    run_id=lineage.run_id,
                )
            )
    first = http.get(f"/v1/queues/{queue}/cases?limit=1", headers=headers).json()
    case = first["items"][0]["case_id"]
    with unit_of_work(db) as session:
        old = session.get(QueueSnapshot, queue)
        run = Repositories(session).create_run(
            actor_id="system",
            idempotency_key=uuid4(),
            batch_id=lineage.batch_id,
            model_id=lineage.model_id,
            policy_hash="f" * 64,
            snapshot_id=lineage.artifact_id,
        )
        score = ScoreRow(
            id=uuid4(),
            run_id=run.id,
            record_key="synthetic-record",
            raw_score=0.9,
            contract_payload={},
        )
        session.add(score)
        session.flush()
        next_queue = QueueSnapshot(
            id=uuid4(),
            run_id=run.id,
            cohort_id=old.cohort_id,
            policy_hash="f" * 64,
            published_version=2,
            published_at=datetime.now(UTC),
        )
        session.add(next_queue)
        session.flush()
        session.add(
            QueueMember(
                queue_id=next_queue.id,
                record_key=score.record_key,
                rank=1,
                score_id=score.id,
                run_id=run.id,
            )
        )
        session.get(QueueHead, (old.cohort_id, "test")).queue_id = next_queue.id
        session.get(QueueHead, (old.cohort_id, "test")).version = 2
        newer_score = score.id
    second = http.get(
        f"/v1/queues/{queue}/cases", params={"limit": 1, **first["next"]}, headers=headers
    ).json()
    assert first["queue_version"] == second["queue_version"] == str(queue)
    assert (
        first["items"][0]["rank"] == 1 and second["items"][0]["rank"] == 2 and second["total"] == 3
    )
    current = http.get(f"/v1/cases/{case}", headers=headers).json()
    assert current["score_id"] == str(lineage.score_id) and current["newer_score_id"] == str(
        newer_score
    )
    assert current["newer_assessment_available"]
    assert http.get(f"/v1/cases/{case}/history?kind=scores", headers=headers).json()["items"][0][
        "selected"
    ]
    assert (
        http.get(f"/v1/queues/{queue}/cases?untrusted_filter=x", headers=headers).status_code == 422
    )


def test_http_evidence_uses_opened_score_and_scoped_access(api, db):
    from mule_detection.api.auth import TokenVerifier
    from mule_detection.persistence.models import Evidence
    from mule_detection.scoring.storage import register_artifact

    service, http, authority, _ = api
    lineage, _, case, headers = opened(api, db)
    principal = TokenVerifier(authority.config, "test").verify(headers["Authorization"])
    artifact = service.artifacts.put(
        {"synthetic-record": {"scale": "raw_margin", "meaning_status": "UNVERIFIED"}},
        schema_id="evidence_test_v1",
        access_scope="synthetic-team",
        context=service.context(principal),
    )
    with unit_of_work(db) as session:
        artifact_id = register_artifact(session, artifact)
        session.add(
            Evidence(
                score_id=lineage.score_id,
                dictionary_version="test-dictionary",
                structured_evidence={"explanation_artifact_id": str(artifact_id)},
            )
        )
    response = http.get(f"/v1/cases/{case}/evidence", headers=headers)
    assert response.status_code == 200 and response.json()["score_id"] == str(lineage.score_id)
    assert "artifact:" not in response.text and "explanation_artifact_id" not in response.text
    assert (
        http.get(f"/v1/cases/{case}/evidence", headers=authority.headers("operator")).status_code
        == 403
    )
    assert (
        http.get(
            f"/v1/cases/{case}/evidence", headers=authority.headers(scope="other-team")
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "role,method,path,payload",
    [
        (
            "analyst",
            "post",
            "/v1/scoring-runs",
            {"batch_id": str(UUID(int=1)), "bundle_digest": "d" * 64},
        ),
        ("analyst", "post", "/v1/training-runs", {"batch_id": str(UUID(int=1))}),
        ("analyst", "post", "/v1/exports", {"queue_version": str(UUID(int=1)), "reason": "review"}),
        ("analyst", "post", "/v1/jobs/{id}/retry", {"reason": "retry"}),
        ("operator", "get", "/v1/cases/{id}", None),
        ("operator", "get", "/v1/cases/{id}/evidence", None),
        ("operator", "get", "/v1/cases/{id}/history", None),
        ("operator", "get", "/v1/queues", None),
        (
            "operator",
            "post",
            "/v1/exports",
            {"queue_version": str(UUID(int=1)), "reason": "review"},
        ),
        ("engineer", "get", "/v1/cases/{id}", None),
        ("engineer", "get", "/v1/queues", None),
        (
            "engineer",
            "post",
            "/v1/scoring-runs",
            {"batch_id": str(UUID(int=1)), "bundle_digest": "d" * 64},
        ),
        ("auditor", "get", "/v1/cases/{id}", None),
        ("auditor", "get", "/v1/cases/{id}/evidence", None),
        ("auditor", "post", "/v1/cases/{id}/assignment", {"expected_version": 0}),
        (
            "auditor",
            "post",
            "/v1/cases/{id}/reviews",
            {"expected_version": 0, "conclusion": "NO_FURTHER_REVIEW"},
        ),
        ("auditor", "get", "/v1/queues", None),
        ("reviewer", "post", "/v1/training-runs", {"batch_id": str(UUID(int=1))}),
        (
            "reviewer",
            "post",
            "/v1/scoring-runs",
            {"batch_id": str(UUID(int=1)), "bundle_digest": "d" * 64},
        ),
        ("reviewer", "post", "/v1/jobs/{id}/retry", {"reason": "retry"}),
    ],
)
def test_every_role_has_explicit_http_denials(api, role, method, path, payload):
    _, http, authority, _ = api
    headers = {**authority.headers(role), "X-Role": "reviewer", "X-Scope": "synthetic-team"}
    path = path.replace("{id}", str(uuid4()))
    response = (
        http.get(path, headers=headers) if method == "get" else post(http, path, headers, payload)
    )
    assert response.status_code == 403, response.text


def test_review_failure_rolls_back_event_note_and_case_together(api, db, monkeypatch):
    from mule_detection.application.audit_service import AuditService

    _, http, _, _ = api
    _, _, case, analyst = opened(api, db)
    base = f"/v1/cases/{case}"
    assert post(http, base + "/assignment", analyst, {"expected_version": 0}).status_code == 200
    assert post(http, base + "/start-review", analyst, {"expected_version": 1}).status_code == 200
    original = AuditService.append

    def broken(*args, **kwargs):
        raise RuntimeError("private dependency failure")

    monkeypatch.setattr(AuditService, "append", broken)
    key = uuid4()
    payload = {"expected_version": 2, "conclusion": "NO_FURTHER_REVIEW", "note": "private note"}
    failed = post(http, base + "/reviews", analyst, payload, key)
    assert failed.status_code == 503 and "private" not in failed.text
    with db() as session:
        assert session.get(Case, case).version == 2
        assert session.scalar(select(func.count()).select_from(CaseNote)) == 0
        assert session.scalar(select(func.count()).select_from(ReviewEvent)) == 2
    monkeypatch.setattr(AuditService, "append", original)
    assert post(http, base + "/reviews", analyst, payload, key).status_code == 200


def test_sensitive_export_requires_explicit_grant_at_creation_and_download(api, db):
    service, http, authority, _ = api
    _, queue, case, analyst = opened(api, db)
    base = f"/v1/cases/{case}"
    post(http, base + "/assignment", analyst, {"expected_version": 0})
    post(http, base + "/start-review", analyst, {"expected_version": 1})
    post(
        http,
        base + "/reviews",
        analyst,
        {
            "expected_version": 2,
            "conclusion": "NO_FURTHER_REVIEW",
            "note": "=formula Ω\nsecond line",
        },
    )
    group = "reviewer-synthetic-team"
    original = authority.config.groups[group]
    authority.config.groups[group] = original.model_copy(
        update={"permissions": frozenset({"export:sensitive"})}
    )
    response = post(
        http,
        "/v1/exports",
        authority.headers("reviewer"),
        {
            "queue_version": str(queue),
            "columns": ["case_id", "note"],
            "reason": "explicit authorized notes",
        },
    )
    assert response.status_code == 202
    identity = UUID(response.json()["job_id"])
    service.run_one(identity)
    path = f"/v1/exports/{identity}/download"
    result = http.get(path, headers=authority.headers("reviewer"))
    assert result.status_code == 200, result.text
    rows = list(csv.DictReader(io.StringIO(result.text)))
    assert rows[0]["note"] == "'=formula Ω\nsecond line"
    with db() as session:
        metadata = session.get(ExportRecord, identity)
        assert "formula" not in json.dumps(metadata.snapshot)
        assert list(metadata.snapshot[0]) == ["artifact_id"]
    authority.config.groups[group] = original
    assert http.get(path, headers=authority.headers("reviewer")).status_code == 403
