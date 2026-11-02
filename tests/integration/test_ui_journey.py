"""API-backed Streamlit journey. Dataset/batch/case writes use services, never hand-edited rows."""

import csv
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import func, select

pytest.importorskip("streamlit")
import uvicorn
from streamlit.testing.v1 import AppTest

from mule_detection.api.app import create_app
from mule_detection.api.auth import Grant
from mule_detection.api.bootstrap import build_service
from mule_detection.application.ingest_service import IngestService
from mule_detection.ingestion.intake import SourceProfile
from mule_detection.persistence.models import AuditEvent, CaseNote, ReviewEvent
from mule_detection.settings import Settings
from tests.api_helpers import SigningAuthority
from tests.integration.test_ingestion import declaration
from tests.integration.test_scoring_publication import scoring as scoring
from tests.integration.test_training import training as training
from tests.ui_helpers import SignedProvider, config
from ui.api_client import ApiClient, ApiFailure
from ui.state import Workspace

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.postgres


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception


def test_real_api_worker_and_streamlit_analyst_journey(
    scoring, training, db, runtime_engine, tmp_path, monkeypatch
):
    import mule_detection.application.ingest_bootstrap as ingest_bootstrap
    import mule_detection.application.registry_bootstrap as registry_bootstrap

    source, request, *_ = scoring
    trainer, _, training_config = training
    profile = SourceProfile(
        source_id="synthetic-research",
        schema_id="research_v1",
        data_tier="research",
        policy_version=trainer.adapter.feature_policy.policy_version,
        access_scope="research",
        identity_columns=("Unnamed: 0",),
        columns=trainer.adapter.schema.columns,
        missing_tokens=trainer.adapter.schema.missing_tokens,
        expected_dataset_hash=trainer.adapter.trusted_dataset_sha256,
    )
    intake = IngestService(
        trainer.factory,
        trainer.raw_store,
        {profile.source_id: profile},
        trainer.adapter.feature_policy,
        authorize=lambda *_: True,
        research_adapter=trainer.adapter,
        trusted_split=trainer.split_path,
    )
    (tmp_path / "secrets").mkdir(exist_ok=True)
    (tmp_path / "secrets/artifact_key").write_text((b"p" * 32).hex())
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config/review_policy.yaml").write_bytes(
        (ROOT / "config/review_policy.yaml").read_bytes()
    )
    monkeypatch.setattr(ingest_bootstrap, "build_ingest", lambda _: intake)
    monkeypatch.setattr(
        registry_bootstrap,
        "build_registry",
        lambda _: (SimpleNamespace(training=trainer), source.resolver, source.loader),
    )
    settings = Settings(
        environment="test",
        root_path=tmp_path,
        database_url=runtime_engine.url.render_as_string(hide_password=False),
        mlflow_uri="http://localhost:5000",
        runtime_policy_path="config/test.yaml",
    )
    authority = SigningAuthority()
    authority.config.groups["research-workspace"] = Grant(
        roles=frozenset({"reviewer", "operator"}), scopes=frozenset({"research"})
    )
    service = build_service(settings, authority.config)
    app = create_app(settings, lambda _: (authority.config, service))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    ui_config = config(environment="test").model_copy(
        update={"api_base_url": f"http://127.0.0.1:{port}"}
    )
    provider = SignedProvider(authority, "reviewer", groups=["research-workspace"])
    workspace = Workspace(ApiClient(ui_config, provider))
    visual = None
    try:
        workspace.authenticate()
        content = (tmp_path / "synthetic.csv").read_bytes()
        workspace.begin(
            "Batch intake",
            "/v1/batches",
            None,
            content=content,
            manifest=json.dumps(
                declaration(intake, content, provenance_limitations=["synthetic provenance"])
            ),
            filename="synthetic.csv",
        )
        received = workspace.submit()
        service.run_one(UUID(received["job_id"]))
        accepted = workspace.poll(received["job_id"], force=True)
        assert accepted["state"] == "SUCCEEDED" and accepted["result"]["outcome"] == "ACCEPTED", (
            accepted["result"]
        )
        batch = accepted["result"]["batch_id"]
        workspace.begin(
            "Scoring",
            "/v1/scoring-runs",
            {"batch_id": batch, "bundle_digest": request.bundle_digest},
        )
        scored = workspace.submit()
        service.run_one(UUID(scored["job_id"]))
        completed = workspace.poll(scored["job_id"], force=True)
        assert completed["state"] == "SUCCEEDED", completed
        queue = completed["result"]["queue_id"]
        workspace.choose_queue(queue)
        monkeypatch.setattr("ui.runtime.create_workspace", lambda: workspace)
        ui = AppTest.from_file(str(ROOT / "ui/app.py"), default_timeout=30).run()
        assert not ui.exception
        click(ui, "Open case")
        assert not ui.error, [error.value for error in ui.error]
        assert any("Research demonstration" in item.value for item in [*ui.warning, *ui.caption])
        assert any("UNVERIFIED" in str(frame.value) for frame in ui.table)
        case = workspace.selected_case
        click(ui, "Assign case")
        click(ui, "Start review")
        ui.text_area[0].set_value("Synthetic review Ω — independent evidence required")
        click(ui, "Save review")
        persisted = workspace.last_result["event_id"]
        # The actual API enforces permissions even when navigation is bypassed.
        denied = Workspace(ApiClient(ui_config, SignedProvider(authority, "operator")))
        denied.authenticate()
        with pytest.raises(ApiFailure) as error:
            denied.api.case(UUID(case))
        assert error.value.status == 403
        next(b for b in ui.sidebar.button if b.label == "History").click().run()
        assert any(persisted in text.value for text in ui.text)
        workspace.begin(
            "Export", "/v1/exports", {"queue_version": queue, "reason": "Synthetic walkthrough"}
        )
        exported = workspace.submit()
        service.run_one(UUID(exported["job_id"]))
        data = workspace.api.request(
            "GET", f"/v1/exports/{exported['job_id']}/download", download=True
        )
        records = list(csv.DictReader(io.StringIO(data.decode())))
        assert records and "note" not in records[0] and records[0]["queue_version"] == queue
        with db() as session:
            assert session.scalar(select(func.count()).select_from(ReviewEvent)) == 3
            assert session.scalar(select(func.count()).select_from(CaseNote)) == 1
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "export:download")
                )
                == 1
            )
        # A browser can reconnect to an acknowledged job without session-state data.
        refreshed = Workspace(ApiClient(ui_config, provider))
        refreshed.authenticate()
        assert refreshed.api.job(UUID(received["job_id"]))["state"] == "SUCCEEDED"
        invalid = b"unexpected\nvalue\n"
        workspace.begin(
            "Invalid batch",
            "/v1/batches",
            None,
            content=invalid,
            manifest=json.dumps(
                declaration(intake, invalid, provenance_limitations=["synthetic provenance"])
            ),
            filename="invalid.csv",
        )
        quarantined_job = workspace.submit()
        service.run_one(UUID(quarantined_job["job_id"]))
        quarantined = workspace.poll(quarantined_job["job_id"], force=True)
        assert quarantined["result"]["outcome"] == "QUARANTINED"
        next(b for b in ui.sidebar.button if b.label == "Operations").click().run()
        assert not ui.exception
        assert any("Validation finding" in warning.value for warning in ui.warning)
        evidence = {
            "result": "PASSED",
            "input_source": "SYNTHETIC_ONLY",
            "upload_job_id": received["job_id"],
            "batch_id": batch,
            "scoring_job_id": scored["job_id"],
            "queue_version": queue,
            "case_id": case,
            "review_event_id": persisted,
            "export_job_id": exported["job_id"],
            "export_rows": len(records),
            "hand_edited_database_rows": False,
            "ui_exception_count": len(ui.exception),
            "quarantined_job_id": quarantined_job["job_id"],
        }
        destination = os.getenv("MULE_TEST_UI_EVIDENCE_DIR")
        if destination:
            out = Path(destination).resolve()
            assert out.is_relative_to(ROOT / "artifacts/phase10")
            out.mkdir(parents=True, exist_ok=True)
            (out / "journey.json").write_text(json.dumps(evidence, indent=2) + "\n")
            if os.getenv("MULE_TEST_UI_VISUAL") == "1":
                private = tmp_path / "ui_private.json"
                credential = provider.credential()
                private.write_text(
                    json.dumps(
                        {
                            "api_base_url": ui_config.api_base_url,
                            "actor_id": credential.actor_id,
                            "expires_at": credential.expires_at,
                            "token": credential.token.get_secret_value(),
                            "case_id": case,
                            "queue_version": queue,
                        }
                    )
                )
                private.chmod(0o600)
                environment = dict(os.environ)
                environment.update(
                    MULE_TEST_UI_STATE_FILE=str(private),
                    STREAMLIT_BROWSER_GATHER_USAGE_STATS="false",
                )
                log = (out / "streamlit.txt").open("w", encoding="utf-8")
                visual = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "streamlit",
                        "run",
                        str(ROOT / "tests/fixtures/ui/visual_entry.py"),
                        "--server.address=127.0.0.1",
                        "--server.port=8510",
                        "--server.headless=true",
                        "--client.showSidebarNavigation=false",
                    ],
                    cwd=ROOT,
                    env=environment,
                    stdout=log,
                    stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                (out / "visual_ready.json").write_text(
                    json.dumps(
                        {"url": "http://127.0.0.1:8510", "status": "SYNTHETIC_REHEARSAL_ONLY"}
                    )
                )
                deadline = time.monotonic() + 240
                while time.monotonic() < deadline and not (out / "visual_done").exists():
                    time.sleep(0.2)
                visual.terminate()
                visual.wait(timeout=15)
                log.close()
                private.unlink(missing_ok=True)
    finally:
        if visual and visual.poll() is None:
            visual.terminate()
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
