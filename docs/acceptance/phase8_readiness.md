# Phase 8 implementation and handoff

Prepared: 2026-10-22. Scope: complete local research scoring/publication and
synthetic stable-identity correction. Qualified use remains blocked by the
existing source, identity, representative-cohort and review dependencies.

| Point | Implemented boundary |
|---|---|
| P08.01 | Canonical scoring request, concurrent idempotent job/run creation, fixed model pin, leased attempts and explicit linked replay. |
| P08.02 | Accepted published input, trusted hashes, exact development membership, policy/signature/data-tier/environment and independent approval checks before inference; repeated worker/publication validation. |
| P08.03 | Encrypted bounded feature/score chunks, completed membership metadata and fresh-token full unpublished restart. |
| P08.04 | Exact membership/count, duplicate/nonfinite/direction checks and deterministic order; empty/singleton ranking semantics. |
| P08.05 | Full-cohort ranks/percentiles and immutable top-K queue members with score/version references. |
| P08.06 | Exact stored-pipeline LightGBM contributions/base column and raw-margin reconciliation; scaled-logistic log-odds support. |
| P08.07 | Saved encoded-to-raw aggregation, observed/imputed/derived states, training-only references and strictly anonymous unverified meanings. |
| P08.08 | Per-row snapshot/model/policy/dictionary lineage, baseline score references, nullable unavailable views and explicit research freshness limitations. |
| P08.09 | Authenticated staged results/evidence, fenced predecessor-checked transaction and atomic queue head, score/evidence, job and audit/outbox completion. |
| P08.10 | Crash injection at chunk two, evidence, before publication, before commit and after commit; concurrent creation, revocation, holdout, invalid score/chunk and stale fence tests. |
| P08.11 | Rescore only affected members, preserve unchanged raw values/source snapshots, rebuild global rank/top-K and preserve historical/opened queue versions. |

## Evidence

- [Complete Windows verification](../../artifacts/phase8/windows_scoring_final/report.json): **320 passing tests**, including **81 PostgreSQL cases**, plus dependency, lint/format, strict typing, PostgreSQL/MLflow/independent approval-role checks, frozen schemas, specification checks, CLI and package builds.
- [Synthetic end-to-end rehearsal](../../artifacts/phase8/rehearsal_current/exports/complete.json): accepted development scoring, required selected-case evidence, explicit unknown cutoff, unavailable semantics and idempotent publication.
- [Synthetic correction rehearsal](../../artifacts/phase8/rehearsal_current/exports/correction.json): one affected record crosses the top-K boundary, all unaffected raw scores remain unchanged, global ranks change and historical/opened assessments remain pinned.

- [Installed-wheel verification](../../artifacts/phase8/wheel_verified/report.json): final packaged Python matches the application source; locked-runtime imports, CLI, prediction parity and additive contributions run outside the checkout without dependency downloads.
- [Reporting export verification](../../artifacts/phase8/rehearsal_current/report.json): two focused end-to-end tests verify public exports after changing only the test/report environment variable to the preserved `MULE_TEST_` namespace. All application sources remain identical to the comprehensive 320-test run. The [final wheel](../../artifacts/phase8/packages_final/mule_detection-0.1.0-py3-none-any.whl) and [source archive](../../artifacts/phase8/sdist_verified/mule_detection-0.1.0.tar.gz) include that reporting fix.
- [Dependency lock preservation](../../artifacts/phase8/lock_preservation.json): all four lock files match Phase 7 byte-for-byte.

Detailed private observations, scored snapshots and contribution artifacts remain
encrypted. Public rehearsal evidence contains synthetic aggregate counts and
flags, not private raw rows or explanations. All existing model-runtime dependency
locks remain unchanged. The scoring request is registered as a new
`scoring_request_v1` contract; prior schema versions remain frozen.

Migration `0008` adds immutable task/chunk metadata, attempt status and a mutable
queue-head pointer with narrow runtime update grants. Existing score, evidence,
snapshot and membership tables remain append-only to runtime identities.
Publication has one database commit and no external registry writes. Phase 7's
independent model decisions remain the inference authority.

## Scope and next phase

Roadmap statuses describe software verification, pending owner acceptance. The
current research adapter remains development-only and has dataset-scoped record
identities. It cannot authorize cross-extract correction or qualify a new source;
the correction algorithm is tested through an explicitly synthetic accepted
stable-identity adapter. Real correction/reconciliation needs the later certified
source/identity and event adapters. No real model approval or research-data
scoring was performed by this implementation verification.

Research scores explicitly preserve unknown observation cutoffs as `STALE` with
`UNKNOWN` completeness. Complete queue materialization is not a claim of source
freshness, prospective accuracy, fairness or calibration. Detailed explanations
are generated for selected queue cases; other rows expose lineage and an explicit
explanation-not-selected state.

The research adapter materializes its development frame at preflight; model
execution/artifact shards are chunk-bounded. This phase does not claim a 100k-row
streaming benchmark, distributed scheduling, shared authenticated deployment or
Linux/remote CI execution. Model workers remain trusted-code resource isolation
with protected storage/OS permissions as documented in Phase 7.

Phase 9 should expose these services through authenticated API/job routes and
explicit read authorization, retain queue pins in case navigation and return
stable safe errors. See [scoring commands, behavior and recovery](../scoring.md).
