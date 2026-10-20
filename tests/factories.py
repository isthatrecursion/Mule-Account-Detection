"""Deterministic fixtures, isolated from the historical private extract."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

FIXED_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def snapshots(seed: int = 42) -> list[dict[str, object]]:
    generator = random.Random(seed)
    return [
        {
            "account_id": f"synthetic-{i}",
            "snapshot_at": FIXED_TIME.isoformat(),
            "source_id": "synthetic-source",
            "label": i % 2,
            "S1": None if i == 2 else generator.random(),
            "category": "UNKNOWN" if i == 3 else "A",
        }
        for i in range(6)
    ]


def manifest() -> dict[str, object]:
    return {
        "batch_id": str(UUID(int=1)),
        "schema_version": "synthetic_v1",
        "row_count": 6,
        "source_id": "synthetic-source",
        "created_at": FIXED_TIME.isoformat(),
        "input_sha256": "a" * 64,
        "data_tier": "synthetic",
    }


def model_metadata() -> dict[str, str]:
    return {
        "model_version": "synthetic-v1",
        "model_tier": "research_demo",
        "bundle_sha256": "b" * 64,
    }


def actor_claims() -> dict[str, object]:
    return {"actor_id": "synthetic-analyst", "roles": ["analyst"], "issuer": "synthetic-test-only"}


def require_test_database(url: str) -> str:
    """No connection/reset is implemented; future fixtures must call this guard first."""
    parsed = urlsplit(url)
    name = parsed.path.lstrip("/")
    if (
        parsed.scheme != "postgresql+psycopg"
        or not parsed.hostname
        or not name.startswith("mule_test_")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("An explicitly dedicated mule_test_* database is required")
    return url
