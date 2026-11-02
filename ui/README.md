# Analyst workspace

The workspace now groups investigation and operations, opens cases directly from queue rows, keeps review controls beside evidence, and collapses technical provenance and demo tools. See [usability changes and verification](../docs/acceptance/workspace_usability.md).

Phase 10 implements the Streamlit client through authenticated FastAPI contracts. Page modules never load models or query PostgreSQL. See [setup and workflow](../docs/workspace.md), [gateway identity contract](../docs/identity_flow.md) and [verification](../docs/acceptance/phase10_readiness.md).

Install the platform `requirements-ui-*.lock`, install this package, then run `python -m ui.launcher --root <project-directory>`. Normal startup requires protected `secrets/ui.json`; the incomplete example intentionally fails closed. No shared demo identity or token-paste flow is available.
# Frontend enhancement previews

The FE-0–FE-4 foundation adds an isolated synthetic component gallery:

```powershell
.venv/Scripts/python.exe -m ui.dev
.venv/Scripts/python.exe -m ui.dev --workspace
.venv/Scripts/python.exe -m ui.dev --workspace --extensions --late-stage PROVISIONAL_HIGHER
.venv/Scripts/python.exe -m ui.dev --demo --port 8520
```

All previews bind to loopback and show a fixture identity/data banner. Normal startup remains fail-closed pending organization identity configuration. See `docs/ui_spec.md`, `docs/acceptance/research_walkthrough.md` and `docs/acceptance/frontend_part4.md`.
