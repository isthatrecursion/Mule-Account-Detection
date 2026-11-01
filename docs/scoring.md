# Scoring, explanations and publication

Phase 8 implements a complete local research scoring workflow from accepted input
and an independently approved immutable bundle to a versioned ranked queue. It
adds global correction/re-ranking, encrypted evidence and crash-safe retries.
The current extract still cannot support qualified use or claims of prospective
fraud detection performance.

## Commands and setup

Use the existing locked Python environment, PostgreSQL and Phase 7 model registry.
Apply the additive migration with migration-only credentials:

```powershell
$env:MULE_MIGRATION_DATABASE_URL_FILE='secrets/migration_database_url'
.venv/Scripts/python.exe -m alembic upgrade head
```

An accepted research batch and a separately approved `RESEARCH_DEMO` candidate are
required. `--model-version` accepts the immutable bundle SHA-256 digest, never a
filesystem path or a mutable MLflow tag. Resolve a human-readable deployment alias
to its approved digest before submitting a scoring request.

```text
mule-detection score --batch-id <uuid> --model-version <bundle-sha256> --target-environment research
mule-detection score --batch-id <uuid> --model-version <bundle-sha256> --target-environment research --enqueue-only
mule-detection score-job --job-id <uuid>
```

Root/environment settings precede the command. The first command executes the
local worker synchronously; enqueue-only records a durable job for a subsequent
worker invocation. This phase does not add a distributed scheduler or HTTP API.
Repeated equivalent requests from the same actor return the original job/run.
After completion, retries retrieve history even if the model is later retired;
they do not grant another inference or publication permission.

A deliberate full replay requires both an explicit new identity and its completed
predecessor, preserving the original run:

```text
mule-detection score --batch-id <uuid> --model-version <bundle-sha256> --target-environment research --replay-id <new-uuid> --replay-of <completed-run-uuid>
```

Corrections use the same command with one or more `--affected-key <key>` arguments.
Their replay ID identifies the reconciliation event, and the new accepted batch
must have the identical eligible population, policy and model. The current real
research adapter has dataset-scoped identities and one trusted extract: it cannot
certify identity continuity across a changed extract. Cross-extract corrections
therefore remain gated on a stable, certified source/identity adapter. The full
correction algorithm is exercised with a synthetic accepted stable-identity source;
no real source is silently remapped or certified.

## Identity, preflight and immutable inputs

`scoring_request_v1` rejects extra fields, arbitrary scores/model paths and
unlinked replay requests. Canonical job identity binds batch/content, accepted
validation, immutable model digest, feature/review policies and replay/correction
identity. Job creation registers the selected model pin, score run, source index
and immutable task in one transaction. Concurrent equivalent submissions converge
on one logical run.

New requests must pass accepted/published validation, protected raw parsing,
trusted source/split hashes, feature signature/policy compatibility, research
environment/data tier and independent model approval. Saved runtime/fixture checks
run before logical scoring starts. The worker independently rechecks the trusted
split register and exact development membership, job/request/model lineage,
acceptance and approval. Holdout keys cannot enter through a direct worker call.
Preflight failures save safe failed-attempt metadata and preserve the active queue.

Immutable feature shards contain predictors only; record keys stay outside the
feature matrix, and targets/holdout rows never enter scoring artifacts. Shards,
chunk scores, ranked staging and detailed contribution evidence use the existing
authenticated encrypted content-addressed artifact store. Per-row score contracts
pin the exact feature shard, including corrected observations. Historical case
reads resolve that row-level snapshot rather than a current mutable frame.

The worker processes at most 128 rows per chunk, with bounded estimator threads
inside the Phase 7 credential-free, resource-limited process. The existing
research adapter materializes the accepted development frame once during request
preflight; this implementation does not claim streaming intake or a 100k-row
capacity benchmark. Model execution and feature artifact reads are chunk-bounded.

## Staging, ranking and factual evidence

Each attempt acquires a database-clock lease and increasing fencing token. Chunk
metadata records row membership, artifact identity and completion under that
token. Failed attempts restart the entire unpublished run with a new token;
previous attempt chunks remain immutable evidence and are never blindly appended.
Leases renew between bounded operations. A stale worker cannot change the new
owner's job state or publish.

Result validation rejects missing/duplicate keys, nonfinite/out-of-range scores,
wrong signatures and incomplete/mismatched chunks. Scores sort descending, then
by stable record key. Every eligible row receives a persisted rank and cohort
size. Percentile is `100 * (N - rank) / (N - 1)`; singleton percentile is 100 and
an empty ranking has no values. The queue contains `min(K, N)` members, while the
full ranking remains available for authorized navigation.

Only the selected top-K cases require detailed explanations in this workflow.
Other ranked rows retain full lineage and an explicit
`NOT_SELECTED_FOR_EXPLANATION` state; no explanation is invented for them.
LightGBM uses the exact stored transformer and `pred_contrib`, preserving its base
column and checking additivity against the raw model margin. Logistic bundles
use exact coefficient contributions on their stored scaled matrix/log-odds.
Both use raw-margin evidence, not percentile or calibrated-probability evidence.
Older logistic bundles declaring another contribution scale must be repackaged;
preflight rejects them instead of silently changing their meaning.

Encoded details remain available for audit. Contributions aggregate by saved raw
field mappings without parsing generated feature names; the aggregate preserves
the total. Facts include observed/imputed/derived status, training empirical-CDF
percentiles for suitable numeric values and frequency/unseen flags for categories.
Unknown values never become observed medians. All current dictionary meanings
remain unverified, so displays retain raw feature IDs and make no claims about
transaction velocity, counterparties, intent or causality.

See the pinned library's [Booster prediction documentation](https://lightgbm.readthedocs.io/en/stable/pythonapi/lightgbm.Booster.html)
for the expected-value contribution column.

## Atomic publication and reads

The publisher independently authenticates staged membership, chunk results,
deterministic ranking and required explanation artifacts. It verifies raw/encoded
additivity, feature mapping signature, scale and dictionary/policy/model/snapshot
lineage before acquiring publication locks.

One short transaction then locks the cohort/environment scope, fences the job,
rechecks acceptance and model revocation, compares the expected predecessor,
inserts all score/evidence rows and immutable queue membership, switches the
active head, marks the run/attempt/job complete and appends audit/outbox events.
A final database-clock lease check occurs before commit. Failed transactions leave
the prior pointer and all its score/evidence versions intact. A lost response
after commit returns the same committed result on retry without duplicate events.

`ScoreQueries` reads an explicit queue version or its active head. Opening an old
queue never silently changes its assessment; a flag indicates a newer queue.
No usable published assessment returns a nullable score and state reasons, not
zero score/rank. Last-complete assessment references remain distinct from current
state. Research observations have unknown observation/availability cutoffs, so
their score DTOs explicitly use `STALE`, `UNKNOWN` completeness and provenance
limitations even though the ranking/publication itself is complete. No source
freshness or qualified completeness is fabricated.

## Corrected cohort behavior

For an approved same-population correction, only affected records are rescored.
Unchanged raw scores and their original observation snapshots are carried forward
into new immutable score versions with predecessor score references. All ranks
and percentiles are recomputed over the entire cohort; newly selected cases get
evidence from the exact snapshot/model that produced their score. A new queue
publishes through the same fencing/predecessor transaction. Original queue/score
versions remain available, and an already-open case remains pinned to its version.

## Verification

```text
python scripts/verify_scoring.py --connections-file secrets/docker_test_connections.json --with-mlflow --with-approver --approval-admin-file secrets/docker_admin_database_url --output-dir artifacts/phase8/new-verification
```

Only a dedicated `mule_test_*` database is accepted; the suite resets that database
and uses synthetic observations. The optional approval role provisioning uses a
protected loopback admin file only during test setup. Tests cover ties, empty and
singleton rankings, contribution sums, imputation/unseen values, authorization,
quarantine, holdout injection, NaN scores, missing chunks, retirement, stale
fences, concurrent requests, full-cohort correction and injected crashes at five
boundaries. Public rehearsal reports contain counts/flags only.

Local Windows results do not claim Linux/remote CI execution. Qualified scoring,
source certification, shared authentication and scheduling remain gated by their
respective data and later deployment phases. Phase 9 can wrap these services in
authenticated API routes without moving inference into request handlers.
