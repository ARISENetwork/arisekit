from __future__ import annotations

from pathlib import Path

import pytest

from arisekit.evaluation.annotation_contract import (
    AnnotationAssignment,
    AnnotationExecutionSpec,
    AnnotationLabel,
    AnnotationResultBundle,
    StudyAnnotationPolicy,
    load_study_policy,
    write_study_policy,
)


def _policy(panel_size: int = 2) -> StudyAnnotationPolicy:
    return StudyAnnotationPolicy(
        population="board-certified emergency physicians",
        credential_requirements={"specialty": "emergency medicine"},
        panel_size_per_item=panel_size,
        calibration_policy={"battery": "calibration-v1", "pass": 0.8},
        irr_method="krippendorff-alpha",
        irr_threshold=0.75,
        adjudication_policy={"role": "senior-clinician", "below_threshold": True},
    )


def test_annotation_operations_reference_methodology_without_redefining_it() -> None:
    policy = _policy()
    execution = AnnotationExecutionSpec(
        annotation_id="pass-1",
        study_policy_digest=policy.digest,
        item_bundle_digest="b" * 64,
        assignments=(
            AnnotationAssignment("case-1", "rater-1"),
            AnnotationAssignment("case-1", "rater-2"),
        ),
        output_artifact="annotation-results.json",
    )
    execution.validate_against(policy)

    result = AnnotationResultBundle(
        annotation_execution_digest=execution.digest,
        study_policy_digest=policy.digest,
        item_bundle_digest="b" * 64,
        labels=(
            AnnotationLabel(
                item_id="case-1",
                label={"answer": "admit"},
                irr_value=0.81,
                adjudicated=False,
            ),
        ),
    )
    assert result.to_dict()["study_policy_digest"] == policy.digest


def test_annotation_rejects_an_undersized_operational_assignment() -> None:
    policy = _policy(panel_size=3)
    execution = AnnotationExecutionSpec(
        annotation_id="pass-1",
        study_policy_digest=policy.digest,
        item_bundle_digest="b" * 64,
        assignments=(
            AnnotationAssignment("case-1", "rater-1"),
            AnnotationAssignment("case-1", "rater-2"),
        ),
        output_artifact="annotation-results.json",
    )
    with pytest.raises(ValueError, match="panel_size_per_item"):
        execution.validate_against(policy)


def test_study_policy_round_trips_canonical_json(tmp_path: Path) -> None:
    policy = _policy()
    path = write_study_policy(tmp_path / "annotation-study-policy.json", policy)
    loaded = load_study_policy(path)
    assert loaded == policy
    assert loaded.digest == policy.digest
