"""Fit once from frozen, authenticated research selection; never reuse a fold model."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import numpy as np

from mule_detection.domain.contracts.common import canonical_hash
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.features.signature import frame_fingerprint
from mule_detection.training.evaluation_policy import TrainingConfig
from mule_detection.training.model_factory import FittedCandidate, fit_candidate
from mule_detection.training.report import RunStore
from mule_detection.training.runner import TrainingInput
from mule_detection.training.search import FrozenSelection


def fit_frozen_research(
    data: TrainingInput,
    prototype: FeaturePipeline,
    store: RunStore,
    run_id: UUID,
) -> tuple[FittedCandidate, dict[str, Any]]:
    manifest = store.manifest(run_id)
    report = store.json(run_id, "report.json", manifest)
    config = TrainingConfig.model_validate(store.json(run_id, "config.json", manifest))
    frozen = FrozenSelection.model_validate(report["frozen_selection"])
    data.guard.assert_development(data.keys, data.dataset_hash, data.split_hash)
    if (
        data.data_tier not in {"research", "synthetic"}
        or config.mode != "research"
        or frozen.config_hash != config.fingerprint
        or frozen.data_hash != data.dataset_hash
        or frozen.feature_policy_hash != prototype.policy.fingerprint
        or manifest["split_hash"] != data.split_hash
    ):
        raise DomainError(ErrorCode.LINEAGE_INVALID)
    # Reconstruct the original request using its recorded environment, not today's
    # code revision. This catches changed predictor values even under a forged hash.
    expected = canonical_hash(
        {
            "actor": manifest["actor_id"],
            "config": config.fingerprint,
            "dataset": data.dataset_hash,
            "split": data.split_hash,
            "validation": data.validation_reference,
            "policy": prototype.policy.fingerprint,
            "predictors": frame_fingerprint(data.X),
            "labels": canonical_hash({"labels": np.asarray(data.target).tolist()}),
            "runtime_and_code": canonical_hash(store.json(run_id, "environment.json", manifest)),
            "semantic_rules": canonical_hash(
                {
                    "version": prototype.semantic_version,
                    "rules": prototype.semantic_rules.model_dump(mode="json")
                    if prototype.semantic_rules
                    else None,
                }
            ),
        }
    )
    if expected != manifest["request_hash"]:
        raise DomainError(ErrorCode.LINEAGE_INVALID)
    members = [
        key
        for fold in store.json(run_id, "splits.json", manifest)
        for key in fold["validation_keys"]
    ]
    if len(members) != len(data.keys) or set(members) != set(data.keys):
        raise DomainError(ErrorCode.SPLIT_MISMATCH)
    fitted = fit_candidate(
        prototype,
        frozen.selected_spec,
        data.X,
        data.target,
        seed=config.seed,
        threads=config.threads,
    )
    return fitted, {
        "training_run_id": str(run_id),
        "trainer_id": manifest["actor_id"],
        "selection_hash": frozen.fingerprint,
        "config_hash": config.fingerprint,
        "data_tier": data.data_tier,
        "dataset_hash": data.dataset_hash,
        "split_hash": data.split_hash,
        "training_rows": len(data.keys),
        "training_membership_hash": canonical_hash({"keys": data.keys}),
        "fitted_training_fingerprint": fitted.features.training_fingerprint_,
        "selected_spec": frozen.selected_spec.model_dump(mode="json"),
        "diagnostic_metrics": report["candidates"][report["selected_family"]][
            "pooled_oof_diagnostic"
        ],
        "output_scale": "review_priority",
        "demo_predictions_are_in_sample": True,
        "qualified_promotion_allowed": False,
    }
