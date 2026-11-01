"""Verify a fresh research final fit from an existing frozen development run.

Local numerical proof only. This does not create operational approval or publish
an alias. Private model, fixture and lineage remain encrypted in ignored var/.
"""

import argparse
import json
from pathlib import Path
from uuid import UUID

from mule_detection.features.inputs import research_frame
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.ingestion.partition_guard import development_batch
from mule_detection.ingestion.research_adapter import ResearchAdapter
from mule_detection.registry.bundle_loader import BundleLoader
from mule_detection.registry.bundle_writer import BundleStore, write_bundle
from mule_detection.registry.promotion_policy import PromotionEvidence, promotion_gate
from mule_detection.training.final_fit import fit_frozen_research
from mule_detection.training.report import RunStore, environment_identity
from mule_detection.training.runner import TrainingInput

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, type=UUID)
    parser.add_argument("--with-research-data", required=True, action="store_true")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    destination = (ROOT / args.output_dir).resolve()
    if destination.exists() or not destination.is_relative_to(ROOT / "artifacts/phase7"):
        parser.error("Select a new directory under artifacts/phase7")
    destination.mkdir(parents=True)
    batch, guard = development_batch(
        ResearchAdapter.from_repository(ROOT),
        ROOT / "DataSet__1_.csv",
        ROOT / "eda/holdout_split_indices.csv",
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
    key = bytes.fromhex((ROOT / "secrets/artifact_key").read_text().strip())
    runs = RunStore(ROOT / "var/artifacts/training_verification", key)
    fitted, lineage = fit_frozen_research(
        data, FeaturePipeline.from_repository(ROOT), runs, args.run_id
    )
    store = BundleStore(ROOT / "var/artifacts/bundles", key)
    digest = write_bundle(fitted, lineage, data.X.iloc[:3], store, root=ROOT)
    BundleLoader(store, lambda *_: False).verify_candidate(digest)
    gate = promotion_gate(
        PromotionEvidence(
            data_tier="research",
            bound_bundle_digest=digest,
            unresolved_critical=("COHORT_CONFOUNDING", "UNCERTIFIED_SOURCE_AND_LABELS"),
        ),
        digest=digest,
        environment="qualified",
        target="APPROVED_FOR_SHADOW",
    )
    assert gate["status"] == "BLOCKED"
    report = {
        "result": "PASSED",
        "scope": "Local numerical packaging proof; no operational approval or deployment",
        "training_run_id": str(args.run_id),
        "bundle_digest": digest,
        "training_rows": len(data.keys),
        "excluded_holdout_rows": batch.excluded_holdout_count,
        "data_hash": data.dataset_hash,
        "split_hash": data.split_hash,
        "selection_hash": lineage["selection_hash"],
        "config_hash": lineage["config_hash"],
        "selected_family": lineage["selected_spec"]["family"],
        "training_membership_hash": lineage["training_membership_hash"],
        "saved_fixture_parity": "PASSED",
        "tolerance": {"atol": 1e-12, "rtol": 0},
        "demo_predictions_are_in_sample": True,
        "performance_recomputed_from_demo": False,
        "private_evidence_encrypted": True,
        "public_raw_rows_or_predictions": False,
        "qualified_gate": gate,
        "environment": environment_identity(ROOT),
    }
    (destination / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps({"result": "PASSED", "bundle_digest": digest, "training_rows": len(data.keys)})
    )


if __name__ == "__main__":
    main()
