"""Versioned intake findings; research acceptance never implies promotion approval."""

from typing import Literal
from uuid import UUID

from mule_detection.domain.contracts.common import Nonnegative, Text, ValueModel


class Finding(ValueModel):
    rule_id: Text
    rule_version: Literal["1"] = "1"
    severity: Literal["ERROR", "WARNING", "PROMOTION_BLOCKER"]
    count: Nonnegative = 1
    sample_references: tuple[str, ...] = ()
    remediation: Text


class ValidationResult(ValueModel):
    intake_id: UUID
    batch_id: UUID | None
    outcome: Literal["RECEIVED", "VALIDATING", "ACCEPTED", "QUARANTINED", "FAILED"]
    row_count: Nonnegative
    finding_codes: tuple[str, ...]
    finding_counts: dict[str, int]
    report_reference: str | None
    qualified_promotion_allowed: bool = False


class IntakeRejected(Exception):
    """Static codes only; parser exceptions/rows must never escape the boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def error(code: str, count: int = 1, samples: tuple[str, ...] = ()) -> Finding:
    return Finding(
        rule_id=code,
        severity="ERROR",
        count=count,
        sample_references=samples,
        remediation="Correct the source or manifest and submit a new intake request.",
    )


def promotion_blockers(tier: str, certified: bool) -> list[Finding]:
    codes = []
    if tier == "research":
        codes += ["CONFOUNDED_RESEARCH_COHORTS", "UNVERIFIED_RESEARCH_PROVENANCE"]
    if tier != "qualified" or not certified:
        codes += ["QUALIFIED_SOURCE_NOT_CERTIFIED"]
    return [
        Finding(
            rule_id=code,
            severity="PROMOTION_BLOCKER",
            remediation="Obtain independent qualified source, feature and label evidence.",
        )
        for code in codes
    ]


def assert_qualified_promotion(report: dict[str, object]) -> None:
    if report.get("qualified_promotion_allowed") is not True:
        raise IntakeRejected("QUALIFIED_PROMOTION_BLOCKED")
