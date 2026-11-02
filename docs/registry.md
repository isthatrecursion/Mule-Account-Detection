# Model bundles and registry

Phase 7 implements research final fitting, encrypted content-addressed bundles,
authenticated MLflow tracking, independent operational decisions, job pins and
audited deployment/rollback. Current data cannot qualify for shadow or pilot use.
Scores remain research review priorities; final-fit demonstration outputs are
in-sample. The Phase 6 OOF report remains the diagnostic evaluation evidence.

## Packaging and trust

`fit_frozen_research` authenticates the frozen selection and original training
request, including predictor values, labels, development membership, split,
feature policy and semantic rules. It creates a fresh pipeline and estimator;
it never copies a fold transformer or accesses holdout labels. Research final
fitting uses the entire authorized development partition once.

`write_bundle` stages preprocessing, estimator, signatures, encoded-to-raw feature
mapping, training reference distributions, model card, source/dependency identity,
lineage, policy and a prediction fixture. Each artifact is AES-GCM encrypted with
its logical filename as authenticated data. `bundle.json` records ciphertext and
plaintext hashes/sizes and the versioned `model_bundle_v1` contract. The directory
identity is SHA-256 of that manifest. Publication never overwrites an identity.
A saved-bundle worker parity check must pass before candidate registration.
An interrupted/failed packaging attempt can leave an unapproved orphan; never
approve or select it merely because a directory exists.

Inference authorization comes from PostgreSQL decisions bound to digest and
environment. A checksum beside an arbitrary uploaded pickle grants no trust.
The loader accepts only the configured storage root and an independently allowed
digest, verifies the entire inventory and hashes, then starts a fresh worker.
The worker checks exact Python/library versions and signatures before joblib
deserialization, verifies fitted feature/model consistency and runs the fixture
with absolute tolerance 1e-12 and relative tolerance zero. Subsequent predictions
recheck authorization. This deliberately favors compatibility checks over silent
loading under a different runtime.

The worker has a private working directory and pipe, an environment allowlist
without database/tracking secrets, CPU/process-memory limits and a timeout.
Windows uses a Job Object; Unix uses resource limits. Models are trusted code:
this process separation is not a complete hostile-pickle sandbox. Protected host
ACLs/container permissions and a separate service identity remain necessary for
shared deployment. Do not grant artifact keys or storage writes to analysts.

## Local service setup

Use the existing Python 3.12 locked environment and local PostgreSQL setup.
The training dependency versions and lock files remain unchanged by Phase 7.
MLflow runs separately as version 3.17.2 with a digest-pinned base image, its own
database role/database, a controlled Docker artifact volume, basic authentication
and a loopback-only port. The application uses its REST API rather than adding
the MLflow client and its transitive dependencies to the model environment.

```powershell
.venv/Scripts/python.exe scripts/init_registry_secrets.py
docker compose -f compose.yaml -f compose.local.yaml -f compose.registry.yaml up -d --build --wait
$env:MULE_MIGRATION_DATABASE_URL_FILE='secrets/migration_database_url'
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe scripts/provision_model_approver.py
```

Provisioning creates the separate `mule_model_approver` role with only decision
append, retirement, audit/outbox append and required reads/row-lock privileges.
Its protected connection file is never substituted with runtime or migration
credentials. Training/runtime cannot insert decisions, retire candidates, update
evidence, or gain approval by changing MLflow tags. CLI approval is local-only;
shared identity/authentication and TLS belong to the later deployment phases.
Do not copy the local approval secret into training workers or runtime containers.

## Commands

After an accepted research batch has a successful frozen training run:

```text
mule-detection package-model --batch-id <uuid> --run-id <training-uuid> --name research_model
mule-detection approve-model --candidate-id <uuid> --target-environment research --target RESEARCH_DEMO --reason <review-reference> --request-id <uuid>
mule-detection deploy-model --candidate-id <uuid> --target-environment research --alias active --expected-version 0 --reason <deployment-reference>
mule-detection reconcile-model --candidate-id <uuid>
mule-detection reconcile-model-alias --target-environment research --alias active
```

Root-level CLI settings/environment options precede the command. Package retries
reuse the existing candidate for that training run and actor instead of refitting.
Approval retries use actor/request identity and reject changed request content.
Research approval is a separate deliberate operation; packaging grants none.

## Recovery and lifecycle

Registration records `PENDING` before HTTP writes, then `IN_FLIGHT`; successful
registration atomically stores registry name/version/run/digest and an audit.
Timeouts become `UNCERTAIN`. Reconciliation searches the immutable request tag
and digest, recovers an already-created remote version and rejects conflicting
or duplicate mappings. It never blindly creates another version after an
uncertain attempt. If a failure occurred before version creation, reconciliation
remains blocked for operator review: inspect the tagged MLflow run/artifacts,
complete the matching remote version under controlled procedures, then retry.
Do not reset an uncertain intent to pending or delete evidence to force a retry.

Candidate decisions are append-only and follow the declared lifecycle. Qualified
states require an independent reviewer, qualified data, approved environment,
identity/dictionary/label/availability and representative-cohort references,
metrics and independent acceptance, threshold policy and security/model-risk
review. Missing evidence produces explicit `BLOCKED` reasons. Current research
evidence always carries cohort/source limitations; perfect AP cannot bypass them.
The current packager only creates research/synthetic candidates, so qualified
promotion remains unavailable pending a certified adapter and reviewed evidence.

The operational deployment record is authoritative. MLflow aliases are mirrors;
manual retagging cannot authorize a model. A mirror failure after DB commit leaves
the audited DB selection intact; run `reconcile-model-alias` to repair it.
Deployment uses an expected version to reject stale changes and fixture health
before changing future selection. See the [rollback runbook](runbooks/model_rollback.md).

`ModelResolver.pin` records the candidate, digest, remote version, decision,
environment and deployment version on a durable job. Alias changes do not alter
existing pins. `revalidate` locks the candidate and rechecks current permission
inside the future Phase 8 publication transaction; retirement blocks publication
without swapping the estimator. Phase 7 supplies these APIs; chunked scoring,
explanations and atomic score/queue publication are Phase 8 work.

## Verification

```text
python scripts/verify_registry.py --connections-file secrets/docker_test_connections.json --with-mlflow --with-approver --output-dir artifacts/phase7/new-verification
```

The connections file must name a dedicated `mule_test_*` database. Tests reset
only that database and use synthetic rows. For a nondefault administrator secret
filename, pass `--approval-admin-file <protected-file>` to the verifier or
`--admin-url-file <protected-file>` to the provisioning script. No administrator
endpoint enters application approval services.

Without `--with-mlflow`, the explicit live-server test is skipped;
`--with-approver` separately opts into provisioning and exercising the local
minimal approval role in that test database. The fake-server recovery/rollback
checks still run.
CI is configured for Linux live-server checks and Windows/Linux unit checks;
local Windows evidence does not claim remote CI or Linux execution.

The local numerical research proof has a separate opt-in command:

```text
python scripts/run_registry_experiment.py --run-id <frozen-run-uuid> --with-research-data --output-dir artifacts/phase7/new-research-proof
```

It decrypts the original local Phase 6 evidence, fits development rows only,
packages a private encrypted bundle, verifies saved fixture parity and emits a
public aggregate/hash report. It creates no operational decision or deployment.

MLflow behavior follows its official [REST API](https://mlflow.org/docs/latest/api_reference/rest-api.html)
and [authentication configuration](https://mlflow.org/docs/latest/self-hosting/security/basic-http-auth/).
