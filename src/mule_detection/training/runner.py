"""Development-only candidate evaluation with encrypted per-fold evidence."""

from __future__ import annotations

import gc
import io
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import joblib  # type: ignore[import-untyped]
import numpy as np

from mule_detection.domain.clock import Clock, SystemClock
from mule_detection.domain.contracts.common import canonical_hash
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.features.signature import frame_fingerprint
from mule_detection.ingestion.partition_guard import PartitionGuard
from mule_detection.training.cohort_probes import cohort_probes
from mule_detection.training.evaluation_policy import (
    LIMITATIONS,
    ModelSpec,
    TrainingConfig,
    require_mode,
)
from mule_detection.training.metrics import bootstrap_intervals, ranking_metrics
from mule_detection.training.model_factory import fit_candidate
from mule_detection.training.report import RunStore
from mule_detection.training.search import FrozenSelection, select_configuration
from mule_detection.training.splits import research_folds
from mule_detection.training.subgroup_report import subgroup_report


@dataclass(frozen=True)
class TrainingInput:
    X: Any
    target: Any
    keys: tuple[str, ...]
    guard: PartitionGuard
    dataset_hash: str
    split_hash: str
    data_tier: str
    cohorts: tuple[str, ...]
    validation_reference: str
    approved_subgroups: dict[str, str]


def run_experiment(
    data: TrainingInput,
    prototype: FeaturePipeline,
    config: TrainingConfig,
    store: RunStore,
    run_id: UUID,
    *,
    actor_id: str,
    environment: dict[str, Any],
    before_finalize: Callable[[], None] = lambda: None,
    clock: Clock | None = None,
) -> dict[str, Any]:
    require_mode(config.mode, data.data_tier)
    data.guard.assert_development(data.keys, data.dataset_hash, data.split_hash)
    prototype.policy.assert_predictors(list(data.X))
    if len(data.X) != len(data.keys) or len(data.target) != len(data.keys):
        raise DomainError(ErrorCode.SPLIT_MISMATCH)
    config_hash = config.fingerprint
    request_hash = canonical_hash(
        {
            "actor": actor_id,
            "config": config_hash,
            "dataset": data.dataset_hash,
            "split": data.split_hash,
            "validation": data.validation_reference,
            "policy": prototype.policy.fingerprint,
            "predictors": frame_fingerprint(data.X),
            "labels": canonical_hash({"labels": np.asarray(data.target).tolist()}),
            "runtime_and_code": canonical_hash(environment),
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
    if not store.begin(run_id, request_hash):
        return evaluate_run(store, run_id, actor_id=actor_id)
    files: dict[str, dict[str, Any]] = {}

    def save(name: str, value: Any) -> None:
        files[name] = store.put_json(run_id, name, value)

    try:
        y = np.asarray(data.target)
        folds = research_folds(data.keys, y, config.outer_folds, config.seed)
        positions = {key: i for i, key in enumerate(data.keys)}
        # Split manifests are durable before any estimator is fitted.
        save(
            "splits.json",
            [
                {
                    **fold.manifest(),
                    "training_positives": int(y[[positions[k] for k in fold.train_keys]].sum()),
                    "validation_positives": int(
                        y[[positions[k] for k in fold.validation_keys]].sum()
                    ),
                    "group_unit": "opaque_research_record_not_verified_account",
                    "temporal_range": None,
                }
                for fold in folds
            ],
        )
        save("config.json", config.model_dump(mode="json"))
        save("environment.json", environment)
        save("feature_policy.json", prototype.policy.model_dump(mode="json"))
        variants: list[tuple[str, str, tuple[str, ...]]] = []
        for configured_family in sorted({spec.family for spec in config.candidates}):
            variants.append((configured_family, configured_family, ()))
            if config.ablation_features:
                if not set(config.ablation_features) <= set(data.X.columns):
                    raise DomainError(ErrorCode.SCHEMA_MISMATCH)
                variants.append(
                    (configured_family + "_ablated", configured_family, config.ablation_features)
                )
        report: dict[str, Any] = {}
        all_predictions: dict[str, Any] = {}
        for name, family, excluded in variants:
            frame = data.X.drop(columns=list(excluded))
            specs = tuple(spec for spec in config.candidates if spec.family == family)
            oof, coverage = np.full(len(y), np.nan), np.zeros(len(y), dtype=int)
            fold_reports: list[dict[str, Any]] = []
            for fold in folds:
                train, valid = (
                    [positions[k] for k in fold.train_keys],
                    [positions[k] for k in fold.validation_keys],
                )
                for keys in (fold.train_keys, fold.validation_keys):
                    data.guard.assert_development(keys, data.dataset_hash, data.split_hash)
                start = time.monotonic()
                selected, search = select_configuration(
                    frame.iloc[train],
                    y[train],
                    fold.train_keys,
                    prototype,
                    specs,
                    folds=config.inner_folds,
                    seed=config.seed + fold.number,
                    threads=config.threads,
                )
                save(f"{name}_fold_{fold.number}_search.json", search)
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    fitted = fit_candidate(
                        prototype,
                        selected,
                        frame.iloc[train],
                        y[train],
                        seed=config.seed + fold.number,
                        threads=config.threads,
                    )
                    score = np.asarray(fitted.predict_score(frame.iloc[valid]), dtype=float)
                metric = ranking_metrics(list(fold.validation_keys), y[valid], score, config.top_k)
                oof[valid], coverage[valid] = score, coverage[valid] + 1
                payload = io.BytesIO()
                joblib.dump(fitted, payload, compress=3)
                artifact_name = f"{name}_fold_{fold.number}_fitted.joblib"
                files[artifact_name] = store.put(run_id, artifact_name, payload.getvalue())
                fold_report = {
                    "fold": fold.number,
                    "seed": config.seed + fold.number,
                    "selected_config": selected.model_dump(mode="json"),
                    "effective_estimator_parameters": fitted.estimator.get_params(),
                    "early_stopping_policy": "DISABLED_PREDECLARED_ESTIMATOR_COUNT",
                    "numeric_scaling": "TRAINING_FITTED_WITHOUT_CENTERING"
                    if fitted.scaler is not None
                    else "NONE",
                    "metrics": metric,
                    "training_rows": len(train),
                    "training_positives": int(y[train].sum()),
                    "validation_rows": len(valid),
                    "elapsed_seconds": time.monotonic() - start,
                    "feature_manifest": fitted.features.exclusion_report_,
                    "input_signature": fitted.features.input_signature_,
                    "transformed_features": fitted.features.transformed_features_,
                    "warning_categories": sorted({type(item.message).__name__ for item in caught}),
                    "predictions": [
                        {"record_key": key, "target": int(y[index]), "raw_score": float(value)}
                        for key, index, value in zip(
                            fold.validation_keys, valid, score, strict=True
                        )
                    ],
                }
                save(f"{name}_fold_{fold.number}.json", fold_report)
                fold_reports.append(
                    {
                        k: v
                        for k, v in fold_report.items()
                        if k
                        in {
                            "fold",
                            "metrics",
                            "elapsed_seconds",
                            "warning_categories",
                            "selected_config",
                        }
                    }
                )
                del fitted, payload
                gc.collect()
            if not (coverage == 1).all() or not np.isfinite(oof).all():
                raise DomainError(ErrorCode.SPLIT_MISMATCH)
            metrics = ranking_metrics(list(data.keys), y, oof, config.top_k)
            all_predictions[name] = [
                {"record_key": key, "target": int(label), "raw_score": float(score)}
                for key, label, score in zip(data.keys, y, oof, strict=True)
            ]
            save(f"{name}_oof.json", all_predictions[name])
            # Select the future final-fit configuration using inner folds on development.
            final_spec, final_search = select_configuration(
                frame,
                y,
                data.keys,
                prototype,
                specs,
                folds=config.inner_folds,
                seed=config.seed,
                threads=config.threads,
            )
            save(f"{name}_final_selection.json", final_search)
            report[name] = {
                "pooled_oof_diagnostic": metrics,
                "fold_results": fold_reports,
                "fold_ap_mean": float(
                    np.mean([f["metrics"]["average_precision"] for f in fold_reports])
                ),
                "fold_ap_std": float(
                    np.std([f["metrics"]["average_precision"] for f in fold_reports])
                ),
                "uncertainty": bootstrap_intervals(
                    list(data.keys),
                    y,
                    oof,
                    list(data.keys),
                    repetitions=config.bootstrap_repetitions,
                    seed=config.seed,
                    ks=config.top_k,
                ),
                "subgroups": subgroup_report(
                    list(data.keys),
                    y,
                    oof,
                    data.approved_subgroups,
                    approval_reference=config.subgroup_approval_reference,
                    minimum_rows=config.minimum_subgroup_rows,
                    minimum_positives=config.minimum_subgroup_positives,
                    k=config.top_k[0],
                    seed=config.seed,
                    research=True,
                ),
                "final_fit_configuration": final_spec.model_dump(mode="json"),
                "ablation_excluded_features": list(excluded),
                "oof_coverage_exactly_once": True,
            }
        candidates = [name for name, _, excluded in variants if not excluded]
        winner = sorted(candidates, key=lambda name: (-report[name]["fold_ap_mean"], name))[0]
        save("cohort_probes.json", cohort_probes(data.X, y, list(data.cohorts), seed=config.seed))
        final_report = {
            "status": "RESEARCH_DIAGNOSTIC_COMPLETE",
            "data_tier": data.data_tier,
            "mode": config.mode,
            "label_policy": "LEGACY_RESEARCH_TARGET_WITH_UNVERIFIED_MATURITY",
            "config_hash": config_hash,
            "candidates": report,
            "selected_family": winner,
            "selection_scope": "development_diagnostic_comparison_only",
            "family_selection_metric": "mean_outer_fold_average_precision",
            "frozen_selection": FrozenSelection(
                config_hash=config_hash,
                feature_policy_hash=prototype.policy.fingerprint,
                data_hash=data.dataset_hash,
                selected_spec=ModelSpec.model_validate(report[winner]["final_fit_configuration"]),
                frozen_at=(clock or SystemClock()).now(),
            ).model_dump(mode="json"),
            "ablation_comparison": {
                name: {
                    "baseline_family": family,
                    "pooled_ap_delta": report[name]["pooled_oof_diagnostic"]["average_precision"]
                    - report[family]["pooled_oof_diagnostic"]["average_precision"],
                    "approval_reference": config.ablation_approval_reference,
                }
                for name, family, excluded in variants
                if excluded
            },
            "calibration": {
                "status": "BLOCKED",
                "reason": "REPRESENTATIVE_PREVALENCE_AND_MATURE_LABELS_UNAVAILABLE",
                "output_scale": "review_priority",
            },
            "qualified_promotion_allowed": False,
            "limitations": list(LIMITATIONS),
        }
        save("report.json", final_report)
        files["model_card.md"] = store.put(
            run_id,
            "model_card.md",
            (
                "# Research candidate evidence\n\nSelected family: "
                + winner
                + "\n\nQualified promotion: BLOCKED\n\n"
                + "\n".join("- " + limitation for limitation in LIMITATIONS)
                + "\n"
            ).encode(),
        )
        before_finalize()
        manifest = {
            "format": "candidate_evidence_v1",
            "run_id": str(run_id),
            "actor_id": actor_id,
            "request_hash": request_hash,
            "dataset_hash": data.dataset_hash,
            "split_hash": data.split_hash,
            "validation_reference": data.validation_reference,
            "config_hash": config_hash,
            "feature_policy_hash": prototype.policy.fingerprint,
            "data_tier": data.data_tier,
            "files": files,
        }
        store.finish(run_id, manifest)
        return evaluate_run(store, run_id, actor_id=actor_id)
    except Exception:
        store.fail(run_id)
        raise


def evaluate_run(store: RunStore, run_id: UUID, *, actor_id: str) -> dict[str, Any]:
    manifest = store.manifest(run_id)
    if manifest["actor_id"] != actor_id:
        raise DomainError(ErrorCode.INVALID_ARGUMENTS)
    config = TrainingConfig.model_validate(store.json(run_id, "config.json", manifest))
    if config.fingerprint != manifest["config_hash"]:
        raise DomainError(ErrorCode.LINEAGE_INVALID)
    report = store.json(run_id, "report.json", manifest)
    splits = store.json(run_id, "splits.json", manifest)
    eligible = [key for fold in splits for key in fold["validation_keys"]]
    if len(eligible) != len(set(eligible)):
        raise DomainError(ErrorCode.SPLIT_MISMATCH)
    for name, candidate in report["candidates"].items():
        rows = store.json(run_id, f"{name}_oof.json", manifest)
        keys = [row["record_key"] for row in rows]
        if set(keys) != set(eligible) or len(keys) != len(eligible):
            raise DomainError(ErrorCode.SPLIT_MISMATCH)
        recalculated = ranking_metrics(
            keys, [r["target"] for r in rows], [r["raw_score"] for r in rows], config.top_k
        )
        if recalculated != candidate["pooled_oof_diagnostic"]:
            raise DomainError(ErrorCode.LINEAGE_INVALID)
    return {
        "run_id": str(run_id),
        "status": "SUCCEEDED",
        "mode": config.mode,
        "data_tier": manifest["data_tier"],
        "selected_family": report["selected_family"],
        "metrics": {
            name: value["pooled_oof_diagnostic"] for name, value in report["candidates"].items()
        },
        "qualified_promotion_allowed": False,
        "output_scale": "review_priority",
    }
