# Phase 6 training and evaluation

The operational service trains research candidates from accepted, published
research batches. It reloads the encrypted intake bytes, verifies the registered
dataset and saved split, separates predictors and labels, and enforces development
membership before fitting. The current CSV cannot enter qualified temporal
training. Changing the CLI mode, manifest tier or report name cannot qualify it.

## Operational CLI

Use the same local runtime connection, protected artifact key and settings as
Phase 4. Train requires an accepted batch ID and a caller-generated run UUID:

```powershell
python -m mule_detection.cli train --config config/model_candidates.yaml --mode research --batch-id <accepted-batch-uuid> --run-id <new-run-uuid>
python -m mule_detection.cli evaluate --run-id <run-uuid>
```

Both operations pass through the local training service's permission boundary.
Shared authenticated access and qualified source adapters remain future work.
`qualified_temporal` is an explicit mode and fails before building adapters for
the current research source. Config paths must remain inside the application root.

Training is synchronous in this phase. Evidence state is durable on disk, with
RUNNING/FAILED/SUCCEEDED outcomes; no background scheduler or automatic resume is
claimed. A successful exact retry returns the original run after rechecking
acceptance and input identity. Reuse with changed actor/config/data/code/policy
conflicts. A failed/interrupted run requires a new UUID, preserving earlier
evidence. A batch acceptance change during training prevents final publication.

## Models, splits and selection

`config/model_candidates.yaml` declares seeds, CPU limits, folds, top-K budgets,
bootstrap repetitions and all candidate parameters. Logistic regression uses
balanced classes and training-fitted numeric scaling without centering; one-hot
columns are unchanged and sparse matrices remain sparse. LightGBM preserves the
reference settings with an explicit thread cap. Convergence warnings fail a
candidate fit rather than silently publishing unfinished optimization.

Both families use identical outer folds and record-key membership. A fresh
Phase 5 pipeline is fitted for every model. Multi-configuration families tune
only inside the outer training fold using mean inner-fold AP. A predeclared
single configuration records its reserved inner plan and skips unnecessary
tuning fits. After outer evaluation, final configuration selection runs only
on development data; a version-bound frozen selection records the config,
feature policy, data hash and timestamp. Family selection uses the declared
mean outer-fold AP comparison. Its results remain selection-affected research
diagnostics, not untouched acceptance estimates.

Ranks use descending score then ascending record key. AP, ROC-AUC, selected
positives, Precision/Recall@K and lift have explicit empty/single-class behavior;
undefined statistics are null. K is capped by cohort size. Group bootstrap
intervals record valid and invalid resamples. Research groups are opaque research
record keys, not verified accounts. Fold metrics are reported alongside pooled
OOF diagnostics because different fold models can have different score scales.

## Time, labels and qualified prerequisites

The label selector considers only versions available/observed by the cutoff.
Known immature corrections invalidate obsolete labels; future corrections do
not alter earlier selections. Snapshots must precede outcomes and have been
available by the cutoff. Counters distinguish unknown, immature, corrected,
policy-negative and ineligible feature-time cases.

`select_repository_labels` filters durable label metadata by known-at in SQL,
then resolves certified contracts through an injected trusted outcome-owner
adapter. Existing database metadata alone cannot certify outcome windows,
adjudication or maturity. Phase 9 must supply actual adjudicated outcomes; the
research path continues to use its explicitly unverified legacy target.

Temporal partition construction supports half-open train/tuning/calibration/
acceptance windows, configured purge gaps, mature known labels, connected
account/entity exclusion and per-record exclusion reasons. Invalid windows or
partitions without both mature classes fail. The independent acceptance guard
requires a matching frozen configuration before label release and rejects reused
or training releases. Controlled release access/inspection registration remains
Phase 13 work; no final-acceptance CLI is exposed here.

Qualified training still requires trusted source/identity/dictionary/availability/
label/prevalence/policy evidence and a certified feature pipeline. The current
legacy feature rules reject qualified fitting. The qualified controls are tested
with synthetic certified-contract fixtures; this is not real source qualification.

## Probes, ablations and calibration

Cohort reports include class counts, per-feature missingness gaps and a bounded
cross-validated source-predictability probe based on missing-cell count/fraction.
They cannot establish causal feature meaning. Approved explicit ablations refit
on the same folds; approved subgroup definitions report global queue selection
burden, denominators and uncertainty. Small samples are suppressed and research
results remain inconclusive; no anonymous value is inferred to be a protected
identity and no fairness certification is issued.

Research output is review priority. Calibration is blocked for current data.
The qualified calibration utility requires representative evidence and disjoint
fit/validation/base-training/selection/acceptance keys and groups. It stores a
Platt mapping, lineage and held-out Brier/reliability results. Callers must derive
those memberships from trusted split and label controls, not client declarations.

## Artifacts and verification

Per-fold membership, search trials, fitted models, predictions, signatures,
configuration, environment/source hashes, metrics, probes and the model card are
AES-GCM encrypted. Files are flushed before the authenticated manifest and final
state pointer. The storage root/key require protected host permissions; temporary
input CSV plaintext is removed after parsing. A failed run retains partial fold
evidence and cannot be evaluated as complete. Evaluation authenticates artifacts
and recomputes OOF metrics from JSON without deserializing executable models.

Candidates are not Phase 7 approved bundles. The current loader exposes no
arbitrary model-upload or scoring API. Training's final acceptance/audit check
and filesystem finalization are separate durable boundaries: a crash between
them leaves RUNNING evidence requiring a new run and later cleanup, not an
approved model. Retention/backup/recovery remains subject to later operations work.

```powershell
python scripts/verify_training.py --output-dir artifacts/phase6/new_synthetic_run
python scripts/verify_training.py --connections-file secrets/DEDICATED_TEST_CONNECTIONS.json --output-dir artifacts/phase6/new_postgres_run
python scripts/run_training_experiment.py --with-research-data --output-dir artifacts/phase6/new_local_research_run
```

Use new directories. Verification uses synthetic data; dedicated database guards
remain mandatory. The optional research command checks the numerical runner on
hash-verified development inputs and stores private evidence under ignored,
encrypted `var/artifacts/training_verification`. It is distinct from operational
accepted-batch training. Public evidence contains aggregate metrics and hashes,
never row-level labels, predictions, raw inputs or serialized models. CI uses
synthetic inputs and needs no private dataset or artifact key.
