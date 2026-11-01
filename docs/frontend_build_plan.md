# MAD frontend work — four-part build plan

Source: `C:/Users/omkud/Downloads/MAD_Frontend_Build_Prompts.md` (FE-0 through FE-16).

Status: Frontend implementation for Parts 1–4 (FE-0–FE-16) is delivered. Synthetic acceptance, lint/type checks and Compose validation passed. See `docs/acceptance/frontend_part1.md` through `frontend_part4.md`. FE-15 runtime deployment and FE-16 qualified/live acceptance remain BLOCKED/NOT_RUN on Docker, identity, backend-extension, qualified-data and owner-approval dependencies. Rich extension views remain fixture-backed as documented in `docs/ui_extension_contracts.md`.

This plan groups the supplied prompts into four sequential delivery parts. It is a frontend enhancement and gap-closure plan over the existing Phase 10 Streamlit workspace, not a reset of the architecture roadmap. Existing working pages, API security, package locks and verification evidence must be preserved. The downloaded document remains unchanged.

## Part 1 — Foundation, API contracts and shared design

**Prompt coverage:** FE-0, FE-1, FE-2, FE-3, FE-4, in that order.

Deliver:
- Audit the existing workspace against the prompt requirements; record reusable components, missing behavior and contract differences.
- UI specification, screen/action permission matrix, approved copy, state vocabulary and unknown-value handling.
- Calm, dense and legible investigation layout: neutral palette, one interaction accent, consistent typography, persistent research/version/time context, accessible status text.
- Validated settings, explicit display timezone, safe structured logging and safe error states.
- Typed API request/response models and HTTPX methods using the current saved OpenAPI contract.
- Deterministic synthetic mock responses and fault injection for local development/tests, with a persistent visible mock-data banner and no production fallback.
- Authentication/session integration, permission-aware navigation and reusable freshness, score, provenance, contribution, pagination and state components; a development-only component gallery.

Completion checks:
- Contract, configuration, logging, identity-isolation and component tests pass; applicable lint/type checks pass.
- Missing scores, unknown values, research status and incomplete data are rendered honestly.
- Existing authenticated workflows continue to work. No production page is replaced with a placeholder merely to follow a scaffold prompt.
- Shared login remains fail-closed when organization identity settings are absent.

Handoff: file changes, component/client interfaces, verified contracts, test results and unresolved identity/API dependencies.

## Part 2 — Main analyst workflow

**Prompt coverage:** FE-5, FE-6, FE-7, FE-8, in that order. Requires Part 1.

Deliver:
- Operations: upload and manifest controls, limits, durable job reconnect, bounded polling, validation/quarantine findings, authorized retry and scoring submission.
- Queue: immutable version selection, server-side permitted filters, stable cursor paging, rank/percentile/review-priority labels, workflow/freshness and explicit newer-version notices.
- Case detail: pinned assessment, provenance and research context, original cutoff, observed/imputed values, signed contributions, reference context and unverified feature meanings.
- Review: assignment, start-review, conclusion/note submission and reasoned reopen actions; retained payload/idempotency key, expected-version checks, persisted action IDs and explicit conflict resolution.

Completion checks:
- Operations → queue → evidence → review works through the API boundary.
- Refresh reconnects to the same acknowledged job, and version changes never silently change the opened assessment.
- Double submit, rerun and timeout retry produce one persisted action; stale writes require a deliberate decision.
- Permissions are enforced by the API even when navigation is bypassed.

Handoff: completed screen flows, tested state/action transitions, failure-state evidence and remaining API dependencies.

## Part 3 — History, exports and extended context

**Prompt coverage:** FE-9, FE-10, FE-11, FE-12, FE-13, in that order. Requires Part 2.

Deliver:
- Immutable assessment/review/audit history, original-review lineage, reopen reasons and supported assessment comparisons.
- Actor/scope/version/filter-bound per-session caches, invalidation and safe fetch/render timing measurements.
- Authorized version-bound export requests, explicit scope confirmation, bounded status polling and expiring API downloads; the UI does not generate its own CSV.
- Late-data experience: buffering, stale, unavailable, provisional and corrected/reconciled views, original versus corrected context and deliberate refresh.
- Feature-flagged, read-only extension viewers for models/governance, retraining proposals, replay/acceptance evidence and safe Grafana links.

Completion checks:
- Two actors cannot share private cached records, counts, notes or evidence.
- Historical reviews retain their original assessment after corrections.
- Export scope/version and expired/forbidden states are correct.
- The synthetic late-event timeline is understandable without color or optimistic wording.
- Missing extension routes show “Not available in this build”; blocked/not-run gates never appear passed. Model approval/promotion/rollback controls are not added.

Dependency boundary: FE-12 requires backend freshness/reconciliation fields; FE-13 requires API extensions. Mock-backed presentation can be completed first. Live integration remains unavailable until matching backend contracts exist. This part does not silently implement architecture Phases 11–13.

Handoff: cache policy, history/export evidence, mock timeline, extension flags and exact proposed API dependencies.

## Part 4 — Verification, deployment preparation and acceptance

**Prompt coverage:** FE-14, FE-15, FE-16, in that order. Requires Part 3 and the applicable backend/deployment prerequisites.

Deliver:
- End-to-end synthetic journeys and quarantine, downtime, expired identity, forbidden, conflict, rate-limit and server-error variants.
- Log/copy disclosure checks, keyboard/accessibility checks, real-stack integration variant and CI coverage.
- Acceptance walkthrough with revision/input/config identity, exact commands, expected/observed results, evidence and reviewer status.
- UI container/Compose integration, TLS/WebSocket ingress configuration, resource/filesystem restrictions, secret exclusion, health checks and identity-bypass/spoofing verification.
- Reproducible research demo, server-owned deployment-status display, shadow-pilot banners and feature-flagged read-only pilot metrics with denominators and label availability.

Completion checks:
- Applicable automated checks and synthetic journey pass; screenshots and persisted IDs support the results.
- Container/configuration and security checks have recorded evidence where executable.
- Demo runs without hand-editing operational state or exposing holdout rows.
- Missing organization identity, qualified data, pilot records or approvals remain explicitly BLOCKED/NOT_RUN with their dependency named.
- Human acceptance and production/pilot approval are recorded separately from software test results; tests cannot grant those approvals.

Handoff: final verification report, screenshots, deployment/run instructions, remaining blockers and owner-review checklist.

## Rules applying to all four parts

1. Build on the current Streamlit/FastAPI architecture; no database, model or raw-artifact access from UI modules.
2. Use actual API contracts and effective permissions before assumptions in the supplied prompts. Reconcile queue discovery, permission names, review conclusions, model selection, fields and freshness enums during Part 1.
3. Never fabricate success, probabilities, business meanings for anonymous fields or qualified-use approval.
4. Preserve per-user identity isolation. Reauthentication must not replay another actor's pending action; any pending-action recovery must be bound to the original verified actor and scope.
5. Keep organization login fail-closed. Synthetic fixture mode is explicit and isolated; deployment approval is not inferred from this plan.
6. Each part ends with beginner-friendly implementation explanations, exact verification commands/results and a handoff. Tests accompany the relevant work throughout; Part 4 adds comprehensive journeys and release checks.
7. Start implementation only when the user requests the corresponding part. No frontend implementation is authorized by the planning request alone.
