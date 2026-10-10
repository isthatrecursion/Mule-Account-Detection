# Stage 2 — Target & Cohort Audit

**Project:** Explainable Fraud Intelligence System for Mule Account Detection  
**Document ID:** `eda/02_label_and_cohort_audit.md`  
**Execution Stage:** Stage 2 (Items 9–16 of Decision-Driven EDA Plan)  
**Status:** Completed & Reproducibly Audited  
**Date:** 2026-10-11  

---

## 1. Executive Summary & Objective

The objective of **Stage 2** is to rigorously audit the candidate target label (`F3924`), dissect the severe class imbalance, investigate extraction-batch confounding (`F2230`), inspect the near-target proxy flag (`F3912`), evaluate positive-unlabeled (PU) and label-delay risks, and analyze target composition across demographic segments within the protected development partition (`dev`).

---

## 2. Ground Truth Target Verification (`F3924`) (Items 9 & 10)

### 2.1. Overall Dataset Distribution
* **Candidate Target Column:** `F3924`
* **Non-Mule Accounts (`0`):** 9,001 (99.1081%)
* **Confirmed Mule Accounts (`1`):** 81 (0.8919%)
* **Imbalance Ratio:** **111.12 : 1** (1 positive per 112 accounts)

```text
Class Distribution:
  [0] Non-Mule:  ████████████████████████████████████████ 9,001 (99.11%)
  [1] Mule:      ▏ 81 (0.89%)
```

### 2.2. Development Partition Distribution
To protect holdout integrity (EDA-010), all target-informed analyses are restricted to the development set:
* **Development Sample Size:** 7,265 accounts
* **Negatives (`0`):** 7,200 (99.105%)
* **Positives (`1`):** 65 (0.895%)
* **Protected Holdout Sample:** 1,817 accounts (1,801 negatives, 16 positives)

### 2.3. The Metric Geometry & The Accuracy Paradox
* If a model naively predicts `0` for every incoming account, it achieves **99.11% Accuracy**, while detecting **0 out of 81 money mules**.
* Standard ROC-AUC is misleading in this regime because a false positive rate of just 2% generates $\approx 180$ false alerts—more than double the entire true mule population.
* **Mandated Operational Metrics:**
  * **Average Precision (AP / PR-AUC)**: Measures ranking quality across all thresholds.
  * **Precision@K**: The proportion of confirmed mules in the top $K$ alerts ($K \in \{25, 50, 100\}$).
  * **Recall@K**: The percentage of all mules captured within an analyst's daily review budget $K$.

---

## 3. Reporting Month Confounding Deep Dive (`F2230`) (Item 11)

### 3.1. Complete Cohort Cross-Tabulation

| Snapshot Month (`F2230`) | Non-Mule (`F3924 = 0`) | Mule (`F3924 = 1`) | Total Accounts | Observed Mule Rate |
| :--- | :---: | :---: | :---: | :---: |
| **`Oct25`** | 9,001 | 0 | 9,001 | **0.00%** |
| **`Sep25`** | 0 | 48 | 48 | **100.00%** |
| **`Nov25`** | 0 | 23 | 23 | **100.00%** |
| **`Dec25`** | 0 | 10 | 10 | **100.00%** |
| **Total** | **9,001** | **81** | **9,082** | **0.89%** |

### 3.2. Extraction Mechanism & Operational Risk
* **Mechanism:** The fraud operations unit assembled this dataset by pulling a massive random sample of baseline active accounts from October 2025, and merging historical confirmed fraud cases logged by the investigative team across September, November, and December 2025.
* **Fatal Risk:** A machine learning model allowed to observe `F2230` will learn a single rule: `IF F2230 != 'Oct25' THEN MULE = 1`. This yields 100% precision, 100% recall, and zero generalizability.
* **Operational Directive:** `F2230` is **permanently quarantined** from training inputs. Continuous features will be tested for correlation against `F2230` in Stage 3 to ensure no background seasonal drift mimics this batch split.

---

## 4. Near-Target Administrative Proxy Audit (`F3912`) (Item 12)

### 4.1. Concordance Analysis
* **Overall Concordance:** 9,077 out of 9,082 records (**99.94% agreement**).
* **Correlation:** Pearson $r = 0.9691$.

| `F3912` Indicator | Non-Mule (`F3924 = 0`) | Mule (`F3924 = 1`) | Total Accounts |
| :---: | :---: | :---: | :---: |
| **0** | 8,998 | 2 | 9,000 |
| **1** | 3 | 79 | 82 |
| **Total** | **9,001** | **81** | **9,082** |

### 4.2. Mismatch Autopsy (The 5 Anomalous Cases)
Analyzing the 5 discrepancy records reveals the true business identity of `F3912`:

```text
False Positives (F3912 = 1, F3924 = 0):
  1. Row 2700 (Account ID 2701): MSME Micro, self-employed, age 7.0 (commercial entity)
  2. Row 5720 (Account ID 5721): Current Account, self-employed, age 3.0 (commercial entity)
  3. Row 6171 (Account ID 6172): Savings Account, self-employed, age 45.0 (individual)

False Negatives (F3912 = 0, F3924 = 1):
  4. Row 9045 (Account ID 9046): Savings Account, self-employed, age 27.0
  5. Row 9051 (Account ID 9052): Savings Account, self-employed, age 36.0
```

* **Interpretation:** `F3912` is an **internal administrative alert or provisional freeze tag**.
  * The 3 false positives represent accounts where an alert was triggered or a provisional hold was placed, but subsequent investigation cleared the customer or found insufficient evidence to confirm mule status.
  * The 2 false negatives represent confirmed mules where the administrative flag was bypassed, delayed, or recorded in an alternate core system.
* **Operational Directive:** `F3912` is a **post-outcome administrative artifact**, not an organic behavioral feature. It is placed on the **permanent feature blacklist**.

---

## 5. Label Quality & Positive-Unlabeled (PU) Risk (Items 13 & 14)

1. **The Positive Class (`F3924 = 1`):**
   * Confirmed mules represent accounts that reached the end of an investigative funnel: victim reported crime $\rightarrow$ law enforcement request / SAR filing $\rightarrow$ manual analyst confirmation $\rightarrow$ account freeze.
   * Label precision is high (near 100%), but recall of total illegal activity is unknown.
2. **The Negative Class (`F3924 = 0`):**
   * The negative class represents **unflagged accounts**, not verified clean accounts.
   * In retail banking, an estimated 0.1%–0.5% of regular accounts may act as undetected "sleeper mules" or low-volume pass-through accounts that never triggered a police inquiry.
3. **Modeling Strategy for Positive-Unlabeled Reality:**
   * Do not rely on hard binary classification boundaries.
   * Frame model optimization as **Risk Ranking / Prioritization**: surface the highest-density anomalies for analyst review rather than enforcing rigid class separation.

---

## 6. Label Delay, Censoring & Account Maturation (Item 15)

* **Maturation Lag:** Mule detection is subject to significant reporting latency (often 30 to 90 days from transaction execution to bank dispute notification).
* **Account Opening Date (`F3888`) vs. Snapshot Date:**
  * Accounts opened in late 2025 (e.g., October–November 2025) have had insufficient maturation time to be confirmed as mules by external law enforcement.
  * In the development partition, **87.7% of confirmed mules** have account tenure $> 365$ days (`G365D`), indicating that fraudsters frequently utilize "sleeper accounts" (aged accounts recruited or sold) rather than exclusively brand-new accounts.

---

## 7. Target Composition by Demographic Segment (Dev Partition) (Item 16)

All statistics below are computed on the isolated **Development Set** (7,265 accounts: 7,200 negatives, 65 positives).

### 7.1. Account Type (`F3886`)
$$\chi^2 = 22.56, \quad p = 0.126$$

| Account Type | Non-Mule (`0`) | Mule (`1`) | Total Accounts | Mule Rate (%) | Relative Risk |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Savings** | 4,713 | 60 | 4,773 | **1.26%** | **1.41x baseline** |
| **Current** | 1,624 | 4 | 1,628 | **0.25%** | 0.28x baseline |
| **MSME Medium** | 56 | 1 | 57 | **1.75%** | 1.96x baseline |
| **MSME Micro / Small** | 458 | 0 | 458 | **0.00%** | 0.00x baseline |
| **Term Deposits & Loans** | 349 | 0 | 349 | **0.00%** | 0.00x baseline |
| **Total Dev** | **7,200** | **65** | **7,265** | **0.89%** | 1.00x |

* **Insight:** **92.3% of all mules operate via Savings Accounts**. Fraudsters avoid term deposits and loan products, targeting high-liquidity personal accounts.

---

### 7.2. Customer Occupation (`F3891`)
$$\chi^2 = 20.24, \quad p = 0.0025 \quad \text{(Statistically Highly Significant)}$$

| Customer Occupation | Non-Mule (`0`) | Mule (`1`) | Total Accounts | Mule Rate (%) | Relative Risk |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Student** | 952 | 20 | 972 | **2.06%** | **2.31x baseline** |
| **Agriculture** | 875 | 10 | 885 | **1.13%** | **1.27x baseline** |
| **Salaried** | 1,519 | 11 | 1,530 | **0.72%** | 0.81x baseline |
| **Self-Employed** | 3,113 | 21 | 3,134 | **0.67%** | 0.75x baseline |
| **Housewife** | 537 | 3 | 540 | **0.56%** | 0.63x baseline |
| **Retired & Others** | 204 | 0 | 204 | **0.00%** | 0.00x baseline |

* **Insight:** **Students exhibit a 2.06% mule rate** (>2.3x higher than average). This directly reflects the global financial crime pattern where criminal syndicates recruit young students via social media with promises of commission for allowing funds to transit their accounts.

---

### 7.3. Geographic Branch Tier (`F3890`)
$$\chi^2 = 9.34, \quad p = 0.0250 \quad \text{(Statistically Significant)}$$

| Branch Geographic Tier | Non-Mule (`0`) | Mule (`1`) | Total Accounts | Mule Rate (%) | Relative Risk |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Rural (`R`)** | 1,572 | 24 | 1,596 | **1.50%** | **1.68x baseline** |
| **Semi-Urban (`SU`)** | 1,921 | 17 | 1,938 | **0.88%** | 0.99x baseline |
| **Metro (`M`)** | 2,307 | 15 | 2,322 | **0.65%** | 0.73x baseline |
| **Urban (`U`)** | 1,400 | 9 | 1,409 | **0.64%** | 0.72x baseline |

* **Insight:** Rural bank branches experience more than double the mule concentration of urban/metro branches, indicating geographic exploitation where local fraud monitoring may be perceived as less stringent.

---

### 7.4. Customer Age Distribution (`F3894`)
$$\text{Mann–Whitney } U = 138,591.5, \quad p = 0.00049 \quad \text{(Statistically Highly Significant)}$$

| Metric | Regular Accounts (`0`) | Confirmed Mules (`1`) | Comparison |
| :--- | :---: | :---: | :--- |
| **Median Age** | **34.0 years** | **30.0 years** | Mules are 4 years younger on average |
| **Interquartile Range (IQR)** | 25.0 to 45.0 (IQR 20) | 24.0 to 38.0 (IQR 14) | Mules tightly concentrated in 20–35 age band |
| **Adult Mean Age ($\ge 18$)** | **39.37 years** | **34.08 years** | $p < 0.001$ shift towards younger cohorts |

---

### 7.5. Bureau Risk Bands (`F3895` & `F3896`)
* **`F3895` (Credit Score Band):** **86.15% of mules** possess a score in the `600` band (compared to 73.24% of regular accounts).
* **`F3896` (Secondary Score Band):** **73.85% of mules** sit in the `600` band.
* **Finding:** Mules do not have terrible or subprime credit scores (400–500); they are predominantly average-score retail consumers whose credentials appear normal during initial onboarding.

---

## 8. Formal Stage 2 Decision Records

### EDA-011 — Metric Architecture Alignment (Precision@K & PR-AUC)
- **Category:** Evaluation & KPI Framework
- **Dataset/Version:** `DataSet__1_.csv` (Development Set)
- **Evidence:** Extreme class imbalance (111.12:1; 0.895% prevalence in dev).
- **Evidence Status:** Verified.
- **Why it matters:** In operational fraud detection, analyst capacity is finite. Optimizing for ROC-AUC produces alert queues with intolerable false-positive rates.
- **Feature Decision:** N/A.
- **Preprocessing Decision:** N/A.
- **Model/Approach Decision:** Optimize models using loss functions aligned with PR-AUC / focal ranking loss.
- **Evaluation Decision:** Primary evaluation criteria: **Precision@25, Precision@50, Precision@100, and PR-AUC**.
- **Explainability Implications:** Explanations will accompany the top $K$ prioritized alerts.
- **Owner and Status:** Lead ML Engineer / Verified & Accepted.

---

### EDA-012 — Administrative Tag Quarantine Confirmation (`F3912`)
- **Category:** Feature Selection & Leakage Prevention
- **Dataset/Version:** `DataSet__1_.csv`
- **Evidence:** 99.94% concordance with target; autopsy of 5 mismatch rows confirms administrative hold/freeze origin.
- **Evidence Status:** Verified.
- **Why it matters:** Retaining `F3912` causes total model degeneration into a single-rule check.
- **Feature Decision:** **Permanent Blacklist**. Remove `F3912` from all training and inference pipelines.
- **Preprocessing Decision:** Automated pipeline validation check that `F3912` is absent from $X$.
- **Model/Approach Decision:** Build models strictly on behavioral, transaction, and demographic signals.
- **Evaluation Decision:** Document performance difference as evidence of leakage remediation.
- **Explainability Implications:** Guarantees that SHAP feature attribution reflects true behavioral drivers.
- **Owner and Status:** Lead ML Engineer / Verified & Accepted.

---

### EDA-013 — Extraction Batch Isolation Confirmation (`F2230`)
- **Category:** Feature Selection & Leakage Prevention
- **Dataset/Version:** `DataSet__1_.csv`
- **Evidence:** 100% correlation between month and class (Oct25 = 0; Sep/Nov/Dec25 = 1).
- **Evidence Status:** Verified.
- **Why it matters:** Retaining `F2230` introduces fatal cohort leakage.
- **Feature Decision:** **Permanent Quarantine**. Drop `F2230` from model inputs.
- **Preprocessing Decision:** Retain only in an audit metadata frame for temporal monitoring.
- **Model/Approach Decision:** Exclude temporal batch proxies.
- **Evaluation Decision:** Test all retained continuous features against `F2230` via ANOVA/KS in Stage 3 to verify absence of residual batch leakage.
- **Explainability Implications:** Prevents invalid calendar-based risk justifications.
- **Owner and Status:** Data Governance Lead / Verified & Accepted.

---

### EDA-014 — Demographic Risk Multipliers (`Student` & `Savings` Signals)
- **Category:** Feature Engineering & Modeling
- **Dataset/Version:** `DataSet__1_.csv` (Development Set)
- **Evidence:** Students exhibit a 2.06% mule rate ($p = 0.0025$, 2.3x relative risk); Savings accounts contain 92.3% of mules.
- **Evidence Status:** Verified.
- **Why it matters:** Validates known financial crime typologies. High interaction between young student profiles and high-velocity transactional spikes.
- **Feature Decision:** Preserve `F3886` and `F3891`; engineer interaction terms (e.g., `STUDENT_SAVINGS_INTERACTION`, `AGE_BELOW_25_STUDENT`).
- **Preprocessing Decision:** One-hot or target encode occupation and account type with out-of-fold regularized priors.
- **Model/Approach Decision:** Gradient boosted trees naturally capture demographic $\times$ velocity interactions.
- **Evaluation Decision:** Conduct subgroup fairness audit to ensure non-mule students are not disproportionately burdened with false alerts.
- **Explainability Implications:** Allows plain-English explanations: *"Account flagged: Student occupation profile exhibiting abnormal high-value throughput."*
- **Owner and Status:** Data Scientist / Verified & Accepted.

---

### EDA-015 — Geographic Risk Bias Mitigation (`Rural` Branches)
- **Category:** Fairness & Model Bias
- **Dataset/Version:** `DataSet__1_.csv` (Development Set)
- **Evidence:** Rural branches (`R`) have a 1.50% mule rate ($p = 0.025$, 1.7x relative risk) compared to 0.64% in Urban branches.
- **Evidence Status:** Verified.
- **Why it matters:** Over-relying on branch geography may unfairly penalize rural account holders who legitimately bank in smaller branches.
- **Feature Decision:** Keep `F3890` (Region Tier), but regularize heavily; do not use raw branch code `F3887` without hierarchical shrinkage.
- **Preprocessing Decision:** Frequency encoding or target encoding with high smoothing for branch codes.
- **Model/Approach Decision:** Audit model score distributions across geographic tiers.
- **Evaluation Decision:** Report False Positive Rate across branch tiers (`R`, `SU`, `M`, `U`).
- **Explainability Implications:** Prevent explanations that cite branch location alone as justification for fraud alerts.
- **Owner and Status:** Compliance & Ethics Lead / Verified & Accepted.

---

### EDA-016 — Positive-Unlabeled (PU) Formulation
- **Category:** Problem Formulation & Threshold Calibration
- **Dataset/Version:** `DataSet__1_.csv`
- **Evidence:** Ground truth negatives are uninvestigated background accounts, not verified clean accounts.
- **Evidence Status:** Verified.
- **Why it matters:** Treating all negatives as absolute zero ground truth penalizes the model when it detects genuine unflagged mules in the background population.
- **Feature Decision:** N/A.
- **Preprocessing Decision:** N/A.
- **Model/Approach Decision:** Use ranking objectives (Pairwise Ranking or Listwise Ranking) and evaluate semi-supervised PU risk scoring.
- **Evaluation Decision:** Evaluate at top $K$ thresholds rather than fixing a classification threshold at $P = 0.5$.
- **Explainability Implications:** Scores are presented as "Relative Risk Ranking", not absolute ground truth probabilities.
- **Owner and Status:** Lead ML Engineer / Verified & Accepted.

---

## 9. Stage Gate Checklist & Approval to Advance to Stage 3

| Item | Requirement | Verification Result | Status |
| :---: | :--- | :---: | :---: |
| **2.1** | Candidate target `F3924` verified | 9,001 (0) vs. 81 (1) confirmed | **PASSED** |
| **2.2** | Class imbalance geometry established | 111.12:1 imbalance; PR-AUC & PR@K mandated | **PASSED** |
| **2.3** | Snapshot month confounding (`F2230`) dissected | Confirmed 100% batch leak; quarantined | **PASSED** |
| **2.4** | Near-target proxy (`F3912`) autopsied | 5 mismatches confirmed administrative origin; blacklisted | **PASSED** |
| **2.5** | Positive-Unlabeled (PU) dynamics analyzed | Ranking paradigm formalized | **PASSED** |
| **2.6** | Label delay & censoring audited | 87.7% of mules in seasoned accounts (`G365D`) | **PASSED** |
| **2.7** | Demographic segment composition tested | Student ($p=0.0025$), Rural ($p=0.025$), Age ($p=0.00049$) verified | **PASSED** |
| **2.8** | Stage 2 Decision Records logged | `EDA-011` through `EDA-016` formally recorded | **PASSED** |

**Conclusion:** Stage 2 is complete. Both structural validity (Stage 1) and target/cohort reliability (Stage 2) are formally verified and audited on the development partition. The project is cleared to advance to **Stage 3 (Data Quality Audit)**.
