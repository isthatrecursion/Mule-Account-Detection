"""Deterministic ranking metrics; unavailable statistics remain null."""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score  # type: ignore[import-untyped]

from mule_detection.domain.errors import DomainError, ErrorCode


def ranking_metrics(
    keys: list[str], target: Any, scores: Any, ks: tuple[int, ...]
) -> dict[str, Any]:
    y, score = np.asarray(target), np.asarray(scores, dtype=float)
    if (
        y.ndim != 1
        or score.ndim != 1
        or len(y) != len(keys)
        or len(score) != len(keys)
        or len(set(keys)) != len(keys)
        or not np.isin(y, [0, 1]).all()
        or not np.isfinite(score).all()
        or any(k < 1 for k in ks)
    ):
        raise DomainError(ErrorCode.VALUE_INVALID)
    n, positives = len(y), int(y.sum())
    order = sorted(range(n), key=lambda i: (-float(score[i]), keys[i]))
    both_classes = 0 < positives < n
    top = []
    for k in ks:
        effective = min(k, n)
        selected = int(y[order[:effective]].sum())
        precision = selected / effective if effective else None
        top.append(
            {
                "k": k,
                "k_effective": effective,
                "selected_positives": selected,
                "precision": precision,
                "recall": selected / positives if positives else None,
                "lift": precision / (positives / n)
                if precision is not None and positives
                else None,
            }
        )
    return {
        "rows": n,
        "positives": positives,
        "average_precision": float(average_precision_score(y, score)) if both_classes else None,
        "roc_auc": float(roc_auc_score(y, score)) if both_classes else None,
        "undefined_reason": None if both_classes else "EMPTY_OR_SINGLE_CLASS",
        "top_k": top,
    }


def bootstrap_intervals(
    keys: list[str],
    target: Any,
    scores: Any,
    groups: list[str],
    *,
    repetitions: int,
    seed: int,
    ks: tuple[int, ...],
) -> dict[str, Any]:
    ranking_metrics(keys, target, scores, ks)
    if len(groups) != len(keys) or not groups:
        raise DomainError(ErrorCode.VALUE_INVALID)
    unique = sorted(set(groups))
    members = {group: np.flatnonzero(np.asarray(groups) == group) for group in unique}
    rng = np.random.default_rng(seed)
    samples: dict[str, list[float]] = {"average_precision": [], "roc_auc": []}
    for k in ks:
        samples[f"precision_at_{k}"] = []
        samples[f"recall_at_{k}"] = []
    invalid: Counter[str] = Counter()
    y, score = np.asarray(target), np.asarray(scores)
    for _ in range(repetitions):
        indices = np.concatenate([members[group] for group in rng.choice(unique, len(unique))])
        # Occurrence suffixes preserve deterministic ties while allowing a sampled group twice.
        metric = ranking_metrics(
            [f"{keys[i]}:{j:08d}" for j, i in enumerate(indices)], y[indices], score[indices], ks
        )
        for name in ("average_precision", "roc_auc"):
            if metric[name] is None:
                invalid[name] += 1
            else:
                samples[name].append(metric[name])
        for row in metric["top_k"]:
            for name in ("precision", "recall"):
                metric_name = f"{name}_at_{row['k']}"
                if row[name] is None:
                    invalid[metric_name] += 1
                else:
                    samples[metric_name].append(row[name])
    return {
        "method": "percentile_group_bootstrap",
        "seed": seed,
        "repetitions": repetitions,
        "group_count": len(unique),
        "intervals": {
            name: {
                "lower": float(np.quantile(values, 0.025)) if values else None,
                "upper": float(np.quantile(values, 0.975)) if values else None,
                "valid_resamples": len(values),
                "invalid_resamples": invalid[name],
            }
            for name, values in samples.items()
        },
    }
