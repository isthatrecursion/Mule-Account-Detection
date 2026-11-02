"""Local numerical verification; operational train must use the accepted-batch CLI.

Default: synthetic inputs, no secrets. --with-research-data: approved local machine
only; hash-bound development data and encrypted evidence under ignored var/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from mule_detection.features.inputs import research_frame
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.ingestion.partition_guard import PartitionGuard, development_batch
from mule_detection.ingestion.research_adapter import ResearchAdapter
from mule_detection.settings import read_yaml
from mule_detection.training.evaluation_policy import TrainingConfig
from mule_detection.training.report import RunStore, environment_identity
from mule_detection.training.runner import TrainingInput, run_experiment

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/model_candidates.yaml"))
    parser.add_argument("--with-research-data", action="store_true")
    args = parser.parse_args()
    destination = (ROOT / args.output_dir).resolve()
    if destination.exists() or not destination.is_relative_to(ROOT / "artifacts/phase6"):
        parser.error("Choose a new directory under artifacts/phase6")
    destination.mkdir(parents=True)
    config = TrainingConfig.model_validate(read_yaml(ROOT / args.config))
    run_id = uuid4()
    if args.with_research_data:
        adapter = ResearchAdapter.from_repository(ROOT)
        batch, guard = development_batch(
            adapter, ROOT / "DataSet__1_.csv", ROOT / "eda/holdout_split_indices.csv"
        )
        data = TrainingInput(
            research_frame(batch, guard),
            batch.labels,
            batch.record_keys,
            guard,
            batch.dataset_sha256,
            batch.split_sha256,
            "research",
            tuple(row.extraction_month or "UNKNOWN" for row in batch.restricted_lineage),
            "LOCAL_VERIFIED_REFERENCE_NOT_OPERATIONAL_BATCH",
            {},
        )
        key = bytes.fromhex((ROOT / "secrets/artifact_key").read_text(encoding="ascii").strip())
        private = ROOT / "var/artifacts/training_verification"
        excluded_holdout = batch.excluded_holdout_count
    else:
        rng = np.random.default_rng(42)
        X = pd.DataFrame(
            {
                "number": rng.normal(size=160),
                "optional": rng.normal(size=160),
                "category": ["a_b", "c_d"] * 80,
            }
        )
        X.loc[::4, "optional"] = np.nan
        keys = tuple(f"synthetic-{i}" for i in range(len(X)))
        y = (X["number"].to_numpy() > 0).astype(int)
        digest = hashlib.sha256(X.to_csv(index=False).encode()).hexdigest()
        guard = PartitionGuard(digest, "b" * 64, frozenset(keys))
        data = TrainingInput(
            X,
            y,
            keys,
            guard,
            digest,
            "b" * 64,
            "synthetic",
            tuple("source-a" if i % 2 else "source-b" for i in range(len(X))),
            "SYNTHETIC_FIXTURE",
            {},
        )
        key = os.urandom(32)
        private = ROOT / "scratch" / f"training-{run_id}"
        excluded_holdout = None
    identity = environment_identity(ROOT)
    result = run_experiment(
        data,
        FeaturePipeline.from_repository(ROOT),
        config,
        RunStore(private, key),
        run_id,
        actor_id="local-verification",
        environment=identity,
    )
    report = {
        "result": "PASSED",
        "scope": "Local numerical candidate verification, not operational intake or independent acceptance",
        "summary": result,
        "config_hash": config.fingerprint,
        "source": {
            "data_tier": data.data_tier,
            "dataset_hash": data.dataset_hash,
            "split_hash": data.split_hash,
            "excluded_holdout_rows": excluded_holdout,
        },
        "environment": identity,
        "private_evidence_encrypted": True,
        "raw_rows_or_predictions_in_public_evidence": False,
    }
    (destination / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"result": "PASSED", "report": str(destination / "report.json"), "run_id": str(run_id)}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
