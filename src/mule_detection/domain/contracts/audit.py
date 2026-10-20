from typing import Literal
from uuid import UUID

from mule_detection.domain.contracts.common import Contract, Digest, Text, UtcTime


class AuditEvent(Contract):
    VERSION = "audit_v1"
    contract_version: Literal["audit_v1"]
    audit_id: UUID
    occurred_at: UtcTime
    actor_id: Text
    correlation_id: UUID
    action: Text
    entity_reference: Text
    request_hash: Digest
    reason_reference: Text | None
    previous_event_id: UUID | None
