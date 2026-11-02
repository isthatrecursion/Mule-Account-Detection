"""Bounded HTTP-only client. No response error text or raw exceptions reach the UI."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any, TypeVar
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel

from ui import dto
from ui.auth import LoginRequired, UserTokenProvider, effective_identity
from ui.config import UiConfig
from ui.copy import MESSAGES as MESSAGES
from ui.errors import ApiFailure as ApiFailure
from ui.errors import (
    Conflict,
    ConnectionUnavailable,
    ContractError,
    Forbidden,
    InvalidRequest,
    NotFound,
    RateLimited,
    RequestTimeout,
    ServerUnavailable,
)
from ui.extensions import ExtensionPayload
from ui.logging_setup import event


class ApiClient:
    def extension(self, kind: str, identity: UUID | None = None) -> ExtensionPayload:
        if kind not in {
            "models",
            "proposals",
            "reports",
            "source-health",
            "case-context",
            "queue-context",
            "deployment-status",
            "pilot-metrics",
        }:
            raise ValueError("Unsupported extension")
        if not self.config.mock_mode:
            raise NotFound()  # ASSUMPTION: no approved live extension routes exist yet.
        if kind.endswith("context") and identity is None:
            raise ValueError("An explicit version identity is required")
        path = "/v1/ui-extensions/" + kind + ("/" + str(identity) if identity else "")
        result = dto.parse(ExtensionPayload, self.request("GET", path), self._last_request_id)
        if result.kind != kind:
            raise ContractError(self._last_request_id)
        return result

    def __init__(
        self,
        config: UiConfig,
        provider: UserTokenProvider,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config, self.provider = config, provider
        self._sleep = sleep
        self._last_request_id: str | None = None
        self._last_status = 0
        self._client = client or httpx.Client(
            base_url=config.api_base_url.rstrip("/"),
            timeout=httpx.Timeout(
                config.read_timeout, connect=config.connect_timeout, write=config.write_timeout
            ),
            verify=config.verify_tls,
            follow_redirects=False,
            trust_env=False,
        )

    def _once(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        key: UUID | None = None,
        content: bytes | None = None,
        manifest: str | None = None,
        filename: str | None = None,
        params: dict[str, Any] | None = None,
        download: bool = False,
    ) -> Any:
        if (
            (not path.startswith("/v1/") and path not in {"/health/live", "/health/ready"})
            or any(v in path for v in ("..", "?", "#", "//"))
            or method not in {"GET", "POST"}
            or method == "POST"
            and key is None
        ):
            raise ValueError("A supported API operation and write identity are required")
        credential = self.provider.credential()
        request_id = str(uuid4())
        headers = {
            "Authorization": "Bearer " + credential.token.get_secret_value(),
            "X-Request-ID": request_id,
        }
        if key:
            headers["Idempotency-Key"] = str(key)
        if content is not None:
            headers.update(
                {
                    "Content-Type": "application/octet-stream",
                    "X-Batch-Manifest": manifest or "{}",
                    "X-Filename": filename or "upload.csv",
                }
            )
        try:
            with self._client.stream(
                method, path, json=payload, content=content, headers=headers, params=params
            ) as response:
                maximum = 16777216 if download else 4194304
                parts, count = [], 0
                for chunk in response.iter_bytes():
                    count += len(chunk)
                    if count > maximum:
                        raise ApiFailure("UNAVAILABLE", request_id=request_id)
                    parts.append(chunk)
                response_id = response.headers.get("X-Request-ID", request_id)
                try:
                    response_id = str(UUID(response_id))
                except ValueError:
                    response_id = request_id
                self._last_request_id = response_id
                self._last_status = response.status_code
                if response.status_code == 401:
                    raise LoginRequired()
                if response.status_code == 403:
                    raise Forbidden(response_id)
                if response.status_code == 404:
                    raise NotFound(response_id)
                if response.status_code == 409:
                    raise Conflict(response_id)
                if response.status_code == 429:
                    raise RateLimited(response_id)
                if response.status_code in {413, 415, 422}:
                    raise InvalidRequest(
                        "INVALID", status=response.status_code, request_id=response_id
                    )
                if response.status_code >= 500:
                    raise ServerUnavailable(
                        "UNAVAILABLE", status=response.status_code, request_id=response_id
                    )
                if not 200 <= response.status_code < 300:
                    raise ApiFailure(
                        "UNAVAILABLE", status=response.status_code, request_id=response_id
                    )
                body = b"".join(parts)
                if download:
                    return body
                value = json.loads(body)
                if not isinstance(value, dict):
                    raise ContractError(response_id)
                return value
        except (ApiFailure, LoginRequired):
            raise
        except httpx.TimeoutException:
            raise RequestTimeout("UNAVAILABLE", request_id=request_id) from None
        except httpx.TransportError:
            raise ConnectionUnavailable("UNAVAILABLE", request_id=request_id) from None
        except (ValueError, UnicodeError):
            raise ContractError(request_id) from None
        except Exception:
            raise ApiFailure("UNAVAILABLE", request_id=request_id) from None

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        # Only reads retry. A write's uncertain outcome belongs to PendingWrite.
        started = time.monotonic()
        try:
            for attempt in range(3):
                try:
                    value = self._once(method, path, **kwargs)
                    event(
                        action="fetch" if method == "GET" else "submit",
                        status=self._last_status,
                        request_id=self._last_request_id,
                        error_code="OK",
                        duration_ms=(time.monotonic() - started) * 1000,
                    )
                    return value
                except (ServerUnavailable, RateLimited):
                    if method != "GET" or attempt == 2:
                        raise
                    self._sleep(0.1 * 2**attempt)
        except ApiFailure as error:
            event(
                action="fetch" if method == "GET" else "submit",
                status=error.status,
                error_code=error.code,
                request_id=error.request_id,
                duration_ms=(time.monotonic() - started) * 1000,
            )
            raise
        raise ApiFailure("UNAVAILABLE")

    def json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        value = self.request(method, path, **kwargs)
        if not isinstance(value, dict):
            raise ContractError()
        model = response_model(method, path)
        if model:
            # Keep the established mapping interface for the existing pages.
            return dto.parse(model, value, self._last_request_id).model_dump(
                mode="json", exclude_unset=True
            )
        raise ContractError()

    def typed(self, model: type[T], method: str, path: str, **kwargs: Any) -> T:
        return dto.parse(model, self.json(method, path, **kwargs))

    def get_me(self) -> dto.Me:
        credential = self.provider.credential()
        return dto.parse(dto.Me, effective_identity(self.json("GET", "/v1/me"), credential))

    def me(self) -> dict[str, Any]:
        return self.get_me().model_dump(mode="json")

    def list_queues(self) -> dto.QueueVersions:
        return self.typed(dto.QueueVersions, "GET", "/v1/queues")

    def queues(self) -> dict[str, Any]:
        return self.list_queues().model_dump(mode="json")

    def get_queue(self, version: UUID, **filters: Any) -> dto.QueuePage:
        if set(filters) - {"limit", "state", "assignee", "after_rank", "after_key"}:
            raise ValueError("Unsupported queue filter")
        return self.typed(
            dto.QueuePage,
            "GET",
            f"/v1/queues/{version}/cases",
            params={k: v for k, v in filters.items() if v is not None},
        )

    def queue(self, version: UUID, **filters: Any) -> dict[str, Any]:
        return self.get_queue(version, **filters).model_dump(mode="json")

    def get_case(self, case_id: UUID) -> dto.CaseDetail:
        return self.typed(dto.CaseDetail, "GET", f"/v1/cases/{case_id}")

    def case(self, case_id: UUID) -> dict[str, Any]:
        return self.get_case(case_id).model_dump(mode="json")

    def get_evidence(self, case_id: UUID) -> dto.EvidencePayload:
        return self.typed(dto.EvidencePayload, "GET", f"/v1/cases/{case_id}/evidence")

    def evidence(self, case_id: UUID) -> dict[str, Any]:
        return self.get_evidence(case_id).model_dump(mode="json")

    def get_history(self, case_id: UUID, kind: str, after: int = 0) -> dto.HistoryPage:
        if kind not in {"reviews", "scores", "audit"}:
            raise ValueError("Unsupported history kind")
        return self.typed(
            dto.HistoryPage,
            "GET",
            f"/v1/cases/{case_id}/history",
            params={"kind": kind, "after": after, "limit": 20},
        )

    def history(self, case_id: UUID, kind: str, after: int = 0) -> dict[str, Any]:
        return self.get_history(case_id, kind, after).model_dump(mode="json", exclude_unset=True)

    def get_job(self, job_id: UUID) -> dto.JobStatus:
        return self.typed(dto.JobStatus, "GET", f"/v1/jobs/{job_id}")

    def job(self, job_id: UUID) -> dict[str, Any]:
        return self.get_job(job_id).model_dump(mode="json")

    def get_batch(self, batch_id: UUID) -> dto.BatchStatus:
        return self.typed(dto.BatchStatus, "GET", f"/v1/batches/{batch_id}")

    def intake(self, content: bytes, manifest: str, filename: str, *, key: UUID) -> dto.Enqueued:
        return self.typed(
            dto.Enqueued,
            "POST",
            "/v1/batches",
            content=content,
            manifest=manifest,
            filename=filename,
            key=key,
        )

    def score(self, request: dto.ScoreSubmission, *, key: UUID) -> dto.Enqueued:
        return self.typed(
            dto.Enqueued,
            "POST",
            "/v1/scoring-runs",
            payload=request.model_dump(mode="json"),
            key=key,
        )

    def train(self, request: dto.TrainingSubmission, *, key: UUID) -> dto.Enqueued:
        return self.typed(
            dto.Enqueued,
            "POST",
            "/v1/training-runs",
            payload=request.model_dump(mode="json"),
            key=key,
        )

    def retry_job(self, job_id: UUID, request: dto.RetryRequest, *, key: UUID) -> dto.Enqueued:
        return self.typed(
            dto.Enqueued,
            "POST",
            f"/v1/jobs/{job_id}/retry",
            payload=request.model_dump(mode="json"),
            key=key,
        )

    def assign(self, case_id: UUID, request: dto.AssignmentRequest, *, key: UUID) -> dto.Mutation:
        return self.typed(
            dto.Mutation,
            "POST",
            f"/v1/cases/{case_id}/assignment",
            payload=request.model_dump(mode="json"),
            key=key,
        )

    def start_review(
        self, case_id: UUID, request: dto.VersionedRequest, *, key: UUID
    ) -> dto.Mutation:
        return self.typed(
            dto.Mutation,
            "POST",
            f"/v1/cases/{case_id}/start-review",
            payload=request.model_dump(mode="json"),
            key=key,
        )

    def review(self, case_id: UUID, request: dto.ReviewRequest, *, key: UUID) -> dto.Mutation:
        return self.typed(
            dto.Mutation,
            "POST",
            f"/v1/cases/{case_id}/reviews",
            payload=request.model_dump(mode="json"),
            key=key,
        )

    def reopen(self, case_id: UUID, request: dto.ReopenRequest, *, key: UUID) -> dto.Mutation:
        return self.typed(
            dto.Mutation,
            "POST",
            f"/v1/cases/{case_id}/reopen",
            payload=request.model_dump(mode="json"),
            key=key,
        )

    def export(self, request: dto.ExportRequest, *, key: UUID) -> dto.Enqueued:
        return self.typed(
            dto.Enqueued, "POST", "/v1/exports", payload=request.model_dump(mode="json"), key=key
        )

    def download(self, job_id: UUID) -> bytes:
        value = self.request("GET", f"/v1/exports/{job_id}/download", download=True)
        if not isinstance(value, bytes):
            raise ContractError()
        return value

    def health(self, readiness: bool = False) -> dto.Health:
        return self.typed(dto.Health, "GET", "/health/ready" if readiness else "/health/live")

    def model(self, model_id: UUID) -> dto.ModelInfo:
        return self.typed(dto.ModelInfo, "GET", f"/v1/models/{model_id}")


T = TypeVar("T", bound=BaseModel)


def response_model(method: str, path: str) -> type[BaseModel] | None:
    if method == "POST":
        if re.fullmatch(r"/v1/cases/[^/]+/(assignment|start-review|reviews|reopen)", path):
            return dto.Mutation
        if path in {
            "/v1/batches",
            "/v1/scoring-runs",
            "/v1/training-runs",
            "/v1/exports",
        } or re.fullmatch(r"/v1/jobs/[^/]+/retry", path):
            return dto.Enqueued
        return None
    routes: tuple[tuple[str, type[BaseModel]], ...] = (
        (r"/v1/me", dto.Me),
        (r"/v1/queues", dto.QueueVersions),
        (r"/v1/queues/[^/]+/cases", dto.QueuePage),
        (r"/v1/cases/[^/]+", dto.CaseDetail),
        (r"/v1/cases/[^/]+/evidence", dto.EvidencePayload),
        (r"/v1/cases/[^/]+/history", dto.HistoryPage),
        (r"/v1/jobs/[^/]+", dto.JobStatus),
        (r"/v1/batches/[^/]+", dto.BatchStatus),
        (r"/v1/models/[^/]+", dto.ModelInfo),
        (r"/health/(live|ready)", dto.Health),
    )
    return next((model for pattern, model in routes if re.fullmatch(pattern, path)), None)
