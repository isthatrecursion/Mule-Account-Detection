"""One application path for durable CSV intake, quarantine, replay and revalidation."""

import io
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, BinaryIO, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from mule_detection.application.audit_service import AuditService
from mule_detection.application.context import ExecutionContext
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.application.validation_service import ValidationService
from mule_detection.domain.contracts.common import parse_contract
from mule_detection.domain.errors import DomainError
from mule_detection.domain.feature_policy import FeaturePolicy
from mule_detection.domain.validation_policy import IntakeRejected, ValidationResult, error
from mule_detection.ingestion.intake import SourceProfile, check_format, safe_filename
from mule_detection.ingestion.partition_guard import development_batch
from mule_detection.ingestion.quality_report import quality_report
from mule_detection.ingestion.research_adapter import ResearchAdapter
from mule_detection.ingestion.validator import CheckedBatch, DeclaredBatch, validate
from mule_detection.persistence.errors import AccessDenied, PersistenceConflict
from mule_detection.persistence.models import IntakeContent, IntakeRequest
from mule_detection.persistence.raw_store import RawStore, StagedRaw
from mule_detection.persistence.repositories import Repositories, fingerprint


class IngestService:
    def __init__(
        self,
        factory: Callable[[], Session],
        store: RawStore,
        profiles: Mapping[str, SourceProfile],
        policy: FeaturePolicy,
        *,
        authorize: Callable[[ExecutionContext, str, str], bool],
        max_rows: int = 100000,
        research_adapter: ResearchAdapter | None = None,
        trusted_split: Path | None = None,
    ) -> None:
        self.factory = factory
        self.store = store
        self.profiles = dict(profiles)
        self.policy = policy
        self.authorize = authorize
        self.max_rows = max_rows
        self.research_adapter = research_adapter
        self.trusted_split = trusted_split
        self.validation = ValidationService(factory, store)

    def _get(self, identity: UUID) -> ValidationResult:
        with unit_of_work(self.factory) as session:
            record = session.get(IntakeRequest, identity)
            assert record is not None
            if record.result:
                result = ValidationResult.model_validate(record.result)
                if result.intake_id != identity and result.outcome in {"RECEIVED", "VALIDATING"}:
                    return self._get(result.intake_id)
                return result
            return ValidationResult(
                intake_id=identity,
                batch_id=record.batch_id,
                outcome=cast(
                    Literal["RECEIVED", "VALIDATING", "ACCEPTED", "QUARANTINED", "FAILED"],
                    record.state,
                ),
                row_count=0,
                finding_codes=(),
                finding_counts={},
                report_reference=None,
            )

    def status(self, identity: UUID, context: ExecutionContext) -> ValidationResult:
        with unit_of_work(self.factory) as session:
            record = session.get(IntakeRequest, identity)
            if record is None or record.actor_id != context.actor_id:
                raise AccessDenied()
            manifest = record.declaration.get("manifest")
            if isinstance(manifest, dict):
                profile = self.profiles.get(str(manifest.get("source_id")))
                if profile and not self.authorize(context, profile.access_scope, "ingest"):
                    raise AccessDenied()
        return self._get(identity)

    def ingest(
        self,
        stream: BinaryIO,
        declaration: object,
        context: ExecutionContext,
        *,
        idempotency_key: UUID,
        filename: str = "upload.csv",
        file_format: str = "csv",
        replay_of: UUID | None = None,
    ) -> ValidationResult:
        if not context.actor_id or context.environment not in {"local", "test", "research"}:
            # Qualified ingestion needs a separately integrated source certification authority.
            raise AccessDenied()
        # Size-limit untrusted metadata before saving it. Invalid metadata still gets a receipt.
        request_hash = fingerprint(
            {
                "declaration": declaration,
                "format": file_format,
                "replay_of": str(replay_of) if replay_of else None,
            }
        )
        operation = f"intake:{context.environment}"
        with unit_of_work(self.factory) as session:
            identity = uuid4()
            stored_parent = (
                replay_of if replay_of and session.get(IntakeRequest, replay_of) else None
            )
            stored = declaration if isinstance(declaration, dict) else {"invalid_metadata": True}
            if len(str(stored)) > 262144:
                stored = {"invalid_metadata": True}
            session.execute(
                insert(IntakeRequest)
                .values(
                    id=identity,
                    actor_id=context.actor_id,
                    operation_scope=operation,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    correlation_id=context.correlation_id,
                    original_filename=safe_filename(filename),
                    declaration=stored,
                    state="RECEIVED",
                    observed={},
                    replay_of=stored_parent,
                )
                .on_conflict_do_nothing(constraint="uq_intake_request")
            )
            record = session.scalars(
                select(IntakeRequest).where(
                    IntakeRequest.actor_id == context.actor_id,
                    IntakeRequest.operation_scope == operation,
                    IntakeRequest.idempotency_key == idempotency_key,
                )
            ).one()
            if record.request_hash != request_hash:
                raise PersistenceConflict()
            new = record.id == identity
            identity = record.id
            if new:
                AuditService().append(
                    session,
                    context,
                    action="intake:receive",
                    entity_reference=f"intake:{identity}",
                    request_hash=request_hash,
                    idempotency_key=identity,
                )
        if not new:
            # The idempotency key binds the declared hash, but retries must still prove actual bytes.
            staged_retry = self.store.stage(stream)
            try:
                with unit_of_work(self.factory) as session:
                    retry_record = session.get(IntakeRequest, identity)
                    assert retry_record is not None
                    expected = retry_record.declaration.get("manifest")
                    observed_hash = retry_record.observed.get("checksum") or (
                        expected.get("checksum") if isinstance(expected, dict) else None
                    )
                    if observed_hash is not None and observed_hash != staged_retry.digest:
                        raise PersistenceConflict()
                return self.status(identity, context)
            finally:
                self.store.discard_stage(staged_retry.stage_id)
        staged: StagedRaw | None = None
        declared: DeclaredBatch | None = None
        profile: SourceProfile | None = None
        checked = CheckedBatch([])
        raw_uri: str | None = None
        try:
            check_format(file_format)
            declared = parse_contract(DeclaredBatch, declaration)
            profile = self.profiles.get(declared.manifest.source_id)
            if profile is None:
                raise IntakeRejected("SOURCE_NOT_REGISTERED")
            if not self.authorize(context, profile.access_scope, "ingest"):
                raise IntakeRejected("SOURCE_ACCESS_DENIED")
            if replay_of and not self.authorize(context, profile.access_scope, "replay"):
                raise IntakeRejected("REPLAY_ACCESS_DENIED")
            with unit_of_work(self.factory) as session:
                session.execute(
                    update(IntakeRequest)
                    .where(IntakeRequest.id == identity)
                    .values(state="VALIDATING")
                )
            staged = self.store.stage(stream, stage_id=identity)
            with unit_of_work(self.factory) as session:
                session.execute(
                    update(IntakeRequest)
                    .where(IntakeRequest.id == identity)
                    .values(observed={"checksum": staged.digest, "byte_count": staged.byte_count})
                )
            if staged.digest == declared.manifest.checksum:
                original = self._claim(
                    identity, staged.digest, declared, profile, replay_of, context
                )
                if original != identity and replay_of is None:
                    self.store.discard_stage(staged.stage_id)
                    result = self._get(original)
                    with unit_of_work(self.factory) as session:
                        session.execute(
                            update(IntakeRequest)
                            .where(IntakeRequest.id == identity)
                            .values(state=result.outcome, result=result.model_dump(mode="json"))
                        )
                        AuditService().append(
                            session,
                            context,
                            action="intake:deduplicate",
                            entity_reference=f"intake:{identity}",
                            request_hash=request_hash,
                            after_reference=f"intake:{original}",
                            idempotency_key=identity,
                        )
                    return result
            checked = validate(
                self.store.staging_path(staged.stage_id),
                declared,
                profile,
                self.policy,
                digest=staged.digest,
                byte_count=staged.byte_count,
                max_rows=self.max_rows,
                research_adapter=self.research_adapter,
                split_path=self.trusted_split,
            )
            raw_uri = self.validation.publish_staged(identity, staged, "RAW")
        except DomainError as exc:
            checked.findings.append(error(exc.code.value))
        except IntakeRejected as exc:
            checked.findings.append(error(exc.code))
        except PersistenceConflict:
            checked.findings.append(error("INTAKE_METADATA_CONFLICT"))
        except Exception:
            # Leave a failed, inspectable request; never mark a partial publication accepted.
            self._mark_failed(identity, context)
            raise
        rules_hash = fingerprint(
            {
                "version": "intake_rules_v1",
                "profile": profile.model_dump(mode="json") if profile else None,
                "policy": self.policy.fingerprint,
            }
        )
        report: dict[str, object] = {
            "version": "validation_v1",
            "declared": declaration,
            "observed_checksum": staged.digest if staged else None,
            "observed_bytes": staged.byte_count if staged else 0,
            "observed_rows": checked.row_count,
            "observed_schema": checked.signature,
            "type_errors_by_field": checked.type_errors,
            "rules_hash": rules_hash,
            "policy_hash": self.policy.fingerprint,
            "findings": [f.model_dump(mode="json") for f in checked.findings],
            "quality": quality_report(checked, profile) if profile and checked.accepted else None,
            "qualified_promotion_allowed": False,
        }
        values = None
        if raw_uri and declared and staged:
            values = {
                "digest": staged.digest,
                "raw_uri": raw_uri,
                "schema_id": declared.manifest.schema_id,
                "data_tier": declared.manifest.data_tier,
                "row_count": checked.row_count,
                "batch_id": str(declared.manifest.batch_id),
                "manifest_hash": fingerprint(declared.model_dump(mode="json")),
            }
        try:
            return self.validation.finish(
                identity, context, report, batch_values=values, rules_hash=rules_hash
            )
        except Exception:
            self._mark_failed(identity, context)
            raise

    def _mark_failed(self, identity: UUID, context: ExecutionContext) -> None:
        with unit_of_work(self.factory) as session:
            intake = session.scalars(
                select(IntakeRequest).where(IntakeRequest.id == identity).with_for_update()
            ).one()
            if intake.state in {"RECEIVED", "VALIDATING"}:
                intake.state = "FAILED"
                intake.result = ValidationResult(
                    intake_id=identity,
                    batch_id=None,
                    outcome="FAILED",
                    row_count=0,
                    finding_codes=("INTAKE_SYSTEM_FAILURE",),
                    finding_counts={"INTAKE_SYSTEM_FAILURE": 1},
                    report_reference=None,
                ).model_dump(mode="json")
                AuditService().append(
                    session,
                    context,
                    action="intake:fail",
                    entity_reference=f"intake:{identity}",
                    request_hash=intake.request_hash,
                    reason_reference="error:INTAKE_SYSTEM_FAILURE",
                    idempotency_key=identity,
                )

    def _claim(
        self,
        identity: UUID,
        digest: str,
        declared: DeclaredBatch,
        profile: SourceProfile,
        replay_of: UUID | None,
        context: ExecutionContext,
    ) -> UUID:
        metadata = declared.model_dump(mode="json")
        # Only the new upload identity is incidental. Producer time/job remain provenance.
        metadata["manifest"].pop("batch_id")
        metadata_hash = fingerprint(metadata)
        with unit_of_work(self.factory) as session:
            # Serialize claims for the same bytes across source scopes as well as within one.
            # The lock is transaction-scoped and released before parsing long-running input.
            lock_key = int(digest[:16], 16)
            if lock_key >= 2**63:
                lock_key -= 2**64
            session.execute(select(func.pg_advisory_xact_lock(lock_key)))
            other_scope = session.scalar(
                select(IntakeContent).where(IntakeContent.digest == digest)
            )
            if other_scope and other_scope.access_scope != profile.access_scope:
                raise IntakeRejected("INTAKE_METADATA_CONFLICT")
            session.execute(
                insert(IntakeContent)
                .values(
                    digest=digest,
                    access_scope=profile.access_scope,
                    metadata_hash=metadata_hash,
                    original_intake_id=identity,
                )
                .on_conflict_do_nothing(constraint="uq_intake_content")
            )
            claim = session.scalars(
                select(IntakeContent).where(
                    IntakeContent.digest == digest,
                    IntakeContent.access_scope == profile.access_scope,
                )
            ).one()
            if claim.metadata_hash != metadata_hash:
                raise IntakeRejected("INTAKE_METADATA_CONFLICT")
            if replay_of:
                parent = session.get(IntakeRequest, replay_of)
                current = session.get(IntakeRequest, identity)
                assert current is not None
                if parent is None or parent.actor_id != current.actor_id:
                    raise IntakeRejected("REPLAY_PARENT_INVALID")
                if (
                    parent.observed.get("checksum") != digest
                    or parent.batch_id == declared.manifest.batch_id
                ):
                    raise IntakeRejected("REPLAY_PARENT_INVALID")
                AuditService().append(
                    session,
                    context,
                    action="intake:replay",
                    entity_reference=f"intake:{identity}",
                    request_hash=metadata_hash,
                    before_reference=f"intake:{replay_of}",
                    idempotency_key=identity,
                )
                return identity
            return claim.original_intake_id

    def revalidate(self, batch_id: UUID, context: ExecutionContext) -> UUID:
        with unit_of_work(self.factory) as session:
            intake = session.scalars(
                select(IntakeRequest).where(IntakeRequest.batch_id == batch_id)
            ).first()
            if intake is None:
                raise PersistenceConflict()
            declared = parse_contract(DeclaredBatch, intake.declaration)
            profile = self.profiles[declared.manifest.source_id]
            if not self.authorize(context, profile.access_scope, "revalidate"):
                raise AccessDenied()
        payload = self.store.read(declared.manifest.checksum)
        staged = self.store.stage(io.BytesIO(payload))
        try:
            checked = validate(
                self.store.staging_path(staged.stage_id),
                declared,
                profile,
                self.policy,
                digest=staged.digest,
                byte_count=staged.byte_count,
                max_rows=self.max_rows,
                research_adapter=self.research_adapter,
                split_path=self.trusted_split,
            )
            rules_hash = fingerprint(
                {
                    "version": "intake_rules_v1",
                    "profile": profile.model_dump(mode="json"),
                    "policy": self.policy.fingerprint,
                }
            )
            report: dict[str, object] = {
                "version": "validation_v1",
                "rules_hash": rules_hash,
                "policy_hash": self.policy.fingerprint,
                "observed_rows": checked.row_count,
                "findings": [f.model_dump(mode="json") for f in checked.findings],
                "quality": quality_report(checked, profile) if checked.accepted else None,
                "qualified_promotion_allowed": False,
            }
            return self.validation.revalidate(
                batch_id, context, report=report, rules_hash=rules_hash, accepted=checked.accepted
            )
        finally:
            self.store.discard_stage(staged.stage_id)

    def research_scoring_input(
        self, batch_id: UUID, keys: tuple[str, ...], context: ExecutionContext
    ) -> dict[str, dict[str, Any]]:
        """Future workers must call this boundary; emits predictors only for guarded keys."""
        with unit_of_work(self.factory) as session:
            Repositories(session).get_accepted_batch(batch_id)
            intake = session.scalars(
                select(IntakeRequest).where(IntakeRequest.batch_id == batch_id)
            ).first()
            if intake is None:
                raise PersistenceConflict()
            declared = parse_contract(DeclaredBatch, intake.declaration)
            profile = self.profiles[declared.manifest.source_id]
            if profile.data_tier != "research" or not self.authorize(
                context, profile.access_scope, "score"
            ):
                raise AccessDenied()
        if self.research_adapter is None or self.trusted_split is None:
            raise IntakeRejected("TRUSTED_SPLIT_REQUIRED")
        staged = self.store.stage(io.BytesIO(self.store.read(declared.manifest.checksum)))
        try:
            research, guard = development_batch(
                self.research_adapter, self.store.staging_path(staged.stage_id), self.trusted_split
            )
            guard.assert_development(keys, staged.digest, research.split_sha256)
            return {
                key: {
                    name: values[i].item() if hasattr(values[i], "item") else values[i]
                    for name, values in research.predictors.items()
                }
                for i, key in enumerate(research.record_keys)
                if key in set(keys)
            }
        finally:
            self.store.discard_stage(staged.stage_id)

    def training_quality(self, batch_id: UUID, context: ExecutionContext) -> str:
        """Restricted diagnostics are separately authorized and stored, never in analyst DTOs."""
        with unit_of_work(self.factory) as session:
            Repositories(session).get_accepted_batch(batch_id)
            intake = session.scalars(
                select(IntakeRequest).where(IntakeRequest.batch_id == batch_id)
            ).first()
            if intake is None:
                raise PersistenceConflict()
            declared = parse_contract(DeclaredBatch, intake.declaration)
            profile = self.profiles[declared.manifest.source_id]
            if profile.data_tier != "research" or not self.authorize(
                context, profile.access_scope, "training-diagnostics"
            ):
                raise AccessDenied()
            intake_id = intake.id
        staged = self.store.stage(io.BytesIO(self.store.read(declared.manifest.checksum)))
        try:
            checked = validate(
                self.store.staging_path(staged.stage_id),
                declared,
                profile,
                self.policy,
                digest=staged.digest,
                byte_count=staged.byte_count,
                max_rows=self.max_rows,
                research_adapter=self.research_adapter,
                split_path=self.trusted_split,
            )
            if not checked.accepted:
                raise IntakeRejected("CURRENT_VALIDATION_REQUIRED")
            report = {
                "version": "restricted_training_quality_v1",
                "data_hash": staged.digest,
                "schema_hash": profile.signature,
                "policy_hash": self.policy.fingerprint,
                "quality": quality_report(checked, profile, training_diagnostics=True),
            }
            uri = self.validation.publish(intake_id, json.dumps(report, sort_keys=True).encode())
            with unit_of_work(self.factory) as session:
                AuditService().append(
                    session,
                    context,
                    action="intake:diagnostics",
                    entity_reference=f"batch:{batch_id}",
                    request_hash=fingerprint(report),
                    after_reference=uri,
                )
            return uri
        finally:
            self.store.discard_stage(staged.stage_id)
