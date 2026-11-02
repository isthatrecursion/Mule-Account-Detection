"""Gate reports are bound to immutable candidate evidence, never registry tags."""

from typing import Any

from pydantic import Field

from mule_detection.domain.contracts.common import Digest, Text, ValueModel, canonical_hash


class PromotionEvidence(ValueModel):
    data_tier: str
    identity_reference: Text | None = None
    dictionary_reference: Text | None = None
    label_reference: Text | None = None
    availability_reference: Text | None = None
    representative_cohort_reference: Text | None = None
    metric_report_reference: Text | None = None
    security_review_reference: Text | None = None
    model_risk_review_reference: Text | None = None
    threshold_policy_version: Text | None = None
    unresolved_critical: tuple[str, ...] = ()
    bound_bundle_digest: Digest
    metrics_passed: bool = False
    independent_acceptance_passed: bool = False
    permitted_environments: tuple[str, ...] = Field(default=())


def promotion_gate(
    evidence: PromotionEvidence, *, digest: str, environment: str, target: str
) -> dict[str, Any]:
    reasons = []
    if evidence.bound_bundle_digest != digest:
        reasons.append("BUNDLE_IDENTITY_MISMATCH")
    if target == "RESEARCH_DEMO":
        if environment not in {"local", "test", "research"} or evidence.data_tier not in {
            "research",
            "synthetic",
        }:
            reasons.append("RESEARCH_ENVIRONMENT_REQUIRED")
    elif target in {"APPROVED_FOR_SHADOW", "APPROVED_FOR_PILOT"}:
        if environment not in {"staging", "qualified"} or evidence.data_tier != "qualified":
            reasons.append("QUALIFIED_DATA_AND_ENVIRONMENT_REQUIRED")
        if environment not in evidence.permitted_environments:
            reasons.append("ENVIRONMENT_NOT_APPROVED")
        for name in (
            "identity_reference",
            "dictionary_reference",
            "label_reference",
            "availability_reference",
            "representative_cohort_reference",
            "metric_report_reference",
            "security_review_reference",
            "model_risk_review_reference",
            "threshold_policy_version",
        ):
            if not getattr(evidence, name):
                reasons.append(name.upper() + "_MISSING")
        if evidence.unresolved_critical:
            reasons.append("CRITICAL_DEPENDENCIES_OPEN")
        if not evidence.metrics_passed or not evidence.independent_acceptance_passed:
            reasons.append("ACCEPTANCE_EVIDENCE_NOT_PASSED")
    elif target not in {"REJECTED", "RETIRED"}:
        reasons.append("INVALID_TARGET")
    return {
        "status": "BLOCKED" if reasons else "PASSED",
        "reasons": reasons,
        "bundle_digest": digest,
        "environment": environment,
        "target": target,
        "evidence_hash": canonical_hash(evidence),
    }
