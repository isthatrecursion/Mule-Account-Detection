"""Logical signatures are ordered registry definitions, independent of CSV column order."""

from mule_detection.persistence.repositories import fingerprint


def schema_signature(columns: list[tuple[str, str]]) -> str:
    return fingerprint([[name, logical_type] for name, logical_type in columns])
