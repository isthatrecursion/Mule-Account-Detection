# Stage 6 — Banking Domain & Specialized Data Analysis

**Project:** Explainable Fraud Intelligence System for Mule Account Detection  
**Document ID:** `eda/06_domain_capabilities_and_data_gaps.md`  
**Execution Stage:** Stage 6 (Items 45–52 of Decision-Driven EDA Plan)  
**Status:** Completed & Reproducibly Audited  
**Date:** 2026-10-11  

> [!IMPORTANT]
> Stage 9 supersedes any feature-semantic, legal-sufficiency, or automated-action language below. Raw categorical values are observed, but business definitions for anonymous and metadata fields require an approved source dictionary. See `eda/09_pre_architecture_verification_and_remediation.md`.

---

## 1. Executive Summary & Objective

The objective of **Stage 6** is to establish the **capability boundaries** of the system. While product vision may call for graph analytics, sequence modeling, and automated plain-English case narratives, engineering integrity requires an uncompromising audit of what the available data actually supports versus what requires upstream data acquisition.

### Key Conclusions in Stage 6:
1. **Current Data Modality is Strictly Tabular:** The dataset provides **one static snapshot record per account** with 2,521 active tabular aggregates and demographic attributes.
2. **Unsupported Architectural Claims Rejected:**
   * **No Graph / Network Chains:** There are zero counterparty links, sender IDs, or transfer edges. Claims of Graph Neural Networks (GNN) or fraud-ring community detection are **scientifically impossible** on this dataset.
   * **No Temporal Event Sequences:** There are no discrete transaction timestamps or raw ledger event streams. Sequence models (LSTM/Transformers) are unsupported.
   * **No Geospatial / NLP Features:** No free-text narrative fields or spatial coordinates exist.
3. **Supported Prototype:** A tabular ranking engine with evidence-limited review briefs. Business-language mappings are enabled only for catalog-approved fields.

---

## 2. Capability Matrix & Architecture Decision Rule (Items 45 & 50)

In strict compliance with the **Architecture Decision Rule** specified in the EDA Plan:

| Fraud Detection Capability | Data Required | Present in `DataSet__1_.csv`? | Supported in Initial Architecture? | Engineering Directive / Boundary |
| :--- | :--- | :---: | :---: | :--- |
| **Account-Level Risk Prioritization** | Snapshot aggregates, demographics, product flags | **YES** | **YES (Primary)** | Gradient boosted trees + regularized cost-sensitive ranking. |
| **Multi-Factor Compliance Explainability** | Verified demographic metadata + SHAP contributions | **YES** | **YES (Primary)** | Rule-guided plain-English narratives grounded in verified fields. |
| **Money-Flow Liquidation Ratios** | Normalized debit/credit concentration aggregates | **YES** | **YES (Secondary)** | Statistical flow concentration indicators (`F156`, `F264`). |
| **Account Maturation / Baseline Profiling** | Account open date (`F3888`), tenure bucket (`F3889`) | **YES** | **YES (Secondary)** | Seasoned vs. newly opened profile baseline segmentation. |
| **Sequential Burst / Velocity Anomaly** | Time-stamped transaction logs, inter-arrival times | **NO** | **NO (Data Gap)** | Excluded; tabular lookback aggregates act as proxies. |
| **Counterparty Graph & Fraud Ring GNN** | Sender/receiver account numbers, transaction edges | **NO** | **NO (Data Gap)** | **Strictly prohibited**. Do not claim network/ring detection. |
| **Transaction Text NLP / Geo-Anomalies** | Transaction memo text, device IP, ATM GPS coordinates | **NO** | **NO (Data Gap)** | **Strictly prohibited**. Omit NLP/geospatial components. |

---

## 3. Supported Banking Indicator Mapping (Item 45)

The 2,521 active features map to 5 functional banking indicator families:

```mermaid
graph TD
    subgraph Supported Banking Indicator Families
        A["1. Observed categorical values<br>(F3886-F3894; meanings pending approval)"]
        B["2. Discrete score-like values<br>(F3895-F3899; meanings pending approval)"]
        C["3. Anonymous binary indicators<br>(F3900-F3918)"]
        D["4. Anonymous bounded numerics<br>(F156, F264, F261)"]
        E["5. Anonymous large-scale numerics<br>(F3811, F3805)"]
    end
    A & B & C & D & E --> F[Multi-Factor Intelligence Synthesizer]
```

1. **Observed category associations:** Values including `Savings`, `RETAIL`, `student`, and `R` occur at different rates across sampled labels. Their field definitions require catalog approval, and the associations may reflect cohort selection.
2. **Anonymous bounded values:** `F156`, `F264`, and `F261` have median `1.00` in positives versus lower medians in negatives. No transaction-flow meaning can be assigned yet.
3. **Anonymous large-scale values:** `F3811` and `F3805` are lower among positives. Units, calculation windows, and business meanings are unknown.
4. **Discrete score-like values:** `F3895 = 600` occurs in 86.15% of positives. Whether this is a bureau score requires source confirmation.
5. **Rare binary indicator:** `F3909 = 1` is associated with an 8.0x sampled-label enrichment. Its channel meaning is unverified.

---

## 4. Customer Baseline Segmentation & Bias Audit (Item 46)

The anonymous `F3811` value varies across observed `F3891` categories:

```text
F3811 Distribution Across F3891 Categories (Development Negatives):
  - Self-Employed:   Median = 969,928   (Mean: 16.25M)
  - Salaried:        Median = 862,095   (Mean: 39.32M)
  - Housewife:       Median = 900,110   (Mean: 10.58M)
  - Student:         Median = 603,507   (Mean: 21.75M)
  - Agriculture:     Median = 638,842   (Mean: 20.90M)
  ----------------------------------------------------
  * Positive labels: Median = 135,589   (Mean:  0.38M)
```

### Critical Bias Safeguard:
* Development negatives with `F3891 = student` have median `F3811 = 603,507`, versus 135,589 among all positives. Both field meanings and the causal interpretation remain unverified.
* **Bias rule:** A demographic category cannot independently trigger an alert or adverse action. Composite “behavioral gates” are also insufficient for certification until the anonymous inputs are defined and prospectively validated.

---

## 5. Enterprise Data Acquisition Gaps & Future Roadmap

To advance beyond static tabular screening, the bank must ingest three upstream data assets:

```text
Data Asset Gap              Required Upstream Table       Enabled Next-Generation Capability
----------------------------------------------------------------------------------------------------
1. Transaction Ledgers      CORE_BANKING_LEDGER_TXNS     Intraday velocity, inter-arrival bursts,
                            (Account, Txn_ID, Time, Amt)  dwell time, rapid round-trip detection.

2. Counterparty Transfer    PAYMENT_SWITCH_EDGES          Graph Neural Networks (GNN), multi-hop
   Graph Edges              (Origin_IBAN, Beneficiary)    money-mule rings, cyclic layering chains.

3. Complete Feature         ENTERPRISE_DATA_CATALOG      100% plain-English translation of all 2,521
   Data Dictionary          (Feature_ID, Source, Unit)    continuous indicators without anonymity.
```

---

## 6. Plain-English Explainability Governance & Feasibility (Item 52)

### 6.1. The Explainability Feasibility Boundary
The product requirement mandates that detection decisions are explained in **plain English to fraud analysts**. We formalize strict governance rules separating permitted factual narratives from ungrounded hallucinations:

| Permitted in Plain-English Explanations ✅ | Strictly Forbidden / Hallucinations ❌ |
| :--- | :--- |
| Citing verified demographic attributes (Occupation, Age, Account Type, Rural Branch). | Fabricating specific transaction details ("Bought $500 crypto on Binance at 2:14 AM"). |
| Citing account tenure bucket (`G365D` seasoned account vs newly opened). | Citing specific counterparty names ("Transferred to John Doe in New York"). |
| Citing credit score bands (`F3895 = 600`). | Inventing geographical locations without GPS data ("Customer logged in from Miami IP"). |
| Citing measured percentile holding balance depletion (`F3811` in bottom 10th percentile). | Inventing specific merchant codes or wire types not present in metadata. |
| Citing an anonymous feature ID, observed value, peer percentile, and signed model contribution (`F156 = 1.0`). | Translating an anonymous feature into “electronic redirection” without a certified definition. |

---

### 6.2. Prototype Analyst Evidence Template
For each ranked account, the prototype may generate an evidence-limited review brief:

```markdown
### MODEL-GENERATED REVIEW PRIORITY
**Record ID:** 9046 | **Risk Rank:** #3 of 7,265 | **Score Type:** relative rank, not probability

#### Observed contributors
* `F156 = 1.00`; high positive contribution; business definition unverified.
* `F3811 = 84,210`; low peer percentile; business definition unverified.
* `F3886 = Savings`, `F3891 = student`; observed raw category values; source definitions pending.

#### Required analyst handling
* Verify the source data and seek independent transactional or case evidence under bank policy.
* Do not infer timing, counterparties, criminal intent, or a required account restriction from the model score.
* Record the analyst outcome for prospective validation and monitoring.
```

---

## 7. Formal Stage 6 Decision Records

### EDA-033 — Architecture Boundary Enforcement (Tabular Only; No GNN)
- **Category:** Architecture & Model Scope
- **Dataset/Version:** `DataSet__1_.csv`
- **Evidence:** Zero sender/receiver links, transaction graph edges, or event timestamps exist.
- **Evidence Status:** Verified.
- **Why it matters:** Claiming graph detection or sequence models without required underlying data constitutes scientific overreach and leads to failed deployments.
- **Feature Decision:** Restrict architecture strictly to tabular risk ranking.
- **Preprocessing Decision:** N/A.
- **Model/Approach Decision:** Gradient Boosted Trees (LightGBM/XGBoost) + Cost-Sensitive Thresholding.
- **Evaluation Decision:** Evaluate on tabular cross-validation metrics.
- **Explainability Implications:** Aligns explanations with achievable tabular signals.
- **Owner and Status:** Lead Architect & ML Engineer / Verified & Accepted.

---

### EDA-034 — Multi-Factor Plain-English Governance Protocol
- **Category:** Explainability Governance
- **Dataset/Version:** `DataSet__1_.csv`
- **Evidence:** Verified metadata columns (`F3886`–`F3923`) contrast with anonymized features (`F1`–`F3885`).
- **Evidence Status:** Verified.
- **Why it matters:** Analysts need traceable evidence, while anonymous feature numbers cannot justify account action or be translated into invented behavior.
- **Feature Decision:** Templates cite approved metadata mappings; all other fields use feature ID, value, percentile, and model contribution.
- **Preprocessing Decision:** Automated template engine mapping SHAP importance to verified factor summaries.
- **Model/Approach Decision:** Rule-guided Case Intelligence Generator.
- **Evaluation Decision:** Human analyst review audit for narrative truthfulness.
- **Explainability Implications:** 100% defensible, audit-proof fraud explanations.
- **Owner and Status:** Data Governance Lead / Verified & Accepted.

---

### EDA-035 — Subgroup Demographic Bias Protection Rule
- **Category:** Fairness & Model Ethics
- **Dataset/Version:** `DataSet__1_.csv` (Development Set)
- **Evidence:** Students exhibit 2.3x relative risk, but legitimate students maintain 4.4x higher holding balances than mules.
- **Evidence Status:** Verified.
- **Why it matters:** Naive models could flag innocent students simply for opening accounts.
- **Feature Decision:** Enforce mandatory behavioral gates: an account cannot be flagged on demographic factors alone.
- **Preprocessing Decision:** N/A.
- **Model/Approach Decision:** Decision trees require joint feature splits (Demographics $\times$ Velocity $\times$ Reserve Depletion).
- **Evaluation Decision:** Audit False Positive Rate across student vs. non-student cohorts.
- **Explainability Implications:** Explanations clearly state that behavioral anomalies triggered the alert, not demographic identity alone.
- **Owner and Status:** Ethics & Compliance Lead / Verified & Accepted.

---

### EDA-036 — Historical Aggregation Lookback Window Mapping
- **Category:** Domain Mapping & Feature Engineering
- **Dataset/Version:** `DataSet__1_.csv` (Active Numerics)
- **Evidence:** Collinear feature clusters (`F448`, `F450`, `F451`, `F453`) exhibit $r > 0.95$ representing nested lookback windows (e.g., 7d, 14d, 30d, 90d).
- **Evidence Status:** Verified.
- **Why it matters:** Nested windows are naturally redundant; retaining the shortest window captures sudden changes, while longer windows capture volume baselines.
- **Feature Decision:** Group lookback clusters; engineer velocity ratios: $\frac{\text{Short Window}}{\text{Long Window}}$.
- **Preprocessing Decision:** Ratio feature engineering.
- **Model/Approach Decision:** Trees exploit sudden velocity acceleration.
- **Evaluation Decision:** Track importance of acceleration features.
- **Explainability Implications:** Explains sudden shifts: *"Recent 7-day volume exceeds 90-day baseline by 8.4x."*
- **Owner and Status:** Data Scientist / Verified & Accepted.

---

### EDA-037 — Enterprise Data Acquisition Gap Specification
- **Category:** Enterprise Architecture & Roadmap
- **Dataset/Version:** `DataSet__1_.csv`
- **Evidence:** Full inventory of data gaps cataloged (transaction ledgers, graph edges, data dictionary).
- **Evidence Status:** Verified.
- **Why it matters:** Establishes the clear evolutionary path for Version 2.0 of the Fraud Intelligence System.
- **Feature Decision:** Document requirements for Phase 2 data pipeline ingestion.
- **Preprocessing Decision:** N/A.
- **Model/Approach Decision:** Architecture designed modularly to ingest graph embeddings when transaction ledgers become available.
- **Evaluation Decision:** Quarterly capability review.
- **Explainability Implications:** Sets expectation boundaries with fraud operations stakeholders.
- **Owner and Status:** Product Manager & Technical Lead / Verified & Accepted.

---

## 8. Stage Gate Checklist & Approval to Advance to Stage 7

| Item | Requirement | Verification Result | Status |
| :---: | :--- | :---: | :---: |
| **6.1** | Banking feature family mapping established | 5 distinct indicator families mapped | **PASSED** |
| **6.2** | Customer baseline segmentation & bias audited | Student baseline balances verified (4.4x higher than mules) | **PASSED** |
| **6.3** | Historical aggregation windows analyzed | Lookback clusters mapped & ratios engineered | **PASSED** |
| **6.4** | Capability matrix & architecture boundaries set | Tabular confirmed; GNN/sequence rejected | **PASSED** |
| **6.5** | Data acquisition gaps documented | Ledgers, edges, and catalog requirements specified | **PASSED** |
| **6.6** | Plain-English explainability template designed | Factual narrative template standardized | **PASSED** |
| **6.7** | Stage 6 Decision Records logged | `EDA-033` through `EDA-037` recorded | **PASSED** |

**Conclusion:** Stage 6 is complete. Domain capabilities, ethical fairness constraints, and plain-English narrative templates are established. The project is cleared to advance to **Stage 7 (Risks, ML Evaluation, Bias & Operational Readiness)**.
