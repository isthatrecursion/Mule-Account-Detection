# Acceptance evidence — <release / run ID>

Record type: `EXECUTED_CHECK` / `NOT_RUN` / `BLOCKED` / `EXAMPLE_ONLY`.
Use explicit values; `UNKNOWN` means not supplied, never approved. `PASSED` is a test result, not owner sign-off.

| Field | Value |
|---|---|
| requirement_id | <register ID> |
| build_revision | <commit + dirty flag + changed-file manifest hash> |
| input_hash | <SHA-256 or NOT_APPLICABLE with reason> |
| config_hash | <SHA-256 manifest> |
| environment | <OS, Python/dependencies, hardware, runtime tier> |
| executed_command | <exact reproducible command or NOT_RUN> |
| observed | <measurement / NOT_RUN / BLOCKED + reason> |
| expected | <observable gate from frozen policy> |
| pass_fail | <PASSED / FAILED / NOT_RUN / BLOCKED / EXAMPLE_ONLY> |
| evidence_link | <immutable report and checksum manifest> |
| reviewer | <identity and authority / PENDING> |
| executed_at | <timezone-aware UTC / NOT_RUN> |
| approval | <PENDING / signed scope, actor, time and rationale> |

## ML validity

Temporal/group isolation, label maturity, freeze/release history, metrics with counts/intervals, leakage and subgroup checks. State representative-data limits.

## Data quality

Source contract, identity, provenance, dictionary, time availability, quarantine and holdout isolation. Link open dependencies.

## Authorization

Allowed/denied actions, independent approval, note/export scopes, override actor/reason and audit atomicity.

## Analyst workflow

Queue policy/cohort version, deterministic ties, review transitions, conclusions distinct from labels and human-only actions.

## Delay replay

Timely/delayed identical event hashes, frozen model/config, completeness, score/queue agreement, affected/unaffected p95 compute, freshness, zero loss/duplicates/downgrades. Synthetic replay cannot prove predictive performance.

## Recovery

Backup identity, restore command, reconciled data/artifact checksums, RPO/RTO targets and observations. `NOT_RUN` until executed.

## Unresolved dependencies and sign-off

Link dependency IDs, gate impact, provider, validator and closure approval. Human reviewer and operator sign-off remain PENDING until actually supplied.

## Synthetic example — EXAMPLE_ONLY

`requirement_id: REQ-QUEUE-001`; `build_revision: EXAMPLE_ONLY`; `input_hash: EXAMPLE_ONLY_SYNTHETIC`; `config_hash: EXAMPLE_ONLY`; `environment: EXAMPLE_ONLY`; `executed_command: NOT_RUN (illustration)`; `observed: NOT_RUN`; `expected: ties sort by record_key ascending; empty has no percentiles; singleton is 100`; `pass_fail: EXAMPLE_ONLY`; `evidence_link: NOT_APPLICABLE (illustration)`; `reviewer: PENDING`; `executed_at: NOT_RUN`; `approval: PENDING`. This example is neither an executed test nor a sign-off.
