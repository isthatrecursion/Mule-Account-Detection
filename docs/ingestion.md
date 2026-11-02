# Phase 4 intake and validation

`IngestService.ingest()` is the application boundary for bounded CSV streams. It creates a committed receipt and receive audit before staging, records `VALIDATING` before parsing, and saves declared and observed metadata separately. Terminal outcomes are `ACCEPTED`, `QUARANTINED` or `FAILED`. Request status is available by intake ID to the authorized actor. A receipt is not an accepted batch.

## Configuration and input

`config/ingestion.yaml` is server-owned. It registers a small synthetic CSV source; the local bootstrap also binds the existing research schema, policy, reference dataset hash and saved split register. Client JSON cannot supply schema paths, rule code, source certification, split paths or raw-file paths. Shared/qualified ingestion is disabled pending authenticated source authority. No real qualified sources are registered.

CSV is the supported format in this phase. Parquet and compressed input are rejected explicitly; there is no unchecked decompression or automatic parser fallback. Defaults are 128 MiB and 100,000 rows, configurable within existing settings limits. Files are staged under generated UUID names. The original filename is sanitized display metadata only. Staging plaintext and secret keys require protected directory permissions/Windows ACLs. Published raw and report objects use AES-GCM with a separately injected 256-bit key. Keys are never in images, manifests or logs.

The declaration JSON wraps the existing frozen `BatchManifest` without changing its contract:

```json
{
  "manifest": {"contract_version": "batch_manifest_v1", "...": "all required manifest fields"},
  "byte_count": 123,
  "logical_schema_signature": "64 lowercase SHA-256 characters"
}
```

For a registered profile, `profile.signature` hashes the canonical ordered `(column name, logical type)` definitions. CSV headers must match that schema, with order canonicalized. The checksum covers exact uploaded bytes, including newlines and BOM. Declared byte count, checksum, schema signature and row count are checked against observed data; false declarations are quarantined, not repaired.

Rules execute in stable phases: schema/version; manifest/count/identity/type; timestamps/source availability; predictor separation. Findings contain stable rule/version IDs, severity, aggregate counts, safe sample references and fixed remediation. Category drift is a warning. Research confounding and unverifiable provenance remain promotion blockers even when restricted research ingestion passes. `assert_qualified_promotion` rejects these reports; ingestion alone grants no model approval.

## Publication, replay and scoring

`raw_publications` records `STAGED` before filesystem publication and `PUBLISHED` afterward. Finalization rechecks checksum/size, flushes bytes and uses an atomic non-overwriting hard link. Existing objects must authenticate before reuse. This local adapter requires a filesystem supporting atomic hard links. Report publication precedes the final transaction containing batch status, accepted validation pointer and audit/outbox event. A crash between these systems leaves inspectable publication state and never accepts an incomplete batch.

Idempotency keys are scoped to actor and environment, with every declared business parameter bound into the request hash. Repeated content under the same source/schema/manifest scope resolves to the existing result. New upload IDs do not create duplicate batches. Declared producer jobs and creation timestamps remain part of provenance and must agree. Conflicting source/owner/policy metadata is quarantined for review. A deliberate replay requires explicit authorization, a new batch identity and an audited parent intake ID. A changed request under an existing key raises a conflict. Retry access is checked again.

Revalidation reads authenticated stored bytes and runs current server rules. A changed rule/profile/policy fingerprint creates an immutable new report. The accepted pointer may advance or be withdrawn for future use; old reports remain. New score runs capture the exact accepted validation ID. `get_accepted_batch` requires an accepted, published report; a staged file or quarantined batch cannot authorize scoring. Exact intake replay returns its original historical result; scoring must still query the current acceptance pointer.

Research uses the existing hash-bound adapter and saved row alignment. All holdout rows are excluded before quality summaries. `research_scoring_input()` checks acceptance and source access, reloads verified development membership, rejects held-out/unknown/duplicate keys and emits predictor fields only. Future workers must use this boundary. Generic partition selection from an analyst request is unsupported. Labels, reference index and extraction-month metadata stay out of predictors.

Quality JSON includes authorized-row counts, per-predictor missing/constant/zero patterns, approved category frequencies, unknown counts, source coverage and a compact table. It never lists unknown category values. `training_quality()` separately authorizes, audits and stores restricted class/cohort missingness diagnostics on the verified development subset; ordinary ingestion reports and the CLI never expose labels. The safe result DTO contains only IDs, outcome, counts, finding codes, an opaque report reference and a false qualified-promotion flag.

## CLI

Apply Alembic revision `0006` using the migration identity as described in [persistence](persistence.md). Supply the runtime PostgreSQL URL through `MULE_DATABASE_URL` or a protected settings secret directory, and `MULE_MLFLOW_URI` as required by the shared settings boundary. Initialize the existing ignored artifact key with `scripts/init_local_secrets.py` if needed. No command here resets a database or rotates existing passwords.

`validate-batch --manifest declaration.json --request-id UUID --filename upload.csv` reads binary CSV data from standard input. Reuse the request ID and exact declaration for a retry. To preserve byte identity on Windows, pass a binary file handle rather than a PowerShell text pipeline:

```python
import subprocess
import sys

with open("secrets/upload.csv", "rb") as stream:
    result = subprocess.run([
        sys.executable, "-m", "mule_detection.cli", "validate-batch",
        "--manifest", "secrets/declaration.json", "--request-id", "YOUR-UUID",
    ], stdin=stream)
raise SystemExit(result.returncode)
```

Exit codes: `0` accepted; `5` rejected/quarantined or still pending; `1` system failure; `2` argument error; `3` settings error. Results are JSON without raw paths, row samples or labels. Intentional replay additionally takes `--replay-of INTAKE-UUID` and a new request and batch ID.

`recover-intake` defaults to a dry run. `--apply` resumes aged tracked publications and marks abandoned unfinished receipts failed, requiring explicit replay to validate again. `--apply --delete-orphans` also removes eligible staging files only after retention (default 24 hours, minimum one hour) and after checking all actors' database references. Failed/quarantined partial staging can be removed after retention; receipts/audits remain. Published raw/report objects and referenced staging are not deleted. Recovery does not declare a batch accepted. The local operator must run recovery during a maintenance window with intake workers stopped; it is not a scheduler or distributed lease manager.

Verification: `python scripts/verify_persistence.py --phase 4 --connections-file secrets/DEDICATED_TEST_CONNECTIONS.json --output-dir artifacts/phase4/NEW_RUN`. The existing dedicated-test guards remain mandatory. Phase 4 performs no training, scoring, public API exposure or production approval.
