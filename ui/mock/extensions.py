"""ASSUMPTION fixtures for extension agreements; never imported by normal runtime."""

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

from ui.mock.backend import fixture_case, fixture_evidence, identity


def assessment(case: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(case[key])
        for key in ("case_id", "score_id", "model_id", "queue_version", "score")
    } | {"facts": fixture_evidence(case)["facts"]}


def fixture_payloads(cases: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    gate = {
        "name": "Qualified predictive evidence",
        "state": "BLOCKED",
        "reasons": ["Qualified independent data and labels are unavailable."],
        "numerator": None,
        "denominator": None,
        "trials": 0,
    }
    result: dict[str, dict[str, Any]] = {
        "models": {
            "kind": "models",
            "revision": "synthetic-v1",
            "models": [
                {
                    "environment": "research",
                    "bundle_digest": "a" * 64,
                    "data_tier": "research",
                    "model_tier": "research_demo",
                    "approval_state": "RESEARCH_ONLY",
                    "requester": "fixture-requester",
                    "reviewer": "fixture-reviewer",
                    "gates": [gate],
                    "events": [
                        {"action": "deployment_decision", "outcome": "BLOCKED"},
                        {"action": "rollback", "outcome": "NOT_RUN"},
                    ],
                }
            ],
        },
        "proposals": {
            "kind": "proposals",
            "revision": "synthetic-v1",
            "proposals": [
                {
                    "proposal_id": identity("proposal"),
                    "trigger": "Synthetic source coverage change",
                    "status": "PROPOSED",
                    "supporting_report_ids": [identity("report")],
                }
            ],
        },
        "reports": {
            "kind": "reports",
            "revision": "synthetic-v1",
            "reports": [
                {
                    "report_id": identity("report"),
                    "scenario_fingerprint": "c" * 64,
                    "evidence_class": "SYNTHETIC_ENGINEERING",
                    "during_delay_disagreement": {
                        "name": "During-delay disagreement",
                        "state": "FAILED",
                        "reasons": ["Two comparisons disagreed during the simulated delay."],
                        "numerator": 2,
                        "denominator": 10,
                        "trials": 10,
                    },
                    "final_consistency": {
                        "name": "Final consistency",
                        "state": "PASSED",
                        "reasons": ["All synthetic final comparisons matched."],
                        "numerator": 10,
                        "denominator": 10,
                        "trials": 10,
                    },
                    "gates": [
                        gate,
                        {
                            "name": "Qualified recall",
                            "state": "NOT_RUN",
                            "reasons": ["No qualified outcome labels are available."],
                            "trials": 0,
                        },
                    ],
                }
            ],
        },
        "source-health": {
            "kind": "source-health",
            "revision": "synthetic-v1",
            "sources": [
                {
                    "source_id": "synthetic-source",
                    "oldest_open_gap_seconds": 300,
                    "pending_reconciliation": True,
                    "complete_through": "2026-10-31T06:00:00Z",
                }
            ],
        },
    }
    result["deployment-status"] = {
        "kind": "deployment-status",
        "revision": "synthetic-decision-v1",
        "decision": {
            "record_id": identity("deployment-decision"),
            "revision": "synthetic-decision-v1",
            "mode": "RESEARCH_DEMO",
            "data_tier": "research",
            "model_tier": "research_demo",
            "approved_by": "fixture-reviewer (synthetic illustration only)",
            "allowed_actions": ["Synthetic review", "Synthetic export", "Recommendations only"],
            "stopping_conditions": [
                "Stop on identity or scope mismatch.",
                "Stop on inconsistent evidence or missing provenance.",
            ],
            "blocking_dependencies": [
                "Qualified predictive use: independent qualified data and labels are unavailable.",
                "Shared deployment: organization identity settings are unavailable.",
            ],
        },
    }
    metrics = []
    for metric_id, name, numerator, denominator, population in (
        ("eligible", "Eligible records", 200, 200, "ELIGIBLE_POPULATION"),
        ("queued", "Queued records", 50, 200, "ELIGIBLE_POPULATION"),
        ("reviewed", "Reviewed cases", 12, 50, "REVIEWED_SAMPLE"),
        (
            "review_duration_seconds",
            "Total review seconds / completed reviews",
            1200,
            12,
            "REVIEWED_SAMPLE",
        ),
        ("reopen_rate", "Reopened / reviewed cases", 2, 12, "REVIEWED_SAMPLE"),
        (
            "adjudicated_yield",
            "Adjudicated positive outcomes / mature reviewed outcomes",
            None,
            0,
            "REVIEWED_SAMPLE",
        ),
        ("overturn_rate", "Overturned / mature adjudications", None, 0, "REVIEWED_SAMPLE"),
        ("label_coverage", "Mature labels / eligible records", 0, 200, "ELIGIBLE_POPULATION"),
    ):
        metrics.append(
            {
                "metric_id": metric_id,
                "name": name,
                "numerator": numerator,
                "denominator": denominator,
                "population": population,
                "labels_available": 0,
                "labels_eligible": 200,
                "outcome_maturity": "NOT_AVAILABLE",
                "state": "BLOCKED" if numerator is None else "PASSED",
                "reasons": ["Synthetic engineering illustration only."]
                + (
                    ["Qualified mature adjudicated labels are unavailable."]
                    if numerator is None
                    else []
                ),
                "freshness_counts": {"COMPLETE": 10, "STALE": 2} if metric_id == "reviewed" else {},
                "corrected_count": 1 if metric_id == "reviewed" else None,
            }
        )
    result["pilot-metrics"] = {
        "kind": "pilot-metrics",
        "revision": "synthetic-metrics-v1",
        "decision_record_id": identity("deployment-decision"),
        "metrics": metrics,
    }
    for case in cases.values():
        payload = {
            "kind": "case-context",
            "revision": "synthetic-v1",
            "case_id": case["case_id"],
            "score_id": case["score_id"],
            "sources": copy.deepcopy(result["source-health"]["sources"]),
        }
        if case["score"]["freshness"] == "PROVISIONAL_HIGHER":
            baseline = fixture_case(1)
            baseline["score_id"] = case["score"]["baseline_score_id"]
            baseline["score"]["raw_score"] = 0.5
            payload["baseline"] = assessment(baseline)
        result["case-context/" + case["case_id"]] = payload
    return result


class LateTimeline:
    """Publish immutable synthetic assessments over ten minutes; keep old reviews intact."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend
        self.start = datetime(2026, 10, 31, 6, tzinfo=UTC)
        self.now = self.start
        self.original_id = identity("case-1")
        self.current_id = self.original_id
        self.case_ids = [self.original_id]
        backend.cases[self.original_id]["score"]["raw_score"] = 0.6
        backend.queue_members[identity("queue")] = [self.original_id]
        self.baseline = assessment(backend.cases[self.original_id])

    def advance(self, stage: str) -> str:
        minutes = {
            "BUFFERING": 2,
            "STALE": 5,
            "PROVISIONAL_HIGHER": 7,
            "CORRECTED": 10,
            "RECONCILED": 10,
        }[stage]
        self.now = self.start + timedelta(minutes=minutes)
        case = copy.deepcopy(self.backend.cases[self.original_id])
        case.update(
            case_id=identity("late-case-" + stage),
            score_id=identity("late-score-" + stage),
            case_version=0,
            state="QUEUED",
            assignee=None,
            conclusion=None,
            newer_assessment_available=False,
            newer_score_id=None,
        )
        case["score"].update(
            freshness=stage if minutes < 10 else "COMPLETE",
            published_at=self.now.isoformat(),
            completeness="INCOMPLETE"
            if stage == "PROVISIONAL_HIGHER"
            else "UNKNOWN"
            if minutes < 10
            else "COMPLETE",
            raw_score=0.85 if stage == "PROVISIONAL_HIGHER" else 0.65 if minutes == 10 else 0.6,
        )
        if minutes == 10:
            case["score"].update(publication_event=stage)
        if stage == "PROVISIONAL_HIGHER":
            case["score"]["baseline_score_id"] = self.baseline["score_id"]
            for coverage in case["score"].get("source_coverage", []):
                coverage.update(
                    status="INCOMPLETE", received_count=190, sequence_gaps=10, complete_through=None
                )
        queue = self.backend.publish_queue([])
        case["queue_version"] = queue
        self.backend.cases[case["case_id"]] = case
        self.backend.queue_members[queue] = [case["case_id"]]
        for previous in self.case_ids:
            self.backend.cases[previous].update(
                newer_assessment_available=True, newer_score_id=case["score_id"]
            )
        self.case_ids.append(case["case_id"])
        self.current_id = case["case_id"]
        source = {
            "source_id": "synthetic-source",
            "oldest_open_gap_seconds": minutes * 60 if minutes < 10 else 0,
            "pending_reconciliation": minutes < 10,
            "complete_through": self.start.isoformat() if minutes < 10 else self.now.isoformat(),
        }
        context = {
            "kind": "case-context",
            "revision": "late-" + stage,
            "case_id": case["case_id"],
            "score_id": case["score_id"],
            "baseline": copy.deepcopy(self.baseline),
            "sources": [source],
        }
        if minutes == 10:
            context["corrected"] = assessment(case)
            for previous in self.case_ids[:-1]:
                prior = self.backend.extension_payloads.get("case-context/" + previous)
                if prior:
                    prior["baseline"] = copy.deepcopy(self.baseline)
                    prior["corrected"] = assessment(case)
                    prior["sources"] = [copy.deepcopy(source)]
        self.backend.extension_payloads["case-context/" + case["case_id"]] = context
        self.backend.extension_payloads["queue-context/" + queue] = {
            "kind": "queue-context",
            "revision": "late-" + stage,
            "queue_version": queue,
            "entered_count": 0,
            "left_count": 0,
        }
        for selected in self.case_ids:
            self.backend.score_histories[selected] = [
                {
                    "score_id": self.backend.cases[key]["score_id"],
                    "queue_version": self.backend.cases[key]["queue_version"],
                    "version": index + 1,
                    "model_id": case["model_id"],
                    "selected": key == selected,
                    **{
                        field: self.backend.cases[key]["score"].get(field)
                        for field in ("raw_score", "rank", "freshness", "assessed_as_of")
                    },
                }
                for index, key in enumerate(self.case_ids)
            ]
        return str(case["case_id"])
