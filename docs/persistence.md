# Phase 3 persistence

The adapter uses SQLAlchemy 2, psycopg 3 and Alembic on PostgreSQL. It stores lineage and operational metadata in 18 tables. Wide raw/features are encrypted, immutable snapshots outside the case table. Phase 4 supplies intake validation; Phase 7 supplies actual model approval; Phase 8 supplies the scoring pipeline; Phase 9 authenticates callers and derives their permissions/scopes. No service here grants qualified approval or performs model inference.

## Local setup

Install the platform dev hash lock and the editable package as described in [development](development.md). Generate ignored local secrets once:

```powershell
.\.venv\Scripts\python.exe scripts/init_local_secrets.py
.\.venv\Scripts\python.exe scripts/configure_local_database.py --test-database mule_test_local
docker compose -f compose.yaml -f compose.local.yaml up -d --wait
$env:MULE_MIGRATION_DATABASE_URL_FILE = (Resolve-Path secrets/migration_database_url).Path
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Compose uses PostgreSQL 17.9, a named volume, SCRAM passwords read from mounted secrets, a health check and separate operational/tracking databases. The base Compose file exposes no host port. The local override binds only `127.0.0.1:55432`. Application runtime credentials belong only to the operational DB. Tracking owns only its separate database. The migration identity owns application schema objects; it is absent from future runtime containers. Read-only has operational SELECT. Initialization runs only for an empty volume; changing secret files does not rotate existing role passwords. Never delete an existing volume to apply migrations or rotate secrets.

Secret generators refuse connection-file overwrites. Keep secret files protected by OS ACLs (Unix mode 0600 is requested; Windows needs account/directory ACLs), use organization-managed keys/storage for shared environments and never copy local keys into images. The encrypted snapshot adapter takes its 32-byte AES-GCM key from injected code/secret storage; `secrets/artifact_key` is a local hex key example. It never loads a key implicitly. Key rotation must retain historical decryption keys and use a separately approved migration; replacing a key file alone cannot decrypt old snapshots. Disk/backup encryption and retention remain deployment controls in Phase 14.

On Linux, file-backed Compose secrets retain host ownership and permissions. The custom PostgreSQL entrypoint reads the four role credentials before the official entrypoint switches to the PostgreSQL identity. Missing, unreadable or empty credentials stop startup; file permissions stay private. Shell scripts use LF on every checkout. The CI startup regression uses a disposable container with mode-0600 secrets owned by a different UID, requires SCRAM, rejects incorrect passwords and checks all four role logins. Existing initialized databases still require an explicit administrative password rotation if their credentials are incorrect; restarting does not repair them. Each GitHub-hosted CI job initializes a fresh test volume.

## Schema and transaction boundaries

Ordered, explicit DDL revisions create lineage (`0001`), scores/queues (`0002`), cases/history/audit (`0003`), table grants (`0004`) and narrow mutable-column grants (`0005`). Later event/reconciliation tables/indexes belong in new Phase 11 revisions. Revision files contain frozen DDL independent of current ORM metadata; production never calls `create_all()`. The integration suite checks metadata/revision consistency on an initially empty dedicated database.

`application/unit_of_work.py` opens/closes one session and transaction per operation. Repositories may flush but never commit. Review and worker-publication services own the UoW, including review/publication events, audit and outbox. An exception, constraint failure or failed commit rolls back the whole operation. Do not catch a persistence failure and then commit that operation. A result callback receives the same session; it must never commit, open a second write transaction or perform irreversible external effects. Outbox delivery workers are future work.

Job/run identity is actor + operation + idempotency key, bound to canonical JSON fingerprints. Dataset identity is content digest; batch identity binds the supplied batch ID to dataset/manifest identity. Review transitions share a `case:transition` idempotency scope; the stored action records assignment/review/reopen permission. Exact retries return the original result and still check current permissions/scopes. Changed content conflicts. Only named identity conflicts are translated; FK/check/unrelated unique failures propagate for safe boundary handling.

Case transitions use a conditional version update. A reopened case clears the current conclusion while preserving immutable review history. Authentication and row-scope derivation must come from trusted server records in Phase 9, never client request fields. These are internal Python services, not authenticated public endpoints. Infrastructure audit stores references, not note text. Model/export services in their later phases must invoke `AuditService` for `model:approve` and `export:authorize`; those operations are not implemented by merely listing their audit action names.

Worker acquisition increments a fencing token and records an attempt. Lease checks and renewal use PostgreSQL wall time, not application/transaction-start time. Publication locks the job row, validates owner/token/expiry before result writes, and checks again after flushing result/audit writes. A replacement waits for the lock. Expired or superseded workers fail and the UoW rolls back their output. Privileged failed-job retry is permission checked, idempotent and audited; it advances the fence. There is no scheduler/reconciliation worker yet.

`case_artifact()` follows case -> score row -> immutable score run -> snapshot metadata. It checks scopes and returns the record lookup key; `ArtifactStore.observation()` independently authorizes before disk access, authenticates ciphertext, checks the content digest and metadata, then resolves that historical record. Later source files cannot change this pointer. The local JSON format permits small approved frames; it does not claim Parquet conversion/performance for the full research extract. Writes use a flushed temporary file and atomic, non-overwriting hard-link publication. Storage must support local atomic hard links; there is no unsafe non-atomic fallback.

## Dedicated test databases

Create a NEW database once using the administrative identity, then run tests with the migration/runtime/read-only identities:

```powershell
$env:MULE_TEST_ENVIRONMENT = 'test'
$env:MULE_TEST_ADMIN_DATABASE_URL_FILE = (Resolve-Path secrets/test_admin_database_url).Path
.\.venv\Scripts\python.exe scripts/create_test_database.py --database mule_test_local
.\.venv\Scripts\python.exe scripts/verify_persistence.py --connections-file secrets/test_connections.json --output-dir artifacts/phase3/my_new_run
```

On the approved local data machine, add `--with-reference` to verify historical dataset/split/exclusion/evidence hashes. CI needs synthetic fixtures only. The optional JSON file contains `MULE_TEST_ENVIRONMENT=test`, `MULE_TEST_DATABASE_URL`, `MULE_TEST_RUNTIME_DATABASE_URL`, `MULE_TEST_READONLY_DATABASE_URL` and `MULE_TEST_TRACKING_DATABASE_URL`; generators write it under ignored secrets. All test operational URLs must target the same dedicated `mule_test_*` database. Tracking tests only connect/read role identity; they do not reset the tracking database.

Migration fixtures require explicit test opt-in, verify the actual connected database name, and truncate only the known application tables inside that dedicated database. No fixture drops a database/schema or touches operational data. Do not run two test suites concurrently against the same test DB. The PostgreSQL marker is excluded from ordinary foundation checks; explicitly invoking PostgreSQL tests without the required credentials fails rather than skipping or passing a fake integration. The runner writes a new report, source/config hashes, JUnit (including synthetic EXPLAIN evidence), logs and checksums; secret URLs/passwords are excluded/redacted.

## Migration recovery

Before shared migration, take and verify a PostgreSQL backup and record current Alembic revision, migration hashes, operator and change ticket in the controlled maintenance log. Run as the migration role during a coordinated maintenance window. PostgreSQL transactional DDL rolls back a failed revision/transaction; inspect the revision and schema through a new connection before retrying corrected, unpublished migration work. The suite injects a failing revision after table creation and proves neither the table nor revision change commits.

Released migration files are immutable: fix a released defect with a new forward revision. Destructive downgrades deliberately fail. For incompatible/corrupt committed state, stop writers and restore the verified pre-migration backup into a separate replacement database, validate schema/lineage/audit integrity, then explicitly switch connection secrets under the approved recovery procedure. Never use `stamp head` to hide failed DDL or reset a persistent volume. Full backup/restore deployment drills remain Phase 14.

See [audit controls](audit_controls.md), [query shapes](query_shapes.md) and [Phase 3 evidence](acceptance/phase3_readiness.md).
