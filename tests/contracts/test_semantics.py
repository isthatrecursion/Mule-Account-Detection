from copy import deepcopy
from datetime import UTC, datetime

import pytest

from mule_detection.application.context import ExecutionContext
from mule_detection.application.review_requests import author_review
from mule_detection.domain.contracts.common import parse_contract
from mule_detection.domain.contracts.events import (
    CompletenessManifest,
    TransactionEvent,
    validate_completeness,
    validate_event_progress,
)
from mule_detection.domain.contracts.evidence import Evidence, validate_evidence
from mule_detection.domain.contracts.feature_dictionary import FeatureDictionary
from mule_detection.domain.contracts.jobs import Job, validate_job_transition
from mule_detection.domain.contracts.labels import QualifiedLabel, select_label_as_of
from mule_detection.domain.contracts.models import ModelBundle
from mule_detection.domain.contracts.reviews import ReviewRequest, validate_review_transition
from mule_detection.domain.contracts.scores import ScoreRow
from mule_detection.domain.contracts.snapshot import (
    QualifiedSnapshot,
    SourceRegistry,
    merge_snapshots,
)
from mule_detection.domain.errors import DomainError, ErrorCode
from mule_detection.settings import read_yaml
from tests.contracts.helpers import ROOT, payload


def test_sources_merge_only_when_ownership_grain_cutoffs_and_coverage_agree():
    registry = payload("source_registry_v1")
    registry["sources"].append(
        dict(registry["sources"][0], source_id="synthetic-other", feature_ids=["S2"])
    )
    source = payload("qualified_snapshot_v1")
    other = deepcopy(source)
    other.update(source_id="synthetic-other", features={"S2": 2.0})
    other["source_coverage"][0]["source_id"] = "synthetic-other"
    server = parse_contract(SourceRegistry, registry)
    merged = merge_snapshots(
        tuple(parse_contract(QualifiedSnapshot, item) for item in (source, other)), server
    )
    assert merged.features == {"S1": 1.0, "S2": 2.0} and merged.completeness == "COMPLETE"
    assert len(merged.source_coverage) == 2 and len(merged.source_snapshot_ids) == 2
    for field, value, code in [
        ("account_id", "different-account", ErrorCode.IDENTITY_CONFLICT),
        ("observation_start", "2025-12-31T00:00:00Z", ErrorCode.CUTOFF_MISMATCH),
    ]:
        bad = deepcopy(other)
        bad[field] = value
        if field == "observation_start":
            bad["source_coverage"][0]["window_start"] = value
        with pytest.raises(DomainError) as result:
            merge_snapshots(
                (parse_contract(QualifiedSnapshot, source), parse_contract(QualifiedSnapshot, bad)),
                server,
            )
        assert result.value.code == code
    other["source_coverage"][0]["status"] = "INCOMPLETE"
    assert (
        merge_snapshots(
            (parse_contract(QualifiedSnapshot, source), parse_contract(QualifiedSnapshot, other)),
            server,
        ).completeness
        == "INCOMPLETE"
    )


def test_missing_source_partition_or_empty_real_registry_cannot_qualify():
    source = parse_contract(QualifiedSnapshot, payload("qualified_snapshot_v1"))
    actual = parse_contract(SourceRegistry, read_yaml(ROOT / "config/source_registry.yaml"))
    assert actual.sources == ()
    with pytest.raises(DomainError):
        merge_snapshots((source,), actual)
    definition = payload("source_registry_v1")
    definition["sources"][0]["required_partitions"].append("p1")
    with pytest.raises(DomainError) as result:
        merge_snapshots((source,), parse_contract(SourceRegistry, definition))
    assert result.value.code == ErrorCode.COMPLETENESS_INVALID


def test_maturity_correction_knowledge_time_and_history_are_enforced():
    first = parse_contract(QualifiedLabel, payload("label_v1"))
    assert select_label_as_of((first,), datetime(2026, 1, 1, tzinfo=UTC)) is None
    assert select_label_as_of((first,), datetime(2026, 1, 2, tzinfo=UTC)) == first
    correction = payload("label_v1")
    correction.update(
        label_id="00000000-0000-4000-8000-000000000002",
        value=0,
        version=2,
        supersedes=str(first.label_id),
        observed_at="2026-01-03T00:00:00Z",
        available_at="2026-01-03T00:00:00Z",
        mature_at="2026-01-04T00:00:00Z",
    )
    second = parse_contract(QualifiedLabel, correction)
    assert select_label_as_of((first, second), datetime(2026, 1, 2, tzinfo=UTC)) == first
    assert select_label_as_of((first, second), datetime(2026, 1, 3, tzinfo=UTC)) is None
    assert select_label_as_of((first, second), datetime(2026, 1, 4, tzinfo=UTC)) == second
    with pytest.raises(DomainError):
        select_label_as_of((second,), datetime(2026, 1, 4, tzinfo=UTC))
    unreviewed = payload("label_v1")
    unreviewed.update(status="UNREVIEWED", value=None, adjudication_reference=None)
    assert (
        select_label_as_of(
            (parse_contract(QualifiedLabel, unreviewed),), datetime(2026, 1, 4, tzinfo=UTC)
        )
        is None
    )


def test_dictionary_and_evidence_never_promote_an_eda_nickname():
    data = payload("feature_dictionary_v1")
    data["entries"][0].update(status="PROVISIONAL", display_name="Informal EDA nickname")
    dictionary = parse_contract(FeatureDictionary, data)
    assert dictionary.display("S1") == "S1" and dictionary.display("UNKNOWN_ID") == "UNKNOWN_ID"
    evidence = payload("evidence_v1")
    evidence["observations"][0]["dictionary_status"] = "PROVISIONAL"
    bundle = parse_contract(ModelBundle, payload("model_bundle_v1"))
    # Contributions may be raw-margin values even when the displayed output is a ranking scale.
    different_output_scale = parse_contract(
        ModelBundle, dict(payload("model_bundle_v1"), output_scale="review_priority")
    )
    validate_evidence(parse_contract(Evidence, evidence), dictionary, different_output_scale)
    validate_evidence(parse_contract(Evidence, evidence), dictionary, bundle)
    data["entries"][0].update(status="CERTIFIED")
    with pytest.raises(DomainError) as result:
        parse_contract(FeatureDictionary, data)
    assert result.value.code == ErrorCode.DICTIONARY_UNCERTIFIED
    data["entries"][0].update(
        unit="synthetic-unit",
        source_table="synthetic-table",
        calculation_window="[start,end)",
        availability_rule="before_snapshot",
        approval_reference="SYNTHETIC_NOT_REAL_APPROVAL",
    )
    certified = parse_contract(FeatureDictionary, data)
    evidence["observations"][0].update(
        dictionary_status="CERTIFIED", display_name=certified.display("S1")
    )
    validate_evidence(parse_contract(Evidence, evidence), certified, bundle)
    with pytest.raises(DomainError):
        validate_evidence(parse_contract(Evidence, evidence), dictionary, bundle)


def test_unavailable_and_unknown_research_time_are_explicit():
    data = payload("score_v1")
    for field in (
        "raw_score",
        "rank",
        "percentile",
        "cohort_id",
        "evidence_reference",
        "assessed_as_of",
        "published_at",
    ):
        data[field] = None
    data.update(freshness="UNAVAILABLE", completeness="UNKNOWN", source_coverage=[])
    assert parse_contract(ScoreRow, data).raw_score is None
    for field, value in [
        ("raw_score", 0.0),
        ("rank", 1),
        ("assessed_as_of", "2026-01-01T00:00:00Z"),
    ]:
        with pytest.raises(DomainError):
            parse_contract(ScoreRow, dict(data, **{field: value}))
    research = payload("score_v1")
    research.update(
        data_tier="research",
        assessed_as_of=None,
        source_coverage=[],
        completeness="UNKNOWN",
        freshness="STALE",
        provenance_limitations=["Historical cutoff unknown"],
    )
    assert parse_contract(ScoreRow, research).assessed_as_of is None
    with pytest.raises(DomainError):
        parse_contract(ScoreRow, dict(research, freshness="COMPLETE"))
    with pytest.raises(DomainError):
        parse_contract(ScoreRow, dict(research, raw_score=float("inf")))


def test_events_use_minor_units_and_explicit_corrections_and_epoch_approval():
    first = parse_contract(TransactionEvent, payload("event_v1"))
    validate_event_progress(
        first, previous=None, approved_epoch="epoch-1", max_clock_skew_seconds=30
    )
    for changes in [
        {"amount_minor": -1},
        {"amount_minor": 1.5},
        {"event_type": "REVERSAL"},
        {"currency": "INR;DROP"},
    ]:
        with pytest.raises(DomainError):
            parse_contract(TransactionEvent, dict(payload("event_v1"), **changes))
    reversal = dict(
        payload("event_v1"),
        event_id="synthetic-reversal",
        event_type="REVERSAL",
        reversal_of=first.event_id,
        source_sequence=2,
    )
    assert parse_contract(TransactionEvent, reversal).reversal_of == first.event_id
    restarted = parse_contract(
        TransactionEvent, dict(payload("event_v1"), sequence_epoch="epoch-2")
    )
    validate_event_progress(
        restarted, previous=first, approved_epoch="epoch-2", max_clock_skew_seconds=30
    )
    with pytest.raises(DomainError):
        validate_event_progress(
            restarted, previous=first, approved_epoch="epoch-1", max_clock_skew_seconds=30
        )


def test_completeness_requires_actual_contiguous_source_contents():
    manifest = parse_contract(CompletenessManifest, payload("completeness_v1"))
    event = parse_contract(TransactionEvent, payload("event_v1"))
    validate_completeness(manifest, (event,))
    for events in [(), (event, event)]:
        with pytest.raises(DomainError):
            validate_completeness(manifest, events)
    huge = dict(
        payload("completeness_v1"), expected_count=10**15, contiguous_committed_sequence=10**15
    )
    with pytest.raises(DomainError):
        validate_completeness(parse_contract(CompletenessManifest, huge), (event,))


def test_complete_score_coverage_cannot_end_before_its_assessment_cutoff():
    data = payload("score_v1")
    data["assessed_as_of"] = data["published_at"] = "2026-01-03T00:00:00Z"
    with pytest.raises(DomainError) as result:
        parse_contract(ScoreRow, data)
    assert result.value.code == ErrorCode.SCORE_STATE_INVALID


def test_workflow_states_are_not_labels_approval_or_freshness():
    job = parse_contract(Job, payload("job_v1"))
    assert job.state == "SUCCEEDED" and job.data_tier == "research"
    for pair in [("PENDING", "RUNNING"), ("RUNNING", "SUCCEEDED"), ("RUNNING", "FAILED")]:
        validate_job_transition(*pair)
    for pair in [("FAILED", "PENDING"), ("SUCCEEDED", "RUNNING")]:
        with pytest.raises(DomainError):
            validate_job_transition(*pair)
    request = parse_contract(ReviewRequest, payload("review_v1"))
    context = ExecutionContext.create("trusted-synthetic-actor", "test")
    assert author_review(request, context).actor_id == context.actor_id
    with pytest.raises(DomainError):
        parse_contract(ReviewRequest, dict(payload("review_v1"), actor_id="forged"))
    for pair, permission in [
        (("QUEUED", "ASSIGNED"), "case:assign"),
        (("ASSIGNED", "IN_REVIEW"), "case:review"),
        (("IN_REVIEW", "REVIEWED"), "case:review"),
        (("REVIEWED", "ASSIGNED"), "case:reopen"),
    ]:
        validate_review_transition(*pair, frozenset([permission]))
        with pytest.raises(DomainError):
            validate_review_transition(*pair, frozenset())
    with pytest.raises(DomainError):
        validate_review_transition("QUEUED", "REVIEWED", frozenset(["case:review"]))
