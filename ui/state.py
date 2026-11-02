"""Per-session state: bound read cache, pinned navigation and explicit pending writes."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from ui.api_client import ApiClient, ApiFailure
from ui.auth import LoginRequired
from ui.cache import SessionCache as SessionCache
from ui.permissions import can


@dataclass
class PendingWrite:
    action: str
    path: str
    payload: dict[str, Any] | None = field(repr=False)
    fingerprint: str
    key: UUID = field(default_factory=uuid4)
    content: bytes | None = field(default=None, repr=False)
    manifest: str | None = field(default=None, repr=False)
    filename: str | None = field(default=None, repr=False)
    state: str = "PENDING"
    result: dict[str, Any] | None = None
    latest: dict[str, Any] | None = field(default=None, repr=False)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    original: dict[str, Any] | None = field(default=None, repr=False)
    history: list[dict[str, Any]] = field(default_factory=list, repr=False)


@dataclass
class Workspace:
    api: ApiClient = field(repr=False)
    identity: dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""
    cache: SessionCache = field(default_factory=SessionCache, repr=False)
    pending: PendingWrite | None = field(default=None, repr=False)
    jobs: list[str] = field(default_factory=list)
    queue_version: str | None = None
    queue_cohort: str | None = None
    cursor: dict[str, Any] = field(default_factory=dict)
    previous_cursors: list[dict[str, Any]] = field(default_factory=list)
    queue_filters: dict[str, Any] = field(default_factory=dict)
    accepted_batches: list[str] = field(default_factory=list)
    selected_case: str | None = None
    history_after: dict[str, int] = field(default_factory=dict)
    last_poll: dict[str, float] = field(default_factory=dict)
    job_views: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    last_result: dict[str, Any] | None = None
    form_cases: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC), repr=False)
    poll_started: dict[str, float] = field(default_factory=dict)
    selected_record: str | None = None
    selected_queue: str | None = None
    pinned_scores: dict[str, str] = field(default_factory=dict)
    export_receipts: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    def authenticate(self) -> None:
        value = self.api.me()  # Authorization decisions are never read from cache.
        current = hashlib.sha256(
            json.dumps(
                {
                    **{
                        k: value[k]
                        for k in ("actor_id", "roles", "permissions", "scopes", "permission_scopes")
                    },
                    "configuration": self.api.config.fingerprint(),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if self.fingerprint and current != self.fingerprint:
            self.clear_sensitive()
        self.identity, self.fingerprint = value, current

    def allowed(self, permission: str) -> bool:
        return can(self.identity, permission)

    def begin(
        self, action: str, path: str, payload: dict[str, Any] | None, **upload: Any
    ) -> PendingWrite:
        if self.pending and self.pending.state in {"PENDING", "UNKNOWN", "CONFLICT"}:
            raise ValueError("Resolve the pending action before submitting another")
        self.pending = PendingWrite(
            action, path, copy.deepcopy(payload), self.fingerprint, **upload
        )
        if path.startswith("/v1/cases/"):
            self.pending.original = copy.deepcopy(self.form_cases.get(path.split("/")[3]))
        return self.pending

    def submit(self) -> dict[str, Any]:
        pending = self.pending
        if pending is None or pending.fingerprint != self.fingerprint:
            raise LoginRequired()
        if pending.result is not None:
            return pending.result
        if pending.state == "CONFLICT":
            raise ApiFailure("CONFLICT", status=409)
        try:
            result = self.api.json(
                "POST",
                pending.path,
                payload=pending.payload,
                key=pending.key,
                content=pending.content,
                manifest=pending.manifest,
                filename=pending.filename,
            )
        except LoginRequired:
            pending.state = "UNKNOWN"
            raise
        except ApiFailure as error:
            pending.state = (
                "CONFLICT"
                if error.status == 409
                else "UNKNOWN"
                if error.code in {"UNAVAILABLE", "CONTRACT"}
                else "REJECTED"
            )
            if error.status == 409 and pending.path.startswith("/v1/cases/"):
                pending.latest = self.api.case(UUID(pending.path.split("/")[3]))
                self.check_pending()
            elif pending.state == "UNKNOWN" and pending.path.startswith("/v1/cases/"):
                self.check_pending()
            raise
        if pending.path == "/v1/exports" and result.get("job_id"):
            self.export_receipts[result["job_id"]] = copy.deepcopy(pending.payload or {})
        pending.state, pending.result = "ACKNOWLEDGED", result
        pending.content = None
        self.last_result = result
        if result.get("job_id"):
            self.reconnect_job(result["job_id"])
            self.job_views.pop(result["job_id"], None)
            self.last_poll.pop(result["job_id"], None)
            self.poll_started[result["job_id"]] = self.clock()
        self.cache.clear()
        if pending.path.startswith("/v1/cases/"):
            self.form_cases.pop(pending.path.split("/")[3], None)
        return result

    def poll(self, job_id: str, *, force: bool = False) -> dict[str, Any]:
        now = self.clock()
        self.poll_started.setdefault(job_id, now)
        if (
            not force
            and job_id in self.job_views
            and (
                self.job_views[job_id]["state"] in {"SUCCEEDED", "FAILED"}
                or now - self.poll_started[job_id] >= self.api.config.max_poll_seconds
            )
        ):
            return self.job_views[job_id]
        if force or now - self.last_poll.get(job_id, -1000) >= self.api.config.poll_seconds:
            self.job_views[job_id] = self.api.job(UUID(job_id))
            self.last_poll[job_id] = now
            job = self.job_views[job_id]
            result = job.get("result") or {}
            batch = result.get("batch_id")
            if (
                job["kind"] == "intake"
                and job["state"] == "SUCCEEDED"
                and result.get("outcome") == "ACCEPTED"
                and batch
            ):
                if batch not in self.accepted_batches:
                    self.accepted_batches.append(batch)
        return self.job_views[job_id]

    def reconnect_job(self, value: str) -> None:
        identity = str(UUID(value))
        if identity not in self.jobs:
            self.jobs.append(identity)
        self.poll_started.setdefault(identity, self.clock())

    def polling_active(self, kind: str | None = None) -> bool:
        return any(
            (kind is None or self.job_views.get(job, {}).get("kind") == kind)
            and self.job_views.get(job, {}).get("state") not in {"SUCCEEDED", "FAILED"}
            and self.clock() - self.poll_started.get(job, self.clock())
            < self.api.config.max_poll_seconds
            for job in self.jobs[-20:]
        )

    def check_pending(self) -> None:
        """Read current state, never infer acknowledgement by matching note text."""
        pending = self.pending
        if pending is None or not pending.path.startswith("/v1/cases/"):
            return
        case_id = UUID(pending.path.split("/")[3])
        try:
            pending.latest = self.api.case(case_id)
            pending.history = self.api.history(case_id, "reviews")["items"]
        except ApiFailure:
            # Keep the original failure and request; a read outage proves no outcome.
            pass

    def open_case(self, case_id: str, record_key: str, queue_version: str) -> None:
        self.selected_case, self.selected_record, self.selected_queue = (
            case_id,
            record_key,
            queue_version,
        )

    def choose_queue(self, identity: str, cohort: str | None = None) -> None:
        if identity != self.queue_version:
            self.queue_version, self.queue_cohort = identity, cohort
            self.cursor, self.previous_cursors, self.history_after = {}, [], {}

    def clear_sensitive(self) -> None:
        self.cache.clear()
        self.pending, self.last_result, self.selected_case = None, None, None
        self.queue_version, self.queue_cohort = None, None
        self.cursor, self.previous_cursors, self.history_after = {}, [], {}
        self.queue_filters.clear()
        self.accepted_batches.clear()
        self.jobs, self.job_views, self.last_poll = [], {}, {}
        self.form_cases.clear()
        self.poll_started.clear()
        self.selected_record = self.selected_queue = None
        self.pinned_scores.clear()
        self.export_receipts.clear()

    def logout(self) -> None:
        self.clear_sensitive()
        self.identity, self.fingerprint = {}, ""
        self.api.provider.logout()

    def suspend(self) -> PendingWrite | None:
        """Retain only an unresolved request, in this server session, across expiry."""
        retained = self.pending
        if retained and retained.state not in {"PENDING", "UNKNOWN", "CONFLICT"}:
            retained = None
        if retained:
            retained.latest = None
            retained.history = []
            retained.original = None
        self.logout()
        return retained

    def restore_pending(self, retained: PendingWrite | None) -> bool:
        """A new verified actor/scope fingerprint must match before exposing the draft."""
        if retained is None or not self.fingerprint or retained.fingerprint != self.fingerprint:
            return False
        self.pending = retained
        if retained.state == "CONFLICT" and retained.path.startswith("/v1/cases/"):
            retained.latest = self.api.case(UUID(retained.path.split("/")[3]))
        return True
