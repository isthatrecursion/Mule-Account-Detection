"""Record durations and fixed categories only; never measure by logging records."""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from ui.logging_setup import event


@contextmanager
def timed_render(page: str, clock: Callable[[], float] = time.perf_counter) -> Iterator[None]:
    started = clock()
    try:
        yield
    finally:
        event(page=page, action="render", duration_ms=max(0.0, clock() - started) * 1000)
