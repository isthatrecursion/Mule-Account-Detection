"""The registered dictionary fingerprint must survive either Git checkout EOL setting."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("checkout_autocrlf", ["false", "true"])
def test_registered_dictionary_bytes_survive_git_checkout(tmp_path, checkout_autocrlf):
    root = Path(__file__).resolve().parents[2]
    relative = "eda/01_schema_and_feature_dictionary.csv"
    original = (root / relative).read_bytes()
    registered = json.loads((root / "config/schema_registry/research_v1.yaml").read_text())
    assert hashlib.sha256(original).hexdigest() == registered["source_dictionary_sha256"]

    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "eda").mkdir()
    (repository / relative).write_bytes(original)
    attributes = root / ".gitattributes"
    (repository / ".gitattributes").write_bytes(
        b"DataSet__1_.csv filter=lfs diff=lfs merge=lfs -text\n"
    )

    def git(*arguments):
        return subprocess.run(
            ["git", *arguments], cwd=repository, check=True, capture_output=True
        ).stdout

    git("init", "--quiet")
    # Reproduce the original Windows add operation before testing both checkout modes.
    git("-c", "core.autocrlf=true", "add", "--", ".gitattributes", relative)
    assert git("show", ":" + relative) != original
    (repository / ".gitattributes").write_bytes(attributes.read_bytes())
    git("add", "--", ".gitattributes")
    git("-c", "core.autocrlf=true", "add", "--renormalize", "--", relative)
    assert git("show", ":" + relative) == original
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    git(
        "-c",
        f"core.autocrlf={checkout_autocrlf}",
        "checkout-index",
        "--all",
        "--prefix=" + checkout.as_posix() + "/",
    )
    assert (checkout / relative).read_bytes() == original
