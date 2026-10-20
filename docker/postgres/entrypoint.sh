#!/bin/bash
set -euo pipefail

# File-backed Compose secrets retain host ownership/mode on Linux. Read private
# files before the official entrypoint drops from root to the postgres identity.
# Assignment and export are separate so a failed read cannot become an empty
# PostgreSQL role password hidden behind a successful `export` command.
secret_root="${MULE_SECRETS_DIR:-/run/secrets}"
MIGRATION_PASSWORD="$(cat "$secret_root/mule_migration_password")"
RUNTIME_PASSWORD="$(cat "$secret_root/mule_runtime_password")"
TRACKING_PASSWORD="$(cat "$secret_root/mule_tracking_password")"
READONLY_PASSWORD="$(cat "$secret_root/mule_readonly_password")"
: "${MIGRATION_PASSWORD:?A nonempty migration credential is required}"
: "${RUNTIME_PASSWORD:?A nonempty runtime credential is required}"
: "${TRACKING_PASSWORD:?A nonempty tracking credential is required}"
: "${READONLY_PASSWORD:?A nonempty read-only credential is required}"
export MIGRATION_PASSWORD RUNTIME_PASSWORD TRACKING_PASSWORD READONLY_PASSWORD

exec /usr/local/bin/docker-entrypoint.sh "$@"
