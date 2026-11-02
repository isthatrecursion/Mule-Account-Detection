"""Sensitive reads belong to one workspace, never a global Streamlit cache."""

import copy
import json
import time
from collections.abc import Callable
from typing import Any

# Authorization and mutable workflow versions are intentionally absent.
CACHE_POLICY = {"queue": 5, "evidence": 15, "history": 5, "extension": 5}


class SessionCache:
    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._values: dict[str, tuple[float, Any]] = {}
        self._clock = clock or (lambda: time.monotonic())

    def cached_get(
        self,
        endpoint: str,
        params: dict[str, Any],
        *,
        actor_fingerprint: str,
        scope_fingerprint: str,
        data_version: str,
        ttl_seconds: int,
        load: Callable[[], Any],
    ) -> Any:
        category = endpoint.split(":", 1)[0]
        maximum = CACHE_POLICY.get(category)
        if not actor_fingerprint or not scope_fingerprint or not data_version or maximum is None:
            return load()
        ttl = min(maximum, max(0, ttl_seconds))
        key = json.dumps(
            [actor_fingerprint, scope_fingerprint, endpoint, data_version, params], sort_keys=True
        )
        current = self._values.get(key)
        if current and current[0] > self._clock():
            return copy.deepcopy(current[1])
        value = load()
        self._values[key] = (self._clock() + ttl, copy.deepcopy(value))
        if len(self._values) > 128:
            self._values.pop(next(iter(self._values)))
        return value

    def read(
        self,
        fingerprint: str,
        endpoint: str,
        version: str,
        filters: dict[str, Any],
        seconds: int,
        load: Callable[[], Any],
    ) -> Any:
        # Compatibility: Workspace's fingerprint already binds actor, grants and scopes.
        return self.cached_get(
            endpoint,
            filters,
            actor_fingerprint=fingerprint,
            scope_fingerprint=fingerprint,
            data_version=version,
            ttl_seconds=seconds,
            load=load,
        )

    def clear(self) -> None:
        self._values.clear()
