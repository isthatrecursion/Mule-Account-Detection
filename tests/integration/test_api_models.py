"""HTTP admission and production worker composition over synthetic accepted model inputs."""

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("jwt")
from fastapi.testclient import TestClient

from mule_detection.api.app import create_app
from mule_detection.api.bootstrap import build_service
from mule_detection.application.unit_of_work import unit_of_work
from mule_detection.persistence.models import BatchAccess
from mule_detection.settings import Settings
from tests.api_helpers import SigningAuthority
from tests.integration.test_api import post
from tests.integration.test_ingestion import intake as intake
from tests.integration.test_scoring_publication import scoring as scoring
from tests.integration.test_training import training as training

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[2]


def test_http_train_and_score_dispatch_to_real_services(
    scoring, training, intake, db, runtime_engine, tmp_path, monkeypatch
):
    import mule_detection.application.ingest_bootstrap as ingest_bootstrap
    import mule_detection.application.registry_bootstrap as registry_bootstrap
    import mule_detection.application.training_bootstrap as training_bootstrap

    source, request, *_ = scoring
    trainer, batch_id, config = training
    (tmp_path / "secrets").mkdir(exist_ok=True)
    (tmp_path / "secrets/artifact_key").write_text((b"p" * 32).hex())
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config/review_policy.yaml").write_bytes(
        (ROOT / "config/review_policy.yaml").read_bytes()
    )
    (tmp_path / "config/model_candidates.yaml").write_text(
        json.dumps(config.model_dump(mode="json"))
    )
    monkeypatch.setattr(ingest_bootstrap, "build_ingest", lambda _: intake)
    monkeypatch.setattr(training_bootstrap, "build_training", lambda _: trainer)
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
    service = build_service(settings, authority.config)
    with unit_of_work(db) as session:
        session.add(BatchAccess(batch_id=batch_id, access_scope="synthetic-team"))
    with TestClient(create_app(settings, lambda _: (authority.config, service))) as http:
        operator, engineer = authority.headers("operator"), authority.headers("engineer")
        payload = {"batch_id": str(batch_id), "bundle_digest": request.bundle_digest}
        score = post(http, "/v1/scoring-runs", operator, payload)
        assert score.status_code == 202
        assert (
            http.get(f"/v1/jobs/{score.json()['job_id']}", headers=operator).json()["state"]
            == "PENDING"
        )
        train = post(http, "/v1/training-runs", engineer, {"batch_id": str(batch_id)})
        assert train.status_code == 202
        assert (
            post(http, "/v1/training-runs", operator, {"batch_id": str(batch_id)}).status_code
            == 403
        )
        assert post(http, "/v1/scoring-runs", engineer, payload).status_code == 403
        service.run_one(UUID(score.json()["job_id"]))
        result = http.get(f"/v1/jobs/{score.json()['job_id']}", headers=operator).json()
        assert result["state"] == "SUCCEEDED", result
        queue = result["result"]["queue_id"]
        page = http.get(f"/v1/queues/{queue}/cases", headers=authority.headers()).json()
        assert page["total"] > 0
        assert page["items"][0]["freshness"] == "STALE"
        evidence = http.get(
            f"/v1/cases/{page['items'][0]['case_id']}/evidence", headers=authority.headers()
        )
        assert evidence.status_code == 200, evidence.text
        assert (
            evidence.json()["facts"]["interpretation"]
            == "MODEL_ASSOCIATION_ONLY_NOT_CAUSAL_OR_CERTIFIED_BEHAVIOR"
        )
        service.run_one(UUID(train.json()["job_id"]))
        trained = http.get(f"/v1/jobs/{train.json()['job_id']}", headers=engineer).json()
        assert trained["state"] == "SUCCEEDED", trained
        assert trained["result"]["state"] == "CANDIDATE_ONLY"
