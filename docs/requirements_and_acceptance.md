# Requirements and acceptance contract

Version: `phase0_v1` · Prepared: 2026-10-20 · Approval: **PENDING_OWNER_REVIEW**.

Design authority: [architecture](../architecture/01_system_architecture.md). Data authority: [Stage 9](../eda/09_pre_architecture_verification_and_remediation.md). Implementation procedure: [roadmap](<../System Architecture Roadmap.md>), P00.01–P00.10.

[The requirement register](acceptance/index.csv) is the normative traceability index. Each row has a stable ID, exact architecture section, accountable role, implementation point, planned test, observable expected behavior, evidence destination, and status. All product requirements start `PLANNED`. A successful Phase 0 document check does not pass a future service, ML, security, or deployment requirement. `AC-01`–`AC-12` identify the twelve final architecture criteria; the register links each to requirements and later implementation points.

## Accountable roles

| Role ID | Responsibility |
|---|---|
| project_owner | Scope, outstanding decisions and agreement to this contract |
| fraud_operations | Review capacity, queue service levels and operational outcome definitions |
| analyst | Assigned investigation and evidence review |
| reviewer | Review oversight, independent model approval where separately authorized |
| engineer | ML/software implementation and reproducibility |
| operator | Intake, jobs, infrastructure, deployment and recovery |
| auditor | Read authorized audit evidence and independently assess controls |
| data_owner | Source identity, cutoffs, provenance and completeness attestation |
| data_governance | Certified feature dictionary and vocabulary approval |
| label_owner | Adjudication, maturity and label corrections |
| model_risk | Independent validation, evaluation and model approval policy |
| compliance | Human decision boundary, lawful attributes and explanation policy |
| security | Access, privacy, retention, security and incident policy |

These are responsibility roles; only the five runtime roles in [permissions](../config/permissions.yaml) grant application actions. Assigned individuals/provider contacts remain `UNKNOWN` until supplied. A role name is not evidence of approval or a grant of permissions.

## Binding definitions

- Investigation: one record at one declared observation cutoff; see [identity and grain](identity_and_grain.md).
- Queue: descending raw score, ascending opaque record key, cohort-specific percentile; see [review policy](../config/review_policy.yaml).
- Human review state, conclusion, fraud label, model approval, ingestion/job state and freshness are separate fields. See [workflow](review_workflow.md) and [freshness](freshness_policy.md).
- Current data/model outputs remain research diagnostics. The 1,817 saved holdout rows are excluded from training, tuning, demo scoring and operational evaluation. A row reference is never a verified account identity or predictor.
- No automatic restriction, freeze, block, filing or customer action. Anonymous inputs receive statistical descriptions only; model contribution does not establish causation or criminal conduct.
- UTC timezone-aware persistence; explicit display timezone; half-open feature windows `[start,end)`. Missing events are not zero activity; missing scores are nullable and `UNAVAILABLE`.
- Application services own transactions, including their audit writes. Immutable publication manifests and atomic queue switches prevent readers observing partial results. Idempotency binds actor/operation/key to a canonical request hash.

## Acceptance and pending decisions

Use [the evidence template](acceptance/template.md). `NOT_RUN`, `BLOCKED`, `FAILED`, `PASSED`, and human approval are distinct. Every executed result needs command, source revision, input/config hashes, environment and evidence. Synthetic examples cannot approve real data or performance. Repeat checks after changing a rule; version policies rather than rewriting previous evidence.

Open dependencies and approval decisions are tracked in [data dependencies](data_dependencies.csv), including unknown queue capacity, qualified evaluation dates, ranking/fairness thresholds, retention, RPO/RTO and representative event data. Closure requires evidence, passing validation and authorized owner sign-off. Data requests are prepared locally; none has been sent to a provider.

Phase 0 implementation may be checked while business agreement remains pending. Proceeding with research engineering does not approve qualified operation. Later enforcement lives in the package/configuration/contracts phases; these policy documents alone are not runtime authorization controls.

Run `python scripts/validate_phase0.py` to check traceability, policy consistency and synthetic specification examples without reading the private dataset. Save a run with `python scripts/validate_phase0.py --output-dir artifacts/phase0/<new-run-id>`; existing run directories are rejected. [Roadmap status](acceptance/roadmap_status.csv) distinguishes completed specification checks from pending owner agreement.
