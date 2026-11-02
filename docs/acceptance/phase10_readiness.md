# Phase 10 readiness

Implementation covers P10.01–P10.10: the API-backed Streamlit investigation workflow, permission-aware operations, pinned queues/cases, factual evidence, resilient review forms, immutable history, independent freshness, scoped caches and an approved-gateway token provider.

Software verification PASSED: **404 tests** and all **11 checks**, including dependency consistency, lint, formatting, strict typing, the full synthetic/PostgreSQL suite, contract snapshots, specification, CLI and package build. Checked source/config/test files remained unchanged throughout. Fresh installed-wheel verification passed all six checks, including actual signed-token HTTP, blocked missing-trust UI startup and NumPy/Arrow interoperability outside the checkout.

Final regression evidence: `artifacts/phase10/windows_workspace_final/report.json` and `walkthrough/journey.json`. The journey includes an invalid quarantined upload and persisted review/export IDs without hand-edited database rows. Fresh runtime installation evidence: `artifacts/phase10/wheel_release_verified/report.json`. The earlier live browser rehearsal is separately recorded under `artifacts/phase10/walkthrough`, with queue/case screenshots and its own persisted synthetic IDs. Interrupted checks and the initial installation timeout are superseded by these final results.

| Point | Implementation and verification |
| --- | --- |
| P10.01 | HTTPX API-only client, bounded response reads, verified TLS, explicit timeouts, safe errors and retained write UUID/payload. UI import-boundary test excludes database/model adapters. |
| P10.02 | Role-aware upload/manifest limits, durable job IDs, bounded polling, accepted/quarantined findings, authorized retry and refreshed-session job reconnection. Training/scoring remain worker operations. |
| P10.03 | Explicit published queue/cohort/version, rank cursor pagination, scope-filtered API results, raw review priority, full-cohort percentile, state/assignee filters and model version. New heads require deliberate navigation. |
| P10.04 | Selected immutable score, model/bundle/batch/policy/dictionary/snapshot references, observed values, signed raw-margin contributions and reference context. Anonymous meanings remain UNVERIFIED; research/cutoff limitations precede evidence. |
| P10.05 | Explicit assignment/review/reopen forms with opened expected version, retained idempotency key across timeouts/reruns, latest-state differences after conflict, and explicit reset before a new action. Notes render as text. |
| P10.06 | Independent paginated score/review/audit histories, immutable event and selected-score references, later correction/model metadata and encrypted reopen reasons. Workflow conclusions never become adjudicated labels. |
| P10.07 | Independently explained complete, buffering, provisional escalation, stale and unavailable states; unavailable renders an em dash, preserving a true zero. Unknown research cutoffs/completeness remain explicit. |
| P10.08 | Server-session-only caches keyed by actor/roles/scopes, endpoint/version/filters and bounded TTL. Scope change, logout, authentication failure and accepted writes invalidate private state; authorization/writes/downloads are not global cache entries. |
| P10.09 | Protected gateway backchannel and signed session/token-binding assertions; per-user API-audience credentials verified again by `/v1/me`. Wrong issuer/audience/binding/hash/expiry and email-header spoofing denied. Organization gateway integration remains BLOCKED. |
| P10.10 | Signed synthetic UI interactions and real loopback API/PostgreSQL/worker journey: upload, validation/quarantine, scoring, queue, assignment/review/history, export and reconnect. Persisted IDs recorded without hand-editing operational rows; browser screenshots inspected. |

The UI renders tables without the built-in dataframe CSV download toolbar. Exports require the API's authorized, version-pinned, actor-bound and audited workflow. Read access still allows a reviewer to view/copy permitted values; this is not a browser data-loss-prevention guarantee.

Six pre-existing core/development/API platform locks are byte-identical to Phase 9 (`artifacts/phase10/lock_preservation.json`). UI locks are separate and retain NumPy 1.26.4; PyArrow 25.0.1 was selected and runtime checked for compatibility. An initial Arrow 26 runtime import failed against this model environment and was replaced before verification. Windows software evidence does not claim Linux CI execution, representative performance or deployment approval.

Normal UI/API startup and shared login remain blocked pending the organization's OIDC/API trust settings and approved gateway session integration. No ID-token forwarding, email-header trust, token-paste interface or permissive fixture fallback is introduced. Identity owners must supply and verify gateway routing/header isolation, per-workspace handle binding, API audience token exchange and revocation before shared deployment.

Qualified use remains blocked by existing source/identity, representative-data and owner-review dependencies. The real dataset and saved holdout are not used by these synthetic UI tests. Owner review is PENDING; software verification does not constitute acceptance of financial-crime conclusions.
