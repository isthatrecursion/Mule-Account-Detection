# Contract error catalog

All Phase 2 failures below use nonzero exit mapping **5** when surfaced through the CLI error boundary. Public messages are fixed in domain/errors.py; rejected values, row content, schema URLs and credential strings are excluded. Direct Pydantic diagnostics are internal: use parse_contract or resolve_contract at external boundaries. Phase 1 argument/configuration/unsupported/internal codes and exits remain unchanged.

Each listed code has an executed synthetic fixture in [failure_cases.json](../tests/fixtures/contracts/failure_cases.json), checked by test_error_catalog_is_exercised_with_specific_safe_codes. A separate coverage test fails if a code is added without a case. This catalog covers pure validation failures, not future database or HTTP status codes.

| Code | Observable rejection / fixture scenario |
|---|---|
| CONTRACT_INVALID | Missing required ID, wrong strict scalar/container type, invalid enum or unexpected field; missing_id and per-contract mutation tables. |
| CONTRACT_VERSION | Unknown version, including a URL/code path offered instead of a registered version; unknown_version. |
| TIMESTAMP_NAIVE | Timestamp has no timezone; naive_timestamp. |
| TIMESTAMP_INVALID | Timestamp is malformed or not UTC; malformed_timestamp. |
| COUNT_INVALID | A nonnegative count is negative; negative_count. |
| SCHEMA_MISMATCH | Duplicate JSON member, duplicate/extra/missing CSV column or ambiguous alias; duplicate_json_key and CSV fixtures. |
| FEATURE_FORBIDDEN | Target, identity, lineage or permanent exclusion requested as predictor; target_predictor. |
| VALUE_INVALID | Unexpected numeric text or a prohibited/nonfinite value; numeric_coercion. |
| HASH_MISMATCH | Bytes disagree with a server-owned fingerprint; research_hash. |
| SPLIT_MISMATCH | Source reference, target, partition or row count disagrees with the split; research_split. |
| IDENTITY_CONFLICT | Duplicate research reference or incompatible source-join identity; research_duplicate. |
| SOURCE_CONFLICT | Duplicate ownership, unknown/missing source or mismatched source authority; source_conflict. |
| CUTOFF_MISMATCH | Missing qualified cutoff or incompatible observation/availability/coverage; unknown_qualified_cutoff. |
| DICTIONARY_UNCERTIFIED | Unsupported display prose, unknown certified field or missing certification metadata; uncertified_prose. |
| LABEL_HISTORY_INVALID | Invalid value/status, correction chain or chronology; label_correction_link. |
| LINEAGE_INVALID | Missing artifacts, wrong policy/bundle/dictionary identity or contribution scale/direction; missing_bundle_artifact. |
| SCORE_STATE_INVALID | Fabricated unavailable values, missing ranked lineage or incomplete/misaligned complete coverage; unavailable_zero. |
| EVENT_SEQUENCE_INVALID | Invalid correction/reversal linkage or producer restart/progress; epoch_reset. |
| EVENT_CLOCK_SKEW | Event time exceeds the registered future-skew allowance; future_event. |
| COMPLETENESS_INVALID | Count/sequence/watermark evidence is contradictory or partitions are absent; contradictory_count. |
| WORKFLOW_INVALID | Unauthorized/skipped review transition or terminal job restart; terminal_job. |

Pydantic field/type failures without a more specific semantic code map to CONTRACT_INVALID. Ingestion policy in Phase 4 determines quarantine severity and affected counts; parsing alone writes no accepted batch, score or approved model. Rejection tests prove the publication callback is unreached; they do not claim a database transaction exists yet.
