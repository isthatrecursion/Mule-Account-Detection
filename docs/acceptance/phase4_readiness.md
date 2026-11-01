# Phase 4 implementation and handoff

Prepared: 2026-10-21. Scope: controlled CSV intake, immutable publication, ordered validation, research partition guards, quarantine, revalidation and exact replay. Qualified use remains blocked by the existing data/approval gates.

| Point | Implementation and verification boundary |
|---|---|
| P04.01 | Binary streams, generated private staging names, CSV-only parser, byte/row/compression limits and safe filename metadata. |
| P04.02 | Durable receipt/validation states with actor/correlation identity; declared and observed bytes/hash/count/schema; manifest mismatch rejection. |
| P04.03 | AES-GCM immutable objects, flushed staging, atomic hard-link publication, tracked recovery states and retention-gated cleanup. |
| P04.04 | Stable schema, identity/type/count and temporal/source/feature phases; versioned findings, certified-only ranges and category warnings. |
| P04.05 | Existing trusted dataset/split alignment reused; development-only quality and direct worker membership guard with predictor-only output. |
| P04.06 | Aggregate missingness, constant/zero/category/coverage summaries and compact table; separate restricted training diagnostics. |
| P04.07 | Hard errors, drift warnings and preserved research promotion blockers; no qualified approval. |
| P04.08 | Immutable encrypted reports, accepted published version and atomic batch/audit updates; new validation versions preserve old evidence. |
| P04.09 | Actor/environment request uniqueness, content metadata conflict checks, exact replay and separately audited intentional replay. |
| P04.10 | CLI streams stdin through the same service, emits safe JSON and rejection/system exit codes; PostgreSQL failure/concurrency/CLI tests. |

Alembic revision `0006` adds three intake/publication/content tables, report publication state and score-run validation lineage. It grants only explicit runtime mutations; historical migrations stay unchanged. Existing historical validation pointers are retained by migration. Operational migration must be applied deliberately; verification upgrades only dedicated synthetic test databases.

See [setup, behavior and limits](../ingestion.md). The CI persistence workflow runs the full Phase 4 suite and uploads evidence under `artifacts/phase4/ci`. Remote execution of this new branch remains pending until pushed. Local evidence is recorded separately; no raw research dataset or holdout scoring is run for these tests.

Phase 5 may build the reusable feature pipeline on the accepted-batch and development-only boundaries. The future worker must query current acceptance and use the partition guard; it cannot infer acceptance from an object path. Parquet/decompression, certified real sources, authenticated shared APIs, scheduled recovery, external durability/backup drills and model approval remain outside this phase.

## Local evidence

- [Final Windows/Docker verification](../../artifacts/phase4/windows_intake_final/report.json): **243 passed**, including **52 PostgreSQL integration cases**. Dependency, Ruff/format, strict mypy, frozen contracts/research schema, Phase 0 specification checks and source/wheel builds pass.
- [Final Linux verification](../../artifacts/phase4/linux_intake_v2/report.json): **243 passed**, including **52 PostgreSQL integration cases**, against the separate Linux PostgreSQL database. Dependency, formatting, typing, schema/specification and packaging checks are recorded individually.
- [Actual CLI bootstrap and release smoke](../../artifacts/phase4/bootstrap_smoke_v1/report.json): runtime-identity ingestion through real configuration and binary stdin, wheel imports outside the checkout, migration/config asset presence and exclusion of private files.
- [Final package identity](../../artifacts/phase4/final_package_v1/report.json): every packaged Python source matches the current working source bytes; isolated imports pass.
- Historical research preservation was checked with `python scripts/reference_manifest.py --verify`: passed with no mismatches. No raw dataset, saved split, historical exclusion register, model or holdout evidence was regenerated.

The initial Windows/Linux runs and intermediate Windows runs are retained as historical evidence. Use the final links above for current verification. Source/config hashes, dirty revision identity, commands, JUnit and checksums accompany each integrated report. Human review and remote CI for this new branch are not fabricated by local tests.
