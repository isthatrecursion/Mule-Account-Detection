"""Inject UTC wall time separately from real compute-duration measurement."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class ManualClock:
    instant: datetime

    def __post_init__(self) -> None:
        if self.instant.utcoffset() is None:
            raise ValueError("A timezone-aware instant is required")
        self.instant = self.instant.astimezone(UTC)

    def now(self) -> datetime:
        return self.instant

    def advance(self, delta: timedelta) -> None:
        if delta < timedelta(0):
            raise ValueError("Logical time cannot move backwards")
        self.instant += delta


class MonotonicTimer:
    def __init__(self) -> None:
        self._started = perf_counter()

    def elapsed_seconds(self) -> float:
        return perf_counter() - self._started
