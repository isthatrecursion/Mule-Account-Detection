# Clean synthetic research walkthrough — FE-16

This walkthrough uses generated fixtures, signed fixture credentials and a simulated HTTP service. It loads no research CSV, private artifact, database, real account or holdout row. It demonstrates UI behavior, not predictive performance or production identity. Research and in-sample limitations remain visible.

## Start clean

From the project directory in PowerShell:

```powershell
.venv/Scripts/python.exe -m ui.dev --demo --port 8520
```

Open `http://127.0.0.1:8520` in a new browser session. The explicit fixture entrypoint creates a fresh service store and ephemeral signing key. The normal launcher and shared deployment never select this entrypoint. Confirm the MOCK DATA banner and the server-declared RESEARCH_DEMO decision, whose approver is explicitly a synthetic fixture identity. Its qualified-use and organization-identity dependencies stay BLOCKED.

## Walkthrough

1. Click **Validate synthetic batch** in the sidebar. The controller generates fixture bytes/manifest and submits the normal HTTP intake request; the fake worker completes its controlled validation fixture. Operations shows a job receipt, SUCCEEDED job status and separate ACCEPTED ingestion status. These are distinct fields.
2. Click **Publish synthetic queue**. Inspect the persisted job ID and immutable bundle digest. This is simulated scoring, not a live LightGBM run. The actual backend worker journey is a separate opt-in integration check.
3. Select **Review queue**. Confirm the explicit queue version, rank, review-priority wording, cohort-percentile wording and server-filtered matching count. Open its case.
4. Inspect research/provenance first: original cutoff, published time, model/bundle/policy/dictionary IDs and source completeness. The in-sample fixture limitation is displayed. Signed contributions show field IDs, observed/imputed values and unverified meanings.
5. Click **Assign case**, then **Start review**. To demonstrate recovery, click **Simulate next review acknowledgement loss** before saving. Enter a synthetic note and click **Save review** once. The fake server commits once but loses its acknowledgement. The pending request retains the original UUID key and payload.
6. Inspect the unknown-outcome state, then click **Check outcome / retry the same request**. One persisted review receipt is shown. The case is REVIEWED; its conclusion is not an outcome label. Review event counts do not increase on rerun/retry.
7. Select **History**. Confirm assignment/start/review events, original score ID and note. Select score history later to compare publications; contributor comparison is available only for matching fixture extension assessments.
8. Select **Exports**, enter a synthetic reason, confirm queue/filter/columns/scope and authorize once. Click **Process pending synthetic jobs**. Fetch/check the authorized download, then use **Download CSV**. The UI requests bytes from the fake API per click; it never builds an export locally.
9. Select a **Simulated late-data stage** and click **Publish next synthetic assessment**. Use BUFFERING, STALE, PROVISIONAL_HIGHER and CORRECTED in sequence. A newer-queue notice offers deliberate selection. Open the new case to see original age/source gaps; provisional and authoritative COMPLETE baseline remain separate. Corrections do not rewrite the original review.
10. Click **Open original reviewed case**. Inspect history and compare the original/corrected score IDs. No presenter edits files or database state.
11. Select **Evidence reports**, **Models** and **Pilot metrics**. Synthetic engineering evidence is distinct from qualified predictive evidence. BLOCKED and NOT_RUN reasons remain visible. Every metric carries its denominator and label availability. Reviewed-sample findings are separated from eligible-population workload counts. No approval/promotion/rollback control exists.

The fixture service may show illustrative pilot aggregates; they are synthetic example records, not live operational reporting. Missing adjudicated labels never become a numeric yield or a qualified-use pass.

## Recovery and stopping

Stop when identity/scope changes, evidence IDs mismatch, contribution reconciliation fails or a required dependency is missing. Expired identity clears private widgets and allows same-actor/scope request recovery only. Quarantine, 401/403/409/429/500, connection failure, unavailable scores and expired exports are exercised by the automated UI suite. Real organization login, TLS ingress and real worker/container checks require their separate prerequisites.

Close the preview and stop its terminal process when finished. Restarting creates a fresh fixture store; this demo does not claim cross-process durable draft recovery. For a real API/worker journey, follow `ui_walkthrough.md` and the opt-in test instructions.
