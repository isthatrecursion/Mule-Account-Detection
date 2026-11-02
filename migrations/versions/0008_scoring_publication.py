"""Unpublished scoring attempts/chunks and atomically selected immutable queues."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "scoring_tasks",
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("score_runs.id"), nullable=False, unique=True),
        sa.Column("cohort_id", sa.Uuid(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column(
            "predecessor_queue_id", sa.Uuid(), sa.ForeignKey("queue_snapshots.id"), nullable=True
        ),
        sa.Column("parent_run_id", sa.Uuid(), sa.ForeignKey("score_runs.id"), nullable=True),
        sa.Column("manifest", JSONB(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.CheckConstraint("state IN ('STAGED','COMPLETE')", name="ck_scoring_tasks_state"),
    )
    op.create_table(
        "scoring_chunks",
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("scoring_tasks.job_id"), primary_key=True),
        sa.Column("fencing_token", sa.BigInteger(), primary_key=True),
        sa.Column("chunk_index", sa.Integer(), primary_key=True),
        sa.Column("artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id"), nullable=False),
        sa.Column("membership_hash", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "row_count >= 0 AND chunk_index >= 0 AND fencing_token > 0",
            name="ck_scoring_chunks_counts",
        ),
    )
    op.create_table(
        "scoring_attempts",
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), primary_key=True),
        sa.Column("fencing_token", sa.BigInteger(), primary_key=True),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.CheckConstraint(
            "state IN ('RUNNING','FAILED','SUCCEEDED')", name="ck_scoring_attempts_state"
        ),
    )
    op.create_table(
        "queue_heads",
        sa.Column("cohort_id", sa.Uuid(), primary_key=True),
        sa.Column("environment", sa.String(), primary_key=True),
        sa.Column("queue_id", sa.Uuid(), sa.ForeignKey("queue_snapshots.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_queue_heads_version"),
    )
    tables = "scoring_tasks, scoring_chunks, scoring_attempts, queue_heads"
    op.execute(f"REVOKE ALL ON {tables} FROM PUBLIC, mule_runtime, mule_readonly")
    op.execute(f"GRANT SELECT, INSERT ON {tables} TO mule_runtime")
    op.execute(f"GRANT SELECT ON {tables} TO mule_readonly")
    op.execute("GRANT UPDATE (state) ON scoring_tasks TO mule_runtime")
    op.execute("GRANT UPDATE (state, error_code) ON scoring_attempts TO mule_runtime")
    op.execute("GRANT UPDATE (queue_id, version) ON queue_heads TO mule_runtime")


def downgrade():
    raise RuntimeError("Use a reviewed forward migration; score and queue history is immutable")
