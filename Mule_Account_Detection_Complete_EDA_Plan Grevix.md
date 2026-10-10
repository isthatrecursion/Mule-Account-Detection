# Mule Account Detection — Complete, Decision-Driven EDA Plan

**Project:** Explainable Fraud Intelligence System for Mule Account Detection  
**Audience:** Data scientists, ML engineers, fraud analysts, and project reviewers  
**Purpose:** Turn exploratory data analysis findings into defensible decisions about features, preprocessing, model selection, evaluation, and analyst-facing risk explanations.  
**Status:** EDA plan, not a completed EDA report. Findings marked *previously observed* require reproducible confirmation and validation against the data dictionary.

---

## 0. Project Context and Existing Dataset Signals

The system is intended to **detect** potentially fraudulent mule accounts, **prioritize** investigations within analyst capacity, and **explain** flagged cases with defensible evidence. It is not merely a classifier that produces a number. Analysts should be able to understand the evidence, limitations, and review priority before taking any consequential action.

### Dataset snapshot from preliminary review

| Property | Previously reported observation | Why it matters |
|---|---|---|
| Rows / presumed accounts | 9,082 | Verify whether rows truly represent unique accounts and one observation per account. |
| Anonymous feature columns | `F1` through `F3924` (3,924) | Feature semantics and provenance are largely unavailable. |
| Additional index | One unnamed index-like column | Never use row position as a predictive feature. |
| Candidate binary target | `F3924` | Must be confirmed using source documentation. |
| Candidate positives | 81 (about 0.89%) | Roughly 111 negatives per positive; high uncertainty in minority-class estimates. |
| Candidate negatives | 9,001 | Negative does **not** necessarily imply independently verified clean behavior. |
| Missing cells | Approximately 27.63% | Missingness structure matters as much as the overall rate. |
| Entirely empty numeric columns | 63 | Candidates for removal after verification. |
| Additional numeric columns with at most one observed value | 296 | Likely low-information; check rare-but-meaningful flags. |
| Reported redundant exact-match numeric columns | 977 | Verify duplication, counts, and overlapping categories before computing usable feature totals. |
| Exact duplicate rows | Previously reported as 0 | Check again after removing index/target; same accounts may have nonidentical snapshots. |
| `F2230` | Reporting-month-like categories | Previously found to perfectly separate the candidate target. |
| `F3912` | Binary feature | Previously found to agree with candidate target in 9,077 of 9,082 rows. |
| Interpretable categories | Product/account type, occupation, customer segment, apparent date and category fields around `F3886`–`F3893` | Mapping must be verified before using them for business explanations. |

**Previously observed suspected leakage patterns** (these are hypotheses until provenance is checked):

| `F2230` value | Reported rows | Reported `F3924 = 1` |
|---|---:|---:|
| `Oct25` | 9,001 | 0 |
| `Sep25` | 48 | 48 |
| `Nov25` | 23 | 23 |
| `Dec25` | 10 | 10 |

The first 9,001 rows were previously observed to have candidate target `0`, and the last 81 to have candidate target `1`. **This may be a label-assembly/cohort artifact rather than real fraudulent behavior.** Investigate before modeling.

### Core operating rules

1. **Do not train a supervised classifier until the true target is confirmed.** `F3924` is only a candidate until the label owner or data dictionary verifies it.
2. **Do not use target proxies, post-outcome indicators, or row ordering.** Investigate `F2230`, `F3912`, and other suspicious features before any final feature set is approved.
3. **Protect the final holdout before target-informed EDA or model selection.** Use development data to fit preprocessing, select features, tune models and calibrate thresholds. Reserve the final test set for a single unbiased evaluation; a valid future-time holdout may require additional data.
4. **Never oversample before splitting.** If oversampling is tested, apply it only to training folds inside cross-validation.
5. **Do not automatically remove extreme values.** Rare financial behavior may be useful evidence of mule activity.
6. **Do not invent business meanings for anonymized features.** SHAP can explain influence of `F1234`; it cannot prove `F1234` means unusual transaction velocity.
7. **Keep the human analyst in control.** Scores and explanations prioritize review; they are not automatic authority to freeze accounts.

### Priority legend

- **Must-do:** Necessary for a defensible feasibility determination, baseline experiment, or operational decision.
- **Optional:** Valuable when additional information is available or after core risks are resolved.
- **Order:** Checklist item numbers specify the recommended sequence. Items within a stage can sometimes run in parallel, but do not bypass the stage gates.

---

## Stage 1 — Data Understanding & Structural Audit

**Execution order: 1–8.** Goal: Establish what each record and feature represents, what data is available at scoring time, and how validation can work.

| # | Priority / Checklist | Why it matters for mule detection | Python libraries / investigation method | Finding → Design decision |
|---|---|---|---|---|
| 1 | ☐ **Must — Dataset inventory** | Quantify size, dimensionality and memory needs before cleaning. | `pandas.read_csv`, `df.shape`, `df.info()`, `df.memory_usage(deep=True)`; optionally Polars. | Large memory overhead → optimize dtypes or use chunking/Polars. |
| 2 | ☐ **Must — Row granularity** | One row might represent an account, account-month or repeated snapshot; this affects labels and splits. | Check source documentation, business keys, account IDs, observation dates and grouping counts. | Repeated accounts → grouped train/test split and account-level risk aggregation. |
| 3 | ☐ **Must — Feature dictionary** | Anonymous `F` columns prevent trustworthy business interpretations and engineered features. | Request mapping: field name, unit, source system, formula, time window and refresh cadence. | Unmapped features → statistical explanations only; avoid invented fraud narratives. |
| 4 | ☐ **Must — Source and sampling provenance** | Target prevalence and apparent patterns may be artifacts of how cases were selected. | Inspect sampling rules, extraction SQL/process, cohort criteria and source counts. | Case-control or enriched sampling → metrics and probability calibration need population correction/representative evaluation. |
| 5 | ☐ **Must — Data types** | Misread numeric codes, dates and categories can distort patterns. | `df.dtypes`, `select_dtypes`, `pd.to_numeric`, `pd.to_datetime` plus data dictionary. | Numeric-coded category → encode categorically rather than scale as continuous. |
| 6 | ☐ **Must — Observation timestamps** | A deployed model cannot use information recorded after the decision point. | Map feature snapshot date, extraction date, transaction windows and label confirmation date. | Post-investigation or future-derived features → exclude or recreate strictly as-of. |
| 7 | ☐ **Must — Business meaning and availability** | An informative feature may be unavailable or too delayed for live screening. | Feature catalog with latency, extraction dependencies, units and generation costs. | Offline-only feature → remove from real-time model or change product design. |
| 8 | ☐ **Must — Define and protect the holdout** | Target-guided EDA on the final test data will produce optimistic estimates. | Select strategy: chronological if valid, `StratifiedGroupKFold` if repeated accounts, `StratifiedShuffleSplit` for development diagnostics. Store split IDs. | No valid representative/chronological two-class test cohort → gather data; do not claim future generalization. |

**Deliverables:** Dataset schema; grain and source definition; feature-provenance register; prediction-time policy; immutable validation strategy.

---

## Stage 2 — Target / Label Analysis

**Execution order: 9–16.** Goal: Verify the target, investigate suspicious label relationships, and distinguish confirmed fraud from incomplete observations.

| # | Priority / Checklist | Why it matters for mule detection | Python libraries / investigation method | Finding → Design decision |
|---|---|---|---|---|
| 9 | ☐ **Must — Verify `F3924` as target** | Without a verified target, supervised results cannot be described as mule detection. | Confirm with label owner/data dictionary; inspect `value_counts(dropna=False)` and label criteria. | Target not confirmed → suspend supervised fraud-performance claims. |
| 10 | ☐ **Must — Class distribution** | Very few positives lead to unreliable minority-class metrics and misleading accuracy. | `value_counts(normalize=True)`, `seaborn.countplot`, ratios. | Extreme imbalance → AP/PR-AUC, Precision@K, Recall@K; consider weighting. |
| 11 | ☐ **Must — Target versus reporting month** | `F2230` reportedly perfectly separates candidate target classes. | `pd.crosstab(df['F2230'], y)`, cohort counts, source extraction comparison. | Label aligned to acquisition batch → cohort-confounding investigation; quarantine batch proxies and obtain representative cohorts. |
| 12 | ☐ **Must — Near-target proxy `F3912`** | This feature reportedly differs from candidate target in only five records. | Crosstab, mismatch-case inspection, mutual information, source/creation timestamp. | Derived from alert/investigation outcome → exclude; genuine pre-decision flag → document carefully and benchmark with/without it. |
| 13 | ☐ **Must — Label reliability** | Confirmed mule, suspected mule, investigated and frozen are different concepts. | Review case policies, adjudication rules, manual samples, corrections/reversals. | Inconsistent label standards → refine labels or train only on adjudicated subset. |
| 14 | ☐ **Must — Negative-label reliability** | Not reported as fraud does not mean proven clean. | Review observation windows, investigation coverage and negative sampling criteria. | Substantial unknown negatives → evaluate positive-unlabeled/ranking alternatives and explicitly qualify labels. |
| 15 | ☐ **Must — Label delay and censoring** | Newly opened/recent accounts may lack sufficient fraud confirmation time. | Compare observation time to fraud-report time and required maturation window. | Insufficient follow-up → exclude immature cohorts or use time-aware evaluation/labeling. |
| 16 | ☐ **Must — Target composition by segment** | A positive class confined to one month/account segment may not transfer elsewhere. | `groupby`, `crosstab`, stratified stacked bars, category support counts. | Cases concentrated in one subgroup/cohort → diagnose sampling bias and seek diverse positives. |

**Deliverables:** Verified label specification; positive/negative quality report; target-proxy investigation; exclusion candidates; documented label maturity and cohort limitations.

---

## Stage 3 — Data Quality Audit

**Execution order: 17–29.** Goal: Specify a cleaning pipeline that does not erase rare but meaningful fraud signals.

| # | Priority / Checklist | Why it matters for mule detection | Python libraries / investigation method | Finding → Design decision |
|---|---|---|---|---|
| 17 | ☐ **Must — Missingness by feature** | Missingness may reflect operational coverage or account characteristics. | `df.isna().mean().sort_values()`, missing-value heatmaps/plots. | Entirely null → drop; partially missing → compare imputation, missing indicator, or feature exclusion. |
| 18 | ☐ **Must — Missingness by account** | A high-risk score based on almost no evidence is dangerous. | `df.isna().mean(axis=1)`, quantiles, histograms. | Very sparse records → insufficient-data flag, abstention or separate review logic. |
| 19 | ☐ **Must — Missingness patterns** | Reporting gaps may correlate with labels for reasons unrelated to behavior. | `missingno`, missing-indicator correlations, `groupby` label/source/month on development data. | Batch-specific missingness → leakage investigation rather than automatic feature inclusion. |
| 20 | ☐ **Must — Duplicate and near-duplicate records** | Same account in train and test inflates model results. | `df.duplicated()`, duplicate check without index/label, hashes, account ID matching if available. | Repeated account/snapshot → grouped splits and/or consolidate observations. |
| 21 | ☐ **Must — Constant and entirely empty features** | Thousands of low-information features increase complexity. | `nunique(dropna=True)`, `sklearn.feature_selection.VarianceThreshold`. | All-null or confirmed constant → remove using train-fitted rules; inspect rare flags. |
| 22 | ☐ **Must — Exact and near-duplicate columns** | Redundancy can inflate explanation complexity and feature count. | `df.T.duplicated()` where feasible; hash columns; numeric correlations in blocks. | Redundant feature family → retain documented representative or regularize; avoid arbitrary deletion of semantically distinct variables. |
| 23 | ☐ **Must — Invalid numeric values** | Unrealistic magnitudes may be errors, sentinel codes or valid financial extremes. | `describe(percentiles=[.01,.05,.5,.95,.99])`, `np.isfinite`, domain range checks. | Invalid values → repair/mark missing; genuine extremes → preserve with robust transformations. |
| 24 | ☐ **Must — Outliers** | Anomalous transactions can be relevant detection signals. | IQR, MAD, quantile summaries, log-scale plots; Isolation Forest as exploratory aid. | Confirmed valid extremes → avoid deleting; transform or use robust models as appropriate. |
| 25 | ☐ **Must — Categorical inconsistencies** | `student`, `Student`, blanks and unknown codes fragment the same category. | `value_counts(dropna=False)`, `.str.strip()`, normalized casing, documented mapping. | Equivalent labels → standardize; undefined codes → keep as unknown pending mapping. |
| 26 | ☐ **Must — Dates and impossible values** | Tenure and temporal features are invalid if dates are placeholders. | `pd.to_datetime(errors='coerce')`, calendar bounds, sentinel checks. | `1900` or other placeholders confirmed → encode as missing, not as genuine old accounts. |
| 27 | ☐ **Must — Zero, negative and sentinel semantics** | Zero activity and missing activity are operationally different. | Value frequency tables for zero/negative/codes; source definitions. | Sentinel → missing; genuine zero balance or reversal → preserve. |
| 28 | ☐ **Must — Business consistency rules** | Contradictory feature combinations can imply extraction bugs. | `pandera`, `pandas` assertions and documented accounting rules. | Impossible duration, ratios or dates → quarantine records and fix upstream processing. |
| 29 | ☐ **Optional — Drift between data batches** | Monthly cohorts may use different extraction schemas or reflect genuine business shifts. | Per-month distributions, KS tests, Wasserstein distance, PSI with suitable binning. | Strong source/batch drift → validate extraction and design cohort-aware assessment. |

**Deliverables:** Missingness matrix and report; verified drop candidates; consistent types/categories; transformations and imputation policy; row/column duplication report; validation rules.

---

## Stage 4 — Univariate Analysis

**Execution order: 30–35.** Goal: Understand individual features before concluding which ones matter to the label.

| # | Priority / Checklist | Why it matters for mule detection | Python libraries / investigation method | Finding → Design decision |
|---|---|---|---|---|
| 30 | ☐ **Must — Numeric distributions** | High skew may be natural in banking data and can affect linear models. | Quantiles, `describe`, histograms, boxplots, skewness; `seaborn`/`matplotlib`. | Strong skew → test log transform for nonnegative variables, signed transforms or `RobustScaler`. |
| 31 | ☐ **Must — Zero inflation** | Dormant accounts and inactivity may need distinct treatment. | Zero fractions and separate zero/nonzero distributions. | Strong zero mass → candidate zero-activity flag or two-part representation. |
| 32 | ☐ **Must — Categorical frequency** | Rare occupations/account products may create unstable patterns. | `value_counts`, cardinality, frequency plots. | Sparse levels → group infrequent values, preserve unknown category at inference. |
| 33 | ☐ **Must — Variance and entropy** | Near-constant columns are numerous in wide anonymized data. | Unique counts, variance, categorical entropy. | Low information → investigate and usually prune, except validated rare-risk indicators. |
| 34 | ☐ **Must — Feature scale and units** | Extremely different numeric ranges can distort distance/linear methods. | Min/max, quantiles, scales and unit mapping. | Mixed scales → scale when needed, use unit-correct transformations; trees often need less scaling. |
| 35 | ☐ **Optional — Feature-family visualization** | Thousands of separate plots are expensive and hard to interpret. | Group by documented semantics/windows; auto-generate selected representative histograms. | Similar distributions across a feature family → standardized family-level processing. |

**Deliverables:** Numeric distribution profile; categorical cardinality report; sparsity and transformations inventory; visual feature gallery for representative groups.

---

## Stage 5 — Bivariate & Multivariate Analysis

**Execution order: 36–44.** Goal: Discover stable candidate signals and distinguish genuine account behavior from cohort artifacts. All target-aware analysis belongs in development data, not the final holdout.

| # | Priority / Checklist | Why it matters for mule detection | Python libraries / investigation method | Finding → Design decision |
|---|---|---|---|---|
| 36 | ☐ **Must — Numeric versus target** | Understand which numerical features differ between candidate positives and negatives. | Class-conditional histograms/quantiles; Mann–Whitney U, effect sizes, univariate ROC-AUC. | Strong association → investigate provenance and stability; do **not** immediately label causal fraud evidence. |
| 37 | ☐ **Must — Categorical versus target** | Customer segments may show associations driven by prevalence or sample design. | Crosstabs, category-level positive rate with denominators, chi-square/Fisher where valid. | High rate with tiny support → do not generalize without broader samples. |
| 38 | ☐ **Must — Missingness versus target** | Absence of data itself may separate the two acquisition cohorts. | Null-indicator crosstabs/MI; control for source and month. | Missingness follows label batch → investigate collection leakage. |
| 39 | ☐ **Must — Feature correlation** | High redundancy can produce unstable interpretation and overfitting. | Pearson/Spearman in manageable blocks, clustering of correlated columns. | Strongly redundant groups → consider representative selection, regularization and explanation grouping. |
| 40 | ☐ **Must — Nonlinear dependence** | Fraud patterns can depend on complex interactions. | `mutual_info_classif`, binning, shallow trees, partial dependence only after model validation. | Stable nonlinear association after leakage controls → compare boosted trees to logistic regression. |
| 41 | ☐ **Must — Confounding and interaction** | Features may look predictive only because they encode month/account type. | Stratified associations, conditional plots, interaction tests, cohort-fixed comparisons. | Association disappears within comparable cohorts → suspect confounding. |
| 42 | ☐ **Must — Feature ranking stability** | Only 81 positives means importance rankings can vary widely. | Repeated train-only CV, bootstrap importance, permutation importance with correct evaluation protocol. | Unstable top features → simplify/regularize model and qualify explanations. |
| 43 | ☐ **Must — Multiple-comparisons effects** | Screening thousands of columns creates chance discoveries. | Benjamini–Hochberg FDR for formal univariate tests; nested CV for predictive selection. | Weak/unstable evidence → avoid causal or operational assertions. |
| 44 | ☐ **Optional — Dimensionality reduction / clusters** | Can expose batch effects, broad groups or unexpected structure. | PCA, TruncatedSVD, UMAP; K-means/HDBSCAN as exploratory aids. | Groups match month/source, not behavior → investigate assembly artifacts; plots alone do not prove fraud detection. |

**Deliverables:** Correlation/feature-family map; candidate feature shortlist; provenance and stability notes; spurious-correlation inventory.

---

## Stage 6 — Banking Domain & Specialized Data Analysis

**Execution order: 45–52.** Goal: Decide which fraud-intelligence capabilities are actually supported by available data. The current CSV does **not** clearly establish raw transaction records, sender–receiver edges, free text or spatial coordinates.

| # | Priority / Checklist | Why it matters for mule detection | Python libraries / investigation method | Finding → Design decision |
|---|---|---|---|---|
| 45 | ☐ **Must — Banking feature-family mapping** | Determine whether anonymized fields are transaction counts, balance stats, velocity measures, ratios or existing flags. | Join data dictionary to feature list; categorize source/units/windows/formulas. | Mapping available → explainable banking indicators; absent → restrict to anonymous tabular classification. |
| 46 | ☐ **Must — Account tenure and customer segments** | Baseline behavior differs by customer/product type, but such fields can create bias. | Validated tenure field and `groupby` of product/occupation/customer segment. | Stable legitimate baseline differences → test careful segmentation; audit subgroup harms. |
| 47 | ☐ **Must — Historical aggregation windows** | 7/30/90-day signals and recent changes have different predictive meanings. | Identify feature lookback windows from metadata; check overlap, start/end times. | Validated short-window features → compare recent-versus-long-term changes while respecting prediction time. |
| 48 | ☐ **Optional — Money-flow velocity** | Mule accounts may receive and rapidly forward funds. | **Only with appropriate source data:** compute inflow/outflow totals, ratios, counterparties, dwell time using `pandas`. | Strong and verified temporal flow signals → add velocity-based features and case evidence. |
| 49 | ☐ **Optional — Time-series behavior** | Fraud behavior may show bursts or sudden changes. | **Only with sequential account observations:** rolling windows, change-point detection, seasonality and volatility. | Useful time dynamics → build temporal engineered features or sequence model; otherwise stay tabular. |
| 50 | ☐ **Optional — Transaction network** | Multiple mule accounts may form suspicious transfer chains. | **Only with transaction edges:** NetworkX/igraph degree, communities, motifs, flow patterns. | Reliable graph connectivity → add graph features or GNN research; without edges do not claim network detection. |
| 51 | ☐ **Optional — Text / geospatial** | Narratives, merchant descriptions or location changes could add evidence. | **Only if present:** spaCy/text profiling; GeoPandas and spatial consistency audits. | Valid external fields → explore NLP/geospatial features; if absent, omit these components. |
| 52 | ☐ **Must — Explainability feasibility** | Product requires truthful plain-English detection reasons. | Validate feature mapping, source records and SHAP/permutation contribution stability. | Feature meanings unknown → show feature IDs and measured contributions, not ungrounded banking narratives. |

**Deliverables:** Supported-indicator map; capability matrix (tabular / temporal / network / text / geospatial); data-acquisition gaps; explanation feasibility report.

### Architecture decision rule

| Available evidence | Supported initial architecture | Do **not** claim without more data |
|---|---|---|
| Only anonymized tabular account features | Tabular classification/ranking, quality controls, statistical feature contributions, human review queue | Verified transaction-chain detection or specific natural-language behavior explanations |
| Time-stamped transaction amount + direction | Transaction velocity, inflow/outflow patterns, temporal anomaly features | Counterparty network patterns without transfer links |
| Sender/receiver identifiers + transfer edges | Network metrics, graph investigation and flow evidence | Verified fraud rings without independent investigation/ground truth |
| Verified data dictionary + case evidence | Domain-grounded textual explanations with feature provenance | Strong claims from unnamed feature contributions alone |

---

## Stage 7 — Risks, ML Evaluation, Bias & Operational Readiness

**Execution order: 53–64.** Goal: Ensure any model is valid, robust, auditable and useful within finite analyst-review capacity.

| # | Priority / Checklist | Why it matters for mule detection | Python libraries / investigation method | Finding → Design decision |
|---|---|---|---|---|
| 53 | ☐ **Must — Full leakage audit** | Target proxies can make model performance appear perfect. | Per-feature provenance/timing; high-target-association screening; source/batch and row-order tests. | Post-outcome or target-derived fields → quarantine/exclude; document feature blacklist. |
| 54 | ☐ **Must — Split contamination audit** | Duplicate accounts or future info across splits invalidate metrics. | Account/group overlap, feature-fingerprint overlap, timestamp audits and purge-gap analysis when relevant. | Contamination → redo with grouping/chronological purge. |
| 55 | ☐ **Must — Imbalance treatment** | Rare positives may be ignored by naïve training. | Compare regularized logistic regression with `class_weight`, weighted boosting, optional SMOTE via `imblearn.Pipeline` inside train folds only. | Weighting suffices → avoid unnecessary synthetic observations; judge by PR metrics. |
| 56 | ☐ **Must — Baseline comparison** | Complex algorithms should beat a transparent, defensible reference. | Random ranker, legitimate simple business-rule baseline (if documented), logistic regression and gradient boosting. | Comparable performance → prefer simpler, more stable model. |
| 57 | ☐ **Must — Fraud-oriented metrics** | 99% accuracy can mean zero detected mules. | `average_precision_score`, precision–recall curve, F1, ROC-AUC, confusion matrix. | Poor positive capture despite accuracy → reject/iterate. |
| 58 | ☐ **Must — Analyst capacity metrics** | Human investigators can review only a limited number of alerts. | Precision@K, Recall@K, lift@K, positives captured per 50/100 alerts; prespecify K. | Weak top-K performance → improve ranking before deploying analyst workflow. |
| 59 | ☐ **Must — Thresholds and calibration** | Model scores should not be presented as verified probabilities without checking calibration. | Validation threshold tuning, `calibration_curve`, Brier score, `CalibratedClassifierCV` on development data. | Miscalibrated scores → calibrate or present as relative risk ranks instead of absolute probabilities. |
| 60 | ☐ **Must — Uncertainty from low positives** | With 81 positives, one or two cases materially change recall. | Confidence intervals and resampling consistent with groups/time; repeated development folds; report sample counts. | Wide CIs → avoid production-readiness claims and request more labeled examples. |
| 61 | ☐ **Must — Fairness / subgroup risk** | Model alerts can impose unequal investigation burden on legitimate customers. | Lawful, sufficiently powered subgroup false-positive/recall analysis; proxy risk audit. | Disparities → investigate sampling, proxy features, policy and mitigation before deployment. |
| 62 | ☐ **Must — Distribution shift and prevalence representativeness** | Model trained on selected cases may fail on actual banking population. | Cohort comparison, prevalence audit, KS/PSI/drift summaries, external and temporal validation if possible. | Major population shift → obtain representative future holdout and monitor drift. |
| 63 | ☐ **Must — Explanation integrity and governance** | Explanations must be stable and supported by traceable facts. | Per-case SHAP/permutation analyses, stability tests, feature lineage and audit logging. | Unmapped or unstable evidence → restrict narratives, use uncertainty flags and analyst review. |
| 64 | ☐ **Must — Privacy, security and reproducibility** | Financial data and risk scores are sensitive; reviewers require traceability. | PII scan, pseudonymization, least-privilege access, experiment/version logs, data retention checks. | Missing controls or traceability → remediate before any operational use. |

**Deliverables:** Leakage register; split protocol; model-ready baseline specification; fraud evaluation scorecard; fairness and uncertainty notes; governance limitations.

---

## Evaluation Metrics — Design Decision Guide

| Metric | Role in this project | What it answers | Caveat |
|---|---|---|---|
| **Precision@K** | Primary operational metric | Of the top K accounts sent for review, how many are labeled positive? | K must reflect analyst capacity; case-label quality matters. |
| **Recall@K** | Primary operational metric | What fraction of known positives are captured within K investigations? | Uncertain negatives and unconfirmed positives affect interpretation. |
| **Average Precision (AP)** | Primary ML ranking metric | How well does the ranking trade precision against recall? | Random ranking baseline is close to prevalence only under representative sampling. |
| **Recall at fixed false-positive rate** | Important secondary | What detection can be achieved with an acceptable false-alarm rate? | May not directly match finite review capacity. |
| **ROC-AUC** | Supporting discrimination metric | Are positives generally scored above negatives? | Can obscure poor alert precision when positives are very rare. |
| **Calibration / Brier score** | For probability-style risk scores | Do predicted probabilities agree with actual frequency? | Biased sampling and prevalence shift invalidate naïve probability interpretation. |
| **Accuracy** | Diagnostic only | What fraction of all records is correctly classified? | All-negative prediction reaches **about 99.11%** here while finding no positives. |

**Important:** For 81 positives out of 9,082 records, the apparent prevalence is approximately **0.89%**. That is a useful reference for random rankings *within this sample*, but not proof of true bank-wide mule prevalence. Avoid presenting inflated random-split metrics as evidence of future detection when month and label are confounded.

### Example analyst review capacities to evaluate

- `K = 25`: very selective daily review budget.
- `K = 50`: small team review queue.
- `K = 100`: broader shortlist reflecting the project's stated aim of prioritizing a manageable number of cases.

These are **illustrative**, not measured bank capacities. The real K should be supplied by operational stakeholders.

---

## Execution Roadmap and Stage Gates

| Phase | Checklist items | Main output | Gate before advancing |
|---|---|---|---|
| **A. Validity first** | 1–16 | Schema, label definitions, cohort/proxy investigation, holdout policy | Correct prediction target and a defensible evaluation strategy exist. |
| **B. Quality and preprocessing** | 17–35 | Cleaning rules, null/duplicate/outlier profiles, transformations | No irreversible cleanup destroys meaningful signals; preprocessing is train-fitted. |
| **C. Signal discovery** | 36–44 | Stable feature shortlist and correlation/confounding report | No strong feature is accepted solely from suspect leakage or unstable univariate associations. |
| **D. Domain feasibility** | 45–52 | Verified banking indicator map and architecture boundaries | Product only claims behavior and explanations demonstrably supported by data. |
| **E. Model readiness** | 53–64 | Baseline/evaluation protocol, risk register, operational KPI plan | Holdout integrity, top-K performance reporting, uncertainty and privacy controls are defined. |

### Minimum viable EDA outputs for the repository

```text
eda/
├── 00_dataset_inventory.md
├── 01_schema_and_feature_dictionary.csv
├── 02_label_and_cohort_audit.md
├── 03_data_quality_report.md
├── 04_distribution_and_association_report.md
├── 05_leakage_and_feature_exclusions.csv
├── 06_domain_capabilities_and_data_gaps.md
├── 07_evaluation_protocol.md
└── 08_eda_to_design_decisions.md
```

These are proposed deliverable filenames, not files already generated.

---

## Template — Turn Every EDA Finding Into a Project Decision

Make one decision record per consequential observation. Record facts separately from decisions and unverified hypotheses.

| Field | Required content |
|---|---|
| **Finding ID** | Unique ID, e.g., `EDA-014`. |
| **Category** | Feature selection / preprocessing / modeling / evaluation / explainability / limitation. |
| **Evidence** | Exact metric, chart, columns, sample size and dataset version. |
| **Status of evidence** | Verified / observed but unexplained / hypothesis / awaiting metadata. |
| **Why it matters** | Effect on false alerts, miss rate, deployment validity, model stability or explanation quality. |
| **Feature-selection decision** | Keep / remove / quarantine / merge / engineer, with rationale. |
| **Preprocessing decision** | Missing-value method, scaling, encoding, clipping, consistency rules. |
| **Model/approach decision** | Selected baseline/model architecture and why. |
| **Evaluation impact** | Required split design, metrics, cohort analyses, confidence intervals or thresholds. |
| **Known limitations** | Unverified labels, biased sampling, absent feature definitions or other uncertainties. |
| **Validation required** | Targeted test, source documentation or new dataset needed to accept decision. |
| **Owner / status** | Responsible person and status: proposed / verified / accepted / rejected / blocked. |

### Copyable decision record

```markdown
### EDA-___ — [Finding title]

- **Category:**
- **Dataset/version:**
- **Evidence (statistic, columns, denominator, figure):**
- **Evidence status:** Verified / Observed / Hypothesis / Blocked
- **Why it matters to mule detection:**
- **Feature decision:** Keep / Remove / Quarantine / Engineer / Merge
- **Preprocessing decision:**
- **Model/approach decision:**
- **Evaluation decision:**
- **Explainability implications:**
- **Known limitation(s):**
- **Required validation / next test:**
- **Owner and acceptance status:**
```

### Initial decision register — preliminary and proposed, **not finalized**

| Area | Existing observation or concern | Recommended decision | Status |
|---|---|---|---|
| Feature selection | `F2230` reportedly separates `F3924` exactly. | Quarantine pending determination of reporting-month provenance and label sampling. | Needs verification |
| Feature selection | `F3912` almost matches the candidate target. | Investigate as possible post-outcome alert/target proxy; compare with/without only after timing audit. | Needs verification |
| Preprocessing | Approximately 27.63% of cells missing. | Evaluate per-feature missingness, imputation, missing indicators and insufficient-data handling. | Pending EDA |
| Preprocessing | Empty/constant/redundant columns reported. | Verify counts and prune using training-only rules; preserve meaningful rare indicators. | Pending EDA |
| Modeling | 3,924 anonymized features and only 81 candidate positives. | Start with regularized logistic regression and weighted gradient-boosting baselines. | Proposed |
| Evaluation | About 0.89% apparent positive prevalence. | Prioritize AP, Precision@K, Recall@K, operational K and uncertainty; do not use accuracy as primary metric. | Proposed |
| Explainability | Most `F` feature names are not interpretable. | Recover feature definitions before generating natural-language transaction-behavior explanations. | Blocked by metadata |
| Architecture | No verified raw transfer edges in provided CSV. | Start with account-level tabular risk scoring; treat graph/network capabilities as conditional. | Proposed |

---

## Final Decisions the EDA Must Enable

Before the team starts implementing a final model and analyst-facing system, it should be possible to answer:

1. **Prediction target:** What event are we predicting, according to an authoritative label definition, and at what point in time?
2. **Population and validation:** Does evaluation represent unseen accounts/future periods, rather than a target-sorted extraction cohort?
3. **Feature trust:** Which inputs are legitimate, available at scoring time and free of target-derived proxies?
4. **Preprocessing:** What imputation, encoding, scaling, deduplication and outlier policies are reproducible?
5. **Model selection:** Does a simple regularized or weighted tabular model provide stable improvement over credible baselines?
6. **Operational quality:** Among the top K cases analysts can realistically review, how many genuine cases are detected, with what uncertainty?
7. **Explanation quality:** Which observations are truly explainable in business terms, and which remain anonymous statistical indicators?
8. **Limitations and data needs:** What critical information—data dictionary, labeled follow-up, bank population sample, transaction edges, timestamps—is still missing?

**Bottom line:** EDA is complete only when it produces a documented **feature policy, preprocessing pipeline specification, credible evaluation design, capability boundary and known-limitations register**. A collection of charts, without these decisions, is not enough for an operational fraud intelligence project.
