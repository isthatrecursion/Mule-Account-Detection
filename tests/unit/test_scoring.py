from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from mule_detection.domain.contracts.scoring import ScoringRequest
from mule_detection.domain.errors import DomainError
from mule_detection.explanations.contributions import contributions
from mule_detection.explanations.evidence_builder import build_evidence
from mule_detection.features.pipeline import FeaturePipeline
from mule_detection.scoring.ranking import ReviewPolicy, rank_scores
from mule_detection.scoring.result_validator import collect_scores
from mule_detection.training.evaluation_policy import ModelSpec
from mule_detection.training.model_factory import fit_candidate
from tests.unit.test_training import training_data as training_data

ROOT = Path(__file__).resolve().parents[2]


def test_hand_calculated_ties_singleton_empty_and_global_correction():
    policy = replace(ReviewPolicy.load(ROOT / "config/review_policy.yaml"), top_k=2)
    scores = {"c": 0.2, "b": 0.9, "a": 0.9, "d": 0.1}
    rows = rank_scores(scores, policy)
    assert [r["record_key"] for r in rows] == ["a", "b", "c", "d"]
    assert [r["percentile"] for r in rows] == [100, 200 / 3, 100 / 3, 0]
    assert [r["selected"] for r in rows] == [True, True, False, False]
    changed = rank_scores({**scores, "d": 0.95}, policy)
    assert [r["record_key"] for r in changed[:2]] == ["d", "a"]
    assert {r["record_key"]: r["raw_score"] for r in changed if r["record_key"] != "d"} == {
        k: v for k, v in scores.items() if k != "d"
    }
    assert rank_scores({}, policy) == []
    assert rank_scores({"only": 0.0}, policy)[0]["percentile"] == 100


@pytest.mark.parametrize(
    "rows,keys",
    [
        ([("a", float("nan"))], ("a",)),
        ([("a", float("inf"))], ("a",)),
        ([("a", -0.1)], ("a",)),
        ([("a", 0.1), ("a", 0.1)], ("a",)),
        ([], ("a",)),
        ([("b", 0.1)], ("a",)),
    ],
)
def test_bad_scores_never_rank(rows, keys):
    with pytest.raises(DomainError):
        collect_scores(rows, keys)


@pytest.mark.parametrize("family", ["lightgbm", "logistic"])
def test_contributions_reconcile_and_anonymous_imputed_unseen_facts(training_data, family):
    fitted = fit_candidate(
        FeaturePipeline.from_repository(ROOT),
        ModelSpec(name="case", family=family, n_estimators=5),
        training_data.X,
        training_data.target,
        seed=42,
        threads=2,
    )
    frame = training_data.X.iloc[:4].copy()
    frame.iloc[0, frame.columns.get_loc("category_under_score")] = "unseen_category"
    output = contributions(fitted, frame)
    np.testing.assert_allclose(
        np.sum(output["values"], axis=1) + output["base_values"], output["raw_margins"], atol=1e-8
    )
    facts = build_evidence(fitted, frame)
    assert facts[0]["scale"] == "raw_margin"
    by_raw = {r["raw_feature"]: r for r in facts[0]["raw_aggregates"]}
    assert by_raw["optional"]["value_status"] == "IMPUTED"
    assert by_raw["optional"]["observed_value"] is None
    assert by_raw["category_under_score"]["unseen_category"]
    assert all(
        r["display_name"] == r["raw_feature"] and r["meaning_status"] == "UNVERIFIED"
        for r in by_raw.values()
    )
    assert sum(r["contribution"] for r in facts[0]["encoded_detail"]) == pytest.approx(
        sum(r["contribution"] for r in by_raw.values())
    )


def test_request_never_accepts_arbitrary_inputs_or_unlinked_replay():
    from uuid import uuid4

    fields = {"batch_id": uuid4(), "bundle_digest": "a" * 64, "environment": "test"}
    with pytest.raises(ValidationError):
        ScoringRequest(**fields, raw_scores={"a": 0.1})
    with pytest.raises(ValidationError):
        ScoringRequest(**fields, replay_id=uuid4())


def test_cli_dispatches_validated_scoring_and_rejects_non_digest_model(
    app_root, monkeypatch, capsys
):
    import json
    from uuid import uuid4

    from mule_detection.cli import main

    job, run, batch = uuid4(), uuid4(), uuid4()

    class Fake:
        def create(self, request, context):
            assert request.batch_id == batch and request.bundle_digest == "a" * 64
            return {"job_id": str(job), "run_id": str(run), "state": "STAGED"}

        def run(self, identity, context):
            assert identity == job
            return {"job_id": str(job), "run_id": str(run), "state": "COMPLETE"}

    monkeypatch.setattr(
        "mule_detection.application.scoring_bootstrap.build_scoring", lambda _: Fake()
    )
    assert (
        main(
            [
                "--root",
                str(app_root),
                "score",
                "--batch-id",
                str(batch),
                "--model-version",
                "a" * 64,
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["state"] == "COMPLETE"
    assert (
        main(
            [
                "--root",
                str(app_root),
                "score",
                "--batch-id",
                str(batch),
                "--model-version",
                "arbitrary-model-path",
            ]
        )
        == 5
    )
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "CONTRACT_INVALID"
