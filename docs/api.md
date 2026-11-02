# Authenticated review API (Phase 9)

The API admits durable work and serves scoped review evidence. It does not approve models, restrict accounts, file reports, or turn review conclusions into fraud labels. Research results retain their unknown cutoff, stale freshness and unverified feature meanings.

## Startup and trust

Install the API lock in addition to the matching development lock when developing:

```powershell
python -m pip install --require-hashes -r requirements-api-windows.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m mule_detection.api.server --root . --environment research
```

Linux uses `requirements-api-linux.lock`. Both API locks constrain the existing model runtime; the four original runtime/development locks remain unchanged.

Normal startup requires `secrets/oidc.json`. The organization has not supplied its issuer, API audience, HTTPS JWKS URL or group-to-role/scope mapping. **Startup therefore remains fail-closed.** `config/oidc.example.json` is an incomplete template, not usable trust configuration. No test issuer, signing key or permissive default is substituted. Complete the template with the identity owner’s actual settings when available. Each group maps to explicit `roles` and `scopes`; role permissions stay bound to that group’s scopes, including combined-role users. An optional `permissions: ["export:sensitive"]` may be granted explicitly to a reviewer group for its own scopes.

The verifier allows configured RS256/ES256 algorithms, checks signatures and issuer/audience/subject/expiry/issued-at/not-before, and selects keys only from the configured JWKS source. It rejects token-supplied remote key URLs, unsigned tokens and unsupported critical headers. HTTPS JWKS fetches have a five-second timeout, no redirects, a one-MiB body bound, at most 100 keys and a cache lifetime of at most five minutes. Unknown-key refreshes are throttled. OIDC role/scope/actor headers have no authority. Subject identifiers become issuer-bound opaque actor IDs.

`create_app(settings=None, service_factory=None)` composes a fresh application without a global app or service singleton. Injected service factories and static test JWKS require an explicitly isolated `test` application; normal `test` startup also requires real trust configuration. The OpenAPI artifact is `contracts/api_openapi_v1.json`; interactive docs and unauthenticated live schema routes are disabled. Regenerate/check it with `python scripts/generate_api_schema.py [--check]`.

## Endpoints and permissions

| Route | Authority and behavior |
| --- | --- |
| `GET /health/live`, `/health/ready` | Safe liveness; readiness checks revision 0009, PostgreSQL and encrypted storage probes. |
| `GET /v1/me` | Verified identity and effective server grants. |
| `POST /v1/batches` | Operator intake; raw `application/octet-stream` body, `X-Batch-Manifest` JSON header and optional `X-Filename`. Registered source scope required. Returns 202 after encrypted upload and PostgreSQL job commit. |
| `GET /v1/batches/{id}` | Operator/engineer, scoped batch status and accepted validation identity. |
| `POST /v1/scoring-runs` | Operator, accepted scoped batch plus immutable bundle digest; returns a durable job. |
| `POST /v1/training-runs` | Engineer, accepted scoped batch; training policy is server-owned `config/model_candidates.yaml`. Candidate creation conveys no model approval. |
| `GET /v1/jobs/{id}` | Kind-specific permission and scope. Safe state, creation time, latest 20 attempt numbers/times and sanitized result. |
| `POST /v1/jobs/{id}/retry` | Operator retry plus the original operation permission, original actor and current scope. Failed jobs only; reason required. |
| `GET /v1/queues` | Analyst/reviewer; discover explicit current queue versions. At most 100 heads. |
| `GET /v1/queues/{version}/cases` | Analyst/reviewer; explicit immutable queue UUID and bounded keyset page. |
| `GET /v1/cases/{id}`, `/evidence` | Analyst/reviewer; selected score, batch/model/bundle/policy/dictionary/snapshot identity, completeness, cutoff and freshness. Scope checked before evidence access. |
| `POST /v1/cases/{id}/assignment` | Analyst self-assignment or reviewer assignment within the reviewer’s scope. Assignee must be a known enabled identity with scope and review permission. |
| `POST /v1/cases/{id}/start-review`, `/reviews` | Assigned actor; explicit ASSIGNED → IN_REVIEW → REVIEWED workflow. |
| `POST /v1/cases/{id}/reopen` | Reviewer within the case scope; append a new version and assignment. |
| `GET /v1/cases/{id}/history` | Separate `kind=reviews|scores|audit` pages; audit requires scoped auditor/reviewer authority and omits notes. |
| `POST /v1/outcomes` | Reviewer permission plus independently configured approved source ownership and stable identity mapping. |
| `POST /v1/exports`, `GET /v1/exports/{job_id}/download` | Reviewer export scope and reason; actor-only, expiring download with current permission checks. |
| `GET /v1/models/{id}` | Scoped analyst/reviewer metadata for models used in authorized batches. No executable paths or approval mutation. |

All mutations require UUID `Idempotency-Key`. Review writes also require `expected_version` (cases start at zero). Repeating identical requests returns the original effect; changed payloads or stale versions return 409. Inputs reject extra actor/permission/path fields. Errors contain static codes and a request UUID, without validation input, rows, SQL, credential or storage locator details. Unknown and out-of-scope objects return the same 404. HTTP role denials return 403.

Queue cursors contain `(after_rank, after_key)` and must include both values, with the same queue UUID. Limits are 1–100; allowed filters are state and assignee. Scope and filters apply before count and pagination. A new head does not switch an open case’s selected score. The case exposes a newer-score reference and score history instead. Mutable workflow filters can change membership between requests even while assessment membership/ranks remain pinned. Histories append in stable order and use bounded offsets. No read response contains raw storage URIs.

## Worker durability

Run a separate worker invocation to process the next pending or expired leased job:

```powershell
python -m mule_detection.api.server --root . --environment research --worker-once
python -m mule_detection.api.server --root . --environment research --worker-once --job-id JOB_UUID
```

Schedule repeated invocations in the deployment’s process supervisor. HTTP requests never fit or run models. PostgreSQL jobs, task payloads, encrypted uploads, attempt history and fencing tokens survive process restarts. Advisory slots enforce `worker_count` across worker processes. A heartbeat renews long-running job leases; publication rechecks the active fence. Training/scoring use the existing accepted-input and immutable-bundle services. No CLI actor is reused for API work.

Jobs store verified grants, their expiration and the authorization policy hash, without bearer tokens. Workers recheck identity disablement, scope, operation permission, expiry and policy before effects and before acknowledgement. Identity grants are locked during final publication. Expired/revoked work fails safely and requires a newly authorized retry; it never runs with fallback authority. Policy changes require retry under the new policy. A genuinely interrupted training artifact remains immutable; if its candidate store cannot resume, submit a new training request rather than overwriting it. Research-only adapter gates remain enforced in staging/qualified environments.

Legacy CLI batches are not assigned guessed API scopes. A source owner must register the appropriate `batch_access` binding through a reviewed operational migration before exposing such data.

## Review notes, outcomes and exports

Notes are bounded to 4,000 characters, reject unsupported controls, and live in authenticated encrypted artifacts. Case update, review event, note metadata and audit/outbox append commit together. An unsuccessful database transaction can leave an unreferenced encrypted object for controlled retention cleanup, never a partial review. Reopening appends history; it does not edit a prior event or score. Review conclusions have no label-table write path.

Adjudicated outcome ingestion is disabled until `secrets/outcome_sources.json` contains approved source entries. Each entry binds `owner` (verified opaque actor ID), `scope`, `approval` reference and `identity_map` (record key → stable account identity). This file is service-owned; request bodies cannot approve a source. Each submission supplies `source_id`, UTC `known_as_of` and versioned `label_v1` contracts. Identity, owner, source, status, maturity, cutoff and supersession chain are validated before the label, contract, submission provenance and audit commit atomically. Corrections append; as-of selection never reads later-known corrections into an earlier cutoff. Review-selected adjudications are marked `population_recall_evidence: false`. They do not automatically change existing training targets or confer representative label coverage.

Exports pin queue version, case state at authorization, scope, actor, selected columns, filter and reason hash. Default columns omit record keys and notes. Sensitive columns require an explicit `export:sensitive` grant at creation and download. The encrypted snapshot is immutable. Downloads expire ten minutes after authorization and return CSV only to the requesting actor with current permissions/scope. Every authorization/download is audited. Batch/run/bundle/policy/cutoff/freshness metadata accompany rows. Formula-like strings (including whitespace-prefixed formulas) are escaped; genuine numeric cells retain their numeric representation. CSV quoting preserves Unicode, commas and multiline notes.

## Verification

`scripts/verify_api.py` runs lint/format/type checks, all synthetic tests, schema drift checks, specification checks and wheel/sdist construction. With an explicit dedicated test connections file it also runs the PostgreSQL HTTP/worker tests and prior-phase regressions. `--with-mlflow --with-approver` exercises the existing authenticated registry and separate approval-role tests. `scripts/verify_installation.py --api` checks a fresh hashed API environment and installed-wheel signed-token HTTP behavior outside the checkout.

The local tests use ephemeral signed test tokens and dedicated PostgreSQL roles. Live organization OIDC integration, shared deployment, remote CI, representative production quality and latency acceptance remain unclaimed.
