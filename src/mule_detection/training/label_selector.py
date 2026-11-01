"""Historical label selection validates only history visible at the requested cutoff."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from mule_detection.domain.contracts.common import utc
from mule_detection.domain.contracts.labels import QualifiedLabel, select_label_as_of
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.persistence.models import Label


@dataclass(frozen=True)
class LabelSnapshot:
    record_key: str
    account_id: str
    snapshot_at: datetime
    available_at: datetime


def select_training_labels(
    snapshots: tuple[LabelSnapshot, ...],
    histories: tuple[QualifiedLabel, ...],
    cutoff: datetime,
) -> tuple[dict[str, QualifiedLabel], dict[str, int]]:
    cutoff = utc(cutoff)
    visible: dict[str, list[QualifiedLabel]] = defaultdict(list)
    for historical_label in histories:
        if historical_label.available_at <= cutoff and historical_label.observed_at <= cutoff:
            visible[historical_label.record_key].append(historical_label)
    if len({s.record_key for s in snapshots}) != len(snapshots):
        raise DomainError(ErrorCode.IDENTITY_CONFLICT)
    selected: dict[str, QualifiedLabel] = {}
    counts: Counter[str] = Counter(
        {
            name: 0
            for name in (
                "eligible",
                "unknown",
                "immature",
                "corrected",
                "source_assumed_negative",
                "feature_after_outcome",
                "future_snapshot",
            )
        }
    )
    for snapshot in snapshots:
        observed, available = utc(snapshot.snapshot_at), utc(snapshot.available_at)
        if observed > available or available > cutoff:
            counts["future_snapshot"] += 1
            continue
        history = tuple(visible.get(snapshot.record_key, ()))
        latest = max(history, key=lambda label: label.version) if history else None
        label = select_label_as_of(history, cutoff)
        if latest and latest.account_id != snapshot.account_id:
            raise DomainError(ErrorCode.IDENTITY_CONFLICT)
        if latest and latest.version > 1:
            counts["corrected"] += 1
        if label is None:
            counts["immature" if latest and latest.mature_at > cutoff else "unknown"] += 1
        elif available > label.event_at or observed >= label.event_at:
            counts["feature_after_outcome"] += 1
        else:
            selected[snapshot.record_key] = label
            counts["eligible"] += 1
            counts["source_assumed_negative"] += int(label.status == "POLICY_NEGATIVE")
    return selected, dict(counts)


def select_repository_labels(
    session: Session,
    snapshots: tuple[LabelSnapshot, ...],
    cutoff: datetime,
    resolve_contract: Callable[[UUID], QualifiedLabel],
) -> tuple[dict[str, QualifiedLabel], dict[str, int]]:
    """Join durable known-at metadata to trusted outcome-owner contracts.

    Existing operational label rows do not contain certified outcome-window and
    adjudication details. The approved outcome adapter must resolve those by ID;
    absence of that adapter cannot be replaced with guessed maturity metadata.
    Future versions are excluded in SQL before their contracts are requested.
    """
    cutoff = utc(cutoff)
    rows = session.scalars(
        select(Label)
        .where(Label.subject_key.in_([s.record_key for s in snapshots]), Label.known_at <= cutoff)
        .order_by(Label.subject_key, Label.known_at, Label.id)
    ).all()
    histories = []
    for row in rows:
        contract = resolve_contract(row.id)
        if (
            contract.label_id != row.id
            or contract.record_key != row.subject_key
            or contract.available_at != row.known_at
            or contract.supersedes != row.supersedes_id
            or str(contract.value) != row.outcome
        ):
            raise DomainError(ErrorCode.LABEL_HISTORY_INVALID)
        histories.append(contract)
    return select_training_labels(snapshots, tuple(histories), cutoff)
