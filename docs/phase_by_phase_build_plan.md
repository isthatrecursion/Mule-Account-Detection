# Complete System Build Plan

**Project:** Explainable Mule Account Risk Ranking

**Prepared:** 2026-10-20

**Design authority:** [Complete System Architecture](../architecture/01_system_architecture.md)

**Data authority:** [Stage 9 verification and remediation](../eda/09_pre_architecture_verification_and_remediation.md)

**Purpose:** Translate the complete architecture into ordered implementation work. This plan adds no delivery deadline and makes no reduction in the agreed solution scope. The architecture remains the single design authority; this document specifies how to build and verify it.

**Detailed construction guide:** [System Architecture Roadmap](<../System Architecture Roadmap.md>) expands every numbered phase point into named files, concrete implementation procedures, and verification checks. Roadmap IDs such as `P05.03` map directly to this plan's phase 5, point 3.

## 1. Project Understanding and Current Starting Point

The product ingests versioned account-feature batches, validates their quality and provenance, uses a reproducible model bundle to rank records for investigation, explains the model's inputs within the available evidence, and supports an audited analyst review workflow. Training, serving, investigation outcomes, monitoring, and model approval form one traceable lifecycle.

The future transaction adapter adds durable ingestion, gap detection, event-time feature reconstruction, freshness states, and targeted reconciliation. The batch product can be built with today's extract; production claims about transaction-derived detection require a qualified event feed and validated feature definitions.

| Area | Evidence already present | Implementation still required |
|---|---|---|
| Data | 9,082 rows, 3,925 columns, 81 positives | Approved source contracts, stable entity identity, timestamps, representative cohorts |
| EDA | Stages 0–9, feature dictionary, 1,404-column exclusion register | Runtime validation and enforceable promotion gates |
| ML | Development-only verification script and saved OOF results | Reusable package, baseline, temporal evaluation path, frozen inference bundle |
| Application | Architecture and workflow requirements | PostgreSQL, FastAPI, Streamlit, case services, audit trail |
| Operations | Design targets and runbook requirements | Container stack, CI/CD, alerts, access controls, backup/restore |
| Delayed records | Architecture section 10 and acceptance requirements | Durable buffer, gap tracker, reconciliation, replay harness |

Saved metrics are evidence of the previous diagnostic run, not a new test performed while writing this plan. The script currently creates OOF reports; it does not save a deployable full-development preprocessing/model bundle. Packaging that bundle is a new task.

### Mandatory boundaries

1. All negatives are from Oct25 and positives are from other extraction months. Removing `F2230` cannot resolve this confounding. Current-model use remains restricted to research demonstrations.
2. The 1,817-row internal holdout stays excluded from training, tuning, demo scoring, and operational evaluation. The development subset or synthetic fixtures power demonstrations.
3. `Unnamed: 0` and the split register's `account_id` are historical row references, not verified banking identities. A research adapter must name that distinction explicitly.
4. Scores indicate review priority. Calibrated fraud probabilities require representative calibration data.
5. Feature IDs can be explained statistically. Business meanings require an approved dictionary.
6. Analyst dispositions are not automatically mature fraud labels. Label adjudication and maturity remain separate processes.
7. No phase introduces automatic account restrictions or report filing.
8. Security, lineage, tests, and auditability begin with the foundation and deepen through later phases.

## 2. Build Order and Completion Levels

| Phase | Outcome | Prerequisite |
|---:|---|---|
| 0 | Requirements, data requests, and measurable acceptance contract | Existing architecture and Stage 9 |
| 1 | Installable package, configuration, and CI skeleton | 0 |
| 2 | Versioned data, model, evidence, and event contracts | 0–1 |
| 3 | PostgreSQL schema, migrations, repositories, audit foundation | 1–2 |
| 4 | Durable batch ingestion, validation, quarantine | 2–3 |
| 5 | Reusable fold-safe feature pipeline | 1–2 and research input adapter from 4 |
| 6 | Reproducible training and evaluation | 4–5 |
| 7 | Model bundle, MLflow registry, approval and rollback | 3 and 6 |
| 8 | Idempotent scoring, explanations, atomic queue publication | 4–5 and 7 |
| 9 | FastAPI, authorized case workflow, feedback and export | 3 and 8 |
| 10 | Streamlit analyst workspace | 9 |
| 11 | Durable transaction buffering and reconciliation | 2–3 and 8; use fixtures until feed qualifies |
| 12 | Delayed-event correctness and performance evidence | 10–11 |
| 13 | Operational monitoring, drift and retraining triggers | Instrumentation from 1–12 |
| 14 | Hardened deployment, release, backup and recovery | 9–13 |
| 15 | Independent acceptance, shadow pilot, promotion and operation | 0–14 plus qualified data and organizational approval |

The data-owner work opened in phase 0 continues alongside engineering. Phases 1–14 can progress with appropriately labeled research inputs and synthetic events. Production validation in phase 15 cannot pass on the present extract.

Completion levels are explicit:

- **Engineering complete:** integrated software and recovery checks pass; outstanding source-data limits remain visible.
- **Research demonstration complete:** the development-only workflow and synthetic resilience replay are repeatable.
- **Shadow pilot approved:** qualified data, security controls, and model review permit operational observation.
- **Production approved:** representative validation, operating policy, security, recovery, and independent approval all pass.

## 3. Phase 0 — Freeze Requirements and Data Acceptance

**Goal:** Make the product's operating rules and external dependencies testable before implementing services.

### Steps

1. Read the architecture's requirements, data gates, risks, and acceptance criteria into a requirements register. Assign an identifier, owner, evidence artifact, and pass condition to each requirement.
2. Define the investigation unit: account at a snapshot cutoff. Separate `research_record_id`, verified `account_id`, batch identity, snapshot identity, and investigation case identity.
3. Define analyst roles and workflow: analyst, reviewer, model engineer, operator, auditor; queued, assigned, in review, reviewed, reopened. Store review conclusion separately from workflow state.
4. Specify queue policy: configurable K, deterministic tie rule, eligibility exclusions, refresh schedule, and capacity owner. K=25/50/100 are diagnostic examples until Operations approves capacity.
5. Convert architectural performance targets into benchmark definitions: 10,000 rows under 15 minutes, queue/case API p95 under 500 ms, and a 100,000-row capacity exercise. Record hardware, payload size, concurrency, warm/cold state, and failure budget; none is a measured result yet.
6. Open the external data request: stable pseudonymous ID, snapshot/event/availability cutoffs, label source and maturity, mixed-class time cohorts, dictionary, and source completeness evidence for future transactions. Give every missing item an owner and closure criterion.
7. Define research versus qualified-data behavior. A research model may be enabled only in the controlled research environment; it must not be promoted through the production approval path.
8. Define score freshness and incompleteness semantics, including an account with no prior complete score: show `UNAVAILABLE` rather than inventing a low-risk default.
9. Decide temporal evaluation policy before receiving new labels: train/tune/calibrate windows, gap/purge rules, and final acceptance release. Never repeatedly tune against a previously inspected acceptance cohort.
10. Create an acceptance evidence template covering data, ML, API/UI, resilience, authorization, recovery, and operator sign-off.

**Build artifacts:** `docs/requirements_and_acceptance.md`, `docs/data_request.md`, `config/review_policy.yaml`, role/action matrix, tracked unresolved decisions.

**Exit check:** Every architectural requirement has an owner and planned test. Missing business thresholds remain explicitly pending rather than being invented.

## 4. Phase 1 — Repository and Engineering Foundation

**Goal:** Establish one reproducible codebase for the API, jobs, pipeline, and dashboard.

### Steps

1. Preserve the existing dataset, split register, exclusions, verification script, and saved artifacts. Record hashes before refactoring so behavior can later be compared.
2. Create an installable `src/mule_detection` package with domain, application, persistence, ingestion, features, training, registry, scoring, explanations, reconciliation, monitoring, and API modules. Keep Streamlit in `ui/`.
3. Create `pyproject.toml` and a locked dependency set. Retain compatibility with the recorded benchmark environment initially; verify upgrades separately from the refactor.
4. Add typed environment configuration for paths, database, MLflow, model policy, job cadence, retention, and input limits. Separate local, test, staging, and controlled deployments.
5. Add `.env.example` with placeholders; exclude secrets, local databases, generated runs, model binaries, and sensitive fixtures from ordinary Git tracking.
6. Define application error types and stable error codes, plus structured logging fields for request/job/batch/model IDs. Redact sensitive rows and analyst note text.
7. Create test directories for contracts, unit behavior, PostgreSQL integration, smoke flows, and resilience. All automated CI fixtures must be synthetic or explicitly approved.
8. Add formatting, lint/type checks, and focused tests to CI. A fresh checkout must install the package without access to the financial dataset.
9. Define the intended command surface for validate, train, score, replay, and health jobs. Implement commands as thin entry points calling application services.
10. Add correlation IDs and clock injection to service interfaces now; controlled time will be needed for deterministic event replay later.

**Build artifacts:** package skeleton, lockfile, configuration module, CI workflow, logging/error conventions, synthetic fixtures.

**Exit check:** Package imports and fixture tests run from a clean checkout. No database password or raw account data appears in logs or CI output.

## 5. Phase 2 — Data and Service Contracts

**Goal:** Make every boundary explicit before joining components.

### Steps

1. Implement versioned batch manifest models: batch/source/schema IDs, observation cutoff, timestamp timezone, expected counts, content hash, owner, and feature-policy version.
2. Define the qualified account snapshot contract with a stable account key and unique `(account_id, snapshot_at, source)` identity. Declare merge behavior if several sources contribute to one snapshot.
3. Build a `research_v1` adapter for the existing CSV. Keep a namespaced research record key derived from dataset identity and original row reference; never label it a verified account identity or use it as a predictor.
4. Define schema/type/missing-value rules for required, optional, forbidden-as-predictor, and metadata fields. A target column may be allowed in a labeled training file but must be separated from the feature frame.
5. Separate permanent policy exclusions from learned structural exclusions. Record the 1,404-column historical register for audit; do not globally apply EDA-derived feature selection to new evaluation partitions.
6. Define the feature dictionary contract: ID, certified name/status, unit, source, window, availability time, sensitivity, and version. Provisional raw categories do not imply certified definitions.
7. Define label contracts with event date, adjudication status, source, maturity date, and as-of cutoff. Specify how corrections supersede older labels without rewriting history.
8. Define model bundle and scoring output contracts: model/pipeline signatures, policy hash, immutable version, research status, runtime versions, score direction, rank, percentile, freshness, and evidence version.
9. Define event contracts including source, partition, sequence epoch, event ID, event time, ingestion time, correction linkage, and a completeness manifest. Specify producer sequence resets and clock-skew handling.
10. Define evidence, review, audit, and job-state contracts. Separate processing state, data freshness, label status, and model approval status rather than overloading a single status field.
11. Add contract fixtures for absent IDs, wrong types, reordered columns, unknown schema, malformed timestamps, target contamination, conflicting metadata, and repeated research keys.

**Build artifacts:** `contracts/`, typed domain models, versioned policy configuration, research adapter, contract error catalog.

**Exit check:** Valid fixtures round-trip; incompatible files fail with stable codes. Unknown provenance cannot be converted into qualified data through a configuration shortcut.

## 6. Phase 3 — PostgreSQL, Repositories and Audit Foundation

**Goal:** Persist coherent, versioned state before building workflow services.

### Steps

1. Start PostgreSQL locally through Compose and create separate operational and MLflow databases/roles. Only local development binds may be exposed; shared access goes through the approved network boundary.
2. Add migrations for datasets, batches, validation reports, model references/approvals, jobs, score runs, score versions, evidence, queue snapshots, cases, review events, labels, audit events, and outbox records.
3. Introduce keys and unique constraints for batch content identity, run idempotency, score identity, review request identity, and event identity. Use foreign keys to enforce lineage. PostgreSQL provides database-enforced unique and referential constraints; use them alongside application checks. [PostgreSQL constraint documentation](https://www.postgresql.org/docs/current/ddl-constraints.html).
4. Keep wide raw feature frames in immutable files/artifacts, referenced by checksum and schema, rather than copying thousands of columns into every case row.
5. Implement repository interfaces and transaction boundaries; route application services through these interfaces rather than embedding SQL in routes or UI pages.
6. Implement the audit writer. Append actor, action, entity/version, timestamp, correlation ID, reason, and safe metadata in the same transaction as each business write.
7. Restrict normal application roles from updating/deleting audit rows. Document that database administrators still require separate controls; append-only application behavior alone is not tamper-proof storage.
8. Add optimistic version checks for analyst case updates and worker leases/attempt records for jobs. A stale client should receive a conflict rather than overwrite another review.
9. Add indexes for queue sort/filter, account history, batch lookup, run state, event sequence and freshness queries. Test representative query plans once fixtures grow.
10. Test migration from an empty database, duplicate requests, concurrent case updates, and rollback after an injected failure between score and audit writes.

**Build artifacts:** migrations, entity/repository definitions, unit-of-work helper, audit/outbox foundation, PostgreSQL integration tests.

**Exit check:** A failed transaction leaves neither orphan scores nor unaudited dispositions. Retrying a committed request cannot create duplicate business records.

## 7. Phase 4 — Batch Intake, Validation and Quarantine

**Goal:** Turn raw input into an immutable accepted batch or an inspectable failure.

### Steps

1. Implement file/path intake with size and format limits. Write uploads into a controlled staging directory; never trust user paths or filenames as storage locations.
2. Hash raw content while ingesting and reconcile actual rows/schema/checksum with the manifest. Register a batch request before starting long processing.
3. Persist raw input immutably and use generated storage keys. If publication fails, retain a recoverable staging record and clean it through an explicit recovery job.
4. Run contract validation: row identity, duplicate snapshots, timestamp ordering, column types, required features, source version, and label/feature separation.
5. Apply research partition filtering before any demo/train/score feature frame is emitted. Preserve holdout membership as a restricted reference; never silently combine it with development records.
6. Generate quality summaries: missingness, unknown categories, zero/constant patterns, source/time coverage, label maturity, and cohort composition where labels are authorized.
7. Classify issues into hard failure, warning, and promotion-only blocker. The current cohort confounding blocks qualified promotion even if research ingestion succeeds.
8. Save validation findings and accepted/quarantined status with rule versions. Scoring accepts only published, compatible accepted batches.
9. Implement duplicate intake as an idempotent lookup; require an explicit replay identity for a deliberate rerun. Conflicting manifests for the same content need investigation.
10. Provide a CLI validation report and safe API-readable summary. Add failure tests for corrupted files, count mismatch, partial writes, missing metadata, and invalid snapshots.

**Build artifacts:** intake service, CSV/Parquet loader, validators, immutable storage adapter, quarantine reports, validation command.

**Exit check:** A valid research development batch is reproducible and traceable; an invalid batch cannot reach the scorer; re-ingestion cannot silently replace historical raw data.

## 8. Phase 5 — Fold-Safe Feature Pipeline

**Goal:** Reuse and harden the existing verification logic for training and inference.

### Steps

1. Extract `FoldSafePreprocessor` into the package while preserving the old verification script as a reference entry point. Separate refactoring from model or preprocessing changes.
2. Preserve the distinction already present in the script: its benchmark removes hard-blocklisted fields and discovers structural exclusions within each training fold; its 2,521-column audit describes the historical register. These feature counts are not interchangeable.
3. Implement cloneable fit/transform components for policy exclusion, approved semantic cleanup, constant/high-missingness/duplicate discovery, imputation, categorical encoding, and final signature checking.
4. Move date and age rules into explicit versioned configuration. Preserve legacy diagnostic behavior under its old version; require certified semantics before those rules enter a qualified pipeline.
5. Fit medians, category sets, pruning, scaling for logistic regression, peer-reference distributions, and any supervised selection only on the appropriate training partition. Pipelines help enforce this separation. [scikit-learn leakage guidance](https://scikit-learn.org/stable/common_pitfalls).
6. Preserve missingness as a data-quality signal. Never invent missing transactions, set absent source data to zero, or add missingness indicators without evaluating their cohort-proxy risk.
7. Preserve feature ordering and mapping from encoded columns to raw feature IDs. Score-time reordered columns must be normalized by name; missing required features must fail.
8. Save selected raw/transformed features, fitted state, policy hash, data signature, and reference statistics with the pipeline. `transform()` must never discover a new feature subset.
9. Add tests that modify only validation data and prove training medians, categories, and feature selection do not change. Test unknown categories, all-missing training columns, forbidden predictors, and save/load parity.
10. Reproduce the legacy benchmark in a separate output directory after refactoring. Compare metrics and selected manifests within a documented environment-dependent tolerance; investigate changes before moving on.

**Build artifacts:** reusable transformers, serialized feature pipeline, signatures/manifests, benchmark parity report, leakage-boundary tests.

**Exit check:** Inference only transforms through a frozen pipeline. No validation/acceptance row influences a fitted decision.

## 9. Phase 6 — Training, Evaluation and Label Controls

**Goal:** Produce reproducible candidate models with honest evidence.

### Steps

1. Implement two explicit evaluation modes: development-only stratified diagnostics for the current extract, and qualified grouped temporal evaluation for representative future data. Reject attempts to rename the first mode as temporal validation.
2. Filter labels by the recorded maturity/adjudication cutoff. Separate unresolved, immature, corrected, and assumed-negative records.
3. Implement split generators and save row/account/group/time membership. For qualified data, enforce the architecture's account/entity separation and purge overlapping windows where required; agree any future alternative returning-account task separately.
4. Build regularized logistic regression and LightGBM under the same folds and comparable feature contracts. Tune only on development folds; keep the current model configuration as the reference, not an assumed optimum.
5. Fit every learned transformation inside the fold. Use nested or reserved tuning partitions when configuration is selected; never choose hyperparameters from final acceptance scores.
6. Generate complete OOF predictions, fold-level metrics/counts, feature manifests, random seeds, and train/validation sizes. Store source/month predictability and missingness-risk probes alongside ranking results.
7. Calculate AP, secondary ROC-AUC, P@K/R@K/lift, and uncertainty with account/group-aware resampling where appropriate. Document that pooled cross-fold top-K can be sensitive to differing model score scales.
8. Evaluate demographic/proxy ablations and subgroup selection burden with counts and intervals. Treat tiny/confounded samples as inconclusive.
9. Calibrate only when representative calibration data exists and the calibration fit is separated from final evaluation. Otherwise publish raw ranking scores and percentiles without a fraud-probability label.
10. Save candidate reports, label/data fingerprints, code revision or source hash, dependency lock hash, splits, predictions, limitations, and failed gates. Do not optimize to reproduce historical headline numbers.

**Build artifacts:** training/evaluation services, split policies, model comparison report, OOF artifacts, model-card draft, evaluation command.

**Exit check:** One config/data fingerprint reproduces a diagnostic run; no holdout is scored; current candidates remain research-only regardless of AP.

## 10. Phase 7 — Frozen Model Bundles, Registry and Approval

**Goal:** Turn an experiment into a controlled, loadable inference artifact.

### Steps

1. After selecting configuration with development diagnostics, fit one final research model/pipeline on the authorized development partition. This final fit produces demo scores, not unbiased evaluation metrics.
2. Package preprocessing, estimator, feature signatures, reference statistics, model card, dependency manifest, policy version, training lineage, and checksums as one immutable bundle.
3. Validate trusted bundle loading and prediction round-trip on fixed fixtures. Never accept arbitrary uploaded serialized Python models from analysts.
4. Start MLflow tracking against its dedicated database/artifact location. Log runs, metrics, data fingerprints, and the entire bundle, then register immutable model versions.
5. Use aliases/tags for deployment references and validation status. Keep project approval states in an explicit approval record; changing a registry tag alone must not authorize scoring. [MLflow registry workflow](https://www.mlflow.org/docs/latest/ml/model-registry/workflow/).
6. Separate research demo, candidate, approved-for-shadow, approved-for-pilot, rejected, and retired statuses. Give the training identity permission to create candidates, never to approve itself.
7. Implement environment-specific promotion checks: representative cohort, dictionary/identity/label approvals, evaluation thresholds, model review and access authorization. A research bundle cannot cross this boundary.
8. Resolve an active alias to an immutable version once at job start. Save that resolved version in the run so a mid-job alias change cannot mix models.
9. Implement rollback to a previously approved compatible bundle. Rollback creates an audited deployment event; past score versions retain their original model IDs.
10. Test unapproved model rejection, corrupt checksum, wrong schema, missing dependencies, unauthorized promotion, alias changes during scoring, and rollback.

**Build artifacts:** bundle builder/loader, MLflow integration, approval service, model-policy checks, rollback command and runbook.

**Exit check:** The scorer can load only a compatible bundle approved for that environment. Every score can be traced to immutable preprocessing and model artifacts.

## 11. Phase 8 — Scoring, Evidence and Queue Publication

**Goal:** Create a complete ranked queue without partial or duplicated publication.

### Steps

1. Implement a scoring request keyed by accepted batch, immutable model version, feature-policy hash, scoring config, and explicit replay identity. Acquire a job lease and record attempts.
2. Verify batch hashes, accepted status, schema compatibility, model authorization, feature cutoff and research restrictions before loading data.
3. Transform and score in bounded chunks without refitting. Persist intermediate results under an unpublished run so failure/retry can safely resume or restart.
4. Reject nonfinite scores, missing rows, duplicated snapshot identities, and mismatched output counts. Set deterministic tie ordering using stable record keys.
5. Rank the full eligible cohort and calculate its percentile definition explicitly. Materialize queue membership from configurable K and preserve the cohort/version used to compute it.
6. Generate top signed contributions for selected cases, preserving base value and contribution scale. Verify contribution sums against the corresponding model output; a raw-margin explanation is not a probability decomposition.
7. Link encoded contributions back to raw feature IDs with observed value, training-reference percentile/category information, and dictionary status. Business prose is permitted only for certified mappings.
8. Store score/evidence lineage and freshness state. On a missing prior assessment, return unavailable; never fall back to zero risk.
9. Publish by atomically changing a completed-run/queue-version pointer after all row counts, evidence and audit checks pass. Large chunk writes occur before this short transaction.
10. Test crash before publication, crash after commit, retry, model mismatch, deterministic ties, evidence integrity, no holdout rows, and top-K correctness.
11. For future single-account reconciliation, update the affected score and recompute the queue ordering/percentiles over the same eligible universe. Account-local score changes can move other accounts' ranks even when their own features are unchanged.

**Build artifacts:** scoring worker, evidence builder, versioned queue store, publication service, scoring command and retry tests.

**Exit check:** A reader sees either the old complete queue or the new complete queue. A repeated job cannot duplicate scores or mix evidence from different versions.

## 12. Phase 9 — FastAPI and Analyst Workflow

**Goal:** Expose an authorized application boundary around published results and case actions.

### Steps

1. Build an application factory, typed request/response schemas, dependency injection, safe errors, request IDs, liveness/readiness checks, and an OpenAPI contract.
2. Add batch/job status and validation-summary reads; restrict intake and job submission to authorized roles. Heavy validation/training/scoring runs in the worker, not inside dashboard requests.
3. Implement paginated queue and case reads bound to a published queue version. Use stable ordering so a reconciliation cannot silently shift the next page under a reviewer.
4. Implement evidence/history/model-provenance endpoints and expose freshness, complete-as-of, source coverage, and research status.
5. Implement case assignment, notes, disposition and reopen actions through application services. Require idempotency keys and an expected case version for writes.
6. Persist each action and audit event transactionally. Keep workflow disposition separate from adjudicated/mature training labels.
7. Add a label-ingestion boundary for approved outcome corrections; preserve source/maturity and selection bias. Unreviewed accounts are not automatically confirmed negatives.
8. Enforce authorization for every route and individual case/export access. Validate identity from trusted credentials, not a caller-supplied actor header. FastAPI's scope mechanism can support API permission enforcement. [FastAPI OAuth2 scopes](https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/).
9. Implement authorized export from an explicit snapshot/version with metadata and access audit. Escape spreadsheet formula injection and minimize exported fields.
10. Test role/action denials, unauthorized direct object access, stale writes, duplicate submissions, note validation, queue pagination during updates, and safe error responses.

**Build artifacts:** API routers, application services, role policy, endpoint contract, API integration tests.

**Exit check:** A reviewer can complete a case through the API with audit evidence; unauthorized callers cannot bypass the UI to alter data.

## 13. Phase 10 — Streamlit Analyst Workspace

**Goal:** Make the operating workflow understandable without exposing unsupported claims.

### Steps

1. Build a thin API client and role-aware navigation. Streamlit reads/writes through FastAPI; it does not query PostgreSQL or load the model directly.
2. Build an intake/operations page showing batch identity, accepted/quarantined status, validation reasons, run progress and authorized retry actions.
3. Build the queue page with batch/version selector, rank, percentile, raw score label, assigned reviewer, workflow state, freshness and model version. Add server-side pagination and filters.
4. Build case detail with observed inputs, top positive/negative contributions, reference context, dictionary status, snapshot cutoff, and complete-as-of time. Avoid causal or legal conclusions.
5. Add notes, assignment and disposition forms with explicit submission and conflict handling. A page rerun must not resend a write with a new idempotency key.
6. Add immutable history for assessments, corrections, case events and model versions. Let a reviewer recognize that their original review used an older score snapshot.
7. Show complete, buffering, stale, corrected and unavailable states. Retaining an old complete score must visibly disclose its age; availability is not a claim of current accuracy.
8. Cache read views by data/version and relevant authorization context, with bounded TTL. Do not share user-specific case data through an unscoped global cache.
9. Wire login to the agreed identity flow and keep authorization in the API. Streamlit documents OIDC authentication, but identity login is distinct from authorization. [Streamlit authentication](https://docs.streamlit.io/develop/concepts/connections/authentication).
10. Exercise the whole journey: valid batch to queue, case evidence, saved review, history and export; then repeat with quarantine, API outage, stale data and concurrent updates.

**Build artifacts:** queue, case, operations and history pages; API client; walkthrough/smoke checks.

**Exit check:** An analyst can review a case without direct database/model access, understand data freshness, and recover safely from stale-page conflicts.

## 14. Phase 11 — Durable Event Buffer and Reconciliation

**Goal:** Implement architecture section 10 while preserving the existing batch and dashboard paths.

### Steps

1. Implement an event-source interface and deterministic synthetic ledger first. Use explicit event definitions unrelated to anonymous F-columns unless a certified feature mapping exists.
2. Add migrations for raw event identity/payload reference, source offsets/epochs, sequence gaps, partition heartbeats, impacted windows, reconciliation jobs, feature versions and freshness state.
3. Persist accepted raw events before acknowledgement and deduplicate by source/event identity. Conflicting payloads for one identity must quarantine/escalate rather than silently overwrite.
4. Track the highest contiguous sequence separately from maximum observed event time. Handle resets/epochs, clock skew and count manifests; time passing alone cannot prove completeness.
5. Map gaps to the dependent windows. If a missing event's account is unknown, conservatively mark all accounts depending on the affected source partition/window incomplete until scope is proven; account-only isolation requires producer evidence.
6. Send proven complete input to the fast path and incomplete windows to a durable buffer. Ten minutes is an allowed-lateness policy, not a deletion TTL; retain unresolved records according to recovery/retention policy.
7. Implement per-source watermarks bounded by source completeness. A multi-source feature window closes only when all required sources satisfy its cutoff.
8. Preserve the last complete score and its timestamp. New accounts with no complete baseline show unavailable. Any provisional escalation is separately marked and cannot lower the complete assessment or trigger automatic action.
9. Rebuild impacted feature windows in deterministic event-time/event-ID order, including corrections, reversals and window boundary effects. Recompute all dependent features; late data may affect subsequent rolling windows too.
10. Before scoring, verify the reconstructed feature signature matches the model. A synthetic event fixture can test reconciliation with a deterministic test scorer; it cannot prove the current anonymous-feature classifier handles transactions.
11. Atomically commit feature/score version, freshness, audit and outbox publication. Use source checkpoints plus idempotent writes; do not assume broker delivery guarantees automatically extend to PostgreSQL. [Kafka delivery design](https://kafka.apache.org/design/).
12. Reconcile rank/percentile and publish a new queue snapshot after corrected scores. Use separate concurrency/resource limits so reconciliation cannot starve ordinary batches or API reads.
13. Implement retries, dead letters, backpressure, expired job leases, restart replay, bounded buffer capacity and operator correction/reopen procedures.

**Build artifacts:** event adapter, durable buffer/gap state, feature-window builder, reconciliation service, freshness service, failure-recovery fixtures.

**Exit check:** Duplicate, reversed, out-of-order and late events converge to the same complete feature state; crashes preserve replayability; unknown source scope is never reported complete.

## 15. Phase 12 — Ten-Minute Replay and Performance Validation

**Goal:** Produce evidence for the delay requirement instead of assuming that buffering guarantees accuracy.

### Steps

1. Specify the replay interval, account population, feature windows, eligible cohort, scoring threshold/band or K, score tolerance epsilon, affected fractions, throughput, hardware and measurement rules before testing.
2. Build a virtual event clock for correctness tests so a ten-minute delay can be simulated quickly. Use actual wall-clock replay/load trials separately for latency and throughput claims.
3. Run a complete timely reference and persist per-window feature vectors, raw scores, bands, queue snapshots, source coverage and timing samples.
4. Inject exact ten-minute delays across multiple severity profiles and source scopes. Include high-risk/high-value events, bursts, cutoff events, duplicates, reversals, missing heartbeats and restarts; do not make the 95% target trivial by delaying only a tiny easy subset.
5. Compare assessments during the outage as well as after reconciliation. A final match does not demonstrate unchanged accuracy during the ten minutes when decisive evidence was unavailable.
6. Measure final consistency on all eligible accounts and separately on affected accounts, plus high-risk/positive subgroups. A good aggregate result must not hide concentrated failure among delayed accounts.
7. Require at least 95% final assessment consistency and top-K overlap under the declared cohort. Aim for identical deterministic final features/scores; investigate any mismatch rather than accepting unexplained errors within the tolerance.
8. Measure p95 compute overhead for affected accounts including all ingestion, initial processing, reconciliation and rescore work attributed to them. Compare equal work boundaries; do not measure only the last rescore while omitting earlier attempts. Exclude injected source waiting, but report waiting/queueing separately.
9. Also measure unaffected-path regression, API response latency during recovery, full recovery lag, missed deadlines, retained/duplicate event counts, and audit coverage. Repeat interleaved reference/delay runs to quantify noise around the 5% target.
10. Preserve the architecture's <=5% affected-compute and unaffected-regression gates, zero lost/duplicate effects, zero partial-data downgrades, and complete correction lineage. Mark any failed gate as unresolved.
11. Treat eleven-minute p95 publication as a workload-dependent target: ten-minute source delay plus reconciliation cadence leaves limited compute/queue budget. A one-minute poll alone does not guarantee it; arrival-triggered processing may be needed.
12. With mature outcomes and qualified event features, additionally evaluate AP, P@K/R@K and error changes. Synthetic replay proves software invariants, not real fraud accuracy.

**Build artifacts:** replay command, fault profiles, correctness/performance reports, timing traces, failure examples, unresolved-gate list.

**Exit check:** Results state what was measured, with denominator, epsilon, volume, hardware, repetitions and affected-account coverage. Neither the 95% nor 5% requirement is reported as passed without evidence. During-outage accuracy remains a separate data-dependent requirement.

## 16. Phase 13 — Monitoring, Drift and Retraining Workflow

**Goal:** Detect broken data, stale assessments, operational failures and model degradation.

### Steps

1. Complete structured instrumentation for ingestion, validation, training, scoring, API, reviews and reconciliation. Correlation IDs live in logs/traces; avoid account/run IDs as unbounded metric labels.
2. Add job status, duration, last success, retries, accepted/rejected rows and error counters. Alert on a missed successful batch, not only on an explicit crash.
3. Expose API rate, errors and latency, plus database connection health and worker saturation. Instrument paths before choosing alert thresholds.
4. Add source arrival lag, watermark/heartbeat age, sequence gaps, buffer depth, stale/unavailable score count, reconciliation duration and correction frequency.
5. Compare schema, missingness, categories and score distributions to a versioned reference with comparable source/time cohorts. Store statistics and thresholds; distinguish severe contract violations from investigable warnings.
6. Build Grafana views for pipeline health, data freshness, validation findings, model version, queue state and delayed-data recovery. Do not put raw sensitive account records in infrastructure dashboards.
7. Add delayed-label performance joins using maturity and observation cutoffs. Keep reviewed-only yield separate from bank-wide prevalence/recall; analyst selection makes reviewed data nonrandom.
8. Create a retraining proposal when approved triggers fire: mature new labels, validated drift, performance decline or changed definitions. Retraining always produces a candidate and follows phases 6–7 again.
9. Define reference/acceptance dataset release policies so repeated retraining does not tune against the same exposed acceptance labels.
10. Test failed/stale jobs, broken source heartbeat, drift breach and alert recovery. Confirm an operator can locate the affected batch/model from safe logs.

**Build artifacts:** metrics, versioned drift reports, Grafana dashboards, alerts, evaluation trigger service, retraining proposal template.

**Exit check:** Operators can detect and investigate stale or failed scoring; drift never silently approves a model or retrains/publishes without review.

## 17. Phase 14 — Deployment, Security and Recovery

**Goal:** Make the integrated system deployable and recoverable on the architecture's single-host foundation.

### Steps

1. Build versioned images for API/UI/jobs and Compose services for PostgreSQL, MLflow, reverse proxy and monitoring. Reuse the worker image for validation/training/scoring/reconciliation commands.
2. Configure non-root runtime identities, private networks, health/readiness checks, bounded memory/CPU and persistent encrypted storage. Avoid heavy training contention with the API/scoring schedule.
3. Put shared access behind TLS and organizational identity. Validate the end-to-end UI-to-API identity flow; strip spoofable proxy headers and enforce roles in the API.
4. Restrict MLflow/artifact access, model promotion, exports, case actions and operational retries. Use separate service/database identities and a documented secret rotation procedure.
5. Add durable scheduling, job locks, backoff and startup recovery. Store in-flight status in PostgreSQL rather than process memory; distinguish liveness from readiness.
6. Implement CI validation of format/types, contracts, leakage boundaries, PostgreSQL integration, API authorization and synthetic smoke/replay. Build/scan immutable image digests and retain the deployment manifest.
7. Rehearse migrations against staging data and prepare forward-fix/rollback steps. Promote the same verified image digest; model approvals remain independent from application releases.
8. Back up PostgreSQL, manifests/raw inputs, model bundles, encryption configuration and required source checkpoints with a consistent recovery plan. Verify checksums and retention/access policy.
9. Restore into a clean environment and replay an interrupted scoring/reconciliation run. Check audit continuity, model availability, published queue consistency and event deduplication.
10. Load-test the declared 10,000-row target and 100,000-row capacity case, API concurrency, and delay recovery concurrently. Record actual results; data scale alone does not establish an SLA.
11. Define RPO/RTO and availability goals with the owner. If contractual resilience requires multiple hosts, implement the architecture's managed/replicated storage path before approval.
12. Write startup, shutdown, failed batch, source outage, rollback, restore, export/retention, incident and key-rotation runbooks. Run an operator rehearsal.

**Build artifacts:** Compose/deployment configuration, CI/CD, image manifest, security/access report, backup/restore evidence, capacity report, runbooks.

**Exit check:** A clean approved environment can start and restore the stack from controlled artifacts; unauthorized access, interrupted jobs and source replay have tested outcomes.

## 18. Phase 15 — Acceptance, Shadow Pilot and Ongoing Operation

**Goal:** Decide what the system is authorized to do using independent evidence.

### Steps

1. Review all architectural acceptance criteria against the evidence index below. Mark passed, failed or blocked, with links to actual reports; code existence is not acceptance evidence.
2. Demonstrate the full research journey: accepted development batch, frozen bundle, published queue, case evidence, disposition, audit, monitoring and corrected-event fixture. Keep research status and source limitations visible.
3. Resolve phase 0 external data requests. Confirm stable identity, approved definitions, same-window mature classes, feature availability and label cutoffs before qualified model evaluation.
4. Freeze a new representative later-period acceptance cohort before analysis. Use a separate tuning/calibration process; independent final evaluation must not become iterative optimization.
5. Complete model-risk review with ranking/calibration evidence, uncertainty, subgroup burden, explanation validity and label-selection limitations. Sign operational K/thresholds and escalation policy.
6. Complete security, deployment/recovery, retention and authorized-user acceptance. Require a genuine approval owner for each organizational gate; this plan does not confer approval.
7. Start a controlled shadow pilot only after those prerequisites pass. Record recommendations and mature outcomes without assuming scores justify adverse action.
8. Measure analyst workload, review time, yield, overturn/reopen rate, data freshness, delayed corrections and operational failures. Keep prospective denominators and label maturity consistent.
9. Evaluate the delay requirement on real representative events and approved features. If accuracy during the ten-minute blind interval is mandatory, measure that specifically; stale-score availability cannot guarantee it.
10. Promote only if all required data, model, security, operational and delayed-event gates pass. Otherwise retain the achieved research/engineering completion level and record the blocker.
11. Operate through monitored releases, candidate retraining, human approval, rollback and periodic restore/security rehearsals. Keep application version, active model and source contracts independently versioned.

**Build artifacts:** acceptance dossier, approval records, shadow-pilot protocol/results, model card, operating handbook, production decision record.

**Exit check:** The deployment claim matches the evidence. Production-model approval stays blocked while the current confounded extract is the only predictive validation source.

## 19. Target Repository Structure

The entries below are planned outputs, not a claim that implementation files already exist.

```text
architecture/01_system_architecture.md       # Sole architecture design authority
docs/
  phase_by_phase_build_plan.md
  requirements_and_acceptance.md
  data_request.md
  runbooks/
  acceptance/
config/                                    # Feature, model, review, monitor policies
contracts/                                 # Versioned external and bundle schemas
src/mule_detection/
  domain/                                  # Contracts, identities, states, policies
  application/                             # Transactional use cases and services
  persistence/                             # Repositories, unit of work, audit/outbox
  ingestion/                               # Batch/event intake and validation
  features/                                # Fit/transform and point-in-time builders
  training/                                # Splits, candidates, evaluation, labels
  registry/                                # Bundles, approvals, immutable references
  scoring/                                 # Jobs, inference, ranking, publication
  explanations/                            # Contributions and dictionary policy
  reconciliation/                          # Gaps, watermarks, windows, corrections
  monitoring/                              # Quality, drift, delayed performance
  api/                                     # Routes, schemas, auth, dependencies
  cli.py                                   # Intended job entry point
ui/                                        # Streamlit API client and pages
migrations/                                # PostgreSQL schema evolution
tests/
  contracts/
  unit/
  integration/
  resilience/
  fixtures/                                # Synthetic or approved minimal inputs
scripts/pre_architecture_verification.py    # Preserve as reference wrapper
eda/                                       # Existing evidence and registers
artifacts/                                 # Existing reports; controlled generated outputs
docker/
compose.yaml
pyproject.toml
<dependency-lockfile>
.github/workflows/
```

### Intended command surface

These are proposed interfaces to implement, not currently runnable commands:

```text
python -m mule_detection.cli validate-batch --manifest <manifest>
python -m mule_detection.cli train --config <config> --mode research
python -m mule_detection.cli evaluate --run-id <run-id>
python -m mule_detection.cli score --batch-id <batch-id> --model-version <version>
python -m mule_detection.cli reconcile --source <source-id>
python -m mule_detection.cli replay --scenario <scenario-config>
python -m mule_detection.cli health
```

The existing reference command is `python scripts/pre_architecture_verification.py --benchmark`. Future parity checks must write to a new output directory rather than overwriting canonical evidence without review.

## 20. Architecture-to-Implementation Traceability

| Architecture area | Build phases | Required evidence |
|---|---|---|
| Requirements and EDA boundaries | 0, 2, 6, 15 | Requirements register, research restrictions, data qualification decision |
| Ingestion, contracts and quarantine | 2–4 | Valid/invalid intake reports, immutable storage, replay idempotency |
| Feature pipeline and fold safety | 5–6 | Fit-boundary tests, reference parity, split and feature manifests |
| Model tracking, registry and promotion | 6–7 | Reproducible runs, trusted bundle, approval denial and rollback tests |
| Batch inference and evidence | 8 | Complete atomic queue, lineage, contribution tests, retry recovery |
| PostgreSQL, API and review/audit | 3, 9 | Constraint/concurrency tests, role checks, audit completeness |
| Streamlit analyst experience | 10 | End-to-end walkthrough including stale/unavailable states |
| Delayed/missing transactions | 11–12 | Gap/replay correctness, affected-cohort metrics, measured timing |
| Monitoring, drift and retraining | 13 | Alerts exercised, delayed-label joins, no self-promotion |
| Deployment, security and scalability | 1, 9, 14 | Reproducible release, security review, load and recovery reports |
| Production/shadow approval | 15 | Qualified data, independent acceptance, explicit approval record |

### Mapping the architecture's twelve acceptance criteria

| Criterion | Primary phase(s) |
|---:|---|
| 1. Clean-machine deployment | 1, 14 |
| 2. Quarantine incompatible batches | 2, 4 |
| 3. Reproducible training | 5–7 |
| 4. No fitting on validation/acceptance | 5–6 |
| 5. Idempotent, versioned scoring | 3, 7–8 |
| 6. Audited analyst disposition | 3, 9–10 |
| 7. Evidence-limited explanations | 2, 8, 10 |
| 8. No automatic freeze/block/report endpoint | 0, 9, 15 |
| 9. Backup and restore | 14 |
| 10. Stage 9 production promotion gate | 0, 7, 15 |
| 11. Transaction completeness enforcement | 11 |
| 12. Measured delay consistency/overhead | 12, 15 |

## 21. Execution Rules

1. Work on one demonstrable phase outcome at a time; finish its acceptance checks before widening scope.
2. Implement the domain contract before its persistence/API/UI adapters.
3. Use deterministic fixtures for engineering tests and real qualified data for predictive claims.
4. Record newly discovered design changes in the architecture; keep implementation progress in this plan's evidence register.
5. Do not invent team capacity or a fixed finish date. The architecture's earlier one-developer 8–10-week assumption is planning context, not an estimate for completing every external approval and future event-feed dependency.
6. Track implementation in [the evidence register](acceptance/roadmap_status.csv). Phases 0–3 now have specification/engineering evidence; see the [Phase 3 handoff](acceptance/phase3_readiness.md). Phase 4 is the next engineering phase. Owner agreement, external data qualification, remote CI and deployment/operational acceptance remain separate pending gates.
