"""Allowlisted JSON logs: arbitrary messages, extras and exceptions are discarded."""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import TextIO

from mule_detection.domain.errors import ErrorCode

EVENTS = {"command_started", "command_completed", "command_failed", "configuration_loaded"}
IDENTIFIERS = (
    "request_id",
    "job_id",
    "batch_id",
    "model_version",
    "data_version",
    "correlation_id",
)
SAFE_ID = re.compile(r"[a-zA-Z0-9_.:-]{1,128}\Z")


class SafeJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event", None)
        payload: dict[str, object] = {
            "event": event if isinstance(event, str) and event in EVENTS else "redacted_event",
            "component": "cli",
            "severity": record.levelname,
        }
        for name in IDENTIFIERS:
            value = getattr(record, name, None)
            if isinstance(value, str) and SAFE_ID.fullmatch(value):
                payload[name] = value
        code = getattr(record, "error_code", None)
        if isinstance(code, str) and code in {item.value for item in ErrorCode}:
            payload["error_code"] = code
        duration = getattr(record, "duration_seconds", None)
        if isinstance(duration, (int, float)) and 0 <= duration < 1e12:
            payload["duration_seconds"] = duration
        fingerprint = getattr(record, "config_fingerprint", None)
        if isinstance(fingerprint, str) and re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            payload["config_fingerprint"] = fingerprint
        # Never use getMessage(), args, exception text/traceback, arbitrary extras or notes.
        return json.dumps(payload, allow_nan=False)


def configure_logging(stream: TextIO | None = None) -> logging.Logger:
    logger = logging.getLogger("mule_detection")
    logger.handlers.clear()
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(SafeJsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
