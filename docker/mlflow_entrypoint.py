"""Secrets enter environment/protected auth config, never process arguments."""

import os
from pathlib import Path
from urllib.parse import quote


def secret(name):
    value = (Path("/run/secrets") / name).read_text().strip()
    if not value:
        raise RuntimeError("Required protected secret missing")
    return value


password = quote(secret("mule_tracking_password"), safe="")
database = f"postgresql+psycopg://mule_tracking:{password}@postgres:5432/mule_tracking"
os.environ["MLFLOW_BACKEND_STORE_URI"] = database
os.environ["MLFLOW_AUTH_ADMIN_USERNAME"] = secret("mlflow_username")
os.environ["MLFLOW_AUTH_ADMIN_PASSWORD"] = secret("mlflow_password")
os.environ["MLFLOW_FLASK_SERVER_SECRET_KEY"] = secret("mlflow_flask_key")
config = Path("/tmp/mule_mlflow_auth.ini")
config.write_text(
    "[mlflow]\ndefault_permission = NO_PERMISSIONS\ndatabase_uri = "
    + database.replace("%", "%%")
    + "\n"
)
config.chmod(0o600)
os.environ["MLFLOW_AUTH_CONFIG_PATH"] = str(config)
os.execvp(
    "mlflow",
    [
        "mlflow",
        "server",
        "--app-name",
        "basic-auth",
        "--serve-artifacts",
        "--artifacts-destination",
        "/mlartifacts",
        "--host",
        "0.0.0.0",
        "--port",
        "5000",
    ],
)
