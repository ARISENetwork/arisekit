"""Golden trace from the supplied specialty pilot options into public contracts."""

from __future__ import annotations

from arisekit.archetype import ArchetypeId, builtin_archetype_registry
from arisekit.authoring.specialty import (
    FIRST_SIX_STRESS_MODES,
    OPTIONAL_EXPANSION_CONDITIONS,
    PILOT_CANDIDATE_CONDITIONS,
    PROFILE_SPECIALTIES,
    SAMPLING_STRATA,
    SCALE_FAMILY_TARGET_RANGES,
    ConditionFamily,
    ProgramScale,
    SamplingFrame,
    Specialty,
    SpecialtyProfile,
    StressMode,
)
from arisekit.specialty_study_design import (
    MultiplicityMethod,
    PhysicianInclusionStrategy,
    SampleSizeTier,
)


def test_specialty_profiles_match_the_supplied_options() -> None:
    assert PROFILE_SPECIALTIES == {
        SpecialtyProfile.FOCUSED: (
            Specialty.CARDIOLOGY,
            Specialty.EMERGENCY_MEDICINE,
            Specialty.PRIMARY_INTERNAL_MEDICINE,
            Specialty.OBSTETRICS_GYNECOLOGY,
        ),
        SpecialtyProfile.BALANCED: (
            Specialty.CARDIOLOGY,
            Specialty.EMERGENCY_MEDICINE,
            Specialty.PRIMARY_INTERNAL_MEDICINE,
            Specialty.OBSTETRICS_GYNECOLOGY,
            Specialty.NEUROLOGY,
            Specialty.PSYCHIATRY,
        ),
        SpecialtyProfile.BROAD: (
            Specialty.CARDIOLOGY,
            Specialty.EMERGENCY_MEDICINE,
            Specialty.PRIMARY_INTERNAL_MEDICINE,
            Specialty.OBSTETRICS_GYNECOLOGY,
            Specialty.NEUROLOGY,
            Specialty.PSYCHIATRY,
            Specialty.ENDOCRINOLOGY,
            Specialty.RHEUMATOLOGY,
            Specialty.ONCOLOGY,
            Specialty.PAIN_MEDICINE,
        ),
        SpecialtyProfile.LIFE_COURSE: (
            Specialty.ADOLESCENT_MEDICINE,
            Specialty.REPRODUCTIVE_CARE,
            Specialty.MATERNAL_MEDICINE,
            Specialty.PRIMARY_INTERNAL_MEDICINE,
            Specialty.GERIATRICS,
        ),
        SpecialtyProfile.SIX_SPECIALTY_PILOT: (
            Specialty.CARDIOLOGY,
            Specialty.EMERGENCY_MEDICINE,
            Specialty.PRIMARY_INTERNAL_MEDICINE,
            Specialty.NEUROLOGY,
            Specialty.PSYCHIATRY,
            Specialty.OBSTETRICS_GYNECOLOGY,
        ),
    }


def test_condition_catalog_and_optional_expansion_are_complete() -> None:
    assert PILOT_CANDIDATE_CONDITIONS == {
        Specialty.CARDIOLOGY: (
            ConditionFamily.ACUTE_CORONARY_SYNDROME,
            ConditionFamily.HEART_FAILURE,
            ConditionFamily.ARRHYTHMIA_QT_RISK,
        ),
        Specialty.EMERGENCY_MEDICINE: (
            ConditionFamily.PULMONARY_EMBOLISM,
            ConditionFamily.SEPSIS,
            ConditionFamily.ACUTE_ABDOMINAL_OR_PELVIC_PAIN,
            ConditionFamily.MEDICATION_ADVERSE_EVENTS,
        ),
        Specialty.PRIMARY_INTERNAL_MEDICINE: (
            ConditionFamily.DIABETES,
            ConditionFamily.THYROID_DISEASE,
            ConditionFamily.AUTOIMMUNE_DISEASE,
            ConditionFamily.CHRONIC_PAIN,
        ),
        Specialty.NEUROLOGY: (
            ConditionFamily.STROKE_TIA,
            ConditionFamily.MIGRAINE_AND_SECONDARY_HEADACHE,
        ),
        Specialty.PSYCHIATRY: (
            ConditionFamily.DEPRESSION_AND_SUICIDALITY,
            ConditionFamily.ADHD,
            ConditionFamily.PERINATAL_MOOD_DISORDERS,
        ),
        Specialty.OBSTETRICS_GYNECOLOGY: (
            ConditionFamily.ECTOPIC_PREGNANCY,
            ConditionFamily.PREECLAMPSIA_AND_POSTPARTUM_COMPLICATIONS,
            ConditionFamily.ENDOMETRIOSIS,
            ConditionFamily.PCOS,
            ConditionFamily.MENOPAUSE,
        ),
    }
    assert OPTIONAL_EXPANSION_CONDITIONS == (
        ConditionFamily.LUPUS_RA,
        ConditionFamily.LUNG_OR_COLORECTAL_CANCER,
        ConditionFamily.OSTEOPOROSIS,
        ConditionFamily.FIBROMYALGIA,
    )


def test_sampling_stress_and_design_option_vocabularies_are_complete() -> None:
    assert set(SAMPLING_STRATA) == {
        "clinical",
        "reference-relationship",
        "life-stage",
        "presentation",
        "complexity",
        "intersectional",
        "sex-and-gender-variables",
        "access-context",
        "acuity",
    }
    assert {value.value for value in SamplingFrame} == {
        "equal-specialty",
        "prevalence-weighted",
        "harm-weighted",
        "equal-specialty-then-prevalence-weighted",
    }
    assert len(tuple(StressMode)) == 13
    assert FIRST_SIX_STRESS_MODES == tuple(StressMode)[:6]
    assert {value.value for value in PhysicianInclusionStrategy} == {
        "model-only-feasibility",
        "clinician-evaluation-only",
        "descriptive-physician-baseline",
        "full-head-to-head",
        "assisted-unassisted-crossover",
    }
    assert {value.value for value in MultiplicityMethod} == {
        "descriptive-confidence-intervals-only",
        "one-primary-no-adjustment",
        "bonferroni",
        "holm",
        "fixed-sequence",
        "hierarchical",
        "false-discovery-rate",
    }


def test_size_bands_and_archetype_workloads_remain_distinct() -> None:
    assert SCALE_FAMILY_TARGET_RANGES == {
        ProgramScale.FEASIBILITY: ((30, 48), (18, 24)),
        ProgramScale.DESCRIPTIVE_PILOT: ((96, 120), (30, 48)),
        ProgramScale.COMPARATIVE: ((300, 500), (60, 100)),
    }
    assert {value.value for value in SampleSizeTier} == {
        "feasibility",
        "descriptive-pilot",
        "comparative-study",
        "illustrative-pilot-default",
        "custom",
    }

    registry = builtin_archetype_registry()
    noharm = registry.get(ArchetypeId.NOHARM).topology
    paired = registry.get(ArchetypeId.PAIRED_EQUITY).topology
    assert noharm.fixed_variants_per_family == 11
    assert noharm.canonical_evaluated_variants_per_family == 5
    assert paired.fixed_variants_per_family == 2
    assert paired.canonical_evaluated_variants_per_family == 2
