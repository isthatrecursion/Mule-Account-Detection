"""Errors contain stable classifications, never API bodies or exception payloads."""

from uuid import UUID

from ui.copy import MESSAGES


class ApiFailure(Exception):
    def __init__(self, code: str, *, status: int = 0, request_id: str | None = None) -> None:
        self.code = code if code in MESSAGES else "UNAVAILABLE"
        self.status = status
        try:
            self.request_id = str(UUID(request_id)) if request_id else None
        except ValueError:
            self.request_id = None
        self.safe_message = MESSAGES[self.code]
        super().__init__(self.code)


class ContractError(ApiFailure):
    def __init__(self, request_id: str | None = None) -> None:
        super().__init__("CONTRACT", request_id=request_id)


class Forbidden(ApiFailure):
    def __init__(self, request_id: str | None = None) -> None:
        super().__init__("DENIED", status=403, request_id=request_id)


class NotFound(ApiFailure):
    def __init__(self, request_id: str | None = None) -> None:
        super().__init__("NOT_FOUND", status=404, request_id=request_id)


class Conflict(ApiFailure):
    def __init__(self, request_id: str | None = None) -> None:
        super().__init__("CONFLICT", status=409, request_id=request_id)


class InvalidRequest(ApiFailure):
    pass


class RateLimited(ApiFailure):
    def __init__(self, request_id: str | None = None) -> None:
        super().__init__("RATE_LIMITED", status=429, request_id=request_id)


class ServerUnavailable(ApiFailure):
    pass


class RequestTimeout(ServerUnavailable):
    pass


class ConnectionUnavailable(ServerUnavailable):
    pass
