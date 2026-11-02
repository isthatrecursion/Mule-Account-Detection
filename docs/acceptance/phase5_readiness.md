# Phase 5 implementation and handoff

Prepared: 2026-10-21. Scope: reusable research preprocessing, frozen inference,
feature/reference signatures, trusted serialization and legacy benchmark parity.
Qualified use remains blocked by the existing data and approval gates.

| Point | Implementation and verification boundary |
|---|---|
| P05.01 | Extracted comparator preserves the original algorithm; the original reference script is unchanged. |
| P05.02 | Historical 2,521 candidate count stays separate from fitted fold exclusions and training fingerprint. |
| P05.03 | Cloneable policy, semantic and structural transformers compose with training-fitted imputation and encoding. |
| P05.04 | Frozen `legacy_research_v1` constants are loaded from explicit configuration; qualified fits and same-version rule changes fail. |
| P05.05 | Fresh pipelines learn selection, imputation, categories and reference distributions only from training inputs. |
| P05.06 | Missing/invalid-cell masks preserve observations; no new indicators or invented source completeness. |
| P05.07 | Ordered input signatures, encoded output metadata and raw-field mappings; reordered/unknown/missing inputs tested. |
| P05.08 | Trusted fitted-state publication includes policies, runtime, training/split/code identities, signatures, sizes and checksums; load verifies before deserialization. |
| P05.09 | Boundary tests cover validation-only mutations, clones, unknown categories, all-null/constant/duplicate columns, exact missingness threshold, sparse output, semantic sentinels, forbidden fields, intake membership, tampering and save/load parity. |
| P05.10 | Independent five-fold comparison uses the unchanged reference and trusted development-only intake; matrices, predictions, OOF coverage, selected features and ranking metrics are compared under a frozen protocol. |

## Verification evidence

Verification evidence:

- [Windows synthetic verification](../../artifacts/phase5/windows_features_verified/report.json): all ten verification stages passed, including **204 tests** (52 PostgreSQL cases deselected), strict typing, lint/format, schemas, synthetic parity and package builds.
- [Final development-only benchmark parity](../../artifacts/phase5/research_parity_final/report.json): **PASSED** across 7,265 development rows and five folds. Selected features, exclusions and matrices match exactly; maximum prediction delta is **0.0**. OOF coverage is exactly once and top-25/50/100 membership is identical. AP is **0.8514962854**, ROC-AUC **0.9742200855** and Precision@50 **0.96** on both paths. These remain confounded development diagnostics.
- [Isolated wheel verification](../../artifacts/phase5/wheel_import_verified/report.json): all packaged Python sources match the working source bytes. The extracted wheel imports outside the checkout under isolated Python and completes synthetic fit/transform/save/load using the already verified runtime dependencies.
- [Fresh installation completion](../../artifacts/phase5/fresh_install_completion/report.json): **PASSED**. The linked original run supplies the successful hashed runtime installation, wheel installation and dependency check; the continuation passes package/feature imports, exact locked-version assertions and CLI smoke outside the checkout.

All ten Phase 5 tracker points refer to passed software evidence; none grants
owner agreement or qualified-use approval. The initial
`research_parity_v1` run is exploratory evidence from before the final intake and
configuration integration; it is superseded by `research_parity_final`.

`windows_features_final` retains the initial sandboxed run: its three failures
were Windows hard-link permission errors in the existing Phase 3/4 artifact
tests. The same regression suite passed outside the restricted sandbox in
`windows_features_verified`; no publication behavior was weakened to bypass it.
The historical reference manifest was verified with no mismatches.

The initial fresh runtime run under `artifacts/phase1/phase5_install_verified`
installed all pinned dependencies and the wheel and passed `pip check`. Its
following smoke process was interrupted, so that original report remains failed;
the continuation result is recorded separately under
`artifacts/phase5/fresh_install_completion`. An earlier offline-venv attempt under
`artifacts/phase5/wheel_smoke_verified` failed at sandboxed `ensurepip`. The passing
`wheel_import_verified` result is an isolated wheel check, not a claim of fresh
dependency installation. Remote CI remains unverified locally. The CI wheel
smoke check was updated to verify required
Phase 4 tables rather than the stale fixed count of 18, and to import the new
feature components.

The package adds an explicit direct dependency on the already-locked joblib
1.6.0; platform package versions and hashes are unchanged. CI adds the synthetic
reference comparison. No remote CI or Linux execution is claimed by these local
Windows runs. Existing Phase 4 work and historical reference data are preserved.

See [feature behavior, commands and limits](../features.md). The canonical feature
pipeline uses the reference's `>=90%` missingness cutoff; the earlier Phase 2
illustrative helper is not used for fitted selection.

## Phase 6 boundary

Training/evaluation services must verify accepted published validation state,
apply development membership again, split before fitting, clone a pipeline for
every fold/candidate, and retain immutable training/config/split identities.
Logistic scaling, model selection, label maturity, temporal/group separation and
independent evaluation remain Phase 6 work. Phase 7 must bind feature artifacts to
approved model bundles and restricted loading. Phase 5 does not enable a public
training/scoring endpoint or approve any production model.

The feature artifact writer needs service-controlled encrypted storage and ACLs;
it is not an encryption or model-approval service. Real-data parity writes only
aggregate diagnostics, feature names and hashes. All 1,817 saved holdout rows stay
excluded from training and scoring. Owner agreement and external data qualification
remain pending independently of successful software checks.
