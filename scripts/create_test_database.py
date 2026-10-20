"""Create a NEW dedicated test database; never reset/drop an existing database.

Requires MULE_TEST_ENVIRONMENT=test and MULE_TEST_ADMIN_DATABASE_URL (or _FILE).
The fixed application roles must already exist from controlled cluster initialization.
"""

import argparse
import os
import re
from pathlib import Path

import psycopg
from psycopg import sql


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    if (
        os.environ.get("MULE_TEST_ENVIRONMENT") != "test"
        or re.fullmatch(r"mule_test_[a-z0-9_]+", args.database) is None
    ):
        parser.error("Explicit test environment and mule_test_* name are required")
    url = os.environ.get("MULE_TEST_ADMIN_DATABASE_URL")
    if not url:
        url = Path(os.environ["MULE_TEST_ADMIN_DATABASE_URL_FILE"]).read_text().strip()
    # psycopg uses libpq URLs, without SQLAlchemy's +psycopg suffix.
    with psycopg.connect(url, autocommit=True) as connection:
        name = sql.Identifier(args.database)
        connection.execute(sql.SQL("CREATE DATABASE {} OWNER mule_migration").format(name))
        connection.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(name))
        connection.execute(
            sql.SQL(
                "GRANT CONNECT ON DATABASE {} TO mule_migration, mule_runtime, mule_readonly"
            ).format(name)
        )
    print("Dedicated test database created; no existing database was reset.")


if __name__ == "__main__":
    main()
