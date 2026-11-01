"""Synthetic PostgreSQL control-plane, registration recovery and rollback checks."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from mule_detection.application.bundle_service import BundleService
from mule_detection.application.context import ExecutionContext
from mule_detection.application.model_approval_service import ModelApprovalService
from mule_detection.application.registry_service import RegistryService
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.domain.errors import DomainError
from mule_detection.persistence.errors import AccessDenied, PersistenceConflict
from mule_detection.persistence.job_repository import JobRepository
from mule_detection.persistence.models import AuditEvent, ModelDecision, RegistryCandidate
from mule_detection.persistence.sqlalchemy import make_engine, session_factory
from mule_detection.registry.bundle_loader import BundleLoader
from mule_detection.registry.bundle_writer import BundleStore, write_bundle
from mule_detection.registry.model_resolver import ModelResolver
from tests.integration.test_training import CONTEXT as TRAINER
from tests.integration.test_training import training as training
from tests.unit.test_registry import final_fit as final_fit
from tests.unit.test_training import training_data as training_data

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[2]
ENGINEER = ExecutionContext.create("engineer", "test")
REVIEWER = ExecutionContext.create("reviewer", "test")


class FakeRegistry:
    def __init__(self):
        self.versions = {}
        self.aliases = {}
        self.creates = 0
        self.lose_reply = False
        self.fail_alias = False

    def lookup(self, name, registration_id):
        return self.versions.get(registration_id)

    def register(self, name, registration_id, digest, directory, metrics, parameters=None):
        self.creates += 1
        value = {
            "version": str(self.creates),
            "run_id": f"run-{self.creates}",
            "bundle_digest": digest,
        }
        self.versions[registration_id] = value
        if self.lose_reply:
            self.lose_reply = False
            raise TimeoutError("Synthetic lost response after remote commit")
        return value

    def set_alias(self, name, alias, version):
        if self.fail_alias:
            raise TimeoutError("Synthetic alias mirror failure")
        self.aliases[(name, alias)] = version


@pytest.fixture
def registry(db, runtime_engine, final_fit, tmp_path):
    data, _, _, fitted, lineage = final_fit
    store = BundleStore(tmp_path / "bundles", b"z" * 32)
    digest = write_bundle(fitted, lineage, data.X.iloc[:3], store, root=ROOT)
    backend = FakeRegistry()
    factory = session_factory(runtime_engine)
    service = RegistryService(
        factory,
        store,
        backend,
        lambda context, action: context.actor_id == "engineer" and action == "model:train",
    )
    candidate = service.create_candidate(digest, "synthetic_registry", ENGINEER)
    approvals = ModelApprovalService(
        db, lambda context, action: context.actor_id == "reviewer" and action == "model:approve"
    )
    resolver = ModelResolver(
        factory,
        backend,
        lambda context, action: (
            context.actor_id == "engineer" and action in {"model:deploy", "model:resolve"}
        ),
    )
    loader = BundleLoader(store, resolver.authorized)
    return service, candidate, approvals, resolver, loader, backend, digest


def approve(approvals, candidate, target="RESEARCH_DEMO"):
    return approvals.decide(
        candidate, "test", target, REVIEWER, reason="SYNTHETIC_TEST_ONLY", idempotency_key=uuid4()
    )


def test_lost_remote_reply_is_reconciled_without_duplicate_model(registry):
    service, candidate, _, _, _, backend, _ = registry
    backend.lose_reply = True
    with pytest.raises(TimeoutError):
        service.synchronize(candidate, ENGINEER)
    with unit_of_work(service.factory) as session:
        assert session.get(RegistryCandidate, candidate).registration_state == "UNCERTAIN"
    result = service.synchronize(candidate, ENGINEER)
    assert result["state"] == "REGISTERED" and backend.creates == 1
    assert service.synchronize(candidate, ENGINEER) == result and backend.creates == 1


def test_accepted_training_packages_once_and_keeps_validation_binding(training, tmp_path):
    trainer, batch_id, config = training
    run_id = uuid4()
    trainer.train(batch_id, run_id, config, TRAINER)
    store = BundleStore(tmp_path / "accepted-bundles", b"z" * 32)
    backend = FakeRegistry()
    registry = RegistryService(trainer.factory, store, backend, lambda *_: True)
    service = BundleService(trainer, registry)
    result = service.build(batch_id, run_id, "accepted_synthetic", TRAINER)
    assert result == service.build(batch_id, run_id, "accepted_synthetic", TRAINER)
    assert backend.creates == 1
    assert len([p for p in store.root.iterdir() if p.is_dir()]) == 1
    with pytest.raises(AccessDenied):
        service.build(batch_id, run_id, "accepted_synthetic", ENGINEER)


def test_runtime_credential_cannot_write_approval_even_with_spoofed_service_permission(registry):
    service, candidate, _, _, _, _, _ = registry
    service.synchronize(candidate, ENGINEER)
    unauthorized = ModelApprovalService(service.factory, lambda *_: True)
    with pytest.raises(DBAPIError):
        approve(unauthorized, candidate)
    with unit_of_work(service.factory) as session:
        assert session.scalar(select(func.count()).select_from(ModelDecision)) == 0


@pytest.mark.skipif(
    os.getenv("MULE_TEST_APPROVER") != "1",
    reason="Explicit local approval-role provisioning opt-in required",
)
def test_separate_provisioned_identity_can_append_decision_and_audit_only(registry):
    service, candidate, _, _, _, _, _ = registry
    service.synchronize(candidate, ENGINEER)
    endpoint = make_url(os.environ["MULE_TEST_DATABASE_URL"])
    assert endpoint.database.startswith("mule_test_")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/provision_model_approver.py",
            "--database",
            endpoint.database,
            "--admin-url-file",
            os.getenv(
                "MULE_TEST_ADMIN_DATABASE_URL_FILE", str(ROOT / "secrets/test_admin_database_url")
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "Separate local test approver provisioning failed"
    password = (ROOT / "secrets/mule_model_approver_password").read_text().strip()
    engine = make_engine(
        endpoint.set(username="mule_model_approver", password=password).render_as_string(
            hide_password=False
        )
    )
    try:
        factory = session_factory(engine)
        approvals = ModelApprovalService(
            factory,
            lambda context, action: context.actor_id == "reviewer" and action == "model:approve",
        )
        decision = approve(approvals, candidate)
        with unit_of_work(factory) as session:
            assert session.get(ModelDecision, decision).state == "RESEARCH_DEMO"
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "model:approve")
                )
                == 1
            )
        from sqlalchemy import text

        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(
                text("UPDATE registry_candidates SET bundle_digest=:digest WHERE id=:id"),
                {"digest": "f" * 64, "id": candidate},
            )
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(text("DELETE FROM model_decisions"))
        approve(approvals, candidate, "RETIRED")
    finally:
        engine.dispose()


def test_alias_changes_do_not_change_pins_and_retirement_blocks_publication(registry):
    service, candidate, approvals, resolver, loader, backend, digest = registry
    service.synchronize(candidate, ENGINEER)
    with pytest.raises(DomainError):
        loader.load(digest, "test")
    approve(approvals, candidate)
    version = resolver.deploy(
        candidate,
        "test",
        "active",
        ENGINEER,
        expected_version=0,
        reason="synthetic deployment",
        loader=loader,
    )
    assert version == 1
    with unit_of_work(service.factory) as session:
        job = JobRepository(session).create(
            actor_id="engineer", operation="score", idempotency_key=uuid4(), request={}
        )
        job_id = job.id
    pinned = resolver.pin(job_id, "test", "active", ENGINEER)
    backend.aliases[("synthetic_registry", "test-active")] = "unapproved-remote-version"
    assert (
        resolver.pin(job_id, "test", "active", ENGINEER).bundle_digest
        == pinned.bundle_digest
        == digest
    )
    resolver.reconcile_alias("test", "active", ENGINEER)
    assert backend.aliases[("synthetic_registry", "test-active")] == "1"
    approve(approvals, candidate, "RETIRED")
    with pytest.raises(DomainError), unit_of_work(service.factory) as session:
        resolver.revalidate(session, job_id)
    with pytest.raises(DomainError):
        loader.load(digest, "test")


def test_research_promotion_and_self_approval_fail(registry):
    service, candidate, approvals, _, _, _, _ = registry
    service.synchronize(candidate, ENGINEER)
    with pytest.raises(AccessDenied):
        approvals.decide(
            candidate, "test", "RESEARCH_DEMO", ENGINEER, reason="denied", idempotency_key=uuid4()
        )
    with pytest.raises(DomainError):
        approvals.decide(
            candidate,
            "qualified",
            "APPROVED_FOR_SHADOW",
            REVIEWER,
            reason="cannot certify research",
            idempotency_key=uuid4(),
        )


def test_alias_mirror_failure_keeps_audited_selection_and_can_be_repaired(registry):
    service, candidate, approvals, resolver, loader, backend, _ = registry
    service.synchronize(candidate, ENGINEER)
    approve(approvals, candidate)
    backend.fail_alias = True
    with pytest.raises(TimeoutError):
        resolver.deploy(
            candidate,
            "test",
            "active",
            ENGINEER,
            expected_version=0,
            reason="synthetic mirror failure",
            loader=loader,
        )
    backend.fail_alias = False
    resolver.reconcile_alias("test", "active", ENGINEER)
    assert backend.aliases[("synthetic_registry", "test-active")] == "1"
    with unit_of_work(service.factory) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "model:alias_reconcile")
            )
            == 1
        )
    with pytest.raises(AccessDenied):
        resolver.deploy(
            candidate,
            "qualified",
            "active",
            ENGINEER,
            expected_version=0,
            reason="training identity cannot deploy qualified",
            loader=loader,
        )


def test_rollback_changes_only_future_selection_with_complete_audit(registry, final_fit, db):
    service, first, approvals, resolver, loader, backend, digest = registry
    service.synchronize(first, ENGINEER)
    approve(approvals, first)
    resolver.deploy(
        first, "test", "active", ENGINEER, expected_version=0, reason="first", loader=loader
    )
    data, _, _, fitted, lineage = final_fit
    second_digest = write_bundle(
        fitted,
        {**lineage, "training_run_id": str(uuid4())},
        data.X.iloc[:3],
        service.store,
        root=ROOT,
    )
    second = service.create_candidate(second_digest, "synthetic_registry", ENGINEER)
    service.synchronize(second, ENGINEER)
    approve(approvals, second)
    with unit_of_work(service.factory) as session:
        job = JobRepository(session).create(
            actor_id="engineer", operation="score", idempotency_key=uuid4(), request={}
        )
        job_id = job.id
    original = resolver.pin(job_id, "test", "active", ENGINEER)
    resolver.deploy(
        second, "test", "active", ENGINEER, expected_version=1, reason="second", loader=loader
    )
    resolver.deploy(
        first,
        "test",
        "active",
        ENGINEER,
        expected_version=2,
        reason="synthetic incident rollback",
        loader=loader,
        rollback=True,
    )
    with pytest.raises(PersistenceConflict):
        resolver.deploy(
            second, "test", "active", ENGINEER, expected_version=1, reason="stale", loader=loader
        )
    assert (
        resolver.pin(job_id, "test", "active", ENGINEER).candidate_id
        == original.candidate_id
        == first
    )
    with unit_of_work(db) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "model:rollback")
            )
            == 1
        )
