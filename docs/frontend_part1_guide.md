# Frontend Part 1 — implementation guide

Read this alongside `ui_spec.md`. It explains the code in small functional groups, so you can follow how data moves through the application.

## 1. Start with names and wording

`ui/enums.py` uses Python string enums: a value can behave like a string while belonging to a known category. `_missing_` maps future server values to UNKNOWN. `presentation` adds a readable label, explanation, text marker and supplementary color token. Freshness, publication event, workflow, job, ingestion and tier remain separate types.

`ui/copy.py` collects approved labels and safe error messages. `find_forbidden` normalizes case/whitespace and checks phrase boundaries. It scans authored wording; it does not rewrite analyst notes or fabricate business meanings.

## 2. Validate configuration before opening pages

`ui/config.py` declares each setting and its bounds. `trust` checks timezone, environment, HTTPS, fixture isolation and polling relationships. `fingerprint` hashes non-secret configuration for session binding. `load` reads only the protected deployment file and replaces parsing errors with a safe configuration failure. The example file keeps organization settings null intentionally.

`ui/logging_setup.py` builds a JSON dictionary from an allowlist. It deliberately ignores log messages and exception bodies because they can contain notes or credentials. `configure_logging` installs that formatter once; `event` is the small call site used by the API client.

## 3. Define API shapes independently

`ui/dto.py` contains UI-owned Pydantic models. `Response` accepts extra future fields, while `Request` rejects extra submitted fields. UUIDs, aware timestamps, bounded versions, finite scores and closed request enums validate data at the boundary. Validators reject unavailable assessments that claim numeric/published values. `parse` converts validation errors into a safe ContractError without including input values.

The history collection has intentionally opaque extra fields because the saved API schema describes mixed score/review/audit dictionaries. This is documented uncertainty, not an invented complete schema. Evidence has explicit raw contribution fields and expandable encoded detail.

`ui/errors.py` gives failures stable classes/codes. Request references must be UUIDs. A malicious response header or server error body cannot become displayed error text.

## 4. Send requests through one client

`ui/api_client.py` constructs HTTPX with bounded timeouts, TLS verification and redirects disabled. `_once` attaches the current provider's bearer credential and a request UUID, bounds response size and maps HTTP failures. `request` retries only GETs, at most three attempts, with short backoff. POST errors return immediately to pending-write state.

`response_model` maps supported routes to models. `json` validates them while preserving mapping returns for the existing pages; `typed` provides typed returns for new work. Public methods cover identity, queues, cases, evidence, history, jobs, batches, intake, scoring, training, retry, assignment, start review, review, reopen, export/download, health and model details. Callers cannot select an arbitrary download host.

## 5. Keep identity and requests in one session

`ui/auth.py` preserves the existing signed gateway assertion checks. Its injected clock makes renewal boundaries testable. It does not derive UI permissions from token claims; `/v1/me` supplies effective grants.

`ui/permissions.py` intersects a permission's scope grants with the identity's scopes. `build_navigation` uses those effective permissions to offer screens. The HTTP API still checks every operation.

`ui/state.py` owns the private read cache, selected versions and pending request. `begin` generates a key once and copies the payload. `submit` retains that request after an unknown outcome, fetches current case data after a conflict and records acknowledged IDs. `suspend` clears private screen state while retaining only an unresolved request. `restore_pending` requires the same actor, grants, scopes and configuration fingerprint; it never submits automatically.

`ui/app.py` composes configuration, authentication, navigation and shared errors. Its expiry gate hides private widgets and offers explicit resume or discard. Explicit logout clears all sensitive state. The existing page renderers remain in use.

## 6. Format facts before rendering them

The component modules separate small pure functions from Streamlit calls:

- `time_fmt`: parse aware timestamps and convert to the configured named timezone.
- `score`: return three display strings; unknown/missing values are dashes, valid zero is preserved.
- `freshness`: show status, original cutoff, publication time and separate publication event; source detail can be expanded.
- `research_banner`: use supplied tiers, with a separate in-sample notice.
- `provenance_header`: place IDs, versions, times and limitations before interpretation.
- `badges`: include category plus marker and explanation; color is supplementary.
- `contribution_chart`: build signed bars and a visible value table; display scale and base/raw output, and preserve encoded detail.
- `pager`: reset cursors when version or filters change; never carry a cursor to another publication.
- `status_views`: present loading, empty and safe failure states with stable codes/request IDs.

Case detail and queue now use the shared score wording/formatting. Case provenance precedes evidence. History uses the explicit timestamp formatter and tolerates absent notes. These are foundation integrations; the later screen redesign work remains in Part 2/3.

## 7. Develop without real account data

`ui/mock/backend.py` provides deterministic records and an in-memory service behind HTTPX MockTransport. The client still serializes requests and validates responses. The service verifies signed fixture credentials, scope/permission grants, workflow versions and idempotency. Fault injection can simulate failure before or after a write commits. No real model or database is loaded.

`ui/dev.py` starts only a loopback Streamlit server. `ui/mock/entry.py` requires its explicit development flag; normal runtime never selects it. `_gallery.py` renders every shared component category and failure state with the fixture banner. Jobs stay in controlled synthetic states until a test changes them; this is not a worker demonstration or production simulator.

## Write it yourself recap

1. Read the saved API schema and write the field/permission differences down.
2. Define category enums, approved labels and safe error codes.
3. Validate settings and construct typed requests/responses.
4. Build one HTTP client and test errors/retry limits before screens.
5. Add identity-bound session state and explicit pending-write recovery.
6. Build pure formatting helpers, then thin renderers and the gallery.
7. Verify contracts, permissions, expiry/conflict behavior and existing flows; keep production startup blocked until real trust settings exist.
