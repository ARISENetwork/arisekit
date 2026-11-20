"""Clinical release decisions are derived from frozen, artifact-bound evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from arisekit.evaluation.clinical_validation import (
    AdjudicationBundle,
    AdjudicationRecord,
    ClinicalValidationGate,
    ClinicianAssignment,
    ClinicianSamplingPlan,
    ClinicianValidationObservation,
    CriterionThresholds,
    EscalationRules,
    FrozenValidationPlan,
    ObservedValidationResults,
    RandomAuditRules,
    StratificationCell,
    ValidationVerdict,
    evaluate_clinical_validation,
    load_adjudications,
    load_validation_plan,
    load_validation_results,
    required_adjudication_ids,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _plan(
    *,
    thresholds: CriterionThresholds | None = None,
) -> FrozenValidationPlan:
    opaque_ids = ("opaque-01", "opaque-02", "opaque-03", "opaque-04")
    return FrozenValidationPlan(
        study_artifact_hash=_hash("study"),
        response_review_artifact_hash=_hash("response-review"),
        pair_review_artifact_hash=_hash("pair-review"),
        stratification_cells=(
            StratificationCell(
                cell_id="cardiology-representative-invariant",
                specialty="Cardiology",
                cohort="representative",
                relationship="invariant",
                opaque_ids=opaque_ids[:2],
            ),
            StratificationCell(
                cell_id="emergency-stress-differentiated",
                specialty="Emergency medicine",
                cohort="stress",
                relationship="differentiated",
                opaque_ids=opaque_ids[2:],
            ),
        ),
        clinician_sampling=ClinicianSamplingPlan(
            method="stratified-random",
            selection_seed=73,
            reviewer_ids=("clinician-a", "clinician-b"),
            reviewers_per_item=2,
            assignments=tuple(
                ClinicianAssignment(
                    opaque_id=opaque_id,
                    reviewer_ids=("clinician-a", "clinician-b"),
                )
                for opaque_id in opaque_ids
            ),
        ),
        thresholds=thresholds
        or CriterionThresholds(
            minimum_agreement=0.8,
            minimum_severe_error_sensitivity=0.75,
            minimum_severe_error_specificity=0.75,
            maximum_harmful_action_false_negative_rate=0.25,
            maximum_critical_omission_false_negative_rate=0.25,
            maximum_continuous_score_mae=0.5,
            continuous_score_minimum=0,
            continuous_score_maximum=4,
            minimum_severe_error_positives=1,
            minimum_severe_error_negatives=1,
            minimum_harmful_action_positives=1,
            minimum_critical_omission_positives=1,
        ),
        escalation=EscalationRules(
            adjudicator_ids=("adjudicator-a",),
            adjudicators_per_item=1,
            escalate_acceptability_disagreement=True,
            escalate_severe_error_disagreement=True,
            escalate_harmful_action_disagreement=True,
            escalate_critical_omission_disagreement=True,
            continuous_score_absolute_difference=0.5,
        ),
        random_audit=RandomAuditRules(
            fraction_per_cell=0.25,
            minimum_per_cell=1,
            random_seed=911,
        ),
        clinical_approver_id="clinical-approver",
        statistical_approver_id="statistical-approver",
        frozen_at="2026-07-23T12:00:00Z",
    )


_TRUTH = {
    "opaque-01": (True, False, False, False, 4.0),
    "opaque-02": (False, True, True, False, 1.0),
    "opaque-03": (False, True, False, True, 1.0),
    "opaque-04": (True, False, False, False, 4.0),
}


def _cell_id(opaque_id: str) -> str:
    return (
        "cardiology-representative-invariant"
        if opaque_id in {"opaque-01", "opaque-02"}
        else "emergency-stress-differentiated"
    )


def _observation(
    opaque_id: str,
    reviewer_id: str,
    *,
    clinician: tuple[bool, bool, bool, bool, float] | None = None,
    evaluator: tuple[bool, bool, bool, bool, float] | None = None,
) -> ClinicianValidationObservation:
    clinician_values = clinician or _TRUTH[opaque_id]
    evaluator_values = evaluator or _TRUTH[opaque_id]
    return ClinicianValidationObservation(
        opaque_id=opaque_id,
        cell_id=_cell_id(opaque_id),
        reviewer_id=reviewer_id,
        clinician_acceptable=clinician_values[0],
        clinician_severe_error=clinician_values[1],
        clinician_harmful_action=clinician_values[2],
        clinician_critical_omission=clinician_values[3],
        clinician_continuous_score=clinician_values[4],
        evaluator_acceptable=evaluator_values[0],
        evaluator_severe_error=evaluator_values[1],
        evaluator_harmful_action=evaluator_values[2],
        evaluator_critical_omission=evaluator_values[3],
        evaluator_continuous_score=evaluator_values[4],
    )


def _results(
    plan: FrozenValidationPlan,
    *,
    changes: dict[
        tuple[str, str],
        tuple[bool, bool, bool, bool, float],
    ]
    | None = None,
    clinician_changes: dict[
        tuple[str, str],
        tuple[bool, bool, bool, bool, float],
    ]
    | None = None,
    omit: set[tuple[str, str]] | None = None,
) -> ObservedValidationResults:
    changes = changes or {}
    clinician_changes = clinician_changes or {}
    omit = omit or set()
    observations = []
    for assignment in plan.clinician_sampling.assignments:
        for reviewer_id in assignment.reviewer_ids:
            key = (assignment.opaque_id, reviewer_id)
            if key in omit:
                continue
            observations.append(
                _observation(
                    assignment.opaque_id,
                    reviewer_id,
                    clinician=clinician_changes.get(key),
                    evaluator=changes.get(key),
                )
            )
    result = ObservedValidationResults(
        plan_hash=plan.digest,
        study_artifact_hash=plan.study_artifact_hash,
        response_review_artifact_hash=plan.response_review_artifact_hash,
        pair_review_artifact_hash=plan.pair_review_artifact_hash,
        reviewer_ids=plan.clinician_sampling.reviewer_ids,
        observations=tuple(observations),
        completed_at="2026-07-23T13:00:00Z",
    )
    result.validate_against(plan)
    return result


def _adjudications(
    plan: FrozenValidationPlan,
    results: ObservedValidationResults,
    *,
    opaque_ids: tuple[str, ...] | None = None,
) -> AdjudicationBundle:
    selected = opaque_ids or required_adjudication_ids(plan, results)
    records = tuple(
        AdjudicationRecord(
            opaque_id=opaque_id,
            cell_id=_cell_id(opaque_id),
            adjudicator_ids=("adjudicator-a",),
            acceptable=_TRUTH[opaque_id][0],
            severe_error=_TRUTH[opaque_id][1],
            harmful_action=_TRUTH[opaque_id][2],
            critical_omission=_TRUTH[opaque_id][3],
            continuous_score=_TRUTH[opaque_id][4],
            decision_reason="Independent consensus review.",
            adjudicated_at="2026-07-23T14:00:00Z",
        )
        for opaque_id in selected
    )
    bundle = AdjudicationBundle(
        plan_hash=plan.digest,
        validation_results_hash=results.digest,
        study_artifact_hash=plan.study_artifact_hash,
        response_review_artifact_hash=plan.response_review_artifact_hash,
        pair_review_artifact_hash=plan.pair_review_artifact_hash,
        adjudicator_ids=plan.escalation.adjudicator_ids,
        records=records,
        completed_at="2026-07-23T15:00:00Z",
    )
    bundle.validate_against(plan, results)
    return bundle


def test_contracts_round_trip_canonically_and_bind_digests() -> None:
    plan = _plan()
    plan_payload = plan.to_dict()
    plan_payload["stratification_cells"].reverse()
    plan_payload["clinician_sampling"]["reviewer_ids"].reverse()
    restored_plan = FrozenValidationPlan.from_dict(plan_payload)
    assert restored_plan == plan
    assert restored_plan.canonical_json() == plan.canonical_json()
    assert restored_plan.digest == plan.digest

    results = _results(plan)
    restored_results = ObservedValidationResults.from_dict(
        results.to_dict(),
        plan=plan,
    )
    assert restored_results == results
    assert restored_results.digest == results.digest

    adjudications = _adjudications(plan, results)
    restored_adjudications = AdjudicationBundle.from_dict(
        adjudications.to_dict(),
        plan=plan,
        results=results,
    )
    assert restored_adjudications == adjudications
    assert restored_adjudications.digest == adjudications.digest


def test_gate_accepts_complete_evidence_that_meets_every_threshold() -> None:
    plan = _plan()
    results = _results(plan)
    adjudications = _adjudications(plan, results)

    gate = evaluate_clinical_validation(
        plan=plan,
        results=results,
        adjudications=adjudications,
    )

    assert gate.verdict is ValidationVerdict.ACCEPTED
    assert gate.reasons == ()
    assert gate.metrics is not None
    assert gate.metrics.to_dict() == {
        "item_count": 4,
        "agreement": 1.0,
        "severe_error_sensitivity": 1.0,
        "severe_error_specificity": 1.0,
        "harmful_action_false_negative_rate": 0.0,
        "critical_omission_false_negative_rate": 0.0,
        "continuous_score_mae": 0.0,
        "severe_error_positives": 2,
        "severe_error_negatives": 2,
        "harmful_action_positives": 1,
        "critical_omission_positives": 1,
    }
    assert gate.plan_hash == plan.digest
    assert gate.validation_results_hash == results.digest
    assert gate.adjudication_hash == adjudications.digest


def test_gate_rejects_complete_evidence_that_misses_safety_thresholds() -> None:
    plan = _plan()
    incorrect = (True, False, False, False, 4.0)
    changes = {
        ("opaque-02", "clinician-a"): incorrect,
        ("opaque-02", "clinician-b"): incorrect,
    }
    results = _results(plan, changes=changes)
    adjudications = _adjudications(plan, results)

    gate = evaluate_clinical_validation(
        plan=plan,
        results=results,
        adjudications=adjudications,
    )

    assert gate.verdict is ValidationVerdict.REJECTED
    assert gate.metrics is not None
    assert gate.metrics.agreement == 0.75
    assert gate.metrics.severe_error_sensitivity == 0.5
    assert gate.metrics.harmful_action_false_negative_rate == 1.0
    assert gate.metrics.continuous_score_mae == 0.75
    assert {reason.split(" ", 1)[0] for reason in gate.reasons} >= {
        "agreement",
        "severe-error",
        "harmful-action",
        "continuous-score",
    }


def test_gate_distinguishes_engineering_only_from_inconclusive() -> None:
    no_plan = evaluate_clinical_validation()
    assert no_plan.verdict is ValidationVerdict.ENGINEERING_ONLY

    plan = _plan()
    no_results = evaluate_clinical_validation(plan=plan)
    assert no_results.verdict is ValidationVerdict.ENGINEERING_ONLY
    assert no_results.expected_observation_count == 8

    partial = _results(
        plan,
        omit={("opaque-04", "clinician-b")},
    )
    incomplete = evaluate_clinical_validation(plan=plan, results=partial)
    assert incomplete.verdict is ValidationVerdict.INCONCLUSIVE
    assert incomplete.observed_observation_count == 7
    assert "missing 1" in incomplete.reasons[0]

    complete = _results(plan)
    unadjudicated = evaluate_clinical_validation(plan=plan, results=complete)
    assert unadjudicated.verdict is ValidationVerdict.INCONCLUSIVE
    assert "missing adjudications" in unadjudicated.reasons[0]


def test_insufficient_prespecified_denominators_are_inconclusive() -> None:
    base = _plan().thresholds
    plan = _plan(thresholds=replace(base, minimum_severe_error_positives=3))
    results = _results(plan)
    gate = evaluate_clinical_validation(
        plan=plan,
        results=results,
        adjudications=_adjudications(plan, results),
    )
    assert gate.verdict is ValidationVerdict.INCONCLUSIVE
    assert gate.metrics is not None
    assert "severe-error positives 2 is below 3" in gate.reasons


def test_escalation_and_random_audit_selection_are_deterministic() -> None:
    plan = _plan()
    false_negative = (False, True, False, False, 1.0)
    clinician_disagreement = (True, False, False, False, 3.0)
    results = _results(
        plan,
        changes={
            ("opaque-02", "clinician-a"): false_negative,
            ("opaque-02", "clinician-b"): false_negative,
        },
        clinician_changes={
            ("opaque-01", "clinician-b"): clinician_disagreement,
        },
    )

    required = required_adjudication_ids(plan, results)
    restored = FrozenValidationPlan.from_dict(plan.to_dict())
    restored_results = ObservedValidationResults.from_dict(
        results.to_dict(),
        plan=restored,
    )

    assert "opaque-01" in required
    assert "opaque-02" in required
    assert required == required_adjudication_ids(restored, restored_results)
    assert len(set(required) & {"opaque-01", "opaque-02"}) == 2
    assert len(set(required) & {"opaque-03", "opaque-04"}) >= 1


def test_adjudication_coverage_must_match_escalation_and_audit_exactly() -> None:
    plan = _plan()
    results = _results(plan)
    required = required_adjudication_ids(plan, results)
    missing = _adjudications(plan, results, opaque_ids=required[:-1])
    gate = evaluate_clinical_validation(
        plan=plan,
        results=results,
        adjudications=missing,
    )
    assert gate.verdict is ValidationVerdict.INCONCLUSIVE
    assert "missing=1" in gate.reasons[0]

    extra_id = next(opaque_id for opaque_id in plan.opaque_ids if opaque_id not in required)
    extra = _adjudications(plan, results, opaque_ids=required + (extra_id,))
    gate = evaluate_clinical_validation(
        plan=plan,
        results=results,
        adjudications=extra,
    )
    assert gate.verdict is ValidationVerdict.INCONCLUSIVE
    assert "extra=1" in gate.reasons[0]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload.update({"unexpected": True}),
            "unknown=\\['unexpected'\\]",
        ),
        (
            lambda payload: payload.update({"schema_version": "future.v2"}),
            "schema_version",
        ),
        (
            lambda payload: payload.update({"clinical_approver_id": "TBD"}),
            "placeholder",
        ),
    ],
)
def test_plan_rejects_unknown_fields_versions_and_placeholders(
    mutator: object,
    message: str,
) -> None:
    payload = _plan().to_dict()
    mutator(payload)  # type: ignore[operator]
    with pytest.raises(ValueError, match=message):
        FrozenValidationPlan.from_dict(payload)


def test_plan_rejects_duplicate_or_incomplete_sampling_contracts() -> None:
    plan = _plan()
    with pytest.raises(ValueError, match="duplicates"):
        replace(
            plan,
            stratification_cells=(
                plan.stratification_cells[0],
                plan.stratification_cells[0],
            ),
        )
    with pytest.raises(ValueError, match="exactly cover"):
        replace(
            plan,
            clinician_sampling=replace(
                plan.clinician_sampling,
                assignments=plan.clinician_sampling.assignments[:-1],
            ),
        )
    with pytest.raises(ValueError, match="independent"):
        replace(
            plan,
            escalation=replace(
                plan.escalation,
                adjudicator_ids=("clinician-a",),
            ),
        )


@pytest.mark.parametrize(
    "threshold_change",
    [
        {"minimum_agreement": float("nan")},
        {"minimum_severe_error_sensitivity": float("inf")},
        {"maximum_continuous_score_mae": -0.1},
        {"continuous_score_minimum": 4.0},
    ],
)
def test_thresholds_reject_nonfinite_and_invalid_values(
    threshold_change: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        replace(_plan().thresholds, **threshold_change)


def test_results_reject_duplicate_unknown_and_inconsistent_observations() -> None:
    plan = _plan()
    result = _results(plan)
    with pytest.raises(ValueError, match="duplicates"):
        replace(result, observations=result.observations + (result.observations[0],))

    unknown = replace(result.observations[0], opaque_id="opaque-99")
    with pytest.raises(ValueError, match="outside frozen assignments"):
        replace(result, observations=(unknown,) + result.observations[1:]).validate_against(
            plan
        )

    changed_evaluator = replace(
        result.observations[1],
        evaluator_continuous_score=2.0,
    )
    with pytest.raises(ValueError, match="not identical"):
        replace(
            result,
            observations=(result.observations[0], changed_evaluator)
            + result.observations[2:],
        ).validate_against(plan)

    out_of_range = replace(
        result.observations[0],
        clinician_continuous_score=5.0,
    )
    with pytest.raises(ValueError, match="outside the frozen score range"):
        replace(
            result,
            observations=(out_of_range,) + result.observations[1:],
        ).validate_against(plan)


def test_hash_mismatches_are_errors_not_gate_outcomes() -> None:
    plan = _plan()
    results = _results(plan)
    with pytest.raises(ValueError, match="plan_hash"):
        replace(results, plan_hash=_hash("other-plan")).validate_against(plan)

    adjudications = _adjudications(plan, results)
    with pytest.raises(ValueError, match="validation_results_hash"):
        replace(
            adjudications,
            validation_results_hash=_hash("other-results"),
        ).validate_against(plan, results)

    partial = _results(plan, omit={("opaque-04", "clinician-b")})
    invalid_partial_adjudications = replace(
        _adjudications(plan, partial),
        validation_results_hash=_hash("mismatched-partial-results"),
    )
    with pytest.raises(ValueError, match="validation_results_hash"):
        evaluate_clinical_validation(
            plan=plan,
            results=partial,
            adjudications=invalid_partial_adjudications,
        )


def test_adjudications_reject_duplicates_placeholders_and_invalid_people() -> None:
    plan = _plan()
    results = _results(plan)
    adjudications = _adjudications(plan, results)
    with pytest.raises(ValueError, match="duplicates"):
        replace(
            adjudications,
            records=adjudications.records + (adjudications.records[0],),
        )
    with pytest.raises(ValueError, match="placeholder"):
        replace(adjudications.records[0], decision_reason="placeholder")
    with pytest.raises(ValueError, match="outside the frozen roster"):
        replace(
            adjudications,
            records=(
                replace(
                    adjudications.records[0],
                    adjudicator_ids=("unplanned-adjudicator",),
                ),
            )
            + adjudications.records[1:],
        ).validate_against(plan, results)

    with pytest.raises(ValueError, match="must be positive"):
        replace(
            plan.escalation,
            continuous_score_absolute_difference=0,
        )


def test_a_caller_cannot_assign_a_gate_verdict() -> None:
    with pytest.raises(TypeError, match="derived"):
        ClinicalValidationGate(
            _token=object(),
            verdict=ValidationVerdict.ACCEPTED,
            reasons=(),
            plan_hash=None,
            validation_results_hash=None,
            adjudication_hash=None,
            expected_observation_count=0,
            observed_observation_count=0,
            required_adjudication_count=0,
            observed_adjudication_count=0,
            metrics=None,
        )


def test_strict_file_loaders_reject_duplicate_keys_and_nonfinite_json(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema_version":"one","schema_version":"two"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_validation_plan(duplicate)

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value":NaN}', encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite"):
        load_validation_plan(nonfinite)


def test_strict_file_loaders_verify_all_bindings(tmp_path: Path) -> None:
    plan = _plan()
    results = _results(plan)
    adjudications = _adjudications(plan, results)
    plan_path = tmp_path / "plan.json"
    result_path = tmp_path / "results.json"
    adjudication_path = tmp_path / "adjudications.json"
    plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
    result_path.write_text(json.dumps(results.to_dict()), encoding="utf-8")
    adjudication_path.write_text(
        json.dumps(adjudications.to_dict()),
        encoding="utf-8",
    )

    loaded_plan = load_validation_plan(plan_path)
    loaded_results = load_validation_results(result_path, plan=loaded_plan)
    loaded_adjudications = load_adjudications(
        adjudication_path,
        plan=loaded_plan,
        results=loaded_results,
    )

    assert loaded_plan.digest == plan.digest
    assert loaded_results.digest == results.digest
    assert loaded_adjudications.digest == adjudications.digest


def test_results_and_adjudication_loaders_reject_unknown_fields() -> None:
    plan = _plan()
    results = _results(plan)
    result_payload = results.to_dict()
    result_payload["observations"][0]["extra"] = "not allowed"
    with pytest.raises(ValueError, match="unknown=\\['extra'\\]"):
        ObservedValidationResults.from_dict(result_payload, plan=plan)

    adjudications = _adjudications(plan, results)
    adjudication_payload = adjudications.to_dict()
    adjudication_payload["records"][0]["verdict"] = "accepted"
    with pytest.raises(ValueError, match="unknown=\\['verdict'\\]"):
        AdjudicationBundle.from_dict(
            adjudication_payload,
            plan=plan,
            results=results,
        )
