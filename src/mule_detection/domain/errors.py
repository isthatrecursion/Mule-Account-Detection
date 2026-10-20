"""Fixed safe messages; arbitrary diagnostics never become public error content."""

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    CONTRACT_INVALID = "CONTRACT_INVALID"
    CONTRACT_VERSION = "CONTRACT_VERSION"
    TIMESTAMP_NAIVE = "TIMESTAMP_NAIVE"
    TIMESTAMP_INVALID = "TIMESTAMP_INVALID"
    COUNT_INVALID = "COUNT_INVALID"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    FEATURE_FORBIDDEN = "FEATURE_FORBIDDEN"
    VALUE_INVALID = "VALUE_INVALID"
    HASH_MISMATCH = "HASH_MISMATCH"
    SPLIT_MISMATCH = "SPLIT_MISMATCH"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    CUTOFF_MISMATCH = "CUTOFF_MISMATCH"
    DICTIONARY_UNCERTIFIED = "DICTIONARY_UNCERTIFIED"
    LABEL_HISTORY_INVALID = "LABEL_HISTORY_INVALID"
    LINEAGE_INVALID = "LINEAGE_INVALID"
    SCORE_STATE_INVALID = "SCORE_STATE_INVALID"
    EVENT_SEQUENCE_INVALID = "EVENT_SEQUENCE_INVALID"
    EVENT_CLOCK_SKEW = "EVENT_CLOCK_SKEW"
    COMPLETENESS_INVALID = "COMPLETENESS_INVALID"
    WORKFLOW_INVALID = "WORKFLOW_INVALID"


MESSAGES = {
    ErrorCode.INVALID_ARGUMENTS: "Invalid arguments. Use --help for the command syntax.",
    ErrorCode.CONFIGURATION_INVALID: "Configuration is missing, invalid, or inaccessible.",
    ErrorCode.UNSUPPORTED_OPERATION: "This operation is not implemented in the current build.",
    ErrorCode.INTERNAL_ERROR: "The operation failed. Refer to the correlation ID.",
}
EXIT_CODES = {
    ErrorCode.INVALID_ARGUMENTS: 2,
    ErrorCode.CONFIGURATION_INVALID: 3,
    ErrorCode.UNSUPPORTED_OPERATION: 4,
    ErrorCode.INTERNAL_ERROR: 1,
}

# Contract errors carry static messages only; rejected rows and values never enter public output.
for _code, _message in {
    ErrorCode.CONTRACT_INVALID: "Required contract fields or types are invalid.",
    ErrorCode.CONTRACT_VERSION: "The contract or schema version is not supported.",
    ErrorCode.TIMESTAMP_NAIVE: "A timestamp is missing its timezone.",
    ErrorCode.TIMESTAMP_INVALID: "A UTC timestamp is invalid.",
    ErrorCode.COUNT_INVALID: "A count is outside the contract limits.",
    ErrorCode.SCHEMA_MISMATCH: "Input columns do not match the registered schema.",
    ErrorCode.FEATURE_FORBIDDEN: "A forbidden or metadata field was requested as a predictor.",
    ErrorCode.VALUE_INVALID: "An input cell violates its logical type or missing-value rule.",
    ErrorCode.HASH_MISMATCH: "Input content does not match its trusted fingerprint.",
    ErrorCode.SPLIT_MISMATCH: "The research split does not align with the input records.",
    ErrorCode.IDENTITY_CONFLICT: "Record identities are duplicated or inconsistent.",
    ErrorCode.SOURCE_CONFLICT: "Source ownership or source registration is inconsistent.",
    ErrorCode.CUTOFF_MISMATCH: "Observation or availability cutoffs are incompatible.",
    ErrorCode.DICTIONARY_UNCERTIFIED: "Certified feature metadata requires known identity and approval.",
    ErrorCode.LABEL_HISTORY_INVALID: "Label correction history is inconsistent.",
    ErrorCode.LINEAGE_INVALID: "Required artifact or model lineage is inconsistent.",
    ErrorCode.SCORE_STATE_INVALID: "Score values contradict assessment state or cohort lineage.",
    ErrorCode.EVENT_SEQUENCE_INVALID: "Event sequence or epoch continuity is invalid.",
    ErrorCode.EVENT_CLOCK_SKEW: "An event exceeds its source clock-skew allowance.",
    ErrorCode.COMPLETENESS_INVALID: "Source completeness evidence is contradictory or insufficient.",
    ErrorCode.WORKFLOW_INVALID: "The requested workflow transition is not permitted.",
}.items():
    MESSAGES[_code] = _message
    EXIT_CODES[_code] = 5


class DomainError(Exception):
    def __init__(self, code: ErrorCode, correlation_id: str | None = None) -> None:
        self.code = code
        self.safe_message = MESSAGES[code]
        self.severity = "ERROR"
        self.correlation_id = correlation_id
        super().__init__(self.safe_message)

    def public(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.safe_message,
            "severity": self.severity,
            "correlation_id": self.correlation_id,
        }
