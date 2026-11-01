"""Predictor-only research frames from hash-verified, development-bound intake."""

from __future__ import annotations

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.ingestion.partition_guard import PartitionGuard
from mule_detection.ingestion.research_adapter import ResearchBatch


def research_frame(batch: ResearchBatch, guard: PartitionGuard) -> pd.DataFrame:
    guard.assert_development(batch.record_keys, batch.dataset_sha256, batch.split_sha256)
    if set(batch.predictors) != set(batch.logical_types) or any(
        len(values) != len(batch.record_keys) for values in batch.predictors.values()
    ):
        raise DomainError(ErrorCode.SCHEMA_MISMATCH)
    columns = {}
    for column, values in batch.predictors.items():
        kind = batch.logical_types[column]
        if kind == "categorical":
            # sklearn's legacy imputer treats NaN as missing, not Python None.
            series = pd.Series(
                [np.nan if value is None else value for value in values], dtype=object
            )
        else:
            series = pd.Series(values.tolist())
            if kind == "number":
                series = series.astype(float)
            elif kind != "integer":
                raise DomainError(ErrorCode.SCHEMA_MISMATCH)
            if kind == "integer":
                for original, converted in zip(values, series, strict=True):
                    if original is not None and int(converted) != int(original):
                        raise DomainError(ErrorCode.VALUE_INVALID)
        columns[column] = series
    return pd.DataFrame(columns)
