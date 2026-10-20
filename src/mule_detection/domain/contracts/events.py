from typing import Literal, Self

from pydantic import model_validator

from mule_detection.domain.contracts.common import (
    Contract,
    Nonnegative,
    Positive,
    Text,
    UtcTime,
    violation,
)
from mule_detection.domain.errors import DomainError, ErrorCode


class TransactionEvent(Contract):
    VERSION = "event_v1"
    contract_version: Literal["event_v1"]
    schema_version: Literal["transaction_minor_units_v1"]
    source_id: Text
    source_partition: Text
    sequence_epoch: Text
    source_sequence: Positive
    event_id: Text
    account_id: Text
    event_time: UtcTime
    ingested_at: UtcTime
    event_type: Literal["TRANSACTION", "CORRECTION", "REVERSAL"]
    amount_minor: Nonnegative
    currency: str
    direction: Literal["IN", "OUT"]
    correction_of: Text | None
    reversal_of: Text | None

    @model_validator(mode="after")
    def money_and_links(self) -> Self:
        import re

        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise violation(ErrorCode.CONTRACT_INVALID)
        expected = {
            "TRANSACTION": (False, False),
            "CORRECTION": (True, False),
            "REVERSAL": (False, True),
        }
        if (self.correction_of is not None, self.reversal_of is not None) != expected[
            self.event_type
        ] or self.event_id in (self.correction_of, self.reversal_of):
            raise violation(ErrorCode.EVENT_SEQUENCE_INVALID)
        return self


class CompletenessManifest(Contract):
    VERSION = "completeness_v1"
    contract_version: Literal["completeness_v1"]
    source_id: Text
    source_partition: Text
    sequence_epoch: Text
    first_sequence: Positive
    contiguous_committed_sequence: Nonnegative
    count_scope: Literal["epoch_prefix"]
    expected_count: Nonnegative
    complete_through: UtcTime
    heartbeat_at: UtcTime
    producer_approval_reference: Text

    @model_validator(mode="after")
    def consistent_counts(self) -> Self:
        if (
            self.first_sequence != 1
            or self.expected_count != self.contiguous_committed_sequence
            or self.complete_through > self.heartbeat_at
        ):
            raise violation(ErrorCode.COMPLETENESS_INVALID)
        return self


def validate_event_progress(
    event: TransactionEvent,
    *,
    previous: TransactionEvent | None,
    approved_epoch: str,
    max_clock_skew_seconds: int,
) -> None:
    """Check newly declared producer progress, not delayed/replayed arrival order.

    Phase 11 routes old/duplicate/out-of-order envelopes to deduplication and buffering.
    Only a trusted source epoch decision can authorize a producer restart.
    """
    if (
        max_clock_skew_seconds < 0
        or (event.event_time - event.ingested_at).total_seconds() > max_clock_skew_seconds
    ):
        raise DomainError(ErrorCode.EVENT_CLOCK_SKEW)
    if event.sequence_epoch != approved_epoch:
        raise DomainError(ErrorCode.EVENT_SEQUENCE_INVALID)
    if previous and (event.source_id, event.source_partition) != (
        previous.source_id,
        previous.source_partition,
    ):
        raise DomainError(ErrorCode.EVENT_SEQUENCE_INVALID)
    if (
        previous
        and event.sequence_epoch == previous.sequence_epoch
        and event.source_sequence <= previous.source_sequence
    ):
        raise DomainError(ErrorCode.EVENT_SEQUENCE_INVALID)
    if previous and event.sequence_epoch != previous.sequence_epoch and event.source_sequence != 1:
        raise DomainError(ErrorCode.EVENT_SEQUENCE_INVALID)


def validate_completeness(
    manifest: CompletenessManifest, events: tuple[TransactionEvent, ...]
) -> None:
    if any(
        (e.source_id, e.source_partition, e.sequence_epoch)
        != (manifest.source_id, manifest.source_partition, manifest.sequence_epoch)
        for e in events
    ):
        raise DomainError(ErrorCode.COMPLETENESS_INVALID)
    sequences = sorted(e.source_sequence for e in events)
    if len(sequences) != manifest.expected_count or any(
        value != index + 1 for index, value in enumerate(sequences)
    ):
        raise DomainError(ErrorCode.COMPLETENESS_INVALID)
