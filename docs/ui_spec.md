# Frontend specification — FE-0–FE-4

This specification extends the existing Phase 10 workspace. Architecture Phases 0–10 supply contracts, validated intake, frozen model bundles, published assessments and the authenticated API. Phases 11–15 add reconciliation, replay, monitoring and deployment evidence later. This frontend ranks records for human review; it cannot restrict accounts, file reports, approve models or turn review conclusions into labels.

## Architecture and scope

`Browser → Streamlit session → UserTokenProvider → HTTPX → FastAPI → application services → PostgreSQL / workers / governed artifacts`.

The UI imports no database, training, prediction or artifact adapters. Backend workers perform intake, training, scoring and exports. UI reads use immutable assessment/queue identifiers. Case workflow versions are mutable and refreshed before writes. A case continues referencing its original assessment when a later assessment appears.

The existing Operations, Review queue, Case evidence, History and Exports screens remain functional. Part 1 adds vocabulary, settings, typed HTTP contracts, synthetic development support, identity recovery and reusable components. FE-5–FE-16 enhancements are not claimed by this delivery.

## Screens and permissions

Roles below describe intended users, not authorization rules. Navigation uses effective permissions and their scope grants from `/v1/me`. The API must enforce permissions even when a page is called directly.

| Screen | Purpose and data | Intended users | Read permission | Actions and permission |
|---|---|---|---|---|
| Operations | Upload limits, batch manifest, durable job status, validation results, immutable bundle digest | Operators/engineers with grants | `job:read`, `batch:read` | Intake `batch:intake`; score `score:submit`; train `train:submit`; retry `job:retry` |
| Review queue | Published version, scoped matching count, rank, raw score, cohort percentile, workflow and freshness | Analysts/reviewers | `queue:read` | Filter/page within a version; open a case with `case:read` |
| Case evidence | Pinned assessment, provenance, research limitations, observed values, signed contributions and workflow version | Analysts/reviewers | `case:read` | Assign `case:assign`; start/save `case:review`; reopen `case:reopen` |
| History | Original assessment lineage, append-only review/audit events, permitted notes | Reviewers/auditors/analysts with grants | `case:read`; audit collection also `audit:read`; notes `note:read` | Select supported history collection and page |
| Exports | Explicit queue version, columns, reason, server job and expiring download | Authorized reviewers/auditors | `job:read` for status | Request/download `export:create`; notes also require `note:read` |
| Source health / Models / Evidence reports / Pilot metrics | API extension, later | Subject to future grants | No invented permissions | Disabled by default; “Not available in this build” until supported |

The existing model-details read route is not a complete Models/governance screen. No approval/promotion/rollback control is added.

### Permission reconciliation

| Prompt permission | Actual use | Confirm against config/permissions.yaml |
|---|---|---|
| `queue:read` | Review queue | Yes; API effective grants remain authoritative |
| `case:assign` | Assign | Yes |
| `case:review` | Start review, save conclusion | Yes |
| `case:reopen` | Reasoned reopen | Yes |
| `export:create` | API export request/download | Yes |
| `model:train` | Actual API route uses `train:submit` | Older nine-permission list differs from API |
| `model:approve` | No UI action | Governance permission does not imply a frontend control |
| `job:retry` | Retry authorized failed job | Yes |
| `audit:read` | Audit history | Yes; requires its own scope grants |

Additional API grants are `case:read`, `note:read`, `batch:intake`, `batch:read`, `score:submit`, `train:submit`, `job:read`. `src/mule_detection/api/auth.py` and the authenticated identity response define actual grants. The UI does not guess a role mapping from the older nine-permission table.

### Required screen states

| Screen | Loading | Empty | Error / unavailable | Forbidden | Conflict |
|---|---|---|---|---|---|
| Operations | Labeled spinner / durable job status | No connected job | Stable code/request ID; unknown write outcome retains its key | Static denied message; no hidden data | Do not resubmit changed request automatically |
| Review queue | Loading authorized version | No published queue or no matching cases | Keep selected version; deliberate retry | No records/counts shown from a different scope | Version/cursor stay together; explicit new version selection |
| Case evidence | Loading pinned assessment | No selected case or no evidence | Missing score is an em dash; no fabricated explanation | No evidence/form rendered after API denial | Refetch case version; show change; deliberate new action |
| History | Loading selected collection | No permitted events | Preserve selected case/collection; safe code/request ID | Notes/audit remain protected | Mutable-case actions use the same conflict component |
| Exports | Loading job/download | No export requested | Unknown POST outcome retains key; expired download requires API handling | No local CSV fallback | Review current request; never silently change queue version |

These are component contracts and target behavior for the later page enhancement parts. Existing page-specific loading/polling flows are preserved in Part 1. The gallery exercises loading, empty, forbidden, conflict and API-unavailable presentations independently.

## Workflow

`QUEUED → ASSIGNED → IN_REVIEW → REVIEWED`

| State | Enabled actions, subject to permissions and API ownership rules |
|---|---|
| QUEUED | Assign |
| ASSIGNED | Start review (the API does not offer reassignment in this state) |
| IN_REVIEW | Save conclusion and optional note |
| REVIEWED | Reopen with reason and assignment context |
| UNKNOWN | No inferred workflow transition |

Reopen appends an event; it does not erase the earlier conclusion or move its assessment. Review conclusions are `NEEDS_MORE_INFORMATION`, `NO_FURTHER_REVIEW`, `REFER_FOR_ADJUDICATION`, the closed enum in saved OpenAPI. A review never creates a qualified outcome label.

Case writes send `expected_version` and one UUID idempotency key per deliberate submission. Other POST routes use idempotency keys but have no `expected_version` field in their schemas. Timeout, connection failure or malformed acknowledgement leaves the outcome unknown. Retrying uses the same key and payload; POSTs are never retried automatically. A 409 retains the draft and fetches current case state. A fresh action requires explicit acknowledgement of that state.

## Vocabulary and interpretation

| Term | Meaning |
|---|---|
| `record_key` | API-provided stable subject identifier; no inferred real-world identity |
| Queue version | Immutable published review queue; cursor and filters belong to it |
| Cohort | Population ranked together, not the count remaining after filtering |
| Raw score | Review-priority score (ranking only) |
| Percentile | Position in that cohort: `100*(N-rank)/(N-1)` for N>1, 100 for N=1, absent for N=0; displayed from API, not recomputed using filtered counts |
| Freshness | COMPLETE, BUFFERING, PROVISIONAL_HIGHER, STALE, UNAVAILABLE; unknown values show UNKNOWN |
| Publication event | CORRECTED or RECONCILED, separate from freshness |
| `assessed_as_of` | Original source cutoff for this assessment; never replaced by refresh time |
| `published_at` | Publication timestamp; may be absent in older responses |
| Provisional | Separate escalation from incomplete data; baseline ID remains visible; no invented baseline numeric value |
| Complete | Required coverage is complete at the stated time; this does not certify feature meanings or deployment readiness |
| DTO | A typed request/response object that validates API data before use |
| Fixture | Explicitly synthetic development data; never a fallback for live failure |
| Keyset cursor | Last `(rank, record_key)` pair within a fixed version, used to request the next page |

Every category has a text marker and explanation. No state relies on color. Unknown or unavailable score values render as em dashes. A valid zero remains zero. Research warnings come from server data/model tiers (`research`, `research_demo`); candidate model tier is not approval. In-sample notices are separate. Unverified anonymous fields retain their field IDs, values and signed contributions; no behavioral interpretation is invented.

## Contract decisions replacing the document's assumptions

1. A1: use existing `GET /v1/queues`, then a concrete version; no `/latest/cases` route is invented.
2. A2: use `/v1/me` actor ID, roles, permissions, scopes and permission-scoped grants. No `display_name` exists.
3. A3: the three review conclusions are explicitly defined by OpenAPI; no runtime conclusion-discovery route exists. A schema parity test guards the local enum.
4. A4: intake/submission permissions are known from the current API, as listed above.
5. A5: the real signed gateway provider already exists; preserve it instead of replacing it with a stub. Organization trust values remain missing and startup fails closed.
6. Scoring requires an immutable `bundle_digest` and `batch_id`. Model selection is not an implicit server alias.
7. Five freshness states and two separate publication events mirror `score_v1`. Model tiers are `research_demo` and `candidate`; ingestion can also fail.
8. Queue `total` is the scoped, filtered matching count. The UI does not present it as full cohort N or top-K policy.
9. Exports are POST → durable job → authorized `/v1/exports/{job_id}/download`. No arbitrary download URL or local CSV generation is added.
10. Case detail exposes neither an arbitrary selected-score endpoint nor a full baseline assessment. Missing fields display “Not supplied”; FE-12 must negotiate extensions rather than invent them.

## Settings, privacy and local development

Validated settings remain in protected `secrets/ui.json`; `config/ui.example.json` is deliberately incomplete. TLS verification cannot be disabled. Only loopback API HTTP in local/test/research environments retains the existing exception; identity URLs require HTTPS. Timeouts, page size, polling interval/deadline, timezone and extension flags are validated. The max polling deadline is a Part 2 consumer setting; existing polling behavior is unchanged in Part 1.

All timestamp display helpers reject naive timestamps and name the configured timezone. Logs discard message/exception text and arbitrary fields, retaining only allowlisted action/page/code, numeric timing/status and UUID request IDs. Tokens, notes, observed feature values and authorization headers never enter those logs.

The synthetic service contains 200 generated records, tied scores, a top-50 queue, stale/buffering/provisional/corrected/reconciled cases and an unavailable assessment outside the ranked queue. Every instance owns its store and ephemeral signing key. Faults can be injected for 401/403/404/409/422/429/500, timeout, connection failure and lost acknowledgement after commit. It is a contract/development simulator, not a database or worker implementation.

Normal runtime rejects mock configuration. `python -m ui.dev` launches the gallery on loopback only; `--workspace` launches the existing pages with a persistent fixture banner. No production identity defaults are supplied. Extension flags do not create unimplemented routes.

## Component interfaces

| Module | Public entrypoints |
|---|---|
| `time_fmt` | `format_time(value, timezone='UTC')` |
| `freshness` | `freshness_text(state, cutoff)`, `render(score, timezone)`, compatibility `display_score(score)` |
| `score` | `score_values(raw_score, rank, percentile, freshness, cohort_size=None)`, `render_score(...)` |
| `research_banner` | `render_research(data_tier, model_tier=None, in_sample=False)` |
| `provenance_header` | `render_provenance(case, timezone='UTC')` |
| `badges` | `badge_text(category, enum_member)`, `render_badge(...)` |
| `contribution_chart` | `chart_spec(EvidenceFacts)`, `render_contributions(EvidenceFacts)` |
| `pager` | `CursorPager.bind(version, filters)`, `.advance(cursor)`, `.back()`, `render_pager(...)` |
| `status_views` | `loading()`, `empty()`, `render_error(ApiFailure)`, `forbidden()`, `conflict()`, `unavailable()` |

Charts also include a visible value table, base value, raw output and scale. Encoded detail is expandable; essential information is not restricted to tooltips. Streamlit's existing neutral theme uses one teal interaction accent and standard keyboard-operable controls.

## FE-9–FE-13 additions

History now compares two supplied assessment versions on the current bounded page. Rank, score, freshness, model and queue differences are labeled Changed/Unchanged. If both matching extension assessments include evidence, it also compares raw-field signed contributions. The original review remains associated with its original score. Missing notes show “Not permitted to view” when the effective grant is absent. Reopen reasons remain append-only history.

Exports require explicit confirmation of the displayed queue version, columns, state filter and authorized scope. The exact request payload is retained as a session receipt. No CSV bytes are cached in page state. Streamlit's deferred download callable performs a fresh API identity check and downloads through the fixed authorized route on each click. A separate availability check presents safe forbidden/expired states and a request-again path. Missing exact expiry/provenance-summary metadata is labeled unavailable rather than inferred from job creation time.

### Cache policy

All eligible records are private to a `Workspace`. Keys contain actor fingerprint, scope fingerprint, endpoint, filters and an explicit data version; the workspace fingerprint also binds effective grants and protected configuration. Values are deep-copied and capped at 128 entries. Shorter configured TTLs win.

| Data | Maximum TTL | Version / invalidation |
|---|---|---|
| Queue page/count | 5 seconds | Explicit queue version and filters; accepted writes clear private reads |
| Immutable case evidence | 15 seconds | Score ID, actor and grants; logout/identity change clear |
| History | 5 seconds | Current case workflow version, selected score and newer-score identity; kind/offset included |
| Extension metadata, if cached by a future caller | 5 seconds | Requires explicit immutable revision; current extension fetches stay fresh |
| Case workflow state, `/me`, credentials, writes, download bytes | Never | Fresh API checks; no shared Streamlit data cache |

An audit-only reader without a current case version bypasses history caching. Fetch timing already comes from the HTTP client; render timing now uses allowlisted page/action fields and numeric durations only. No values, notes, headers, tokens or arbitrary messages enter performance logs.

### Late-data and extension boundary

BUFFERING/STALE/provisional views retain the original assessment time and show age with an injectable aware clock. Gap age, reconciliation and complete-through are shown only when supplied. Provisional and authoritative COMPLETE baseline values occupy separate panels. Corrected/reconciled publications can compare previous and corrected assessments. Queue movement counts require a matching publication context; selecting a newer queue remains deliberate.

The synthetic ten-minute fixture publishes separate assessments at 0/2/5/7/10 minutes and keeps earlier case score payloads and reviews unchanged. These are engineering fixtures, not an implementation of backend reconciliation workers.

Read-only Models, Retraining proposals, Evidence reports and Source health views require explicit flags and effective audit grants. Normal clients refuse the proposed routes; flags alone cannot enable live use. Disabled/missing views show “Not available in this build”. Pilot metrics remains later FE-16 work. Exact proposed routes/fields and monitoring-link restrictions are documented in `docs/ui_extension_contracts.md`.
