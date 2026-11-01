# FE-0–FE-4 handoff

Completed 2026-11-01 (Asia/Calcutta). Scope: Part 1 of `docs/frontend_build_plan.md`, enhancing the existing Phase 10 Streamlit workspace.

| Phase | Delivered |
|---|---|
| FE-0 | `docs/ui_spec.md`; independent status enums with UNKNOWN; approved copy and safe error messages |
| FE-1 | Validated timezone/TLS/timeouts/polling/page-size/extension settings; allowlisted JSON logging; preserved functional page shell |
| FE-2 | UI-owned request/response DTOs; typed HTTPX methods; bounded read retries and safe failures; 200-record isolated synthetic service with fault injection |
| FE-3 | Effective permission navigation; existing signed gateway integration preserved; same-actor/grant/scope/configuration pending-request recovery after expiry; explicit logout/discard |
| FE-4 | Freshness, score, research, provenance, badges, signed contributions, paging, time and error components; isolated development gallery |

## Verification

Final foundation verification: **238 tests passed**, including new frontend foundation tests, existing UI regressions, API authentication and domain contract tests. **mypy passed for 148 source files**. Applicable Ruff lint and formatting passed. All eight dependency lock files match the pre-work hashes in `artifacts/frontend/part1/baseline.json`; the saved API schema and backend behavior were not changed for Part 1.

```powershell
.venv/Scripts/python.exe -m ruff check ui tests/ui tests/unit/test_ui_app.py tests/unit/test_ui_client.py
.venv/Scripts/python.exe -m mypy src/mule_detection ui --cache-dir var/mypy-fe-final
.venv/Scripts/python.exe -m pytest tests/ui tests/unit/test_ui_client.py tests/unit/test_ui_auth.py tests/unit/test_ui_app.py tests/unit/test_api_auth.py tests/contracts -q --tb=short --basetemp=var/test-tmp-fe-release --junitxml=artifacts/frontend/part1/tests.xml
```

Evidence: `artifacts/frontend/part1/tests.xml`, baseline hashes and local gallery screenshot. The initial sandboxed type cache reported SQLite corruption; verification used a fresh local cache. Streamlit tests needed normal local temporary-file/thread access and passed there. PostgreSQL worker journeys were not rerun for this frontend-only foundation; prior Phase 10 evidence is preserved, not relabeled as a new run.

## Run the synthetic preview

```powershell
# Shared component gallery; explicit synthetic identity, loopback only
.venv/Scripts/python.exe -m ui.dev
# Existing workflow screens using the isolated synthetic API
.venv/Scripts/python.exe -m ui.dev --workspace
```

No dataset, database or model files are loaded. The mock is a deterministic contract simulator; jobs are controlled fixture states, not real workers. Normal `python -m ui.launcher` remains fail-closed. Production runtime rejects mock mode.

## Interfaces and contract decisions

See `docs/ui_spec.md` for the component signature table, API differences, screen states and permission matrix; `docs/frontend_part1_guide.md` explains file responsibilities and how to reproduce the implementation. Existing mapping-returning API methods remain compatible; new callers can use `get_case`, `get_queue`, `get_evidence`, `get_history`, `get_job`, `get_batch` and typed mutation/submission methods.

Freshness has five values, while CORRECTED/RECONCILED are separate publication events. Model tiers are `research_demo`/`candidate`. Queue discovery, permission names, conclusion enums, explicit bundle selection and export download routes follow actual OpenAPI/API implementation, replacing the prompt's unconfirmed assumptions. Missing full-cohort N/K, observation cutoff, baseline details or arbitrary-score navigation are not fabricated.

## Outstanding dependencies

Shared organization login remains **BLOCKED** until issuer, API audience/JWKS, gateway issuer/audience/JWKS and backchannel service configuration, approved login/client flow, role/group-to-scope mapping, ingress header stripping and session revocation are supplied and verified. Synthetic tests do not grant deployment/pilot approval.

Pending drafts survive expiry only within the same server session. Full browser-session loss/server restart is not durable draft recovery. FE-5–FE-8 will enhance Operations, queue, case evidence and reviews; FE-9–FE-16 remain separate future work.
