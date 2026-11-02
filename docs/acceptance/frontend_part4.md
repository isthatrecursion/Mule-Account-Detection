# FE-14–FE-16 handoff

Frontend implementation delivered on 2026-11-01 (Asia/Calcutta). Synthetic verification passed; live deployment and qualified-use acceptance are explicitly separate gates.

The frontend status record is `frontend_status.csv`. The original 170-point backend roadmap evidence is preserved rather than marked passed by a frontend fixture run.

| Phase | Delivered | Verification / remaining gate |
|---|---|---|
| FE-14 | Clean synthetic intake → queue → evidence → review → history → export journey; unknown acknowledgement recovery; failure variants; log/copy checks; opt-in real-stack wrapper; frontend CI job | **306 passed, 1 skipped** in the combined suite; the real PostgreSQL/API/worker wrapper is opt-in and was skipped |
| FE-15 | Same-image UI/API Dockerfile; private-network Compose overlay; separate database network; non-root/read-only/resource limits; protected secret mounts; TLS/WebSocket/auth-subrequest ingress; spoofed-header stripping; offline checker; build-once release-candidate workflow | Static deployment contract and Compose parsing PASSED. Docker Linux engine remained unavailable after a start attempt. Image build/health, image history and live TLS/ingress tests are NOT_RUN. Organization identity integration is BLOCKED |
| FE-16 | Explicit synthetic demo controls; server-decision display; shadow banner/stopping conditions; read-only pilot metrics with denominators, populations, maturity and label availability | Synthetic decision/metric tests PASSED. Qualified data, mature labels, deployment/pilot approvals and live status/metric extension contracts remain BLOCKED |

## Commands and evidence

```powershell
.venv/Scripts/python.exe -m ruff check ui tests/ui scripts/verify_ui_deployment.py
.venv/Scripts/python.exe -m ruff format --check ui tests/ui scripts/verify_ui_deployment.py
.venv/Scripts/python.exe -m mypy src/mule_detection ui --cache-dir var/mypy-fe-part4
.venv/Scripts/python.exe -m pytest tests/ui tests/unit/test_ui_client.py tests/unit/test_ui_auth.py tests/unit/test_ui_app.py tests/unit/test_api_auth.py tests/contracts -q --tb=short --basetemp=var/test-tmp-fe4-release --junitxml=artifacts/frontend/part4/tests.xml
.venv/Scripts/python.exe scripts/verify_ui_deployment.py
.venv/Scripts/python.exe -m ui.dev --demo --port 8520
```

Lint/format checks passed. Type checking passed for **159 source files**. The combined suite passed **306 tests**, with **one explicit integration skip**. Dependency locks are unchanged from the foundation baseline. The normal/container launcher still returns `UI_IDENTITY_CONFIGURATION_REQUIRED` when protected trust settings are absent.

Evidence: `artifacts/frontend/part4/tests.xml`, `deployment.json`, `verification.json`, screenshots, and the generated matrix in `docs/acceptance/ui_walkthrough.md`. Earlier Phase 10 PostgreSQL evidence remains separate; it is not relabeled as a new run.

## Output and reproducible demo

The live output is the loopback-only synthetic preview at `http://127.0.0.1:8520`. Follow `research_walkthrough.md` for a clean store, synthetic validation/scoring receipts, review recovery, export and late correction. The fixture banner and research limitations stay visible. No private data, holdout row, real model or database is loaded by the preview.

The fake service simulates worker completion and example pilot aggregates. Its decision record is explicitly a synthetic fixture illustration. A server-declared SHADOW record adds “Shadow pilot: recommendations only, no account actions”. Missing approval identity or research-only PILOT inputs produce BLOCKED. Actual API permissions remain authoritative; displaying a decision does not add a promotion control or override authorization.

## Deployment handoff

Read `docs/ui_deployment.md` before deployment. The opt-in command uses `compose.yaml` plus `compose.workspace.yaml`; the existing persistence-only default is preserved. Both services require one externally supplied immutable application digest. The release workflow builds once and saves that exact image artifact, checksum and image ID; organization publishing must record its registry manifest digest and promote that same image without rebuilding.

The UI mounts only its `ui.json`. It has no raw/model/artifact/database-secret mount and does not join the database network. The API and UI use private networks; the ingress alone publishes a loopback TLS port by default. The `/v1/` TLS route preserves the API bearer for independent JWT verification. UI routes replace the opaque session header using the approved gateway subrequest. Missing gateway include/certificates/configuration fail closed.

No real issuer, audience, client, callback URL, gateway endpoint, TLS certificate or role-to-scope policy was guessed. File-secret host permissions, egress restrictions, backend source/model mounts, migrations, worker orchestration and target-environment ingress tests are deployment-owner prerequisites. The Docker CLI was installed, but the Linux engine stayed unreachable; container/image runtime evidence is NOT_RUN.

## File walkthrough

`tests/ui/journeys/` supplies the complete synthetic flow and an explicitly skipped-by-default real-stack wrapper. The latter delegates to the existing PostgreSQL/API/worker integration test and suppresses raw subprocess errors. `test_log_safety.py` checks a full signed-credential review/evidence/error path for credential/note/feature-value disclosure. `test_forbidden_copy.py` renders every screen with approved copy scanning. `test_deployment.py` checks private services and direct-header denial; those tests do not claim a live ingress test.

`ui/extensions.py` adds typed decision and pilot metric contracts. Invalid/missing approval, denominators or label evidence cannot become a qualified pass. `ui/components/deployment.py` displays server-owned use/allowed actions/stopping conditions. `ui/pages/pilot.py` separates reviewed-sample findings from eligible-population workload and renders the label denominator/maturity for every metric. These use proposed, fixture-only read extensions until backend agreement.

`ui/mock/demo.py` creates a clean generated fixture, calls the same HTTP client/state path as the screens, and exposes explicit fake-worker/fault/timeline controls. Normal runtime never imports it. `ui/dev.py --demo` chooses this isolated entrypoint; `ui.container.py` instead validates protected settings before binding the private container port and disables production watcher/telemetry.

`docker/Dockerfile.app` packages UI/API source with the existing hash locks. `compose.workspace.yaml` adds least-privilege service boundaries. `docker/nginx/` defines TLS/WebSocket and verified-session forwarding without a credential fallback. `scripts/verify_ui_deployment.py` validates static invariants and Compose parsing without loading private secrets. Its NOT_RUN/BLOCKED fields are intentional acceptance outcomes.

## Remaining approval and evidence requirements

- Organization identity/gateway/TLS settings and target-environment integration: BLOCKED.
- Application image build/health, image-history inspection and live ingress spoof/bypass/WebSocket verification: NOT_RUN while Docker engine and protected inputs are unavailable.
- New live deployment-status/pilot-metric API contracts: BLOCKED pending backend-owner agreement.
- Qualified predictive claims/pilot rollout: BLOCKED pending independent qualified data, mature labels and recorded authorized approvals.
- Full keyboard, screen-reader and owner visual acceptance: NOT_RUN; semantic/status and functional widget checks are automated, and the contrast calculation is recorded separately.

The build does not grant those approvals. Architecture Phases 11–15 are not automatically marked passed by frontend fixture tests.
