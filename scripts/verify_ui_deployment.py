"""Offline deployment-contract checks; never load private secrets or claim runtime approval."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def verify(root: Path) -> dict:
    compose = yaml.safe_load((root / "compose.workspace.yaml").read_text(encoding="utf-8"))
    ui, api, ingress = (compose["services"][name] for name in ("ui", "api", "ui_ingress"))
    assert ui["image"] == api["image"]  # Required external immutable input.
    assert "MULE_APP_IMAGE:?" in ui["image"]
    for service in (ui, api):
        assert service["user"] == "10001:10001" and service["read_only"]
        assert (
            service["cap_drop"] == ["ALL"] and "no-new-privileges:true" in service["security_opt"]
        )
        assert (
            "ports" not in service and service["tmpfs"] and service["mem_limit"] and service["cpus"]
        )
        assert service["healthcheck"]["test"][0] == "CMD"
    assert compose["networks"]["ui_private"]["internal"]
    assert compose["networks"]["service_private"]["internal"]
    assert "database_private" not in ui["networks"]
    assert "database_private" in api["networks"]
    assert all(secret["target"] == "/app/secrets/ui.json" for secret in ui["secrets"])
    assert len(ui["secrets"]) == 1 and "volumes" not in ui
    nginx = (root / "docker/nginx/nginx.conf").read_text(encoding="utf-8")
    template = (root / "docker/nginx/gateway-auth.conf.example").read_text(encoding="utf-8")
    for required in (
        "auth_request /_gateway_auth;",
        "proxy_set_header X-Mule-Session $verified_session;",
        "proxy_http_version 1.1;",
        "proxy_set_header Upgrade $http_upgrade;",
        "ssl_protocols TLSv1.2 TLSv1.3;",
        "include /run/secrets/ui_gateway_ingress.conf;",
        'proxy_set_header Authorization "";',
    ):
        assert required in nginx
    assert "internal;" in template and "proxy_ssl_verify on;" in template
    for name in ("X-User", "X-Email", "X-Role", "X-Scope", "X-Forwarded-User"):
        assert f'proxy_set_header {name} "";' in nginx
    dockerfile = (root / "docker/Dockerfile.app").read_text(encoding="utf-8")
    assert "COPY . " not in dockerfile and "COPY ./ " not in dockerfile
    assert "--require-hashes" in dockerfile and "USER 10001:10001" in dockerfile
    ignore = (root / ".dockerignore").read_text(encoding="utf-8")
    for excluded in (
        "**/secrets/**",
        "**/.env*",
        "**/*.csv",
        "**/*.parquet",
        "**/.streamlit/secrets.toml",
        "**/*.pem",
        "**/*.key",
    ):
        assert excluded in ignore
    assert (root / ".gitignore").read_text(encoding="utf-8").find(".streamlit/secrets.toml") >= 0
    launcher = (root / "ui/container.py").read_text(encoding="utf-8")
    for flag in (
        "--server.fileWatcherType=none",
        "--server.enableXsrfProtection=true",
        "--server.enableCORS=true",
        "--browser.gatherUsageStats=false",
    ):
        assert flag in launcher
    return {
        "static_deployment_contract": "PASSED",
        "ui_api_same_image": True,
        "direct_ui_api_host_ports": False,
        "secrets_excluded_from_source_copy": True,
        "organization_identity": "BLOCKED",
        "container_build_and_health": "NOT_RUN",
        "ingress_tls_and_bypass_runtime": "NOT_RUN",
        "image_history": "NOT_RUN",
        "egress_note": "Fixed identity endpoints require egress; enforce host/network destination policy in the deployment environment.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/frontend/part4")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if not output.is_relative_to(ROOT / "artifacts"):
        parser.error("Evidence must remain in the project artifacts directory")
    report = verify(ROOT)
    environment = dict(os.environ)
    environment.update(
        MULE_REVIEW_HOST="review.example.invalid",
        MULE_APP_IMAGE="example.invalid/mule@sha256:" + "0" * 64,
        MULE_NGINX_IMAGE="example.invalid/nginx@sha256:" + "1" * 64,
    )
    try:
        composed = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "compose.yaml",
                "-f",
                "compose.workspace.yaml",
                "--profile",
                "workspace",
                "config",
                "--no-env-resolution",
                "--quiet",
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            timeout=20,
            check=False,
        )
        report["compose_config"] = "PASSED" if composed.returncode == 0 else "FAILED"
        report["compose_inputs"] = "VALIDATION_ONLY_SYNTHETIC_IMAGE_DIGESTS_NOT_DEPLOYED"
    except (OSError, subprocess.TimeoutExpired):
        report["compose_config"] = "NOT_RUN"
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=15,
            check=False,
        )
        report["docker_engine"] = "AVAILABLE" if result.returncode == 0 else "UNAVAILABLE"
    except (OSError, subprocess.TimeoutExpired):
        report["docker_engine"] = "UNAVAILABLE"
    report["input_sha256"] = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in (
            "compose.workspace.yaml",
            "docker/Dockerfile.app",
            "docker/nginx/nginx.conf",
            ".dockerignore",
        )
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "deployment.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
