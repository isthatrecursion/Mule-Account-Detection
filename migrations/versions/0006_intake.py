"""Durable intake lifecycle, immutable content claims and recoverable raw publication."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def identity() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.add_column(
        "validation_reports",
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Historical Phase 3 reports predate publication tracking.
    op.execute("UPDATE validation_reports SET published = true")
    op.alter_column("validation_reports", "published", server_default=None)
    op.add_column("score_runs", sa.Column("validation_id", sa.Uuid(), nullable=True))
    op.execute(
        "UPDATE score_runs AS r SET validation_id = b.accepted_validation_id FROM batches AS b WHERE r.batch_id = b.id"
    )
    op.create_foreign_key(
        "fk_run_validation",
        "score_runs",
        "validation_reports",
        ["validation_id", "batch_id"],
        ["id", "batch_id"],
    )
    op.create_table(
        "intake_requests",
        *identity(),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("operation_scope", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("declaration", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("observed", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("replay_of", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_intake_requests"),
        sa.UniqueConstraint(
            "actor_id", "operation_scope", "idempotency_key", name="uq_intake_request"
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["batches.id"], name="fk_intake_requests_batch_id_batches"
        ),
        sa.ForeignKeyConstraint(
            ["replay_of"],
            ["intake_requests.id"],
            name="fk_intake_requests_replay_of_intake_requests",
        ),
        sa.CheckConstraint(
            "state IN ('RECEIVED','VALIDATING','ACCEPTED','QUARANTINED','FAILED')",
            name="ck_intake_requests_state",
        ),
    )
    op.create_index("ix_intake_state_created", "intake_requests", ["state", "created_at"])
    op.create_table(
        "raw_publications",
        *identity(),
        sa.Column("intake_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("byte_count", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_raw_publications"),
        sa.ForeignKeyConstraint(
            ["intake_id"],
            ["intake_requests.id"],
            name="fk_raw_publications_intake_id_intake_requests",
        ),
        sa.CheckConstraint("kind IN ('RAW','REPORT')", name="ck_raw_publications_kind"),
        sa.CheckConstraint("state IN ('STAGED','PUBLISHED')", name="ck_raw_publications_state"),
        sa.CheckConstraint("byte_count >= 0", name="ck_raw_publications_bytes"),
    )
    op.create_index("ix_publication_intake", "raw_publications", ["intake_id"])
    op.create_table(
        "intake_contents",
        *identity(),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("access_scope", sa.String(), nullable=False),
        sa.Column("metadata_hash", sa.String(64), nullable=False),
        sa.Column("original_intake_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_intake_contents"),
        sa.UniqueConstraint("digest", "access_scope", name="uq_intake_content"),
        sa.ForeignKeyConstraint(
            ["original_intake_id"],
            ["intake_requests.id"],
            name="fk_intake_contents_original_intake_id_intake_requests",
        ),
    )
    tables = "intake_requests, raw_publications, intake_contents"
    op.execute(f"REVOKE ALL ON {tables} FROM PUBLIC, mule_runtime, mule_readonly")
    op.execute(f"GRANT SELECT, INSERT ON {tables} TO mule_runtime")
    op.execute(f"GRANT SELECT ON {tables} TO mule_readonly")
    op.execute(
        "GRANT UPDATE (state, observed, result, batch_id) ON intake_requests TO mule_runtime"
    )
    op.execute("GRANT UPDATE (state) ON raw_publications TO mule_runtime")


def downgrade() -> None:
    raise RuntimeError("Destructive downgrades are disabled; use a reviewed forward migration")
