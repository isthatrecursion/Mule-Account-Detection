# FE-9–FE-13 handoff

Completed 2026-11-01 (Asia/Calcutta). This delivers Part 3 frontend behavior against existing API contracts and explicitly isolated extension fixtures. Backend roadmap Phases 11–13 and organization identity integration are separate dependencies.

| Phase | Delivered | Evidence |
|---|---|---|
| FE-9 | Bounded immutable history; note permission notices; selected metadata comparisons; optional matching historical contributor comparisons | Original review survives correction; old score retained; comparison and paging tests |
| FE-10 | `ui/cache.py` private policy, actor/scope/version/filter keys, deep copies, TTL/bounds, accepted-write invalidation; safe render timing | Actor/scope/version/filter isolation, no auth/write caching, TTL expiry, mutation isolation, invalidation and logging tests |
| FE-11 | Confirmed export scope, exact session receipt, supported state filter, bounded jobs, deferred authenticated API downloads, expiry/denial recovery | Exact submitted receipt, server-frozen rows, no prefetch before click, expiry, direct permission and sensitive-column denial tests |
| FE-12 | Explicit assessment age and source context; separate baseline/provisional panels; corrected/reconciled comparison; deliberate publication switch | Ten-minute COMPLETE → BUFFERING → STALE → PROVISIONAL_HIGHER → CORRECTED/RECONCILED scenarios; original score/review immutability; movement notice tests |
| FE-13 | Flagged read-only governance/proposal/report/source viewers; explicit evidence class and gate outcomes; bounded Grafana links | Flags off/on, BLOCKED reasons, NOT_RUN for missing denominators/trials, forbidden action controls absent, URL bounds, no live extension HTTP calls |

## Verification

**283 tests passed**, combining frontend foundation/workflow/history/cache/export/late-data/extension tests, existing UI regressions, API authentication and domain contracts. **mypy passed for 155 source files**. Applicable Ruff lint and formatting passed. Dependency locks remain at the Part 1 baseline; no backend API schema/migration or production identity settings were changed.

```powershell
.venv/Scripts/python.exe -m ruff check ui tests/ui
.venv/Scripts/python.exe -m ruff format --check ui tests/ui
.venv/Scripts/python.exe -m mypy src/mule_detection ui --cache-dir var/mypy-fe-part3
.venv/Scripts/python.exe -m pytest tests/ui tests/unit/test_ui_client.py tests/unit/test_ui_auth.py tests/unit/test_ui_app.py tests/unit/test_api_auth.py tests/contracts -q --tb=short --basetemp=var/test-tmp-fe3-release --junitxml=artifacts/frontend/part3/tests.xml
```

The sandboxed test runner stalled; the normal local runner completed the tests. Evidence is recorded in `artifacts/frontend/part3/`. Browser QA uses signed synthetic identities and generated records only. PostgreSQL/real-worker integration was not rerun; prior Phase 10 evidence is preserved separately. Shared deployment and qualified/pilot acceptance remain blocked on their actual dependencies.

## Preview

```powershell
.venv/Scripts/python.exe -m ui.dev --workspace --extensions --late-stage PROVISIONAL_HIGHER
.venv/Scripts/python.exe -m ui.dev --workspace --extensions --late-stage CORRECTED
```

The preview binds to loopback. Fixture banners stay visible. Extension flags and timeline settings affect only the dedicated development entrypoint; normal startup still rejects missing organization trust configuration and mock mode.

## API dependencies / assumptions

`docs/ui_extension_contracts.md` lists the six exact proposed GET routes and payload fields. They are marked ASSUMPTION and supported only by the isolated fake API. Normal `ApiClient.extension` refuses them before sending a request, even with flags enabled. Backend agreement and real contract/authorization tests are required before live integration.

Current history exposes metadata, not arbitrary historical evidence. Contributor comparison requires both selected score IDs' evidence in an extension payload. Current export jobs do not return full scope/exact expiry/model-policy summary metadata; the UI shows its submitted receipt when available and otherwise labels it unavailable. Download expiry remains server enforced on each request. Existing API permissions and `export:sensitive` remain authoritative.

Gap age, pending reconciliation, baseline/corrected assessment objects and queue movement counts are extension assumptions; missing values never become zero, complete coverage or a pass. CORRECTED/RECONCILED remain publication events separate from freshness. Existing original case/evidence pins remain unchanged.

No model approval/promotion/rollback controls were added. Read-only extension authorization uses existing audit grants only in fixture mode, pending backend-owner agreement. Qualified evidence is never inferred from synthetic engineering passes.

## Implementation walkthrough

`ui/cache.py` extracts the existing session cache and adds an explicit policy. The key combines identity, scope, endpoint, version and filters before lookup; values are copied on both sides. Missing versions and noneligible reads bypass caching. `ui/state.py` preserves its compatibility import, clears reads after writes and retains export request receipts only in that actor's server session.

`ui/performance.py` measures a render block with a monotonic clock and emits fixed safe fields. The HTTP client already records fetch timings. `ui/app.py` wraps the page renderer, reconnects export jobs from the URL, and adds only permitted flagged read-only viewers.

`ui/pages/history.py` refreshes mutable workflow/version metadata before a short private history read. Comparisons stay on the selected page. `ui/components/comparison.py` separates factual differences from absent historical evidence and uses explicit timezone formatting.

`ui/pages/exports.py` validates the selected queue, allowlisted columns/state and explicit confirmation. The exact request is sent once through existing pending-write state. `authorized_download` checks the session binding, obtains fresh API identity and requests bytes only through the API when the user clicks. The UI never builds CSV or reads an export artifact.

`ui/components/late_context.py` shows original age and supplied source coverage context. A provisional score and COMPLETE baseline use separate panels. Corrected objects feed the shared comparison component. `ui/pages/queue.py` offers a deliberate new-publication action and displays movement counts only when supplied for that exact version.

`ui/extensions.py` declares proposed DTOs. A purported PASSED gate without trial/denominator evidence becomes NOT_RUN, and invalid count relationships fail validation. `ui/pages/extensions.py` renders only read-only supplied facts, keeps delayed disagreement distinct from final consistency, exposes blocked reasons and builds approved monitoring links without arbitrary query values.

`ui/mock/extensions.py` owns deterministic example governance/report records and the ten-minute publication scenario. It appends new assessments and changes only current-case newer-assessment metadata; original score payloads/reviews survive. `ui/mock/backend.py` simulates authorized server-frozen export bytes, sensitive-column denial and expiry; no real worker/data/model shortcut is used.

## Rebuild recap

1. Check existing history/export shapes before defining missing extension payloads.
2. Compare supplied immutable facts and retain lineage IDs.
3. Bind private caches to identity/scope/version; keep mutable authorization fresh.
4. Confirm export scope and defer each download to server authorization.
5. Render incomplete and corrected data without overwriting original assessments.
6. Gate extension views and show missing evidence as NOT_RUN/BLOCKED.
7. Verify scenarios and record which live contracts remain unavailable.

FE-14–FE-16 have not started. Their comprehensive release journeys, deployment hardening and acceptance approvals remain Part 4.
