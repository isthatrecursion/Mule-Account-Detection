"""Ordered raw and encoded signatures without parsing generated feature names."""

from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from mule_detection.domain.contracts.common import canonical_hash
from mule_detection.domain.errors import DomainError, ErrorCode


def frame_fingerprint(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(
        canonical_hash({"columns": [(str(c), str(t)) for c, t in frame.dtypes.items()]}).encode()
    )
    digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    return digest.hexdigest()


def logical_type(series: Any) -> str:
    return "categorical" if str(series.dtype) in ("object", "category") else "numeric"


def input_signature(frame: pd.DataFrame) -> list[dict[str, str]]:
    return [{"name": str(c), "kind": logical_type(frame[c])} for c in frame]


def align_input(frame: pd.DataFrame, signature: list[dict[str, str]]) -> pd.DataFrame:
    names = [item["name"] for item in signature]
    if frame.columns.duplicated().any() or set(frame.columns) != set(names):
        raise DomainError(ErrorCode.SCHEMA_MISMATCH)
    for item in signature:
        if logical_type(frame[item["name"]]) != item["kind"]:
            raise DomainError(ErrorCode.SCHEMA_MISMATCH)
    return frame.loc[:, names].copy()


def transformed_mapping(transformer: Any) -> list[dict[str, Any]]:
    names = transformer.get_feature_names_out().tolist()
    mapping: list[dict[str, Any]] = []
    for name, fitted, columns in transformer.transformers_:
        if name == "remainder" or not len(columns):
            continue
        output_slice = transformer.output_indices_[name]
        if name == "numeric":
            raw_columns = list(columns)
        else:
            encoder = fitted.named_steps["encoder"]
            raw_columns = [
                column
                for column, categories in zip(columns, encoder.categories_, strict=True)
                for _ in categories
            ]
        if len(raw_columns) != output_slice.stop - output_slice.start:
            raise DomainError(ErrorCode.SCHEMA_MISMATCH)
        for index, raw in zip(
            range(output_slice.start, output_slice.stop), raw_columns, strict=True
        ):
            mapping.append({"index": index, "name": names[index], "raw_feature": raw})
    return mapping
