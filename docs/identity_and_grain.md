# Identity and investigation grain

Policy: `identity_v1` · Owner: data_owner · Agreement: pending.

The investigation unit is one record at one declared `snapshot_at` cutoff. Features describe the declared half-open observation interval ending at that cutoff; they do not imply a transaction stream or verified account history.

Generate UUID4 values for `batch_id`, `score_run_id`, `case_id` and internal `snapshot_id`. A `record_key` is an opaque internal scoring key, never a predictor. Multiple scoring runs may refer to the same snapshot. A case links the snapshot and score versions; case identity is independent of account identity.

## Research identity

Freeze UUID namespace `672c45ae-3a4d-4ab0-8d85-636c2c15c9ea`. Compute the dataset SHA-256 over unchanged input bytes. Lowercase the 64 hexadecimal characters. The original row reference is the nonnegative integer in the historical split register, encoded in decimal without leading zeros. Validate its one-to-one mapping to physical CSV records before importing; reject duplicate, missing or noninteger references rather than substituting a DataFrame position. No source snapshot cutoff is known for this extract; keep it unknown, do not use import time as an observation time.

Define `research_record_id = uuid5(namespace, dataset_sha256 + ':' + canonical_original_row_reference)` and `record_key = 'research:' + str(research_record_id)`. A changed file has a different identity even if row numbers match. Reimporting an identical file/reference yields the same identity. Keep the original reference and the split register's misleadingly named `account_id` only in restricted lineage metadata. Do not return them as verified accounts. UUID5 provides deterministic naming, not anonymization; restrict mapping access.

## Qualified identity

Require source-certified stable pseudonymous `account_id`, `source_id`, timezone-aware `snapshot_at` and an approved source contract. Enforce unique `(account_id,snapshot_at,source_id)` for an accepted snapshot version. The same triple and same content is an idempotent retry. Different content is a conflict unless an explicit correction references the superseded version; never overwrite it. Link opaque UUID snapshot keys to this triple through restricted lineage.

The source must document key reissue, merge/split, retirement, pseudonym rotation, linked entity groups, and correction semantics. Unresolved identity mapping blocks qualified intake and grouped evaluation. Related accounts/entities cannot cross qualified evaluation partitions. No identity is inferred from demographic uniqueness. Domain implementation is deferred to P02.02–P02.03.

Synthetic check: identical digest/reference produces the same UUID; a different digest at the same row produces a different UUID; leading-zero input normalizes to the integer representation; malformed references fail. The Phase 0 checker exercises this specification, not an implemented ingestion adapter.
