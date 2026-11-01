# Phase 6 implementation and handoff

Prepared: 2026-10-22. Scope: research training/evaluation and conditional qualified
evaluation controls. Qualified source certification and deployment remain blocked.

| Point | Implementation boundary |
|---|---|
| P06.01 | Explicit research/qualified-temporal modes; current research input cannot elevate its tier. |
| P06.02 | Known-at SQL query and as-of contract selector; mature correction/identity/outcome-time checks and diagnostic counters. |
| P06.03 | Keyed research folds and purged, connected-entity-disjoint temporal partitions with hashes, counts and exclusion reasons. |
| P06.04 | Comparable logistic/LightGBM candidates, bounded threads, numeric-only sparse-safe scaling and fresh feature fits. |
| P06.05 | Inner-only multi-configuration search; explicit single-config path, frozen selection and acceptance-release guards. |
| P06.06 | Encrypted per-fold models, predictions, feature manifests, timings and membership; cohort/source missingness probes. |
| P06.07 | Deterministic ranking metrics, fold/pooled diagnostic distinction and group bootstrap with invalid-resample counts. |
| P06.08 | Approved explicit ablation refits and subgroup denominators/uncertainty; small samples and research fairness remain inconclusive. |
| P06.09 | Research calibration blocked; qualified Platt utility requires representative evidence and disjoint fit/evaluation inputs. |
| P06.10 | Authenticated encrypted candidate evidence, source/config/data identity, model card and explicit failed-run behavior. |

## Verification evidence

- [Complete Windows verification](../../artifacts/phase6/windows_training_complete/report.json): **274 tests**, including **58 PostgreSQL integration cases**, plus dependency, lint/format, strict typing, frozen schemas, Phase 0 specifications, synthetic training and package builds. This includes the final authenticated run-state consistency check.
- [Development-only candidate run](../../artifacts/phase6/research_training_v1/report.json): both families produced OOF scores for all **7,265 development rows**; **1,817 holdout rows** were excluded. LightGBM AP **0.8514962854**, ROC-AUC **0.9742200855**, Precision@50 **0.96**. Logistic AP **0.3660178299**, ROC-AUC **0.9333867521**, Precision@50 **0.58**. LightGBM won the declared mean-fold AP comparison. These are confounded development diagnostics, not prospective detection evidence.
- [Current-code research evaluation](../../artifacts/phase6/research_current_evaluation.json): authenticated evaluation reproduces the frozen run summary without refitting or exporting predictions. Numerical training sources are unchanged; the recorded source differences are the operational audit allowlist and run-state identity hardening. The original run identity remains preserved.
- [Installed-wheel verification](../../artifacts/phase6/wheel_current_verified/report.json): final packaged Python sources match the working tree; offline installation into the existing isolated environment, exact locked-runtime checks, imports, both synthetic candidate fits and CLI smoke run outside the checkout.

Private research fold models, membership, predictions, reports and model card are
encrypted under ignored application storage. Public reports contain aggregates
and hashes only. The existing reference manifest was verified with no mismatches.
Earlier runs remain diagnostic history; use the final evidence links above.
Remote CI and Linux execution are not claimed by these Windows results.

No database migration or approval is added. Training uses existing acceptance and
audit tables, adding the `model:train` action to the service allowlist. Threadpoolctl
3.7.0 is now a direct dependency at its already-locked version; package versions
and lock hashes were preserved. The pinned sklearn/SciPy combination emits
deprecation warnings in diagnostic/calibration tests; convergence failures are
separately treated as failed fits.

All ten roadmap points describe software verification scope. Qualified temporal
orchestration remains blocked by the absent certified source and feature adapter;
conditional split/label/calibration controls were exercised with synthetic
contracts. No real qualified evaluation, acceptance-label release, fairness
certification, calibration approval or model promotion is claimed.

See [training behavior, commands and limits](../training.md).

## Next phase boundary

Phase 7 must package a final authorized development fit from the frozen selection,
bind preprocessing/model identity, integrate registry tracking and enforce
independent approval, trusted restricted loading and rollback. Research candidate
metrics cannot approve qualified use. Label/source/dictionary availability,
representative cohorts, certified feature semantics and owner sign-off remain
external dependencies. Shared authentication, durable worker scheduling and
controlled final-acceptance release registration are not implemented by Phase 6.
