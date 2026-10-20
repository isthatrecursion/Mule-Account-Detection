"""Check Phase 0 specifications and synthetic examples; no runtime or data approval.

Requires Python 3.12 and PyYAML (the current audit environment provides it).
No financial input is opened. Later phases must implement/test actual services.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import platform
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = "tests/fixtures/phase0/specification_examples.json"
DOCS = [
    "docs/requirements_and_acceptance.md", "docs/identity_and_grain.md",
    "docs/review_workflow.md", "docs/performance_protocol.md", "docs/data_request.md",
    "docs/freshness_policy.md", "docs/acceptance/template.md", "docs/acceptance/phase0_readiness.md",
]
CONFIGS = [
    "config/permissions.yaml", "config/review_policy.yaml", "config/benchmarks.yaml",
    "config/evaluation_policy.yaml", "config/environments/research.yaml",
    "config/environments/qualified.yaml",
]
REGISTERS = ["docs/acceptance/index.csv", "docs/data_dependencies.csv"]
ROLES = {
    "project_owner", "fraud_operations", "analyst", "reviewer", "engineer", "operator",
    "auditor", "data_owner", "data_governance", "label_owner", "model_risk", "compliance", "security",
}
NAMESPACE = uuid.UUID("672c45ae-3a4d-4ab0-8d85-636c2c15c9ea")


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read_csv(path: str) -> list[dict[str, str]]:
    with (ROOT / path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def research_key(dataset_hash: str, reference: object) -> str:
    """Executable specification only, not the future ingestion adapter."""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", dataset_hash):
        raise ValueError("invalid SHA-256")
    if isinstance(reference, bool) or not re.fullmatch(r"[0-9]+", str(reference)):
        raise ValueError("invalid original row reference")
    return "research:" + str(uuid.uuid5(NAMESPACE, f"{dataset_hash.lower()}:{int(str(reference))}"))


def rank_example(scores: list[dict], k: int) -> tuple[list[dict], list[dict]]:
    """Reference arithmetic on synthetic rows; does not score a model."""
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("K must be a positive integer")
    if len({row["record_key"] for row in scores}) != len(scores):
        raise ValueError("duplicate record keys")
    if any(not math.isfinite(row["raw_score"]) for row in scores):
        raise ValueError("nonfinite score")
    ordered = sorted(scores, key=lambda row: (-row["raw_score"], row["record_key"]))
    count = len(ordered)
    ranked = [dict(row, rank=i, percentile=100 if count == 1 else 100 * (count - i) / (count - 1))
              for i, row in enumerate(ordered, 1)]
    return ranked, ranked[:k]


def time_value(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("timezone required")
    return parsed


def evaluation_errors(example: dict) -> set[str]:
    """Synthetic eligibility example for the future temporal evaluator."""
    errors: set[str] = set()
    windows = example["windows"]
    gap = example["feature_lookback_seconds"] + example["label_outcome_window_seconds"]
    groups: set[str] = set()
    previous_end = None
    for window in windows:
        start, end = time_value(window["start"]), time_value(window["end"])
        if end <= start:
            errors.add("WINDOW_ORDER")
        if previous_end is not None and (start - previous_end).total_seconds() < gap:
            errors.add("OVERLAP_OR_PURGE")
        if groups.intersection(window["groups"]):
            errors.add("SHARED_GROUP")
        groups.update(window["groups"])
        previous_end = end
    if time_value(example["labels_released_at"]) <= time_value(example["freeze_at"]):
        errors.add("PRE_FREEZE_RELEASE")
    if example["inspection_history"]:
        errors.add("EXPOSED_ACCEPTANCE")
    return errors


def qualified_example(policy: dict, record: dict) -> bool:
    """Reference predicate reads authoritative record fields, never display aliases."""
    return bool(
        record["validated_source_contract"]
        and record["data_tier"] in policy["allowed_data_tiers"]
        and record["model_tier"] in policy["allowed_model_tiers"]
        and record["critical_dependencies_open"] == 0
        and record["representative_acceptance"]
        and record["trainer_id"] != record["approver_id"]
        and record["approval_scope"] in ("shadow", "pilot")
    )


def validate() -> list[dict]:
    checks: list[dict] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append({"check": name, "result": "PASSED" if condition else "FAILED", "detail": detail})

    def rejects(name: str, operation) -> None:
        try:
            operation()
        except (ValueError, TypeError):
            check(name, True)
        else:
            check(name, False, "invalid example accepted")

    for path in DOCS + CONFIGS + REGISTERS + [FIXTURE, "docs/acceptance/roadmap_status.csv"]:
        check(f"artifact:{path}", (ROOT / path).is_file())
    if any(item["result"] == "FAILED" for item in checks):
        return checks
    configs = {path: yaml.safe_load((ROOT / path).read_text(encoding="utf-8")) for path in CONFIGS}
    fixture = json.loads((ROOT / FIXTURE).read_text(encoding="utf-8"))
    requirements = read_csv(REGISTERS[0])
    dependencies = read_csv(REGISTERS[1])
    roadmap = (ROOT / "System Architecture Roadmap.md").read_text(encoding="utf-8")
    valid_points = set(re.findall(r"^### (P\d{2}\.\d{2})", roadmap, re.MULTILINE))
    requirement_ids = [row["requirement_id"] for row in requirements]
    check("register:unique_ids", len(requirement_ids) == len(set(requirement_ids)))
    required_fields = {"requirement_id", "requirement", "architecture_section", "owner_role",
                       "implementation_point", "test_id", "expected", "evidence_path", "status"}
    for row in requirements:
        rid = row["requirement_id"]
        check(f"register:{rid}", required_fields <= row.keys()
              and all(row.get(field) for field in required_fields)
              and row["owner_role"] in ROLES and row["status"] == "PLANNED"
              and set(row["implementation_point"].split(";")) <= valid_points
              and bool(re.fullmatch(r"REQ-[A-Z]+-\d{3}", rid)),
              "Product requirement remains planned with owner, observable check and valid roadmap mapping")
    check("register:unique_tests", len({row["test_id"] for row in requirements}) == len(requirements))
    for number in range(1, 13):
        criterion = f"AC-{number:02d}"
        check(f"acceptance:{criterion}", any(criterion in row["acceptance_criteria"].split(";") for row in requirements))
        check(f"acceptance:explicit_source_{number}", any(row["architecture_section"] == f"11 / {number}" for row in requirements))
    for number in range(1, 13):
        check(f"functional:source_{number}", any(row["architecture_section"] == f"1 / Functional requirements / {number}" for row in requirements))
    check("register:eight_nfr", sum(row["requirement_id"].startswith("REQ-NFR-") for row in requirements) == 8)
    check("register:eight_shared_invariants", sum(row["requirement_id"].startswith("REQ-INV-") for row in requirements) == 8)

    dep_ids = [row["dependency_id"] for row in dependencies]
    check("dependencies:unique", len(dep_ids) == len(set(dep_ids)))
    request_text = (ROOT / "docs/data_request.md").read_text(encoding="utf-8")
    for row in dependencies:
        anchor = row["fixture_path"].split("#", 1)[1]
        check(f"dependency:{row['dependency_id']}", row["owner_role"] in ROLES
              and row["provider_role"] in ROLES and row["provider_name"] == "UNKNOWN"
              and row["status"] == "OPEN" and row["supplied_evidence"] == "NOT_SUPPLIED"
              and row["validation_evidence"] == "NOT_RUN" and row["owner_approval"] == "PENDING"
              and all(row[field] for field in ("required_columns", "sample_format", "acceptance_validator", "implementation_gate", "impact_if_absent"))
              and anchor in fixture and "acceptable" in fixture[anchor] and "reject" in fixture[anchor]
              and row["dependency_id"] in request_text)
    check("dependencies:seven_core_requests", {"identity", "snapshot cutoff", "feature availability", "certified dictionary", "label definition maturity", "mixed-class time periods", "transaction completeness"} <= {row["category"] for row in dependencies})

    identity = fixture["research_identity"]
    base = research_key(identity["dataset_sha256"], identity["row_reference"])
    check("identity:retry", base == research_key(identity["dataset_sha256"], identity["row_reference"]))
    check("identity:canonical_reference", base == research_key(identity["dataset_sha256"].upper(), identity["equivalent_row_reference"]))
    check("identity:dataset_namespace", base != research_key(identity["other_dataset_sha256"], identity["row_reference"]))
    for value in (-1, True, "4.2", "", " row42"):
        rejects(f"identity:reject:{value!r}", lambda value=value: research_key(identity["dataset_sha256"], value))
    rejects("identity:reject_bad_digest", lambda: research_key("invalid", 42))

    review = configs["config/review_policy.yaml"]
    example = fixture["queue_examples"]
    ordered, queue = rank_example(example["scores"], example["top_k"])
    check("queue:ties", [row["record_key"] for row in ordered] == example["expected_keys"])
    check("queue:percentiles", [row["percentile"] for row in ordered] == example["expected_percentiles"])
    check("queue:top_k", [row["record_key"] for row in queue] == example["expected_top"])
    check("queue:empty", rank_example([], 50) == ([], []))
    check("queue:singleton", rank_example([example["scores"][0]], 50)[0][0]["percentile"] == 100)
    check("queue:K_does_not_change_scores", rank_example(example["scores"], 1)[0] == ordered)
    for value in (0, -1, True):
        rejects(f"queue:invalid_K:{value}", lambda value=value: rank_example(example["scores"], value))
    rejects("queue:duplicate", lambda: rank_example([example["scores"][0]] * 2, 50))
    rejects("queue:nonfinite", lambda: rank_example([{"record_key": "x", "raw_score": float("nan")}], 50))
    check("queue:configuration", review["top_k"] == 50 and review["qualified_top_k"] is None
          and review["sort"] == ["raw_score_desc", "record_key_asc"]
          and review["percentile"]["formula"] == "100 * (N - rank) / (N - 1)"
          and review["percentile"]["singleton"] == 100 and review["percentile"]["empty"] == "no_values"
          and review["eligible_snapshot_contract"]["exclude_internal_holdout"]
          and not review["top_k_change_requires_rescoring"] and review["policy_change_requires_new_version"])

    permissions = configs["config/permissions.yaml"]
    expected_grants = {
        "analyst": {"queue:read", "case:assign", "case:review"},
        "reviewer": {"queue:read", "case:assign", "case:review", "case:reopen", "export:create", "model:approve", "audit:read"},
        "engineer": {"model:train"}, "operator": {"job:retry"}, "auditor": {"audit:read"},
    }
    check("permissions:deny_default", permissions["default"] == "deny")
    check("permissions:roles", set(permissions["roles"]) == set(expected_grants))
    for action in permissions["permissions"]:
        allowed = [role for role, grants in expected_grants.items() if action in grants]
        denied = [role for role, grants in expected_grants.items() if action not in grants]
        check(f"permissions:{action}:allowed", bool(allowed) and action in permissions["roles"][allowed[0]])
        check(f"permissions:{action}:denied", bool(denied) and action not in permissions["roles"][denied[0]])
    for role, grants in expected_grants.items():
        check(f"permissions:exact:{role}", set(permissions["roles"][role]) == grants)
    constraints = permissions["constraints"]
    check("permissions:independence_and_override", constraints["model_approval_requires_independent_actor"]
          and constraints["combined_roles_do_not_bypass_self_approval_denial"]
          and not constraints["operator_case_note_access"]
          and set(constraints["overrides_require"]) == {"actor_id", "authorized_role", "reason", "expected_version", "audit_event"})
    transitions = permissions["workflow"]["transitions"]
    expected_transitions = {
        ("QUEUED", "ASSIGNED"): ("case:assign", "ASSIGNED"),
        ("ASSIGNED", "IN_REVIEW"): ("case:review", "REVIEW_STARTED"),
        ("IN_REVIEW", "REVIEWED"): ("case:review", "REVIEW_SUBMITTED"),
        ("REVIEWED", "ASSIGNED"): ("case:reopen", "REOPENED"),
    }
    check("workflow:exact_transitions", {(t["from"], t["to"]): (t["permission"], t["event"]) for t in transitions} == expected_transitions)
    for transition in transitions:
        action = transition["permission"]
        check(f"workflow:{transition['event']}:allowed", action in permissions["roles"]["reviewer"])
        check(f"workflow:{transition['event']}:denied", action not in permissions["roles"]["operator"])
    check("workflow:skip_denied", ("QUEUED", "REVIEWED") not in expected_transitions)
    check("workflow:reopened_is_event", "REOPENED" not in permissions["workflow"]["states"])
    check("workflow:conclusion_separate", not permissions["workflow"]["conclusion_is_fraud_label"]
          and "NEEDS_MORE_INFORMATION" in permissions["workflow"]["conclusions"])

    research = configs["config/environments/research.yaml"]
    qualified = configs["config/environments/qualified.yaml"]
    check("tiers:research_only", research["allowed_model_tiers"] == ["research_demo"] and not research["qualified_promotion_allowed"])
    for policy in (research, qualified):
        check(f"tiers:{policy['environment']}:immutable_authority", not policy["tier_authority"]["dashboard_request_or_environment_override_allowed"]
              and not policy["internal_holdout_allowed"] and not policy["automatic_account_action_enabled"])
    record = {"validated_source_contract": True, "data_tier": "qualified", "model_tier": "approved_for_shadow",
              "critical_dependencies_open": 0, "representative_acceptance": True,
              "trainer_id": "engineer-a", "approver_id": "reviewer-b", "approval_scope": "shadow"}
    check("tiers:qualified_example", qualified_example(qualified, record))
    for name, change in {
        "research_bundle": {"model_tier": "research_demo", "alias": "production", "environment_override": "qualified"},
        "research_data": {"data_tier": "research"}, "critical_dependency": {"critical_dependencies_open": 1},
        "self_approval": {"approver_id": "engineer-a"}, "no_source": {"validated_source_contract": False},
        "no_acceptance": {"representative_acceptance": False}, "no_scope": {"approval_scope": None},
    }.items():
        check(f"tiers:reject:{name}", not qualified_example(qualified, dict(record, **change)))
    predicate = qualified["approval_predicate"]
    check("tiers:approval_policy", predicate["all_critical_dependencies_closed"]
          and predicate["independent_approver_required"] and not predicate["self_approval_allowed"]
          and not predicate["research_bundle_allowed"] and not predicate["alias_change_implies_qualification"]
          and not predicate["application_deployment_implies_model_approval"])

    # Source evidence, not a timeout or a dictionary label, determines completeness.
    complete = fixture["completeness"]["acceptable"]
    def complete_example(value: dict) -> bool:
        sequences = value["received_sequences"]
        return (sequences == list(range(1, value["committed_sequence"] + 1))
                and len(sequences) == value["expected_count"]
                and value.get("heartbeat_at") is not None
                and time_value(value["watermark"]) >= time_value(value["window_end"]))
    check("completeness:valid_example", complete_example(complete))
    for name, change in {
        "gap": {"received_sequences": [1, 3]}, "count": {"expected_count": 4},
        "heartbeat": {"heartbeat_at": None}, "watermark": {"watermark": "2026-01-01T00:02:00Z"},
    }.items():
        check(f"completeness:reject:{name}", not complete_example(dict(complete, **change)))

    unavailable = fixture["unavailable"]
    check("freshness:outage_new_account", all(unavailable[field] is None for field in
          ("raw_score", "rank", "percentile", "assessed_as_of", "published_at"))
          and unavailable["freshness"] == "UNAVAILABLE" and unavailable["completeness"] == "UNKNOWN")
    freshness_doc = (ROOT / "docs/freshness_policy.md").read_text(encoding="utf-8")
    check("freshness:all_terms", all(term in freshness_doc for term in
          ("COMPLETE", "BUFFERING", "PROVISIONAL_HIGHER", "RECONCILED", "STALE", "CORRECTED", "UNAVAILABLE")))

    evaluation = configs["config/evaluation_policy.yaml"]
    check("evaluation:no_invented_dates", all(value is None for window in evaluation["windows"].values() for value in window.values()))
    check("evaluation:unknown_blocks", evaluation["unresolved_window_behavior"] == "block_qualified_evaluation"
          and evaluation["groups"]["remove_cross_partition_connected_groups"]
          and not evaluation["acceptance_release"]["reused_or_inspected_cohort_allowed_as_untouched"])
    good = fixture["evaluation"]
    check("evaluation:valid_synthetic", not evaluation_errors(good))
    for name, expected in [("overlap", "OVERLAP_OR_PURGE"), ("shared_group", "SHARED_GROUP"),
                           ("reused_release", "EXPOSED_ACCEPTANCE"), ("early_release", "PRE_FREEZE_RELEASE")]:
        bad = copy.deepcopy(good)
        if name == "overlap":
            bad["windows"][1]["start"] = bad["windows"][0]["start"]
        elif name == "shared_group":
            bad["windows"][1]["groups"] = bad["windows"][0]["groups"]
        elif name == "reused_release":
            bad["inspection_history"] = ["synthetic prior inspection"]
        else:
            bad["labels_released_at"] = bad["freeze_at"]
        check(f"evaluation:reject:{name}", expected in evaluation_errors(bad))
    label = fixture["labels"]["acceptable"]
    for window in good["windows"]:
        as_of = time_value(window["label_as_of"])
        # Both maturity and availability must precede the partition's label cutoff.
        mature = time_value(label["label_mature_at"]) <= as_of and time_value(label["label_available_at"]) <= as_of
        check(f"evaluation:maturity:{window['name']}", mature == (window["name"] != "train"))
    rejects("evaluation:naive_time", lambda: time_value("2026-01-01T00:00:00"))

    benchmarks = configs["config/benchmarks.yaml"]
    check("benchmarks:four_scenarios", set(benchmarks["scenarios"]) == {"batch_10k", "capacity_100k", "api_reads", "reconciliation_with_dashboard"})
    for name, scenario in benchmarks["scenarios"].items():
        check(f"benchmarks:{name}:design_only", scenario["observed"] is None
              and scenario["start_event"] and scenario["stop_event"] and scenario["expected"]
              and scenario["eligible_rows"] == scenario["rows"])
    scenarios = benchmarks["scenarios"]
    check("benchmarks:architecture_limits", scenarios["batch_10k"]["expected"]["wall_seconds_lt"] == 900
          and scenarios["api_reads"]["expected"]["per_endpoint_p95_ms_lt"] == 500
          and scenarios["capacity_100k"]["rows"] == 100000)
    delay = scenarios["reconciliation_with_dashboard"]
    check("benchmarks:delay_gates", delay["expected"] == {
        "assessment_consistency_gte": 0.95, "top_k_overlap_gte": 0.95,
        "affected_p95_compute_overhead_lte": 0.05, "unaffected_p95_regression_lte": 0.05,
        "duplicate_or_lost_events": 0, "partial_data_downgrades": 0,
        "corrected_lineage_fraction": 1.0, "event_to_publication_p95_seconds_lte": 660,
        "per_endpoint_api_p95_ms_lt": 500,
    } and delay["injected_delay_seconds"] == 600 and delay["recovery_scan_seconds"] == 60)
    check("benchmarks:provenance_required", {"hardware_fingerprint", "input_hash", "config_hash", "code_revision"}
          <= set(benchmarks["reference_hardware"]["required_at_run"])
          and benchmarks["common"]["missing_fingerprint_behavior"] == "invalid_run"
          and benchmarks["data_policy"] == "synthetic_only_in_CI")
    template = (ROOT / "docs/acceptance/template.md").read_text(encoding="utf-8")
    check("evidence:template_fields", all(field in template for field in (
        "requirement_id", "build_revision", "input_hash", "config_hash", "environment", "executed_command",
        "observed", "expected", "pass_fail", "evidence_link", "reviewer", "NOT_RUN", "BLOCKED", "EXAMPLE_ONLY")))
    status = read_csv("docs/acceptance/roadmap_status.csv")
    check("roadmap:all_points", {row["point_id"] for row in status} == valid_points and len(status) == len(valid_points))
    check("roadmap:ten_phase0_points", sum(row["point_id"].startswith("P00.") for row in status) == 10)
    check("roadmap:unbuilt_points_planned", all(
        (row["status"] == "PLANNED" and row["result"] == "NOT_RUN")
        or (row["status"] in {"IN_PROGRESS", "PASSED", "FAILED", "BLOCKED", "NOT_RUN"}
            and row["evidence_path"] != "NOT_RUN"
            and (ROOT / row["evidence_path"]).is_file())
        for row in status if not row["point_id"].startswith("P00.")))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="New immutable evidence directory under this repository")
    args = parser.parse_args()
    destination = None
    if args.output_dir:
        destination = args.output_dir.resolve()
        if not destination.is_relative_to(ROOT / "artifacts" / "phase0"):
            parser.error("output-dir must be under artifacts/phase0")
        if destination.exists():
            parser.error("output-dir already exists; select a new run ID")
    try:
        checks = validate()
    except (KeyError, ValueError, TypeError, OSError, yaml.YAMLError) as error:
        checks = [{"check": "specification_load", "result": "FAILED", "detail": str(error)}]
    passed = all(item["result"] == "PASSED" for item in checks)
    sources = DOCS + CONFIGS + REGISTERS + [FIXTURE, "scripts/validate_phase0.py",
        "architecture/01_system_architecture.md", "System Architecture Roadmap.md",
        "docs/phase_by_phase_build_plan.md", "eda/09_pre_architecture_verification_and_remediation.md"]
    hashes = {path: digest(ROOT / path) for path in sorted(sources) if (ROOT / path).is_file()}
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False)
    state = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=False)
    config_hashes = {path: hashes[path] for path in CONFIGS if path in hashes}
    report = {
        "scope": "Phase 0 specification checks and synthetic reference examples only; NOT runtime enforcement, performance measurement, external data validation, or human approval",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "executed_command": subprocess.list2cmdline([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]),
        "build_revision": git.stdout.strip() if git.returncode == 0 else "UNKNOWN",
        "working_tree_dirty": bool(state.stdout.strip()) if state.returncode == 0 else "UNKNOWN",
        "source_manifest_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
        "input_hash": hashes.get(FIXTURE, "MISSING"),
        "config_hash": hashlib.sha256(json.dumps(config_hashes, sort_keys=True).encode()).hexdigest(),
        "environment": {"python": sys.version, "platform": platform.platform(), "PyYAML": yaml.__version__},
        "expected": "All Phase 0 specification checks pass; product requirements remain PLANNED; dependencies remain OPEN; approval PENDING",
        "observed": {"checks": len(checks), "passed": sum(item["result"] == "PASSED" for item in checks)},
        "pass_fail": "PASSED" if passed else "FAILED", "reviewer": "PENDING_OWNER_REVIEW",
        "approval": "PENDING", "source_hashes": hashes, "checks": checks,
    }
    if destination:
        destination.mkdir(parents=True, exist_ok=False)
        report_path = destination / "report.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (destination / "manifest.json").write_text(json.dumps({"report.json": digest(report_path)}, indent=2) + "\n", encoding="utf-8")
        print(f"Evidence: {report_path}")
    print(f"{report['pass_fail']}: {report['observed']['passed']}/{len(checks)} specification checks")
    for item in checks:
        if item["result"] == "FAILED":
            print(f"FAILED: {item['check']}: {item['detail']}")
    print("Runtime acceptance NOT_RUN. External dependencies OPEN. Human approval PENDING.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
