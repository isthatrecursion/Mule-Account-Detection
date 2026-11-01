# Supply a reviewed python:3.12-slim-bookworm@sha256:... base; no floating release base.
ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE} AS dependencies
RUN python -c "import sys; assert sys.version_info[:2] == (3, 12)"
WORKDIR /build
COPY requirements-linux.lock requirements-api-linux.lock requirements-ui-linux.lock ./
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements-api-linux.lock -r requirements-ui-linux.lock

FROM ${PYTHON_IMAGE} AS application
ENV PATH="/opt/venv/bin:$PATH" PYTHONPATH="/app/src:/app" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/* && groupadd --gid 10001 mule && useradd --uid 10001 --gid 10001 --no-create-home mule
COPY --from=dependencies /opt/venv /opt/venv
WORKDIR /app
COPY --chown=10001:10001 src/ /app/src/
COPY --chown=10001:10001 ui/ /app/ui/
COPY --chown=10001:10001 config/ /app/config/
COPY --chown=10001:10001 .streamlit/config.toml /app/.streamlit/config.toml
RUN mkdir -p /app/secrets /app/var/artifacts && chown -R 10001:10001 /app/secrets /app/var
USER 10001:10001
EXPOSE 8501 8000
CMD ["python", "-m", "ui.container"]
