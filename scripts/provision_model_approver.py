"""Provision a separate, minimally privileged LOCAL approval identity after migration.

Administrator credentials are read only by this provisioning process. It creates
no model approval and grants no membership to the runtime/training identity.
"""

import argparse
import secrets
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="mule_operational")
    parser.add_argument(
        "--admin-url-file", type=Path, default=ROOT / "secrets/test_admin_database_url"
    )
    args = parser.parse_args()
    if args.database != "mule_operational" and not args.database.startswith("mule_test_"):
        parser.error("Only local operational or dedicated test databases are allowed")
    directory = ROOT / "secrets"
    admin = make_url(args.admin_url_file.read_text().strip())
    if admin.host not in {"localhost", "127.0.0.1"}:
        parser.error("Only a loopback administrator endpoint is allowed")
    password_path = directory / "mule_model_approver_password"
    if not password_path.exists():
        with password_path.open("x", encoding="ascii") as stream:
            stream.write(secrets.token_urlsafe(36))
        password_path.chmod(0o600)
    password = password_path.read_text().strip()
    endpoint = admin.set(drivername="postgresql", database=args.database)
    with psycopg.connect(endpoint.render_as_string(hide_password=False), autocommit=True) as db:
        if not db.execute("SELECT 1 FROM pg_roles WHERE rolname='mule_model_approver'").fetchone():
            db.execute(
                sql.SQL(
                    "CREATE ROLE mule_model_approver LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
                ).format(sql.Literal(password))
            )
        db.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO mule_model_approver").format(
                sql.Identifier(args.database)
            )
        )
        db.execute("GRANT USAGE ON SCHEMA public TO mule_model_approver")
        db.execute(
            "GRANT SELECT ON registry_candidates, model_decisions, audit_events, outbox TO mule_model_approver"
        )
        db.execute("GRANT INSERT ON model_decisions, audit_events, outbox TO mule_model_approver")
        # PostgreSQL row locks also need an UPDATE privilege; only the retirement
        # column can be changed, never the digest, source evidence or trainer.
        db.execute("GRANT UPDATE (retired) ON registry_candidates TO mule_model_approver")
    if args.database == "mule_operational":
        path = directory / "model_approval_database_url"
        value = endpoint.set(
            drivername="postgresql+psycopg", username="mule_model_approver", password=password
        ).render_as_string(hide_password=False)
        if path.exists() and path.read_text().strip() != value:
            parser.error("Existing approval endpoint differs; review it without overwriting")
        if not path.exists():
            with path.open("x", encoding="utf-8") as stream:
                stream.write(value)
            path.chmod(0o600)
    print("Local approval identity provisioned; credentials omitted; no candidate approved.")


if __name__ == "__main__":
    main()
