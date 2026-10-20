from sqlalchemy.orm import Session

from mule_detection.persistence.models import AuditEvent, Outbox


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(self, event: AuditEvent) -> None:
        self.session.add(event)
        self.session.flush()
        self.session.add(Outbox(audit_id=event.id, payload_reference=f"audit:{event.id}"))
        self.session.flush()
