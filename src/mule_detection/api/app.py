"""HTTP application factory; normal startup requires configured OIDC trust."""

import json
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any, BinaryIO, Literal, cast
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPBearer

from mule_detection.api.auth import AuthConfig, AuthenticationRequired, Principal, TokenVerifier
from mule_detection.api.dto import (
    Assignment,
    BatchView,
    CaseView,
    Enqueued,
    ErrorResponse,
    EvidenceView,
    ExportSubmission,
    HistoryView,
    JobView,
    ModelView,
    MutationView,
    OutcomeSubmission,
    OutcomeView,
    QueueView,
    Reopen,
    Retry,
    Review,
    ScoreSubmission,
    StartReview,
    TrainingSubmission,
)
from mule_detection.api.service import ApiService, NotFound
from mule_detection.domain.errors import DomainError
from mule_detection.domain.validation_policy import IntakeRejected
from mule_detection.persistence.errors import AccessDenied, LeaseLost, PersistenceConflict
from mule_detection.settings import Settings, load_settings


def create_app(
    settings: Settings | None = None,
    service_factory: Callable[[Settings], tuple[AuthConfig, ApiService]] | None = None,
) -> FastAPI:
    settings = settings or load_settings(Path.cwd(), secrets_dir=Path.cwd() / "secrets")
    if service_factory is not None:
        if settings.environment != "test":
            raise ValueError("Service injection is restricted to isolated test applications")
        auth, service = service_factory(settings)
        if not auth.isolated_test:
            raise ValueError("Injected applications must declare isolated test trust")
    else:
        from mule_detection.api.bootstrap import build_service

        auth = AuthConfig.load(settings.root_path, settings.environment)
        service = build_service(settings, auth)
    verifier = TokenVerifier(auth, settings.environment)
    app = FastAPI(
        title="Mule Review API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 413, 422, 503)},
    )
    app.state.service = service

    def failure(request: Request, status: int, code: str) -> JSONResponse:
        request_id = str(getattr(request.state, "request_id", uuid4()))
        headers = {"X-Request-ID": request_id, "Cache-Control": "no-store"}
        if status == 401:
            headers["WWW-Authenticate"] = "Bearer"
        return JSONResponse(
            status_code=status,
            content={"error": {"code": code, "request_id": request_id}},
            headers=headers,
        )

    @app.middleware("http")
    async def boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            request.state.request_id = UUID(request.headers.get("X-Request-ID", ""))
        except ValueError:
            request.state.request_id = uuid4()
        if request.method == "POST" and request.url.path != "/v1/batches":
            try:
                if int(request.headers.get("Content-Length", "0")) > 1_048_576:
                    return failure(request, 413, "BODY_TOO_LARGE")
                count = 0
                chunks = []
                async for chunk in request.stream():
                    count += len(chunk)
                    if count > 1_048_576:
                        return failure(request, 413, "BODY_TOO_LARGE")
                    chunks.append(chunk)
                request._body = b"".join(chunks)
            except (ValueError, RuntimeError):
                return failure(request, 400, "INVALID_REQUEST")
        try:
            response = await call_next(request)
        except Exception:
            return failure(request, 503, "DEPENDENCY_UNAVAILABLE")
        response.headers["X-Request-ID"] = str(request.state.request_id)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    async def auth_error(request: Request, error: Exception) -> JSONResponse:
        return failure(request, 401, "AUTHENTICATION_REQUIRED")

    async def denied(request: Request, error: Exception) -> JSONResponse:
        return failure(request, 403, "ACCESS_DENIED")

    async def missing(request: Request, error: Exception) -> JSONResponse:
        return failure(request, 404, "NOT_FOUND")

    async def conflict(request: Request, error: Exception) -> JSONResponse:
        return failure(request, 409, "VERSION_OR_IDEMPOTENCY_CONFLICT")

    async def invalid(request: Request, error: Exception) -> JSONResponse:
        return failure(request, 422, "INVALID_REQUEST")

    app.add_exception_handler(AuthenticationRequired, auth_error)
    app.add_exception_handler(AccessDenied, denied)
    app.add_exception_handler(NotFound, missing)
    app.add_exception_handler(PersistenceConflict, conflict)
    app.add_exception_handler(LeaseLost, conflict)
    app.add_exception_handler(RequestValidationError, invalid)
    app.add_exception_handler(ValueError, invalid)
    app.add_exception_handler(DomainError, invalid)
    app.add_exception_handler(IntakeRejected, invalid)

    bearer = HTTPBearer(auto_error=False)

    def identity(request: Request, token: Annotated[Any, Depends(bearer)]) -> Principal:
        principal = verifier.verify(request.headers.get("Authorization"))
        service.remember(principal)
        return principal

    User = Annotated[Principal, Depends(identity)]
    Key = Annotated[UUID, Header(alias="Idempotency-Key")]

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"state": "LIVE"}

    @app.get("/health/ready")
    def ready(request: Request) -> Response:
        return (
            JSONResponse({"state": "READY"})
            if service.ready()
            else failure(request, 503, "NOT_READY")
        )

    @app.get("/v1/me")
    def me(principal: User) -> dict[str, Any]:
        return principal.payload()

    @app.post("/v1/batches", status_code=202, response_model=Enqueued)
    async def upload(
        request: Request,
        principal: User,
        key: Key,
        manifest: Annotated[str, Header(alias="X-Batch-Manifest", max_length=16384)],
        filename: Annotated[str, Header(alias="X-Filename", max_length=200)] = "upload.csv",
    ) -> Any:
        principal.require("batch:intake")
        if request.headers.get("Content-Type", "").split(";")[0] != "application/octet-stream":
            return failure(request, 415, "UNSUPPORTED_MEDIA_TYPE")
        declaration = json.loads(manifest)
        if not isinstance(declaration, dict):
            raise ValueError()
        with tempfile.SpooledTemporaryFile(
            max_size=1_048_576, dir=str(service.raw.root / "staging")
        ) as stream:
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    return failure(request, 413, "BODY_TOO_LARGE")
                stream.write(chunk)
            stream.seek(0)
            # Storage and database calls run in a worker thread, never block the event loop.
            from starlette.concurrency import run_in_threadpool

            return await run_in_threadpool(
                service.upload,
                cast(BinaryIO, stream),
                declaration,
                filename,
                principal,
                key,
                request.state.request_id,
            )

    @app.get("/v1/batches/{batch_id}", response_model=BatchView)
    def batch(batch_id: UUID, principal: User) -> dict[str, Any]:
        return service.batch(batch_id, principal)

    @app.post("/v1/scoring-runs", status_code=202, response_model=Enqueued)
    def score(
        payload: ScoreSubmission, request: Request, principal: User, key: Key
    ) -> dict[str, Any]:
        principal.require("score:submit")
        return service.submit_model_work(
            "score", payload.model_dump(mode="json"), principal, key, request.state.request_id
        )

    @app.post("/v1/training-runs", status_code=202, response_model=Enqueued)
    def train(
        payload: TrainingSubmission, request: Request, principal: User, key: Key
    ) -> dict[str, Any]:
        principal.require("train:submit")
        return service.submit_model_work(
            "train", payload.model_dump(mode="json"), principal, key, request.state.request_id
        )

    @app.get("/v1/jobs/{job_id}", response_model=JobView)
    def job(job_id: UUID, principal: User) -> dict[str, Any]:
        return service.job(job_id, principal)

    @app.post("/v1/jobs/{job_id}/retry", status_code=202, response_model=Enqueued)
    def retry(
        job_id: UUID, payload: Retry, request: Request, principal: User, key: Key
    ) -> dict[str, Any]:
        return service.retry(job_id, principal, key, payload.reason, request.state.request_id)

    @app.get("/v1/queues")
    def queues(principal: User) -> dict[str, Any]:
        return service.queues(principal)

    @app.get("/v1/queues/{version}/cases", response_model=QueueView)
    def queue(
        version: UUID,
        request: Request,
        principal: User,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after_rank: Annotated[int | None, Query(ge=1)] = None,
        after_key: Annotated[str | None, Query(max_length=512)] = None,
        state: Literal["QUEUED", "ASSIGNED", "IN_REVIEW", "REVIEWED"] | None = None,
        assignee: Annotated[str | None, Query(max_length=100)] = None,
    ) -> dict[str, Any]:
        if set(request.query_params) - {"limit", "after_rank", "after_key", "state", "assignee"}:
            raise ValueError()
        if (after_rank is None) != (after_key is None):
            raise ValueError()
        return service.queue(version, principal, limit, after_rank, after_key, state, assignee)

    @app.get("/v1/cases/{case_id}", response_model=CaseView)
    def case(case_id: UUID, principal: User) -> dict[str, Any]:
        return service.case(case_id, principal)

    @app.get("/v1/cases/{case_id}/evidence", response_model=EvidenceView)
    def evidence(case_id: UUID, request: Request, principal: User) -> dict[str, Any]:
        return service.evidence(case_id, principal, request.state.request_id)

    @app.post("/v1/cases/{case_id}/assignment", response_model=MutationView)
    def assign(
        case_id: UUID, payload: Assignment, request: Request, principal: User, key: Key
    ) -> dict[str, Any]:
        return service.transition(
            case_id,
            principal,
            key,
            request.state.request_id,
            payload.expected_version,
            "ASSIGNED",
            assignee=payload.assignee,
        )

    @app.post("/v1/cases/{case_id}/start-review", response_model=MutationView)
    def start(
        case_id: UUID, payload: StartReview, request: Request, principal: User, key: Key
    ) -> dict[str, Any]:
        return service.transition(
            case_id, principal, key, request.state.request_id, payload.expected_version, "IN_REVIEW"
        )

    @app.post("/v1/cases/{case_id}/reviews", response_model=MutationView)
    def review(
        case_id: UUID, payload: Review, request: Request, principal: User, key: Key
    ) -> dict[str, Any]:
        return service.transition(
            case_id,
            principal,
            key,
            request.state.request_id,
            payload.expected_version,
            "REVIEWED",
            conclusion=payload.conclusion,
            note=payload.note,
        )

    @app.post("/v1/cases/{case_id}/reopen", response_model=MutationView)
    def reopen(
        case_id: UUID, payload: Reopen, request: Request, principal: User, key: Key
    ) -> dict[str, Any]:
        return service.transition(
            case_id,
            principal,
            key,
            request.state.request_id,
            payload.expected_version,
            "ASSIGNED",
            assignee=payload.assignee,
            reopen=True,
            note=payload.reason,
        )

    @app.get("/v1/cases/{case_id}/history", response_model=HistoryView)
    def history(
        case_id: UUID,
        request: Request,
        principal: User,
        kind: Literal["reviews", "scores", "audit"] = "reviews",
        after: Annotated[int, Query(ge=0, le=100000)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> dict[str, Any]:
        return service.history(case_id, principal, kind, after, limit, request.state.request_id)

    @app.post("/v1/exports", status_code=202, response_model=Enqueued)
    def export(
        payload: ExportSubmission, request: Request, principal: User, key: Key
    ) -> dict[str, Any]:
        return service.export(payload, principal, key, request.state.request_id)

    @app.get("/v1/exports/{job_id}/download")
    def download(job_id: UUID, request: Request, principal: User) -> Response:
        payload = service.download(job_id, principal, request.state.request_id)
        return Response(
            payload,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="review-{job_id}.csv"'},
        )

    @app.post("/v1/outcomes", response_model=OutcomeView)
    def outcomes(
        payload: OutcomeSubmission, request: Request, principal: User, key: Key
    ) -> dict[str, Any]:
        return service.outcomes(payload, principal, key, request.state.request_id)

    @app.get("/v1/models/{model_id}", response_model=ModelView)
    def model(model_id: UUID, principal: User) -> dict[str, Any]:
        return service.model(model_id, principal)

    # The local annotations above must be resolved before FastAPI/Pydantic evaluates them.
    return app
