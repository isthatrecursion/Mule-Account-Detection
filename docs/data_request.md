# External data and operating-policy request package

Prepared 2026-10-20. Status: **PREPARED_LOCALLY_NOT_SENT**. Provider identities: `UNKNOWN`. [Dependency register](data_dependencies.csv) holds owners, validators, blocking gates, sample formats, acceptable fixtures and closure status. No external messages were sent.

The present extract is month/target-confounded and lacks verified account keys, observation times, availability and mature-label provenance. It supports research engineering, not qualified evaluation or model approval. Request the following through the organization's approved data-sharing channel; do not place private samples or direct identifiers in Git or CI.

## Required replacement package

Supply versioned UTF-8 CSV/Parquet snapshots plus a JSON manifest with schema/version, source/extract/job ID, UTC creation/cutoff times, SHA-256, row count, feature policy, owner and contact. Records require stable pseudonymous `account_id`, `snapshot_at`, `source_id`, entity linkage and correction/reissue semantics. Confirm one account-at-cutoff per source and demonstrate duplicates/corrections handling.

Supply a signed dictionary with `feature_id,definition,unit,source,calculation_window,available_at_rule,certification_status,dictionary_version,sensitivity`. Include field-level event/availability timestamps or auditable producing-job evidence that proves availability at scoring time. Anonymous values cannot be assigned business narratives from association alone.

Supply labels with `account_id,snapshot_at,label,label_source,label_event_at,label_available_at,label_status,label_mature_at,adjudication_id,label_version`. Describe case selection, negative verification, false-negative ascertainment, censoring and label corrections. Both mature classes must occur within each comparable evaluation period. Freeze a new later-period acceptance cohort with an independent custodian before labels or target-aware analysis are released; the historical 1,817 rows remain excluded.

For future transaction features provide source-scoped `event_id`, account/source/partition/sequence epoch and sequence, event/ingestion time, type, amount, currency, direction, schema and correction/reversal linkage. Include heartbeat/manifest committed positions and expected counts, sequence-reset semantics and clock assumptions. A source gap with unknown account scope affects all dependent windows. Provide representative replay contents including ten-minute delays and mature outcomes; synthetic tests cannot close this production evidence dependency.

## Requested policy decisions

Fraud Operations must supply review capacity K, cadence/service levels, outcome definition and cost assumptions. Model Risk must approve representative temporal windows, purge durations, minimum counts, ranking gates, uncertainty and calibration tolerances. Compliance must approve explanation vocabulary, human decision workflow, lawful attributes, subgroup count/interval rules, disparity thresholds and remediation. Security/platform owners must approve retention, access/SSO, release, RPO/RTO and incident requirements. These are tracked as dependencies rather than invented defaults.

## Stage 9 issue coverage

| Stage 9 issue | Dependency IDs | Gate |
|---|---|---|
| Hidden cohort leakage | DEP-003, DEP-006, DEP-008 | qualified data/evaluation/promotion |
| Feature-definition conflicts | DEP-004, DEP-010 | approved business vocabulary |
| CV reproducibility | DEP-013 | benchmark parity and reproducible run evidence |
| Fold selection leakage | DEP-013 | fitted-transform boundary tests |
| Holdout isolation | DEP-008 | new acceptance freeze and historical holdout exclusion |
| Account identity | DEP-001, DEP-002 | qualified intake and grouped splitting |
| Operational claims | DEP-009 | operational capacity and ranking gates |
| Explainability/actions | DEP-010 | compliance workflow and vocabulary |
| Fairness | DEP-011 | representative subgroup validation |
| Label validity | DEP-005 | mature-label eligibility |

Transaction completeness (DEP-007), representative event replay (DEP-014) and security/recovery (DEP-012) also gate the architecture's later operational requirements.

## Validation and closure

Each dependency identifies a planned validator/test ID and acceptable synthetic fixture in [fixtures](../tests/fixtures/phase0/specification_examples.json). These examples describe acceptable structure; they do not certify any supplied data. P02/P04/P06/P12/P14 implement the real validators. A provider saying data exists leaves status OPEN.

Close a row only after: (1) evidence received via an approved restricted location; (2) checksum/version and provider authority recorded; (3) the specified real validator passes and its execution evidence is linked; (4) accountable owner approves closure with identity/time/scope. Partial delivery remains OPEN with notes. Prepared artifacts are not requests acknowledged by providers and are not approval. Critical open dependencies block qualified promotion; research engineering can continue.
