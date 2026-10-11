"""Reproducible pre-architecture checks for the mule-account dataset.

The script deliberately restricts all target-aware analysis and model fitting to
the saved development partition. It never scores the internal holdout.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


TARGET = "F3924"
INDEX = "Unnamed: 0"
BATCH = "F2230"
HARD_BLOCKLIST = {
    INDEX,
    TARGET,
    BATCH,
    "F3912",
    "F3287",
    "F3290",
    "F3611",
    "F3614",
}

MODEL_CONFIG = {
    "objective": "binary",
    "n_estimators": 300,
    "learning_rate": 0.05,
    "num_leaves": 15,
    "scale_pos_weight": 10.0,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "n_jobs": -1,
    "verbosity": -1,
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def environment_manifest(root: Path) -> dict:
    packages = {}
    for name in ("pandas", "numpy", "scikit-learn", "lightgbm", "scipy"):
        packages[name] = importlib.metadata.version(name)
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": packages,
        "input_sha256": {
            "dataset": file_sha256(root / "DataSet__1_.csv"),
            "split_register": file_sha256(root / "eda" / "holdout_split_indices.csv"),
            "exclusion_register": file_sha256(
                root / "eda" / "05_leakage_and_feature_exclusions.csv"
            ),
        },
        "verification_script_sha256": file_sha256(Path(__file__).resolve()),
    }


def _series_digest(series: pd.Series) -> bytes:
    values = pd.util.hash_pandas_object(series, index=False).values.tobytes()
    return hashlib.blake2b(
        str(series.dtype).encode("utf-8") + values, digest_size=16
    ).digest()


class FoldSafePreprocessor:
    """Fit structural selection, imputation, and encoding on one training fold."""

    def __init__(self, missing_threshold: float = 0.90):
        self.missing_threshold = missing_threshold

    @staticmethod
    def _semantic_clean(frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        if "F3888" in frame:
            parsed = pd.to_datetime(frame["F3888"], errors="coerce")
            legacy = parsed.dt.year.le(1950)
            frame["F3888_IS_LEGACY"] = legacy.astype("int8")
            frame["F3888"] = parsed.where(~legacy).map(
                lambda value: value.toordinal() if pd.notna(value) else np.nan
            )
        if {"F3893", "F3894"}.issubset(frame.columns):
            invalid_age = (
                frame["F3893"].eq("RETAIL")
                & (frame["F3894"].lt(18) | frame["F3894"].gt(100))
            )
            frame.loc[invalid_age, "F3894"] = np.nan
        return frame

    def fit(self, frame: pd.DataFrame) -> "FoldSafePreprocessor":
        frame = self._semantic_clean(frame)
        zero_variance = [
            column for column in frame if frame[column].nunique(dropna=True) <= 1
        ]
        candidates = frame.drop(columns=zero_variance)
        high_missingness = candidates.columns[
            candidates.isna().mean().ge(self.missing_threshold)
        ].tolist()
        candidates = candidates.drop(columns=high_missingness)

        canonical_by_digest: dict[bytes, str] = {}
        duplicates: list[str] = []
        for column in candidates:
            digest = _series_digest(candidates[column])
            canonical = canonical_by_digest.get(digest)
            if canonical is not None and candidates[column].equals(candidates[canonical]):
                duplicates.append(column)
            else:
                canonical_by_digest[digest] = column

        self.dropped_ = {
            "zero_variance": zero_variance,
            "high_missingness": high_missingness,
            "exact_duplicate": duplicates,
        }
        dropped = set(zero_variance + high_missingness + duplicates)
        self.keep_columns_ = [column for column in frame if column not in dropped]
        selected = frame[self.keep_columns_]
        categorical = selected.select_dtypes(include=["object", "category"]).columns.tolist()
        numeric = [column for column in selected if column not in categorical]

        self.transformer_ = ColumnTransformer(
            transformers=[
                (
                    "numeric",
                    SimpleImputer(strategy="median", add_indicator=False),
                    numeric,
                ),
                (
                    "categorical",
                    Pipeline(
                        steps=[
                            ("imputer", SimpleImputer(strategy="most_frequent")),
                            (
                                "encoder",
                                OneHotEncoder(handle_unknown="ignore", sparse_output=True),
                            ),
                        ]
                    ),
                    categorical,
                ),
            ],
            sparse_threshold=0.3,
        )
        self.transformer_.fit(selected)
        return self

    def transform(self, frame: pd.DataFrame):
        frame = self._semantic_clean(frame)
        return self.transformer_.transform(frame[self.keep_columns_])

    def fit_transform(self, frame: pd.DataFrame):
        return self.fit(frame).transform(frame)


def load_inputs(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    data = pd.read_csv(root / "DataSet__1_.csv")
    splits = pd.read_csv(root / "eda" / "holdout_split_indices.csv")
    exclusions = pd.read_csv(root / "eda" / "05_leakage_and_feature_exclusions.csv")
    return data, splits, exclusions


def validate_saved_artifacts(
    data: pd.DataFrame, splits: pd.DataFrame, exclusions: pd.DataFrame
) -> dict:
    if len(data) != len(splits):
        raise ValueError("Dataset and split register have different row counts")
    if not np.array_equal(data[INDEX].to_numpy(), splits["account_id"].to_numpy()):
        raise ValueError("Split account IDs are not aligned with the dataset")
    if not np.array_equal(data[TARGET].to_numpy(), splits["target"].to_numpy()):
        raise ValueError("Split targets are not aligned with the dataset")
    if exclusions["column_name"].duplicated().any():
        raise ValueError("Exclusion register contains duplicate column names")
    unknown = sorted(set(exclusions["column_name"]) - set(data.columns))
    if unknown:
        raise ValueError(f"Exclusion register references unknown columns: {unknown}")

    month_target = pd.crosstab(data[BATCH], data[TARGET])
    mixed_class_months = int((month_target.gt(0).sum(axis=1) > 1).sum())
    return {
        "rows": int(len(data)),
        "columns": int(data.shape[1]),
        "positive_labels": int(data[TARGET].sum()),
        "exclusion_count": int(len(exclusions)),
        "registered_active_columns": int(data.shape[1] - len(exclusions)),
        "split_counts": splits.groupby(["split", "target"]).size().to_dict(),
        "month_target_crosstab": month_target.to_dict(),
        "months_containing_both_classes": mixed_class_months,
        "cohort_identifiability": (
            "FAIL: target and extraction month cannot be separated in this dataset"
            if mixed_class_months == 0
            else "PASS"
        ),
    }


def audit_development_features(
    data: pd.DataFrame, splits: pd.DataFrame, exclusions: pd.DataFrame
) -> tuple[dict, pd.DataFrame]:
    development = data.loc[splits["split"].eq("dev").to_numpy()].copy()
    active_columns = [
        column for column in data.columns if column not in set(exclusions["column_name"])
    ]
    active = development[active_columns]
    positive = development[TARGET].eq(1)
    negative = ~positive
    missingness_delta = (
        active.loc[positive].isna().mean() - active.loc[negative].isna().mean()
    ).abs().sort_values(ascending=False)
    residual = pd.DataFrame(
        {
            "column_name": missingness_delta.index,
            "absolute_missingness_gap": missingness_delta.values,
            "positive_missingness": active.loc[positive].isna().mean()[
                missingness_delta.index
            ].values,
            "negative_missingness": active.loc[negative].isna().mean()[
                missingness_delta.index
            ].values,
        }
    )
    all_positive_missing = residual.loc[
        residual["positive_missingness"].eq(1.0)
        & residual["negative_missingness"].lt(1.0)
    ]
    audit = {
        "development_rows": int(len(development)),
        "development_positives": int(development[TARGET].sum()),
        "active_columns": int(len(active_columns)),
        "missingness_gap_ge_0_10": int(
            residual["absolute_missingness_gap"].ge(0.10).sum()
        ),
        "missingness_gap_ge_0_25": int(
            residual["absolute_missingness_gap"].ge(0.25).sum()
        ),
        "columns_missing_for_all_development_positives": int(len(all_positive_missing)),
        "maximum_missingness_gap": float(residual["absolute_missingness_gap"].max()),
        "interpretation": (
            "These are residual cohort-risk indicators, not proven leakage or proven "
            "behavioral signals. Perfect month/target confounding prevents that distinction."
        ),
    }
    return audit, residual


def top_k_metrics(target: np.ndarray, score: np.ndarray, k: int) -> dict:
    order = np.argsort(-score)[:k]
    positives = int(target[order].sum())
    return {
        "k": k,
        "positives": positives,
        "precision": positives / k,
        "recall": positives / int(target.sum()),
    }


def run_fold_safe_benchmark(
    data: pd.DataFrame, splits: pd.DataFrame
) -> tuple[dict, pd.DataFrame, list[dict], dict]:
    development_mask = splits["split"].eq("dev").to_numpy()
    development = data.loc[development_mask].reset_index(drop=True)
    account_ids = development[INDEX].copy()
    target = development[TARGET].astype(int).to_numpy()
    features = development.drop(columns=[column for column in HARD_BLOCKLIST if column in development])

    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = np.full(len(development), np.nan)
    fold_ids = np.full(len(development), -1)
    fold_reports: list[dict] = []
    fold_features: dict[str, list[str]] = {}

    for fold, (train_index, validation_index) in enumerate(
        folds.split(features, target), start=1
    ):
        preprocessor = FoldSafePreprocessor(missing_threshold=0.90)
        train_matrix = preprocessor.fit_transform(features.iloc[train_index])
        validation_matrix = preprocessor.transform(features.iloc[validation_index])
        model = lgb.LGBMClassifier(
            **MODEL_CONFIG,
            random_state=42 + fold,
        )
        model.fit(train_matrix, target[train_index])
        fold_score = model.predict_proba(validation_matrix)[:, 1]
        scores[validation_index] = fold_score
        fold_ids[validation_index] = fold
        fold_features[str(fold)] = preprocessor.keep_columns_
        fold_reports.append(
            {
                "fold": fold,
                "model_random_state": 42 + fold,
                "train_rows": int(len(train_index)),
                "validation_rows": int(len(validation_index)),
                "validation_positives": int(target[validation_index].sum()),
                "selected_raw_columns": int(len(preprocessor.keep_columns_)),
                "dropped": {
                    key: len(value) for key, value in preprocessor.dropped_.items()
                },
                "roc_auc": float(roc_auc_score(target[validation_index], fold_score)),
                "average_precision": float(
                    average_precision_score(target[validation_index], fold_score)
                ),
            }
        )

    if np.isnan(scores).any() or (fold_ids < 1).any():
        raise RuntimeError("Out-of-fold predictions are incomplete")
    metrics = {
        "scope": "development-only out-of-fold diagnostic",
        "cross_validation": {
            "type": "StratifiedKFold",
            "n_splits": 5,
            "shuffle": True,
            "random_state": 42,
        },
        "model": {"class": "lightgbm.LGBMClassifier", **MODEL_CONFIG},
        "limitations": [
            "Target and extraction month are perfectly confounded.",
            "These metrics do not establish future-period or production performance.",
            "No internal holdout rows were scored.",
        ],
        "roc_auc": float(roc_auc_score(target, scores)),
        "average_precision": float(average_precision_score(target, scores)),
        "top_k": [top_k_metrics(target, scores, k) for k in (25, 50, 100)],
    }
    predictions = pd.DataFrame(
        {
            "account_id": account_ids,
            "fold": fold_ids,
            "target": target,
            "oof_score": scores,
        }
    )
    return metrics, predictions, fold_reports, fold_features


def json_safe(value):
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/pre_architecture_verification"),
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run the five-fold development-only LightGBM benchmark.",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output_dir
    if not output.is_absolute():
        output = root / output
    output.mkdir(parents=True, exist_ok=True)

    data, splits, exclusions = load_inputs(root)
    structure = validate_saved_artifacts(data, splits, exclusions)
    feature_audit, residual = audit_development_features(data, splits, exclusions)
    report: dict = {
        "environment": environment_manifest(root),
        "structure": structure,
        "development_feature_audit": feature_audit,
    }
    residual.head(100).to_csv(output / "residual_cohort_risk.csv", index=False)

    if args.benchmark:
        metrics, predictions, folds, fold_features = run_fold_safe_benchmark(data, splits)
        report["benchmark"] = metrics
        report["folds"] = folds
        predictions.to_csv(output / "oof_predictions.csv", index=False)
        with (output / "fold_feature_manifests.json").open(
            "w", encoding="utf-8"
        ) as handle:
            json.dump(fold_features, handle, indent=2, sort_keys=True)

    with (output / "verification_report.json").open("w", encoding="utf-8") as handle:
        json.dump(json_safe(report), handle, indent=2, sort_keys=True)
    print(json.dumps(json_safe(report), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
