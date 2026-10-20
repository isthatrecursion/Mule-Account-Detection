# Phase 0 implementation and readiness

Prepared: 2026-10-20. Specification version: `phase0_v1`.

**Specification artifacts implemented; business agreement PENDING_OWNER_REVIEW. Qualified use BLOCKED.**

The Phase 0 checker exercises specification consistency and synthetic arithmetic/policy examples. It does not implement the planned application, validate a provider package, measure a benchmark, certify ML validity or grant approval. All 95 product requirements remain PLANNED, with 14 external dependencies OPEN. Named role owners are defined; individual assignees and provider names remain UNKNOWN.

| Point | Delivered specification | Verification scope |
|---|---|---|
| P00.01 | requirements_and_acceptance.md; acceptance/index.csv | Twelve functional requirements, eight NFRs, architecture/shared invariants and twelve final criteria have stable IDs, owners, observable checks and specific roadmap mappings. |
| P00.02 | identity_and_grain.md | Deterministic namespace/dataset/reference identity, duplicate import and changed-dataset examples; verified account grain and corrections defined. Runtime adapter deferred to Phase 2. |
| P00.03 | permissions.yaml; review_workflow.md | All nine permissions have allow/deny examples; transitions, independent approval, note isolation, privileged reasons and conclusion/label separation specified. |
| P00.04 | review_policy.yaml | Research K=50, eligibility, daily research cadence, ties, empty/singleton cohorts, percentile endpoints and immutable policy changes specified. Qualified capacity remains unknown. |
| P00.05 | benchmarks.yaml; performance_protocol.md | Four repeatable experiment designs, proposed hardware/workload, fingerprints and exact limits. Measurements NOT_RUN; observed values null. |
| P00.06 | data_request.md; data_dependencies.csv | Seven required source requests plus acceptance, operations, compliance, fairness, security/recovery, parity and representative replay dependencies. Requests prepared locally; no messages sent. |
| P00.07 | environments/research.yaml; environments/qualified.yaml | Immutable tier authority and fail-closed approval predicate examples including alias/env override and self-approval denial. Runtime policy loading/enforcement deferred. |
| P00.08 | freshness_policy.md | Seven terms with independent completeness/events, retained baseline timestamps and nullable UNAVAILABLE new-account response specified. |
| P00.09 | evaluation_policy.yaml | Train/tune/calibrate/acceptance order, maturity cutoffs, conservative lookback-plus-label purge, connected entity isolation and one-time acceptance release defined. Actual dates/durations remain blocked on source evidence. |
| P00.10 | acceptance/template.md | Complete evidence fields, domain sections, explicit NOT_RUN/BLOCKED and EXAMPLE_ONLY illustration. |

## Reproduce the document checks

Use Python 3.12 with PyYAML (available in the current audit environment). Run from the repository root:

```powershell
python scripts/validate_phase0.py
python scripts/validate_phase0.py --output-dir artifacts/phase0/phase0_specification_v1
```

The saved run is [report.json](../../artifacts/phase0/phase0_specification_v1/report.json), with [manifest.json](../../artifacts/phase0/phase0_specification_v1/manifest.json). The second command refuses to overwrite existing evidence; choose a new run ID to repeat. The report records actual UTC execution time, Python/OS/PyYAML, Git HEAD/dirty state, input/config/source hashes, command and individual check results. Its source manifest fingerprints the uncommitted specification files, so the result does not falsely imply they existed in HEAD. The roadmap tracker is updated after the evidence run and is not part of that manifest, avoiding a circular checksum.

[roadmap_status.csv](roadmap_status.csv) tracks all 170 points. PASSED for P00 means the specification implementation/check scope only; reviewer and owner agreement remain pending. Future points remain PLANNED/NOT_RUN. Planned test IDs and future evidence paths in index.csv are destinations, not claims that those tests or artifacts already exist.

## Remaining agreement and handoff

Project owner and accountable roles still need to review these definitions. Operational K/cadence, ranking and fairness thresholds, qualified time windows/purge parameters, representative data, vocabulary, security/retention, RPO/RTO and approval scopes require supplied evidence and signed decisions. None is silently approved by this implementation.

Phase 1 can build the research package/CI foundation against these explicit draft contracts. It must preserve the existing EDA/dataset/reference artifacts before refactoring, lock dependencies, load/validate policies and add runtime enforcement through later contracts/services. Qualified promotion remains blocked until the external dependencies and independent approval gates actually close. No architecture design decision was changed by this Phase 0 work.
