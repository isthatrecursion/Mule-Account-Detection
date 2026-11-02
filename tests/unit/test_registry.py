from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from mule_detection.domain.errors import DomainError
from mule_detection.domain.model_lifecycle import require_transition
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.registry.bundle_loader import BundleLoader
from mule_detection.registry.bundle_writer import BundleStore, write_bundle
from mule_detection.registry.promotion_policy import PromotionEvidence, promotion_gate
from mule_detection.training.evaluation_policy import ModelSpec, TrainingConfig
from mule_detection.training.final_fit import fit_frozen_research
from mule_detection.training.report import RunStore, encode, sha256
from mule_detection.training.runner import run_experiment
from tests.unit.test_training import training_data as training_data

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def final_fit(training_data, tmp_path):
    data = training_data
    config = TrainingConfig(
        outer_folds=2,
        inner_folds=2,
        bootstrap_repetitions=20,
        candidates=(ModelSpec(name="tree", family="lightgbm", n_estimators=5),),
    )
    runs = RunStore(tmp_path / "runs", b"x" * 32)
    run_id = uuid4()
    prototype = FeaturePipeline.from_repository(ROOT)
    run_experiment(
        data,
        prototype,
        config,
        runs,
        run_id,
        actor_id="engineer",
        environment={"scope": "synthetic"},
    )
    fitted, lineage = fit_frozen_research(data, prototype, runs, run_id)
    return data, runs, run_id, fitted, lineage


def test_final_fit_is_fresh_and_fingerprint_bound(final_fit):
    data, runs, run_id, fitted, lineage = final_fit
    assert lineage["training_rows"] == len(data.keys)
    assert lineage["demo_predictions_are_in_sample"] and not lineage["qualified_promotion_allowed"]
    changed = data.X.copy()
    changed.iloc[0, 0] += 100
    with pytest.raises(DomainError):
        fit_frozen_research(
            replace(data, X=changed), FeaturePipeline.from_repository(ROOT), runs, run_id
        )


def test_bundle_roundtrip_in_worker_and_inference_does_not_mutate(final_fit, tmp_path):
    data, _, _, fitted, lineage = final_fit
    store = BundleStore(tmp_path / "bundles", b"z" * 32)
    digest = write_bundle(fitted, lineage, data.X.iloc[:3], store, root=ROOT)
    before = {p.name: sha256(p.read_bytes()) for p in store.path(digest).iterdir()}
    loader = BundleLoader(store, lambda d, e: d == digest and e == "research")
    loaded = loader.load(digest, "research")
    np.testing.assert_allclose(
        loaded.predict_score(data.X.iloc[:5]),
        fitted.predict_score(data.X.iloc[:5]),
        atol=1e-12,
        rtol=0,
    )
    assert before == {p.name: sha256(p.read_bytes()) for p in store.path(digest).iterdir()}
    with pytest.raises(DomainError):
        loader.load(digest, "qualified")
    loader.authorize = lambda *_: False
    with pytest.raises(DomainError):
        loaded.predict_score(data.X.iloc[:1])


def test_manifest_tampering_cannot_replace_independently_pinned_digest(final_fit, tmp_path):
    data, _, _, fitted, lineage = final_fit
    store = BundleStore(tmp_path / "bundles", b"z" * 32)
    digest = write_bundle(fitted, lineage, data.X.iloc[:3], store, root=ROOT)
    path = store.path(digest) / "bundle.json"
    manifest = json.loads(path.read_bytes())
    manifest["contract"]["model_tier"] = "candidate"
    path.write_bytes(encode(manifest))
    loader = BundleLoader(store, lambda d, e: d == digest)
    with pytest.raises(DomainError):
        loader.load(digest, "research")
    with pytest.raises(DomainError):
        loader.load(sha256(path.read_bytes()), "research")


@pytest.mark.parametrize("case", ["missing", "corrupt", "runtime", "signature"])
def test_invalid_bundle_failure_paths(final_fit, tmp_path, case):
    data, _, _, fitted, lineage = final_fit
    store = BundleStore(tmp_path / "bundles", b"z" * 32)
    digest = write_bundle(fitted, lineage, data.X.iloc[:3], store, root=ROOT)
    directory = store.path(digest)
    if case == "missing":
        (directory / "model.joblib.enc").unlink()
    elif case == "corrupt":
        path = directory / "model.joblib.enc"
        path.write_bytes(path.read_bytes() + b"corrupt")
    else:
        manifest = json.loads((directory / "bundle.json").read_bytes())
        if case == "runtime":
            manifest["contract"]["runtime_versions"]["scikit-learn"] = "incompatible"
        else:
            manifest["contract"]["input_signature"] = "f" * 64
            manifest["input_signature_hash"] = "f" * 64
        payload = encode(manifest)
        (directory / "bundle.json").write_bytes(payload)
        new = sha256(payload)
        directory.rename(store.path(new))
        digest = new
    with pytest.raises(DomainError):
        BundleLoader(store, lambda *_: True).load(digest, "research")


def test_perfect_research_metrics_do_not_qualify_a_model():
    evidence = PromotionEvidence(
        data_tier="research",
        bound_bundle_digest="a" * 64,
        metrics_passed=True,
        independent_acceptance_passed=True,
        permitted_environments=("qualified",),
    )
    gate = promotion_gate(
        evidence, digest="a" * 64, environment="qualified", target="APPROVED_FOR_PILOT"
    )
    assert (
        gate["status"] == "BLOCKED" and "QUALIFIED_DATA_AND_ENVIRONMENT_REQUIRED" in gate["reasons"]
    )
    assert (
        promotion_gate(evidence, digest="a" * 64, environment="research", target="RESEARCH_DEMO")[
            "status"
        ]
        == "PASSED"
    )
    with pytest.raises(DomainError):
        require_transition("CANDIDATE", "APPROVED_FOR_SHADOW", trainer="same", reviewer="same")
    with pytest.raises(DomainError):
        require_transition("RETIRED", "RESEARCH_DEMO", trainer="a", reviewer="b")
