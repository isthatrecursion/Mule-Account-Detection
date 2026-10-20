#!/bin/bash
# Run only in a disposable official PostgreSQL container, never on the host.
set -euo pipefail
work=/tmp/mule-private-secret-startup-test
mkdir -p "$work/secrets" "$work/empty" "$work/missing"
chmod 755 "$work" "$work/secrets" "$work/empty" "$work/missing"
for name in postgres_admin_password mule_migration_password mule_runtime_password mule_tracking_password mule_readonly_password; do
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n' > "$work/secrets/$name"
    chown 1001:1001 "$work/secrets/$name"
    chmod 600 "$work/secrets/$name"
done

# Simulate the runner's private files: readable by container root, not postgres.
if gosu postgres test -r "$work/secrets/mule_migration_password"; then
    printf 'FAILED: secret ownership fixture does not isolate postgres\n' >&2
    exit 1
fi
unset MIGRATION_PASSWORD RUNTIME_PASSWORD TRACKING_PASSWORD READONLY_PASSWORD
export PGDATA="$work/data" POSTGRES_USER=postgres POSTGRES_DB=postgres
export POSTGRES_INITDB_ARGS='--auth-host=scram-sha-256'
export POSTGRES_PASSWORD_FILE="$work/secrets/postgres_admin_password"
export MULE_SECRETS_DIR="$work/secrets"

# Neither a missing file nor an empty file may reach database initialization.
if MULE_SECRETS_DIR="$work/missing" bash /opt/mule/entrypoint.sh postgres > "$work/missing.log" 2>&1; then
    printf 'FAILED: startup accepted missing secrets\n' >&2
    exit 1
fi
cp "$work/secrets/"* "$work/empty/"
: > "$work/empty/mule_runtime_password"
if MULE_SECRETS_DIR="$work/empty" bash /opt/mule/entrypoint.sh postgres > "$work/empty.log" 2>&1; then
    printf 'FAILED: startup accepted an empty secret\n' >&2
    exit 1
fi
if gosu postgres bash /opt/mule/entrypoint.sh postgres > "$work/permission.log" 2>&1; then
    printf 'FAILED: startup ignored a private-file read failure\n' >&2
    exit 1
fi
test ! -e "$PGDATA/PG_VERSION"
printf 'PASSED: missing, empty and unreadable secrets fail before initialization\n'

# The direct-init fallback must also stop before psql if a read fails.
psql() { printf 'PSQL_MUST_NOT_RUN\n'; }
export -f psql
if gosu postgres bash /opt/mule/init/01-databases.sh > "$work/fallback.log" 2>&1; then
    printf 'FAILED: direct initialization accepted unreadable secrets\n' >&2
    exit 1
fi
if grep -q PSQL_MUST_NOT_RUN "$work/fallback.log"; then
    printf 'FAILED: direct initialization reached SQL after a secret read failure\n' >&2
    exit 1
fi
unset -f psql
printf 'PASSED: direct initialization fails before SQL on secret read errors\n'

cleanup() {
    if [[ -s "$PGDATA/postmaster.pid" ]]; then
        gosu postgres pg_ctl -D "$PGDATA" -m fast -w stop >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT
startup_entrypoint="${MULE_TEST_STARTUP_ENTRYPOINT:-/opt/mule/entrypoint.sh}"
bash "$startup_entrypoint" postgres > "$work/startup.log" 2>&1 &
server_pid=$!
ready=false
for attempt in {1..60}; do
    if pg_isready -h 127.0.0.1 -U postgres -d postgres >/dev/null 2>&1; then
        ready=true
        break
    fi
    if ! kill -0 "$server_pid" 2>/dev/null; then
        printf 'FAILED: PostgreSQL startup exited\n' >&2
        tail -n 30 "$work/startup.log" >&2
        exit 1
    fi
    sleep 1
done
if [[ "$ready" != true ]]; then
    printf 'FAILED: PostgreSQL did not become ready\n' >&2
    exit 1
fi

# Authenticate over TCP/SCRAM, not a local trust-authenticated Unix socket.
for role in mule_migration mule_runtime mule_readonly mule_tracking; do
    database=mule_operational
    if [[ "$role" == mule_tracking ]]; then database=mule_tracking; fi
    if PGPASSWORD=invalid-synthetic-password command psql \
        -h 127.0.0.1 -U "$role" -d "$database" -At -v ON_ERROR_STOP=1 \
        -c 'SELECT current_user' > "$work/wrong-password.log" 2>&1; then
        printf 'FAILED: PostgreSQL accepted an incorrect password for %s\n' "$role" >&2
        exit 1
    fi
    actual=$(PGPASSWORD="$(cat "$work/secrets/${role}_password")" command psql \
        -h 127.0.0.1 -U "$role" -d "$database" -At -v ON_ERROR_STOP=1 -c 'SELECT current_user')
    test "$actual" = "$role"
    printf 'PASSED: private-file startup authenticates %s\n' "$role"
done
printf 'PASSED: isolated PostgreSQL startup regression checks\n'
