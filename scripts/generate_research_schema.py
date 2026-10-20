"""Generate logical roles/types from EDA representation metadata, never its inferred meanings."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = ROOT / "eda/01_schema_and_feature_dictionary.csv"
    with source.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    blocked = {"F3912", "F3287", "F3290", "F3611", "F3614"}
    columns = []
    for row in rows:
        name = row["column_name"]
        role = (
            "label"
            if name == "F3924"
            else "lineage"
            if name in ("Unnamed: 0", "F2230")
            else "forbidden"
            if name in blocked
            else "predictor"
        )
        columns.append(
            {
                "name": name,
                "logical_type": {"float64": "number", "int64": "integer", "object": "categorical"}[
                    row["dtype"]
                ],
                "role": role,
                "required": True,
                "missing": "forbidden" if name in ("Unnamed: 0", "F3924") else "imputable",
            }
        )
    value = {
        "contract_version": "tabular_schema_v1",
        "schema_id": "research_v1",
        "source_dictionary_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "raw_header_aliases": {"": "Unnamed: 0"},
        "reorder": "canonicalize_to_registry_order",
        # Frozen pandas 2.2.3 CSV null lexicon used by the preserved reference reader.
        # The physical file serializes missing cells as NA as well as empty strings.
        "missing_tokens": [
            "",
            "#N/A",
            "#N/A N/A",
            "#NA",
            "-1.#IND",
            "-1.#QNAN",
            "-NaN",
            "-nan",
            "1.#IND",
            "1.#QNAN",
            "<NA>",
            "N/A",
            "NA",
            "NULL",
            "NaN",
            "None",
            "n/a",
            "nan",
            "null",
        ],
        "columns": columns,
    }
    # JSON is also valid YAML; compact rows keep the full 3925-column registry reviewable.
    text = json.dumps(value, indent=2) + "\n"
    target = ROOT / "config/schema_registry/research_v1.yaml"
    if args.check:
        return int(not target.is_file() or target.read_text(encoding="utf-8") != text)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"Generated {len(columns)} column rules without importing inferred business prose")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
