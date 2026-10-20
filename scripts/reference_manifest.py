"""Create/verify immutable fingerprints of the pre-architecture evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PATHS = [
    "DataSet__1_.csv",
    "eda/holdout_split_indices.csv",
    "eda/05_leakage_and_feature_exclusions.csv",
    "scripts/pre_architecture_verification.py",
    "eda/09_pre_architecture_verification_and_remediation.md",
]


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def create_manifest(root: Path) -> dict:
    report = json.loads(
        (root / "artifacts/pre_architecture_verification/verification_report.json").read_text(
            encoding="utf-8"
        )
    )
    paths = REFERENCE_PATHS + [
        p.relative_to(root).as_posix()
        for p in sorted((root / "artifacts/pre_architecture_verification").rglob("*"))
        if p.is_file()
    ]
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "creation_context": "P01.01 evidence preservation; no benchmark rerun or source modification",
        "reference_environment": report["environment"],
        "files": [
            {
                "path": name,
                "size_bytes": (root / name).stat().st_size,
                "sha256": sha256(root / name),
            }
            for name in paths
        ],
    }


def verify_manifest(root: Path, manifest: dict) -> list[str]:
    return [
        row["path"]
        for row in manifest["files"]
        if not (root / row["path"]).is_file()
        or (root / row["path"]).stat().st_size != row["size_bytes"]
        or sha256(root / row["path"]) != row["sha256"]
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/reference_manifest.json")
    args = parser.parse_args()
    if args.verify:
        mismatches = verify_manifest(ROOT, json.loads(args.output.read_text(encoding="utf-8")))
        print(
            json.dumps({"status": "FAILED" if mismatches else "PASSED", "mismatches": mismatches})
        )
        return int(bool(mismatches))
    manifest = create_manifest(ROOT)
    if verify_manifest(ROOT, manifest):
        raise RuntimeError("Reference evidence changed during hashing")
    # Exclusive creation prevents overwriting the original preservation record.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"status": "CREATED", "files": len(manifest["files"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
