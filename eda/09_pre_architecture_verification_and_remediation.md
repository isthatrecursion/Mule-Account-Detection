# Pre-Architecture Verification and Remediation Gate

**Project:** Explainable Mule Account Detection

**Status:** Architecture-ready for a controlled prototype; production validation blocked by data provenance and cohort design

**Date:** 2026-10-11

**Authority:** This document supersedes conflicting readiness, holdout, feature-semantics, and operational claims in Stages 0–8.

## 1. Decision

The repository is ready to proceed to **prototype architecture and implementation** with strict validation gates. It is not yet evidence for production fraud decisions.

The reason is structural and cannot be fixed by another random split or by dropping a few more columns: `F2230` shows that all 9,001 negative examples come from `Oct25`, while all 81 positive examples come from `Sep25`, `Nov25`, or `Dec25`. There is no extraction month containing both classes. Consequently, this dataset cannot identify whether a feature difference is caused by mule behavior, extraction month, source-query differences, or case-selection procedures.

The architecture may be built now, but promotion beyond a controlled prototype requires a representative dataset containing both positive and negative outcomes within the same time windows.

## 2. Verified repository facts

The automated check in `scripts/pre_architecture_verification.py` verifies:

| Check | Result |
|---|---:|
| Rows / columns | 9,082 / 3,925 |
| Labels | 9,001 negative / 81 positive |
| Registered exclusions | 1,404 unique, valid columns |
| Registered active columns | 2,521 |
| Development partition | 7,265 rows / 65 positives |
| Internal holdout partition | 1,817 rows / 16 positives |
| Months containing both classes | **0** |
| Retained features with missingness gap >= 10 percentage points | 504 |
| Retained features with missingness gap >= 25 percentage points | 36 |
| Retained features absent for every development positive | 27 |
| Largest retained-feature missingness gap | 34.08 percentage points |

The last four results are cohort-risk indicators. They do not prove that all listed columns leak the target, and they do not prove that any are genuine behavioral signals. Perfect month/target confounding makes those hypotheses observationally indistinguishable here.

## 3. Resolution of the pending issues

| Issue | Resolution | Architecture rule | Closure condition |
|---|---|---|---|
| Hidden cohort leakage | Treat the entire current sample as confounded. Keep the existing hard blacklist and monitor all retained features, but do not call the remaining space leakage-free. | A dataset gate rejects model promotion when no time cohort contains both classes; drift and missingness reports are mandatory. | Obtain same-window positives and negatives, plus feature provenance and availability timestamps. |
| Feature-definition conflicts | Raw values settle representation: `F3886` contains product labels such as `Savings`; `F3893` contains `RETAIL`/`CORPORATE`. Their source-system meanings remain provisional. | Explanations show raw value, feature ID, percentile, and dictionary status. Business labels require an approved catalog mapping. | Data owner signs a dictionary containing definition, unit, source, calculation window, and scoring-time availability. |
| CV reproducibility | Added a deterministic five-fold, development-only benchmark with saved out-of-fold predictions and explicit parameters. | Every experiment saves configuration, fold assignment, selected columns, predictions, metrics, dependency versions, and data hash. | CI reruns the benchmark within a documented tolerance. |
| Feature selection inside CV | Structural selection, imputation, encoding, and date/age cleanup are fitted independently on each training fold in the verification script. | Any target-aware selection must also live inside the fold pipeline. The FDR list in Stage 5 is exploratory and cannot be pre-applied to validation folds. | Pipeline tests show that validation rows and labels are unavailable to every fitted transformer. |
| Holdout isolation | The saved 20% split is reclassified as an **internal reference holdout**. Dataset-wide inspection and prior reporting mean it is not a pristine production acceptance set. It remains unscored by the new verification script. | Never tune against this split. Use a new later-period external acceptance set for the production gate. | Acquire and freeze a future, representative cohort before any target-aware analysis. |
| Account identity | Demographic uniqueness does not establish account identity. Row grain is treated as an assumption. | Ingestion requires a stable pseudonymous `account_id`; split logic groups all records for one account and related entities. | Data owner confirms entity key, snapshot grain, and duplicate/reissue semantics. |
| Operational claims | Precision@K values are historical development-ranking diagnostics. They do not define daily volume, staffing, investigation yield, or bank-wide fraud capture. | Queue size and threshold are configuration supplied by Fraud Operations and validated prospectively. | Operations supplies capacity, service-level target, investigation outcome definition, and cost matrix. |
| Explainability and actions | Pearson correlation near zero means only low measured linear association. It does not prove independence, causality, or legal sufficiency. | SHAP explains model behavior, not why fraud occurred. The system may recommend review; it cannot automatically freeze, block, file a SAR, or assert criminal conduct. | Compliance approves explanation vocabulary and a human decision workflow. |
| Fairness | Existing subgroup rates are exploratory and too small/confounded to certify fairness. | Sensitive and proxy attributes are reported separately; policy-critical actions require human review and prospective disparity monitoring. | Legal/compliance defines lawful attributes, thresholds, sample-size rules, and remediation policy. |
| Label validity | `F3924` behaves as the binary target in this extract, but label definition, event time, maturity, and false-negative process are absent. | Training contracts require label source, label timestamp, observation cutoff, and maturity window. | Label owner signs the label specification and supplies adjudication outcomes. |

## 4. Reproducible development diagnostic

Run:

```powershell
python scripts\pre_architecture_verification.py --benchmark
```

The current implementation produced the following development-only out-of-fold results:

| Metric | Result |
|---|---:|
| ROC-AUC | 0.9742 |
| Average precision | 0.8515 |
| Precision / recall at 25 | 1.000 / 0.3846 |
| Precision / recall at 50 | 0.960 / 0.7385 |
| Precision / recall at 100 | 0.540 / 0.8308 |

These numbers reproduce a deterministic pipeline; they do **not** validate real-world mule detection. The same batch structure is present in every random fold. Fold average precision ranges from 0.7090 to 0.9685, which also shows substantial instability from only 13 positive validation examples per fold.

The run writes:

- `artifacts/pre_architecture_verification/verification_report.json`
- `artifacts/pre_architecture_verification/oof_predictions.csv`
- `artifacts/pre_architecture_verification/residual_cohort_risk.csv`
- `artifacts/pre_architecture_verification/fold_feature_manifests.json`

The earlier `0.7825` average precision and `88%` Precision@50 remain legacy reported values because their original code, predictions, and complete configuration are absent. They are not the canonical reproducible benchmark.

## 5. Architecture invariants

The next architecture must enforce these rules:

1. **Data contract first:** schema version, stable account key, snapshot timestamp, feature event-time cutoff, label timestamp, label maturity, and provenance are required fields.
2. **Temporal separation:** training, calibration, and acceptance use non-overlapping time periods. Repeated accounts and linked entities cannot cross partitions.
3. **Fold-safe training:** preprocessing, feature discovery, selection, encoding, imputation, calibration, and threshold selection fit only on training data.
4. **Two feature tiers:** catalog-approved fields may receive business descriptions; anonymous fields are displayed only as feature IDs, values, percentiles, and signed model contributions.
5. **Decision separation:** the model creates a ranked review queue. Analysts and bank policy own holds, restrictions, SAR decisions, and customer contact.
6. **Reproducibility:** every run records the data fingerprint, code revision, environment, parameters, splits, predictions, metrics, and model artifact.
7. **Monitoring:** schema drift, missingness drift, score drift, cohort performance, calibration, top-K yield, subgroup burden, and delayed-label performance are versioned.
8. **Fail closed:** unknown schema versions, missing provenance, unavailable required fields, or failed drift gates prevent automated scoring and route the batch for investigation.

## 6. Required data package for production validation

The minimum acceptable replacement or extension dataset must contain:

- a stable pseudonymous account identifier and snapshot timestamp;
- both mature positive and mature negative outcomes inside each evaluation window;
- label source, event date, adjudication status, and observation/maturity cutoff;
- feature definitions, units, source tables, aggregation windows, and availability times;
- repeated snapshots where temporal behavior is claimed;
- investigation outcomes for estimating operational precision and analyst burden;
- a later-period acceptance cohort untouched by EDA, tuning, and threshold selection.

Until this package exists, the correct product claim is: **a reproducible research prototype for ranking labels within a confounded retrospective extract**.

## 7. Architecture readiness

The project can now proceed to architecture with the following scope:

- ingestion and schema validation;
- versioned feature contracts and quarantine rules;
- fold-safe training and experiment tracking;
- risk ranking and analyst review workflow;
- evidence-limited explanations;
- monitoring and promotion gates;
- adapters for the future representative dataset.

Production model approval, automated account action, bank-wide recall claims, causal fraud narratives, and legal-sufficiency claims remain outside the evidence supported by this repository.
