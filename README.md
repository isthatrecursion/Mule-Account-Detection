# Fraud Intelligence System: Explainable Mule Account Detection

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![LightGBM](https://img.shields.io/badge/Model-LightGBM%20Ensemble-brightgreen.svg)](https://lightgbm.readthedocs.io/)
[![Git LFS](https://img.shields.io/badge/Storage-Git%20LFS-orange.svg)](https://git-lfs.github.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A research prototype for **explainable mule-account risk ranking**. It prioritizes accounts for human investigation and reports model evidence with explicit provenance and uncertainty boundaries.

> [!IMPORTANT]
> The current extract is retrospectively assembled: every negative is from `Oct25`, while every positive is from `Sep25`, `Nov25`, or `Dec25`. No month contains both classes. The dataset therefore cannot separate mule behavior from extraction-cohort effects, and results in this repository are development diagnostics rather than production performance. See [`eda/09_pre_architecture_verification_and_remediation.md`](eda/09_pre_architecture_verification_and_remediation.md).

---

## 📌 The Problem We Are Solving

Banks are drowning in transaction volume and losing the fight against financial crime for three specific reasons:
1. **Rule-Based Systems are Reactive:** Static threshold rules fail the moment fraudsters adjust behavior (e.g. splitting transfers across new counterparties or changing velocity).
2. **Manual Review Doesn't Scale:** Investigating 10,000 unranked alerts overwhelms compliance teams. Systems must surface the top 25–50 high-conviction accounts ranked by genuine risk.
3. **Black-Box Outputs are Legally Unusable:** A bank cannot freeze an account simply because *"the model output 0.94"*. Compliance, AML, and SAR filings legally require **multi-factor, plain-English justifications**.

### The Real-World Dataset Challenge
* **9,082 Accounts** monitored.
* **81 Confirmed Mules** vs. **9,001 Regular Accounts** (**111.12 : 1 extreme class imbalance**; $0.89\%$ positive prevalence).
* **3,924 High-Dimensional Features** with anonymized column headers.
* **Full of real-world traps:** Fatal collection-batch leakage, administrative tag proxies, and extraction artifacts.

---

## 🔍 Critical EDA Discoveries & Traps Averted

Through a decision-driven exploratory analysis, we identified known data traps and established a controlled prototype boundary:

### 1. Data Leakage Remediation (1,404 Columns Pruned)
* **Row-Order Sorting Trap (`Unnamed: 0`):** Rows 1–9,001 were non-mules; rows 9,002–9,082 were all mules. Monotonic row index permanently stripped (`EDA-002`).
* **Extraction Batch Leak (`F2230`):** 100% of non-mules originated from an `Oct25` extraction, while 100% of confirmed mules came from `Sep25`, `Nov25`, and `Dec25`. Naive models memorized the batch month rather than fraud behavior. Permanently quarantined (`EDA-003`).
* **Near-target proxy (`F3912`):** Exhibited 99.94% agreement with the target ($r = 0.969$). Its operational meaning is unverified, so it is conservatively blacklisted as a likely post-outcome field (`EDA-012`).
* **September Schema Artifacts (`F3287`, `F3290`, `F3611`, `F3614`):** Features populated exclusively in the September fraud query. Blacklisted (`EDA-018`).
* **Registered candidate space:** The sequential exclusion register leaves **2,521 candidate features**. An automated follow-up found substantial residual cohort risk, so this space must not be described as leakage-free.

### 2. Measured associations and interpretation limits
* `F3811` has a development-set median of **840,459** for negatives and **135,589** for positives. Its source-system meaning is not certified.
* `F156`, `F264`, and `F261` have median **1.00** among positives and lower medians among negatives. The values support a statistical contrast, not claims about electronic redirection or timing.
* Near-zero Pearson correlation between selected features indicates low measured linear association in this sample. It does not establish independence, causality, or legal sufficiency.
* Student status is associated with the sampled label, but month, case selection, and target are confounded. Demographic fields cannot independently trigger an alert or adverse action.

---

## 📊 Reproducible Development Diagnostic

The repository now includes a deterministic five-fold benchmark with preprocessing fitted separately inside every training fold. It saves out-of-fold predictions and never scores the internal holdout:

```text
5-Fold Out-of-Fold Cross-Validation Performance:
================================================================================================================
Model Architecture                          ROC-AUC   PR-AUC (AP)   P@25    R@25    P@50    R@50    P@100   R@100
================================================================================================================
Fold-safe LightGBM diagnostic               0.9742      0.8515     100.0%  38.5%   96.00%  73.8%   54.00%  83.1%
================================================================================================================
```

These are historical, out-of-fold ranking results within the confounded development sample. They do not establish future-period precision, daily analyst throughput, or bank-wide fraud capture. The previously reported AP `0.7825` and Precision@50 `88%` lack their original code and predictions and are retained only in historical EDA documents.

---

## 📁 Repository Structure & Deliverables

```text
.
├── DataSet__1_.csv                             # Raw 111.14 MB dataset (Tracked via Git LFS)
├── .gitattributes                              # Git LFS configuration
├── .gitignore                                  # Python & environment ignore rules
├── README.md                                   # Project architecture & executive briefing
├── Mule_Account_Detection_Complete_EDA_Plan Grevix.md # Master EDA plan & governance specification
├── architecture/
│   ├── 01_system_architecture.md               # Complete target architecture and scale-up design
│   ├── 02_complete_solution_14h_execution_plan.md # Capability-complete 13–14 hour build plan
│   └── 03_delayed_transaction_resilience.md    # 10-minute buffer, reconciliation and acceptance gates
├── eda/
    ├── 00_dataset_inventory.md                 # Stage 0: Physical profile, dimensions & initial verification
    ├── 01_schema_and_feature_dictionary.csv    # Stage 1: Full 3,925-column taxonomy & dictionary
    ├── 01_data_understanding_and_structural_audit.md # Stage 1: Account grain, feature families & latency
    ├── holdout_split_indices.csv               # Internal 80/20 reference split; not production acceptance
    ├── 02_label_and_cohort_audit.md            # Stage 2: Target verification, F2230/F3912 autopsies, demographics
    ├── 03_data_quality_report.md               # Stage 3: Missingness leakage, zero-variance, duplicate pruning
    ├── 04_distribution_and_association_report.md # Stage 4: Active space (2,521 features), skewness, zero-mass
    ├── 05_leakage_and_feature_exclusions.csv   # Stage 5: Master 1,404-column exclusion register
    ├── 05_bivariate_and_multivariate_analysis.md # Stage 5: 742 FDR significant predictors, pass-through mechanics
    ├── 06_domain_capabilities_and_data_gaps.md # Stage 6: Architecture boundaries, plain-English governance
    ├── 07_evaluation_protocol.md               # Stage 7: 5-fold CV scorecard, top-K review budgets, bootstrap CIs
    ├── 08_eda_to_design_decisions.md           # Historical synthesis; subject to Stage 9 gates
    └── 09_pre_architecture_verification_and_remediation.md # Authoritative readiness boundary
├── scripts/pre_architecture_verification.py    # Reproducible audit and fold-safe benchmark
└── artifacts/pre_architecture_verification/    # Saved audit, folds, metrics, and OOF scores
```

---

## 🛡️ Evidence-Limited Analyst Brief

The prototype may use SHAP to describe model behavior. Anonymous features remain anonymous until an approved source dictionary maps them to business concepts:

```markdown
### MODEL REVIEW BRIEF — HIGH PRIORITY RECORD
**Account ID:** 9046 | **Risk Rank:** #3 of 7,265 | **Calculated Risk:** 99.4th Percentile
**Output Type:** MODEL-GENERATED REVIEW PRIORITY

Observed inputs contributing to the score:
* F156 = 1.00; high positive model contribution; business definition unverified.
* F3811 = 84,210; low peer percentile; business definition unverified.
* F3886 = Savings and F3891 = student; raw categorical values observed in the extract; source definitions pending.

Required next step:
* Route to an authorized analyst for independent evidence review under bank policy.
* Do not infer transaction timing, counterparties, criminal intent, or a required account action from this score.
```

---

## 🚀 Getting Started & Git LFS Setup

### 1. Clone the Repository (with Git LFS)
Because the dataset is **111.14 MB**, Git LFS is required:
```bash
# Install Git LFS if not already installed
git lfs install

# Clone the repository
git clone https://github.com/isthatrecursion/Mule-Account-Detection.git
cd Mule-Account-Detection

# Pull the large dataset file
git lfs pull
```

### 2. Set Up Python Environment
```bash
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install pandas numpy scikit-learn lightgbm scipy

# Reproduce the structural audit and development-only benchmark
python scripts\pre_architecture_verification.py --benchmark
```

---

## ⚖️ Governance & Compliance Standards
* **Known exclusions:** 1,404 columns are cataloged in `eda/05_leakage_and_feature_exclusions.csv`; residual cohort confounding remains unresolved.
* **Fairness:** Demographic attributes cannot independently trigger an alert or adverse action. Prospective fairness validation is required on representative data.
* **Human authority:** The model ranks cases for review. Holds, restrictions, SAR filings, and customer actions remain human and policy decisions.
* **Validation:** The 1,817-row saved split is an internal reference holdout, not a production acceptance set. Production validation requires a new later-period cohort.
