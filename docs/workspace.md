# Analyst workspace (Phase 10)

The Streamlit workspace uses only HTTP APIs. Its modules do not import database sessions, model loaders, prediction code or training adapters. API permissions remain authoritative when navigation is bypassed.

## Start

```powershell
python -m pip install --require-hashes -r requirements-ui-windows.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m ui.launcher --root . --port 8501
```

Linux uses `requirements-ui-linux.lock`. These locks extend the existing API locks; all six prior model/development/API locks remain unchanged. Arrow 25.0.1 is pinned because Arrow 26 requires NumPy 2, while the validated model runtime uses NumPy 1.26.4. The UI launcher binds to loopback, preserves Streamlit XSRF/CORS protection and disables usage telemetry. The approved identity gateway must protect shared deployment; see [identity flow](identity_flow.md).

`secrets/ui.json` is mandatory. It is intentionally absent until the organization’s identity integration is available. Normal startup does not substitute a signed fixture or infer authority from `st.user`/email headers. Starting `streamlit run ui/app.py` directly shows a safe blocked page if configuration is missing. Never run the synthetic visual fixture as a shared application.

## Investigation workflow

1. **Operations:** permitted users select a CSV and its declared manifest. The page displays the workspace upload/row limits; API validation remains authoritative. Submission returns a durable job identity and safely displayed findings or quarantine status. Automatic polling is bounded by `poll_seconds`. The job UUID in the URL lets an authenticated refreshed session reconnect without re-uploading. Only failed jobs expose authorized retry, with a reason and a retained idempotency key.
2. **Review queue:** select an explicit queue UUID, use server-side state/assignee filters and rank/key pagination. Rank, full-cohort percentile, raw review-priority score, assignee, workflow state, freshness and model version stay distinct. A new head is announced without switching the opened queue; refreshing to it is deliberate.
3. **Case evidence:** the selected immutable score remains pinned. Cutoff, completeness, freshness, research limitations and model/bundle/batch/policy/dictionary/snapshot identities precede contribution details. Observed, imputed and derived values, signed contributions, base/margin, reference percentiles and frequencies are displayed as model evidence. Anonymous F-fields remain unverified; no transaction behavior, destinations or legal conclusions are invented.
4. **Review:** assign, start review, enter a bounded note and select one allowed conclusion. Each form is bound to the case/version. The fetched expected version and one retained UUID accompany each explicit submit. A timeout means the outcome is unknown; retry the same saved action. A 409 displays the submitted version and latest API state and requires an explicit review of differences before a new action. Accepted actions clear affected caches and display the persisted event identity. Notes use text rendering rather than HTML.
5. **History:** independently paginated score, review and authorized audit histories preserve the selected evidence references. Later corrected assessment versions do not rewrite earlier reviews. Reopen reasons are stored through the same encrypted note/audit transaction; older records can honestly show that a reason is unavailable. Audit access does not imply note access.
6. **Exports:** authorized users choose the pinned queue, minimal columns and a reason. Sensitive columns appear only with an explicit API grant. The API authorizes and captures an encrypted immutable snapshot; only the requesting actor can fetch it before expiry, with permissions checked again. The UI does not generate its own CSV or bypass formula escaping and auditing.

Freshness labels explain complete, buffering, provisional escalation, stale and unavailable states without relying on color. An unavailable score is an em dash; a genuine zero remains zero. A provisional escalation references the retained authoritative baseline and warns that reconciliation remains pending.

## Session and failure behavior

Read caching is confined to the current server-side session. Keys include actor/role/scope fingerprint, endpoint, explicit queue/score version and filters, with a short TTL. Authorization, mutable case state, writes, notes history and downloads are never global cached decisions. Accepted writes, identity/scope changes, API authentication failures and logout invalidate sensitive state. Credentials never enter cache entries.

Pending writes retain the original payload/key across reruns and timeouts, preventing a new request identity from being created by a retry. Keep the session open until an uncertain action is resolved. After a browser/session loss, inspect durable job status or case history before starting a new action; pending payloads are deliberately not written to browser storage. Acknowledged jobs can reconnect by their URL job UUID. Two sessions cannot share cache contents or gateway bindings.

Safe error messages include an opaque request reference. They do not include server exception text, SQL, rows, notes or bearer tokens. The UI displays API downtime, denied scope, expired identity and version conflicts as distinct states. Candidate training/scoring always executes in the separately started API worker.

## Verification

Unit tests exercise the HTTP client, gateway assertions, scope-bound caches, pending writes, polling and freshness. Streamlit AppTest covers navigation, assignment, evidence, review, reopen reason, history and logout. A dedicated PostgreSQL walkthrough performs synthetic upload, validation, model scoring, actual Streamlit review, history, authorized export and job reconnection over real loopback HTTP. It records persisted IDs without editing operational rows by hand.

`tests/fixtures/ui/visual_entry.py` is explicitly gated to a private local test rehearsal. It uses an expiring signed fixture only, no real accounts, and is never imported by the production launcher. Organization identity integration, deployment and performance acceptance remain pending.
