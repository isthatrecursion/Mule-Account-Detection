"""Create missing local registry credentials without printing or replacing them."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "secrets"
root.mkdir(exist_ok=True)
for name, value in {
    "mlflow_username": "registry-admin",
    "mlflow_password": secrets.token_urlsafe(32),
    "mlflow_flask_key": secrets.token_hex(32),
}.items():
    path = root / name
    if not path.exists():
        with path.open("x", encoding="ascii") as stream:
            stream.write(value)
        path.chmod(0o600)
print("Local registry credentials present; values omitted.")
