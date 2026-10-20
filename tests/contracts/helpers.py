import copy
import csv
import hashlib
import json
from pathlib import Path

from mule_detection.domain.contracts.common import parse_contract
from mule_detection.domain.contracts.tabular import TabularSchema
from mule_detection.domain.feature_policy import FeaturePolicy
from mule_detection.ingestion.research_adapter import ResearchAdapter

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads((ROOT / "tests/fixtures/contracts/minimal_valid.json").read_text())


def payload(version):
    return copy.deepcopy(FIXTURES[version])


def synthetic_research(tmp_path, *, change=None, reorder=False):
    schema = parse_contract(TabularSchema, payload("tabular_schema_v1"))
    header = [column.name for column in schema.columns]
    rows = [
        ["1", "0.1", "1", "NA", "SYN_A", "0", "0"],
        ["2", "0.2", "2", "Savings", "SYN_B", "1", "1"],
        ["3", "0.3", "3", "HOLDOUT_ONLY", "SYN_C", "1", "1"],
        ["4", "", "4", "UNKNOWN", "SYN_A", "0", "0"],
    ]
    splits = [["1", "dev", "0"], ["2", "dev", "1"], ["3", "holdout", "1"], ["4", "dev", "0"]]
    if change:
        change(header, rows, splits)
    if reorder:
        header.reverse()
        for row in rows:
            row.reverse()
    dataset = tmp_path / "synthetic.csv"
    split = tmp_path / "synthetic_split.csv"
    with dataset.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)
    with split.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["account_id", "split", "target"])
        writer.writerows(splits)
    adapter = ResearchAdapter(
        schema,
        parse_contract(FeaturePolicy, payload("feature_policy_v1")),
        hashlib.sha256(dataset.read_bytes()).hexdigest(),
        hashlib.sha256(split.read_bytes()).hexdigest(),
        3,
    )
    return adapter, dataset, split
