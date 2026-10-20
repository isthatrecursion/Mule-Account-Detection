"""Create new random local secret files exclusively; never print their contents."""

from pathlib import Path
from secrets import token_urlsafe

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    destination = ROOT / "secrets"
    destination.mkdir(exist_ok=True)
    for name in (
        "postgres_admin_password",
        "mule_migration_password",
        "mule_runtime_password",
        "mule_tracking_password",
        "mule_readonly_password",
        "artifact_key",
    ):
        path = destination / name
        if path.exists():
            continue
        value = (
            AESGCM.generate_key(bit_length=256).hex()
            if name == "artifact_key"
            else token_urlsafe(32)
        )
        with path.open("x", encoding="ascii", newline="\n") as stream:
            stream.write(value)
        path.chmod(0o600)
    print("Local secrets are available in the ignored secrets directory.")


if __name__ == "__main__":
    main()
