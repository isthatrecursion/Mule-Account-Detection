# Phase 5 feature pipeline

The package now provides training-only feature discovery and frozen inference for
the authorized research workflow. It does not train or approve a deployable model.
Qualified rules, temporal evaluation, model registration and public scoring belong
to subsequent phases and remain blocked by the existing data dependencies.

## Application boundary

Use an accepted published validation version and the trusted research adapter.
`research_frame(batch, guard)` checks development membership and converts only
predictors into a new DataFrame. It normalizes categorical `None` to NumPy NaN,
preserves integer values, and rejects lossy nullable-integer conversion. Labels
and lineage stay separate. It does not make a quarantined batch acceptable: the
application must still query current acceptance before reading the snapshot.

```python
from sklearn.base import clone
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.features.inputs import research_frame

X = research_frame(verified_research_batch, partition_guard)
prototype = FeaturePipeline.from_repository(repository_root)
pipeline = clone(prototype)
pipeline.fit(X.iloc[train_positions])
train_matrix = pipeline.transform(X.iloc[train_positions])
validation_matrix = pipeline.transform(X.iloc[validation_positions])
```

Create a fresh clone for every fold and candidate. Splitting, eligibility, labels,
source completeness and accepted-batch authorization are application concerns;
passing a DataFrame to this numerical component does not certify them. Legacy
semantic rules reject every qualified fit, including zero-filled source gaps.
Optional cell imputation therefore cannot authorize an absent transaction source.

## Reference behavior

The untouched `scripts/pre_architecture_verification.py` remains the independent
reference. `features/preprocessor.py` extracts its algorithm with sklearn cloning
support. It is a low-level comparator without the application authorization or
predictor checks supplied by `FeaturePipeline`.

The reusable pipeline composes policy enforcement, versioned semantic cleanup,
structural pruning, and a numeric/categorical `ColumnTransformer`. Structural
selection retains the reference order: constants/all-null columns, missingness
**greater than or equal to 90%**, then dtype-sensitive exact duplicate columns.
Imputation uses training medians and most-frequent categories. Unknown categories
use the stored encoder's ignore policy. No new missingness indicators are added;
the historical date indicator remains part of `legacy_research_v1`.

`config/semantic_rules.yaml` supplies the legacy date/age constants. The frozen
`SemanticRules` model requires their exact values under this version. Changing a
constant requires a new implemented/versioned rule and reviewed parity decision;
editing the certification flag cannot authorize qualified use. Date/age business
meanings remain unverified. The generated `F3888_IS_LEGACY` cannot be supplied as
an input predictor, because cleanup owns its definition.

The earlier `domain.feature_policy.derive_structural_exclusions` is a Phase 2
contract illustration, with a strict `>` threshold and simplified duplicate
semantics. It is not used for training or pipeline selection. Phase 5 deliberately
preserves the historical benchmark's `>=` comparison rather than changing it to
match that helper. The exclusion manifest records the actual comparison used.

## Signatures, evidence references and missingness

The fitted input signature records ordered names and numeric/categorical types.
Inference accepts reordered columns, rejects missing/extra/duplicate columns and
type-family changes, and checks transformed dimensionality and finite values.
An empty inference batch produces `(0, n_features_out)`; empty training or no
surviving features is rejected.

Encoded features map to raw fields through transformer output slices and learned
category arrays. Underscores in column/category names cannot break this mapping.
Reference numeric values/counts and category frequencies are learned only from
training observations. They carry a training fingerprint; they are not population
statistics or certified business interpretations. `missing_mask()` reports missing
and legacy-invalid cells without changing original observations. Later evidence
generation must distinguish those cells from observed values.

`exclusion_report_` separates the historical **2,521 registered candidates** from
the actual fold's selected features and drop reasons. It never forces every fold
to select that historical count.

## Fitted artifacts

`save_pipeline(pipeline, root, split_fingerprint=..., code_identity=...)` stages the
joblib state, raw/encoded signatures, exclusions, training references, and both
policies. It records training/split/code identities, package/Python versions,
file sizes and hashes, flushes files, writes the manifest last, and publishes by
directory rename under the manifest SHA-256. Existing publications are not
overwritten. A failed staging directory is unpublished; recovery/retention of
staging directories must be integrated with the later registry lifecycle.

`load_pipeline(directory, allowed_root=..., expected_digest=...)` checks the
independently pinned manifest digest, allowed root, exact artifact inventory,
runtime compatibility and file hashes **before** trusted joblib deserialization.
Use only service-controlled roots and approval-supplied digests. Joblib executes
code; hashes supplied alongside an analyst upload do not establish trust. Phase 7
must add model/environment approval, restricted loading and model/pipeline parity.

Training reference distributions and fitted artifacts are confidential. Store
them only on approved encrypted storage with appropriate ACLs. The feature writer
does not itself encrypt files or provide registry approval. Tests save synthetic
artifacts; the real-data parity runner writes no fitted bundles, raw rows, labels,
record-level predictions or membership lists into public evidence.

## Verification

```powershell
.\.venv\Scripts\python.exe scripts/verify_features.py --output-dir artifacts/phase5/new_synthetic_run
.\.venv\Scripts\python.exe scripts/compare_reference_pipeline.py --output-dir artifacts/phase5/new_research_run --with-research-data --threads 2
```

Use a new output directory each time. The first command runs dependency checks,
lint/format/types, all non-PostgreSQL non-benchmark tests, contract/specification
checks, synthetic five-fold parity, and wheel/source builds. CI uses synthetic
data and does not need the private CSV.

The opt-in local comparison verifies the raw dataset/split hashes and alignment,
then compares the legacy parser against predictor frames emitted by the trusted
adapter. Both paths use the same five folds, seeds and model parameters, with an
explicit two-thread resource limit. Before fitting it freezes zero matrix
tolerance and `1e-12` absolute prediction/metric tolerance. It compares per-fold
selected features, exclusions, matrices, predictions, OOF coverage, AP/ROC-AUC,
and deterministic top-K membership. Each fold publishes aggregate evidence and
membership hashes. The saved holdout never enters fitting or prediction.

These comparisons establish refactor parity in the recorded environment. They
do not establish future-period fraud detection, fairness or qualified-use approval.
