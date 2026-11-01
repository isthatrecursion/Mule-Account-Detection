"""Publication-backed validation and atomic batch status/audit updates."""

import io
import json
from collections import Counter
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from mule_detection.application.audit_service import AuditService
from mule_detection.application.context import ExecutionContext
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.domain.validation_policy import ValidationResult
from mule_detection.persistence.models import Batch, IntakeRequest, RawPublication, ValidationReport
from mule_detection.persistence.raw_store import RawStore, StagedRaw
from mule_detection.persistence.repositories import Repositories, fingerprint


class ValidationService:
    def __init__(self, factory: Callable[[], Session], store: RawStore) -> None:
        self.factory = factory
        self.store = store

    def publish(self, intake_id: UUID, payload: bytes, kind: str = "REPORT") -> str:
        staged = self.store.stage(io.BytesIO(payload))
        return self.publish_staged(intake_id, staged, kind)

    def publish_staged(self, intake_id: UUID, staged: StagedRaw, kind: str) -> str:
        with unit_of_work(self.factory) as session:
            session.add(
                RawPublication(
                    id=staged.stage_id,
                    intake_id=intake_id,
                    kind=kind,
                    digest=staged.digest,
                    byte_count=staged.byte_count,
                )
            )
        # The database knows about the object before filesystem publication can occur.
        uri = self.store.finalize(staged)
        with unit_of_work(self.factory) as session:
            publication = session.get(RawPublication, staged.stage_id)
            assert publication is not None
            publication.state = "PUBLISHED"
        self.store.discard_stage(staged.stage_id)
        return uri

    def finish(
        self,
        intake_id: UUID,
        context: ExecutionContext,
        report: dict[str, object],
        *,
        batch_values: dict[str, object] | None,
        rules_hash: str,
    ) -> ValidationResult:
        uri = self.publish(intake_id, json.dumps(report, sort_keys=True, allow_nan=False).encode())
        findings = report["findings"]
        assert isinstance(findings, list)
        counts: Counter[str] = Counter()
        for finding in findings:
            counts[str(finding["rule_id"])] += int(finding["count"])
        accepted = not any(f["severity"] == "ERROR" for f in findings)
        with unit_of_work(self.factory) as session:
            intake = session.scalars(
                select(IntakeRequest).where(IntakeRequest.id == intake_id).with_for_update()
            ).one()
            if intake.result:
                return ValidationResult.model_validate(intake.result)
            if intake.state not in {"RECEIVED", "VALIDATING"}:
                raise ValueError("Interrupted intake requires an explicit replay")
            batch_id = None
            if batch_values:
                raw_digest = str(batch_values["digest"])
                if (
                    session.scalar(
                        select(RawPublication.id).where(
                            RawPublication.intake_id == intake_id,
                            RawPublication.kind == "RAW",
                            RawPublication.digest == raw_digest,
                            RawPublication.state == "PUBLISHED",
                        )
                    )
                    is None
                ):
                    raise ValueError("Batch acceptance requires published raw data")
                repository = Repositories(session)
                dataset = repository.register_dataset(
                    content_hash=str(batch_values["digest"]),
                    raw_uri=str(batch_values["raw_uri"]),
                    schema_id=str(batch_values["schema_id"]),
                    data_tier=str(batch_values["data_tier"]),
                    row_count=int(str(batch_values["row_count"])),
                )
                batch_id = UUID(str(batch_values["batch_id"]))
                batch = repository.register_batch(
                    batch_id=batch_id,
                    dataset_id=dataset.id,
                    manifest_hash=str(batch_values["manifest_hash"]),
                )
                validation = ValidationReport(
                    published=True,
                    batch_id=batch_id,
                    rules_hash=rules_hash,
                    findings_uri=uri,
                    outcome="ACCEPTED" if accepted else "REJECTED",
                )
                session.add(validation)
                session.flush()
                batch.status = "ACCEPTED" if accepted else "QUARANTINED"
                batch.accepted_validation_id = validation.id if accepted else None
            result = ValidationResult(
                intake_id=intake_id,
                batch_id=batch_id,
                outcome="ACCEPTED" if accepted else "QUARANTINED",
                row_count=int(str(report["observed_rows"])),
                finding_codes=tuple(counts),
                finding_counts=counts,
                report_reference=uri,
                qualified_promotion_allowed=False,
            )
            intake.state = result.outcome
            intake.batch_id = batch_id
            intake.result = result.model_dump(mode="json")
            AuditService().append(
                session,
                context,
                action="intake:finalize",
                entity_reference=f"intake:{intake_id}",
                request_hash=fingerprint(report),
                after_reference=uri,
                idempotency_key=intake_id,
            )
            return result

    def revalidate(
        self,
        batch_id: UUID,
        context: ExecutionContext,
        *,
        report: dict[str, object],
        rules_hash: str,
        accepted: bool,
    ) -> UUID:
        """Internal-only: caller is the ingest service after validating stored bytes again."""
        with unit_of_work(self.factory) as session:
            batch = session.scalars(
                select(Batch).where(Batch.id == batch_id).with_for_update()
            ).one()
            previous = session.scalar(
                select(ValidationReport).where(
                    ValidationReport.batch_id == batch_id, ValidationReport.rules_hash == rules_hash
                )
            )
            if previous:
                return previous.id
            intake = session.scalars(
                select(IntakeRequest).where(IntakeRequest.batch_id == batch_id)
            ).first()
            assert intake is not None
            intake_id = intake.id
        uri = self.publish(intake_id, json.dumps(report, sort_keys=True, allow_nan=False).encode())
        with unit_of_work(self.factory) as session:
            batch = session.scalars(
                select(Batch).where(Batch.id == batch_id).with_for_update()
            ).one()
            previous = session.scalar(
                select(ValidationReport).where(
                    ValidationReport.batch_id == batch_id, ValidationReport.rules_hash == rules_hash
                )
            )
            if previous:
                return previous.id
            version = ValidationReport(
                published=True,
                batch_id=batch_id,
                rules_hash=rules_hash,
                findings_uri=uri,
                outcome="ACCEPTED" if accepted else "REJECTED",
            )
            session.add(version)
            session.flush()
            before = batch.accepted_validation_id
            batch.status = "ACCEPTED" if accepted else "QUARANTINED"
            batch.accepted_validation_id = version.id if accepted else None
            AuditService().append(
                session,
                context,
                action="batch:revalidate",
                entity_reference=f"batch:{batch_id}",
                request_hash=rules_hash,
                before_reference=str(before) if before else None,
                after_reference=uri,
            )
            return version.id
