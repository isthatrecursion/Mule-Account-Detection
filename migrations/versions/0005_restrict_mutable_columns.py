"""Runtime updates only workflow/lease/delivery fields, preserving stored lineage."""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("REVOKE UPDATE ON batches, jobs, cases, outbox FROM mule_runtime")
    op.execute("GRANT UPDATE (status, accepted_validation_id) ON batches TO mule_runtime")
    op.execute(
        "GRANT UPDATE (state, lease_owner, lease_expires_at, fencing_token, result_reference) ON jobs TO mule_runtime"
    )
    op.execute("GRANT UPDATE (state, assignee, version, conclusion) ON cases TO mule_runtime")
    op.execute("GRANT UPDATE (delivered_at) ON outbox TO mule_runtime")


def downgrade() -> None:
    raise RuntimeError("Privilege widening requires an explicitly reviewed forward migration")
