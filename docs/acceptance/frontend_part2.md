# FE-5–FE-8 handoff

Completed 2026-11-01 (Asia/Calcutta), building on the verified FE-0–FE-4 foundation. Existing backend routes, authorization and dependency locks are preserved.

## Delivered behavior

| Phase | Implementation | Verification |
|---|---|---|
| FE-5 Operations | Bounded upload/manifest submission; automatic URL job reconnection; separately labeled job/ingestion states; timestamps/attempts; safe findings; accepted-batch check; immutable scoring digest; authorized failed-job retry | Upload limits and duplicate requests; reconnect from fresh session state; quarantine without raw rows; terminal/deadline polling stops; manual refresh; denied retry; accepted/quarantined scoring gates |
| FE-6 Queue | Published version selection; server-side state/assignee filters; stable keyset cursors; shared score semantics; record key with full-value disclosure; explicit newer-version action; selected case/record/queue context | V+1 publication during V pagination, no duplicate/skipped records, explicit switch/reset; empty and single-record queues; unknown freshness; unsupported filter denial |
| FE-7 Evidence | Immutable score pin; case/evidence ID matching; provenance before interpretation; signed raw-field chart/table; encoded details; observed/imputed/unseen labels; contribution reconciliation warning; original assessment retained | Missing scores stay dashes; research/unverified notices; literal untrusted text; mismatched evidence denied; changed score pin denied; newer-assessment/history navigation |
| FE-8 Reviews | Permission/state/ownership-aware forms; original version and request timestamp; one key/payload; current-state/history checks after uncertain outcomes; explicit conflict resolution; reasoned reopen; persisted receipt; acknowledged UI pending state cleared | Lost acknowledgement + rerun + retry produces one review; stale version does not overwrite; missing permission/direct-call denial; other assignee denial; reopen appends with original score lineage |

The normal launcher still returns `UI_IDENTITY_CONFIGURATION_REQUIRED` without organization configuration. No identity fallback, model approval, automatic account action, backend migration or deployment was added.

## Contract limits kept explicit

- Intake results expose `finding_codes`, outcome and row count. The table supplies approved safe wording for recognized codes; rule version/severity/affected-count/block metadata displays “Not supplied”. No raw rows are shown. An intake quarantine message is scoped to that operation, not an assertion that no earlier score exists.
- Scoring requires `batch_id` and an approved immutable `bundle_digest`. There is no implicit alias-selection route. Accepted status is checked through `GET /v1/batches/{id}`; this UI flow therefore also needs `batch:read`. Model identity appears read-only when provided by the result.
- Queue filtering supports state and assignee only. Freshness filtering, arbitrary sorting, full-cohort N, top-K policy and policy-version fields are absent from the current endpoint. The UI neither sends unsupported parameters nor fabricates counts.
- A case already pins its assessment. There is no arbitrary-score case lookup or full last-complete-baseline payload. The newer-score notice leads to history and deliberate queue/case selection; it cannot display absent baseline details.
- Review conclusions come from the saved OpenAPI enum, protected by schema parity tests. There is no dynamic conclusion-discovery endpoint.
- History can inform an uncertain write but cannot prove which idempotency key committed. Only replaying the exact original key/payload can resolve its API acknowledgement. No text matching is used to infer success.
- Retry reuses the existing durable job ID as the real API does. The synthetic service models this contract; it does not execute workers or validate real source rows.

These are documented API dependencies, not hidden frontend fallbacks. Later backend extensions can enrich the views without changing their safety rules.

## Verification and evidence

Combined foundation/workflow/UI/authentication/domain-contract suite: **259 passed**. **mypy: 148 source files passed**. **Ruff: checks and formatting passed**. All eight dependency locks retain their Part 1 baseline hashes. Browser checks cover the synthetic queue/case workflow; screenshots are in `artifacts/frontend/part2/`.

```powershell
.venv/Scripts/python.exe -m ruff check ui tests/ui tests/unit/test_ui_app.py tests/unit/test_ui_client.py
.venv/Scripts/python.exe -m ruff format --check ui tests/ui tests/unit/test_ui_app.py tests/unit/test_ui_client.py
.venv/Scripts/python.exe -m mypy src/mule_detection ui --cache-dir var/mypy-fe-final
.venv/Scripts/python.exe -m pytest tests/ui tests/unit/test_ui_client.py tests/unit/test_ui_auth.py tests/unit/test_ui_app.py tests/unit/test_api_auth.py tests/contracts -q --tb=short --basetemp=var/test-tmp-fe-part2-release --junitxml=artifacts/frontend/part2/tests.xml
.venv/Scripts/python.exe -m ui.dev --workspace
```

Tests use local signed synthetic identities over HTTPX and Streamlit AppTest. No holdout rows or real account records are loaded. PostgreSQL/real-worker integration is **not rerun in this delivery**; previous Phase 10 evidence remains separate. Organization identity integration and production/pilot acceptance remain **BLOCKED**, pending the inputs listed in `docs/identity_flow.md`.

## File walkthrough

`ui/state.py`: `PendingWrite` adds creation time, original workflow context and bounded fetched history. `Workspace.poll` reads at the interval, returns stored terminal results, and stops automatic reads at the configured deadline. `reconnect_job` validates the durable UUID. `polling_active` controls whether the Streamlit fragment has a timer. `open_case` preserves selected record/queue context; `pinned_scores` prevents silent assessment replacement. `check_pending` reads case/history without inferring success.

`ui/app.py`: reconnects a URL job before scheduling the fragment. A terminal/deadline transition reruns the shell once to remove its timer. Manual refresh remains available. Authentication and effective permissions run before page data is rendered.

`ui/pages/operations.py`: `submit_upload` checks byte/metadata limits without reading CSV rows. `finding_rows` converts only safe finding codes into a table. `render_job` separates execution and ingestion outcomes, shows attempts and bounds, and gates retry. Model-job submission verifies accepted batch state before sending the immutable scoring request.

`ui/pages/queue.py`: builds only supported filters, displays the server's filtered count, resets cursors on version/filter changes, formats unknown/missing scores consistently and records the selected case tuple. Full record keys are available in a disclosure rather than silently discarded by truncation.

`ui/pages/case_detail.py`: fetches fresh workflow state while retaining the first score ID for that case. Evidence must match both case and score. Shared components place research/provenance/freshness/score before the contribution table and review form.

`ui/components/contribution_chart.py`: shows signed bars and every value in a visible table. It checks `base + sum(contributions)` against raw output within tolerance and presents discrepancies as a warning, not a corrected or invented explanation.

`ui/components/actions.py`: forms keep a fetched expected version, enforce an explicit reopen reason and use one request identity. An unknown acknowledgement exposes read/check and exact-request retry controls. A conflict displays submitted/current context and requires a deliberate reset. On acknowledgement the UI clears its pending draft and retains the server receipt.

`ui/mock/backend.py`: retains immutable queue membership versions, exposes controlled job completions, verifies synthetic identity/permissions/ownership, and models same-job retry. It remains isolated from the production launcher. `tests/ui/test_operations.py`, `test_queue.py`, `test_case_detail.py`, `test_review.py` test the associated behaviors; shared helpers use actual Streamlit widgets.

## Rebuild recap

1. Read the existing API shapes and record unsupported fields before designing controls.
2. Keep job IDs and deadlines in session state; reconnect only through the API.
3. Pair queue cursors with explicit versions and filter sets.
4. Pin case scores and validate evidence lineage before interpretation.
5. Keep expected version, payload and idempotency key together until acknowledgement.
6. Exercise timeout/conflict/permission cases alongside the successful path.
7. Record test evidence and API limits; keep identity/deployment approval separate.

Next authorized work would be Part 3, FE-9–FE-13. It has not been started by this delivery.
