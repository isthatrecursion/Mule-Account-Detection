"""Scoped API jobs, immutable queue/case links, notes and adjudicated outcomes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def identity():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
    ]


def ref(name, target, **kwargs):
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(target), **kwargs)


def upgrade():
    op.create_table(
        "api_identities",
        sa.Column("actor_id", sa.String(), primary_key=True),
        sa.Column("grants", JSONB(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "api_tasks",
        ref("job_id", "jobs.id", primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("access_scope", sa.String(), nullable=False),
        sa.Column("request", JSONB(), nullable=False),
        sa.Column("authorization", JSONB(), nullable=False),
        sa.Column("result", JSONB()),
        sa.CheckConstraint("kind IN ('intake','score','train','export')", name="kind"),
    )
    op.create_table(
        "batch_access",
        ref("batch_id", "batches.id", primary_key=True),
        sa.Column("access_scope", sa.String(), nullable=False),
    )
    op.create_table(
        "queue_cases",
        ref("queue_id", "queue_snapshots.id", primary_key=True),
        sa.Column("record_key", sa.String(), primary_key=True),
        ref("case_id", "cases.id", nullable=False, unique=True),
        sa.ForeignKeyConstraint(
            ["queue_id", "record_key"], ["queue_members.queue_id", "queue_members.record_key"]
        ),
    )
    op.create_table(
        "case_notes",
        *identity(),
        ref("review_id", "review_events.id", nullable=False, unique=True),
        ref("case_id", "cases.id", nullable=False),
        ref("score_id", "score_rows.id", nullable=False),
        ref("artifact_id", "artifacts.id", nullable=False),
    )
    op.create_table(
        "outcome_submissions",
        *identity(),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("known_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance", JSONB(), nullable=False),
        sa.UniqueConstraint("actor_id", "idempotency_key"),
    )
    op.create_table(
        "outcome_contracts",
        ref("label_id", "labels.id", primary_key=True),
        ref("submission_id", "outcome_submissions.id", nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
    )
    op.create_table(
        "export_records",
        ref("job_id", "jobs.id", primary_key=True),
        ref("queue_id", "queue_snapshots.id", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        ref("artifact_id", "artifacts.id"),
        sa.Column("snapshot", JSONB(), nullable=False),
    )
    tables = (
        "api_identities, api_tasks, batch_access, queue_cases, case_notes, "
        "outcome_submissions, outcome_contracts, export_records"
    )
    op.execute(f"REVOKE ALL ON {tables} FROM PUBLIC, mule_runtime, mule_readonly")
    op.execute(f"GRANT SELECT, INSERT ON {tables} TO mule_runtime")
    op.execute(f"GRANT SELECT ON {tables} TO mule_readonly")
    op.execute("GRANT UPDATE (grants, valid_until) ON api_identities TO mule_runtime")
    op.execute('GRANT UPDATE ("authorization", result) ON api_tasks TO mule_runtime')
    op.execute("GRANT UPDATE (artifact_id) ON export_records TO mule_runtime")
    op.execute("GRANT SELECT ON alembic_version TO mule_runtime, mule_readonly")


def downgrade():
    raise RuntimeError("Use a reviewed forward migration; API history is immutable")
