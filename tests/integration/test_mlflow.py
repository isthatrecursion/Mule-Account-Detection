"""Opt-in authenticated local-server proof using synthetic encrypted bundles only."""

import hashlib
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from mule_detection.application.registry_service import RegistryService
from mule_detection.registry.mlflow_adapter import MlflowBackend
from tests.integration.test_registry import ENGINEER
from tests.integration.test_registry import registry as registry
from tests.unit.test_registry import final_fit as final_fit
from tests.unit.test_training import training_data as training_data

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.mlflow,
    pytest.mark.skipif(
        os.getenv("MULE_TEST_MLFLOW") != "1", reason="Explicit MLflow opt-in required"
    ),
]
ROOT = Path(__file__).resolve().parents[2]


def test_authenticated_registration_complete_artifacts_and_reconciliation(registry):
    original, candidate, approvals, resolver, loader, _, digest = registry
    backend = MlflowBackend(
        "http://127.0.0.1:5000",
        (ROOT / "secrets/mlflow_username").read_text().strip(),
        (ROOT / "secrets/mlflow_password").read_text().strip(),
    )
    with pytest.raises(HTTPError) as denied:
        urlopen("http://127.0.0.1:5000/api/2.0/mlflow/experiments/search", timeout=10)
    assert denied.value.code == 401
    version_request = Request(
        backend.base_url + "/version", headers={"Authorization": backend.authorization}
    )
    with urlopen(version_request, timeout=10) as response:
        assert response.read().decode().strip() == backend.VERSION

    class LostReply:
        lookup = backend.lookup
        set_alias = backend.set_alias

        def register(self, *args):
            backend.register(*args)
            raise TimeoutError("Synthetic lost response after actual server commit")

    service = RegistryService(original.factory, original.store, LostReply(), original.authorize)
    with pytest.raises(TimeoutError):
        service.synchronize(candidate, ENGINEER)
    service.backend = backend
    result = service.synchronize(candidate, ENGINEER)
    assert result == service.synchronize(candidate, ENGINEER)
    found = backend.lookup("synthetic_registry", str(candidate))
    assert found["bundle_digest"] == digest
    run = backend.request("GET", "/api/2.0/mlflow/runs/get", {"run_id": found["run_id"]})["run"]
    assert run["info"]["status"] == "FINISHED"
    relative = run["info"]["artifact_uri"].removeprefix("mlflow-artifacts:/").strip("/")
    for path in original.store.path(digest).iterdir():
        request = Request(
            backend.base_url
            + "/api/2.0/mlflow-artifacts/artifacts/"
            + relative
            + "/bundle/"
            + path.name,
            headers={"Authorization": backend.authorization},
        )
        with urlopen(request, timeout=20) as response:
            assert (
                hashlib.sha256(response.read()).digest()
                == hashlib.sha256(path.read_bytes()).digest()
            )
    backend.set_alias("synthetic_registry", "synthetic-proof", found["version"])
    # A second version exercises existing registered-model handling (HTTP 400).
    second = backend.register(
        "synthetic_registry", str(uuid4()), digest, original.store.path(digest), {}
    )
    assert second["version"] != found["version"]
