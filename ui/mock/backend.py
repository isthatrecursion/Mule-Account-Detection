"""Synthetic in-memory HTTP service, never a fallback for an unavailable API.

UUIDs and records are deterministic. A fresh signing key and isolated store belong
to each factory call. Only the fake service creates export bytes or applies writes.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import time
from collections import defaultdict, deque
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr, ValidationError

from ui import dto
from ui.api_client import ApiClient
from ui.auth import LoginRequired, UserCredential
from ui.config import UiConfig
from ui.permissions import can
from ui.state import Workspace

STAMP = "2026-10-31T06:00:00Z"
ISSUER = "https://synthetic.example.test"
AUDIENCE = "isolated-ui-fixture"
PERMISSIONS = (
    "queue:read",
    "case:read",
    "case:assign",
    "case:review",
    "case:reopen",
    "note:read",
    "audit:read",
    "export:create",
    "batch:intake",
    "batch:read",
    "score:submit",
    "train:submit",
    "job:read",
    "job:retry",
)


def identity(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, "mad-frontend-fixture/" + name))


def fixture_case(index: int = 1) -> dict[str, Any]:
    unavailable = index == 200
    freshness = {2: "STALE", 3: "BUFFERING", 4: "PROVISIONAL_HIGHER", 200: "UNAVAILABLE"}.get(
        index, "COMPLETE"
    )
    score = {
        "data_tier": "research",
        "raw_score": None if unavailable else round(1 - ((index - 1) // 2) / 100, 3),
        "rank": None if unavailable else index,
        "percentile": None if unavailable else 100 * (200 - index) / 199,
        "freshness": freshness,
        "completeness": "COMPLETE"
        if freshness == "COMPLETE"
        else "INCOMPLETE"
        if freshness == "PROVISIONAL_HIGHER"
        else "UNKNOWN",
        "assessed_as_of": None if unavailable else STAMP,
        "published_at": None if unavailable else STAMP,
        "source_coverage": [
            {
                "source_id": "synthetic-source",
                "source_partition": "fixture",
                "window_start": "2026-10-30T06:00:00Z",
                "window_end": STAMP,
                "complete_through": STAMP,
                "expected_count": 200,
                "received_count": 200,
                "sequence_gaps": 0,
                "heartbeat_at": STAMP,
                "status": "COMPLETE",
            }
        ]
        if freshness == "COMPLETE"
        else [],
        "provenance_limitations": ["Synthetic in-sample demonstration; no evaluation claim."],
    }
    if index in {5, 6}:
        score["publication_event"] = "CORRECTED" if index == 5 else "RECONCILED"
    if index == 4:
        score["baseline_score_id"] = identity("baseline")
    return {
        "case_id": identity(f"case-{index}"),
        "record_key": f"synthetic-{index:04d}",
        "state": "QUEUED",
        "case_version": 0,
        "assignee": None,
        "conclusion": None,
        "score_id": identity(f"score-{index}"),
        "score": score,
        "run_id": identity("run"),
        "batch_id": identity("batch"),
        "model_id": identity("model"),
        "bundle_digest": "a" * 64,
        "policy_hash": "b" * 64,
        "dictionary_version": "anonymous_v1",
        "snapshot_id": identity("snapshot"),
        "queue_version": identity("queue"),
        "newer_assessment_available": index == 2,
        "newer_score_id": identity("corrected-score-2") if index == 2 else None,
    }


def fixture_evidence(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "score_id": case["score_id"],
        "dictionary_version": "anonymous_v1",
        "facts": None
        if case["score"]["freshness"] == "UNAVAILABLE"
        else {
            "scale": "log_odds",
            "base_value": -0.4,
            "raw_margin": 0.25,
            "raw_aggregates": [
                {
                    "raw_feature": "F3888",
                    "observed_value": 2.5,
                    "value_status": "OBSERVED",
                    "meaning_status": "UNVERIFIED",
                    "contribution": 0.8,
                    "reference_percentile": 61.0,
                },
                {
                    "raw_feature": "F12",
                    "observed_value": None,
                    "value_status": "IMPUTED",
                    "meaning_status": "UNVERIFIED",
                    "contribution": -0.15,
                    "encoded_detail": [{"column": "F12_missing", "contribution": -0.15}],
                },
            ],
        },
        "limitations": ["Synthetic evidence; field meanings are unverified."],
    }


def fixture_config(**changes: Any) -> UiConfig:
    values = dict(
        environment="local",
        mock_mode=True,
        api_base_url=ISSUER,
        api_issuer=ISSUER,
        api_audience=AUDIENCE,
        gateway_url=ISSUER + "/session",
        gateway_issuer=ISSUER,
        gateway_audience="fixture-workspace",
        gateway_jwks_url=ISSUER + "/keys",
        gateway_service_token=SecretStr("synthetic-unused-service-value-32-bytes"),
        login_url=ISSUER + "/login",
    )
    values.update(changes)
    return UiConfig.model_validate(values)


class FixtureProvider:
    def __init__(self, key: rsa.RSAPrivateKey, subject: str, config: UiConfig) -> None:
        if not config.mock_mode or config.environment not in {"local", "test"}:
            raise ValueError("Fixture identity requires explicit isolated configuration")
        self.actor_id = "oidc:" + hashlib.sha256((ISSUER + "\0" + subject).encode()).hexdigest()
        self.expires_at = int(time.time()) + 900
        self._token = SecretStr(
            jwt.encode(
                {
                    "iss": ISSUER,
                    "aud": AUDIENCE,
                    "sub": subject,
                    "iat": int(time.time()),
                    "exp": self.expires_at,
                },
                key,
                algorithm="RS256",
            )
        )
        self.closed = False

    def credential(self) -> UserCredential:
        if self.closed or self.expires_at <= time.time():
            raise LoginRequired()
        return UserCredential(self.actor_id, self.expires_at, "isolated-fixture", self._token)

    def logout(self) -> None:
        self.closed = True


class MockBackend:
    def __init__(
        self,
        key: rsa.RSAPublicKey,
        provider: FixtureProvider,
        permissions: tuple[str, ...] = PERMISSIONS,
        scope: str = "synthetic-team",
    ) -> None:
        self.key = key
        self.principal: dict[str, Any] = dict(
            actor_id=provider.actor_id,
            roles=["fixture"],
            permissions=list(permissions),
            scopes=[scope],
            permission_scopes={p: [scope] for p in permissions},
            role_scopes={"fixture": [scope]},
            expires_at=provider.expires_at,
        )
        self.cases = {identity(f"case-{i}"): fixture_case(i) for i in range(1, 201)}
        self.batch_state = "ACCEPTED"
        self.queue_heads = [
            {"queue_version": identity("queue"), "cohort_id": identity("cohort"), "version": 1}
        ]
        self.queue_members = {identity("queue"): list(self.cases)[:50]}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.histories: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.score_histories: dict[str, list[dict[str, Any]]] = {}
        from ui.mock.extensions import fixture_payloads

        self.extension_payloads = fixture_payloads(self.cases)
        self.export_expired: set[str] = set()
        self.export_requests: dict[str, dict[str, Any]] = {}
        self.export_bytes: dict[str, bytes] = {}
        self.effects: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}
        self.faults: dict[tuple[str, str], deque[int | str]] = defaultdict(deque)
        self.calls: list[tuple[str, str]] = []

    def inject(self, method: str, path: str, *faults: int | str) -> None:
        self.faults[(method, path)].extend(faults)

    def publish_queue(self, indices: list[int] | None = None) -> str:
        """A test publishes a new immutable membership list; the old version survives."""
        version = len(self.queue_members) + 1
        queue = identity(f"queue-{version}")
        self.queue_heads = [
            {"queue_version": queue, "cohort_id": identity("cohort"), "version": version}
        ]
        self.queue_members[queue] = [
            identity(f"case-{i}") for i in (indices if indices is not None else range(1, 51))
        ]
        return queue

    def complete_job(
        self,
        job_id: str,
        *,
        state: str = "SUCCEEDED",
        outcome: str = "ACCEPTED",
        codes: list[str] | None = None,
    ) -> None:
        job = self.jobs[job_id]
        job["state"] = state
        job["attempts"] = [{"attempt": 1, "started_at": STAMP}]
        if state == "FAILED":
            job["result"] = {"error_code": "JOB_FAILED"}
        elif job["kind"] == "intake":
            self.batch_state = outcome
            job["result"] = {
                "batch_id": identity("batch"),
                "outcome": outcome,
                "row_count": 200,
                "finding_codes": codes or [],
            }
        elif job["kind"] == "score":
            job["result"] = {
                "batch_id": identity("batch"),
                "model_id": identity("model"),
                "bundle_digest": "a" * 64,
                "queue_id": identity("queue"),
            }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        self.calls.append((method, path))
        headers = {"X-Request-ID": request.headers.get("X-Request-ID", identity("request"))}

        def response(status: int, payload: Any = None) -> httpx.Response:
            return httpx.Response(status, json=payload or {}, headers=headers)

        try:
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            claims = jwt.decode(
                token,
                self.key,
                algorithms=["RS256"],
                audience=AUDIENCE,
                issuer=ISSUER,
                options={"require": ["exp", "iat", "sub"]},
            )
            actor = "oidc:" + hashlib.sha256((ISSUER + "\0" + claims["sub"]).encode()).hexdigest()
            if actor != self.principal["actor_id"]:
                return response(403)
        except jwt.PyJWTError:
            return response(401)
        fault = self.faults[(method, path)].popleft() if self.faults[(method, path)] else None
        if isinstance(fault, int):
            return response(fault)
        if fault == "timeout":
            raise httpx.ReadTimeout("Fixture timeout")
        if fault == "connection":
            raise httpx.ConnectError("Fixture connection failure")
        if path == "/v1/me":
            return response(200, self.principal)
        if path in {"/health/live", "/health/ready"}:
            return response(200, {"state": "ready"})
        if path == "/v1/ui-extensions/deployment-status":
            return response(200, copy.deepcopy(self.extension_payloads["deployment-status"]))
        permission = self.permission(method, path, request.url.params.get("kind", "reviews"))
        if permission is None:
            return response(404)
        if not can(self.principal, permission) or "synthetic-team" not in self.principal["scopes"]:
            return response(403)
        try:
            if method == "GET":
                payload = self.read(path, dict(request.url.params))
                if isinstance(payload, bytes):
                    return httpx.Response(200, content=payload, headers=headers)
                return response(200, payload)
            key = str(UUID(request.headers.get("Idempotency-Key", "")))
            effect_key = (actor, path, key)
            digest = hashlib.sha256(
                request.content + request.headers.get("X-Batch-Manifest", "").encode()
            ).hexdigest()
            prior = self.effects.get(effect_key)
            if prior:
                return response(200, prior[1]) if prior[0] == digest else response(409)
            payload = {} if path == "/v1/batches" else json.loads(request.content)
            result = self.write(path, payload, key)
            self.effects[effect_key] = (digest, result)
            if fault == "after_commit_timeout":
                raise httpx.ReadTimeout("Fixture acknowledgement lost")
            return response(200 if "event_id" in result else 202, result)
        except KeyError:
            return response(404)
        except (ValidationError, ValueError, TypeError):
            return response(422)
        except FixtureConflict:
            return response(409)
        except FixtureDenied:
            return response(403)

    @staticmethod
    def permission(method: str, path: str, kind: str) -> str | None:
        if path.startswith("/v1/ui-extensions/"):
            return (
                "case:read"
                if "/case-context/" in path
                else "queue:read"
                if "/queue-context/" in path
                else "audit:read"
            )
        if path.startswith("/v1/queues"):
            return "queue:read"
        if path.startswith("/v1/cases/"):
            if method == "GET":
                return (
                    "audit:read" if path.endswith("/history") and kind == "audit" else "case:read"
                )
            return {
                "assignment": "case:assign",
                "start-review": "case:review",
                "reviews": "case:review",
                "reopen": "case:reopen",
            }.get(path.split("/")[-1])
        if path.startswith("/v1/jobs/"):
            return "job:read" if method == "GET" else "job:retry"
        if path.startswith("/v1/batches"):
            return "batch:read" if method == "GET" else "batch:intake"
        if path.startswith("/v1/exports"):
            return "export:create"
        return {"/v1/scoring-runs": "score:submit", "/v1/training-runs": "train:submit"}.get(
            path
        ) or ("case:read" if path.startswith("/v1/models/") else None)

    def read(self, path: str, params: dict[str, str]) -> Any:
        if path.startswith("/v1/ui-extensions/"):
            return copy.deepcopy(self.extension_payloads[path.removeprefix("/v1/ui-extensions/")])
        if path == "/v1/queues":
            return {"items": copy.deepcopy(self.queue_heads)}
        if path.startswith("/v1/queues/"):
            version_id = path.split("/")[3]
            if version_id not in self.queue_members or not path.endswith("/cases"):
                raise KeyError()
            rows = [
                {
                    **{
                        k: c[k]
                        for k in ("case_id", "record_key", "state", "case_version", "assignee")
                    },
                    **{k: c["score"][k] for k in ("rank", "raw_score", "percentile", "freshness")},
                }
                for c in (self.cases[case] for case in self.queue_members[version_id])
            ]
            rows = [
                r
                for r in rows
                if all(not params.get(k) or r[k] == params[k] for k in ("state", "assignee"))
            ]
            total = len(rows)
            if params.get("after_rank"):
                rows = [
                    r
                    for r in rows
                    if (r["rank"], r["record_key"])
                    > (int(params["after_rank"]), params.get("after_key", ""))
                ]
            limit = max(1, min(100, int(params.get("limit", "25"))))
            page = rows[:limit]
            cursor = (
                {"after_rank": page[-1]["rank"], "after_key": page[-1]["record_key"]}
                if len(rows) > limit
                else None
            )
            return dict(
                queue_version=version_id,
                version=list(self.queue_members).index(version_id) + 1,
                total=total,
                items=page,
                next=cursor,
                model_version="fixture-1",
                bundle_digest="a" * 64,
                batch_id=identity("batch"),
            )
        if path.startswith("/v1/cases/"):
            case = copy.deepcopy(self.cases[path.split("/")[3]])
            if path.endswith("/evidence"):
                return fixture_evidence(case)
            if path.endswith("/history"):
                rows = (
                    self.histories[case["case_id"]]
                    if params.get("kind") != "scores"
                    else [{"score_id": case["score_id"], "score": case["score"]}]
                )
                if params.get("kind") == "scores" and case["case_id"] in self.score_histories:
                    rows = self.score_histories[case["case_id"]]
                rows = copy.deepcopy(rows)
                if not can(self.principal, "note:read"):
                    for row in rows:
                        row.pop("note", None)
                offset, limit = int(params.get("after", "0")), int(params.get("limit", "20"))
                return {
                    "items": rows[offset : offset + limit],
                    "next": offset + limit if len(rows) > offset + limit else None,
                }
            return case
        if path.startswith("/v1/jobs/"):
            return self.jobs[path.split("/")[3]]
        if path == f"/v1/batches/{identity('batch')}":
            return dict(
                batch_id=identity("batch"),
                state=self.batch_state,
                validation_id=identity("validation"),
                created_at=STAMP,
            )
        if path == f"/v1/models/{identity('model')}":
            return dict(
                model_id=identity("model"),
                bundle_digest="a" * 64,
                tier="research_demo",
                registry_version="fixture-1",
            )
        if path.startswith("/v1/exports/") and path.endswith("/download"):
            if path.split("/")[3] in self.export_expired:
                raise KeyError()
            job = self.jobs[path.split("/")[3]]
            if job["kind"] != "export" or job["state"] != "SUCCEEDED":
                raise FixtureConflict()
            request = self.export_requests.get(path.split("/")[3], {})
            if set(request.get("columns", [])) & {"record_key", "note"} and not can(
                self.principal, "export:sensitive"
            ):
                raise FixtureDenied()
            return self.export_bytes.get(path.split("/")[3], b"case_id,rank,raw_score,state\r\n")
        raise KeyError()

    def write(self, path: str, payload: dict[str, Any], key: str) -> dict[str, Any]:
        if path.startswith("/v1/cases/"):
            case = self.cases[path.split("/")[3]]
            action = path.split("/")[-1]
            schemas: dict[str, type[dto.Request]] = {
                "assignment": dto.AssignmentRequest,
                "start-review": dto.VersionedRequest,
                "reviews": dto.ReviewRequest,
                "reopen": dto.ReopenRequest,
            }
            schemas[action].model_validate(payload)
            if (
                action in {"start-review", "reviews"}
                and case["assignee"] != self.principal["actor_id"]
            ):
                raise FixtureDenied()
            if payload["expected_version"] != case["case_version"]:
                raise FixtureConflict()
            allowed = {
                "assignment": {"QUEUED"},
                "start-review": {"ASSIGNED"},
                "reviews": {"IN_REVIEW"},
                "reopen": {"REVIEWED"},
            }
            if case["state"] not in allowed[action]:
                raise FixtureConflict()
            case["state"] = {
                "assignment": "ASSIGNED",
                "start-review": "IN_REVIEW",
                "reviews": "REVIEWED",
                "reopen": "ASSIGNED",
            }[action]
            case["assignee"] = payload.get("assignee") or self.principal["actor_id"]
            case["case_version"] += 1
            if action == "reviews":
                case["conclusion"] = payload["conclusion"]
            elif action in {"assignment", "reopen"}:
                case["conclusion"] = None
            result = dict(
                event_id=identity("event-" + key),
                case_id=case["case_id"],
                case_version=case["case_version"],
            )
            self.histories[case["case_id"]].append(
                {
                    **result,
                    "action": "case:reopen"
                    if action == "reopen"
                    else "case:assign"
                    if action == "assignment"
                    else "case:review",
                    "score_id": case["score_id"],
                    "actor_id": self.principal["actor_id"],
                    "conclusion": payload.get("conclusion"),
                    "note": payload.get("note") or payload.get("reason"),
                    "created_at": STAMP,
                }
            )
            return result
        kind = {
            "/v1/batches": "intake",
            "/v1/scoring-runs": "score",
            "/v1/training-runs": "train",
            "/v1/exports": "export",
        }.get(path)
        submission_schemas: dict[str, type[dto.Request]] = {
            "score": dto.ScoreSubmission,
            "train": dto.TrainingSubmission,
            "export": dto.ExportRequest,
        }
        submission_schema = submission_schemas.get(kind or "")
        if submission_schema:
            submission_schema.model_validate(payload)
        if path.endswith("/retry"):
            dto.RetryRequest.model_validate(payload)
            old = self.jobs[path.split("/")[3]]
            if old["state"] != "FAILED":
                raise FixtureConflict()
            kind = old["kind"]
        if not kind:
            raise KeyError()
        job_id = path.split("/")[3] if path.endswith("/retry") else identity("job-" + key)
        if kind == "export" and not path.endswith("/retry"):
            if set(payload["columns"]) & {"record_key", "note"} and not can(
                self.principal, "export:sensitive"
            ):
                raise FixtureDenied()
            members = self.queue_members[payload["queue_version"]]
            self.export_requests[job_id] = copy.deepcopy(payload)
            columns = payload["columns"] + [
                "queue_version",
                "bundle_digest",
                "policy_hash",
                "assessed_as_of",
                "freshness",
            ]
            output = io.StringIO(newline="")
            writer = csv.writer(output)
            writer.writerow(columns)
            for member in members:
                case = self.cases[member]
                if payload.get("state") and payload["state"] != case["state"]:
                    continue
                row = {**case, **case["score"]}
                events = self.histories[member]
                row["note"] = events[-1].get("note") if events else None
                values = []
                for column in columns:
                    value = row.get(column)
                    if isinstance(value, str) and (
                        value.startswith(("\t", "\r", "\n"))
                        or value.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "-", "@"))
                    ):
                        value = "'" + value
                    values.append(value)
                writer.writerow(values)
            self.export_bytes[job_id] = output.getvalue().encode()
        result = {"job_id": job_id, "state": "PENDING"}
        self.jobs[job_id] = {
            **result,
            "kind": kind,
            "created_at": STAMP,
            "attempts": [],
            "result": None,
        }
        return result


class FixtureConflict(Exception):
    pass


class FixtureDenied(Exception):
    pass


def create_workspace(
    *,
    permissions: tuple[str, ...] = PERMISSIONS,
    scope: str = "synthetic-team",
    subject: str = "developer",
    config: UiConfig | None = None,
) -> tuple[Workspace, MockBackend]:
    config = config or fixture_config()
    if not config.mock_mode or config.environment not in {"local", "test"}:
        raise ValueError("Explicit isolated fixture configuration is required")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    provider = FixtureProvider(key, subject, config)
    backend = MockBackend(key.public_key(), provider, permissions, scope)
    client = httpx.Client(
        base_url=config.api_base_url, transport=httpx.MockTransport(backend), trust_env=False
    )
    return Workspace(ApiClient(config, provider, client=client, sleep=lambda _: None)), backend
