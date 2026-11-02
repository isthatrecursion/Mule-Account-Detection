"""Allowlisted operational logs discard free text, exception details and extra data."""

import json
import logging
import math
from typing import TextIO
from uuid import UUID

PAGES = frozenset({"app", "queue", "case", "history", "operations", "exports", "gallery"})
ACTIONS = frozenset({"fetch", "submit", "render", "login", "logout", "contract"})
CODES = frozenset(
    {
        "OK",
        "UNAVAILABLE",
        "DENIED",
        "NOT_FOUND",
        "CONFLICT",
        "INVALID",
        "RATE_LIMITED",
        "CONTRACT",
        "LOGIN_REQUIRED",
    }
)


class SafeJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Never call getMessage()/formatException(): both can contain arbitrary secrets.
        value: dict[str, object] = {"event": "ui_operation"}
        for name, allowed in (("page", PAGES), ("action", ACTIONS), ("error_code", CODES)):
            item = getattr(record, name, None)
            if isinstance(item, str) and item in allowed:
                value[name] = item
        identity = getattr(record, "request_id", None)
        try:
            if isinstance(identity, str):
                value["request_id"] = str(UUID(identity))
        except ValueError:
            pass
        status = getattr(record, "status", None)
        if type(status) is int and 0 <= status <= 599:
            value["status"] = status
        duration = getattr(record, "duration_ms", None)
        if (
            isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and math.isfinite(duration)
            and duration >= 0
        ):
            value["duration_ms"] = round(duration, 2)
        return json.dumps(value, ensure_ascii=True)


def configure_logging(stream: TextIO | None = None) -> logging.Logger:
    logger = logging.getLogger("mad.ui")
    if not logger.handlers or stream is not None:
        handler = logging.StreamHandler(stream)
        handler.setFormatter(SafeJsonFormatter())
        logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def event(**fields: object) -> None:
    configure_logging().info("ui_operation", extra=fields)
