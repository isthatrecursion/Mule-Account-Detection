# Phase 1 development foundation

Phase 2 adds [versioned contracts and source compatibility](contracts.md). Run `python scripts/verify_contracts.py --output-dir artifacts/phase2/<new-run-id>` for the integrated synthetic suite, generated-schema freeze checks and wheel build. The optional `--with-research-data` path validates the preserved local adapter using aggregate-only evidence; CI never needs it. See [Phase 2 handoff](acceptance/phase2_readiness.md). Phase 3 adds [PostgreSQL setup, migrations and persistence checks](persistence.md), including explicit dedicated test database credentials.

Python 3.12 is the supported baseline. The five ML versions are pinned to the **saved** Stage 9 report: NumPy 1.26.4, pandas 2.2.3, scikit-learn 1.5.2, LightGBM 4.7.0 and SciPy 1.17.1. Changing them requires separate parity evidence. Phase 3 adds locked SQLAlchemy/Alembic/psycopg and cryptography dependencies. PostgreSQL persistence can now run locally; API/UI, MLflow and scoring services remain later work.

## Install and verify

Windows PowerShell from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev-windows.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe scripts/verify_foundation.py --output-dir artifacts/phase1/my_new_run
```

On Linux use `python3.12 -m venv .venv`, `.venv/bin/python` and `requirements-dev-linux.lock`. Runtime-only installation uses `requirements-windows.lock` or `requirements-linux.lock` followed by a built wheel with `--no-deps`. Never copy a Windows environment into Linux. Build tools are pinned in the dev lock and pyproject; hashes lock transitive distributions. Every saved verification run has a new directory; existing evidence cannot be overwritten.

`python -m build --no-isolation` builds with the locked backend. Install the resulting wheel into a fresh environment from the platform runtime lock and import it from outside the checkout. No raw CSV is required to install, build or run the fast tests. PostgreSQL/benchmark tests are separately marked and are not implemented as fake passing integrations. GitHub Actions checks the Windows/Linux matrix without LFS financial data or private credentials; its remote execution remains NOT_RUN until pushed and observed.

To regenerate each lock, run on its target OS under Python 3.12 with the pinned pip-tools/build environment:

```text
python -m piptools compile --generate-hashes --strip-extras --no-emit-index-url --no-emit-trusted-host --output-file requirements-<platform>.lock pyproject.toml
python -m piptools compile --extra dev --constraint requirements-<platform>.lock --allow-unsafe --generate-hashes --strip-extras --no-emit-index-url --no-emit-trusted-host --output-file requirements-dev-<platform>.lock pyproject.toml
```

`--allow-unsafe` pins pip/setuptools rather than leaving build tools unresolved. Review all lock changes; dev resolution is constrained by the runtime lock. [pip-tools cross-environment guidance](https://github.com/jazzband/pip-tools#cross-environment-usage-of-requirementsinrequirementstxt-and-pip-compile) explains why locks are generated separately.

## Settings and secrets

`load_settings` is the only loading boundary. Select the environment through `--environment`, then `MULE_ENVIRONMENT`, then `local`; conflicting explicit/environment selectors fail. Environment files live under `config/environments`. For field values the priority is process `MULE_*` variables, explicitly selected dotenv, explicitly selected secrets directory, YAML runtime fields, then typed defaults. Dotenv is never loaded implicitly. A dotenv file does not select a different environment: pass `--environment research` when using a research dotenv. This precedence uses [Pydantic settings sources](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

Mandatory `MULE_DATABASE_URL` and `MULE_MLFLOW_URI` are injected as secret endpoint values. They are never committed in YAML, printed, or included in the public configuration fingerprint. The PostgreSQL URL uses `postgresql+psycopg://`; tracking uses HTTP(S). `.env.example` contains uncredentialed localhost examples, not deployed services. Use a secret file named `MULE_DATABASE_URL` under an explicitly selected private directory when needed.

Paths resolve exactly once against `--root` (default current directory), remain inside that root and are checked for readable policies and writable artifact storage. Negative/nonpositive limits, unknown environments, missing endpoints, contradictory policies and research model restrictions in staging/qualified fail with `CONFIGURATION_INVALID`. The configuration fingerprint covers nonsecret effective settings and policy contents. Real secret files, exports, operational volumes, private fixtures and model outputs are ignored by Git. Docker's independent allowlist omits raw CSVs, EDA artifacts, secrets, exports and virtual environments.

`model_tier` is a requested loader restriction, never a declaration of actual approval. A qualified configuration can be parsed for future engineering; it does not approve a model or authorize deployment. Actual data/model tiers must still come from immutable validation/approval records in later phases. Critical dependencies, self-approval, alias changes and research bundles cannot be waived by runtime configuration. Qualified operation remains blocked by the Phase 0 dependencies.

## Commands and error handling

```powershell
.\.venv\Scripts\python.exe -m mule_detection.cli --help
.\.venv\Scripts\python.exe -m mule_detection.cli --dotenv .env health
```

Global options precede the subcommand. `health` checks configuration and local policy/storage access only and returns `foundation_only`, `operational_readiness: NOT_IMPLEMENTED`, `qualified_approval: NOT_GRANTED`. It does not connect to PostgreSQL/MLflow or report the future system healthy. Copy `.env.example` to a local `.env` before the example command. The current actor `local-cli` is execution lineage, not authenticated bank identity.

`validate-batch --manifest`, `train --config --mode`, `evaluate --run-id`, `score --batch-id --model-version`, `reconcile --source`, and `replay --scenario` parse typed requests then fail explicitly with `UNSUPPORTED_OPERATION` until their services exist. IDs parse as UUIDs; bad arguments never dispatch. Exit codes: 0 completed foundation command, 1 internal failure, 2 bad arguments, 3 invalid configuration, 4 unimplemented operation. Ordinary logs are JSON on stderr; compact results/errors are on stdout. Correlation IDs link both. Arbitrary messages, credentials, rows, analyst notes and exception tracebacks are excluded from ordinary logs; sensitive diagnostics need a separately secured facility in later phases.

Wall time is injected as a UTC `Clock`; `ManualClock` advances logical intervals instantly. Compute duration uses `MonotonicTimer`, independently of virtual/event time. Frozen execution context carries actor/environment/correlation identity. Audit uses the controlled application clock; worker leases use PostgreSQL `clock_timestamp()` so different workers agree on expiry.

## Reference preservation and handoff

`docs/reference_manifest.json` hashes the raw dataset, split, exclusion register, historical verification script, Stage 9 authority and saved benchmark files in streaming chunks, with sizes and the environment copied from the historical report. `python scripts/reference_manifest.py --verify` checks unchanged evidence on the approved local machine; CI does not need those files. Creating the manifest refuses overwrites and never reruns the historical benchmark. New comparison runs must use distinct directories and document any intentional change.

The Phase 0 checker now permits later roadmap points to progress when they link real evidence; unbuilt points still remain PLANNED/NOT_RUN. This is an intentional validation-only change so Phase 1 progress does not invalidate the Phase 0 traceability check. Original Phase 0 evidence and source fingerprints remain immutable.

Phase 2 implements actual batch/label/model/event contracts and input validators. Source qualification, representative temporal evaluation, model approval, application services and operational deployment are still later work. Phase 1 completion cannot close any external data dependency or certify ML performance.
