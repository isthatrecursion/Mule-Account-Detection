# Phase 2 implementation and handoff

Prepared: 2026-10-20. Scope: **typed contracts, server-owned schemas/source compatibility, safe boundary validation and the development-only research adapter**. Qualified use remains blocked. Parsing a contract does not create an accepted batch, approve a source/model or publish a score.

| Point | Delivered implementation | Verification scope |
|---|---|---|
| P02.01 | BatchManifest, strict version registry and generated batch_manifest_v1 JSON Schema. | Unknown versions, missing IDs, wrong types, naive/non-UTC timestamps, negative counts, unknown fields and unknown qualified cutoffs fail with safe codes. Research cutoff remains nullable with explicit provenance limits. |
| P02.02 | QualifiedSnapshot, SourceCoverage, SourceRegistry and deterministic source merge. | Conflicting ownership, mismatched account/time grain, incompatible cutoffs and missing required partitions cannot produce a complete joined snapshot. The real source registry is empty. Stored uniqueness and correction transactions follow in Phase 3/4. |
| P02.03 | Hash-bound ResearchAdapter and frozen UUID5 identity helper. | Only the saved development membership is emitted. Labels and restricted row/month lineage are separate from predictors. No verified account or observation cutoff is invented. |
| P02.04 | Complete 3,925-column research_v1 catalog and explicit cell/header rules. | Required/extra/duplicate/reordered columns, type failures and target injection tested. Literal categories are preserved except declared missing tokens; unexpected numeric text fails rather than becoming NaN. Integer precision is preserved, with explicit logical-type metadata. |
| P02.05 | Versioned permanent feature policy, canonical hash, bundle-policy compatibility helper and separate training-only fold-exclusion records/reference calculation. | Historical 1,404-column register hash retained. Validation-only missingness does not influence training selection. Target/identity/permanent exclusions are forbidden; changing policy changes its fingerprint. Actual transformer extraction/parity remains Phase 5. |
| P02.06 | Versioned dictionary entries and evidence authority checks. | Unknown/uncertified entries display ID only. Certified entries need known ID, definition metadata and approval reference; informal EDA names cannot become business prose. Real certifications remain absent. |
| P02.07 | Qualified label contract, correction-history validation and as-of selector. | Immature, unreviewed and future-known labels cannot leak into an earlier cutoff. A known immature correction does not fall back to an obsolete label. Raw research labels do not become qualified labels. |
| P02.08 | Bundle and score contracts with signatures/digests, policy/runtime metadata, output/contribution scales and explicit unavailable/freshness lineage. | Missing bundle artifacts, wrong policy hashes, nonfinite scores, fabricated unavailable values, missing ranked lineage and incomplete/misaligned complete coverage fail. |
| P02.09 | Minor-unit event and producer completeness contracts with clock/epoch/progress/content validators. | Explicit reversals/corrections, authorized epoch restarts, future skew, contradictory counts and missing/duplicate sequences tested. No real event feed or reconciliation worker is implied. |
| P02.10 | Evidence, review, job and audit types plus trusted-context review binder. | Actor injection, unsupported narratives/scales, workflow skipping and terminal job restarts fail. Research job success, review conclusion, fraud-label maturity and approval remain separate. Persistence/authentication arrive later. |
| P02.11 | Fifteen minimal valid fixtures, per-contract mutations, enum failures, all 21 contract-code scenarios and generated-schema/version freeze checks in CI. | Rejected inputs do not reach a publication callback. Regeneration cannot silently overwrite an already frozen schema. No database transaction is claimed before Phase 3. |

## Executed evidence

- [Windows final report](../../artifacts/phase2/windows_contracts_v3/report.json): **177 tests**, dependency checks, Ruff, formatting, strict mypy, fifteen generated/frozen schemas, research catalog generation check, 271 Phase 0 checks, wheel/sdist build and unchanged-reference hashes pass.
- [Linux final report](../../artifacts/phase2/linux_contracts_v3/report.json): the same **177 tests** and synthetic integrated checks pass under the existing locked Python 3.12 Linux environment. Raw research adaptation is deliberately NOT_RUN on this path.
- [Installed-wheel check](../../artifacts/phase2/wheel_smoke_v1/report.json): the final wheel installs without network/dependency resolution in the previously verified isolated runtime environment; all fifteen contracts import and round-trip synthetic payloads outside the checkout, and pip check passes.
- Windows opt-in local adapter verification emits **7,265 development rows / 65 positives**, excludes **1,817 holdout rows**, and returns **3,917 raw predictor columns before fold pruning**. Output evidence contains aggregate counts and input/policy hashes only. No model is fit; no development or holdout score is calculated; no private rows are written.

Reports and checksum manifests use exclusive run directories. They capture actual commands, UTC time, environment, current HEAD/dirty state, input/config hashes and the exact source/config/schema/fixture fingerprints. This is uncommitted implementation evidence; it does not claim the implementation already existed in HEAD. The roadmap tracker and this handoff are written after execution to avoid circular hashes. Remote GitHub Actions execution remains NOT_RUN.

The initial Windows run is retained as FAILED because the new strict reader exposed two representation details previously supplied implicitly by pandas: the CSV's blank first header and its serialized NA missing marker. Both now have explicit, server-owned rules and synthetic regressions. Later successful runs retain the original raw dataset, split, exclusions, verification code and benchmark artifacts unchanged. Intermediate successful runs precede the final integer-precision guard and remain historical evidence.

## Reproduce and continue

See [contract behavior and limits](../contracts.md), [error catalog](../contract_error_catalog.md), and [development setup](../development.md). From the repository root:

```powershell
.\.venv\Scripts\python.exe scripts/verify_contracts.py --output-dir artifacts/phase2/new_synthetic_run
.\.venv\Scripts\python.exe scripts/verify_contracts.py --with-research-data --output-dir artifacts/phase2/new_local_reference_run
```

The second command is for the approved local data machine only. Choose new directories; existing evidence is never overwritten. Source/type schemas remain external configuration or generated server metadata, not request-supplied code. JSON Schema is necessary shape evidence, while semantic helpers enforce cross-field/history/policy/source rules. Future services must call them with trusted records and context.

Phase 2 is engineering-complete within this scope. All 14 external dependencies remain OPEN, qualified source registration is empty, Phase 0 owner agreement remains pending, and product acceptance requirements remain PLANNED. CLI heavy operations continue to fail explicitly until their services are built. Contract parsing, a CERTIFIED string, a tier claim or a configuration change cannot grant operating/model approval.

Phase 3 can build PostgreSQL databases, migrations, database-enforced identities/lineage, repositories/unit of work, append-only audit privileges and optimistic concurrency on these contracts. Durable intake/quarantine is Phase 4; fold-safe feature parity is Phase 5; registry approval, scoring, API authorization and reconciliation follow their roadmap phases. Preserve the 1,817-row holdout boundary throughout. No architecture design decision changed.
