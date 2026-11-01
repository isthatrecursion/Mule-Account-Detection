# Proposed frontend read extensions — FE-12 / FE-13

**ASSUMPTION: these routes are fixture contracts, not deployed API endpoints.** Normal `ApiClient.extension` refuses them before making an HTTP request, even if a UI feature flag is enabled. Matching backend contracts, authorization mapping and backend-owner agreement are required before a future live implementation removes that guard. No backend roadmap Phase 11–13 completion is implied.

All proposed reads use the existing API audience and effective scope authorization. For development only, case context uses `case:read`, queue context uses `queue:read`, and governance/report/source/proposal viewers use `audit:read`. These mappings require explicit API-owner review before live use; they are not new permission names or a production role policy.

## Envelope and routes

Each response has `kind` and a nonempty immutable `revision`. Unknown/missing required schema data fails safely. Proposed models are defined in `ui/extensions.py`.

| GET route | Kind | Required payload / binding |
|---|---|---|
| `/v1/ui-extensions/models` | `models` | `models[]`: environment, bundle_digest, data_tier, model_tier, approval_state, requester, reviewer, gates[], deployment/rollback events[] |
| `/v1/ui-extensions/proposals` | `proposals` | `proposals[]`: proposal_id, trigger, status, supporting_report_ids[] |
| `/v1/ui-extensions/reports` | `reports` | `reports[]`: report_id, scenario_fingerprint, evidence_class, during_delay_disagreement, final_consistency, gates[] |
| `/v1/ui-extensions/source-health` | `source-health` | `sources[]`: registered source_id, oldest_open_gap_seconds, pending_reconciliation, complete_through |
| `/v1/ui-extensions/case-context/{case_id}` | `case-context` | case_id, score_id matching the pinned assessment; optional baseline/corrected assessments and sources[] |
| `/v1/ui-extensions/queue-context/{queue_version}` | `queue-context` | queue_version matching the explicit publication; entered_count and left_count for published membership movement |
| `/v1/ui-extensions/deployment-status` | `deployment-status` | decision: record_id, revision, mode, data_tier, model_tier, approved_by, allowed_actions[], stopping_conditions[], blocking_dependencies[] |
| `/v1/ui-extensions/pilot-metrics` | `pilot-metrics` | decision_record_id binding the decision above; metrics[] with fixed metric_id, numerator/denominator, population, label counts/denominator, maturity, state/reasons, optional freshness/correction counts |

No writes, decisions, promotions, rollback requests, account actions or arbitrary external URLs are part of these contracts. Responses must be filtered by effective permission scopes on the server, including aggregate counts.

The decision endpoint is proposed authenticated context metadata, not an authority derived from browser claims. Pilot metrics use fixture audit-read grants pending backend-owner agreement. Metric IDs exclude inferred population recall; reviewed samples and eligible-population workload remain separate. Missing/zero denominator or absent mature-label evidence renders NOT_RUN/BLOCKED. Pilot decisions using research-only data/model inputs are blocked. An approval identity is required for any nonblocked declared use. Neither endpoint is enabled for normal clients by this implementation.

## Field semantics

An assessment contains `score_id`, `case_id` where available, `model_id`, `queue_version`, the actual `ScoreVersion` payload and optional `EvidenceFacts`. Baseline/corrected scores are separate objects: a provisional value never overwrites the baseline. A baseline numeric panel requires a COMPLETE baseline. Original assessment time stays unchanged. Historical contributor comparisons require evidence for both selected score IDs; when absent, the UI says it is unavailable.

Source ages are nonnegative integer seconds. `complete_through` must be timezone-aware. Missing gap age or reconciliation status remains “Not supplied”. Source context is not a license to replace the original score cutoff with refresh time.

Gates contain `name`, state (`PASSED`, `FAILED`, `BLOCKED`, `NOT_RUN`, `UNKNOWN`), reasons[], numerator, denominator and trials. A claimed PASSED gate with missing/zero denominator or missing/zero trials renders NOT_RUN with the missing-evidence reason. Numerator cannot exceed denominator. During-delay disagreement and final consistency are separate measurements. Evidence class is explicitly `SYNTHETIC_ENGINEERING` or `QUALIFIED_PREDICTIVE`; synthetic passes never grant predictive or deployment approval.

Governance state is server supplied and remains separate from model tier. Requester and reviewer identities are shown to expose separation of duties; identical identities trigger a warning. There are no approve/promote/rollback controls.

Monitoring URLs are built from protected `grafana_base_url` and `monitored_sources`, a fixed dashboard path and only environment/source filters. HTTPS, a recognized environment and a configured source slug are required. No API-provided arbitrary URLs, tokens, notes, account identifiers or export URLs enter the link. No monitoring link is shown by default.

## Existing API limits preserved

Current `/history?kind=scores` returns score/rank/freshness/model/queue metadata, not full historical contribution sets. The core comparison works with those supplied fields; richer contribution comparisons use only matching extension assessments. Existing case reads remain pinned.

Current export jobs return status, creation time and opaque result, not an exact scope/expiry/provenance-summary object. The UI retains its submitted request receipt within that server session; after a new session, absent receipt data is explicitly unavailable. Downloads use only the fixed authenticated API job route, never an assumed signed URL. The server checks actor, scope and expiry per download. Exact export metadata would require an independently agreed API extension, not guessed fields in this proposal.

## Safe rollout conditions

Backend owners must agree route/schema versioning, scope filters, measurement definitions, qualified-evidence provenance, immutable revisions, error behavior and bounds before live integration. Contract tests against that real API must pass. UI flags alone do not establish availability, qualification or approval. The normal runtime continues to fail closed without organization identity configuration.
