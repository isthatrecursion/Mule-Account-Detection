# System Architecture Roadmap

**Project:** Explainable Mule Account Risk Ranking  
**Prepared:** 2026-10-20  
**Architecture:** [Complete System Architecture](architecture/01_system_architecture.md)  
**Phase index:** [Phase-by-phase build plan](docs/phase_by_phase_build_plan.md)  
**Data authority:** [Stage 9 verification and remediation](eda/09_pre_architecture_verification_and_remediation.md)

## Read this before implementing

This is an implementation manual for all 16 phases and all 170 numbered points in the phase plan. `P05.03` means phase 5, point 3. Each point identifies the files to write, the actual implementation procedure, and a check that demonstrates the intended behavior. Follow point order within a phase, except where a prerequisite explicitly points ahead.

This document specifies future implementation. It does not claim that the package, commands, services, tests, migrations, or example outputs already exist. Code excerpts illustrate interfaces or critical algorithms; they are not a complete application. Names such as `publish_queue()` are project functions to implement, not APIs supplied by a third-party library. Shell commands are instructions for the later build and were not executed to implement the application while preparing this roadmap.

The architecture remains the design authority. This roadmap expands its decisions; it adds no delivery deadline. PowerShell commands assume the working directory is `C:\Users\omkud\Mule Account Detection`. Use an approved local machine for financial data and synthetic fixtures in CI.

**Path convention:** source-module shorthand such as `domain/contracts/batch.py`, `application/review_service.py`, `api/app.py`, or `features/pipeline.py` means that path under `src/mule_detection/`. Paths beginning with `src/`, `config/`, `contracts/`, `docs/`, `docker/`, `ui/`, `tests/`, `scripts/`, `migrations/`, `.github/`, or root filenames are repository-relative as written. Keep generated data/artifacts outside the installed source package.

### Navigation

- [Phase 0 — Requirements and data acceptance](#phase-0--requirements-and-data-acceptance)
- [Phase 1 — Package, configuration, and CI foundation](#phase-1--package-configuration-and-ci-foundation)
- [Phase 2 — Contracts and boundary schemas](#phase-2--contracts-and-boundary-schemas)
- [Phase 3 — PostgreSQL, migrations, and transactional persistence](#phase-3--postgresql-migrations-and-transactional-persistence)
- [Phase 4 — Durable batch intake, validation, and quarantine](#phase-4--durable-batch-intake-validation-and-quarantine)
- [Phase 5 — Reusable feature pipeline](#phase-5--reusable-feature-pipeline)
- [Phase 6 — Training, splits, evaluation, and labels](#phase-6--training-splits-evaluation-and-labels)
- [Phase 7 — Model bundle, registry, approval, and rollback](#phase-7--model-bundle-registry-approval-and-rollback)
- [Phase 8 — Scoring, explanations, and atomic queue publication](#phase-8--scoring-explanations-and-atomic-queue-publication)
- [Phase 9 — FastAPI and analyst case services](#phase-9--fastapi-and-analyst-case-services)
- [Phase 10 — Streamlit analyst workspace](#phase-10--streamlit-analyst-workspace)
- [Phase 11 — Event ingestion, durable buffering, and reconciliation](#phase-11--event-ingestion-durable-buffering-and-reconciliation)
- [Phase 12 — Ten-minute replay and performance evidence](#phase-12--ten-minute-replay-and-performance-evidence)
- [Phase 13 — Monitoring, drift, and retraining proposals](#phase-13--monitoring-drift-and-retraining-proposals)
- [Phase 14 — Deployment, security, release, and recovery](#phase-14--deployment-security-release-and-recovery)
- [Phase 15 — Independent acceptance, shadow pilot, and operation](#phase-15--independent-acceptance-shadow-pilot-and-operation)

### Starting position and immutable boundaries

- Existing: raw CSV, EDA, split/exclusion registers, `scripts/pre_architecture_verification.py`, and saved diagnostic artifacts.
- To build: installable package, PostgreSQL, jobs, model bundle, MLflow integration, FastAPI, Streamlit, reconciliation, monitoring, and deployment.
- The current 9,082 rows include 81 positives; extraction month and label are perfectly confounded. Current metrics cannot approve production detection.
- The 1,817 saved holdout rows are excluded from training, tuning, demo scoring, and operational evaluation. Original row references are not verified account identities.
- Research examples use development rows or synthetic events. A synthetic ledger must not be converted into anonymous F-column inputs without certified definitions.
- Missing source events are not zero transactions. A missing assessment is not a zero-risk assessment.
- The system ranks accounts for human investigation. It has no automatic account-restriction or regulatory-filing action.

### Dependency route

```text
0 requirements -> 1 package -> 2 contracts -> 3 persistence -> 4 ingestion
-> 5 features -> 6 evaluation -> 7 registry -> 8 scoring
-> 9 API -> 10 analyst UI -> 11 reconciliation -> 12 replay
-> 13 monitoring -> 14 deployment/recovery -> 15 acceptance and operation
```

Request missing production data in phase 0 and track it throughout. Software work can progress on research inputs; qualified validation cannot pass without the requested data.

### Shared implementation rules

1. **Identity:** use `record_key` as an opaque internal score key. A qualified record links to verified `account_id`; a research record links to `research_record_id`. Never make a historical CSV index a predictor or verified account key.
2. **Time:** persist timezone-aware UTC times; display local timezone explicitly. Use event time for feature windows and ingestion time for lag measurements. Use half-open feature windows `[start, end)`.
3. **State:** keep ingestion status, job status, model approval, label maturity, score freshness, and case state in separate fields/enums.
4. **Transactions:** service methods own commits. Repositories accept a session and do not commit independently. Audit and business changes commit together.
5. **Artifacts:** write to a temporary run directory, calculate checksums, then publish an immutable manifest. Readers follow a published pointer and never scan unfinished directories.
6. **Idempotency:** bind a key to actor/operation plus canonical request hash. Same key and same request return the original result; same key and different content fail with conflict.
7. **Changes:** preserve reference behavior first. Version a changed feature rule, model, contract, or metric; do not silently alter old reports.
8. **Evidence:** save test command, code revision, config/input fingerprints, environment, result, and date. A passed test must link to a real run.

## Phase 0 — Requirements and data acceptance

**Inputs:** architecture, Stage 9, existing data evidence.  
**Output:** agreed acceptance contract and explicit external dependencies.

### P00.01 — Turn requirements into a trackable register

**Write:** `docs/requirements_and_acceptance.md`, `docs/acceptance/index.csv`.

1. Copy each functional requirement, nonfunctional target, architecture invariant, and final acceptance criterion into a row with a stable ID: `REQ-ING-001`, `REQ-ML-001`, etc.
2. Give each row `requirement, architecture_section, owner_role, implementation_point, test_id, evidence_path, status`. Start status as `PLANNED`; do not mark current designs passed.
3. Phrase the test as observable behavior: an incompatible schema produces a quarantine report and zero published scores.

**Check:** all twelve architecture acceptance criteria link to at least one requirement and roadmap point; none depends on an undefined owner role.

### P00.02 — Specify investigation and identity grain

**Write:** `docs/identity_and_grain.md`, later `domain/identity.py`.

1. Define an investigation snapshot as one record at one declared observation cutoff. Generate UUIDs for batches, score runs, cases, and internal snapshots.
2. For research, compute a deterministic namespaced key from dataset SHA-256 plus original row reference. Keep the original reference only in restricted lineage metadata.
3. For qualified inputs, require the source's stable pseudonymous account ID and enforce `(account_id, snapshot_at, source_id)` uniqueness. Explain corrections/reissued IDs in the source contract.

**Check:** importing the same research row twice produces the same research identity; the same row number in a different dataset does not collide.

### P00.03 — Define roles and review transitions

**Write:** `config/permissions.yaml`, `docs/review_workflow.md`.

1. List permissions independently of screens: `queue:read`, `case:assign`, `case:review`, `case:reopen`, `export:create`, `model:train`, `model:approve`, `job:retry`, `audit:read`.
2. Map analyst/reviewer/engineer/operator/auditor roles to those actions. Engineers cannot approve their own candidates; operators do not automatically gain case-note access.
3. Define permitted transitions `QUEUED -> ASSIGNED -> IN_REVIEW -> REVIEWED`; reopening appends a new event. Keep conclusion values such as `NEEDS_MORE_INFORMATION` separate from workflow state and fraud labels.

**Check:** construct allowed/denied examples for each permission and transition; record the actor and reason needed for privileged overrides.

### P00.04 — Specify the queue calculation

**Write:** `config/review_policy.yaml`.

1. Declare `top_k`, eligible snapshot contract, sort direction, tie rule, refresh cadence, and policy owner. Use a research value such as 50 only in explicitly research configuration.
2. Define ranking as descending raw score followed by ascending `record_key`. Define percentile as `100 * (N - rank) / (N - 1)` for `N > 1`; set the singleton cohort's percentile to 100 for `N=1`. For `N=0`, return an empty queue with no percentile values.
3. Record that percentile is position in a specific eligible cohort, not a fraud probability. Pin cohort and policy versions in every queue snapshot.

**Check:** a fixed score fixture has reproducible ties, top-K membership, and percentile endpoints. Changing K creates a policy version, not new model scores.

### P00.05 — Define performance experiments before collecting results

**Write:** `config/benchmarks.yaml`, `docs/performance_protocol.md`.

1. Add named scenarios for 10,000-row batch latency, 100,000-row capacity, API reads, and reconciliation alongside dashboard load.
2. For each, record CPU/RAM, worker limits, dataset width, eligible rows, concurrency, warm/cold caches, repetitions, and measurement start/stop events.
3. Keep architecture targets as expected limits: 15-minute batch, 500-ms API p95, and later delay gates. Store `observed: null` until measured. Generate load from synthetic rows, not repeated private rows in CI.

**Check:** another engineer can repeat a scenario using only its configuration; no result exists without input and hardware fingerprints.

### P00.06 — Open actionable external data requests

**Write:** `docs/data_request.md`, `docs/data_dependencies.csv`.

1. Create one dependency row for identity, snapshot cutoff, feature availability, certified dictionary, label definition/maturity, mixed-class time periods, and transaction completeness evidence.
2. For each, specify required columns, provider role, sample format, acceptance validator, status, and impact if absent. Use `UNKNOWN` rather than invented provider names.
3. Define closure as supplied evidence plus a passing validator and owner approval. A conversation saying data exists does not close the dependency.

**Check:** each Stage 9 blocker maps to a request, an implementation gate, and a test fixture describing acceptable replacement data.

### P00.07 — Define research and qualified runtime policies

**Write:** `config/environments/*.yaml`, `domain/model_policy.py` later.

1. Record `data_tier` and `model_tier` as immutable properties derived from validation/approval records, not user-selected labels on the dashboard.
2. Define a research environment that permits research-demo bundles and a qualified environment requiring validated source contracts and explicit shadow/pilot approval.
3. Make the production approval predicate reject any unresolved critical dependency, research-only bundle, or self-approval. Keep deployment permission separate from model approval.

**Check:** a research model cannot become qualified merely by changing an alias, request body, or environment variable.

### P00.08 — Specify freshness and unavailable-score behavior

**Write:** `docs/freshness_policy.md`, later `domain/freshness.py`.

1. Define `COMPLETE`, `BUFFERING`, `PROVISIONAL_HIGHER`, `RECONCILED`, `STALE`, `CORRECTED`, and `UNAVAILABLE`. Separate the assessment's completeness from events describing a reconciliation.
2. Every returned score includes `assessed_as_of`, `published_at`, source coverage, and current freshness. Retained scores keep their original assessment time.
3. If there is no complete historical score, return nullable score/rank plus `UNAVAILABLE`. Retain the complete baseline separately from any provisional escalation.

**Check:** opening a new account during a source outage never yields score zero, low-risk text, or an apparently complete timestamp.

### P00.09 — Freeze evaluation-window rules

**Write:** `config/evaluation_policy.yaml`.

1. Specify train, tuning, calibration, and final acceptance windows with label maturity as of each cutoff. Document purge gaps from feature lookback/label windows.
2. For the qualified evaluation task in the architecture, remove shared account/entity groups across partitions. If returning-account forecasting is later requested, create a separately reviewed evaluation policy.
3. Release acceptance labels only after model/config freeze. Record which acceptance cohorts have been inspected; exposed cohorts cannot serve repeatedly as untouched tests.

**Check:** overlapping windows, immature labels, shared groups, and reused acceptance releases fail explicit eligibility checks.

### P00.10 — Build the acceptance evidence template

**Write:** `docs/acceptance/template.md`.

1. Add fields `requirement_id, build_revision, input_hash, config_hash, environment, executed_command, observed, expected, pass_fail, evidence_link, reviewer`.
2. Include sections for ML validity, data quality, authorization, analyst workflow, delay replay, recovery, and unresolved dependencies.
3. Make `NOT_RUN` and `BLOCKED` first-class outcomes; attach reasons instead of leaving empty cells that could be mistaken for approval.

**Check:** populate one synthetic example marked `EXAMPLE_ONLY`; reviewers can distinguish planned checks, executed tests, and human sign-off.

**Phase 0 exit:** agreed definitions exist; external inputs are tracked; no architecture requirement disappears into an unassigned note.

## Phase 1 — Package, configuration, and CI foundation

**Prerequisite:** phase 0. **Output:** installable package and deterministic local/CI setup.

### P01.01 — Preserve the existing evidence

**Write:** `docs/reference_manifest.json` using a small script in `scripts/`.

1. Hash the raw dataset, split register, exclusions, verification source, and existing benchmark artifacts in streaming chunks. Record file size, relative path, digest and creation context.
2. Read dependency versions from the saved report rather than assuming current installed versions are identical. Do not rerun the benchmark into its canonical directory.
3. Store new runs under distinct run IDs. Compare future refactors to these references and retain a change explanation when differences are intentional.

**Check:** modifying a copied fixture changes its digest; creating the manifest does not change any source evidence file.

### P01.02 — Create the source package

**Write:** `src/mule_detection/`, `ui/`, `tests/`.

1. Create `__init__.py` and modules for `domain`, `application`, `persistence`, `ingestion`, `features`, `training`, `registry`, `scoring`, `explanations`, `reconciliation`, `monitoring`, and `api`.
2. Put data structures and policies in `domain`; orchestrating use cases in `application`; database/filesystem implementations in adapters. Routes and UI pages depend on application interfaces.
3. Add a minimal package import test. Do not create dozens of placeholder functions claiming success; unimplemented paths must explicitly fail until built.

**Check:** installing the project makes `import mule_detection` work outside the repository directory.

### P01.03 — Build and lock dependencies

**Write:** `pyproject.toml`, platform-specific runtime/dev lockfiles.

1. Declare the setuptools backend, project metadata, Python baseline, source discovery, runtime dependencies, and a dev extra. Start with the reference ML versions; add SQLAlchemy 2/Alembic/Psycopg, Pydantic settings, FastAPI/Uvicorn, Streamlit/HTTPX, MLflow, metrics, YAML, and approved Parquet support as needed.
2. Use pip-tools to resolve runtime and dev environments; compile separately for Windows development and Linux deployment when platform resolution differs. Validate with `pip check`.
3. Check in resolved locks and build-tool versions. Upgrading the reference ML stack is a separate change requiring parity evidence.

Illustrative packaging skeleton; dependencies must be filled before locking:

```toml
[build-system]
requires = ["setuptools>=77.0.3"]
build-backend = "setuptools.build_meta"

[project]
name = "mule-detection"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[project.optional-dependencies]
dev = ["pytest", "ruff", "mypy", "pip-tools"]

[tool.setuptools.packages.find]
where = ["src"]

[project.scripts]
mule-detection = "mule_detection.cli:main"
```

After filling dependency declarations and implementing the CLI entry point:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install pip-tools
.\.venv\Scripts\python.exe -m piptools compile --extra dev --output-file requirements-dev-windows.lock pyproject.toml
.\.venv\Scripts\python.exe -m pip install -r requirements-dev-windows.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m pip check
```

For deployment generate the runtime lock without `--extra dev` on the deployment platform. Setuptools configuration and lock generation follow [PyPA packaging guidance](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) and [pip-tools documentation](https://pip-tools.readthedocs.io/en/stable/).

**Check:** a second fresh environment installs from the committed platform lock without resolving different runtime versions.

### P01.04 — Implement typed environment settings

**Write:** `src/mule_detection/settings.py`, environment YAML under `config/environments/`.

1. Model environment name, database URL, MLflow URI, artifact root, limits, policy paths and cadence with Pydantic settings. Resolve repository-relative paths once to absolute paths.
2. Merge nonsecret config with environment/secret injection through one documented precedence rule. Validate directory permissions, positive limits and allowed environment names at startup.
3. Prevent research overrides in the qualified environment. Log a redacted configuration fingerprint; never render passwords in exceptions.

**Check:** missing mandatory config fails startup clearly; a negative upload limit and incompatible environment/model tier fail validation.

### P01.05 — Exclude local and sensitive material from Git

**Write:** `.env.example`, `.gitignore`, `.dockerignore` additions.

1. List variable names with empty/example values; store real credentials in untracked local secret files or organization-managed secrets.
2. Ignore virtual environments, operational data volumes, generated model/run directories, exports, private fixtures and `.env` variants except `.env.example`.
3. Keep existing reviewed artifacts and intentional Git LFS dataset handling intact. Exclude raw data and local secrets from Docker build context independently of Git.

**Check:** `git check-ignore` identifies a dummy secret/export file; the example configuration remains trackable and Docker context omits confidential files.

### P01.06 — Implement safe errors and structured logs

**Write:** `domain/errors.py`, `application/logging.py`.

1. Define domain exceptions with code, safe message, severity and correlation ID. Keep diagnostic stack traces server-side; API responses expose stable codes.
2. Implement JSON logging with an allowlist of request/job/batch/model IDs, component, duration and error code. Add a redaction filter for credentials and raw payload fields.
3. Log lifecycle events once at service boundaries. Do not log feature frames, full HTTP authorization headers, or analyst notes.

**Check:** deliberately raise an error with sensitive fixture content; client and ordinary log outputs contain the safe error code and no secret/row text.

### P01.07 — Build meaningful synthetic fixtures

**Write:** `tests/fixtures/`, `tests/conftest.py`.

1. Create tiny labeled snapshots with mixed classes, missing values, duplicate columns, unknown categories, and invalid timestamps. Create no actual bank account identities.
2. Add factory functions for manifests, batches, model metadata and actor claims. Use fixed seeds and an injected clock, not current time.
3. Mark PostgreSQL and expensive benchmark tests separately. Integration fixtures use a dedicated test database and refuse to reset an operational database.

**Check:** fixture generation is identical across repeats; running fast tests requires neither the real CSV nor network access.

### P01.08 — Add the initial CI workflow

**Write:** `.github/workflows/checks.yml`.

1. Set up the locked Python environment, install the package, run Ruff, type checks and selected pytest tests. Add a minimal wheel build/import check.
2. Use a PostgreSQL service for integration jobs when phase 3 exists. Keep public repository PR jobs free of private credentials and financial data.
3. Upload safe test reports on failure and fail the build for failed checks; avoid success fallbacks that hide unavailable tests.

**Check:** a deliberately broken fixture or import causes CI failure; a clean synthetic checkout passes the implemented checks only.

### P01.09 — Implement CLI dispatch without service logic

**Write:** `src/mule_detection/cli.py`.

1. Use `argparse` subcommands for validation, training, evaluation, scoring, reconciliation, replay and health. Parse IDs/config paths into typed request objects.
2. Construct settings/adapters, call the application service, print a compact JSON result, and map domain errors to documented nonzero exit codes.
3. Add `main()` plus an `if __name__ == '__main__'` block. Before a service is implemented, its command returns a clear unsupported operation rather than fake output.

**Check:** `python -m mule_detection.cli --help` works; bad arguments never start a job and service failures return nonzero status.

### P01.10 — Inject clocks and correlation context

**Write:** `domain/clock.py`, `application/context.py`.

1. Define `Clock.now()` for timezone-aware UTC wall time and a separate monotonic timer for duration measurements. Implement production and manually advanceable test clocks.
2. Carry immutable actor/environment/correlation context into each application call. Generate a context when a CLI/job begins and propagate it into spawned job records.
3. Pass clocks to completeness, label maturity and lease code instead of calling global time functions inside those policies.

**Check:** a test advances a ten-minute logical interval instantly; duration measurements still use a real monotonic timer when benchmarking compute.

**Phase 1 exit:** package/fixtures/CI work independently of confidential data; versioned configuration and error conventions are in place.

## Phase 2 — Contracts and boundary schemas

**Prerequisite:** phases 0–1. **Output:** typed schemas and explicit source compatibility.

### P02.01 — Implement batch manifests

**Write:** `domain/contracts/batch.py`, `contracts/batch_manifest_v1.schema.json`.

1. Define `BatchManifest` with strict known fields: contract version, batch/source/schema IDs, observation cutoff, expected row count, checksum, feature-policy version, data tier and owner reference. Qualified manifests require a known timezone-aware UTC observation cutoff. The separate research contract permits an unknown/null historical cutoff with an explicit provenance limitation; upload time is never substituted.
2. Use Pydantic validation for shape/types and explicit cross-field validators for timezone/cutoff relationships. Generate JSON Schema from the same model, not a second hand-maintained definition.
3. Resolve schemas through a server-owned version registry. A manifest cannot reference arbitrary local schema files or remote code.

**Check:** unknown contract versions, naive timestamps and negative counts produce distinct safe codes. Pydantic models/schema generation are described in [official model documentation](https://docs.pydantic.dev/latest/concepts/models/).

### P02.02 — Define qualified snapshots and source merge rules

**Write:** `domain/contracts/snapshot.py`, `config/source_registry.yaml`.

1. Represent identity/cutoffs separately from a feature-value mapping. Require verified account identity, source and snapshot time on the qualified path.
2. Configure which source owns each feature and the observation/availability cutoffs it guarantees. Reject duplicate ownership rather than taking the last file's value.
3. When sources join, require matching account/snapshot grain and compatible cutoff coverage; attach source-specific completeness to the resulting snapshot.

**Check:** a multi-source fixture with mismatched cutoffs or conflicting features cannot become a complete snapshot.

### P02.03 — Adapt the current research CSV

**Write:** `ingestion/research_adapter.py`.

1. Verify dataset and split-register alignment using original row references and hashes. Restrict emitted feature rows to the saved development mask.
2. Generate `research_record_id` from dataset fingerprint and original reference; keep target in a separate label array and extraction month in restricted audit metadata.
3. Set research tier and unknown verified-account/event provenance explicitly. Do not invent a historical snapshot date from upload time or the coarse extraction-month label.

**Check:** exactly the authorized development membership is emitted; holdout keys and `Unnamed: 0` never appear in the predictor matrix.

### P02.04 — Classify input fields and missing-value rules

**Write:** `config/schema_registry/research_v1.yaml`, validator rules.

1. Define each allowed column's logical type and role. Preserve categorical strings during parsing; numeric coercion errors are findings, not silently generated NaNs.
2. Allow target in authorized labeled files but strip it before feature transformation. Metadata/forbidden predictors may be retained for lineage but cannot reach model inputs.
3. Distinguish optional fields, imputable feature cells and missing required source coverage. Only the first two can follow a configured missing-value policy.

**Check:** a file containing an allowed target is usable for training; intentionally including that target as a predictor fails a separate feature-policy assertion.

### P02.05 — Version permanent and learned exclusions

**Write:** `config/feature_policy.yaml`, `domain/feature_policy.py`.

1. Store the permanent policy blocklist, reasons, approval context, and version independently of the historical 1,404-column exclusion register.
2. Preserve that register's hash as an EDA audit reference. Learn missingness/constant/duplicate pruning on each training fold, saving the resulting fold-specific exclusions.
3. Hash canonical policy contents and bind every bundle to its policy. A new blocklist creates a new policy/bundle, not a silent score-time change.

**Check:** changing validation-only missingness cannot alter a training fold's learned list; the target and hard-blocklisted fields are always absent.

### P02.06 — Implement dictionary certification metadata

**Write:** `domain/contracts/feature_dictionary.py`, `config/feature_dictionary/`.

1. Define feature ID, status (`UNVERIFIED`, `PROVISIONAL`, `CERTIFIED`), display name, unit, source table, window, availability, sensitivity and approving reference.
2. Validate certified entries require approval/version and a known feature ID. Unknown entries fall back to ID-only display.
3. Version dictionary changes and save the dictionary version used by evidence generation. A newer definition does not rewrite prior case explanations.

**Check:** an uncertified feature cannot acquire business prose even when it has an informal nickname in an EDA report.

### P02.07 — Implement label contracts

**Write:** `domain/contracts/labels.py`, `contracts/label_v1.schema.json`.

1. Require record/account key, value, label source, event time, adjudication status, maturity time, observed/available time, and version/supersession reference on qualified labels.
2. Define an as-of selector that chooses the latest valid label known by the evaluation cutoff, with mature adjudication. Unreviewed remains unknown unless a signed negative-label policy proves otherwise.
3. Retain correction history and exclude future-discovered labels from historical training snapshots.

**Check:** a label matured tomorrow is not training-eligible today; a correction learned after a historical cutoff does not leak backward.

### P02.08 — Define bundle and scoring-output schemas

**Write:** `domain/contracts/models.py`, `domain/contracts/scores.py`.

1. Require bundle ID, artifact digests, input/transformed signatures, training fingerprint, policy/runtime versions, output scale, research status and model card.
2. Score rows require run/record/snapshot identity, immutable model reference, nullable raw score/rank/percentile, freshness, complete-as-of time and evidence reference.
3. Validate nullable fields by state: `UNAVAILABLE` cannot have a complete score; published ranked rows require finite scores and cohort identity.

**Check:** incomplete lineage or an unavailable row carrying a fabricated zero-risk score fails schema/service validation.

### P02.09 — Define transaction and completeness contracts

**Write:** `domain/contracts/events.py`, `contracts/event_v1.schema.json`.

1. Require source, partition, epoch, sequence, event ID, account identity, event/ingestion times and schema-defined payload. Use integer minor units or approved decimal rules for money.
2. Define explicit correction/reversal event types and references; never infer a reversal solely from a negative amount.
3. Define heartbeat/manifests with contiguous committed sequence, count scope and producer-certified complete-through event time. Record clock-skew limits and epoch restart semantics.

**Check:** a sequence reset without a new epoch, future-skewed event, or contradictory completeness manifest is rejected/escalated.

### P02.10 — Separate workflow and evidence types

**Write:** `domain/contracts/evidence.py`, `reviews.py`, `jobs.py`, `audit.py`.

1. Define evidence as raw observations, contribution direction/scale/base value, reference context, dictionary status and bundle identity.
2. Define review requests with expected case version, actor from trusted context, conclusion, note reference and idempotency key; no request-controlled approval actor.
3. Define job states `PENDING/RUNNING/SUCCEEDED/FAILED` independently of freshness and approval. Document allowed transitions and terminal-state behavior.

**Check:** a completed job can still produce research-only data; a reviewed case does not become a mature fraud label automatically.

### P02.11 — Build contract failure fixtures

**Write:** `tests/contracts/`, JSON/YAML fixtures.

1. For each contract, create a minimal valid fixture and a table of one-field mutations: missing ID, wrong type, unknown version, naive timestamp, conflicting counts and invalid enum.
2. Assert the specific failure code and that rejected input creates no accepted batch, score or approved model.
3. Add reorder/extra-column and research-key collision cases. Compare generated schemas in CI so an accidental breaking contract change requires a version decision.

**Check:** every failure in the documented error catalog has at least one meaningful fixture; tests do not merely check that a model instance can be constructed.

**Phase 2 exit:** contracts explain exactly what every service boundary accepts, rejects, and preserves.

## Phase 3 — PostgreSQL, migrations, and transactional persistence

**Prerequisite:** phases 1–2. **Output:** durable repositories, audit and concurrency behavior.

### P03.01 — Start isolated operational and tracking databases

**Write:** `compose.yaml`, `docker/postgres/init/`, secret templates.

1. Add a PostgreSQL service with a named data volume and health check. For development only, bind its port to `127.0.0.1`; shared deployment keeps it internal.
2. In controlled initialization scripts, create operational and MLflow databases plus distinct migration, runtime, tracking and read-only roles. Supply passwords from secrets, not committed SQL literals.
3. Give runtime roles only required schema/table privileges. Run database creation once; migrations manage later schema changes.

**Check:** each identity connects only to its permitted database/operations; restart retains data.

### P03.02 — Implement the schema as ordered migrations

**Write:** SQLAlchemy models, `migrations/`, `alembic.ini`.

1. Initialize Alembic, load metadata and the secret database URL in its environment file, and split revisions into lineage, scoring, cases/audit, then event/reconciliation extensions.
2. Use the schema map below. Review generated SQL, foreign-key order, required fields and indexes before applying; autogeneration is a starting point.
3. Apply to an empty test database, inspect the revision and schema, and test the documented migration recovery path. Do not run `create_all()` as production schema management.

| Entity | Required core fields | Important relationship/key |
|---|---|---|
| datasets | id, content hash, raw URI, schema/tier | immutable content identity |
| batches | id, dataset ID, manifest hash, status | accepted validation version |
| validation_reports | id, batch, rules hash, findings URI, outcome | batch + validation version |
| model_refs / approvals | bundle digest, registry/version, tier, approval | immutable version + approval event |
| jobs / attempts | request hash, lease owner/expiry, fencing token, state | unique idempotent request |
| score_runs / score_rows | batch/model/policy, record key, score, snapshot | unique run + record key |
| evidence | score row, structured evidence, dictionary version | immutable score/evidence pairing |
| queue_snapshots / members | cohort/policy, published version, rank | unique queue + rank/record |
| cases / review_events | subject, workflow, optimistic version, actor | event history, not overwritten notes |
| labels | account/record, outcome, maturity, known-at, supersedes | versioned as-of labels |
| audit_events / outbox | actor, action, entity, correlation, payload ref | same-transaction append |

Follow [Alembic's migration tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html) for the migration environment and revision commands.

**Check:** `alembic upgrade head` on an empty test database produces the intended tables and foreign keys; no private row is needed.

### P03.03 — Enforce duplicate and lineage rules in the database

**Write:** constraints in migrations and repository conflict translation.

1. Add unique constraints for batch/manifest identity, job request, `(run_id, record_key)`, `(queue_id, rank)`, `(queue_id, record_key)` and action idempotency scope.
2. Require nonnull values in identity columns and foreign keys for score-to-run, evidence-to-score and review-to-case lineage.
3. On uniqueness conflict, read the original record and compare request fingerprints. Return its identity for an exact replay or a conflict for changed content; never swallow arbitrary database exceptions.

**Check:** concurrent requests cannot both create the same run; a score referencing a nonexistent run fails. See [PostgreSQL constraints](https://www.postgresql.org/docs/current/ddl-constraints.html).

### P03.04 — Store wide feature data outside case rows

**Write:** `persistence/artifacts.py`, dataset/snapshot metadata mappings.

1. Save approved raw/feature frames in immutable content-addressed files with schema/count metadata. Use controlled encrypted storage; Parquet is an option after schema conversion is validated.
2. Store only artifact URI, digest, record lookup key, contract/policy version and timestamps in operational tables.
3. Resolve case observations from the versioned scored snapshot, not the newest mutable source file. Apply access checks before artifact reads.

**Check:** changing a later source batch does not change observed values shown for an older assessment.

### P03.05 — Implement repositories and a unit of work

**Write:** `persistence/repositories.py`, `persistence/sqlalchemy.py`, `application/unit_of_work.py`.

1. Define narrow methods such as `get_accepted_batch`, `create_run`, `append_review` and `publish_queue`; keep query details in adapters.
2. Open one SQLAlchemy session/transaction per application operation. Repositories flush if needed but never commit; the outer unit of work commits or rolls back.
3. Roll back on exceptions and close sessions reliably. Do not share sessions across requests or worker processes.

**Check:** a fake failure after inserting a review rolls back the review and its audit row. Transaction context patterns are documented in [SQLAlchemy Session Basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html).

### P03.06 — Implement append-only audit writes

**Write:** `application/audit_service.py`, `persistence/audit_repository.py`.

1. Accept trusted actor/context, action, entity/version, before/after safe references and reason. Generate event identity and timestamp from controlled services.
2. Append inside the business transaction; use the same session. Store note references rather than duplicating confidential note text into infrastructure audit payloads.
3. Audit model approval, queue publication, dispositions, export authorization, privileged retries and correction/reopen actions.

**Check:** injecting an audit-write failure also prevents the business change from committing.

### P03.07 — Restrict audit mutation privileges

**Write:** role grants in migrations and `docs/audit_controls.md`.

1. Grant runtime identities `INSERT` and required reads on audit tables; revoke ordinary `UPDATE/DELETE`. Apply the same rule to immutable review/approval events.
2. Use a separate migration/administrative identity and log privileged maintenance. Define export to organization-approved immutable/tamper-evident storage when required by pilot policy.
3. Document administrator capability and retention exceptions; append-only application behavior is not cryptographic tamper evidence.

**Check:** runtime SQL attempting to alter an audit event is denied; migration privileges are not available in application containers.

### P03.08 — Implement optimistic updates and worker fencing

**Write:** `application/review_service.py`, `persistence/job_repository.py`.

1. For cases, issue `UPDATE ... SET version=version+1 ... WHERE id=:id AND version=:expected`; zero rows means stale client/conflict.
2. For jobs, acquire a lease with owner, expiry and incrementing fencing token in one transaction. Renew only while token/owner match.
3. Require the active fencing token at result publication. An expired worker that resumes after a replacement starts must not publish stale output.

**Check:** two reviewers cannot both overwrite version 4; a superseded worker cannot publish after its lease expires.

### P03.09 — Add indexes from real query shapes

**Write:** index migrations and `docs/query_shapes.md`.

1. Index queue membership by queue/version and rank, cases by authorized scope/state/assignee, history by subject/time, and jobs by state/lease expiry.
2. Plan event indexes for source/partition/epoch/sequence and account/event time; add them with the phase 11 schema.
3. On synthetic scale fixtures, inspect `EXPLAIN (ANALYZE, BUFFERS)` for representative reads. Avoid indexing every wide feature or mutable JSON field.

**Check:** queue pagination reads a bounded published subset rather than sorting the entire score table on every request.

### P03.10 — Exercise migrations and transaction failures

**Write:** `tests/integration/test_persistence.py`, dedicated test database helpers.

1. Apply migrations to a fresh isolated database and seed synthetic lineage/cases.
2. Run duplicate creates, simultaneous case writes and failure injection between business and audit writes. Inspect committed state using a new session.
3. Restart connections and verify published records remain coherent. Test-database reset helpers must check the explicit test environment and database name before dropping fixtures.

**Check:** the suite proves atomicity, uniqueness and stale-write prevention through externally visible committed state.

**Phase 3 exit:** durable storage enforces business identities, versioning, audited writes and safe concurrency.

## Phase 4 — Durable batch intake, validation, and quarantine

**Prerequisite:** phases 2–3. **Output:** accepted immutable batches or inspectable failures.

### P04.01 — Implement controlled intake

**Write:** `ingestion/intake.py`, `persistence/raw_store.py`.

1. Accept a file-like stream or a server-authorized source reference, not an arbitrary analyst-supplied filesystem path.
2. Stream to a generated staging filename under the configured root, enforce byte/row/format limits and reject compressed inputs unless decompression limits are implemented.
3. Create an intake request identity and safe original-filename metadata; parse only supported CSV/Parquet through schema-aware loaders.

**Check:** oversized input, unsupported format and path traversal cannot write outside the controlled root or produce an accepted batch.

### P04.02 — Verify content against the manifest

**Write:** `ingestion/fingerprints.py`, `application/ingest_service.py`.

1. While streaming, compute SHA-256 and bytes; after parsing, compute observed row count and logical schema signature.
2. Compare these with declared metadata before acceptance. Record declared and observed values separately for diagnosis.
3. Persist `RECEIVED/VALIDATING` state before long work and attach job/correlation identity. Progress is observable even if the worker later fails.

**Check:** a correct file with a false checksum/count is rejected with a manifest-mismatch code, not silently repaired.

### P04.03 — Publish raw artifacts immutably

**Write:** raw-store `stage`, `finalize`, and recovery methods.

1. Move/copy a fully flushed staging artifact into content-addressed storage and publish its manifest only after checksum verification. Use atomic rename when filesystem guarantees permit.
2. Record object/file publication state in the database. Cross-filesystem/database writes need recoverable states because they do not share one transaction.
3. Add a janitor/recovery command that finds abandoned staging objects, verifies references and either resumes publication or removes only approved orphan objects after retention.

**Check:** a crash between file persistence and database acceptance leaves a recoverable orphan, not a visible incomplete batch.

### P04.04 — Execute validation rules in a stable order

**Write:** `ingestion/validator.py`, rule registry.

1. Run schema/version checks first, then identity/count/type checks, then timestamps/provenance and feature/label separation.
2. Return structured findings containing rule ID/version, severity, aggregate counts, safe sample references and remediation message. Avoid dumping raw rows.
3. Use source-specific missing/range rules only when certified. Distinguish an allowed imputed cell from an unavailable required data source.

**Check:** a snapshot with a future feature-availability time or duplicate qualified identity fails before scoring.

### P04.05 — Enforce research partition restrictions

**Write:** `ingestion/partition_guard.py`.

1. Match the saved split register to the verified dataset identity, original reference and row alignment. Fail if the register cannot be trusted for this input.
2. Emit development rows only for training/demo scoring. Keep excluded holdout identities in a restricted guard structure, not a user-selectable UI filter.
3. Assert that every output record belongs to the development set and that targets/index/month metadata are outside predictor inputs.

**Check:** an attempted score request containing a held-out research key fails even if sent directly to a worker service.

### P04.06 — Generate quality summaries

**Write:** `ingestion/quality_report.py`.

1. Compute per-field missing counts, type errors, category frequencies, constant/zero patterns and snapshot/source coverage on the authorized subset.
2. For authorized training diagnostics, add class counts by cohort and residual missingness gaps. Do not expose labels through analyst scoring endpoints.
3. Store aggregates plus schema/policy/data fingerprints as versioned JSON and a compact table for the operations UI.

**Check:** known fixture missing counts and unknown categories match expected values; no summary is calculated over an unauthorized holdout selection.

### P04.07 — Classify acceptance and promotion findings

**Write:** `domain/validation_policy.py`.

1. Define hard failures such as wrong schema/hash, duplicate identity, missing required source or incompatible timestamp.
2. Define warnings such as approved-category drift, and qualified-promotion blockers such as confounded labeled cohorts or uncertified feature availability.
3. Permit only the explicitly authorized research workflow when promotion blockers remain. Preserve those blockers in the validation report/model metadata.

**Check:** current data can pass restricted research ingestion while the exact same validation evidence prevents qualified model approval.

### P04.08 — Persist validation outcomes

**Write:** `application/validation_service.py` and batch repository methods.

1. Save immutable report artifact, rule versions, finding counts and outcome. Finalize batch status in a transaction with its audit event.
2. Scoring must query an accepted published validation version; it cannot infer acceptance from file existence.
3. Revalidation creates a new report/version and records whether the new policy invalidates future use; old results keep their original evidence.

**Check:** a manually staged file or a quarantined batch ID cannot be used to start a scoring run.

### P04.09 — Implement exact replay versus conflict

**Write:** ingestion idempotency handler.

1. Build canonical request identity from content hash, schema/source, manifest fingerprint and operation scope; persist it under a unique constraint.
2. Return the existing accepted/quarantined result for the same request. If content matches but source metadata conflicts, return an explicit conflict requiring review.
3. For deliberate reprocessing, issue an audited replay ID linked to the original batch instead of modifying it.

**Check:** retrying intake cannot double-count volume or create a second indistinguishable queue; an intentional replay remains separately traceable.

### P04.10 — Expose safe reports and failure tests

**Write:** `cli validate-batch`, report DTO, `tests/integration/test_ingestion.py`.

1. Have the CLI return batch ID, outcome, counts, finding codes and report reference; use nonzero exit status for rejection/system failure according to the documented convention.
2. Reuse the same safe DTO later in API responses. Keep private raw-file paths and label-bearing fields out of it.
3. Exercise corrupted files, count mismatch, parser limits, partial writes, invalid metadata and duplicate replays through the application service.

**Check:** valid and invalid inputs both leave useful lifecycle/audit evidence and no invalid input creates published scores.

**Phase 4 exit:** immutable intake, partition guards, validation, quarantine and exact replay work together through one service path.

## Phase 5 — Reusable feature pipeline

**Prerequisite:** contracts and research adapter. **Output:** frozen fit/transform behavior with reproducible signatures.

### P05.01 — Extract the existing preprocessor without changing behavior

**Write:** `features/preprocessor.py`, reference-wrapper changes only after comparison.

1. Copy the existing `FoldSafePreprocessor` into the package with its same missingness threshold, ordering, dtype handling and cleanup behavior.
2. Keep the original verification script runnable; add a separate packaged comparison runner that writes into a new artifact directory.
3. Run both paths against the same synthetic frame and authorized development partitions. Investigate any changed columns/matrix values before adding improvements.

**Check:** old and extracted implementations produce equivalent selected features and transformed matrices under the reference configuration.

### P05.02 — Preserve historical exclusions versus fitted selection

**Write:** `features/exclusion_report.py`.

1. Expose two separately named outputs: historical registered candidate count and current fold/bundle selected features.
2. Keep the registered 2,521 candidate columns as an audit fact. For learning, apply hard exclusions then fit structural pruning on each training fold, as the existing benchmark does.
3. Save each fold's dropped columns with reasons and training-partition fingerprint. Do not force all folds to select exactly 2,521 columns.

**Check:** a feature constant only inside one training fold is dropped there without changing unrelated folds or the historical register.

### P05.03 — Implement cloneable transformer components

**Write:** `features/transformers.py`, `features/pipeline.py`.

1. Implement scikit-learn-compatible transformers with constructor parameters only in `__init__`, learned attributes ending in `_`, `fit(X, y=None)` returning self, and `transform(X)` using fitted state.
2. Separate policy exclusion, semantic cleanup, structural pruning and mixed numeric/categorical transformation. Build `ColumnTransformer` with numeric imputation and categorical imputation/one-hot encoding.
3. Reject use before fitting and incompatible required-column signatures. Use fresh cloned pipelines per fold/model rather than reusing a fitted object.

**Check:** cloning and save/load work; fitting one clone cannot mutate another. The pipeline fitting boundary follows [scikit-learn's leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html).

### P05.04 — Version date and age cleanup explicitly

**Write:** `config/semantic_rules.yaml`, `features/semantic_cleanup.py`.

1. Name the existing F3888/F3893/F3894 rules `legacy_research_v1` and preserve their original behavior for benchmark parity.
2. For each rule record its feature IDs, operation, invalid/sentinel condition, output mapping and certification status. Do not assume provisional age/product semantics are production-certified.
3. Require approved dictionary/rule references in qualified mode. Changing a date threshold or generated indicator creates a new feature-policy version.

**Check:** configured sentinel dates reproduce reference results; qualified mode rejects an uncertified semantic rule rather than silently interpreting it.

### P05.05 — Keep all fitted statistics inside training

**Write:** training pipeline factory and fit-boundary instrumentation.

1. Split rows first; pass only training X/y into `fit`. Fit imputation, encoding, pruning, logistic scaling and any feature selection inside the fresh pipeline.
2. Calculate evidence reference percentiles/categories from training data only and save the reference partition fingerprint.
3. Apply `transform` and `predict` to validation rows without calling any discovery/fit method. Calibration needs its own separated training/validation procedure.

**Check:** replacing validation values with extreme numbers does not alter training medians, selected columns, category sets or reference distributions.

### P05.06 — Distinguish feature imputation from absent transactions

**Write:** missing-value policy and quality output.

1. Allow configured cell imputation only after snapshot/source completeness checks. Preserve a record of which values were missing.
2. Keep source gaps in freshness/quality state; do not fill unavailable transaction counts or balances with zero to make the model run.
3. Evaluate any new missingness indicator as a model-feature change with cohort-proxy probes and retraining. Preserve reference behavior until that experiment passes review.

**Check:** a missing optional research cell can be imputed; a qualified incomplete source window cannot become complete through imputation.

### P05.07 — Preserve feature order and raw-column mappings

**Write:** `features/signature.py`, feature-name mapping artifact.

1. Save ordered required input columns/types, selected raw features and transformed feature names from the fitted transformer.
2. Map one-hot output positions back to their source feature through transformer metadata/output slices, not string-splitting names that may contain underscores.
3. At inference reorder input by saved names, ignore only explicitly permitted metadata, and reject missing required features. Match transformed dimensionality before calling the model.

**Check:** column reordering leaves scores unchanged; deleting a required input fails; a category name containing underscores still maps to the correct raw feature.

### P05.08 — Serialize the complete fitted state

**Write:** pipeline artifact writer/reader used by phase 7.

1. Save trusted fitted preprocessing plus JSON manifests for input/transformed signatures, policy, learned exclusions and reference summaries.
2. Hash each artifact and record Python/library versions. Include training data/split fingerprints so the bundle cannot mix components from different runs.
3. Freeze learned state after fit; inference code never writes categories, medians or new feature lists back into the active artifact.

**Check:** repeated inference leaves artifact digests unchanged; a loaded pipeline transforms a fixed fixture identically to its pre-save form.

### P05.09 — Write leakage and edge-case tests

**Write:** `tests/unit/test_feature_boundaries.py`.

1. Fit with known train medians/categories, mutate validation-only records, and assert invariant learned state. Add an obvious target-proxy sentinel to ensure forbidden predictors are blocked.
2. Exercise unknown categories, all-null training columns, duplicate feature contents, reordered inputs, missing columns and empty batches with defined outcomes.
3. Test serialization and raw-to-encoded mapping. Assert matrix values/signatures, not just the selected-column count.

**Check:** deliberately moving imputation outside the fold causes a test failure; valid unknown categories follow the configured encoding policy.

### P05.10 — Run benchmark parity without overwriting evidence

**Write:** `scripts/compare_reference_pipeline.py`, comparison report.

1. Run reference and packaged pipelines under the same dependency lock, splits, seeds and model configuration; use distinct output directories.
2. Compare OOF membership, per-fold selected columns, prediction deltas, AP/ROC-AUC and top-K metrics. Choose numerical tolerance before interpreting a difference.
3. Classify differences as intentional versioned change, platform numerical variance, or defect. Keep the original report and attach the decision.

**Check:** the comparison explains every material difference; no new result is described as production validation.

**Phase 5 exit:** one package pipeline supports fold-safe training and immutable inference with a verified mapping to the reference implementation.

## Phase 6 — Training, splits, evaluation, and labels

**Prerequisite:** phases 4–5. **Output:** reproducible candidates with honest diagnostic/qualified reports.

### P06.01 — Implement explicit evaluation modes

**Write:** `training/evaluation_policy.py`, CLI/config modes.

1. Implement `research` using the saved development selection and existing five-fold stratified diagnostic; tag every output with its cohort confounding.
2. Implement `qualified_temporal` only for certified identity/cutoff/label inputs. Reject it when time windows lack representative mature classes or provenance.
3. Validate evaluation mode at service startup; changing a report title cannot bypass its data eligibility checks.

**Check:** the current CSV can run research diagnostics but qualified temporal evaluation returns a data-gate failure.

### P06.02 — Select labels as of the training cutoff

**Write:** `training/label_selector.py`.

1. Query label versions known by the as-of timestamp; resolve supersession chains using only information available then.
2. Include labels with approved adjudication and maturity by the configured cutoff. Separate unknown, immature, corrected and source-assumed-negative counts in the report.
3. Join to snapshots using verified identity and defined feature-before-outcome rules. Research target use remains a separately tagged legacy diagnostic path.

**Check:** future labels and later corrections cannot improve a historical training run through backward leakage.

### P06.03 — Implement and persist split membership

**Write:** `training/splits.py`, immutable split manifests.

1. Build split functions returning row keys for train/tune/calibration/acceptance, not anonymous positional arrays alone.
2. For temporal mode sort by cutoff, enforce approved boundaries, purge overlapping feature/outcome windows, and exclude account/linked-entity overlap according to phase 0's task definition.
3. Save membership hash, time ranges, class/group counts and every exclusion reason before model fitting.

**Check:** synthetic overlapping groups/windows fail; all predicted validation records have exactly one documented fold membership.

### P06.04 — Implement baseline and tree candidates fairly

**Write:** `training/model_factory.py`, `config/model_candidates.yaml`.

1. Create factories for regularized logistic regression and LightGBM using identical row splits and versioned compatible feature policies.
2. Add training-fitted scaling for logistic numeric features; handle sparse categorical matrices without unintended densification or centering errors.
3. Use the existing LightGBM config as a reference candidate and bound CPU threads/memory. Record class weighting and any early-stopping policy; neither model sees final acceptance data during fitting.

**Check:** both candidates produce OOF scores for the same eligible records, with a saved configuration rather than hidden defaults.

### P06.05 — Separate tuning from final evaluation

**Write:** `training/search.py` and evaluation guard.

1. Reserve tuning folds/windows inside development; for each candidate configuration fit fresh pipelines per fold.
2. Select configuration using predeclared ranking metrics and complexity constraints, saving all tried configurations and scores.
3. Freeze configuration and policy hashes before final acceptance. Never use the internal holdout or final acceptance results to choose preprocessing, K, calibration or thresholds.

**Check:** evaluator rejects a nonfrozen candidate on the acceptance path; acceptance artifacts cannot be supplied as tuning input.

### P06.06 — Persist OOF predictions and cohort probes

**Write:** `training/runner.py`, `training/cohort_probes.py`.

1. For each fold save training/validation keys, fitted manifest, target counts, seed, predictions and timing. Assert every development key receives exactly one OOF prediction.
2. Probe source/month predictability and feature missingness differences on authorized development data; store limitations when the target/source confounding prevents causal interpretation.
3. Save fold artifacts before aggregate reporting so a failed later fold does not create a misleading complete metric table.

**Check:** incomplete OOF coverage fails the run; no held-out key appears in predictions or fitted training membership.

### P06.07 — Implement ranking metrics and uncertainty correctly

**Write:** `training/metrics.py`.

1. Compute AP, secondary ROC-AUC, selected-positive count, P@K, R@K and lift using deterministic score/tie sorting. Handle K greater than N, zero positives and single-class validation explicitly.
2. Calculate fold distributions and bootstrap intervals; resample account/entity groups when repeated records exist, and report invalid resamples rather than hiding them.
3. Label pooled cross-fold ranking carefully because different fold models can produce different score scales. Include fold-level/batch-relevant results alongside legacy pooled diagnostics.

**Check:** a hand-calculated tiny fixture matches counts/metrics and undefined statistics are marked unavailable, not zero.

### P06.08 — Evaluate sensitive/proxy feature effects

**Write:** `training/subgroup_report.py`, ablation configurations.

1. Identify approved reporting groups and potentially sensitive/proxy feature sets from the dictionary; do not infer protected identities from anonymous values.
2. Refit ablated candidate pipelines on the same folds and compare ranking/selection burden. Report each subgroup's denominator, positive count and uncertainty.
3. Apply minimum-sample and policy review gates. Current confounding/tiny samples result in inconclusive findings rather than fairness certification.

**Check:** an insufficient subgroup is visibly suppressed/inconclusive; changing subgroup definitions changes a report version.

### P06.09 — Add calibration only when supported

**Write:** `training/calibration.py`.

1. Gate calibration on representative prevalence, label maturity and a calibration partition excluded from model selection/final acceptance.
2. Fit the configured calibration method using only its allowed data; store its mapping, training lineage, reliability/Brier results and output-scale metadata.
3. Without those prerequisites keep ranking-only output and prohibit a UI label such as fraud probability or percent chance.

**Check:** research models return ranking scores/percentiles; a qualified calibrated bundle identifies the separate calibrated probability and its evidence.

### P06.10 — Finalize candidate reports and run manifests

**Write:** `training/report.py`, run manifest/model card.

1. Write config/data/source/dependency hashes, split memberships, metrics, predictions, cohort probes, limitations and gate outcomes into an immutable candidate directory.
2. Add code Git revision plus dirty-tree/source hash when applicable; record actual dependency versions, not just desired requirements.
3. Finalize run state only after artifact completeness checks. Return candidate/run identity to the CLI and registry service.

**Check:** a reviewer can reproduce the run without guessing hidden parameters; a failed evaluation remains failed even if some metrics are high.

**Phase 6 exit:** candidate evidence is reproducible and data-tier limitations are mechanically enforced.

## Phase 7 — Model bundle, registry, approval, and rollback

**Prerequisite:** phases 3 and 6. **Output:** trusted frozen inference bundles and controlled model selection.

### P07.01 — Fit the final authorized research bundle

**Write:** `training/final_fit.py`.

1. Read a frozen selected configuration and verify its development data/split/policy fingerprints.
2. Instantiate a fresh pipeline/model and fit once on the authorized development subset. Do not copy one fold's fitted transformer onto a differently trained model.
3. Mark predictions on those training rows as demonstration/in-sample output. Retain OOF metrics as diagnostic evaluation evidence; never recalculate performance from final-fit demo scores.

**Check:** fitted row membership excludes all 1,817 holdout rows and the final bundle links to the exact configuration-selection report.

### P07.02 — Package an immutable bundle

**Write:** `registry/bundle_writer.py`, model bundle manifest schema.

1. Save preprocessing, estimator, signatures, raw-column mapping, reference distributions and model card into a staging bundle directory.
2. Save hashes/sizes for each file, dependency and code identity, training fingerprint, output scale, dictionary/policy versions and research status in `bundle.json`.
3. Verify all hashes and a prediction fixture before marking the bundle finalized. Use a content-addressed immutable bundle ID and never overwrite an active bundle directory.

Suggested layout:

```text
<bundle-id>/
  bundle.json
  pipeline.joblib
  model.txt or trusted-model.joblib
  input_signature.json
  transformed_features.json
  reference_statistics.json
  model_card.md
  environment.json
  validation_fixture.json
```

**Check:** missing/replaced artifacts or mismatched preprocessing/model identities prevent bundle finalization.

### P07.03 — Implement trusted loading and parity tests

**Write:** `registry/bundle_loader.py`.

1. Accept only registry-controlled artifact references under allowed storage roots; analysts cannot upload arbitrary serialized executable models.
2. Check approval/environment, expected bundle digest, all artifact hashes, compatible runtime and input signature before deserializing trusted preprocessing.
3. Load in a restricted worker process and compare fixed fixture predictions to recorded outputs within a declared tolerance. Artifact trust must come from protected storage/approval, not a checksum embedded beside an untrusted file.

**Check:** tampering with a model and its local manifest cannot override the independently recorded approved digest.

### P07.04 — Connect experiment tracking and registration

**Write:** `registry/mlflow_adapter.py`, MLflow service configuration.

1. Run MLflow with its dedicated database/backend and controlled artifact root. Configure authentication/network restrictions before shared use.
2. Log candidate parameters, metric summaries, data/config hashes and full bundle artifacts using the pinned MLflow version.
3. Register a version referencing that bundle and mirror registry name/version/digest into the operational model record. Registry writes must be recoverable/idempotent if the database transaction later fails.

**Check:** repeated registration of the same request returns the recorded mapping or a recoverable pending state, not untracked duplicate active models.

### P07.05 — Separate registry aliases from approval authority

**Write:** model selection/approval records and registry synchronization.

1. Use registry aliases for human-readable deployment references and tags for diagnostic status. Implement actual authorization in operational approval records bound to digest/environment.
2. Allow an approval service to move an alias only after checking those records; reconcile any external alias change against allowed versions.
3. Save audit events for alias/deployment changes. Do not use an old-style stage name or mutable validation tag as sufficient evidence.

**Check:** manually retagging an unapproved version cannot make the scorer accept it. Alias/tag behavior follows [MLflow's official registry workflow](https://www.mlflow.org/docs/latest/ml/model-registry/workflow/).

### P07.06 — Enforce model lifecycle and separation of duties

**Write:** `domain/model_lifecycle.py`, `application/model_approval_service.py`.

1. Implement allowed transitions among candidate, research-demo, approved-for-shadow, approved-for-pilot, rejected and retired states.
2. Store requesting/training identity, reviewer identity, evidence references, reason and timestamp. Reject same-person self-approval for qualified states.
3. Give training jobs candidate-create permission only. A runtime deployment identity can resolve approved versions but cannot approve them.

**Check:** an engineer's training credential cannot approve its own candidate or update a production alias.

### P07.07 — Implement environment-specific promotion gates

**Write:** `registry/promotion_policy.py`.

1. Evaluate the immutable candidate's data tier, dictionary/identity/label qualification, unresolved risks, required metric evidence and permitted target environment.
2. Require passed organizational review references and threshold policy version; a missing field yields `BLOCKED`, never an optimistic default.
3. Produce a machine-readable gate report with individual reasons. Current cohort confounding always blocks qualified promotion.

**Check:** even perfect research AP cannot override the missing representative-cohort dependency.

### P07.08 — Pin model resolution for each job

**Write:** `registry/model_resolver.py`, job/run fields.

1. Resolve alias to immutable registry version/bundle digest at job creation/start under the approval policy.
2. Persist resolved identity in the run and use it for all chunks, explanation generation and retries.
3. Revalidate that identity at publication; revocation prevents new publication according to policy, but never swaps the estimator halfway through.

**Check:** changing the active alias while a run is processing does not create mixed-model scores.

### P07.09 — Implement audited rollback

**Write:** rollback command and `docs/runbooks/model_rollback.md`.

1. Select a previously approved compatible bundle, verify it is still allowed, and record rollback reason/actor/reference to the incident.
2. Update future deployment selection atomically; leave completed score runs unchanged. If rescoring is needed, create an explicit new run.
3. Check active-version health and a fixture after rollback; preserve both old and new deployment events.

**Check:** rollback changes future scoring selection without rewriting existing evidence or concealing the failed deployment.

### P07.10 — Test registry/promotion failure paths

**Write:** `tests/integration/test_registry.py`.

1. Exercise unapproved, retired, corrupt, wrong-signature, unknown-runtime and missing-artifact bundles through the same loader used by scoring.
2. Simulate alias changes, MLflow timeouts, registration retries and unauthorized promotions; verify consistent recoverable operational state.
3. Run the rollback rehearsal with two valid compatible fixtures and verify audit history/immutable score lineage.

**Check:** tests prove authorization and artifact consistency independently of whether the registry UI displays a reassuring status.

**Phase 7 exit:** inference loads a trusted approved immutable model/pipeline combination, with reproducible selection and rollback.

## Phase 8 — Scoring, explanations, and atomic queue publication

**Prerequisite:** accepted batches and approved compatible bundles. **Output:** complete ranked queues and traceable evidence.

### P08.01 — Create idempotent scoring jobs

**Write:** `application/scoring_service.py`, scoring request schema.

1. Canonically hash accepted batch ID/content, immutable bundle digest, feature/review policy hashes and explicit replay ID.
2. Create or retrieve the unique job, then acquire its lease/fencing token. Record attempt start, selected model and authorized actor/environment.
3. Return existing job/run identity on retry. Treat a different replay ID as a deliberate new run linked to its predecessor.

**Check:** simultaneous equivalent requests create one logical run and distinct attempts cannot both publish.

### P08.02 — Verify all prerequisites before inference

**Write:** scoring preflight validator.

1. Read accepted validation state and raw/feature artifact hashes, verify the allowed schema and observation/availability cutoffs.
2. Resolve/check the bundle approval, policy signature, data tier and research partition guard.
3. Fail preflight with specific safe reasons before transforming any records if a prerequisite is missing. Save the failed attempt and preserve the current published queue.

**Check:** a direct worker request cannot bypass quarantine, holdout exclusion, research restrictions or unapproved-model checks.

### P08.03 — Score bounded chunks without mutating active state

**Write:** `scoring/worker.py`, staging score repository.

1. Read the immutable input in configurable chunks, transform through the frozen pipeline and calculate raw ranking scores.
2. Persist chunk results under an unpublished run with row-key uniqueness and completed-chunk metadata. Keep any dataframe index outside feature inputs.
3. Define retry as verified chunk resumption or full unpublished-run restart; never append blindly to partially completed output. Bound estimator threads and memory.

**Check:** interrupting after chunk two and retrying yields each eligible record exactly once with the pinned model.

### P08.04 — Validate score completeness and deterministic order

**Write:** `scoring/result_validator.py`.

1. Verify expected record membership/count, no duplicates, finite scores, correct output direction and successful signature validation.
2. Sort score descending then stable record key. Persist a sort-policy version and never rely on nondeterministic database tie order.
3. Reject mismatched chunk counts or missing records before ranking/publication; an empty eligible cohort returns a defined empty result, not misleading percentiles.

**Check:** synthetic NaN scores, missing rows and duplicate keys cause failed publication while the previous queue remains readable.

### P08.05 — Materialize ranks and the top-K queue

**Write:** `scoring/ranking.py`, queue snapshot tables.

1. Rank all eligible scored records under the frozen policy; calculate percentile using the phase 0 formula and record the cohort size.
2. Select `min(K, N)` queue members, preserving full ranking results for authorized navigation. Mark research scores and score-scale metadata.
3. Store queue members with score-version references. A queue snapshot is immutable and can be paginated stably after later reconciliation.

**Check:** a hand-calculated tied-score fixture produces the expected order, percentile values and selected-positive/top-K counts.

### P08.06 — Generate contributions on the correct output scale

**Write:** `explanations/contributions.py`.

1. For the LightGBM bundle, transform the selected cases through the exact stored pipeline and request tree contributions with the pinned library API.
2. Preserve the extra expected/base-value column and verify base plus contributions matches the corresponding raw-margin output, not the displayed percentile.
3. Save scale/base value and selected positive/negative contributors. Validate matrix shape, feature names and numerical tolerance before publishing evidence.

LightGBM exposes contribution prediction through `pred_contrib`; the extra expected-value column is specified in [Booster prediction documentation](https://lightgbm.readthedocs.io/en/stable/pythonapi/lightgbm.Booster.html).

**Check:** contribution sums reconcile to model raw output; no explanation implies that contributions sum directly to fraud probability.

### P08.07 — Build raw-feature evidence without invented meanings

**Write:** `explanations/evidence_builder.py`, factual templates.

1. Map encoded contributions back to raw fields using saved transformer mappings. Sum encoded contributions for a raw field when presenting an aggregated reason, retaining detail for audit.
2. Attach observed raw value and training-reference percentile for suitable numeric fields; use category frequency/unseen status for categorical fields. Label imputed values separately from observations.
3. Use certified display names only when the versioned dictionary allows them. Otherwise render `Fxxxx`, value and model contribution with meaning-unverified status.

**Check:** an anonymous fixture never becomes a claim about transfer velocity, counterparties or intent; aggregated contributions preserve the total.

### P08.08 — Persist lineage and unavailable-score semantics

**Write:** score/evidence repository methods and output DTOs.

1. Link score rows to run, batch/snapshot, bundle, feature policy, evidence/dictionary version, cutoff and freshness coverage.
2. Preserve the last complete assessment as a separate version reference. A provisional result does not replace its historical provenance.
3. Return nullable score/rank when no usable complete assessment exists; keep state reasons available to the UI.

**Check:** every case evidence value can be traced to the scored snapshot and every unavailable state remains visibly distinct from a legitimate low score.

### P08.09 — Publish a completed queue atomically

**Write:** `application/publication_service.py`.

1. Write chunks, evidence and ranking into unpublished versioned storage first; verify counts and artifact hashes.
2. In a short database transaction recheck lease/fencing token, approval and expected predecessor, mark the run complete, set the active queue pointer, and append audit/outbox events.
3. Readers query the pointer plus immutable membership. If publication fails, keep the old pointer and retry through idempotent transaction handling.

Critical algorithm, expressed as project-level pseudocode:

```text
stage scores -> validate full membership -> stage evidence/ranks
begin transaction
  lock publication scope; verify job lease and fencing token
  verify model authorization and expected prior queue version
  mark run complete; switch active queue pointer
  append publication audit and outbox event
commit
```

**Check:** a reader never observes mixed chunks, scores without required evidence, or a pointer to an incomplete run.

### P08.10 — Exercise scoring crash and retry scenarios

**Write:** `tests/integration/test_scoring_publication.py`.

1. Inject failures during chunk write, evidence generation, before pointer commit and immediately after commit.
2. Retry with the same request; compare final membership, scores, rank and lineage to a clean reference run.
3. Test retired/revoked model, incorrect input signature, ties, holdout keys and insufficient permissions. Assert the prior queue remains intact on failed publication.

**Check:** clean and recovered runs have the same complete visible result with no duplicate business effects.

### P08.11 — Reconcile rank changes across the full cohort

**Write:** corrected-score publication method and queue rebuilder.

1. When an affected account is rescored, preserve its old score and append a corrected version linked to the reconciliation event.
2. Recalculate order/percentiles over the same eligible population using corrected and unchanged score versions; unchanged scores may still move in rank.
3. Publish a new queue snapshot atomically. Keep the queue version a reviewer opened, and flag when a newer assessment exists rather than moving their open case silently.

**Check:** raising one account across the K boundary changes the expected membership and neighboring ranks while leaving unaffected raw score values unchanged.

**Phase 8 exit:** idempotent scoring, evidence correctness, atomic publication, and global ranking updates work together.

## Phase 9 — FastAPI and analyst case services

**Prerequisite:** phase 8 and persistence. **Output:** authorized request/response contracts over application services.

### P09.01 — Implement the application factory and HTTP boundary

**Write:** `api/app.py`, `api/dependencies.py`, `api/errors.py`, route modules.

1. Expose `create_app(settings=None, service_factory=None)` so tests inject repositories, clocks and fake identity without production globals. With no arguments, load validated runtime settings and construct real adapters; this is the Uvicorn `--factory` entry path.
2. Register typed request/response models, error handlers, request-ID middleware and startup configuration validation. Keep database sessions scoped to each application operation.
3. Add liveness for process health and readiness for required dependencies/migrations; exclude sensitive internals from public responses. Snapshot OpenAPI after routes exist.

**Check:** a fake service can be exercised through the real HTTP contract; exceptions become stable safe errors and readiness fails when required storage is unavailable.

### P09.02 — Add batch/job endpoints without synchronous heavy work

**Write:** `api/routes/batches.py`, `jobs.py`.

1. Intake requests authenticate/authorize, enforce byte limits, stage uploads durably and return `202` with a job ID after durable job registration.
2. Workers consume PostgreSQL-backed pending jobs; API handlers do not run model training, ingestion validation or scoring inside a page request.
3. Add job/batch status endpoints that return attempts, safe error codes, timestamps and validation summaries. Restrict retries and expensive job types by permission.

**Check:** restarting the API after a `202` does not erase the job; unauthorized users cannot submit training or privileged retries.

### P09.03 — Implement version-stable queue and case reads

**Write:** `api/routes/queues.py`, read repository.

1. On first queue read return the explicit published queue version; require that version in subsequent pagination requests.
2. Use keyset pagination over `(rank, record_key)` inside that immutable version, with server-enforced page limits and allowlisted filters.
3. Apply actor case-scope permissions in repository queries before pagination/counting, not after fetching records.

**Check:** publishing a newer queue while a user pages through an older one does not duplicate/skip records or leak unauthorized counts.

### P09.04 — Expose provenance and score history

**Write:** `api/routes/cases.py`, `models.py`, response DTOs.

1. Return the case's selected score version, observation cutoff, assessed-as-of/publication time, model/bundle/policy/dictionary versions and source freshness.
2. Provide separately paginated score/review/audit history appropriate to actor permissions; retain original evidence snapshots.
3. Include a `newer_assessment_available` flag/reference if reconciliation or a later batch supersedes the opened version. Do not return raw storage credentials or private artifact paths.

**Check:** a reviewer can identify exactly which evidence supported an earlier disposition even after model/source changes.

### P09.05 — Implement safe review writes

**Write:** review request DTOs and `application/review_service.py`.

1. Require `expected_version` and an `Idempotency-Key`. Take actor identity from verified request context and validate transition/assignment rights.
2. In one transaction compare/update the case version, append the immutable review/note event and its audit entry, and store the idempotency response fingerprint.
3. Return `409` for stale versions or changed-content reuse of a key; return the original result for exact retries.

Example request contract to implement:

```http
POST /v1/cases/<case-id>/reviews
Authorization: Bearer <validated-access-token>
Idempotency-Key: <generated-request-uuid>
Content-Type: application/json

{"expected_version":4,"conclusion":"NEEDS_MORE_INFORMATION","note":"Synthetic example only"}
```

**Check:** double-click/retry creates one review; a stale reviewer cannot overwrite the newer case state.

### P09.06 — Keep workflow conclusions separate from labels

**Write:** review-event persistence and label-boundary tests.

1. Persist reviewed conclusion, note reference, actor, score version and reason without writing directly to the mature label table.
2. Add explicit outcome-verification requests for downstream adjudication if needed; preserve a reference to the original investigation.
3. Audit corrections as new events. When a review changes, historical training runs retain the label snapshot actually available to them.

**Check:** marking a case reviewed does not immediately change next-run training labels or turn an unreviewed case into a confirmed negative.

### P09.07 — Implement adjudicated outcome ingestion

**Write:** `application/label_ingest_service.py`, restricted label routes/CLI.

1. Accept versioned label manifests from an approved outcome owner, validate identity, known-at time, maturity, source and supersession.
2. Insert outcome versions and validation/audit records atomically; reject ambiguous joins or future-discovered corrections on an as-of request.
3. Carry review-selection and adjudication provenance into evaluation datasets so reviewed-case yield is not reported as population recall.

**Check:** incomplete/unapproved outcome submissions cannot enter mature training labels; corrected outcomes can be reconstructed as of historical cutoffs.

### P09.08 — Implement server-side identity and permissions

**Write:** `api/auth/`, permission dependency and identity-provider adapter.

1. Select the organization's OIDC/access-token trust configuration: issuer, API audience, allowed algorithms, key source, expiry/skew and role/group mapping. These values must be supplied, never guessed.
2. Verify signature/issuer/audience/expiry using a maintained JWT/OIDC library, cache signing keys safely and reject unknown/expired tokens. Do not decode claims without verifying them.
3. Resolve effective permissions and case scope server-side; check action and object access on each endpoint. Test identity injection is allowed only in an explicitly isolated test app.

**Check:** spoofed headers, wrong audience, altered token, expired token and a valid actor outside the case's scope fail. FastAPI supports permission scopes as described in [its OAuth2 documentation](https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/).

### P09.09 — Build authorized exports

**Write:** `application/export_service.py`, export route/worker.

1. Bind the export request to actor permissions, queue/data version, selected columns and filters. Register an audited export ID before generation.
2. Generate from immutable scored snapshots; include batch/model/policy/as-of metadata. Minimize identity/note fields and restrict download access/expiry.
3. Escape spreadsheet formula-leading characters in string cells under the approved CSV policy; quote fields properly. Keep numeric fields numeric where safe and test multiline/unicode values.

**Check:** a downloaded export contains exactly the authorized version/scope and cannot execute a formula-bearing synthetic note when opened as a spreadsheet.

### P09.10 — Exercise authorization and concurrency through HTTP

**Write:** `tests/integration/test_api.py`, role/action fixtures.

1. Use the real API app with a dedicated database and signed test tokens. Cover each permission with allowed and denied requests, including direct object-ID access.
2. Test stale writes, replayed keys, changed-content retries, malformed notes, invalid pagination/version and concurrent review updates.
3. Fail a worker/database dependency and verify safe status/readiness responses and persistence of already acknowledged jobs.

**Check:** tests assert committed business/audit state as well as response codes; hiding a button is never the only access-control test.

### HTTP surface to implement

| Route | Behavior | Permission |
|---|---|---|
| `POST /v1/batches` | Durable intake + validation job, `202` | batch intake |
| `GET /v1/batches/{id}` | Safe status and validation summary | scoped batch read |
| `POST /v1/scoring-runs` | Durable scoring request | job submission |
| `GET /v1/jobs/{id}` | Job lifecycle and safe failures | scoped operations read |
| `GET /v1/queues/{version}/cases` | Stable paginated membership | queue read |
| `GET /v1/cases/{id}` | Case, selected score and freshness | scoped case read |
| `GET /v1/cases/{id}/evidence` | Immutable model evidence | scoped evidence read |
| `POST /v1/cases/{id}/assignment` | Version-checked assignment | case assign |
| `POST /v1/cases/{id}/reviews` | Idempotent audited review | case review |
| `POST /v1/cases/{id}/reopen` | Audited allowed transition | case reopen |
| `GET /v1/cases/{id}/history` | Permitted immutable history | scoped history read |
| `POST /v1/exports` | Version-bound export job | export create |
| `GET /health/live`, `GET /health/ready` | Process/dependency state | deployment policy |

No route above performs automatic account restriction, automated filing, or model self-approval.

**Phase 9 exit:** application behavior and authorization are enforceable through the API independently of the UI.

## Phase 10 — Streamlit analyst workspace

**Prerequisite:** phase 9. **Output:** usable investigation flow over the API.

### P10.01 — Implement the API client and page shell

**Write:** `ui/app.py`, `ui/api_client.py`, `ui/pages/`.

1. Use HTTPX with explicit API base URL, TLS verification, timeouts and safe errors. Forward only the trusted per-user API credential supplied by the identity adapter.
2. Add methods matching API DTOs; generate request IDs and preserve idempotency keys for pending writes. Do not retry writes with a new identity after a timeout.
3. Build navigation from effective permissions, while leaving the API authoritative. UI code must not import database sessions, bundle loaders or model prediction functions.

**Check:** denying API access still denies the operation if a UI navigation check is bypassed.

### P10.02 — Build the intake and operations page

**Write:** `ui/pages/operations.py`.

1. Provide upload/manifest selection for permitted roles and display configured limits before submission.
2. Submit once, store the returned job ID in session state, and poll status at a bounded interval. Show safe validation findings and quarantine reasons.
3. Expose retry only when permission and job state allow it; retry creates/reuses the server's recorded request rather than rerunning a Python model from Streamlit.

**Check:** browser refresh during validation reconnects to the same durable job and an invalid file produces understandable findings.

### P10.03 — Build the ranked queue page

**Write:** `ui/pages/queue.py`.

1. Select a published batch/queue version and request a bounded server-side page. Render rank, percentile, raw score label, assignee, case state, freshness and model version.
2. Send allowlisted filters/sort options to the API; preserve queue version and cursor together in session state.
3. Indicate when a newer queue exists and let the user deliberately refresh. Keep contextual selection across page reruns.

**Check:** pagination remains stable during reconciliation; no raw score is labeled percent chance or legal conclusion.

### P10.04 — Build case evidence detail

**Write:** `ui/pages/case_detail.py`.

1. Request case/evidence for an explicit assessment version. Show observation cutoff, source completeness, model version and research status above interpretation-sensitive details.
2. Render observed versus imputed values, signed contributors, contribution scale/base, reference context and dictionary certification.
3. Use fixed factual templates and encoded/escaped text; do not generate unsupported business narratives from anonymous IDs.

**Check:** a case with only F-column semantics stays understandable as model evidence without invented transactions, destinations or timing claims.

### P10.05 — Implement resilient review forms

**Write:** assignment/note/disposition UI components.

1. Use explicit submit forms. Generate a request UUID once when the user submits and keep payload plus key until the response is known.
2. Include the fetched case version; on `409`, fetch the latest case and ask the user to review differences before a fresh action.
3. After success clear pending form state, refetch case/history and show its persisted action identity. Do not treat a network timeout as proof the write failed.

**Check:** double submission, rerun and timeout retry create one review event and display the server's actual persisted result.

### P10.06 — Show immutable history and correction context

**Write:** `ui/pages/history.py`.

1. Fetch versioned assessment and review events in timestamp order with pagination.
2. Link each review to the model/score/evidence version it used; highlight later corrected assessments without altering the earlier record.
3. Display the reason for reopen/override and a safe comparison of changed evidence/rank. Restrict note/audit details according to API permissions.

**Check:** a reviewer can reconstruct what they saw before a late transaction changed the assessment.

### P10.07 — Render freshness as an independent signal

**Write:** reusable `ui/components/freshness.py`.

1. Map freshness enum to explicit text, source reason and assessed-as-of timestamp; color is supplementary.
2. Show a retained score's original time and buffering/stale warning. For unavailable, show an em dash and explanation, never zero or a low-risk badge.
3. Show provisional escalation separately from the authoritative last complete assessment and indicate whether a later reconciliation is pending.

**Check:** stale/complete/unavailable states are distinguishable without relying on color or hidden tooltips.

### P10.08 — Scope caching to actor and immutable data

**Write:** API-read caching wrapper.

1. Cache only eligible read responses using actor/scope fingerprint, endpoint filters, explicit data/queue version and short TTL.
2. Do not cache credentials, unversioned case writes or mutable authorization decisions globally. Invalidate affected case views after accepted writes.
3. Prefer per-session caching for sensitive actor-specific records; public configuration/contract metadata can have a separate cache policy.

**Check:** two actors with different case scopes never receive one another's cached queue counts, notes or evidence.

### P10.09 — Connect login to a real API credential flow

**Write:** `ui/auth.py`, deployment identity adapter and `docs/identity_flow.md`.

1. Choose the organization's supported login route: Streamlit OIDC authentication or a trusted identity gateway. Configure issuer/client/callback/secrets in protected runtime config.
2. Define how the server obtains an API-audience access token for that specific logged-in user, through the approved gateway/BFF authorization-code/session flow. Native UI login or `st.user` claims alone are not an API bearer credential and must not be forwarded as proof.
3. Implement a `UserTokenProvider` that resolves the server-side authenticated session to a short-lived API token; verify session binding, expiry, logout and audience. If organization token exchange is unavailable, keep shared deployment blocked while local tests use isolated signed fixtures.

**Check:** a logged-in UI user can call only permitted API actions; a spoofed email/header or another user's session cannot impersonate them. Streamlit distinguishes identity authentication from authorization in [its official authentication guide](https://docs.streamlit.io/develop/concepts/connections/authentication).

### P10.10 — Exercise the analyst journey and failure states

**Write:** UI smoke scenarios and acceptance walkthrough.

1. Start API/database/worker/UI with synthetic data and perform upload, accepted validation, queue navigation, case evidence, disposition, history and authorized export.
2. Repeat with quarantine, an unavailable API, an expired identity, stale data, a new unavailable account and conflicting reviews.
3. Capture safe screenshots/checklist and persisted action IDs; inspect logs for accidental feature/note/token disclosure.

**Check:** the journey remains coherent after retries and corrections, and the walkthrough does not require editing database rows by hand.

**Phase 10 exit:** analysts can complete an audited review and understand evidence/freshness limitations through a functioning API-backed interface.

## Phase 11 — Event ingestion, durable buffering, and reconciliation

**Prerequisite:** event contracts, durable persistence and score publication. **Output:** safe correction of incomplete event-derived assessments.

### P11.01 — Implement an event-source interface and synthetic ledger

**Write:** `ingestion/event_source.py`, `tests/fixtures/event_ledger.py`.

1. Define source operations to read events/manifests from a recorded position, acknowledge durable receipt and resume after restart.
2. Build a seeded synthetic ledger with explicit transaction definitions, event IDs, sequences, epochs, account IDs and event/arrival times. Include empty periods with valid completeness heartbeats.
3. Implement a deterministic fixture feature builder/test scorer using those definitions. Do not pretend it reconstructs anonymous account-feature F-columns.

**Check:** timely and shuffled delivery contain the same source event identities and can be replayed from a saved position.

### P11.02 — Add event and reconciliation storage

**Write:** event migrations and repositories.

1. Add raw events, source checkpoints/epochs, sequence gap ranges, heartbeat manifests, account-window dependencies, feature versions, reconciliation jobs and publication outbox tables.
2. Enforce unique source/event identity and source/partition/epoch/sequence positions under the producer's documented uniqueness policy; store payload hash to detect collisions.
3. Index account/event-time windows and open gaps. Store completeness and last-complete score references independently from processing attempts.

**Check:** a new process can reconstruct all pending gaps/windows from the database; no correctness-critical buffer lives only in Python memory.

### P11.03 — Persist before acknowledgment and detect conflicting repeats

**Write:** `application/event_ingest_service.py`.

1. Validate identity and payload, append raw event/digest and accepted checkpoint metadata transactionally, then acknowledge durable receipt.
2. For repeated identity with identical payload, return the recorded ingestion outcome without applying features twice.
3. For repeated identity with different payload, create a conflict finding; require a proper correction event or source repair. Do not overwrite the original event.

**Check:** a crash before acknowledgment may cause redelivery but no duplicate effect; a contradictory repeat never silently changes a scored window.

### P11.04 — Implement contiguous-sequence tracking

**Write:** `reconciliation/gap_tracker.py`.

1. Maintain highest contiguous persisted position plus later received ranges for each source/partition/epoch. Receiving position 104 after 101 opens gap 102–103 rather than advancing completeness to 104.
2. Close gap ranges as missing positions arrive and advance contiguous progress only when each required sequence is present or formally source-reconciled.
3. Compare producer heartbeat/count manifests, handle new epochs explicitly, and quarantine excessive event-time clock skew. Maximum observed timestamp is only an observation, not a completeness guarantee.

**Check:** receiving 101,104,102,103 yields documented gap transitions and contiguous progress 101,101,102,104.

### P11.05 — Determine the real impact scope of missing records

**Write:** `reconciliation/dependencies.py`.

1. Map feature definitions to source partitions, account sets and windows. Persist the mapping used for each scored feature snapshot.
2. If source routing proves a gap belongs to one account, mark its dependent windows incomplete. If the missing event's account is unknown, mark all accounts dependent on that partition/window until source evidence narrows the impact.
3. Include downstream rolling windows and derived group features in the dependency expansion. Do not claim unaffected accounts without a defensible dependency boundary.

**Check:** a partition-level unknown-account gap cannot leave all but one guessed account marked complete.

### P11.06 — Separate the fast path from durable late-event work

**Write:** `reconciliation/router.py`, buffer repository.

1. Route proven contiguous complete input to normal aggregation; record out-of-order/gap events and impacted windows in durable pending work.
2. Start the ten-minute lateness timer from the declared event/window policy, track oldest unresolved gap and mark stale on grace expiry.
3. Keep unresolved events beyond ten minutes until reconciled/retained per policy. The grace interval is not a delete-after-ten-minutes TTL.

**Check:** a source outage longer than ten minutes creates visible stale state without silently discarding the records needed for later recovery.

### P11.07 — Compute completeness-aware source watermarks

**Write:** `reconciliation/watermarks.py`.

1. Use source-certified complete-through event time together with verified contiguous durable receipt and the lateness policy. Record the evidence supporting advancement.
2. For a feature window, evaluate every required source's coverage; use the conservative required-source minimum and keep open sequence/count discrepancies blocking completeness.
3. Close `[start,end)` only when all source contracts prove coverage through `end`. Idle sources need explicit completeness heartbeats, not fabricated progress from wall time.

**Check:** a fast source cannot close a multi-source window while another required source has an unresolved gap or missing heartbeat.

### P11.08 — Preserve complete and provisional assessments separately

**Write:** `application/freshness_service.py`.

1. Keep an immutable last-complete assessment pointer plus current data coverage/freshness. Do not relabel yesterday's score as complete for today's cutoff.
2. If partial data raises review priority, store a separate provisional assessment with explicit incomplete status and no adverse-action authority.
3. For no baseline, use unavailable. Disallow partial-data risk downgrades/closure; allow a lower assessment only after complete reconciliation and normal review policy.

**Check:** losing a decisive event cannot suppress an existing complete high-priority case; the UI continues to disclose baseline age.

### P11.09 — Reconstruct event-time features correctly

**Write:** `features/event_windows.py`, correction/reversal logic.

1. Query immutable source events for affected accounts and feature lookback windows; order by event time plus stable event identity for ties.
2. Apply versioned reversal/correction semantics, currency/unit rules and complete source coverage before computing counts, sums or order-dependent features.
3. Recompute every impacted rolling window, including later windows that include a late historical event. Incremental updates are allowed only when equivalent to full deterministic rebuilding.

**Check:** timely/full rebuild and delayed/reconciled feature vectors match, including a reversal near the window boundary.

### P11.10 — Enforce model-feature compatibility for events

**Write:** event feature signature adapter and scoring preflight.

1. Define the exact event-derived feature schema and its certified mapping to the model bundle's required inputs.
2. If no mapping exists for the current anonymous-feature model, stop at fixture feature/test-scorer validation; do not fill missing F-columns or invent a translation.
3. Adding genuinely new event features requires the training/evaluation/registry path again, with its own bundle signature.

**Check:** feeding transaction count/amount features to an incompatible snapshot model fails before inference.

### P11.11 — Commit corrected effects and checkpoints coherently

**Write:** `application/reconciliation_service.py`, outbox consumer.

1. Claim a window/version lease with fencing, build immutable corrected features and stage corrected scores outside the publication transaction.
2. In one transaction verify dependency version/completeness, insert feature/score versions, append audit/outbox and advance the processed checkpoint or window marker.
3. Acknowledge external consumption according to the chosen durable boundary and deduplicate retries. Deliver outbox messages at least once with idempotent consumers; do not claim cross-system exactly-once merely because Kafka is used.

**Check:** crash before/after commit produces either no visible correction or one complete correction, with replay resolving uncertain acknowledgment. See [Kafka delivery semantics](https://kafka.apache.org/design/) for the external-system boundary.

### P11.12 — Publish corrected queues without starving normal reads

**Write:** reconciliation queue publisher and worker resource configuration.

1. Feed corrected score versions into the existing queue builder; recalculate cohort ranks/percentiles and publish a complete snapshot.
2. Run reconciliation with its own concurrency, database pool and CPU budget; batch co-occurring corrections so one account/window is not rescored for every single arriving record.
3. Keep API reads on published versions and ordinary batch jobs on separate scheduling limits. Monitor backlog/age, not just worker success counts.

**Check:** replaying a late-event burst leaves the existing dashboard readable and normal batch work within the measured regression gate.

### P11.13 — Implement retries, dead letters, and capacity recovery

**Write:** retry policies, dead-letter repository, operator commands/runbook.

1. Classify transient database/source errors versus permanent contract/conflicting-payload failures. Retry transient work with bounded exponential backoff/jitter and a recorded attempt budget.
2. Persist dead letters with safe payload reference, reason and original source position. Repair/replay creates an audited action; operators cannot mark missing sequences complete without source evidence.
3. Recover expired leases on restart, monitor disk/buffer capacity, apply upstream backpressure, and retain raw replayability under the defined retention policy.

**Check:** worker restart, full buffer and unparseable event cause observable recoverable states rather than event loss or fake completeness.

**Phase 11 exit:** durable late-event recovery is integrated with source completeness, immutable scoring and queue publication.

## Phase 12 — Ten-minute replay and performance evidence

**Prerequisite:** phase 11 and a working dashboard/API. **Output:** measured correctness/overhead results with explicit limits.

### P12.01 — Freeze a replay scenario specification

**Write:** `config/replay/*.yaml`, `docs/replay_protocol.md`.

1. Define seed, source partitions, account population, event interval, feature lookbacks, eligible/affected sets, source delay fraction, throughput and fault selection strategy.
2. Freeze model/test-scorer version, band/threshold or K policy, comparison cutoffs and score tolerance. Use exact feature-vector matching for deterministic fixtures where possible.
3. Record hardware/resources, warmup, number/order of trials, and whether a result is synthetic engineering evidence or qualified predictive evidence.

**Check:** the scenario fingerprint fully determines event contents and delay assignments; changing difficulty creates a new scenario.

### P12.02 — Implement virtual-time correctness and real-time performance runners

**Write:** `reconciliation/replay.py`, `monitoring/timing.py`.

1. Use a priority queue ordered by scheduled arrival time/stable event ID. Advance the injected virtual clock, ingest due events and trigger scheduled completeness/reconciliation actions.
2. Simulate ten logical minutes without sleeping for unit correctness tests.
3. For actual latency/throughput runs use wall-clock paced ingestion and real worker/database scheduling; measure durations with monotonic timers. Never report virtual-clock speed as processing latency.

**Check:** logical state matches between runners at comparable checkpoints, while reports clearly identify which timing method produced each statistic.

### P12.03 — Produce the timely reference

**Write:** reference replay output writer.

1. Replay the frozen event set in timely order through the real services, not a separate idealized algorithm only used for comparison.
2. Save per-window complete feature vectors, scores/bands, queue members, source coverage, audit identities and timings.
3. Independently compute expected fixture aggregates for a small subset so a common bug in both reference and delayed pipelines does not pass unnoticed.

**Check:** reference counts match the source ledger, expected features and complete-window policy before any delayed comparison is attempted.

### P12.04 — Inject representative and adversarial delays

**Write:** delay/fault-profile generators.

1. Delay selected events by exactly 600 seconds in arrival time while preserving their original event time and payload.
2. Cover multiple affected fractions and source scopes, high-risk/high-value events, bursts, window cutoffs, reversals, duplicates, heartbeat loss and restart boundaries.
3. Include a scenario with decisive fraud-like synthetic evidence delayed; do not select only harmless events or so few accounts that 95% passes automatically.

**Check:** compare source event IDs/payload hashes across runs to prove the delay scenario changes arrival, not the underlying event set.

### P12.05 — Compare during the blind interval and after recovery

**Write:** checkpoint comparator.

1. At equal event-time cutoffs record the timely reference assessment and what the delayed system actually displayed: old complete, provisional, stale or unavailable.
2. After all records reconcile compare final windows and queues at the same cutoff/model version.
3. Report during-delay disagreement and time spent stale separately from final consistency. Explain that unseen decisive evidence makes unconditional unchanged real-time accuracy impossible to guarantee from buffering alone.

**Check:** a delayed decisive event can show temporary disagreement even if final reconciliation matches exactly; the report does not hide that interval.

### P12.06 — Report denominators that reveal affected-account failures

**Write:** `reconciliation/replay_metrics.py`.

1. Define all eligible records/accounts, directly affected accounts, conservatively impacted partition dependents, and authorized high-risk/positive subgroups before calculating rates.
2. Report matched score/band fractions for each denominator, plus unavailable/stale coverage and rank displacement.
3. Keep threshold/band comparisons separate from top-K membership so global rank movement is not mistaken for changed account-level inference.

**Check:** a fixture where all affected accounts fail cannot appear successful merely because most unaffected accounts match.

### P12.07 — Calculate final consistency and queue overlap

**Write:** comparison functions with explicit tolerance policy.

1. Align final reference/delayed rows by account/record, window, bundle and feature-policy version; count missing counterpart rows as failures/unavailable, not silently drop them.
2. Check feature equality, score tolerance and agreed risk-band equality, and compute `|topK_reference intersect topK_delayed| / K_effective` on the same eligible cohort.
3. Require at least 95% final consistency and top-K overlap under the scenario, while treating unexplained deterministic mismatches as defects to investigate.

**Check:** one changed score, one missing row and one moved queue member produce the expected different metrics.

### P12.08 — Measure all affected processing work fairly

**Write:** per-stage timing ledger and attribution rules.

1. Record monotonic service durations for validation/ingestion effects, initial feature work, reconciliation, inference, evidence and publication. Exclude deliberate source waiting and separate queue waiting; keep database/service wait inside a consistently defined operation boundary.
2. Attribute shared batch work by a predeclared rule such as equal eligible-record share or documented event-weight share, identically in timely/delayed runs. Also report total run CPU/service work to expose attribution artifacts.
3. Sum every attempt's attributed work per account before p95 calculation. Compare paired workloads; do not time only the last rescore while ignoring earlier processing.

**Check:** deliberately adding a redundant pre-reconciliation calculation raises measured overhead instead of disappearing from the metric.

### P12.09 — Measure normal-path and dashboard regression

**Write:** concurrent replay/API load runner.

1. During both reference and delayed runs issue the same authorized queue/case read workload and unchanged-account scoring traffic.
2. Save p50/p95/p99 service/response times, queue wait, stale duration, missed deadlines, resource usage, source receipt counts, duplicate effects and audit coverage.
3. Interleave repeated reference/delay trials with comparable warmup and report variability/confidence around the overhead estimate; a noisy single run cannot establish a 5% limit.

**Check:** resource starvation induced in a test is visible as unaffected/API regression even if final score equality remains perfect.

### P12.10 — Implement machine-readable acceptance gates

**Write:** replay report/gate evaluator.

1. Apply declared gates: >=95% final consistency and top-K overlap; <=5% affected p95 work overhead and unaffected p95 processing regression; zero lost/duplicate effects and partial-data downgrades; complete correction lineage.
2. Evaluate each scenario and important affected subgroup, retaining raw numerator/denominator and trial samples.
3. Return passed/failed/blocked/not-run explicitly. A failed gate stays open; do not change limits after viewing the result to obtain a pass.

**Check:** a deliberately failing fixture produces a failed report and nonzero acceptance command status.

### P12.11 — Validate the actual recovery-lag budget

**Write:** recovery-lag instrumentation and scheduling policy.

1. Measure original event time to corrected publication, decomposed into source delay, detection/scheduling wait, processing and publication wait.
2. Test the eleven-minute p95 target with a full ten-minute delay. A one-minute poll plus nonzero computation can exceed eleven minutes; use arrival-triggered reconciliation with bounded coalescing plus periodic recovery if measurements require it.
3. Confirm the same feature-window cutoff/source coverage is used in the comparison; do not compare an earlier closed window to a newer incomplete one.

**Check:** the measured decomposition explains deadline breaches; cadence configuration alone is never presented as a latency guarantee.

### P12.12 — Add real predictive validation when data permits

**Write:** qualified event-evaluation report adapter.

1. With approved event-feature mappings and mature outcomes, join timely/delayed predictions to outcome labels under the same observation policy.
2. Compare AP, P@K/R@K, false-positive/negative changes, coverage and uncertainty both during delay and after reconciliation.
3. Keep synthetic correctness, final consistency and predictive accuracy as separately named evidence. Until qualified data exists, mark predictive delay acceptance blocked.

**Check:** no report claims 95% unchanged real fraud accuracy solely from equality of deterministic fixture scores after recovery.

**Phase 12 exit:** replay artifacts establish exactly which resilience/performance claims are measured and which remain data-dependent.

## Phase 13 — Monitoring, drift, and retraining proposals

**Prerequisite:** instrumentation from prior phases. **Output:** actionable detection of stale/broken data and controlled model evaluation triggers.

### P13.01 — Complete instrumentation with bounded cardinality

**Write:** `monitoring/metrics.py`, request/job instrumentation wrappers.

1. Register counters, histograms and state gauges once per service process; instrument service boundaries rather than every dataframe loop.
2. Use bounded labels such as component, operation, outcome and known rule code. Keep account IDs, job IDs, raw values and arbitrary error text in safe correlated logs, not metric labels.
3. Define timestamp/duration units explicitly in metric names and avoid duplicating measurements under different meanings.

**Check:** processing thousands of distinct accounts does not create thousands of new metric series. [Prometheus instrumentation guidance](https://prometheus.io/docs/practices/instrumentation/) covers instrumentation and label considerations.

### P13.02 — Monitor completed work and missed schedules

**Write:** job metrics publisher and alert rules.

1. Publish counters for starts/outcomes/retries/rows and histograms for service duration. Maintain last successful completion timestamp per bounded job type/environment.
2. Detect overdue success using configured schedule and allowance; include a never-succeeded state so absence of prior success does not suppress the alert.
3. Expose failed/quarantined/pending/expired-lease counts from durable state rather than relying only on in-memory counters lost at restart.

**Check:** disabling a scheduled job fires overdue-success detection even though no explicit exception occurred.

### P13.03 — Monitor API and resource contention

**Write:** API middleware, pool/worker metrics and dashboard queries.

1. Measure request count, safe route-template outcome and response latency. Use normalized route templates, not raw case-ID URLs, as labels.
2. Observe database pool saturation, worker occupancy, memory/CPU and pending-job age with deployment-level collectors and application state.
3. Correlate slow requests with training/reconciliation contention. Set alert thresholds from phase 0/load evidence rather than invented universal values.

**Check:** an injected slow repository is visible in API latency and pool contention without exposing request payloads.

### P13.04 — Publish freshness and reconciliation signals

**Write:** `monitoring/freshness_metrics.py`.

1. Export event-arrival lag, heartbeat/watermark age, open-gap count, oldest-gap age, pending-window/buffer depth and reconciliation failures/duration.
2. Export counts by freshness state and correction outcome. Keep per-account diagnostic detail in restricted database reports.
3. Calculate ages from persisted event/source timestamps under known clock policy. Track invalid future timestamps separately rather than reporting negative lag as healthy.

**Check:** delayed fixtures visibly increase buffering/stale counts and recovery decreases them after complete publication.

### P13.05 — Implement versioned quality and drift comparison

**Write:** `monitoring/drift.py`, reference artifacts and thresholds.

1. Bind a baseline to model/data/source/time cohort; save reference schema, missingness, category distributions and fixed score/numeric summary bins learned on the reference.
2. Compute current comparable summaries, distribution differences, missingness shifts and unknown-category rates. Preserve per-feature detail in artifacts; expose bounded aggregate metric counts.
3. Assign critical contract violations to blocking policy and statistical warnings to investigation. Statistical drift does not itself prove lower fraud performance or authorize retraining/promotion.

**Check:** source-mix changes are identified as comparability issues, and an unexplained required-schema change blocks scoring.

### P13.06 — Build operator-focused Grafana dashboards

**Write:** `docker/grafana/provisioning/`, dashboard JSON.

1. Provision a Prometheus data source and dashboards for batch health, API/worker resources, validation failures, source freshness, reconciliation backlog and active deployment identity.
2. For every panel define metric/unit, expected interpretation and link to a restricted runbook or safe operations view.
3. Include no raw account values, confidential notes or export links in infrastructure panels. Use bounded environment/source/job filters.

**Check:** an operator can move from a stale-source panel to the correct recovery procedure without database access.

### P13.07 — Implement delayed-label performance reporting

**Write:** `monitoring/performance.py`.

1. Join original versioned predictions to latest eligible mature adjudicated outcomes as of an explicit reporting cutoff.
2. Calculate review-budget precision/yield, outcome counts, uncertainty and approved subgroup burden. Preserve reviewed-only selection and unknown-label denominators.
3. Publish population recall only when the outcome sampling/coverage supports it; do not infer it from the small reviewed queue.

**Check:** adding unresolved/unreviewed accounts changes coverage counts without automatically creating negative labels.

### P13.08 — Create retraining proposals instead of automatic replacements

**Write:** `application/retraining_proposal_service.py`.

1. Evaluate approved triggers such as enough new mature outcomes, persistent material drift, validated performance decline or revised feature definitions.
2. Deduplicate proposals by trigger/data/policy version, attach supporting reports and request an owner decision.
3. A permitted retraining run goes through candidate evaluation and approval phases 6–7; the trigger service cannot change the active bundle.

**Check:** repeated alerts create one tracked proposal and never silently replace the scoring model.

### P13.09 — Manage reference and acceptance-data releases

**Write:** `domain/evaluation_releases.py`, access-controlled dataset registry.

1. Track dataset release IDs, eligible time range, approved purpose, users who accessed labels and whether the release has been exposed in model selection.
2. Freeze model/config before authorizing final evaluation access and record that event.
3. Retire inspected final cohorts from untouched-acceptance status and request later representative releases for future independent decisions; keep historical reports immutable.

**Check:** a previously inspected acceptance release cannot be resubmitted as a new untouched final test.

### P13.10 — Exercise alerts and their recovery

**Write:** alert tests and `docs/runbooks/monitoring.md`.

1. Inject job silence, batch failure, missing heartbeat, watermark lag, growing buffer and drift breach into a synthetic controlled environment.
2. Verify rule pending/firing/resolved states, delivery to the configured approved channel, deduplication and runbook context. Notification destinations are organization configuration, not invented accounts.
3. Confirm safe correlation lets operators find the affected run/source/model and document recovery checks before closing the incident.

**Check:** alerts fire and resolve under observed failures; merely loading Grafana panels does not count. Rule behavior follows [Prometheus alerting documentation](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/).

**Phase 13 exit:** failures and freshness issues are visible, investigated through runbooks, and separated from controlled retraining/approval.

## Phase 14 — Deployment, security, release, and recovery

**Prerequisite:** integrated services and resilience evidence. **Output:** repeatable controlled deployment and tested restoration.

### P14.01 — Build images and Compose service topology

**Write:** `docker/Dockerfile`, `compose.yaml`, deployment overrides.

1. Build a Python application image from an approved pinned base and locked Linux dependencies; add required native LightGBM libraries and a built package wheel. Keep financial data, secrets and local artifacts out of build context.
2. Run API, UI and worker roles with distinct commands from the versioned application image; add dedicated PostgreSQL, MLflow, Prometheus, Grafana and reverse-proxy services.
3. Pin dependency images by reviewed version/digest and save a deployment manifest. Set startup health dependencies, while retaining runtime reconnect/retry behavior.

Examples of role commands after the corresponding entry points exist:

```text
API:    python -m uvicorn mule_detection.api.app:create_app --factory --host 0.0.0.0 --port 8000
UI:     python -m streamlit run ui/app.py --server.address 0.0.0.0
Worker: python -m mule_detection.cli work --job-types validate,train,score,reconcile
```

Implement the `work` polling dispatcher explicitly; it is not supplied by argparse or Docker. Compose waits for readiness only when appropriate health conditions are configured; see [Docker startup-order guidance](https://docs.docker.com/compose/how-tos/startup-order/).

**Check:** containers start from versioned configuration and the worker connects to durable job storage rather than process-local pending lists.

### P14.02 — Configure runtime isolation and resources

**Write:** container user/permissions, Compose resource/network/volume configuration.

1. Run application services as non-root with read-only code/bundle access and narrowly writable scratch/output locations. Use private networks and expose only approved ingress.
2. Put database, raw artifacts, models and backups on persistent encrypted host/managed volumes; volume existence alone does not provide encryption.
3. Limit CPU, memory, process count and database pools per role. Schedule heavy training separately or cap it so inference/UI/reconciliation have explicit capacity.

**Check:** an application process cannot read another service's secret files or write into the active model directory; contention tests confirm the configured limits.

### P14.03 — Implement TLS and the complete identity chain

**Write:** ingress configuration, identity adapter deployment, `docs/identity_flow.md` finalization.

1. Terminate trusted TLS and configure internal service authentication/TLS according to the organization boundary. Set upload/time limits and websocket support required by Streamlit.
2. Integrate the approved OIDC/session-to-API credential flow from P10.09. Validate callback URLs, token audiences, expiration/refresh/logout and service-account scopes.
3. Strip untrusted identity headers at ingress and prohibit API trust based solely on browser-supplied user/email headers. Restrict direct container access so gateway assumptions cannot be bypassed.

**Check:** requests bypassing ingress, spoofing headers, reusing expired tokens or changing audience cannot impersonate a user.

### P14.04 — Lock down artifacts, approvals, exports, and secrets

**Write:** service-role matrix, secret rotation procedure, storage ACLs.

1. Restrict bundle writes to model packaging/registry identities; inference gets read-only approved artifact access. Separate candidate creation from approval and operational retries from case-data permissions.
2. Use organization secret storage or protected runtime secret mounts; never bake passwords into source, image layers or command-line logs.
3. Test credential rotation with overlap/expiry and rollback. For private build dependencies use BuildKit secret mounts rather than `ARG`/persistent `ENV` secrets, as described in [Docker build secrets](https://docs.docker.com/build/building/secrets/).

**Check:** a retired credential fails after rotation and no inspection of image history exposes a live secret.

### P14.05 — Build durable scheduling and restart recovery

**Write:** worker polling loop, scheduler entry point and recovery job.

1. Schedule batch/reconciliation/backup requests with durable database idempotency keys for each due interval. Host scheduler or approved orchestration submits requests; it does not hold the only work state.
2. Poll eligible pending jobs, atomically claim leases/fencing tokens, update heartbeat and retry transient failures with bounded backoff.
3. On restart recover expired attempts safely, respect publication fences and inspect unfinished artifact staging. Graceful shutdown stops new claims before relinquishing/finishing active work.

**Check:** host/API/worker restarts preserve acknowledged pending work and cannot allow two expired/current workers to publish the same job.

### P14.06 — Build CI/CD around evidence and immutable images

**Write:** `.github/workflows/checks.yml`, build/release/deploy workflows.

1. Run lock installation, lint/types, contract/leakage/unit tests, PostgreSQL integration, authorization checks and a small synthetic end-to-end/replay suite on PRs.
2. On the protected release path, build the application wheel/image, create dependency/SBOM evidence, scan, sign or attest according to policy and push to a private approved registry.
3. Deploy an immutable digest to staging, run smoke/recovery checks and require the configured environment approval for the same digest's promotion. Never put private deployment secrets in untrusted PR jobs.

**Check:** failed tests/scans stop promotion; the deployed image identity matches the tested artifact rather than a rebuilt mutable tag.

### P14.07 — Rehearse migration and application rollback

**Write:** migration rollout procedure and release compatibility matrix.

1. Test upgrades from the currently deployed schema using synthetic/masked staging copies, including expected volume and locked-table impact.
2. Prefer expand/backfill/contract migrations so old/new application versions can coexist during rollout. Record whether a given revision supports application rollback; do not assume a destructive schema downgrade is safe.
3. Save previous image/config/model identities and a forward-fix path. Model rollback remains independently controlled from application deployment.

**Check:** a failed release can return to a compatible verified application or forward-fix without losing reviews, published queue identity or audit history.

### P14.08 — Implement consistent backups

**Write:** backup command, encrypted backup manifest and retention job.

1. Record a recovery manifest linking database backup, raw/model artifact digests, deployment/schema revision and source/reconciliation checkpoints. Coordinate separate operational/MLflow stores with a documented recovery boundary.
2. Use PostgreSQL's supported backup tools and protected credentials. Keep immutable artifact retention long enough that every retained database reference remains resolvable.
3. Encrypt, checksum and store backups in the approved separate failure domain. Define retention/deletion separately for data, scores, audit, models and exports; test with non-sensitive backup fixtures first.

The database dump/restore mechanism is documented in [PostgreSQL SQL Dump guidance](https://www.postgresql.org/docs/current/backup-dump.html).

**Check:** a backup manifest identifies every needed artifact and key reference; backup success means verified persisted files, not merely an exit message.

### P14.09 — Restore and replay into a clean environment

**Write:** `docs/runbooks/restore.md`, recovery validation command.

1. Provision an isolated destination, restore the selected database backups and required immutable artifacts, then verify schema and dependency versions before enabling traffic.
2. Validate published queue pointers, artifact hashes, approval records and audit continuity. Recover pending jobs/leases without treating old workers as live.
3. Replay uncertain source acknowledgments from checkpoints and verify deduplication/convergence. Measure actual recovery time and data-loss boundary.

**Check:** a restored analyst can open an earlier case/evidence version and delayed-event replay creates no duplicate corrected effect.

### P14.10 — Load-test the complete workload

**Write:** load scenarios and performance acceptance reports.

1. Generate safe synthetic wide batches at 10,000 and 100,000 rows with realistic types/missingness; record width and peak memory. Keep real-data quality claims separate.
2. Run scoring with explanation workload, API concurrency, scheduled jobs and late-event recovery under declared resource limits.
3. Collect start-to-publication latency, API p95, queue wait, memory, database contention and recovery backlog; compare against frozen phase 0 targets and phase 12 overhead definitions.

**Check:** reports identify actual bottlenecks and target breaches; passing a tiny row fixture is not evidence of capacity.

### P14.11 — Implement availability/RPO/RTO according to measured need

**Write:** `docs/service_levels.md`, approved resilience deployment decision.

1. Ask the owner to supply acceptable data loss, restore time and service hours; record unresolved values as blockers for contractual deployment.
2. Compare restore/load evidence to those requirements. A single host cannot provide host-failure continuity merely through container restart policies.
3. If requirements demand more, implement the architecture's managed/replicated PostgreSQL/artifact storage and separate app hosts, then test failover and split-brain/duplicate-worker behavior.

**Check:** the selected topology's recovery/failover evidence supports the stated service level; no invented SLA is attached to the prototype.

### P14.12 — Write runbooks that an operator can execute

**Write:** `docs/runbooks/` procedures for start/stop, failed batch, stale source, rollback, restore, retention, export, incident and credential rotation.

1. For each include symptom/alert, permission/prerequisites, diagnosis queries or commands, safe action, expected output, verification and escalation owner role.
2. Bind every destructive/irreversible operation to verified destination/environment and backup/approval prerequisites. Routine retries preserve idempotency rather than deleting failed history.
3. Have a second operator or a fresh controlled rehearsal follow the written steps and record gaps; fix the runbook and repeat the affected procedure.

**Check:** recovery succeeds without undocumented direct database edits or personal knowledge of the implementation.

**Phase 14 exit:** deployment, access, release and restore procedures are exercised and their measured limits are recorded.

## Phase 15 — Independent acceptance, shadow pilot, and operation

**Prerequisite:** implemented phases and qualified data/approvals for qualified claims. **Output:** an evidence-backed deployment decision.

### P15.01 — Assemble the acceptance dossier

**Write:** `docs/acceptance/<release-id>/index.md` and evidence index.

1. Copy the phase 0 requirements matrix into a release-specific view and attach executed test/report identities for each requirement.
2. Record passed, failed, blocked or not-run with reviewer/owner and reason; validate links and file digests.
3. Review all twelve architectural acceptance criteria explicitly, including future feed qualification and replay gates. Screenshots/code presence do not replace test/approval evidence.

**Check:** no requirement appears passed based only on a plan or a report from a different model/build/data version.

### P15.02 — Rehearse the complete research demonstration

**Write:** `docs/acceptance/research_walkthrough.md`.

1. Start from a clean approved environment and load a verified development-only batch or synthetic fixture.
2. Show validation, pinned bundle, queue, case evidence, review, audit, monitoring, late-event fixture and recovery through normal interfaces.
3. Keep research status/current cohort limitations visible and label final-fit demo scores as in-sample demonstration, not new evaluation.

**Check:** no presenter manually changes files/database state to make the path work and no holdout row enters the demo.

### P15.03 — Close data qualification dependencies with actual evidence

**Write:** signed source/label/dictionary references in the data-dependency registry.

1. Validate supplied stable IDs, snapshot grain, mature mixed-class time cohorts, feature availability and source definitions with the phase 2/4 rules.
2. Confirm approved dictionary coverage for every business explanation and documented identity/label correction semantics.
3. Link provider approvals and validation reports to each dependency. Keep unresolved critical items blocking qualified use, even if engineering completion is achieved.

**Check:** replacing the research tier requires source evidence and approved validation, not editing a manifest field by hand.

### P15.04 — Perform a genuinely independent final evaluation

**Write:** acceptance dataset release and evaluator report.

1. Freeze a representative later-period cohort, mature labels, group separation/purge rules and access controls before target-aware inspection.
2. Freeze the candidate pipeline/model/calibration/K policy and execute final evaluation once through the controlled evaluator.
3. Have an independent reviewer assess metrics, uncertainty and failure slices. A failed decision starts new development and a future acceptance release, not repeated tuning against exposed labels.

**Check:** acceptance reports include frozen model/data hashes and cannot be mistaken for the historical internal split diagnostic.

### P15.05 — Complete model-risk and investigation-policy review

**Write:** final model card, review records and signed operational policy.

1. Provide ranking/calibration evidence, error analysis, cohort/source probes, subgroup limitations, feature certification and explanation validation.
2. Let authorized reviewers approve thresholds/K, case escalation, correction/reopen behavior and permitted use scope. Record rejected/inconclusive findings and mitigations.
3. Bind approval to immutable bundle/data/policy versions and target environment; approval expires or reopens under defined material changes.

**Check:** the model-risk owner can identify the exact version/use that was approved and reasons it would be withdrawn.

### P15.06 — Complete organizational operating approvals

**Write:** security/access, retention, recovery, service-level and user-acceptance records.

1. Exercise role separation, identity flow, secret management, export restrictions and incident/runbook procedures with authorized stakeholders.
2. Review backup restore/failover evidence, capacity results, support roles and retention/deletion requirements.
3. Record actual sign-offs with scope and conditions. An engineer's passing tests do not substitute for compliance/security authority where organization policy requires it.

**Check:** every required operational gate has a genuine responsible approval and current evidence.

### P15.07 — Launch a bounded shadow pilot

**Write:** `docs/shadow_pilot_protocol.md`, pilot runtime configuration.

1. Define pilot accounts/source scope, dates, reviewer access, stopping conditions, support ownership and approved decision influence.
2. Score prospectively using qualified source contracts and preserve recommendations, freshness, corrections and independent review outcomes.
3. Observe performance/workflow without adding unauthorized automated actions. Stop or roll back on predefined critical data, security or safety failures.

**Check:** pilot outputs are distinguishable from production decisions and can be audited at their original observation cutoff.

### P15.08 — Measure actual analyst and operational outcomes

**Write:** pilot analysis report and performance dashboard.

1. Measure eligible/queued/reviewed counts, review duration, adjudicated yield, overturn/reopen rates and outcome maturity/coverage.
2. Join freshness, delayed corrections and source failures to queue/case outcomes. Investigate whether delay or stale scores shift reviewer workload disproportionately.
3. Separate reviewed-only findings from population metrics and show intervals/sample limitations; do not extrapolate global fraud capture from selected reviews.

**Check:** denominators and label availability are explicit for every business metric.

### P15.09 — Validate the delay requirement on representative events

**Write:** qualified replay/pilot delay acceptance report.

1. Use approved event features and a frozen compatible model to repeat phase 12 on representative ledger records and target hardware.
2. Evaluate during-delay accuracy/coverage as well as final consistency, ranking and processing overhead on the affected cohort.
3. If unchanged accuracy during missing decisive evidence is mandatory and the data does not support it, record the failed/blocked requirement and review feasible source redundancy/freshness/service-policy options; do not claim a buffering mechanism removes the information gap.

**Check:** the real delay claim is supported by actual outcome evidence, not synthetic score agreement alone.

### P15.10 — Make the explicit deployment decision

**Write:** `docs/acceptance/<release-id>/decision.md`, promotion transaction.

1. Aggregate data, ML, security, operational, analyst and delayed-event gate results for the intended use scope.
2. If all required gates pass, execute the authorized promotion/deployment and retain rollback identity. If any critical gate is blocked/failed, preserve achieved research/engineering status and name its closure dependency.
3. Audit actor, rationale, evidence hashes, target environment and approved policy. Do not translate a finished dashboard into production-model approval.

**Check:** the deployment's visible status and allowed actions match the decision record and enforced model/runtime policy.

### P15.11 — Operate through versioned changes and rehearsals

**Write:** recurring operations checklist and change records.

1. Monitor source/data/model/application versions independently and retain the exact tuple used for every assessment.
2. Route retraining through candidate evaluation/approval, application changes through CI/staging release and source-contract changes through validation/compatibility review.
3. Repeat access reviews, restore/failover exercises, incident rehearsals and acceptance-data renewal on the organization's approved cadence; record results and reopen failed requirements.

**Check:** a new model, application image or source definition can be traced, evaluated and rolled back without rewriting prior evidence.

**Phase 15 exit:** the complete system's authorized use is supported by actual data, software, operational and human approval evidence.

## Appendix A — Concrete project interfaces to implement

Use narrow interfaces so later adapters do not change business behavior. These signatures are design contracts to implement, not preexisting package functions:

| Interface/module | Operation | Required behavior |
|---|---|---|
| `Clock` | `now()` | Return timezone-aware UTC under injectable time |
| `RawStore` | `stage(stream)`, `finalize(staged, digest)` | Bounded durable write, no mutable overwrite |
| `BatchValidator` | `validate(frame, manifest, context)` | Structured findings, no model fitting |
| `FeaturePipeline` | `fit(X,y=None)`, `transform(X)` | Training-only learned state, frozen inference |
| `BundleLoader` | `load(ref, environment)` | Trusted digest, signature and approval checks |
| `ModelResolver` | `resolve(alias, environment)` | Immutable approved model identity |
| `UnitOfWork` | context enter/commit/rollback | One business/audit transaction |
| `ScoringService` | `request_score(request, context)` | Idempotent durable job submission |
| `PublicationService` | `publish(run_id, expected_version, fence)` | Atomic complete queue switch |
| `ReviewService` | `submit(case_id, request, context)` | Permissions, optimistic version, idempotency, audit |
| `EventSource` | `read(position)`, `ack(position)` | Replayable ingestion boundary |
| `CompletenessService` | `coverage(window, dependencies)` | Evidence-based required-source completeness |
| `ReconciliationService` | `reconcile(window_id, fence)` | Deterministic reconstruction + atomic correction |
| `ReplayRunner` | `run(scenario, mode)` | Timely/delayed comparable evidence |

Implement protocols/abstract interfaces where multiple adapters are real requirements; avoid creating a separate abstraction for every private helper.

## Appendix B — Example policy and transaction structures

The following YAML is a **synthetic research configuration example**, not a production policy or measured threshold report. Complete its schema and wire it through settings before using it.

```yaml
policy_version: research_review_v1
environment: research
data_tier: research
review:
  top_k: 50
  sort: [raw_score_desc, record_key_asc]
  percentile_definition: descending_rank_linear_v1
scores:
  output_kind: review_priority
  calibrated_probability_enabled: false
  missing_baseline: unavailable
reconciliation:
  allowed_lateness_seconds: 600
  recovery_scan_seconds: 60
  arrival_triggered: true
  partial_data_downgrade_allowed: false
  unknown_gap_scope: all_dependent_windows
```

An optimistic case update uses the database's affected-row count, not a prior read followed by an unconditional overwrite:

```sql
UPDATE cases
SET workflow_state = :new_state,
    version = version + 1,
    updated_at = :now
WHERE id = :case_id
  AND version = :expected_version;
```

Execute that update only after permission/transition checks, inside the same transaction as immutable review/audit inserts. If no row updates, roll back and return conflict. A separate idempotency record must distinguish a legitimate retry after success from a stale fresh request.

Suggested findings structure, with **synthetic values only**:

```json
{
  "rule_id": "SCHEMA_REQUIRED_FIELD",
  "rule_version": "1",
  "severity": "ERROR",
  "affected_count": 2,
  "safe_message": "Required qualified account identifiers are missing",
  "blocks": ["qualified_ingestion", "scoring"],
  "raw_rows_included": false
}
```

## Appendix C — Per-phase verification and execution commands

Run commands only after their referenced code/config/fixtures exist. Replace angle-bracket arguments with recorded IDs or approved paths; do not execute these examples as a claim that implementation has already been completed.

```text
Phase 1:  python -m pytest tests/unit -q
Phase 2:  python -m pytest tests/contracts -q
Phase 3:  python -m alembic upgrade head
Phase 3:  python -m pytest tests/integration/test_persistence.py -q
Phase 4:  python -m mule_detection.cli validate-batch --manifest <manifest-path>
Phase 5:  python -m pytest tests/unit/test_feature_boundaries.py -q
Phase 6:  python -m mule_detection.cli train --config <config-path> --mode research
Phase 6:  python -m mule_detection.cli evaluate --run-id <run-id>
Phase 7:  python -m pytest tests/integration/test_registry.py -q
Phase 8:  python -m mule_detection.cli score --batch-id <id> --model-version <version>
Phase 9:  python -m pytest tests/integration/test_api.py -q
Phase 10: python -m streamlit run ui/app.py
Phase 11: python -m mule_detection.cli reconcile --source <source-id>
Phase 12: python -m mule_detection.cli replay --scenario <scenario-path>
Phase 14: docker compose config
Phase 14: docker compose up -d
Phase 14: python -m mule_detection.cli health
```

The existing reference script can run independently after its dependencies are installed. Always choose a new output directory for comparison runs:

```powershell
python scripts\pre_architecture_verification.py --benchmark --output-dir artifacts\reference_comparison_new_run
```

Before invoking that command, ensure the chosen directory does not already hold reviewed evidence; choose a unique run directory rather than overwrite it.

## Appendix D — Completion evidence and handoff discipline

For each point `Pxx.yy`, keep a record in `docs/acceptance/roadmap_status.csv` with these columns:

```text
point_id,status,code_revision,files_changed,test_or_review_command,
result,evidence_path,blocking_dependency,reviewer,checked_at
```

Store one CSV row per point; the wrapped header above is for display. Allowed statuses are `PLANNED`, `IN_PROGRESS`, `PASSED`, `FAILED`, `BLOCKED`, and `NOT_RUN`. An implementation task may be passed with a qualified deployment gate still blocked; state those scopes separately.

Before closing a phase:

1. Confirm every mapped point has its files, implemented behavior and meaningful checks.
2. Exercise the previous phase's integrated path against the new changes.
3. Record unresolved external dependencies and prevent unsupported promotion through enforceable policy.
4. Update the architecture if a genuine design decision changed; update this roadmap's implementation detail when only the construction approach changed.
5. Hand off exact run/config/model/data identities and the next phase's prerequisites, not an informal statement that everything works.

The first build action is P00.01. Continue through the documented prerequisites and use the evidence register to decide when each phase is ready to close.
