"""Registry reconciliation, independent decisions and pinned deployment identities."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def identity():
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
    ]


def upgrade():
    op.create_table(
        "registry_candidates",
        *identity(),
        sa.Column("bundle_digest", sa.String(64), nullable=False),
        sa.Column("training_run_id", sa.Uuid(), nullable=False),
        sa.Column("trainer_id", sa.String(), nullable=False),
        sa.Column("data_tier", sa.String(), nullable=False),
        sa.Column("registry_name", sa.String(), nullable=False),
        sa.Column("registration_state", sa.String(), nullable=False),
        sa.Column("remote_run_id", sa.String(), nullable=True),
        sa.Column("remote_version", sa.String(), nullable=True),
        sa.Column("model_ref_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_payload", postgresql.JSONB(), nullable=False),
        sa.Column("retired", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_registry_candidates"),
        sa.UniqueConstraint("bundle_digest", name="uq_registry_candidates_bundle_digest"),
        sa.UniqueConstraint("model_ref_id", name="uq_registry_candidates_model_ref_id"),
        sa.ForeignKeyConstraint(
            ["model_ref_id"],
            ["model_refs.id"],
            name="fk_registry_candidates_model_ref_id_model_refs",
        ),
        sa.CheckConstraint(
            "registration_state IN ('PENDING','IN_FLIGHT','UNCERTAIN','REGISTERED')",
            name="ck_registry_candidates_registration_state",
        ),
    )
    op.create_table(
        "model_decisions",
        *identity(),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("reason_reference", sa.String(), nullable=False),
        sa.Column("evidence_payload", postgresql.JSONB(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_model_decisions"),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["registry_candidates.id"],
            name="fk_model_decisions_candidate_id_registry_candidates",
        ),
        sa.UniqueConstraint(
            "candidate_id", "environment", "version", name="uq_model_decisions_candidate_id"
        ),
        sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_model_decisions_actor_id"),
        sa.CheckConstraint(
            "state IN ('RESEARCH_DEMO','APPROVED_FOR_SHADOW','APPROVED_FOR_PILOT','REJECTED','RETIRED')",
            name="ck_model_decisions_state",
        ),
    )
    op.create_table(
        "model_deployments",
        *identity(),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("alias", sa.String(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_model_deployments"),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["registry_candidates.id"],
            name="fk_model_deployments_candidate_id_registry_candidates",
        ),
        sa.UniqueConstraint("environment", "alias", name="uq_model_deployments_environment"),
        sa.CheckConstraint("version > 0", name="ck_model_deployments_version"),
    )
    op.create_table(
        "model_pins",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("bundle_digest", sa.String(64), nullable=False),
        sa.Column("registry_version", sa.String(), nullable=False),
        sa.Column("deployment_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("job_id", name="pk_model_pins"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_model_pins_job_id_jobs"),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["registry_candidates.id"],
            name="fk_model_pins_candidate_id_registry_candidates",
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["model_decisions.id"],
            name="fk_model_pins_decision_id_model_decisions",
        ),
    )
    op.execute(
        "REVOKE ALL ON registry_candidates, model_decisions, model_deployments, model_pins FROM PUBLIC, mule_runtime, mule_readonly"
    )
    op.execute(
        "GRANT SELECT ON registry_candidates, model_decisions, model_deployments, model_pins TO mule_runtime, mule_readonly"
    )
    op.execute("GRANT INSERT ON registry_candidates, model_deployments, model_pins TO mule_runtime")
    op.execute(
        "GRANT UPDATE (registration_state, remote_run_id, remote_version, model_ref_id) ON registry_candidates TO mule_runtime"
    )
    op.execute("GRANT UPDATE (candidate_id, version) ON model_deployments TO mule_runtime")
    # Approval INSERT and retirement UPDATE are deliberately absent from runtime.
    # A separately provisioned control-plane identity must receive those grants.


def downgrade():
    raise RuntimeError("Use a reviewed forward migration; registry history is immutable")
