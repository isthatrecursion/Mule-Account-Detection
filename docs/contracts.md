# Phase 2 boundary contracts

The server-owned [registry](../src/mule_detection/domain/contracts/registry.py) resolves fifteen fixed version identifiers. Use `resolve_contract(version, payload)` or `parse_contract(Model, payload)` at untrusted boundaries. These functions return typed values or a safe `DomainError`; they do not register an accepted batch, approve a model, fetch a URL, load code or write business state. Public errors use the [error catalog](contract_error_catalog.md), never rejected values or Pydantic input diagnostics.

## Versioned interfaces

| Version | Contract and additional semantic checks |
|---|---|
| batch_manifest_v1 | Batch/source/schema identity, tier claim, count/hash/policy/owner/job and UTC timestamps. Qualified cutoff must be known; research may retain an unknown cutoff with explicit limitations. Created/upload time never fills it. |
| qualified_snapshot_v1 | Verified-identity reference, account/source/snapshot grain, observation/availability cutoffs, feature mapping and source coverage. Identity, labels and permanent exclusions cannot be predictors. Source ownership, contract/approval references, required partitions and matching cutoffs are checked by `merge_snapshots`. |
| source_registry_v1 | Server-controlled source contracts, feature ownership, required partitions, cutoff guarantees and clock-skew limits. Duplicate source or feature ownership is rejected. The actual registry is empty: no real source is qualified. |
| tabular_schema_v1 | The research_v1 column catalog: logical type, role, required-column status, permitted null markers and deterministic ordering. Raw blank row-reference header explicitly maps to Unnamed: 0; ambiguous/duplicate headers fail. |
| feature_policy_v1 | Eight permanent safety exclusions and their reasons, policy version/hash and historical EDA register hash/count. Fold-derived exclusions remain separate. |
| feature_dictionary_v1 | UNVERIFIED/PROVISIONAL/CERTIFIED metadata, version, known IDs and certification references. Uncertified or unknown fields display only their IDs. `validate_evidence` checks against the server dictionary; a request's CERTIFIED string is not authority. |
| label_v1 | Qualified label source/event/observation/availability/maturity, account/record linkage, adjudication or signed negative-policy reference, version and supersession. `select_label_as_of` checks correction history and knowledge time. |
| model_bundle_v1 | Artifact hashes, input/transformed signatures, training fingerprint, policy/runtime versions, model card, dictionary, output scale and contribution scale. Candidate/research tiers grant no approval. `validate_bundle_policy` binds metadata to canonical server policy content. |
| score_v1 | Run/record/snapshot/bundle/cohort lineage, finite nullable score/rank/percentile, evidence, assessment/publication times, coverage, independent completeness/freshness/publication event and baseline reference. UNAVAILABLE rejects fabricated scores and times. |
| event_v1 | Source/partition/epoch/sequence/event/account identity, UTC event/ingestion times and typed money/direction. Integer nonnegative minor units; reversals/corrections require explicit source-scoped references. |
| completeness_v1 | Producer-certified epoch-prefix count, contiguous committed position, heartbeat and complete-through watermark. `validate_completeness` checks actual source/partition/epoch contents and contiguous counts without allocating from an untrusted claimed count. |
| evidence_v1 | Raw observations, signed contributions/directions, base value, explicit contribution scale, peer-reference context, dictionary version and bundle identity. No free business-narrative field. |
| review_v1 | Expected case version, conclusion, restricted note reference and idempotency key. Actor comes from trusted service context through the application binder; actor/approval fields in a request are rejected. |
| job_v1 | PENDING/RUNNING/SUCCEEDED/FAILED independently of tier, approval, label maturity and score freshness. Terminal jobs do not restart in place; later retry services create linked attempts. |
| audit_v1 | Immutable-event envelope with actor/time/correlation, action/entity, canonical request hash and predecessor/reason references. Persisted append-only guarantees belong to Phase 3. |

Enums are independent. A successful research job remains research-only. A reviewed conclusion is not a mature label. RECONCILED/CORRECTED are publication events, not proof of completeness. A source approval reference is a claim that must resolve to actual server authority; parsing text is not approval.

## Research adapter and predictor policy

`ResearchAdapter.from_repository(root)` loads only the preserved reference hashes and server policy/catalog; it is a local research helper, not a production bootstrap. A future service constructs adapters from trusted source records, never request-controlled expected hashes. Input digests are checked before and after reading. The historical CSV's physical first header is blank; the named alias reproduces the pandas-derived Unnamed: 0 column without guessing account identity.

The file serializes missing data with NA and empty cells. The research catalog freezes the pandas 2.2.3 null-token lexicon used by the original reader. Only explicitly declared imputable markers become missing numeric cells. Unexpected numeric text, nonfinite numbers and invalid integer representations fail; they are never silently coerced to NaN. Categorical strings remain strings unless the source contract explicitly declares that exact string a missing marker. Synthetic tests include a categorical NA value under a schema where NA is not declared missing, and a separate physical-format fixture where it is.

The adapter validates raw row-reference/target alignment to the saved split, duplicate references and allowed partition values, then emits development rows only. Its output contains read-only predictor arrays, a separate label array, opaque namespaced record keys, restricted row/month lineage, input/policy hashes and explicit unknown account/cutoff provenance. It returns no holdout keys or feature rows. Research identities follow the frozen UUID5 namespace in [identity policy](identity_and_grain.md); changing the dataset hash changes the namespace input even at the same row reference.

There are **3,917 raw predictors before fold pruning** (3,925 physical columns minus eight permanent exclusions). The historical 1,404-column register is an audit reference, not a global learned selector. The previously reported 2,521 candidate columns remain historical EDA evidence. `derive_structural_exclusions` is a training-only contract reference with fit-partition/data/policy fingerprints; the actual reusable transformer and historical parity checks are Phase 5 work. No target-aware feature selection or model fitting runs in Phase 2.

## Time, labels and incomplete assessment semantics

Contracts require timezone-aware UTC and half-open windows. Qualified source merges require account/snapshot grain, matching windows, a single owner for each feature and all configured partitions. Database uniqueness and correction transactions are later Phase 3/4 controls; the typed envelope alone cannot enforce uniqueness against stored history.

The label selector first chooses the latest label **known** by the cutoff, then requires mature adjudication or an explicitly referenced negative policy. Future-discovered corrections do not leak backward. A known immature/unreviewed correction invalidates an obsolete mature label instead of silently falling back. Unreviewed is unknown. Research binary labels do not satisfy the qualified label contract without genuine timing and adjudication evidence.

UNAVAILABLE has null score/rank/percentile/cohort/evidence/assessment/publication/baseline fields and cannot claim COMPLETE. Complete ranked rows require cohort/evidence lineage and complete source windows ending at the assessment cutoff. Historical research outputs whose cutoff is unknown must state their limitation, UNKNOWN completeness and STALE freshness; the schema cannot manufacture a complete-as-of date. Retaining an old score retains its old timestamps. Separate provisional escalation and baseline storage are implemented in Phase 11; this contract requires a baseline link for a PROVISIONAL_HIGHER score row. A new account's baseline stays UNAVAILABLE during an outage.

`validate_event_progress` applies to newly declared **producer progress**, with an externally authorized epoch restart and source clock-skew allowance. It is not an arrival-order filter: late, duplicate and out-of-order envelopes need the Phase 11 durable deduplication/buffering path. A completeness manifest must be producer-certified and bound to registered sources; empty received data without such evidence is not certified inactivity. No transaction feed is connected here.

## Schema freeze, CI and next boundaries

[Generated JSON schemas](../contracts/) describe the same models; cross-field, source-authority, time/history and policy checks also require the Python validators. JSON Schema shape checking alone cannot replace them. The [version manifest](../contracts/version_manifest.json) freezes each initial schema digest and decision reference. A changed existing schema cannot be overwritten by normal regeneration. New versions must retain supported prior versions, have an explicit version decision and be registered with `--register-new-versions DECISION_REFERENCE`; semantic changes require review even if JSON Schema shape stays identical. This engineering freeze is not human operating approval.

```powershell
.\.venv\Scripts\python.exe scripts/generate_contract_schemas.py --check
.\.venv\Scripts\python.exe scripts/generate_research_schema.py --check
.\.venv\Scripts\python.exe scripts/verify_contracts.py --output-dir artifacts/phase2/new_synthetic_run
```

Use `--with-research-data` only on the approved local machine to add unchanged-reference hashing and aggregate-only adapter verification. It neither trains nor scores and writes no private rows. Existing evidence directories are rejected. CI checks all synthetic contracts, previous foundation behavior, generated schemas and the frozen version manifest without loading the raw dataset. Remote workflow execution remains NOT_RUN until actually observed.

Persistence, immutable validation/approval authority, durable intake/quarantine, model loading/signature verification, score publication, API identity/authorization and event reconciliation are later phases. Their services must call these semantic helpers with trusted context and records. Every external dependency remains open; changing a producer tier, alias, schema claim or configuration cannot close one.
