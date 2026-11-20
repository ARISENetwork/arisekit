"""Specialty program allocation is deterministic, bound, and fail closed."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from arisekit.authoring.specialty import (
    BENCHMARK_PLAN_SCHEMA_VERSION,
    CANONICAL_ACUITY_LEVELS,
    FIRST_SIX_STRESS_MODES,
    PROFILE_SPECIALTIES,
    AcuityLevel,
    BenchmarkArchetype,
    BenchmarkTrack,
    ClinicalLock,
    ClinicalScope,
    ConditionFamily,
    ConditionSelection,
    DataAuthorization,
    FailureEvidenceReference,
    ProgramScale,
    ReferenceRelationship,
    ReleaseScope,
    RepresentativeSelectionPolicy,
    RightsBasis,
    SamplingFrame,
    SamplingProtocol,
    Specialty,
    SpecialtyBenchmarkPlan,
    SpecialtyProfile,
    SpecialtyProgramSpec,
    StressSelectionBasis,
    StressSelectionPolicy,
    StressMode,
    materialize_specialty_program,
    normalize_condition_family,
    normalize_specialty,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


_CONDITIONS = {
    Specialty.CARDIOLOGY: (
        ConditionFamily.HEART_FAILURE,
        ConditionFamily.ACUTE_CORONARY_SYNDROME,
    ),
    Specialty.EMERGENCY_MEDICINE: (
        ConditionFamily.ACUTE_ABDOMINAL_OR_PELVIC_PAIN,
        ConditionFamily.SEPSIS,
    ),
    Specialty.PRIMARY_INTERNAL_MEDICINE: (
        ConditionFamily.DIABETES,
        ConditionFamily.AUTOIMMUNE_DISEASE,
    ),
    Specialty.NEUROLOGY: (
        ConditionFamily.MIGRAINE_AND_SECONDARY_HEADACHE,
        ConditionFamily.STROKE_TIA,
    ),
    Specialty.PSYCHIATRY: (
        ConditionFamily.ADHD,
        ConditionFamily.DEPRESSION_AND_SUICIDALITY,
    ),
    Specialty.OBSTETRICS_GYNECOLOGY: (
        ConditionFamily.ENDOMETRIOSIS,
        ConditionFamily.ECTOPIC_PREGNANCY,
    ),
    Specialty.ENDOCRINOLOGY: (
        ConditionFamily.THYROID_DISEASE,
        ConditionFamily.DIABETES,
    ),
    Specialty.RHEUMATOLOGY: (
        ConditionFamily.FIBROMYALGIA,
        ConditionFamily.LUPUS_RA,
    ),
    Specialty.ONCOLOGY: (
        ConditionFamily.LUNG_OR_COLORECTAL_CANCER,
        ConditionFamily.OSTEOPOROSIS,
    ),
    Specialty.PAIN_MEDICINE: (
        ConditionFamily.CHRONIC_PAIN,
        ConditionFamily.FIBROMYALGIA,
    ),
    Specialty.ADOLESCENT_MEDICINE: (
        ConditionFamily.ADHD,
        ConditionFamily.MIGRAINE_AND_SECONDARY_HEADACHE,
    ),
    Specialty.REPRODUCTIVE_CARE: (
        ConditionFamily.ENDOMETRIOSIS,
        ConditionFamily.PCOS,
    ),
    Specialty.MATERNAL_MEDICINE: (
        ConditionFamily.PERINATAL_MOOD_DISORDERS,
        ConditionFamily.PREECLAMPSIA_AND_POSTPARTUM_COMPLICATIONS,
    ),
    Specialty.GERIATRICS: (
        ConditionFamily.OSTEOPOROSIS,
        ConditionFamily.MEDICATION_ADVERSE_EVENTS,
    ),
}


def _scope(
    profile: SpecialtyProfile = SpecialtyProfile.SIX_SPECIALTY_PILOT,
    *,
    specialties: tuple[Specialty, ...] | None = None,
    sampling: SamplingProtocol | None = None,
    weights: dict[Specialty, tuple[float, float, float, float]] | None = None,
    representative: RepresentativeSelectionPolicy | None = None,
    stress: StressSelectionPolicy | None = None,
    stress_modes: tuple[StressMode, ...] = FIRST_SIX_STRESS_MODES,
) -> ClinicalScope:
    selected_specialties = (
        specialties if specialties is not None else PROFILE_SPECIALTIES[profile]
    )
    condition_weights = weights or {}
    return ClinicalScope(
        profile=profile,
        specialties=selected_specialties,
        condition_selections=tuple(
            ConditionSelection(
                specialty=specialty,
                common_condition=_CONDITIONS[specialty][0],
                high_harm_condition=_CONDITIONS[specialty][1],
                common_prevalence_weight=condition_weights.get(
                    specialty, (1.0, 1.0, 1.0, 1.0)
                )[0],
                common_harm_weight=condition_weights.get(
                    specialty, (1.0, 1.0, 1.0, 1.0)
                )[1],
                high_harm_prevalence_weight=condition_weights.get(
                    specialty, (1.0, 1.0, 1.0, 1.0)
                )[2],
                high_harm_harm_weight=condition_weights.get(
                    specialty, (1.0, 1.0, 1.0, 1.0)
                )[3],
            )
            for specialty in selected_specialties
        ),
        sampling=sampling or SamplingProtocol(),
        representative_selection=(representative or RepresentativeSelectionPolicy()),
        stress_selection=stress or StressSelectionPolicy(),
        stress_modes=stress_modes,
    )


def _authorization() -> DataAuthorization:
    return DataAuthorization(
        id="hospital-specialty-export",
        source_reference="inventory://approved-specialty-export",
        data_inventory_sha256=_hash("data-inventory"),
        rights_basis=RightsBasis.INSTITUTION_AUTHORIZED,
        authorization_reference="governance://approval/ARISE-2026-014",
        authorization_artifact_sha256=_hash("authorization"),
        authorized_by="Institutional data owner",
        authorized_at="2026-07-23T09:00:00Z",
        release_scope=ReleaseScope.RESTRICTED,
    )


def _spec(
    *,
    scale: ProgramScale = ProgramScale.DEFAULT_PILOT,
    profile: SpecialtyProfile = SpecialtyProfile.SIX_SPECIALTY_PILOT,
    model_ids: tuple[str, ...] = ("model-a", "model-b", "model-c"),
    repetitions: int = 3,
    scope: ClinicalScope | None = None,
    archetype: BenchmarkArchetype = BenchmarkArchetype.PAIRED_SPECIALTY_EQUITY,
    representative_family_target: int | None = None,
    stress_family_target: int | None = None,
) -> SpecialtyProgramSpec:
    clinical_scope = scope or _scope(profile)
    return SpecialtyProgramSpec(
        program_id="specialty-synthetic-pilot",
        clinical_scope=clinical_scope,
        clinical_lock=ClinicalLock(
            scope_sha256=clinical_scope.scope_sha256,
            clinician_name="Reviewing physician",
            clinician_credential="board-certified specialty physician",
            locked_at="2026-07-23T10:00:00Z",
            approval_reference="clinical-review://scope-lock/001",
        ),
        data_authorizations=(_authorization(),),
        study_design_hash=_hash("study-design"),
        scale=scale,
        archetype=archetype,
        model_ids=model_ids,
        model_repetitions=repetitions,
        representative_family_target=representative_family_target,
        stress_family_target=stress_family_target,
    )


def test_taxonomy_normalizes_attached_specialty_and_condition_labels() -> None:
    assert normalize_specialty("primary care") is Specialty.PRIMARY_INTERNAL_MEDICINE
    assert (
        normalize_specialty("primary/internal medicine")
        is Specialty.PRIMARY_INTERNAL_MEDICINE
    )
    assert (
        normalize_specialty("obstetrics/gynecology") is Specialty.OBSTETRICS_GYNECOLOGY
    )
    assert normalize_specialty("OB/GYN") is Specialty.OBSTETRICS_GYNECOLOGY
    assert (
        normalize_condition_family("arrhythmia/QT risk")
        is ConditionFamily.ARRHYTHMIA_QT_RISK
    )
    assert normalize_condition_family("stroke/TIA") is ConditionFamily.STROKE_TIA
    assert normalize_condition_family("lupus/RA") is ConditionFamily.LUPUS_RA
    with pytest.raises(ValueError, match="unknown specialty"):
        normalize_specialty("invented specialty")
    with pytest.raises(ValueError, match="unknown condition"):
        normalize_condition_family("invented condition")


def test_profiles_cover_focused_balanced_broad_life_course_and_pilot() -> None:
    assert len(PROFILE_SPECIALTIES[SpecialtyProfile.FOCUSED]) == 4
    assert len(PROFILE_SPECIALTIES[SpecialtyProfile.BALANCED]) == 6
    assert len(PROFILE_SPECIALTIES[SpecialtyProfile.BROAD]) == 10
    assert PROFILE_SPECIALTIES[SpecialtyProfile.LIFE_COURSE] == (
        Specialty.ADOLESCENT_MEDICINE,
        Specialty.REPRODUCTIVE_CARE,
        Specialty.MATERNAL_MEDICINE,
        Specialty.PRIMARY_INTERNAL_MEDICINE,
        Specialty.GERIATRICS,
    )
    assert PROFILE_SPECIALTIES[SpecialtyProfile.SIX_SPECIALTY_PILOT] == (
        Specialty.CARDIOLOGY,
        Specialty.EMERGENCY_MEDICINE,
        Specialty.PRIMARY_INTERNAL_MEDICINE,
        Specialty.NEUROLOGY,
        Specialty.PSYCHIATRY,
        Specialty.OBSTETRICS_GYNECOLOGY,
    )
    assert SpecialtyProfile.CUSTOM not in PROFILE_SPECIALTIES


def test_single_specialty_custom_scope_roundtrips_and_is_hash_bound() -> None:
    scope = _scope(
        SpecialtyProfile.CUSTOM,
        specialties=(Specialty.CARDIOLOGY,),
        weights={Specialty.CARDIOLOGY: (3.0, 1.0, 1.0, 4.0)},
    )
    assert ClinicalScope.from_dict(scope.to_dict()) == scope

    tampered = copy.deepcopy(scope.to_dict())
    tampered["condition_selections"][0]["common_prevalence_weight"] = 7.0
    with pytest.raises(ValueError, match="scope hash"):
        ClinicalScope.from_dict(tampered)

    plan = materialize_specialty_program(
        _spec(
            scale=ProgramScale.SMOKE,
            scope=scope,
            model_ids=("model-a",),
            repetitions=1,
        )
    )
    assert plan.totals["representative_families"] == 3
    assert plan.totals["stress_families"] == 6


def test_custom_scope_requires_unique_global_order_and_exact_selections() -> None:
    canonical = _scope(
        SpecialtyProfile.CUSTOM,
        specialties=(Specialty.CARDIOLOGY, Specialty.NEUROLOGY),
    )

    with pytest.raises(ValueError, match="global taxonomy"):
        _scope(
            SpecialtyProfile.CUSTOM,
            specialties=(Specialty.NEUROLOGY, Specialty.CARDIOLOGY),
        )
    with pytest.raises(ValueError, match="must be unique"):
        _scope(
            SpecialtyProfile.CUSTOM,
            specialties=(Specialty.CARDIOLOGY, Specialty.CARDIOLOGY),
        )
    with pytest.raises(ValueError, match="cover every specialty once"):
        ClinicalScope(
            profile=SpecialtyProfile.CUSTOM,
            specialties=canonical.specialties,
            condition_selections=canonical.condition_selections[:1],
            sampling=canonical.sampling,
            representative_selection=canonical.representative_selection,
            stress_selection=canonical.stress_selection,
        )
    with pytest.raises(ValueError, match="must not be empty"):
        ClinicalScope(
            profile=SpecialtyProfile.CUSTOM,
            specialties=(),
            condition_selections=(),
            sampling=canonical.sampling,
            representative_selection=canonical.representative_selection,
            stress_selection=canonical.stress_selection,
        )


def test_custom_scope_accepts_any_nonempty_canonical_stress_mode_subset() -> None:
    selected_modes = (
        StressMode.UNJUSTIFIED_DEMOGRAPHIC_CHANGE,
        StressMode.SYMPTOM_MINIMIZATION,
        StressMode.MULTIMODAL_INTERPRETATION_ERROR,
    )
    scope = _scope(
        SpecialtyProfile.CUSTOM,
        specialties=(Specialty.CARDIOLOGY,),
        stress_modes=selected_modes,
    )
    plan = materialize_specialty_program(
        _spec(
            scale=ProgramScale.SMOKE,
            scope=scope,
            model_ids=("model-a",),
            repetitions=1,
        )
    )
    stress_cells = [cell for cell in plan.cells if cell.track is BenchmarkTrack.STRESS]
    assert tuple(cell.stress_mode for cell in stress_cells) == selected_modes
    assert plan.totals["stress_families"] == len(selected_modes)

    for invalid_modes, error in (
        ((), "must not be empty"),
        ((selected_modes[1], selected_modes[0]), "canonical order"),
        ((selected_modes[0], selected_modes[0]), "must be unique"),
    ):
        with pytest.raises(ValueError, match=error):
            _scope(
                SpecialtyProfile.CUSTOM,
                specialties=(Specialty.CARDIOLOGY,),
                stress_modes=invalid_modes,
            )


def test_named_profiles_retain_exactly_the_first_six_stress_modes() -> None:
    assert _scope().stress_modes == FIRST_SIX_STRESS_MODES
    with pytest.raises(ValueError, match="named profiles require the first six"):
        _scope(
            stress_modes=FIRST_SIX_STRESS_MODES + (StressMode.SYMPTOM_MINIMIZATION,),
        )


@pytest.mark.parametrize("bad_weight", [0, -1, float("inf"), float("nan")])
def test_condition_weights_must_be_positive_and_finite(bad_weight: float) -> None:
    with pytest.raises(ValueError, match="positive and finite"):
        ConditionSelection(
            specialty=Specialty.CARDIOLOGY,
            common_condition=ConditionFamily.HEART_FAILURE,
            high_harm_condition=ConditionFamily.ACUTE_CORONARY_SYNDROME,
            common_prevalence_weight=bad_weight,
        )


def test_representative_track_cannot_use_model_failure_selection() -> None:
    with pytest.raises(ValueError, match="representative-track"):
        RepresentativeSelectionPolicy(uses_model_failure_evidence=True)


def test_observed_failure_stress_selection_requires_bound_evidence() -> None:
    with pytest.raises(ValueError, match="hash-bound evidence"):
        StressSelectionPolicy(basis=StressSelectionBasis.OBSERVED_MODEL_FAILURES)

    policy = StressSelectionPolicy(
        basis=StressSelectionBasis.OBSERVED_MODEL_FAILURES,
        failure_evidence=(
            FailureEvidenceReference(
                id="heldout-failure-analysis",
                artifact_sha256=_hash("failure-analysis"),
                analysis_code_sha256=_hash("failure-analysis-code"),
            ),
        ),
    )
    assert policy.failure_evidence[0].id == "heldout-failure-analysis"


def test_clinical_scope_is_hash_bound_and_requires_exact_profile_order() -> None:
    scope = _scope()
    restored = ClinicalScope.from_dict(scope.to_dict())
    assert restored == scope
    assert restored.reference_relationships == (
        ReferenceRelationship.INVARIANT,
        ReferenceRelationship.DIFFERENTIATED,
        ReferenceRelationship.INFORMATION_REQUIRED,
    )
    assert restored.stress_modes == FIRST_SIX_STRESS_MODES

    tampered = copy.deepcopy(scope.to_dict())
    tampered["condition_selections"][0]["common_condition"] = "arrhythmia-qt-risk"
    with pytest.raises(ValueError, match="scope hash"):
        ClinicalScope.from_dict(tampered)

    with pytest.raises(ValueError, match="canonical order"):
        ClinicalScope(
            profile=SpecialtyProfile.SIX_SPECIALTY_PILOT,
            specialties=tuple(reversed(scope.specialties)),
            condition_selections=tuple(reversed(scope.condition_selections)),
            sampling=scope.sampling,
            representative_selection=scope.representative_selection,
            stress_selection=scope.stress_selection,
        )


def test_clinical_lock_and_data_authorization_fail_closed() -> None:
    scope = _scope()
    wrong_lock = ClinicalLock(
        scope_sha256=_hash("other-scope"),
        clinician_name="Reviewing physician",
        clinician_credential="specialist",
        locked_at="2026-07-23T10:00:00Z",
        approval_reference="clinical-review://scope-lock/002",
    )
    with pytest.raises(ValueError, match="does not bind"):
        SpecialtyProgramSpec(
            program_id="specialty-synthetic-pilot",
            clinical_scope=scope,
            clinical_lock=wrong_lock,
            data_authorizations=(_authorization(),),
            study_design_hash=_hash("study-design"),
            scale=ProgramScale.DEFAULT_PILOT,
            archetype=BenchmarkArchetype.PAIRED_SPECIALTY_EQUITY,
            model_ids=("model-a", "model-b", "model-c"),
            model_repetitions=3,
        )

    authorization_data = _authorization().to_dict()
    authorization_data["authorization_reference"] = "governance://changed"
    with pytest.raises(ValueError, match="authorization hash"):
        DataAuthorization.from_dict(authorization_data)

    with pytest.raises(ValueError, match="explicitly permit"):
        DataAuthorization(
            id="partial-rights",
            source_reference="inventory://partial",
            data_inventory_sha256=_hash("partial-inventory"),
            rights_basis=RightsBasis.PERMISSION,
            authorization_reference="approval://partial",
            authorization_artifact_sha256=_hash("partial-approval"),
            authorized_by="Data owner",
            authorized_at="2026-07-23T09:00:00Z",
            release_scope=ReleaseScope.PRIVATE,
            permitted_tracks=(BenchmarkTrack.REPRESENTATIVE,),
        )


def test_default_pilot_materializes_exact_cells_variants_and_calls() -> None:
    plan = materialize_specialty_program(_spec())
    assert plan.totals == {
        "sub_benchmark_cells": 54,
        "representative_families": 108,
        "stress_families": 36,
        "total_families": 144,
        "total_variants": 288,
        "calls_per_model": 864,
        "total_model_calls": 2592,
    }

    representative = [
        cell for cell in plan.cells if cell.track is BenchmarkTrack.REPRESENTATIVE
    ]
    stress = [cell for cell in plan.cells if cell.track is BenchmarkTrack.STRESS]
    assert len(representative) == 18
    assert len(stress) == 36
    assert {
        (cell.specialty, cell.reference_relationship) for cell in representative
    } == {
        (specialty, relationship)
        for specialty in PROFILE_SPECIALTIES[SpecialtyProfile.SIX_SPECIALTY_PILOT]
        for relationship in ReferenceRelationship
    }
    assert all(cell.family_count == 6 for cell in representative)
    assert all(cell.expected_variants == 12 for cell in representative)
    assert all(cell.expected_calls_per_model == 36 for cell in representative)
    assert all(cell.expected_model_calls == 108 for cell in representative)
    assert all(
        tuple(item.family_count for item in cell.condition_allocations) == (3, 3)
        for cell in representative
    )
    assert all(cell.family_count == 1 for cell in stress)
    assert all(cell.expected_variants == 2 for cell in stress)
    assert all(cell.expected_calls_per_model == 6 for cell in stress)
    assert all(cell.expected_model_calls == 18 for cell in stress)
    assert all(
        sum(item.family_count for item in cell.acuity_allocations) == cell.family_count
        for cell in plan.cells
    )
    assert all(
        max(
            next(
                (
                    item.family_count
                    for item in cell.acuity_allocations
                    if item.acuity is level
                ),
                0,
            )
            for level in CANONICAL_ACUITY_LEVELS
        )
        - min(
            next(
                (
                    item.family_count
                    for item in cell.acuity_allocations
                    if item.acuity is level
                ),
                0,
            )
            for level in CANONICAL_ACUITY_LEVELS
        )
        <= 1
        for cell in plan.cells
    )
    assert {
        level: sum(
            allocation.family_count
            for cell in plan.cells
            for allocation in cell.acuity_allocations
            if allocation.acuity is level
        )
        for level in CANONICAL_ACUITY_LEVELS
    } == {
        AcuityLevel.ROUTINE: 48,
        AcuityLevel.URGENT: 48,
        AcuityLevel.EMERGENT: 48,
    }


@pytest.mark.parametrize(
    ("frame", "expected_counts"),
    [
        (SamplingFrame.EQUAL_SPECIALTY, (3, 3)),
        (SamplingFrame.PREVALENCE_WEIGHTED, (5, 1)),
        (SamplingFrame.HARM_WEIGHTED, (2, 4)),
        (SamplingFrame.HYBRID, (5, 1)),
    ],
)
def test_sampling_frames_drive_largest_remainder_condition_allocations(
    frame: SamplingFrame,
    expected_counts: tuple[int, int],
) -> None:
    scope = _scope(
        SpecialtyProfile.CUSTOM,
        specialties=(Specialty.CARDIOLOGY,),
        sampling=SamplingProtocol(frame=frame),
        weights={Specialty.CARDIOLOGY: (3.0, 1.0, 1.0, 3.0)},
    )
    plan = materialize_specialty_program(
        _spec(
            scale=ProgramScale.CUSTOM,
            scope=scope,
            model_ids=("model-a",),
            repetitions=1,
            representative_family_target=18,
            stress_family_target=6,
        )
    )
    invariant = next(
        cell
        for cell in plan.cells
        if cell.track is BenchmarkTrack.REPRESENTATIVE
        and cell.reference_relationship is ReferenceRelationship.INVARIANT
    )
    assert (
        tuple(allocation.family_count for allocation in invariant.condition_allocations)
        == expected_counts
    )
    assert plan.totals["representative_families"] == 18
    assert plan.totals["stress_families"] == 6
    assert plan.totals["total_families"] == 24


def test_hybrid_preserves_outer_balance_while_prevalence_weights_outer_grid() -> None:
    specialties = (Specialty.CARDIOLOGY, Specialty.EMERGENCY_MEDICINE)
    weights = {
        Specialty.CARDIOLOGY: (3.0, 1.0, 1.0, 3.0),
        Specialty.EMERGENCY_MEDICINE: (1.0, 1.0, 1.0, 1.0),
    }

    totals_by_frame: dict[SamplingFrame, dict[Specialty, int]] = {}
    for frame in (SamplingFrame.PREVALENCE_WEIGHTED, SamplingFrame.HYBRID):
        scope = _scope(
            SpecialtyProfile.CUSTOM,
            specialties=specialties,
            sampling=SamplingProtocol(frame=frame),
            weights=weights,
        )
        plan = materialize_specialty_program(
            _spec(
                scale=ProgramScale.CUSTOM,
                scope=scope,
                model_ids=("model-a",),
                repetitions=1,
                representative_family_target=18,
                stress_family_target=6,
            )
        )
        totals_by_frame[frame] = {
            specialty: sum(
                cell.family_count
                for cell in plan.cells
                if cell.track is BenchmarkTrack.REPRESENTATIVE
                and cell.specialty is specialty
            )
            for specialty in specialties
        }

    assert totals_by_frame[SamplingFrame.PREVALENCE_WEIGHTED] == {
        Specialty.CARDIOLOGY: 12,
        Specialty.EMERGENCY_MEDICINE: 6,
    }
    assert totals_by_frame[SamplingFrame.HYBRID] == {
        Specialty.CARDIOLOGY: 9,
        Specialty.EMERGENCY_MEDICINE: 9,
    }


def test_largest_remainder_ties_rotate_deterministically_across_cells() -> None:
    scope = _scope(
        SpecialtyProfile.CUSTOM,
        specialties=(Specialty.CARDIOLOGY,),
        sampling=SamplingProtocol(frame=SamplingFrame.EQUAL_SPECIALTY),
    )
    spec = _spec(
        scale=ProgramScale.CUSTOM,
        scope=scope,
        model_ids=("model-a",),
        repetitions=1,
        representative_family_target=9,
        stress_family_target=6,
    )
    first = materialize_specialty_program(spec)
    second = materialize_specialty_program(spec)
    representative = [
        tuple(allocation.family_count for allocation in cell.condition_allocations)
        for cell in first.cells
        if cell.track is BenchmarkTrack.REPRESENTATIVE
    ]
    assert representative == [(2, 1), (1, 2), (2, 1)]
    assert first == second
    assert first.totals["total_families"] == 15


def test_acuity_ties_rotate_across_cells_without_condition_inference() -> None:
    scope = _scope(
        SpecialtyProfile.CUSTOM,
        specialties=(Specialty.CARDIOLOGY,),
    )
    plan = materialize_specialty_program(
        _spec(
            scale=ProgramScale.SMOKE,
            scope=scope,
            model_ids=("model-a",),
            repetitions=1,
        )
    )
    representative = [
        cell for cell in plan.cells if cell.track is BenchmarkTrack.REPRESENTATIVE
    ]
    assert [
        tuple(
            allocation.acuity
            for allocation in cell.acuity_allocations
            if allocation.family_count
        )
        for cell in representative
    ] == [
        (AcuityLevel.ROUTINE,),
        (AcuityLevel.URGENT,),
        (AcuityLevel.EMERGENT,),
    ]
    assert {
        cell.condition_allocations[0].condition_family for cell in representative
    } == {
        ConditionFamily.HEART_FAILURE,
        ConditionFamily.ACUTE_CORONARY_SYNDROME,
    }


@pytest.mark.parametrize(
    ("representative_target", "stress_target"),
    [(7, 5), (17, 11), (31, 19), (47, 26)],
)
def test_acuity_is_near_balanced_within_each_track_for_arbitrary_targets(
    representative_target: int,
    stress_target: int,
) -> None:
    scope = _scope(
        SpecialtyProfile.CUSTOM,
        specialties=(
            Specialty.CARDIOLOGY,
            Specialty.EMERGENCY_MEDICINE,
        ),
        stress_modes=(
            StressMode.UNJUSTIFIED_DEMOGRAPHIC_CHANGE,
            StressMode.SYMPTOM_MINIMIZATION,
            StressMode.FAILURE_TO_REQUEST_INFORMATION,
        ),
    )
    plan = materialize_specialty_program(
        _spec(
            scale=ProgramScale.CUSTOM,
            scope=scope,
            model_ids=("model-a",),
            repetitions=1,
            representative_family_target=representative_target,
            stress_family_target=stress_target,
        )
    )

    for track, expected_total in (
        (BenchmarkTrack.REPRESENTATIVE, representative_target),
        (BenchmarkTrack.STRESS, stress_target),
    ):
        track_cells = [cell for cell in plan.cells if cell.track is track]
        totals = tuple(
            sum(
                allocation.family_count
                for cell in track_cells
                for allocation in cell.acuity_allocations
                if allocation.acuity is level
            )
            for level in CANONICAL_ACUITY_LEVELS
        )
        assert sum(totals) == expected_total
        assert max(totals) - min(totals) <= 1
        assert all(
            tuple(allocation.acuity for allocation in cell.acuity_allocations)
            == CANONICAL_ACUITY_LEVELS
            for cell in track_cells
        )
        assert all(
            all(allocation.family_count >= 0 for allocation in cell.acuity_allocations)
            for cell in track_cells
        )
        assert all(
            sum(allocation.family_count for allocation in cell.acuity_allocations)
            == cell.family_count
            for cell in track_cells
        )


def test_smoke_plan_is_smaller_and_covers_each_specialty_and_stress_mode() -> None:
    plan = materialize_specialty_program(
        _spec(
            scale=ProgramScale.SMOKE,
            model_ids=("model-a",),
            repetitions=1,
        )
    )
    assert plan.totals == {
        "sub_benchmark_cells": 24,
        "representative_families": 18,
        "stress_families": 6,
        "total_families": 24,
        "total_variants": 48,
        "calls_per_model": 48,
        "total_model_calls": 48,
    }
    stress = [cell for cell in plan.cells if cell.track is BenchmarkTrack.STRESS]
    assert {cell.specialty for cell in stress} == set(
        PROFILE_SPECIALTIES[SpecialtyProfile.SIX_SPECIALTY_PILOT]
    )
    assert {cell.stress_mode for cell in stress} == set(FIRST_SIX_STRESS_MODES)


def test_noharm_archetype_uses_eleven_variants_per_family() -> None:
    plan = materialize_specialty_program(
        _spec(
            scale=ProgramScale.SMOKE,
            model_ids=("model-a",),
            repetitions=1,
            archetype=BenchmarkArchetype.NOHARM,
        )
    )
    assert plan.spec.variants_per_family == 11
    assert plan.totals["total_families"] == 24
    assert plan.totals["total_variants"] == 264
    assert plan.totals["calls_per_model"] == 264


def test_default_noharm_pilot_preserves_144_families_with_11_variants() -> None:
    plan = materialize_specialty_program(_spec(archetype=BenchmarkArchetype.NOHARM))

    assert plan.totals == {
        "sub_benchmark_cells": 54,
        "representative_families": 108,
        "stress_families": 36,
        "total_families": 144,
        "total_variants": 1584,
        "calls_per_model": 4752,
        "total_model_calls": 14256,
    }


def test_default_scale_enforces_comparison_shape_but_smoke_supports_profiles() -> None:
    with pytest.raises(ValueError, match="three or four models"):
        _spec(model_ids=("model-a", "model-b"))
    with pytest.raises(ValueError, match="three model repetitions"):
        _spec(repetitions=1)
    with pytest.raises(ValueError, match="six-specialty"):
        _spec(
            profile=SpecialtyProfile.FOCUSED,
            scope=_scope(SpecialtyProfile.FOCUSED),
        )

    focused = materialize_specialty_program(
        _spec(
            scale=ProgramScale.SMOKE,
            profile=SpecialtyProfile.FOCUSED,
            scope=_scope(SpecialtyProfile.FOCUSED),
            model_ids=("model-a",),
            repetitions=1,
        )
    )
    assert focused.totals["representative_families"] == 12
    assert focused.totals["stress_families"] == 6
    assert {
        cell.specialty for cell in focused.cells if cell.track is BenchmarkTrack.STRESS
    } == set(PROFILE_SPECIALTIES[SpecialtyProfile.FOCUSED])
    assert {
        cell.stress_mode
        for cell in focused.cells
        if cell.track is BenchmarkTrack.STRESS
    } == set(FIRST_SIX_STRESS_MODES)


@pytest.mark.parametrize(
    ("scale", "representative_target", "stress_target"),
    [
        (ProgramScale.FEASIBILITY, 30, 18),
        (ProgramScale.DESCRIPTIVE_PILOT, 96, 30),
        (ProgramScale.COMPARATIVE, 300, 60),
        (ProgramScale.CUSTOM, 17, 9),
    ],
)
def test_explicit_scale_targets_are_bound_and_preserve_totals(
    scale: ProgramScale,
    representative_target: int,
    stress_target: int,
) -> None:
    scope = _scope(
        SpecialtyProfile.CUSTOM,
        specialties=(Specialty.CARDIOLOGY,),
    )
    spec = _spec(
        scale=scale,
        scope=scope,
        model_ids=("model-a",),
        repetitions=1,
        representative_family_target=representative_target,
        stress_family_target=stress_target,
    )
    restored = SpecialtyProgramSpec.from_dict(spec.to_dict())
    assert restored.representative_family_target == representative_target
    assert restored.stress_family_target == stress_target
    plan = materialize_specialty_program(restored)
    assert plan.totals["representative_families"] == representative_target
    assert plan.totals["stress_families"] == stress_target


def test_scale_ranges_require_caller_selected_targets() -> None:
    scope = _scope(
        SpecialtyProfile.CUSTOM,
        specialties=(Specialty.CARDIOLOGY,),
    )
    with pytest.raises(ValueError, match="requires explicit"):
        _spec(
            scale=ProgramScale.FEASIBILITY,
            scope=scope,
            model_ids=("model-a",),
            repetitions=1,
        )
    with pytest.raises(ValueError, match="between 30 and 48"):
        _spec(
            scale=ProgramScale.FEASIBILITY,
            scope=scope,
            model_ids=("model-a",),
            repetitions=1,
            representative_family_target=29,
            stress_family_target=18,
        )
    with pytest.raises(ValueError, match="between 18 and 24"):
        _spec(
            scale=ProgramScale.FEASIBILITY,
            scope=scope,
            model_ids=("model-a",),
            repetitions=1,
            representative_family_target=30,
            stress_family_target=25,
        )
    with pytest.raises(ValueError, match="exactly 108"):
        _spec(
            representative_family_target=109,
            stress_family_target=36,
        )
    with pytest.raises(ValueError, match="derived from"):
        _spec(
            scale=ProgramScale.SMOKE,
            scope=scope,
            model_ids=("model-a",),
            repetitions=1,
            representative_family_target=4,
            stress_family_target=6,
        )


def test_study_design_and_sample_targets_are_hash_bound() -> None:
    spec_data = copy.deepcopy(_spec().to_dict())
    spec_data["study_design_hash"] = _hash("different-study-design")
    with pytest.raises(ValueError, match="program spec hash"):
        SpecialtyProgramSpec.from_dict(spec_data)

    target_data = copy.deepcopy(_spec().to_dict())
    target_data["representative_family_target"] = 107
    with pytest.raises(ValueError, match="exactly 108"):
        SpecialtyProgramSpec.from_dict(target_data)

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        SpecialtyProgramSpec(
            program_id="invalid-study-design",
            clinical_scope=_scope(),
            clinical_lock=ClinicalLock(
                scope_sha256=_scope().scope_sha256,
                clinician_name="Reviewing physician",
                clinician_credential="specialist",
                locked_at="2026-07-23T10:00:00Z",
                approval_reference="clinical-review://scope-lock/invalid",
            ),
            data_authorizations=(_authorization(),),
            study_design_hash="not-a-hash",
            scale=ProgramScale.DEFAULT_PILOT,
            archetype=BenchmarkArchetype.PAIRED_SPECIALTY_EQUITY,
            model_ids=("model-a", "model-b", "model-c"),
            model_repetitions=3,
        )


def test_spec_and_plan_roundtrip_and_reject_unknown_fields() -> None:
    spec = _spec()
    assert SpecialtyProgramSpec.from_dict(spec.to_dict()) == spec
    plan = materialize_specialty_program(spec)
    serialized = json.loads(json.dumps(plan.to_dict()))
    assert SpecialtyBenchmarkPlan.from_dict(serialized) == plan

    serialized["unexpected"] = "not allowed"
    with pytest.raises(ValueError, match="fields do not match"):
        SpecialtyBenchmarkPlan.from_dict(serialized)


def test_scope_spec_and_plan_have_strict_canonical_json_roundtrips() -> None:
    scope = _scope()
    spec = _spec(scope=scope)
    plan = materialize_specialty_program(spec)

    for value, parser, bound_digest in (
        (scope, ClinicalScope.from_json, scope.scope_sha256),
        (spec, SpecialtyProgramSpec.from_json, spec.spec_sha256),
        (plan, SpecialtyBenchmarkPlan.from_json, plan.plan_sha256),
    ):
        assert parser(value.canonical_json) == value
        assert value.digest == bound_digest
        assert value.canonical_json == json.dumps(
            value.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )


@pytest.mark.parametrize(
    "parser",
    [
        ClinicalScope.from_json,
        SpecialtyProgramSpec.from_json,
        SpecialtyBenchmarkPlan.from_json,
    ],
)
def test_specialty_json_parsers_reject_duplicate_keys_and_nonfinite_numbers(
    parser: object,
) -> None:
    duplicate = '{"schema_version":"first","schema_version":"second"}'
    with pytest.raises(ValueError, match="duplicate JSON key"):
        parser(duplicate)  # type: ignore[operator]

    nonfinite = materialize_specialty_program(_spec()).canonical_json.replace(
        '"common_prevalence_weight":1.0',
        '"common_prevalence_weight":1e309',
        1,
    )
    with pytest.raises(ValueError, match="non-finite JSON number"):
        parser(nonfinite)  # type: ignore[operator]


def test_plan_rejects_rehashed_non_deterministic_condition_allocation() -> None:
    plan_data = copy.deepcopy(materialize_specialty_program(_spec()).to_dict())
    first_cell = plan_data["cells"][0]
    first_cell["condition_allocations"] = [
        {
            "condition_family": "heart-failure",
            "family_count": 4,
        },
        {
            "condition_family": "acute-coronary-syndrome",
            "family_count": 2,
        },
    ]
    first_cell["family_count"] = 6
    first_cell["expected_variants"] = 12
    first_cell["expected_calls_per_model"] = 36
    first_cell["expected_model_calls"] = 108
    plan_payload = {
        "schema_version": BENCHMARK_PLAN_SCHEMA_VERSION,
        "spec": plan_data["spec"],
        "cells": plan_data["cells"],
        "totals": plan_data["totals"],
    }
    plan_data["plan_sha256"] = _canonical_hash(plan_payload)

    with pytest.raises(ValueError, match="deterministic specialty allocation"):
        SpecialtyBenchmarkPlan.from_dict(plan_data)


def test_plan_rejects_rehashed_unbalanced_acuity_allocation() -> None:
    plan_data = copy.deepcopy(materialize_specialty_program(_spec()).to_dict())
    plan_data["cells"][0]["acuity_allocations"] = [
        {"acuity": "routine", "family_count": 3},
        {"acuity": "urgent", "family_count": 2},
        {"acuity": "emergent", "family_count": 1},
    ]
    plan_payload = {
        "schema_version": BENCHMARK_PLAN_SCHEMA_VERSION,
        "spec": plan_data["spec"],
        "cells": plan_data["cells"],
        "totals": plan_data["totals"],
    }
    plan_data["plan_sha256"] = _canonical_hash(plan_payload)

    with pytest.raises(ValueError, match="near-balanced"):
        SpecialtyBenchmarkPlan.from_dict(plan_data)


def test_plan_rejects_cellwise_valid_but_track_unbalanced_acuity() -> None:
    scope = _scope(
        SpecialtyProfile.CUSTOM,
        specialties=(Specialty.CARDIOLOGY,),
    )
    plan_data = copy.deepcopy(
        materialize_specialty_program(
            _spec(
                scale=ProgramScale.SMOKE,
                scope=scope,
                model_ids=("model-a",),
                repetitions=1,
            )
        ).to_dict()
    )
    representative_cells = [
        cell
        for cell in plan_data["cells"]
        if cell["track"] == BenchmarkTrack.REPRESENTATIVE.value
    ]
    representative_cells[1]["acuity_allocations"] = [
        {"acuity": "routine", "family_count": 1},
        {"acuity": "urgent", "family_count": 0},
        {"acuity": "emergent", "family_count": 0},
    ]

    with pytest.raises(ValueError, match="representative acuity allocation"):
        SpecialtyBenchmarkPlan.from_dict(plan_data)


def test_plan_hash_detects_direct_tampering() -> None:
    plan_data = copy.deepcopy(materialize_specialty_program(_spec()).to_dict())
    plan_data["totals"]["total_model_calls"] += 1
    with pytest.raises(ValueError, match="serialized benchmark plan"):
        SpecialtyBenchmarkPlan.from_dict(plan_data)
