"""ASSUMPTION: proposed read contracts, enabled only in isolated fixture mode.

No matching backend routes are deployed. These models document the extension
agreement required before a future live integration can be enabled.
"""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from ui.dto import EvidenceFacts, Nonnegative, Response, ScoreVersion


class Gate(Response):
    name: str
    state: Literal["PASSED", "FAILED", "BLOCKED", "NOT_RUN", "UNKNOWN"] = "NOT_RUN"
    reasons: list[str] = Field(default_factory=list)
    numerator: Nonnegative | None = None
    denominator: Nonnegative | None = None
    trials: Nonnegative | None = None

    @model_validator(mode="after")
    def sufficient_evidence(self) -> Self:
        if self.state == "PASSED" and (
            self.numerator is None
            or self.denominator is None
            or not self.trials
            or not self.denominator
        ):
            self.state = "NOT_RUN"
            self.reasons.append("Required denominators or trial evidence are missing.")
        if (
            self.numerator is not None
            and self.denominator is not None
            and self.numerator > self.denominator
        ):
            raise ValueError("Invalid evidence denominator")
        return self


class ModelSummary(Response):
    environment: str
    bundle_digest: str
    data_tier: str
    model_tier: str
    approval_state: str = "UNKNOWN"
    requester: str | None = None
    reviewer: str | None = None
    gates: list[Gate] = Field(default_factory=list)
    events: list[dict[str, str]] = Field(default_factory=list)


class Proposal(Response):
    proposal_id: UUID
    trigger: str
    status: str
    supporting_report_ids: list[UUID] = Field(default_factory=list)


class Report(Response):
    report_id: UUID
    scenario_fingerprint: str
    evidence_class: Literal["SYNTHETIC_ENGINEERING", "QUALIFIED_PREDICTIVE"]
    during_delay_disagreement: Gate
    final_consistency: Gate
    gates: list[Gate] = Field(default_factory=list)


class Assessment(Response):
    score_id: UUID
    case_id: UUID | None = None
    model_id: UUID
    queue_version: UUID | None = None
    score: ScoreVersion
    facts: EvidenceFacts | None = None


class SourceContext(Response):
    source_id: str
    oldest_open_gap_seconds: Nonnegative | None = None
    pending_reconciliation: bool | None = None
    complete_through: AwareDatetime | None = None


class DeploymentDecision(Response):
    record_id: UUID
    revision: str = Field(min_length=1)
    mode: Literal["BLOCKED", "RESEARCH_DEMO", "SHADOW", "PILOT"]
    data_tier: str
    model_tier: str
    approved_by: str | None = None
    allowed_actions: list[str] = Field(default_factory=list)
    stopping_conditions: list[str] = Field(default_factory=list)
    blocking_dependencies: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def approval_is_explicit(self) -> Self:
        if self.mode != "BLOCKED" and not self.approved_by:
            self.mode = "BLOCKED"
            self.allowed_actions = []
            self.blocking_dependencies.append("An approval identity is not supplied.")
        if self.mode == "PILOT" and (
            self.data_tier != "qualified" or self.model_tier == "research_demo"
        ):
            self.mode = "BLOCKED"
            self.allowed_actions = []
            self.blocking_dependencies.append(
                "Qualified data and a qualified-use model decision are required for pilot use."
            )
        return self


class PilotMetric(Response):
    metric_id: Literal[
        "eligible",
        "queued",
        "reviewed",
        "review_duration_seconds",
        "adjudicated_yield",
        "reopen_rate",
        "overturn_rate",
        "label_coverage",
    ]
    name: str
    numerator: float | None = Field(default=None, allow_inf_nan=False, ge=0)
    denominator: Nonnegative | None = None
    population: Literal["REVIEWED_SAMPLE", "ELIGIBLE_POPULATION"]
    labels_available: Nonnegative | None = None
    labels_eligible: Nonnegative | None = None
    outcome_maturity: Literal["NOT_AVAILABLE", "IMMATURE", "MATURE", "UNKNOWN"] = "UNKNOWN"
    state: Literal["PASSED", "BLOCKED", "NOT_RUN"] = "NOT_RUN"
    reasons: list[str] = Field(default_factory=list)
    freshness_counts: dict[str, Nonnegative] = Field(default_factory=dict)
    corrected_count: Nonnegative | None = None

    @model_validator(mode="after")
    def missing_is_not_zero(self) -> Self:
        outcome_metric = self.metric_id in {"adjudicated_yield", "overturn_rate"}
        if (
            self.numerator is None
            or not self.denominator
            or self.labels_available is None
            or self.labels_eligible is None
            or (outcome_metric and (not self.labels_available or self.outcome_maturity != "MATURE"))
        ):
            self.state = "NOT_RUN" if self.state != "BLOCKED" else "BLOCKED"
            self.reasons.append(
                "Required denominator or label-availability evidence is unavailable."
            )
        if (
            self.labels_available is not None
            and self.labels_eligible is not None
            and self.labels_available > self.labels_eligible
        ):
            raise ValueError("Invalid label coverage")
        return self


class ExtensionPayload(Response):
    kind: Literal[
        "models",
        "proposals",
        "reports",
        "source-health",
        "case-context",
        "queue-context",
        "deployment-status",
        "pilot-metrics",
    ]
    revision: str = Field(min_length=1)
    models: list[ModelSummary] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)
    reports: list[Report] = Field(default_factory=list)
    sources: list[SourceContext] = Field(default_factory=list)
    case_id: UUID | None = None
    score_id: UUID | None = None
    queue_version: UUID | None = None
    baseline: Assessment | None = None
    corrected: Assessment | None = None
    entered_count: Nonnegative | None = None
    left_count: Nonnegative | None = None
    decision: DeploymentDecision | None = None
    decision_record_id: UUID | None = None
    metrics: list[PilotMetric] = Field(default_factory=list)
