from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import StrictInt, model_validator

from mule_detection.domain.contracts.common import Contract, Positive, Text, UtcTime, violation
from mule_detection.domain.errors import DomainError, ErrorCode


class QualifiedLabel(Contract):
    VERSION = "label_v1"
    contract_version: Literal["label_v1"]
    label_id: UUID
    record_key: Text
    account_id: Text
    value: StrictInt | None
    label_source: Text
    event_at: UtcTime
    observed_at: UtcTime
    available_at: UtcTime
    mature_at: UtcTime
    status: Literal["UNREVIEWED", "ADJUDICATED", "POLICY_NEGATIVE"]
    adjudication_reference: Text | None
    negative_policy_reference: Text | None
    version: Positive
    supersedes: UUID | None

    @model_validator(mode="after")
    def label_rules(self) -> Self:
        if (
            self.value not in (None, 0, 1)
            or not self.event_at <= self.observed_at <= self.available_at
            or self.mature_at < self.event_at
        ):
            raise violation(ErrorCode.LABEL_HISTORY_INVALID)
        if (self.version == 1) != (self.supersedes is None):
            raise violation(ErrorCode.LABEL_HISTORY_INVALID)
        if self.status == "UNREVIEWED" and self.value is not None:
            raise violation(ErrorCode.LABEL_HISTORY_INVALID)
        if self.status == "ADJUDICATED" and (
            self.value is None or self.adjudication_reference is None
        ):
            raise violation(ErrorCode.LABEL_HISTORY_INVALID)
        if self.status == "POLICY_NEGATIVE" and (
            self.value != 0 or not self.negative_policy_reference
        ):
            raise violation(ErrorCode.LABEL_HISTORY_INVALID)
        return self


def select_label_as_of(
    history: tuple[QualifiedLabel, ...], cutoff: datetime
) -> QualifiedLabel | None:
    if cutoff.utcoffset() is None:
        raise DomainError(ErrorCode.TIMESTAMP_NAIVE)
    ordered = sorted(history, key=lambda item: item.version)
    if ordered:
        first = ordered[0]
        for index, label in enumerate(ordered):
            if (label.record_key, label.account_id) != (first.record_key, first.account_id):
                raise DomainError(ErrorCode.LABEL_HISTORY_INVALID)
            if label.version != index + 1 or (
                index
                and (
                    label.supersedes != ordered[index - 1].label_id
                    or label.available_at < ordered[index - 1].available_at
                )
            ):
                raise DomainError(ErrorCode.LABEL_HISTORY_INVALID)
        if len({item.label_id for item in ordered}) != len(ordered):
            raise DomainError(ErrorCode.LABEL_HISTORY_INVALID)
    known = [item for item in ordered if item.available_at <= cutoff and item.observed_at <= cutoff]
    if not known:
        return None
    latest = known[-1]
    # A known but immature/unreviewed correction invalidates the obsolete mature label.
    return (
        latest
        if latest.mature_at <= cutoff and latest.status in ("ADJUDICATED", "POLICY_NEGATIVE")
        else None
    )
