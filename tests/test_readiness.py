"""Parity readiness is evidence-derived and hash-stable."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from arisekit.readiness import (
    AnalysisReadiness,
    ClinicalReviewReadiness,
    ParityReadinessRecord,
    SourceSimilarityReadiness,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _record() -> ParityReadinessRecord:
    return ParityReadinessRecord(
        generated_bundle_hash=_hash("bundle"),
        clinical_review=ClinicalReviewReadiness(
            review_artifact_hash=_hash("clinical"),
            reviewer_ids=("reviewer-a", "reviewer-b"),
            adjudicator_id="reviewer-c",
            reviewed_family_count=30,
            expected_family_count=30,
            critical_defect_count=0,
            unresolved_disagreement_count=0,
        ),
        source_similarity=SourceSimilarityReadiness(
            report_hash=_hash("similarity"),
            analysis_code_hash=_hash("code"),
            representation_schema_hash=_hash("schema"),
            similarity_metric="prespecified-cosine",
            comparison_count=30,
            rejection_threshold=0.8,
            maximum_observed_similarity=0.4,
        ),
        analysis=AnalysisReadiness(
            same_vs_same_report_hash=_hash("same-vs-same"),
            level_margin_lower=-0.05,
            level_margin_upper=0.05,
            maximum_profile_distance=0.05,
            bootstrap_draws=10_000,
            bootstrap_seed=17,
            clinical_approver="clinical-approver",
            statistical_approver="statistical-approver",
            approved_at="2026-07-22T00:00:00Z",
        ),
    )


def test_readiness_round_trips_and_derives_flags() -> None:
    record = _record()
    restored = ParityReadinessRecord.from_dict(record.to_dict())

    assert restored == record
    assert restored.ready is True
    assert restored.blockers == ()
    assert restored.digest == record.digest


def test_clinical_and_similarity_failures_cannot_claim_ready() -> None:
    record = _record()
    blocked = replace(
        record,
        clinical_review=replace(
            record.clinical_review,
            unresolved_disagreement_count=1,
        ),
        source_similarity=replace(
            record.source_similarity,
            maximum_observed_similarity=0.9,
        ),
    )
    assert blocked.ready is False
    assert blocked.blockers == ("clinical-review", "source-similarity")

    payload = blocked.to_dict()
    payload["ready"] = True
    with pytest.raises(ValueError, match="does not match"):
        ParityReadinessRecord.from_dict(payload)


def test_review_and_analysis_require_independent_people() -> None:
    with pytest.raises(ValueError, match="independent"):
        replace(_record().clinical_review, adjudicator_id="reviewer-a")
    with pytest.raises(ValueError, match="distinct"):
        replace(
            _record().analysis,
            statistical_approver="clinical-approver",
        )


def test_readiness_rejects_strings_masquerading_as_arrays() -> None:
    payload = _record().to_dict()
    payload["clinical_review"]["reviewer_ids"] = "reviewer-a"
    with pytest.raises(ValueError, match="JSON array"):
        ParityReadinessRecord.from_dict(payload)

    payload = _record().to_dict()
    payload["blockers"] = ""
    with pytest.raises(ValueError, match="JSON array"):
        ParityReadinessRecord.from_dict(payload)
