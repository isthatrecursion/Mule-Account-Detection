"""Inner-only configuration search and version-bound acceptance guards."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from mule_detection.domain.contracts.common import Digest, UtcTime, ValueModel, canonical_hash
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.training.evaluation_policy import ModelSpec
from mule_detection.training.metrics import ranking_metrics
from mule_detection.training.model_factory import fit_candidate
from mule_detection.training.splits import research_folds


class FrozenSelection(ValueModel):
    config_hash: Digest
    feature_policy_hash: Digest
    data_hash: Digest
    selected_spec: ModelSpec
    frozen_at: UtcTime

    @property
    def fingerprint(self) -> str:
        return canonical_hash(self)


def require_acceptance_release(
    frozen: FrozenSelection | None,
    *,
    release_hash: str,
    expected_config_hash: str,
    expected_policy_hash: str,
    label_release_at: datetime,
    inspected_release_hashes: frozenset[str],
) -> None:
    if (
        frozen is None
        or label_release_at.utcoffset() is None
        or frozen.config_hash != expected_config_hash
        or frozen.feature_policy_hash != expected_policy_hash
        or frozen.frozen_at >= label_release_at
        or release_hash in inspected_release_hashes
        or release_hash == frozen.data_hash
    ):
        raise DomainError(ErrorCode.SPLIT_MISMATCH)


def select_configuration(
    X: Any,
    target: Any,
    keys: tuple[str, ...],
    prototype: FeaturePipeline,
    specs: tuple[ModelSpec, ...],
    *,
    folds: int,
    seed: int,
    threads: int,
) -> tuple[ModelSpec, dict[str, Any]]:
    if not specs or len({spec.family for spec in specs}) != 1:
        raise DomainError(ErrorCode.CONFIGURATION_INVALID)
    # Even a predeclared single configuration has an explicit reserved inner plan;
    # no tuning fits are needed when there is no choice to make.
    splits = research_folds(keys, target, folds, seed)
    report: dict[str, Any] = {
        "metric": "mean_inner_average_precision",
        "inner_splits": [fold.manifest() for fold in splits],
        "trials": [],
    }
    if len(specs) == 1:
        report.update(
            status="PREDECLARED_SINGLE_CONFIGURATION", selected=specs[0].model_dump(mode="json")
        )
        report["trials"] = [
            {
                "spec": specs[0].model_dump(mode="json"),
                "mean_inner_average_precision": None,
                "fitted": False,
            }
        ]
        return specs[0], report
    positions = {key: i for i, key in enumerate(keys)}
    y = np.asarray(target)
    for spec in specs:
        scores = []
        for fold in splits:
            train = [positions[key] for key in fold.train_keys]
            valid = [positions[key] for key in fold.validation_keys]
            candidate = fit_candidate(
                prototype, spec, X.iloc[train], y[train], seed=seed + fold.number, threads=threads
            )
            metric = ranking_metrics(
                list(fold.validation_keys), y[valid], candidate.predict_score(X.iloc[valid]), (1,)
            )
            scores.append(metric["average_precision"])
        report["trials"].append(
            {
                "spec": spec.model_dump(mode="json"),
                "fold_average_precision": scores,
                "mean_inner_average_precision": float(np.mean(scores)),
                "fitted": True,
            }
        )
    winner = sorted(
        report["trials"],
        key=lambda row: (-row["mean_inner_average_precision"], row["spec"]["name"]),
    )[0]
    selected = next(spec for spec in specs if spec.name == winner["spec"]["name"])
    report.update(status="INNER_TUNING_COMPLETE", selected=selected.model_dump(mode="json"))
    return selected, report
