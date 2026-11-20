"""Autonomous FHIR generation admits engineering candidates, not clinical claims."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from arisekit.authoring.fhir_generation import (
    AutomatedCheckName,
    AutomatedCheckResult,
    AutonomousFHIRTaskSpec,
    ConstraintOperator,
    ConstraintPhase,
    EngineeringStatus,
    EvidenceRequirement,
    GenerationLineage,
    ResponseRequirement,
    SearchParameter,
    StateConstraint,
    TaskBranch,
    TruthSource,
    TruthSourceKind,
    benchmark_item_from_candidate,
    build_engineering_gate,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _task() -> AutonomousFHIRTaskSpec:
    source = TruthSource(
        source_id="fhir-state-one",
        kind=TruthSourceKind.FHIR_STATE,
        locator="fixture://patient-state-one",
        sha256=_hash("patient-state-one"),
    )
    return AutonomousFHIRTaskSpec(
        task_id="task-patient-age",
        family_id="family-demographics",
        capability="Retrieve a patient fact and report it",
        branch=TaskBranch.READ_ONLY,
        patient_id="patient-one",
        frozen_time="2026-07-28T12:00:00Z",
        instruction="Report the patient's age at the frozen time.",
        context="Use the patient record, not an inferred identity.",
        truth_sources=(source,),
        evidence_requirements=(
            EvidenceRequirement(
                evidence_id="patient-birth-date",
                resource_type="Patient",
                search_parameters=(SearchParameter(name="_id", value="patient-one"),),
                projection="Patient.birthDate",
                source_ids=(source.source_id,),
            ),
        ),
        required_outcomes=(),
        forbidden_outcomes=(),
        response_requirements=(
            ResponseRequirement(
                field_id="patient-age",
                value_type="integer-years",
                source_ids=(source.source_id,),
            ),
        ),
        lineage=GenerationLineage(
            generator_model="generator-snapshot",
            generator_family="generator-family",
            generator_prompt_sha256=_hash("generator-prompt"),
            generation_code_sha256=_hash("generation-code"),
            source_bundle_sha256s=(_hash("source-bundle"),),
            seed=17,
            generated_at="2026-07-28T12:01:00Z",
        ),
    )


def _checks(*, passed: bool = True) -> tuple[AutomatedCheckResult, ...]:
    return tuple(
        AutomatedCheckResult(
            name=name,
            passed=passed,
            evidence_sha256=_hash(f"evidence-{name.value}-{passed}"),
            details=f"Reproducible result for {name.value}.",
        )
        for name in AutomatedCheckName
    )


def test_passing_gate_packages_only_an_engineering_candidate() -> None:
    task = _task()
    gate = build_engineering_gate(task, _checks())
    item = benchmark_item_from_candidate(task, gate)

    assert gate.status is EngineeringStatus.ENGINEERING_CANDIDATE
    assert gate.to_dict()["clinical_validity"] == "not-established"
    assert item.metadata["generation_status"] == "engineering-candidate"
    assert item.metadata["clinical_validity"] == "not-established"
    assert item.metadata["human_validation_required"] is True
    assert item.ground_truth["task_spec"]["truth_sources"][0]["kind"] == (
        "fhir-state"
    )


def test_gate_requires_every_fixed_automated_check() -> None:
    task = _task()
    with pytest.raises(ValueError, match="exact engineering gate"):
        build_engineering_gate(task, _checks()[:-1])


def test_empty_finish_and_action_safety_paths_fail_closed() -> None:
    task = _task()
    with pytest.raises(ValueError, match="agent-observed evidence"):
        replace(
            task,
            branch=TaskBranch.NO_ACTION_REQUIRED,
            evidence_requirements=(),
        )

    required = StateConstraint(
        constraint_id="medication-created",
        phase=ConstraintPhase.DELTA,
        resource_type="MedicationRequest",
        selector=(),
        path="MedicationRequest.status",
        operator=ConstraintOperator.EQUALS,
        expected="active",
        source_ids=(task.truth_sources[0].source_id,),
    )
    with pytest.raises(ValueError, match="critical forbidden outcome"):
        replace(
            task,
            branch=TaskBranch.ACTION_REQUIRED,
            required_outcomes=(required,),
            forbidden_outcomes=(),
        )


def test_generator_model_output_cannot_be_declared_a_truth_source() -> None:
    with pytest.raises(ValueError):
        TruthSourceKind("generator-output")
