"""Generate JSON schemas from server models; --check rejects accidental contract drift."""

import argparse
import hashlib
import json
from pathlib import Path

from mule_detection.domain.contracts.registry import CONTRACTS

ROOT = Path(__file__).resolve().parents[1]


def generated_schemas() -> dict[str, str]:
    return {
        f"{version}.schema.json": json.dumps(model.model_json_schema(), sort_keys=True, indent=2)
        + "\n"
        for version, model in CONTRACTS.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--register-new-versions", metavar="DECISION_REFERENCE")
    args = parser.parse_args()
    directory = ROOT / "contracts"
    files = generated_schemas()
    manifest_path = directory / "version_manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {"versions": {}}
    )
    registered = manifest["versions"]
    changed = [
        name
        for name, entry in registered.items()
        if name not in files
        or hashlib.sha256(files[name].encode()).hexdigest() != entry["schema_sha256"]
    ]
    new = set(files) - set(registered)
    if changed or (new and not args.register_new_versions):
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "changed_or_retired_versions": changed,
                    "version_decision_required": sorted(new),
                }
            )
        )
        return 1
    if args.check and args.register_new_versions:
        parser.error("--check cannot register versions")
    if args.check:
        invalid = [
            name
            for name, expected in files.items()
            if not (directory / name).is_file()
            or (directory / name).read_text(encoding="utf-8") != expected
        ]
        invalid.extend(
            path.name for path in directory.glob("*.schema.json") if path.name not in files
        )
        print(
            json.dumps(
                {
                    "status": "FAILED" if invalid else "PASSED",
                    "schema_count": len(files),
                    "mismatches": invalid,
                }
            )
        )
        return int(bool(invalid))
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")
    if args.register_new_versions:
        for name in sorted(new):
            registered[name] = {
                "schema_sha256": hashlib.sha256(files[name].encode()).hexdigest(),
                "decision_reference": args.register_new_versions,
                "reviewer": "PENDING_OWNER_REVIEW",
            }
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
    print(f"Generated {len(files)} model-owned schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
