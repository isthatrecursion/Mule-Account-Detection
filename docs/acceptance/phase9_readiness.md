# Phase 9 readiness

Implementation covers P09.01–P09.10: authenticated application factory, durable jobs, versioned queues, pinned case evidence, transactional reviews, separate conclusions/outcomes, approved outcome intake, server-side scope grants and audited exports.

Software verification PASSED: **368 tests**, including **117 PostgreSQL integration cases**, and all 11 verification steps (dependency consistency, lint, format, strict types, full tests, contract snapshots, specification, CLI and build). Checked package/config/test sources remained unchanged during the final run. The fresh installed API wheel also passed all six installation checks, including actual signed-token HTTP and fail-closed missing trust. The clean database rehearsal passed 57 HTTP/persistence checks from migrations 0001–0009. No real dataset scoring or holdout access was performed.

The final evidence directory is `artifacts/phase9/windows_api_verified`; its report records source hashes, commands, test results and runtime package identities. Installed package evidence is recorded separately under `artifacts/phase9/wheel_verified`. The earlier `windows_api_final` directory is explicitly superseded and is not acceptance evidence.

| Point | Implementation and verification |
| --- | --- |
| P09.01 | `api/app.py`, strict input/output DTOs and saved OpenAPI; missing trust rejects normal startup, injection requires isolated test settings, errors are static and readiness checks schema/storage. |
| P09.02 | Encrypted durable upload before 202; PostgreSQL task payloads and leased workers; restarted service reloads tasks; real synthetic training/scoring through production worker composition. |
| P09.03 | Explicit queue UUID, rank/key cursors, bounded pages, allowlisted filters, scope before count and pagination; old queue remains pinned across a newer head. |
| P09.04 | Scoped selected-score detail and encrypted evidence; immutable batch/model/bundle/policy/dictionary/snapshot references; paginated history and explicit newer assessment reference. |
| P09.05 | Expected version, actor-bound idempotency, assignment ownership, concurrent CAS conflict and atomic case/event/encrypted-note/audit transaction; injected audit failure rolls back all database effects. |
| P09.06 | Conclusions append through review events and never write Label rows; reopening appends a new workflow version. |
| P09.07 | Approved source ownership, stable identities, label maturity/cutoff/supersession validation, immutable contracts and historical as-of selection; review-selected provenance never claims population recall. |
| P09.08 | Signed RS256 HTTP tests, altered/unsigned/expired/wrong-audience/issuer/future tokens denied; spoof headers ignored; combined group grants retain their own permission scopes. |
| P09.09 | Scoped actor-only expiring downloads, encrypted authorization snapshots and CSV artifacts, current sensitive-column grants, immutable state and metadata, Unicode/multiline and formula safety. |
| P09.10 | Real HTTP with dedicated PostgreSQL runtime permissions, all five roles, direct object denial, concurrency, changed-key conflicts, revoked/expired/policy-changed jobs, clean migration and installed-wheel HTTP checks. |

Separate evidence includes `fresh_postgresql/report.json` (new database from migrations 0001–0009), `lock_preservation.json` (four existing locks unchanged), and `package_manifest.json` (wheel/sdist content and hashes). Local software evidence does not substitute for the blocked integration and owner decisions below.

Normal startup is deliberately blocked until the organization supplies OIDC issuer, audience, JWKS location and group-to-role/scope mapping. The user explicitly chose fail-closed startup. Static signing keys and service injection are restricted to isolated test applications.

All earlier research limitations remain: source and target are confounded; the 1,817-row holdout is untouched; representative mature outcomes and qualified source evidence are absent. Adjudicated outcome intake requires independently approved source ownership and stable identity bindings. No model approval, account restriction, filing or production-quality acceptance is implied.

Owner review, live organization identity integration, deployment, performance acceptance and remote CI execution remain pending. See `docs/api.md` for setup and operational behavior.
