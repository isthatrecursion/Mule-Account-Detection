#!/bin/bash
set -euo pipefail
# No echo/xtrace: passwords enter psql via environment, then quoted SQL literals.
secret_root="${MULE_SECRETS_DIR:-/run/secrets}"
# Docker preloads these while root can read mode-0600 host-mounted secrets.
# The fallback supports controlled direct initialization outside Docker.
if [[ ! -v MIGRATION_PASSWORD ]]; then
    MIGRATION_PASSWORD="$(cat "$secret_root/mule_migration_password")"
fi
if [[ ! -v RUNTIME_PASSWORD ]]; then
    RUNTIME_PASSWORD="$(cat "$secret_root/mule_runtime_password")"
fi
if [[ ! -v TRACKING_PASSWORD ]]; then
    TRACKING_PASSWORD="$(cat "$secret_root/mule_tracking_password")"
fi
if [[ ! -v READONLY_PASSWORD ]]; then
    READONLY_PASSWORD="$(cat "$secret_root/mule_readonly_password")"
fi
: "${MIGRATION_PASSWORD:?A nonempty migration credential is required}"
: "${RUNTIME_PASSWORD:?A nonempty runtime credential is required}"
: "${TRACKING_PASSWORD:?A nonempty tracking credential is required}"
: "${READONLY_PASSWORD:?A nonempty read-only credential is required}"
export MIGRATION_PASSWORD RUNTIME_PASSWORD TRACKING_PASSWORD READONLY_PASSWORD
psql --username "$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
\getenv migration_password MIGRATION_PASSWORD
\getenv runtime_password RUNTIME_PASSWORD
\getenv tracking_password TRACKING_PASSWORD
\getenv readonly_password READONLY_PASSWORD
CREATE ROLE mule_migration LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'migration_password';
CREATE ROLE mule_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'runtime_password';
CREATE ROLE mule_tracking LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'tracking_password';
CREATE ROLE mule_readonly LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'readonly_password';
CREATE DATABASE mule_operational OWNER mule_migration;
CREATE DATABASE mule_tracking OWNER mule_tracking;
REVOKE ALL ON DATABASE mule_operational FROM PUBLIC;
REVOKE ALL ON DATABASE mule_tracking FROM PUBLIC;
REVOKE ALL ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;
GRANT CONNECT ON DATABASE mule_operational TO mule_migration, mule_runtime, mule_readonly;
GRANT CONNECT ON DATABASE mule_tracking TO mule_tracking;
\connect mule_operational
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO mule_migration;
GRANT USAGE ON SCHEMA public TO mule_runtime, mule_readonly;
\connect mule_tracking
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO mule_tracking;
SQL
unset MIGRATION_PASSWORD RUNTIME_PASSWORD TRACKING_PASSWORD READONLY_PASSWORD
