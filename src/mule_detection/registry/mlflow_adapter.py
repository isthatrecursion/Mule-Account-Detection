"""Pinned MLflow REST surface; no client dependency enters the training lock."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from mule_detection.domain.errors import DomainError, ErrorCode


class RegistryBackend(Protocol):
    def lookup(self, name: str, registration_id: str) -> dict[str, str] | None: ...
    def register(
        self,
        name: str,
        registration_id: str,
        digest: str,
        directory: Path,
        metrics: dict[str, float],
        parameters: dict[str, str] | None = None,
    ) -> dict[str, str]: ...
    def set_alias(self, name: str, alias: str, version: str) -> None: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: Any, msg: Any, headers: Any, newurl: Any
    ) -> None:
        return None


class MlflowBackend:
    VERSION = "3.17.2"

    def __init__(self, base_url: str, username: str, password: str) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not username
            or not password
        ):
            raise DomainError(ErrorCode.CONFIGURATION_INVALID)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "mlflow"}
        ):
            raise DomainError(ErrorCode.CONFIGURATION_INVALID)
        self.base_url = base_url.rstrip("/")
        self.authorization = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
        self.opener = build_opener(NoRedirect())

    def request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        *,
        raw: bytes | None = None,
        missing: bool = False,
        exists: bool = False,
    ) -> dict[str, Any]:
        data = (
            raw
            if raw is not None
            else json.dumps(payload).encode()
            if payload is not None and method != "GET"
            else None
        )
        if method == "GET" and payload:
            path += "?" + urlencode(payload)
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": self.authorization,
                "Content-Type": "application/octet-stream"
                if raw is not None
                else "application/json",
            },
        )
        try:
            with self.opener.open(request, timeout=20) as response:
                body = response.read(8 * 1024 * 1024)
                return json.loads(body) if body else {}
        except HTTPError as error:
            try:
                code = json.loads(error.read(65536)).get("error_code")
            except (ValueError, AttributeError):
                code = None
            if (missing and error.code == 404) or (
                exists and error.code in {400, 409} and code == "RESOURCE_ALREADY_EXISTS"
            ):
                return {}
            # Server messages may contain URIs/credentials; never propagate them.
            raise DomainError(ErrorCode.LINEAGE_INVALID) from None
        except (URLError, OSError, ValueError):
            raise DomainError(ErrorCode.LINEAGE_INVALID) from None

    @staticmethod
    def _name(name: str) -> None:
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name) is None:
            raise DomainError(ErrorCode.INVALID_ARGUMENTS)

    def lookup(self, name: str, registration_id: str) -> dict[str, str] | None:
        self._name(name)
        versions = []
        token = None
        for _ in range(100):
            query = {"filter": f"name = '{name}'", "max_results": "100"}
            if token:
                query["page_token"] = token
            response = self.request("GET", "/api/2.0/mlflow/model-versions/search", query)
            for version in response.get("model_versions", []):
                tags = {tag["key"]: tag["value"] for tag in version.get("tags", [])}
                if tags.get("registration_id") == registration_id:
                    versions.append(
                        {
                            "version": str(version["version"]),
                            "run_id": version["run_id"],
                            "bundle_digest": tags["bundle_digest"],
                        }
                    )
            token = response.get("next_page_token")
            if not token:
                break
        else:
            raise DomainError(ErrorCode.LINEAGE_INVALID)
        if len(versions) > 1:
            raise DomainError(ErrorCode.IDENTITY_CONFLICT)
        return versions[0] if versions else None

    def register(
        self,
        name: str,
        registration_id: str,
        digest: str,
        directory: Path,
        metrics: dict[str, float],
        parameters: dict[str, str] | None = None,
    ) -> dict[str, str]:
        self._name(name)
        experiment = self.request(
            "GET",
            "/api/2.0/mlflow/experiments/get-by-name",
            {"experiment_name": "mule_candidates"},
            missing=True,
        )
        if not experiment:
            self.request(
                "POST",
                "/api/2.0/mlflow/experiments/create",
                {"name": "mule_candidates"},
                exists=True,
            )
            experiment = self.request(
                "GET",
                "/api/2.0/mlflow/experiments/get-by-name",
                {"experiment_name": "mule_candidates"},
            )
        experiment_id = experiment["experiment"]["experiment_id"]
        tags = [
            {"key": "registration_id", "value": registration_id},
            {"key": "bundle_digest", "value": digest},
            {"key": "data_tier", "value": "research"},
        ]
        run = self.request(
            "POST", "/api/2.0/mlflow/runs/create", {"experiment_id": experiment_id, "tags": tags}
        )["run"]["info"]
        run_id = run["run_id"]
        self.request(
            "POST",
            "/api/2.0/mlflow/runs/log-batch",
            {
                "run_id": run_id,
                "params": [
                    {"key": key, "value": value}
                    for key, value in {**(parameters or {}), "bundle_digest": digest}.items()
                ],
                "metrics": [
                    {"key": key, "value": value, "timestamp": run["start_time"], "step": 0}
                    for key, value in metrics.items()
                ],
            },
        )
        artifact = run["artifact_uri"]
        if not artifact.startswith("mlflow-artifacts:/"):
            raise DomainError(ErrorCode.CONFIGURATION_INVALID)
        relative = artifact.removeprefix("mlflow-artifacts:/").strip("/")
        for path in directory.iterdir():
            if path.is_file() and (path.name == "bundle.json" or path.name.endswith(".enc")):
                self.request(
                    "PUT",
                    "/api/2.0/mlflow-artifacts/artifacts/"
                    + quote(relative + "/bundle/" + path.name, safe="/"),
                    raw=path.read_bytes(),
                )
        self.request(
            "POST", "/api/2.0/mlflow/registered-models/create", {"name": name}, exists=True
        )
        version = self.request(
            "POST",
            "/api/2.0/mlflow/model-versions/create",
            {
                "name": name,
                "source": artifact.rstrip("/") + "/bundle",
                "run_id": run_id,
                "tags": tags,
            },
        )["model_version"]
        self.request(
            "POST", "/api/2.0/mlflow/runs/update", {"run_id": run_id, "status": "FINISHED"}
        )
        return {"version": str(version["version"]), "run_id": run_id, "bundle_digest": digest}

    def set_alias(self, name: str, alias: str, version: str) -> None:
        self._name(name)
        self._name(alias)
        self.request(
            "POST",
            "/api/2.0/mlflow/registered-models/alias",
            {"name": name, "alias": alias, "version": version},
        )
