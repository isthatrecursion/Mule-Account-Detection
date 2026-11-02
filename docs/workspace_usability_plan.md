# Workspace usability correction plan

Prepared: 2026-11-01 (Asia/Calcutta).

Status: frontend corrections implemented. Verification and remaining API dependencies are recorded in [workspace usability acceptance](acceptance/workspace_usability.md).

## Target experience

The main workflow is: review queue -> open case -> examine evidence -> record a decision -> inspect history or export when needed.

The first screen should show cases and their available actions. A case should immediately identify the record, review state, assignee, assessment priority and freshness. Detailed technical references remain available beside that context, behind an expandable section.

Keep the current Streamlit/FastAPI architecture. Preserve API permissions, pinned assessments and queue versions, server ordering, private session state, expected-version checks, retained request identities and authenticated downloads. Layout changes must not bypass the established assignment/start-review/save transitions.

## Changes mapped to the ten findings

### 1. Useful content starts too far down the page

- Replace the full deployment block above every page with a compact workspace status area and an expandable deployment-details section.
- Keep the synthetic-data indicator visible in mock mode. State research limitations once in the shared status area, with the full explanation expandable.
- Keep blocking action errors, unresolved requests, identity failures and exceptional freshness warnings visible where relevant. Compacting status must not hide a restriction or imply approval.
- Reduce the oversized shared heading and spacing so the selected page's task content starts higher.
- Files: `ui/app.py`, `ui/components/deployment.py`, `ui/components/research_banner.py`.
- Done when: at a 1366 x 768 desktop viewport the queue heading, filters and first cases are visible without scrolling in normal and demo modes. Blocking configurations show their required blocking state instead.

### 2. Unrelated responsibilities share one flat navigation

- Group navigation into Investigation (Review queue, Case evidence, History), Operations (Data intake, Scoring/training, Jobs), and Governance (live-supported model/source/pilot views).
- Present Exports as an investigation utility with queue context carried forward.
- Default queue-authorized users to Review queue. Users without queue access land on their first permitted task.
- Keep groups permission-aware; omit empty groups. Preserve existing grants rather than inventing new role rules.
- Initially, Operations subviews may share the existing page/controller; the grouping does not require new backend endpoints.
- Files: `ui/app.py`, `ui/permissions.py`, `ui/pages/operations.py`.
- Done when: investigation tasks are visually distinct from operational and governance tasks, and every currently permitted action remains reachable.

### 3. Demo controls compete with normal navigation

- Move simulation controls into a collapsed, clearly named Developer demo tools section, shown only in the explicit preview entrypoint.
- Keep the synthetic-data indicator visible even while tools are collapsed.
- Group fake-worker, late-data and fault-injection actions within those tools. Keep them out of the normal navigation list.
- Files: `ui/mock/demo.py`, `ui/mock/entry.py`.
- Done when: the initial demo view shows the normal workflow; tools remain accessible on demand and absent from normal runtime.

### 4. Opening a queue case requires matching its UUID twice

- Add a directly associated Open case action to each displayed row using native Streamlit controls. Remove the separate Case to open UUID dropdown.
- Keep rank, record reference, review priority, assignee, workflow state and freshness in the main row. Put the model version in the queue header rather than repeating it in every row.
- Arrange filters in a compact toolbar; move page size and technical queue references into secondary controls.
- Use the existing `workspace.open_case` path so record, queue and assessment context remain pinned.
- Retain server-side filters and cursor pagination; do not add client-side sorting that misrepresents published rank.
- Files: `ui/pages/queue.py`, `ui/state.py`.
- Done when: activating a row's Open action reaches that exact case in one action, including after filtering and pagination, with keyboard access.

### 5. Case actions and useful context are buried

- Begin with a compact case summary: record reference, state, assignee, rank, review-priority score, percentile and freshness/cutoff.
- Add a visible Back to queue action that preserves the opened queue and pagination context.
- Use a desktop split layout: evidence in the main column; the current permitted review action in a bounded adjacent panel. Use a readable stacked order on narrow screens.
- Put score/model/bundle/batch/policy/dictionary/snapshot/queue references in Assessment provenance, collapsed by default.
- Keep critical stale, unavailable and provisional/baseline context visible. Preserve explicit selection of newer assessments.
- Files: `ui/pages/case_detail.py`, `ui/components/provenance_header.py`, `ui/components/actions.py`, `ui/components/late_context.py`.
- Done when: case identity, state, assignee and the available next action are visible before detailed contributions. The full evidence and provenance remain accessible.

### 6. Repeated facts and warnings dilute attention

- Assign each message one owner: shared workspace area for environment/research mode; case summary for freshness/cutoff; evidence section for interpretation limits; provenance for technical references.
- Remove duplicate assessment time, publication time and completeness renderings across provenance and freshness.
- Show a short contribution explanation once, alongside the scale and reconciliation information. Retain the chart and accessible value table.
- Render unknown values consistently and distinguish a missing value from a genuine zero.
- Files: `ui/copy.py`, `ui/components/freshness.py`, `ui/components/research_banner.py`, `ui/components/provenance_header.py`, `ui/components/contribution_chart.py`.
- Done when: facts have one primary location, and exceptional conditions remain clear without repeated generic banners.

### 7. Routine actions require copying internal IDs

- Add Assigned to me and Unassigned conveniences using supported API behavior; retain exact actor-ID entry as an advanced option. Do not derive a complete staff directory from a bounded queue page.
- Carry a successful intake's accepted batch into scoring submission and expose session-known accepted batches with clear labels.
- Use existing queue discovery for export selection, defaulting to the pinned queue. Show a readable queue label with the exact version in details.
- Move manual case/job IDs into Open by ID or Reconnect sections. Label opaque record keys honestly; do not invent customer names.
- Keep advanced entry for an approved bundle digest until an authorized discovery endpoint exists. Never treat the current model-details endpoint as a list of approved scoring bundles.
- Backend follow-up: permission-scoped user lookup, accepted-batch listing and approved scoring-bundle discovery if complete pickers are required. Specify labels, pagination, scope and eligibility before implementing those endpoints.
- Files: `ui/pages/queue.py`, `ui/pages/operations.py`, `ui/pages/exports.py`, `ui/components/actions.py`, `ui/api_client.py`, `ui/dto.py`.
- Done when: the ordinary queue/review/export journey needs no manually copied UUID, and intake-to-scoring carries known batch context. Remaining digest/manual entry is explicit until backend discovery is available.

### 8. Fixture previews resemble live-supported product sections

- Build normal navigation from configured, actually supported capabilities and effective permissions. Omit unavailable extension pages from the normal task list.
- In demo mode, place Models, Retraining proposals, Evidence reports, Source health and Pilot metrics under a clearly marked Preview section.
- Label each preview as synthetic and explain that live integration is pending. Do not show a preview as a live capability merely because its flag is enabled.
- Preserve explicit unavailable feedback for direct attempts to open unsupported pages.
- Files: `ui/permissions.py`, `ui/app.py`, `ui/pages/extensions.py`, `ui/pages/pilot.py`, `ui/api_client.py`, `ui/mock/demo.py`.
- Done when: users can distinguish supported tasks from synthetic previews before opening them; live extension integration remains a separately recorded backend dependency.

### 9. History reads like a database field dump

- Keep history within the selected case's context, with a direct return to its evidence view.
- Render events as a readable timeline: time, action, actor, conclusion and authorized note/reopen reason first.
- Put event/score/model/queue identifiers and workflow versions behind event details.
- Use readable action and conclusion labels while preserving exact API values in details and request payloads.
- Keep review, assessment and audit collection controls explicit. Retain their current independent pagination; do not pretend separately paginated collections form one complete chronological feed.
- Label assessment comparisons with time and version instead of UUID alone; retain the current bounded-page comparison limitation visibly.
- Files: `ui/pages/history.py`, `ui/components/comparison.py`, `ui/copy.py`.
- Done when: a reviewer can identify who did what, when, and why without expanding technical details; historical assessment links and note permissions remain correct.

### 10. Export controls are misleading and incomplete

- Resolve each connected job's kind before rendering export controls. Show export refresh/status/download controls only for export jobs.
- Remove the Fetch authorized download control that retrieves and discards CSV bytes. Keep one Download CSV action that performs fresh authorization.
- Add Reconnect export by job ID on the Exports page; resolve the job and verify its kind before accepting it as an export. Handle invalid, forbidden, missing and non-export IDs clearly.
- Keep automatic polling bounded and scoped to relevant jobs; an unrelated job must not keep the Exports page polling.
- Present selected queue, columns, state and authorized scope together before the existing explicit confirmation/reason submission.
- Preserve server-frozen export contents, API permissions and expiry handling. Display exact expiry only if supplied by the backend.
- Files: `ui/pages/exports.py`, `ui/state.py`, `ui/app.py`.
- Done when: mixed job sessions produce no unrelated export controls, reconnect works from Exports, and download makes the required authorized request without a preliminary discarded file fetch.

## Implementation order

1. **Export defects (point 10):** fix misleading job controls, reconnect, download and page-specific polling; add focused behavior regressions.
2. **Workspace structure (points 1, 2, 3, 8 and shared parts of 6):** compact status, grouped navigation, collapsed developer tools and clearly separate previews. Capture before/after screens.
3. **Main investigation flow (points 4, 5, remaining 6 and frontend parts of 7):** direct row actions, case summary, accessible review panel, consolidated messaging and context handoffs.
4. **History and completion (point 9 and remaining 7):** readable event presentation, contextual export selection and advanced ID entry. Record backend discovery dependencies separately.

Each increment should leave the existing workflow usable. The frontend work can proceed without waiting for new lookup endpoints. Full selector coverage under point 7 cannot be claimed until those endpoints are available.

## Verification and completion evidence

- Update existing queue, review, case, export, history, permission and journey tests for changed controls. Add behavior regressions for wrong-case selection, mixed job kinds, export reconnect, contextual handoffs and accidental exposure of preview controls.
- Recheck conflict and timeout recovery, identity/scope changes, missing permissions, unavailable evidence, provisional/baseline separation and expired downloads where the layout/state changes touch them.
- Exercise one full synthetic journey: intake -> scoring -> queue -> open case -> assign -> start review -> save -> history -> export -> download. Also test returning to the same filtered/paged queue.
- Inspect rendered screens at desktop and narrow widths. Confirm the first-viewport requirements, readable tables, keyboard focus, native labels and action reachability. Include complete/stale/provisional cases and a mixed-job export session.
- Run applicable Ruff, mypy and existing UI/contract tests. Report actual results and distinguish synthetic verification from any live integration checks.
- Save before/after screenshots and a ten-point pass/dependency checklist. Completion requires observed UI evidence for each frontend fix; automated test counts alone do not establish usability.

## Scope boundary

This plan covers correction of the current workspace. A frontend framework migration, new model training behavior, production deployment and implementation of proposed governance/monitoring APIs are separate work. Existing research limitations and feature-meaning constraints remain accurately communicated in the revised layout.
