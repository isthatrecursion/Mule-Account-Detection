"""Keyed research folds and purged, entity-disjoint temporal partitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from sklearn.model_selection import StratifiedKFold  # type: ignore[import-untyped]

from mule_detection.domain.contracts.common import canonical_hash, utc
from mule_detection.domain.errors import DomainError, ErrorCode


@dataclass(frozen=True)
class Fold:
    number: int
    train_keys: tuple[str, ...]
    validation_keys: tuple[str, ...]

    def manifest(self) -> dict[str, Any]:
        content = {
            "fold": self.number,
            "train_keys": self.train_keys,
            "validation_keys": self.validation_keys,
        }
        return {**content, "membership_hash": canonical_hash(content)}


def research_folds(keys: tuple[str, ...], target: Any, count: int, seed: int) -> tuple[Fold, ...]:
    y = np.asarray(target)
    if (
        len(keys) != len(y)
        or len(keys) != len(set(keys))
        or count < 2
        or not np.isin(y, [0, 1]).all()
        or min(int((y == 0).sum()), int((y == 1).sum())) < count
    ):
        raise DomainError(ErrorCode.SPLIT_MISMATCH)
    return tuple(
        Fold(number, tuple(keys[i] for i in train), tuple(keys[i] for i in valid))
        for number, (train, valid) in enumerate(
            StratifiedKFold(count, shuffle=True, random_state=seed).split(np.zeros(len(y)), y), 1
        )
    )


@dataclass(frozen=True)
class TemporalRecord:
    record_key: str
    account_id: str
    entity_groups: frozenset[str]
    snapshot_at: datetime
    label: int
    label_available_at: datetime
    label_mature_at: datetime


@dataclass(frozen=True)
class Window:
    name: str
    start: datetime
    end: datetime
    label_as_of: datetime


def temporal_partitions(
    records: tuple[TemporalRecord, ...],
    windows: tuple[Window, ...],
    *,
    feature_lookback: timedelta,
    outcome_window: timedelta,
) -> dict[str, Any]:
    names = ("train", "tuning", "calibration", "final_acceptance")
    if (
        tuple(w.name for w in windows) != names
        or feature_lookback < timedelta(0)
        or outcome_window < timedelta(0)
    ):
        raise DomainError(ErrorCode.SPLIT_MISMATCH)
    for i, window in enumerate(windows):
        start, end, as_of = utc(window.start), utc(window.end), utc(window.label_as_of)
        if (
            start >= end
            or as_of < end
            or (i and start < windows[i - 1].end + feature_lookback + outcome_window)
        ):
            raise DomainError(ErrorCode.SPLIT_MISMATCH)
    if len({r.record_key for r in records}) != len(records):
        raise DomainError(ErrorCode.IDENTITY_CONFLICT)
    # Union all identifiers before assignment: a bridging entity links otherwise
    # different account/group names and cannot evade disjointness checks.
    parent: dict[str, str] = {}

    def find(value: str) -> str:
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]

    for record in records:
        identifiers = [
            "account:" + record.account_id,
            *("entity:" + g for g in record.entity_groups),
        ]
        for value in identifiers[1:]:
            parent[find(value)] = find(identifiers[0])
    partitions: dict[str, list[str]] = {name: [] for name in names}
    reasons: dict[str, str] = {}
    component_windows: dict[str, set[str]] = {}
    assignments: dict[str, str] = {}
    by_key = {r.record_key: r for r in records}
    for record in sorted(records, key=lambda r: (r.snapshot_at, r.record_key)):
        at = utc(record.snapshot_at)
        matches = [w for w in windows if w.start <= at < w.end]
        if not matches:
            reasons[record.record_key] = "OUTSIDE_WINDOWS_OR_PURGE_GAP"
            continue
        window = matches[0]
        if (
            record.label not in (0, 1)
            or utc(record.label_available_at) > window.label_as_of
            or utc(record.label_mature_at) > window.label_as_of
        ):
            reasons[record.record_key] = "IMMATURE_OR_UNAVAILABLE_LABEL"
            continue
        component = find("account:" + record.account_id)
        assignments[record.record_key] = window.name
        component_windows.setdefault(component, set()).add(window.name)
    for key, name in assignments.items():
        if len(component_windows[find("account:" + by_key[key].account_id)]) > 1:
            reasons[key] = "CROSS_PARTITION_CONNECTED_ENTITY"
        else:
            partitions[name].append(key)
    for members in partitions.values():
        if {by_key[key].label for key in members} != {0, 1}:
            raise DomainError(ErrorCode.SPLIT_MISMATCH)
    content: dict[str, Any] = {
        "partitions": partitions,
        "exclusion_reasons": reasons,
        "windows": [
            {
                "name": w.name,
                "start": w.start.isoformat(),
                "end": w.end.isoformat(),
                "label_as_of": w.label_as_of.isoformat(),
            }
            for w in windows
        ],
        "purge_seconds": (feature_lookback + outcome_window).total_seconds(),
        "counts": {
            name: {
                "rows": len(members),
                "positives": sum(by_key[k].label for k in members),
                "groups": len({find("account:" + by_key[k].account_id) for k in members}),
            }
            for name, members in partitions.items()
        },
    }
    return {**content, "membership_hash": canonical_hash(content)}
