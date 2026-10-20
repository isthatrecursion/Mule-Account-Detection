"""Explicit least-privilege grants; no default grants for future/event tables."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABLES = (
    "datasets, batches, validation_reports, model_refs, artifacts, jobs, job_attempts, "
    "score_runs, score_rows, evidence, queue_snapshots, queue_members, cases, review_events, "
    "approvals, labels, audit_events, outbox"
)


def upgrade() -> None:
    op.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA public TO mule_runtime, mule_readonly")
    op.execute(f"REVOKE ALL ON {TABLES} FROM PUBLIC, mule_runtime, mule_readonly")
    op.execute(f"GRANT SELECT, INSERT ON {TABLES} TO mule_runtime")
    op.execute(f"GRANT SELECT ON {TABLES} TO mule_readonly")
    op.execute("GRANT UPDATE ON batches, jobs, cases, outbox TO mule_runtime")
    # Alembic history, schema CREATE and role membership remain migration-only.


def downgrade() -> None:
    raise RuntimeError("Destructive downgrades are disabled; restore or forward-fix")
