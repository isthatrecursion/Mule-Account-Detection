# Fraud Intelligence System: Explainable Mule Account Detection

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![LightGBM](https://img.shields.io/badge/Model-LightGBM%20Ensemble-brightgreen.svg)](https://lightgbm.readthedocs.io/)
[![Git LFS](https://img.shields.io/badge/Storage-Git%20LFS-orange.svg)](https://git-lfs.github.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An institutional, end-to-end **Explainable Fraud Intelligence System** that identifies bank accounts used to receive and funnel illicit funds (**money mules**), prioritizing alerts for human investigators and generating **plain-English, legally defensible case intelligence briefs** for compliance and fraud operations.

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

Through a rigorous 7-stage, decision-driven Exploratory Data Analysis, we identified and quarantined fatal data traps:

### 1. Data Leakage Remediation (1,404 Columns Pruned)
* **Row-Order Sorting Trap (`Unnamed: 0`):** Rows 1–9,001 were non-mules; rows 9,002–9,082 were all mules. Monotonic row index permanently stripped (`EDA-002`).
* **Extraction Batch Leak (`F2230`):** 100% of non-mules originated from an `Oct25` extraction, while 100% of confirmed mules came from `Sep25`, `Nov25`, and `Dec25`. Naive models memorized the batch month rather than fraud behavior. Permanently quarantined (`EDA-003`).
* **Post-Outcome Administrative Tag Proxy (`F3912`):** Exhibited 99.94% agreement with the target ($r = 0.969$). An autopsy of 5 mismatch cases confirmed it was an internal administrative hold/freeze tag. Blacklisted to prevent target leakage (`EDA-012`).
* **September Schema Artifacts (`F3287`, `F3290`, `F3611`, `F3614`):** Features populated exclusively in the September fraud query. Blacklisted (`EDA-018`).
* **Active Clean Feature Space:** Pruning 393 zero-variance and 1,011 duplicate columns established an active space of **2,521 clean features** (`EDA-023`).

### 2. Dissecting the Money Mule Typology
* **Pass-Through / Zero-Reserve Liquidation:** Legitimate accounts maintain median holding reserves of **840,459** (`F3811`). Confirmed mules hold median reserves of only **135,589** ($p = 2.3 \times 10^{-19}$). Stolen funds are not stored; they are liquidated within minutes.
* **Elevated Liquidation Concentration:** Ratios `F156`, `F264`, and `F261` reach **median 1.00 in mules** (100% electronic redirection) vs. 0.33–0.60 in legitimate accounts ($AUC = 0.78$–$0.79$).
* **Orthogonal Dimensions ($r = 0.000$):** Reserve Depletion and Outflow Velocity have zero correlation with each other, providing the mathematical foundation for multi-factor legal reasoning.
* **Demographic Gateway:** Students exhibit a **2.06% mule rate** (over **2.3x higher** than the 0.89% population baseline; $\chi^2 = 20.24, p = 0.0025$), reflecting global criminal recruitment typologies.

---

## 📊 Empirical Baseline Performance Scorecard

Evaluated under strict **5-Fold Stratified Cross-Validation on the Development Set** (7,265 accounts) with all 1,404 leakage features eliminated:

```text
5-Fold Out-of-Fold Cross-Validation Performance:
================================================================================================================
Model Architecture                          ROC-AUC   PR-AUC (AP)   P@25    R@25    P@50    R@50    P@100   R@100
================================================================================================================
1. Random Uniform Ranking                   0.4929      0.0093      0.00%   0.0%    0.00%   0.0%    0.00%   0.0%
2. Domain Heuristic Rule (Savings+Student)  0.7118      0.0260      8.00%   3.1%    6.00%   4.6%    3.00%   4.6%
3. Regularized Logistic Regression (L2)     0.7573      0.0274      4.00%   1.5%    4.00%   3.1%    2.00%   3.1%
4. LightGBM Ensemble (Active Clean Space)   0.9579      0.7825     100.0%  38.5%   88.00%  67.7%   53.00%  81.5%
================================================================================================================
```

### Operational Fraud Operations Impact:
* **$K = 25$ Urgent Queue:** **100.0% Precision** (25 of 25 alerts are true confirmed mules; zero false alarms).
* **$K = 50$ Daily Queue:** **88.0% Precision** (44 confirmed mules, only 6 false alarms). **Catches 67.7% of all fraud in the bank within 50 daily investigations**.
* **$K = 100$ Weekly Audit:** **81.5% Recall** (captures 53 out of 65 mules).

---

## 📁 Repository Structure & Deliverables

```text
.
├── DataSet__1_.csv                             # Raw 111.14 MB dataset (Tracked via Git LFS)
├── .gitattributes                              # Git LFS configuration
├── .gitignore                                  # Python & environment ignore rules
├── README.md                                   # Project architecture & executive briefing
├── Mule_Account_Detection_Complete_EDA_Plan Grevix.md # Master EDA plan & governance specification
└── eda/
    ├── 00_dataset_inventory.md                 # Stage 0: Physical profile, dimensions & initial verification
    ├── 01_schema_and_feature_dictionary.csv    # Stage 1: Full 3,925-column taxonomy & dictionary
    ├── 01_data_understanding_and_structural_audit.md # Stage 1: Account grain, feature families & latency
    ├── holdout_split_indices.csv               # Stage 1: Protected 80/20 split (1,817 locked holdout accounts)
    ├── 02_label_and_cohort_audit.md            # Stage 2: Target verification, F2230/F3912 autopsies, demographics
    ├── 03_data_quality_report.md               # Stage 3: Missingness leakage, zero-variance, duplicate pruning
    ├── 04_distribution_and_association_report.md # Stage 4: Active space (2,521 features), skewness, zero-mass
    ├── 05_leakage_and_feature_exclusions.csv   # Stage 5: Master 1,404-column exclusion register
    ├── 05_bivariate_and_multivariate_analysis.md # Stage 5: 742 FDR significant predictors, pass-through mechanics
    ├── 06_domain_capabilities_and_data_gaps.md # Stage 6: Architecture boundaries, plain-English governance
    ├── 07_evaluation_protocol.md               # Stage 7: 5-fold CV scorecard, top-K review budgets, bootstrap CIs
    └── 08_eda_to_design_decisions.md           # Master Blueprint: 8 architectural answers & production design
```

---

## 🛡️ Explainability & Plain-English Intelligence Brief

The system couples **TreeSHAP** feature attribution with a verified banking metadata synthesizer to generate legally defensible case intelligence briefs:

```markdown
### 🚨 FRAUD INVESTIGATION BRIEF — HIGH-RISK MULE CANDIDATE
**Account ID:** 9046 | **Risk Rank:** #3 of 7,265 | **Calculated Risk:** 99.4th Percentile
**Primary Risk Profile:** RETAIL SAVINGS / STUDENT CONDUIT

1. Demographic & Gateway Factors:
   * 27-year-old student (F3891 = student, F3894 = 27), Retail Savings Account (F3886).
   * Seasoned account (F3889 = G365D, open > 1 year). Matches sleeper recruitment typology.
   * Standard bureau credit risk score band 600 (F3895 = 600).

2. Liquidation & Velocity Anomalies (Dimension 1):
   * Flow concentration metric F156 = 1.00 (100% electronic redirection of credits; 99th percentile).
   * Active digital channel flag F3909 = 1 (8.0x positive mule risk multiplier).

3. Holding Reserve Depletion (Dimension 2 - Orthogonal):
   * Holding balance metric F3811 = 84,210 (bottom 4th percentile of savings accounts; normal peer median = 603,500).
   * Overnight dwell time indicates rapid transit with near-zero capital retention.

Disposition Recommendation:
   * Multi-factor convergence verified across 3 orthogonal dimensions.
   * Place temporary 24-hour administrative debit hold; request source-of-funds verification.
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
```

---

## ⚖️ Governance & Compliance Standards
* **Leakage Prevention:** 1,404 columns permanently quarantined in `eda/05_leakage_and_feature_exclusions.csv`.
* **Ethical AI & Fairness:** Strict behavioral gates ensure no account is flagged on demographic identity alone (student false alert rate is bounded at **0.84%**).
* **Model Risk Management (SR 11-7):** 95% bootstrap confidence intervals reported for all operational review capacities.
* **Holdout Partition Protection:** 1,817 accounts locked in `eda/holdout_split_indices.csv` remain 100% untouched for final production validation.
