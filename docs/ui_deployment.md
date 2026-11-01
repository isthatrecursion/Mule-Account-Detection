# Frontend deployment preparation — FE-15

Shared deployment remains BLOCKED pending organization OIDC/gateway settings, TLS certificates, a reviewed application image and backend source/model prerequisites. The opt-in overlay preserves the existing PostgreSQL/registry workflows; it does not deploy automatically.

## Build one image, use one digest

`docker/Dockerfile.app` accepts a reviewed `python:3.12-...-slim-bookworm@sha256:...` base. The API/UI runtime uses the existing hash-locked Linux dependencies and Python 3.12. It copies only source, public configuration and the Streamlit theme, runs as UID/GID 10001 and has no credentials in build arguments or image layers.

`.github/workflows/ui-release-candidate.yml` is manually triggered, builds the application once and exports that exact image archive plus its SHA-256 and image ID. It neither publishes nor deploys. The organization's release process must load/publish that same artifact, record its registry manifest digest, and use that same `repository@sha256:...` reference for both UI and API across environments. Archive checksum, image/config ID and registry manifest digest are different identifiers; do not substitute one for another.

```powershell
# Supply reviewed real digests; these placeholders are intentionally incomplete.
$env:MULE_APP_IMAGE = 'REGISTRY/APP@sha256:REVIEWED_APPLICATION_DIGEST'
$env:MULE_NGINX_IMAGE = 'REGISTRY/NGINX@sha256:REVIEWED_NGINX_DIGEST'
$env:MULE_REVIEW_HOST = 'APPROVED_CERTIFICATE_DNS_HOSTNAME'
docker compose -f compose.yaml -f compose.workspace.yaml --profile workspace config --no-env-resolution --quiet
```

Do not run `up` until the prerequisites below are satisfied. FE-15's local static check substitutes syntactically valid synthetic digests only for parsing; it never pulls or deploys them.

## Runtime boundaries

The UI/API use the same image, non-root users, read-only root filesystems, dropped capabilities, no-new-privileges, memory/CPU/PID limits and bounded tmpfs scratch. Neither publishes a host port. The UI has no database-network membership or raw/model/artifact volume. Only its protected `ui.json` is mounted. API artifacts use a separate named volume and its own secret mounts.

The ingress listens on unprivileged TLS port 8443. Host publishing defaults to loopback; public exposure requires the deployment owner's explicit binding/network policy. UI and API communicate through a private service network. PostgreSQL is on a separate database network. Identity egress is explicit; host/network firewall policy must constrain it to approved trust endpoints. Docker network membership alone does not enforce an outbound hostname allowlist.

The TLS ingress has a fixed `/v1/` route to the internal API, preserving its API-audience bearer token for independent API verification. Configure `api_base_url` in `ui.json` to the approved HTTPS certificate hostname and port; the ingress has that hostname as a private network alias. Certificate verification stays enabled. UI/browser routes use a gateway auth subrequest and replace client-supplied X-Mule-Session with the verified gateway result, strip spoofable identity/role/scope/Authorization headers, and forward WebSocket upgrades. The gateway assertion/binding and the API token are still independently verified by their existing providers.

These settings follow the documented [Compose service controls](https://docs.docker.com/reference/compose-file/services/), [NGINX auth subrequests](https://nginx.org/en/docs/http/ngx_http_auth_request_module.html) and [WebSocket proxy headers](https://nginx.org/en/docs/http/websocket.html). Their runtime behavior must be tested in the target environment.

## Protected inputs

- `secrets/ui.json`: actual API/gateway trust configuration, login URL and service credential. No fixture or browser-selected endpoints. Native `st.user`/ID tokens are not API credentials.
- OIDC client/cookie signing secrets remain in the organization's gateway/BFF secret store under the existing identity design; they are not copied into this UI image or invented as Streamlit login defaults.
- `secrets/oidc.json`, runtime database URL, tracking URI and artifact key for the API, following existing backend setup. Database files mount under the `MULE_DATABASE_URL`/`MULE_MLFLOW_URI` secret names expected by Settings.
- TLS certificate/key and `secrets/ui_gateway_ingress.conf`, adapted from the example using the approved fixed HTTPS gateway endpoint and trusted CA. The include must define internal `/_gateway_auth` and return a verified per-workspace child handle. Missing files/configuration prevent startup.
- Existing backend source registrations, migrations, model bundles, tracking credentials and worker orchestration. They are not supplied by a frontend image or by this overlay.

File-based Compose secret ownership/modes depend on the host implementation; verify that only the assigned non-root service UID can read the mounted files. Compose file mounts do not guarantee that requested uid/gid overrides are honored. Do not solve permissions by copying secrets into images or making broad private directories readable.

Streamlit's container entry validates protected configuration before binding. It disables the watcher/telemetry, retains XSRF/CORS checks and hides raw error details. It deliberately differs from the development launcher, which binds only to loopback. `.streamlit/secrets.toml`, environment files, private data, CSV/Parquet and credential/key files are excluded from the Docker build context and Git where applicable.

## Checks and honest status

Run `python scripts/verify_ui_deployment.py` for static boundaries, safe source-copy rules, Compose parsing and engine availability. Static checks do not prove image history, live TLS/header stripping, gateway session revocation or bypass denial at an actual ingress.

At acceptance, verify: direct UI/API host ports are unreachable; forged email/user/role/session headers cannot impersonate; missing/expired/wrong-audience credentials fail; WebSockets work through TLS; the same reviewed image digest is used; private secrets/data are absent from image history/context; and containers are healthy as non-root with a read-only filesystem. Existing unit tests prove provider/runtime rejection but are not labeled as live ingress tests.

The local Docker CLI was available but its Linux engine remained unreachable after a start attempt. Container build/health, image-history inspection and live TLS ingress therefore remain NOT_RUN. Organization identity integration remains BLOCKED until the actual trust/gateway settings are supplied. No qualified/pilot approval is granted by a passing synthetic suite.
