# Workspace usability corrections

Implemented on 2026-11-01 (Asia/Calcutta), following `docs/workspace_usability_plan.md`.

The current Streamlit/FastAPI workspace is retained. Investigation is the primary navigation group; Operations contains separate intake, scoring/training and job tabs. Synthetic extension previews and developer controls have their own collapsed sections. Unsupported extensions are excluded from normal runtime navigation even when configured.

## Ten-point acceptance record

| Finding | Implemented correction | Verification / limit |
|---|---|---|
| 1. Content below deployment notices | Compact environment status; deployment details, session identity and last action in sidebar expanders; reduced main padding | Queue cases and direct actions visible at 1366 x 768; synthetic label remains visible |
| 2. Flat mixed navigation | Investigation and Operations groups; permitted operational tasks in native tabs | Permission-filtered navigation tests; empty groups omitted |
| 3. Developer controls mixed with work | Collapsed Developer demo tools, present only through the explicit preview entry | Synthetic journey still exercises worker/fault controls; normal runtime has no demo controls |
| 4. UUID dropdown to open a case | Native Open case action associated with each row; self-contained row labels; context restored on Back to queue | Exact-row selection, next-page context and assignment-filter return regressions |
| 5. Buried review controls | Record/state/assignee/priority/freshness summary; compact action panel before detailed evidence; expandable provenance | Desktop first-view assignment action; assignment/start/save/history browser walkthrough; evidence IDs checked before review controls render |
| 6. Repeated warnings and facts | One primary location for cutoff, publication time and completeness; consolidated contribution explanation; deduplicated source limitations | Rendering regressions; stale/provisional/unavailable and historical-baseline tests |
| 7. Manual internal-ID handoffs | Assigned to me / Unassigned (queued) filters; remembered filters; accepted-batch picker from session results; API-discovered queue selection for exports; advanced case/actor/job entry | Ordinary queue/review/export journey requires no copied case/queue UUID; accepted batches revalidated before job submission. Complete user/batch/approved-bundle discovery still requires backend list contracts |
| 8. Fixture views look live | Explicit Preview · Synthetic only group; per-page synthetic labels; mock-mode capability gating | Live navigation excludes proposed extension routes; existing client still rejects those routes outside fixtures |
| 9. Database-style history | Readable event/action/time/actor/conclusion/note presentation; technical event fields expandable; time/version comparison labels | History and immutable-lineage regressions. A generic review activity remains generic when the API does not distinguish start-review from other review events |
| 10. Export defects | Resolve job kind before controls; export-specific reconnect; one deferred authorized download; polling scoped to export jobs | Mixed-job, wrong-kind/missing/denied reconnect, immutable CSV, expiry and scope regressions; no preliminary discarded CSV fetch |

`Unassigned (queued)` uses the existing queued workflow state, rather than inventing an unsupported assignee query sentinel. Actor names, account identities, approved models and full historical feeds are not fabricated from bounded pages.

## Automated verification

- Full UI/client/auth/contract suite: **315 passed, 1 skipped**. The skipped test is the existing opt-in PostgreSQL/API/worker integration wrapper.
- Final history/journey/context smoke checks: **18 passed**.
- Ruff lint and format checks passed for the affected UI/test scope.
- Mypy passed for **159 source files** (`src/mule_detection` and `ui`).
- A pre-existing log test was made deterministic: it now checks structured log fields/values, rather than accidentally matching the digits `1234` inside random request UUIDs.

Commands used:

```powershell
.venv/Scripts/python.exe -m ruff check ui tests/ui tests/unit/test_ui_app.py tests/integration/test_ui_journey.py
.venv/Scripts/python.exe -m ruff format --check ui tests/ui tests/unit/test_ui_app.py tests/integration/test_ui_journey.py
.venv/Scripts/python.exe -m mypy src/mule_detection ui --cache-dir var/mypy-workspace-usability
.venv/Scripts/python.exe -m pytest tests/ui tests/unit/test_ui_client.py tests/unit/test_ui_auth.py tests/unit/test_ui_app.py tests/unit/test_api_auth.py tests/contracts -q --tb=short --basetemp=var/test-tmp-usability-release --junitxml=artifacts/frontend/usability/tests.xml
.venv/Scripts/python.exe -m pytest tests/ui/test_history.py tests/ui/journeys/test_synthetic_journey.py tests/ui/test_workspace_usability.py -q --tb=short --basetemp=var/test-tmp-usability-smoke --junitxml=artifacts/frontend/usability/final-smoke.xml
```

On this Windows host, sandboxed Python loopback socket initialization hung before Streamlit/test execution. The successful UI tests and loopback-only preview ran outside that sandbox; the network/authentication restrictions in the application were retained.

## Visual and browser evidence

Preview command: `.venv/Scripts/python.exe -m ui.dev --demo --port 8521`.

Screenshots are under `artifacts/frontend/usability/`. Earlier screenshots under `artifacts/frontend/part2/` and `part4/` retain the previous layout for comparison. Desktop inspection uses 1366 x 768; narrow inspection uses 390 x 844. A browser walkthrough exercised row opening, assignment, start-review, saving a synthetic note and history navigation. Browser export submission and synthetic worker completion were observed. The browser automation download-event capture timed out; authorized CSV content, fresh permission checks and expiry behavior were verified through the actual deferred-download callback in tests, not claimed as a browser file-save result.

This is synthetic UI and functional verification. A full screen-reader audit, owner visual acceptance and a new live PostgreSQL/deployment walkthrough were not performed.

## Remaining backend dependencies

The frontend work is implemented using the available API. Complete permission-scoped user search, accepted-batch listing and approved scoring-bundle discovery need backend contracts. Session-known accepted batches are selectable now; exact bundle-digest entry remains explicit. Models/source-health/pilot extensions remain synthetic previews pending approved live routes. Production identity integration and qualified-use approvals remain separate existing prerequisites.
