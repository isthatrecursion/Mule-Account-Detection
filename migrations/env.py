"""Migration-only credentials; never fall back to the runtime database URL."""

import os
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from mule_detection.persistence.models import Base

config = context.config
target_metadata = Base.metadata


def run() -> None:
    supplied = config.attributes.get("connection")
    if supplied is not None:
        context.configure(connection=supplied, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    url = os.environ.get("MULE_MIGRATION_DATABASE_URL")
    secret_file = os.environ.get("MULE_MIGRATION_DATABASE_URL_FILE")
    if not url and secret_file:
        url = Path(secret_file).read_text(encoding="utf-8").strip()
    if not url:
        raise RuntimeError("A migration-only database URL is required")
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(
        url, poolclass=NullPool, hide_parameters=True, connect_args={"connect_timeout": 10}
    )
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run()
