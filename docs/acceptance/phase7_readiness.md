# Phase 7 implementation and handoff

Prepared: 2026-10-22. Scope: local research packaging, trusted loading, registry,
approval controls and rollback. Qualified promotion and shared deployment remain
blocked by data qualification, independent review and later deployment controls.

| Point | Implementation boundary |
|---|---|
| P07.01 | Fresh final pipeline/model fit from authenticated frozen selection and exact development inputs; final-fit demonstrations remain in-sample. |
| P07.02 | Encrypted immutable bundle, complete inventory/hashes, signatures/raw mappings, training references, model card, source/runtime identity and saved parity fixture. |
| P07.03 | Independent digest/environment authorization, protected root, pre-deserialization checks and separate credential-free resource-limited worker. |
| P07.04 | Authenticated pinned MLflow server with separate tracking DB; encrypted artifact upload and recoverable registration mapping. |
| P07.05 | Database approval/deployment authority; mutable external aliases are recoverable mirrors and cannot authorize inference. |
| P07.06 | Append-only lifecycle decisions, qualified self-approval denial and database-level denial of runtime approval writes; separate approval provisioning. |
| P07.07 | Digest-bound evidence and explicit missing-dependency reasons; current research/cohort limitations always block qualified promotion. |
| P07.08 | Durable per-job digest/version/decision pins and locked publication revalidation; no estimator swap on alias changes. |
| P07.09 | Health-checked compare-and-set future selection, explicit rollback reason and preserved audit/history. |
| P07.10 | Synthetic artifact/permission/retirement/alias/timeout/rollback failures and opt-in actual-server recovery checks. |

## Evidence

- [Complete Windows verification](../../artifacts/phase7/windows_registry_final/report.json) records **291 passing tests**, including **67 PostgreSQL cases** and the authenticated MLflow proof, plus dependency checks, lint/format, strict typing, frozen schemas, Phase 0 specifications, CLI smoke and wheel/sdist builds.
- [Installed-wheel verification](../../artifacts/phase7/wheel_verified/report.json) checks packaged Python against the working tree, reuses the isolated locked runtime without dependency downloads, imports outside the checkout and verifies saved-model predictions through the installed worker.
- [Research final-fit proof](../../artifacts/phase7/research_bundle_v1/report.json) authenticates Phase 6 run `8adf55ea-39b8-42fe-9266-b97f782c3152`, fits a fresh selected LightGBM pipeline/model on **7,265 development rows**, excludes **1,817 holdout rows**, and verifies saved-worker fixture parity at absolute tolerance **1e-12**, relative tolerance **0**. The [current-code parity check](../../artifacts/phase7/research_current_parity.json) also verifies that original bundle after the audit and resolver hardening. It does not recompute evaluation performance from final-fit predictions, approve a candidate, or deploy an alias.

Private research models, reference distributions, lineage and fixture predictions
remain encrypted in ignored `var/`. Public research evidence contains only
aggregate counts, identifiers and hashes. The original Phase 6 evaluation is
preserved. The [lock-preservation check](../../artifacts/phase7/lock_preservation.json) confirms all four dependency lock files remain byte-identical to Phase 6;
MLflow's separate container does not enter the model environment.

The dedicated approval-role test provisions a minimal local control-plane
identity, appends a research decision and audit/outbox, retires the candidate,
and verifies it cannot rewrite the digest or delete decision history.

The actual-server test rejects anonymous access, checks the server version,
verifies complete encrypted artifacts against local hashes, creates another
version under the same registered name, and recovers a simulated lost reply after
remote registration. Synthetic PostgreSQL tests separately deny approval writes
from runtime credentials, enforce independent decisions, retain pins across alias
changes, stop publication after retirement and preserve rollback audit history.

Earlier failed/partial verification directories remain diagnostic history. Use
the final reports linked above for acceptance; all verification sources stayed
unchanged during the final checks. The reference manifest also verifies without
mismatches.

## Boundaries and next phase

All ten roadmap statuses describe implemented software verification scope;
organizational acceptance remains pending owner review. Research-only promotion
does not establish qualified detection performance, fairness or calibration.
Qualified candidate creation awaits a certified source/feature adapter and
approved immutable evidence. The current packager cannot create qualified tiers.

The worker is resource-limited trusted-code isolation, not a complete sandbox for
hostile uploaded pickles. Shared identity, host/container ACLs, service-secret
separation and TLS are later deployment responsibilities. Local basic auth is
bound to loopback; no shared/public MLflow deployment is claimed. CI is configured
for additional platforms; local evidence does not claim its remote execution.

Phase 8 must use `ModelResolver.pin` once for a durable scoring job, retain that
identity for chunks/explanations/retries, and call `revalidate` in its atomic
publication transaction. Phase 7 does not implement scoring/SHAP, queue publication
or analyst UI. See [registry commands and recovery](../registry.md) and the
[rollback runbook](../runbooks/model_rollback.md).
