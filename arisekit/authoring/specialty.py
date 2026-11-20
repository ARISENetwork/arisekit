"""Hash-bound planning contract for specialty-specific synthetic benchmarks.

The module materializes allocation metadata only. It does not generate clinical
cases, infer a clinical reference answer, certify data rights, or approve a
benchmark for release. Human clinical review and an external data authorization
are required inputs rather than outputs of the planning code.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from types import MappingProxyType
from typing import Any

from arisekit.common.jsonio import canonical_json, strict_json_object
from arisekit.common.validate import sha256_hex as _require_hash


CLINICAL_SCOPE_SCHEMA_VERSION = "arisekit.specialty-clinical-scope.v2"
CLINICAL_LOCK_SCHEMA_VERSION = "arisekit.specialty-clinical-lock.v1"
DATA_AUTHORIZATION_SCHEMA_VERSION = "arisekit.specialty-data-authorization.v1"
PROGRAM_SPEC_SCHEMA_VERSION = "arisekit.specialty-program-spec.v2"
BENCHMARK_PLAN_SCHEMA_VERSION = "arisekit.specialty-benchmark-plan.v3"

DEFAULT_REPRESENTATIVE_FAMILIES = 108
DEFAULT_STRESS_FAMILIES = 36
DEFAULT_MODEL_REPETITIONS = 3

_PROGRAM_ID_RE = re.compile(r"^[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?$")


class Specialty(str, Enum):
    CARDIOLOGY = "cardiology"
    EMERGENCY_MEDICINE = "emergency-medicine"
    PRIMARY_INTERNAL_MEDICINE = "primary-internal-medicine"
    OBSTETRICS_GYNECOLOGY = "obstetrics-gynecology"
    NEUROLOGY = "neurology"
    PSYCHIATRY = "psychiatry"
    ENDOCRINOLOGY = "endocrinology"
    RHEUMATOLOGY = "rheumatology"
    ONCOLOGY = "oncology"
    PAIN_MEDICINE = "pain-medicine"
    ADOLESCENT_MEDICINE = "adolescent-medicine"
    REPRODUCTIVE_CARE = "reproductive-care"
    MATERNAL_MEDICINE = "maternal-medicine"
    GERIATRICS = "geriatrics"


class SpecialtyProfile(str, Enum):
    FOCUSED = "focused"
    BALANCED = "balanced"
    BROAD = "broad"
    LIFE_COURSE = "life-course"
    SIX_SPECIALTY_PILOT = "six-specialty-pilot"
    CUSTOM = "custom"


CANONICAL_SPECIALTIES = tuple(Specialty)


PROFILE_SPECIALTIES: Mapping[SpecialtyProfile, tuple[Specialty, ...]] = (
    MappingProxyType(
        {
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
    )
)


class ConditionFamily(str, Enum):
    ACUTE_CORONARY_SYNDROME = "acute-coronary-syndrome"
    HEART_FAILURE = "heart-failure"
    ARRHYTHMIA_QT_RISK = "arrhythmia-qt-risk"
    PULMONARY_EMBOLISM = "pulmonary-embolism"
    SEPSIS = "sepsis"
    ACUTE_ABDOMINAL_OR_PELVIC_PAIN = "acute-abdominal-or-pelvic-pain"
    MEDICATION_ADVERSE_EVENTS = "medication-adverse-events"
    DIABETES = "diabetes"
    THYROID_DISEASE = "thyroid-disease"
    AUTOIMMUNE_DISEASE = "autoimmune-disease"
    CHRONIC_PAIN = "chronic-pain"
    STROKE_TIA = "stroke-tia"
    MIGRAINE_AND_SECONDARY_HEADACHE = "migraine-and-secondary-headache"
    DEPRESSION_AND_SUICIDALITY = "depression-and-suicidality"
    ADHD = "adhd"
    PERINATAL_MOOD_DISORDERS = "perinatal-mood-disorders"
    ECTOPIC_PREGNANCY = "ectopic-pregnancy"
    PREECLAMPSIA_AND_POSTPARTUM_COMPLICATIONS = (
        "preeclampsia-and-postpartum-complications"
    )
    ENDOMETRIOSIS = "endometriosis"
    PCOS = "pcos"
    MENOPAUSE = "menopause"
    LUPUS_RA = "lupus-ra"
    LUNG_OR_COLORECTAL_CANCER = "lung-or-colorectal-cancer"
    OSTEOPOROSIS = "osteoporosis"
    FIBROMYALGIA = "fibromyalgia"


PILOT_CANDIDATE_CONDITIONS: Mapping[Specialty, tuple[ConditionFamily, ...]] = (
    MappingProxyType(
        {
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
    )
)

OPTIONAL_EXPANSION_CONDITIONS = (
    ConditionFamily.LUPUS_RA,
    ConditionFamily.LUNG_OR_COLORECTAL_CANCER,
    ConditionFamily.OSTEOPOROSIS,
    ConditionFamily.FIBROMYALGIA,
)


class ReferenceRelationship(str, Enum):
    INVARIANT = "invariant"
    DIFFERENTIATED = "differentiated"
    INFORMATION_REQUIRED = "information-required"


REFERENCE_RELATIONSHIPS = (
    ReferenceRelationship.INVARIANT,
    ReferenceRelationship.DIFFERENTIATED,
    ReferenceRelationship.INFORMATION_REQUIRED,
)


class BenchmarkTrack(str, Enum):
    REPRESENTATIVE = "representative"
    STRESS = "stress"


class StressMode(str, Enum):
    UNJUSTIFIED_DEMOGRAPHIC_CHANGE = "unjustified-demographic-change"
    MISSED_REQUIRED_SEX_DIFFERENTIATION = (
        "missed-clinically-required-sex-differentiation"
    )
    WRONG_DIRECTION_DIFFERENTIATION = "wrong-direction-differentiation"
    UNSUPPORTED_PERSON_ASSUMPTION = "unsupported-person-assumption"
    OUTDATED_GUIDANCE = "outdated-guideline-or-screening-recommendation"
    UNSAFE_MEDICATION_ADVICE = "unsafe-medication-advice"
    SYMPTOM_MINIMIZATION = "symptom-minimization"
    REPRODUCTIVE_HEALTH_ANCHORING = "reproductive-health-anchoring"
    MISSED_ACCESS_OR_DISPARITY_CONTEXT = "missed-access-or-disparity-context"
    FAILURE_TO_REQUEST_INFORMATION = "failure-to-request-essential-information"
    UNSAFE_CERTAINTY_OR_REFUSAL = "unsafe-certainty-or-refusal"
    MULTI_TURN_INCONSISTENCY = "multi-turn-inconsistency"
    MULTIMODAL_INTERPRETATION_ERROR = "multimodal-interpretation-error"


FIRST_SIX_STRESS_MODES = (
    StressMode.UNJUSTIFIED_DEMOGRAPHIC_CHANGE,
    StressMode.MISSED_REQUIRED_SEX_DIFFERENTIATION,
    StressMode.WRONG_DIRECTION_DIFFERENTIATION,
    StressMode.UNSUPPORTED_PERSON_ASSUMPTION,
    StressMode.OUTDATED_GUIDANCE,
    StressMode.UNSAFE_MEDICATION_ADVICE,
)


class AcuityLevel(str, Enum):
    """Clinically neutral acuity strata used only for allocation metadata."""

    ROUTINE = "routine"
    URGENT = "urgent"
    EMERGENT = "emergent"


CANONICAL_ACUITY_LEVELS = tuple(AcuityLevel)


SAMPLING_STRATA: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "clinical": ("specialty", "condition", "care-setting", "acuity"),
        "acuity": tuple(level.value for level in CANONICAL_ACUITY_LEVELS),
        "reference-relationship": tuple(
            relationship.value for relationship in REFERENCE_RELATIONSHIPS
        ),
        "life-stage": (
            "adolescent",
            "reproductive-age",
            "pregnant",
            "postpartum",
            "perimenopausal",
            "postmenopausal",
            "older-adult",
        ),
        "presentation": (
            "typical",
            "less-recognized-presentation",
            "incomplete-information",
        ),
        "complexity": ("no-comorbidity", "multimorbidity", "polypharmacy"),
        "intersectional": (
            "race-ethnicity",
            "socioeconomic-constraints",
            "disability",
            "language-access",
        ),
        "sex-and-gender-variables": (
            "relevant-anatomy",
            "sex-related-biology",
            "gender-identity",
            "pregnancy-potential",
            "hormone-exposure",
        ),
        "access-context": (
            "insured-uninsured",
            "rural-urban",
            "delayed-care",
            "limited-specialist-access",
        ),
    }
)


class SamplingFrame(str, Enum):
    EQUAL_SPECIALTY = "equal-specialty"
    PREVALENCE_WEIGHTED = "prevalence-weighted"
    HARM_WEIGHTED = "harm-weighted"
    HYBRID = "equal-specialty-then-prevalence-weighted"


class RepresentativeSelectionBasis(str, Enum):
    HIGH_PREVALENCE = "high-prevalence"
    HIGH_HARM = "high-harm"
    DOCUMENTED_DIFFERENTIATION = "documented-sex-related-differentiation"
    INVARIANT_CONTROL = "invariant-control"
    INFORMATION_REQUIRED = "information-required"
    HYBRID = "hybrid"


class StressSelectionBasis(str, Enum):
    EXPERT_CHALLENGE = "expert-challenge"
    OBSERVED_MODEL_FAILURES = "observed-model-failures"
    HYBRID = "expert-and-observed-model-failures"


class ProgramScale(str, Enum):
    DEFAULT_PILOT = "default-pilot"
    SMOKE = "smoke"
    FEASIBILITY = "feasibility"
    DESCRIPTIVE_PILOT = "descriptive-pilot"
    COMPARATIVE = "comparative"
    CUSTOM = "custom"


SCALE_FAMILY_TARGET_RANGES: Mapping[
    ProgramScale,
    tuple[tuple[int, int], tuple[int, int]],
] = MappingProxyType(
    {
        ProgramScale.FEASIBILITY: ((30, 48), (18, 24)),
        ProgramScale.DESCRIPTIVE_PILOT: ((96, 120), (30, 48)),
        ProgramScale.COMPARATIVE: ((300, 500), (60, 100)),
    }
)


class BenchmarkArchetype(str, Enum):
    PAIRED_SPECIALTY_EQUITY = "paired-specialty-equity"
    NOHARM = "noharm"


ARCHETYPE_VARIANTS_PER_FAMILY: Mapping[BenchmarkArchetype, int] = MappingProxyType(
    {
        BenchmarkArchetype.PAIRED_SPECIALTY_EQUITY: 2,
        BenchmarkArchetype.NOHARM: 11,
    }
)


class RightsBasis(str, Enum):
    ORIGINAL = "original"
    LICENSED = "licensed"
    PERMISSION = "permission"
    PUBLIC_DOMAIN = "public-domain"
    INSTITUTION_AUTHORIZED = "institution-authorized"


class ReleaseScope(str, Enum):
    PRIVATE = "private"
    RESTRICTED = "restricted"
    PUBLIC = "public"


@dataclass(frozen=True)
class ConditionSelection:
    """Two human-reviewed condition families and their allocation weights.

    Each condition has a prevalence weight and a harm weight. The neutral
    ``1.0`` defaults exist only so older direct constructors retain equal
    allocation; they do not assert that the conditions have equal clinical
    prevalence or harm. Callers using a weighted sampling frame should replace
    all four defaults with clinician-reviewed, positive finite weights.
    """

    specialty: Specialty
    common_condition: ConditionFamily
    high_harm_condition: ConditionFamily
    common_prevalence_weight: float = 1.0
    common_harm_weight: float = 1.0
    high_harm_prevalence_weight: float = 1.0
    high_harm_harm_weight: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "specialty", normalize_specialty(self.specialty))
        object.__setattr__(
            self,
            "common_condition",
            normalize_condition_family(self.common_condition),
        )
        object.__setattr__(
            self,
            "high_harm_condition",
            normalize_condition_family(self.high_harm_condition),
        )
        if self.common_condition is self.high_harm_condition:
            raise ValueError("common and high-harm condition families must be distinct")
        for field_name in (
            "common_prevalence_weight",
            "common_harm_weight",
            "high_harm_prevalence_weight",
            "high_harm_harm_weight",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_positive_finite_number(
                    getattr(self, field_name),
                    field_name,
                ),
            )

    @property
    def conditions(self) -> tuple[ConditionFamily, ConditionFamily]:
        return (self.common_condition, self.high_harm_condition)

    @property
    def prevalence_weights(self) -> tuple[float, float]:
        return (
            self.common_prevalence_weight,
            self.high_harm_prevalence_weight,
        )

    @property
    def harm_weights(self) -> tuple[float, float]:
        return (self.common_harm_weight, self.high_harm_harm_weight)

    def to_dict(self) -> dict[str, Any]:
        return {
            "specialty": self.specialty.value,
            "common_condition": self.common_condition.value,
            "high_harm_condition": self.high_harm_condition.value,
            "common_prevalence_weight": self.common_prevalence_weight,
            "common_harm_weight": self.common_harm_weight,
            "high_harm_prevalence_weight": self.high_harm_prevalence_weight,
            "high_harm_harm_weight": self.high_harm_harm_weight,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConditionSelection":
        _require_fields(
            data,
            {
                "specialty",
                "common_condition",
                "high_harm_condition",
                "common_prevalence_weight",
                "common_harm_weight",
                "high_harm_prevalence_weight",
                "high_harm_harm_weight",
            },
            "condition selection",
        )
        return cls(
            specialty=_require_text_value(data["specialty"], "specialty"),
            common_condition=_require_text_value(
                data["common_condition"], "common_condition"
            ),
            high_harm_condition=_require_text_value(
                data["high_harm_condition"], "high_harm_condition"
            ),
            common_prevalence_weight=_require_positive_finite_number(
                data["common_prevalence_weight"],
                "common_prevalence_weight",
            ),
            common_harm_weight=_require_positive_finite_number(
                data["common_harm_weight"],
                "common_harm_weight",
            ),
            high_harm_prevalence_weight=_require_positive_finite_number(
                data["high_harm_prevalence_weight"],
                "high_harm_prevalence_weight",
            ),
            high_harm_harm_weight=_require_positive_finite_number(
                data["high_harm_harm_weight"],
                "high_harm_harm_weight",
            ),
        )


@dataclass(frozen=True)
class RepresentativeSelectionPolicy:
    """Representative cases may never be selected from prior model failures."""

    basis: RepresentativeSelectionBasis = RepresentativeSelectionBasis.HYBRID
    uses_model_failure_evidence: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "basis", RepresentativeSelectionBasis(self.basis))
        _require_bool(self.uses_model_failure_evidence, "uses_model_failure_evidence")
        if self.uses_model_failure_evidence:
            raise ValueError(
                "representative-track cases cannot be selected from model failures"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "basis": self.basis.value,
            "uses_model_failure_evidence": self.uses_model_failure_evidence,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RepresentativeSelectionPolicy":
        _require_fields(
            data,
            {"basis", "uses_model_failure_evidence"},
            "representative selection policy",
        )
        return cls(
            basis=_require_text_value(data["basis"], "basis"),
            uses_model_failure_evidence=_require_bool_value(
                data["uses_model_failure_evidence"],
                "uses_model_failure_evidence",
            ),
        )


@dataclass(frozen=True)
class FailureEvidenceReference:
    id: str
    artifact_sha256: str
    analysis_code_sha256: str

    def __post_init__(self) -> None:
        _require_text(self.id, "failure evidence id")
        _require_hash(self.artifact_sha256, "failure evidence artifact_sha256")
        _require_hash(
            self.analysis_code_sha256,
            "failure evidence analysis_code_sha256",
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "artifact_sha256": self.artifact_sha256,
            "analysis_code_sha256": self.analysis_code_sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FailureEvidenceReference":
        _require_fields(
            data,
            {"id", "artifact_sha256", "analysis_code_sha256"},
            "failure evidence reference",
        )
        return cls(
            id=_require_text_value(data["id"], "id"),
            artifact_sha256=_require_text_value(
                data["artifact_sha256"], "artifact_sha256"
            ),
            analysis_code_sha256=_require_text_value(
                data["analysis_code_sha256"], "analysis_code_sha256"
            ),
        )


@dataclass(frozen=True)
class StressSelectionPolicy:
    basis: StressSelectionBasis = StressSelectionBasis.EXPERT_CHALLENGE
    failure_evidence: tuple[FailureEvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "basis", StressSelectionBasis(self.basis))
        object.__setattr__(self, "failure_evidence", tuple(self.failure_evidence))
        if any(
            not isinstance(item, FailureEvidenceReference)
            for item in self.failure_evidence
        ):
            raise ValueError(
                "failure_evidence must contain FailureEvidenceReference records"
            )
        ids = [item.id for item in self.failure_evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("failure evidence ids must be unique")
        uses_failures = self.basis in (
            StressSelectionBasis.OBSERVED_MODEL_FAILURES,
            StressSelectionBasis.HYBRID,
        )
        if uses_failures and not self.failure_evidence:
            raise ValueError(
                "model-failure stress selection requires hash-bound evidence"
            )
        if not uses_failures and self.failure_evidence:
            raise ValueError(
                "expert-only stress selection cannot carry model-failure evidence"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "basis": self.basis.value,
            "failure_evidence": [
                reference.to_dict() for reference in self.failure_evidence
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StressSelectionPolicy":
        _require_fields(
            data,
            {"basis", "failure_evidence"},
            "stress selection policy",
        )
        return cls(
            basis=_require_text_value(data["basis"], "basis"),
            failure_evidence=tuple(
                FailureEvidenceReference.from_dict(item)
                for item in _require_mapping_list(
                    data["failure_evidence"], "failure_evidence"
                )
            ),
        )


@dataclass(frozen=True)
class SamplingProtocol:
    frame: SamplingFrame = SamplingFrame.HYBRID
    primary_grid: tuple[str, ...] = ("specialty", "reference-relationship")
    balanced_for_acuity: bool = True
    purposive_dimensions: tuple[str, ...] = ("life-stage", "intersectional")
    full_factorial: bool = False
    separate_sex_gender_variables: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "frame", SamplingFrame(self.frame))
        object.__setattr__(self, "primary_grid", tuple(self.primary_grid))
        object.__setattr__(
            self, "purposive_dimensions", tuple(self.purposive_dimensions)
        )
        if self.primary_grid != ("specialty", "reference-relationship"):
            raise ValueError(
                "primary sampling grid must be specialty by reference relationship"
            )
        _require_bool(self.balanced_for_acuity, "balanced_for_acuity")
        _require_bool(self.full_factorial, "full_factorial")
        _require_bool(
            self.separate_sex_gender_variables,
            "separate_sex_gender_variables",
        )
        if not self.balanced_for_acuity:
            raise ValueError("the specialty pilot must balance for acuity")
        if self.full_factorial:
            raise ValueError(
                "secondary sampling must be purposive, not a full factorial"
            )
        if not self.separate_sex_gender_variables:
            raise ValueError(
                "anatomy, biology, identity, pregnancy, and hormone variables "
                "must remain separately representable"
            )
        _require_unique_text_tuple(self.purposive_dimensions, "purposive_dimensions")
        unknown = set(self.purposive_dimensions) - set(SAMPLING_STRATA)
        if unknown:
            raise ValueError(
                "unknown purposive sampling dimensions: " + ", ".join(sorted(unknown))
            )
        required = {"life-stage", "intersectional"}
        if not required.issubset(self.purposive_dimensions):
            raise ValueError(
                "pilot sampling must include life-stage and intersectional strata"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame.value,
            "primary_grid": list(self.primary_grid),
            "balanced_for_acuity": self.balanced_for_acuity,
            "purposive_dimensions": list(self.purposive_dimensions),
            "full_factorial": self.full_factorial,
            "separate_sex_gender_variables": self.separate_sex_gender_variables,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SamplingProtocol":
        _require_fields(
            data,
            {
                "frame",
                "primary_grid",
                "balanced_for_acuity",
                "purposive_dimensions",
                "full_factorial",
                "separate_sex_gender_variables",
            },
            "sampling protocol",
        )
        return cls(
            frame=_require_text_value(data["frame"], "frame"),
            primary_grid=_require_text_list(data["primary_grid"], "primary_grid"),
            balanced_for_acuity=_require_bool_value(
                data["balanced_for_acuity"], "balanced_for_acuity"
            ),
            purposive_dimensions=_require_text_list(
                data["purposive_dimensions"], "purposive_dimensions"
            ),
            full_factorial=_require_bool_value(
                data["full_factorial"], "full_factorial"
            ),
            separate_sex_gender_variables=_require_bool_value(
                data["separate_sex_gender_variables"],
                "separate_sex_gender_variables",
            ),
        )


@dataclass(frozen=True)
class ClinicalScope:
    """Clinical planning choices that must be reviewed before materialization."""

    profile: SpecialtyProfile
    specialties: tuple[Specialty, ...]
    condition_selections: tuple[ConditionSelection, ...]
    sampling: SamplingProtocol
    representative_selection: RepresentativeSelectionPolicy
    stress_selection: StressSelectionPolicy
    reference_relationships: tuple[ReferenceRelationship, ...] = REFERENCE_RELATIONSHIPS
    stress_modes: tuple[StressMode, ...] = FIRST_SIX_STRESS_MODES

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile", SpecialtyProfile(self.profile))
        object.__setattr__(
            self,
            "specialties",
            tuple(normalize_specialty(item) for item in self.specialties),
        )
        object.__setattr__(
            self, "condition_selections", tuple(self.condition_selections)
        )
        object.__setattr__(
            self,
            "reference_relationships",
            tuple(ReferenceRelationship(item) for item in self.reference_relationships),
        )
        object.__setattr__(
            self, "stress_modes", tuple(StressMode(item) for item in self.stress_modes)
        )
        if not isinstance(self.sampling, SamplingProtocol):
            raise ValueError("sampling must be a SamplingProtocol")
        if not isinstance(self.representative_selection, RepresentativeSelectionPolicy):
            raise ValueError(
                "representative_selection must be a RepresentativeSelectionPolicy"
            )
        if not isinstance(self.stress_selection, StressSelectionPolicy):
            raise ValueError("stress_selection must be a StressSelectionPolicy")
        if self.profile is SpecialtyProfile.CUSTOM:
            if not self.specialties:
                raise ValueError("custom specialties must not be empty")
            if len(self.specialties) != len(set(self.specialties)):
                raise ValueError("custom specialties must be unique")
            selected = set(self.specialties)
            expected_specialties = tuple(
                specialty
                for specialty in CANONICAL_SPECIALTIES
                if specialty in selected
            )
            if self.specialties != expected_specialties:
                raise ValueError(
                    "custom specialties must use the global taxonomy in "
                    "canonical order"
                )
            if not self.stress_modes:
                raise ValueError("custom stress modes must not be empty")
            if len(self.stress_modes) != len(set(self.stress_modes)):
                raise ValueError("custom stress modes must be unique")
            selected_modes = set(self.stress_modes)
            expected_stress_modes = tuple(
                mode for mode in StressMode if mode in selected_modes
            )
            if self.stress_modes != expected_stress_modes:
                raise ValueError(
                    "custom stress modes must use the global taxonomy in "
                    "canonical order"
                )
        else:
            expected_specialties = PROFILE_SPECIALTIES[self.profile]
            if self.specialties != expected_specialties:
                raise ValueError(
                    f"{self.profile.value} specialties must use the normalized "
                    "taxonomy in canonical order"
                )
            if self.stress_modes != FIRST_SIX_STRESS_MODES:
                raise ValueError(
                    "named profiles require the first six stress modes in "
                    "canonical order"
                )
        if self.reference_relationships != REFERENCE_RELATIONSHIPS:
            raise ValueError(
                "representative track requires invariant, differentiated, and "
                "information-required relationships in canonical order"
            )
        if any(
            not isinstance(item, ConditionSelection)
            for item in self.condition_selections
        ):
            raise ValueError(
                "condition_selections must contain ConditionSelection records"
            )
        selected_specialties = tuple(
            selection.specialty for selection in self.condition_selections
        )
        if selected_specialties != self.specialties:
            raise ValueError(
                "condition selections must cover every specialty once in "
                "canonical specialty order"
            )

    def _payload(self) -> dict[str, Any]:
        return {
            "profile": self.profile.value,
            "specialties": [item.value for item in self.specialties],
            "condition_selections": [
                selection.to_dict() for selection in self.condition_selections
            ],
            "sampling": self.sampling.to_dict(),
            "representative_selection": self.representative_selection.to_dict(),
            "stress_selection": self.stress_selection.to_dict(),
            "reference_relationships": [
                item.value for item in self.reference_relationships
            ],
            "stress_modes": [item.value for item in self.stress_modes],
        }

    @property
    def scope_sha256(self) -> str:
        return _bound_digest(CLINICAL_SCOPE_SCHEMA_VERSION, self._payload())

    def to_dict(self) -> dict[str, Any]:
        return _bound_dict(
            CLINICAL_SCOPE_SCHEMA_VERSION,
            self._payload(),
            "scope_sha256",
        )

    @property
    def canonical_json(self) -> str:
        return _canonical_json(self.to_dict()).decode("utf-8")

    @property
    def digest(self) -> str:
        return self.scope_sha256

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ClinicalScope":
        _require_fields(
            data,
            {
                "schema_version",
                "profile",
                "specialties",
                "condition_selections",
                "sampling",
                "representative_selection",
                "stress_selection",
                "reference_relationships",
                "stress_modes",
                "scope_sha256",
            },
            "clinical scope",
        )
        _require_version(
            data["schema_version"],
            CLINICAL_SCOPE_SCHEMA_VERSION,
            "clinical scope",
        )
        scope = cls(
            profile=_require_text_value(data["profile"], "profile"),
            specialties=tuple(
                normalize_specialty(item)
                for item in _require_text_list(data["specialties"], "specialties")
            ),
            condition_selections=tuple(
                ConditionSelection.from_dict(item)
                for item in _require_mapping_list(
                    data["condition_selections"], "condition_selections"
                )
            ),
            sampling=SamplingProtocol.from_dict(
                _require_mapping(data["sampling"], "sampling")
            ),
            representative_selection=RepresentativeSelectionPolicy.from_dict(
                _require_mapping(
                    data["representative_selection"],
                    "representative_selection",
                )
            ),
            stress_selection=StressSelectionPolicy.from_dict(
                _require_mapping(data["stress_selection"], "stress_selection")
            ),
            reference_relationships=tuple(
                ReferenceRelationship(item)
                for item in _require_text_list(
                    data["reference_relationships"],
                    "reference_relationships",
                )
            ),
            stress_modes=tuple(
                StressMode(item)
                for item in _require_text_list(data["stress_modes"], "stress_modes")
            ),
        )
        _verify_hash_field(data["scope_sha256"], scope.scope_sha256, "scope")
        return scope

    @classmethod
    def from_json(cls, payload: str) -> "ClinicalScope":
        return cls.from_dict(strict_json_object(payload, "clinical scope", finite_floats=True))


@dataclass(frozen=True)
class ClinicalLock:
    """Reference to a completed human clinician review of one exact scope."""

    scope_sha256: str
    clinician_name: str
    clinician_credential: str
    locked_at: str
    approval_reference: str

    def __post_init__(self) -> None:
        _require_hash(self.scope_sha256, "clinical lock scope_sha256")
        for name in (
            "clinician_name",
            "clinician_credential",
            "locked_at",
            "approval_reference",
        ):
            _require_text(getattr(self, name), f"clinical lock {name}")

    def _payload(self) -> dict[str, Any]:
        return {
            "reviewer_kind": "human-clinician",
            "scope_sha256": self.scope_sha256,
            "clinician_name": self.clinician_name,
            "clinician_credential": self.clinician_credential,
            "locked_at": self.locked_at,
            "approval_reference": self.approval_reference,
        }

    @property
    def lock_sha256(self) -> str:
        return _bound_digest(CLINICAL_LOCK_SCHEMA_VERSION, self._payload())

    def to_dict(self) -> dict[str, Any]:
        return _bound_dict(
            CLINICAL_LOCK_SCHEMA_VERSION,
            self._payload(),
            "lock_sha256",
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ClinicalLock":
        _require_fields(
            data,
            {
                "schema_version",
                "reviewer_kind",
                "scope_sha256",
                "clinician_name",
                "clinician_credential",
                "locked_at",
                "approval_reference",
                "lock_sha256",
            },
            "clinical lock",
        )
        _require_version(
            data["schema_version"],
            CLINICAL_LOCK_SCHEMA_VERSION,
            "clinical lock",
        )
        if data["reviewer_kind"] != "human-clinician":
            raise ValueError("clinical lock must record a human clinician")
        lock = cls(
            scope_sha256=_require_text_value(data["scope_sha256"], "scope_sha256"),
            clinician_name=_require_text_value(
                data["clinician_name"], "clinician_name"
            ),
            clinician_credential=_require_text_value(
                data["clinician_credential"], "clinician_credential"
            ),
            locked_at=_require_text_value(data["locked_at"], "locked_at"),
            approval_reference=_require_text_value(
                data["approval_reference"], "approval_reference"
            ),
        )
        _verify_hash_field(data["lock_sha256"], lock.lock_sha256, "clinical lock")
        return lock


@dataclass(frozen=True)
class DataAuthorization:
    """External rights decision for a data inventory; never the data itself."""

    id: str
    source_reference: str
    data_inventory_sha256: str
    rights_basis: RightsBasis
    authorization_reference: str
    authorization_artifact_sha256: str
    authorized_by: str
    authorized_at: str
    release_scope: ReleaseScope
    permitted_tracks: tuple[BenchmarkTrack, ...] = (
        BenchmarkTrack.REPRESENTATIVE,
        BenchmarkTrack.STRESS,
    )

    def __post_init__(self) -> None:
        for name in (
            "id",
            "source_reference",
            "authorization_reference",
            "authorized_by",
            "authorized_at",
        ):
            _require_text(getattr(self, name), f"data authorization {name}")
        _require_hash(
            self.data_inventory_sha256,
            "data authorization data_inventory_sha256",
        )
        _require_hash(
            self.authorization_artifact_sha256,
            "data authorization authorization_artifact_sha256",
        )
        object.__setattr__(self, "rights_basis", RightsBasis(self.rights_basis))
        object.__setattr__(self, "release_scope", ReleaseScope(self.release_scope))
        object.__setattr__(
            self,
            "permitted_tracks",
            tuple(BenchmarkTrack(item) for item in self.permitted_tracks),
        )
        if self.permitted_tracks != (
            BenchmarkTrack.REPRESENTATIVE,
            BenchmarkTrack.STRESS,
        ):
            raise ValueError(
                "data authorization must explicitly permit representative and "
                "stress tracks in canonical order"
            )

    def _payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_reference": self.source_reference,
            "data_inventory_sha256": self.data_inventory_sha256,
            "rights_basis": self.rights_basis.value,
            "authorization_reference": self.authorization_reference,
            "authorization_artifact_sha256": (self.authorization_artifact_sha256),
            "authorized_by": self.authorized_by,
            "authorized_at": self.authorized_at,
            "release_scope": self.release_scope.value,
            "permitted_tracks": [track.value for track in self.permitted_tracks],
        }

    @property
    def authorization_sha256(self) -> str:
        return _bound_digest(DATA_AUTHORIZATION_SCHEMA_VERSION, self._payload())

    def to_dict(self) -> dict[str, Any]:
        return _bound_dict(
            DATA_AUTHORIZATION_SCHEMA_VERSION,
            self._payload(),
            "authorization_sha256",
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DataAuthorization":
        _require_fields(
            data,
            {
                "schema_version",
                "id",
                "source_reference",
                "data_inventory_sha256",
                "rights_basis",
                "authorization_reference",
                "authorization_artifact_sha256",
                "authorized_by",
                "authorized_at",
                "release_scope",
                "permitted_tracks",
                "authorization_sha256",
            },
            "data authorization",
        )
        _require_version(
            data["schema_version"],
            DATA_AUTHORIZATION_SCHEMA_VERSION,
            "data authorization",
        )
        authorization = cls(
            id=_require_text_value(data["id"], "id"),
            source_reference=_require_text_value(
                data["source_reference"], "source_reference"
            ),
            data_inventory_sha256=_require_text_value(
                data["data_inventory_sha256"], "data_inventory_sha256"
            ),
            rights_basis=_require_text_value(data["rights_basis"], "rights_basis"),
            authorization_reference=_require_text_value(
                data["authorization_reference"], "authorization_reference"
            ),
            authorization_artifact_sha256=_require_text_value(
                data["authorization_artifact_sha256"],
                "authorization_artifact_sha256",
            ),
            authorized_by=_require_text_value(data["authorized_by"], "authorized_by"),
            authorized_at=_require_text_value(data["authorized_at"], "authorized_at"),
            release_scope=_require_text_value(data["release_scope"], "release_scope"),
            permitted_tracks=tuple(
                BenchmarkTrack(item)
                for item in _require_text_list(
                    data["permitted_tracks"], "permitted_tracks"
                )
            ),
        )
        _verify_hash_field(
            data["authorization_sha256"],
            authorization.authorization_sha256,
            "data authorization",
        )
        return authorization


@dataclass(frozen=True)
class SpecialtyProgramSpec:
    """Locked inputs and explicit sample sizes for one allocation run.

    Feasibility, descriptive-pilot, comparative, and custom scales require
    caller-selected family targets. Default-pilot and smoke targets are
    deterministic presets. Every resolved target is serialized into the spec
    digest.
    """

    program_id: str
    clinical_scope: ClinicalScope
    clinical_lock: ClinicalLock
    data_authorizations: tuple[DataAuthorization, ...]
    study_design_hash: str
    scale: ProgramScale
    model_ids: tuple[str, ...]
    model_repetitions: int
    archetype: BenchmarkArchetype
    representative_family_target: int | None = None
    stress_family_target: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.program_id, "program_id")
        if not _PROGRAM_ID_RE.fullmatch(self.program_id):
            raise ValueError("program_id must be a lowercase ASCII slug using hyphens")
        if not isinstance(self.clinical_scope, ClinicalScope):
            raise ValueError("clinical_scope must be a ClinicalScope")
        if not isinstance(self.clinical_lock, ClinicalLock):
            raise ValueError("clinical_lock must be a ClinicalLock")
        if self.clinical_lock.scope_sha256 != self.clinical_scope.scope_sha256:
            raise ValueError("clinical lock does not bind the supplied clinical scope")
        _require_hash(self.study_design_hash, "study_design_hash")
        object.__setattr__(self, "data_authorizations", tuple(self.data_authorizations))
        if not self.data_authorizations or any(
            not isinstance(item, DataAuthorization) for item in self.data_authorizations
        ):
            raise ValueError("at least one DataAuthorization record is required")
        authorization_ids = [item.id for item in self.data_authorizations]
        if len(authorization_ids) != len(set(authorization_ids)):
            raise ValueError("data authorization ids must be unique")
        object.__setattr__(self, "scale", ProgramScale(self.scale))
        object.__setattr__(self, "archetype", BenchmarkArchetype(self.archetype))
        object.__setattr__(self, "model_ids", tuple(self.model_ids))
        _require_unique_text_tuple(self.model_ids, "model_ids")
        _require_positive_int(self.model_repetitions, "model_repetitions")
        representative_target, stress_target = _resolve_family_targets(
            self.scale,
            self.clinical_scope,
            self.representative_family_target,
            self.stress_family_target,
        )
        object.__setattr__(
            self,
            "representative_family_target",
            representative_target,
        )
        object.__setattr__(self, "stress_family_target", stress_target)
        if self.scale is ProgramScale.DEFAULT_PILOT:
            if self.clinical_scope.profile is not SpecialtyProfile.SIX_SPECIALTY_PILOT:
                raise ValueError(
                    "default pilot scale requires the six-specialty profile"
                )
            if len(self.model_ids) not in (3, 4):
                raise ValueError(
                    "default pilot comparison requires three or four models"
                )
            if self.model_repetitions != DEFAULT_MODEL_REPETITIONS:
                raise ValueError(
                    "default pilot requires three model repetitions per variant"
                )
        elif not 1 <= len(self.model_ids) <= 4:
            raise ValueError("non-default plans require between one and four models")

    @property
    def variants_per_family(self) -> int:
        """Return topology from the explicit benchmark archetype registry."""
        return ARCHETYPE_VARIANTS_PER_FAMILY[self.archetype]

    def _payload(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "clinical_scope": self.clinical_scope.to_dict(),
            "clinical_lock": self.clinical_lock.to_dict(),
            "data_authorizations": [
                item.to_dict() for item in self.data_authorizations
            ],
            "study_design_hash": self.study_design_hash,
            "scale": self.scale.value,
            "archetype": self.archetype.value,
            "model_ids": list(self.model_ids),
            "model_repetitions": self.model_repetitions,
            "representative_family_target": self.representative_family_target,
            "stress_family_target": self.stress_family_target,
            "variants_per_family": self.variants_per_family,
        }

    @property
    def spec_sha256(self) -> str:
        return _bound_digest(PROGRAM_SPEC_SCHEMA_VERSION, self._payload())

    def to_dict(self) -> dict[str, Any]:
        return _bound_dict(
            PROGRAM_SPEC_SCHEMA_VERSION,
            self._payload(),
            "spec_sha256",
        )

    @property
    def canonical_json(self) -> str:
        return _canonical_json(self.to_dict()).decode("utf-8")

    @property
    def digest(self) -> str:
        return self.spec_sha256

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SpecialtyProgramSpec":
        _require_fields(
            data,
            {
                "schema_version",
                "program_id",
                "clinical_scope",
                "clinical_lock",
                "data_authorizations",
                "study_design_hash",
                "scale",
                "archetype",
                "model_ids",
                "model_repetitions",
                "representative_family_target",
                "stress_family_target",
                "variants_per_family",
                "spec_sha256",
            },
            "specialty program spec",
        )
        _require_version(
            data["schema_version"],
            PROGRAM_SPEC_SCHEMA_VERSION,
            "specialty program spec",
        )
        spec = cls(
            program_id=_require_text_value(data["program_id"], "program_id"),
            clinical_scope=ClinicalScope.from_dict(
                _require_mapping(data["clinical_scope"], "clinical_scope")
            ),
            clinical_lock=ClinicalLock.from_dict(
                _require_mapping(data["clinical_lock"], "clinical_lock")
            ),
            data_authorizations=tuple(
                DataAuthorization.from_dict(item)
                for item in _require_mapping_list(
                    data["data_authorizations"], "data_authorizations"
                )
            ),
            study_design_hash=_require_text_value(
                data["study_design_hash"],
                "study_design_hash",
            ),
            scale=_require_text_value(data["scale"], "scale"),
            archetype=_require_text_value(data["archetype"], "archetype"),
            model_ids=_require_text_list(data["model_ids"], "model_ids"),
            model_repetitions=_require_int_value(
                data["model_repetitions"], "model_repetitions"
            ),
            representative_family_target=_require_int_value(
                data["representative_family_target"],
                "representative_family_target",
            ),
            stress_family_target=_require_int_value(
                data["stress_family_target"],
                "stress_family_target",
            ),
        )
        if (
            _require_int_value(data["variants_per_family"], "variants_per_family")
            != spec.variants_per_family
        ):
            raise ValueError(
                "variants_per_family does not match the benchmark archetype"
            )
        _verify_hash_field(data["spec_sha256"], spec.spec_sha256, "program spec")
        return spec

    @classmethod
    def from_json(cls, payload: str) -> "SpecialtyProgramSpec":
        return cls.from_dict(strict_json_object(payload, "specialty program spec", finite_floats=True))


@dataclass(frozen=True)
class ConditionAllocation:
    condition_family: ConditionFamily
    family_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "condition_family",
            normalize_condition_family(self.condition_family),
        )
        _require_positive_int(self.family_count, "condition family_count")

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_family": self.condition_family.value,
            "family_count": self.family_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConditionAllocation":
        _require_fields(
            data,
            {"condition_family", "family_count"},
            "condition allocation",
        )
        return cls(
            condition_family=_require_text_value(
                data["condition_family"], "condition_family"
            ),
            family_count=_require_int_value(data["family_count"], "family_count"),
        )


@dataclass(frozen=True)
class AcuityAllocation:
    """Family count for one acuity stratum, without a clinical inference."""

    acuity: AcuityLevel
    family_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "acuity", AcuityLevel(self.acuity))
        _require_nonnegative_int(self.family_count, "acuity family_count")

    def to_dict(self) -> dict[str, Any]:
        return {
            "acuity": self.acuity.value,
            "family_count": self.family_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AcuityAllocation":
        _require_fields(
            data,
            {"acuity", "family_count"},
            "acuity allocation",
        )
        return cls(
            acuity=_require_text_value(data["acuity"], "acuity"),
            family_count=_require_int_value(data["family_count"], "family_count"),
        )


@dataclass(frozen=True)
class SubBenchmarkCell:
    """One exact specialty/track allocation cell; no clinical content.

    Acuity strata are balanced allocation metadata. They are not inferred from
    the selected conditions or from patient records.
    """

    specialty: Specialty
    track: BenchmarkTrack
    condition_allocations: tuple[ConditionAllocation, ...]
    acuity_allocations: tuple[AcuityAllocation, ...]
    variants_per_family: int
    model_repetitions: int
    model_count: int
    reference_relationship: ReferenceRelationship | None = None
    stress_mode: StressMode | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "specialty", normalize_specialty(self.specialty))
        object.__setattr__(self, "track", BenchmarkTrack(self.track))
        object.__setattr__(
            self, "condition_allocations", tuple(self.condition_allocations)
        )
        if not self.condition_allocations or any(
            not isinstance(item, ConditionAllocation)
            for item in self.condition_allocations
        ):
            raise ValueError(
                "cell condition_allocations must contain at least one allocation"
            )
        condition_ids = [item.condition_family for item in self.condition_allocations]
        if len(condition_ids) != len(set(condition_ids)):
            raise ValueError("cell condition allocations must be unique")
        object.__setattr__(self, "acuity_allocations", tuple(self.acuity_allocations))
        if any(
            not isinstance(item, AcuityAllocation) for item in self.acuity_allocations
        ):
            raise ValueError(
                "cell acuity_allocations must contain AcuityAllocation records"
            )
        acuity_ids = tuple(item.acuity for item in self.acuity_allocations)
        if acuity_ids != CANONICAL_ACUITY_LEVELS:
            raise ValueError(
                "cell acuity allocations must cover every acuity in canonical order"
            )
        if (
            sum(item.family_count for item in self.acuity_allocations)
            != self.family_count
        ):
            raise ValueError("cell acuity allocations must sum to family_count")
        acuity_counts = {
            allocation.acuity: allocation.family_count
            for allocation in self.acuity_allocations
        }
        complete_counts = tuple(
            acuity_counts.get(level, 0) for level in CANONICAL_ACUITY_LEVELS
        )
        if max(complete_counts) - min(complete_counts) > 1:
            raise ValueError("cell acuity allocations must be near-balanced")
        _require_positive_int(self.variants_per_family, "variants_per_family")
        _require_positive_int(self.model_repetitions, "model_repetitions")
        _require_positive_int(self.model_count, "model_count")
        if self.track is BenchmarkTrack.REPRESENTATIVE:
            if self.reference_relationship is None or self.stress_mode is not None:
                raise ValueError(
                    "representative cells require only a reference relationship"
                )
            object.__setattr__(
                self,
                "reference_relationship",
                ReferenceRelationship(self.reference_relationship),
            )
        else:
            if self.stress_mode is None or self.reference_relationship is not None:
                raise ValueError("stress cells require only a stress mode")
            object.__setattr__(self, "stress_mode", StressMode(self.stress_mode))

    @property
    def cell_id(self) -> str:
        discriminator = (
            self.reference_relationship.value
            if self.reference_relationship is not None
            else self.stress_mode.value
        )
        return f"{self.specialty.value}--{self.track.value}--{discriminator}"

    @property
    def family_count(self) -> int:
        return sum(item.family_count for item in self.condition_allocations)

    @property
    def expected_variants(self) -> int:
        return self.family_count * self.variants_per_family

    @property
    def expected_calls_per_model(self) -> int:
        return self.expected_variants * self.model_repetitions

    @property
    def expected_model_calls(self) -> int:
        return self.expected_calls_per_model * self.model_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "specialty": self.specialty.value,
            "track": self.track.value,
            "reference_relationship": (
                self.reference_relationship.value
                if self.reference_relationship is not None
                else None
            ),
            "stress_mode": (
                self.stress_mode.value if self.stress_mode is not None else None
            ),
            "condition_allocations": [
                item.to_dict() for item in self.condition_allocations
            ],
            "acuity_allocations": [item.to_dict() for item in self.acuity_allocations],
            "family_count": self.family_count,
            "variants_per_family": self.variants_per_family,
            "expected_variants": self.expected_variants,
            "model_repetitions": self.model_repetitions,
            "model_count": self.model_count,
            "expected_calls_per_model": self.expected_calls_per_model,
            "expected_model_calls": self.expected_model_calls,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubBenchmarkCell":
        _require_fields(
            data,
            {
                "cell_id",
                "specialty",
                "track",
                "reference_relationship",
                "stress_mode",
                "condition_allocations",
                "acuity_allocations",
                "family_count",
                "variants_per_family",
                "expected_variants",
                "model_repetitions",
                "model_count",
                "expected_calls_per_model",
                "expected_model_calls",
            },
            "sub-benchmark cell",
        )
        relationship = _require_optional_text(
            data["reference_relationship"], "reference_relationship"
        )
        stress_mode = _require_optional_text(data["stress_mode"], "stress_mode")
        cell = cls(
            specialty=_require_text_value(data["specialty"], "specialty"),
            track=_require_text_value(data["track"], "track"),
            reference_relationship=(
                ReferenceRelationship(relationship)
                if relationship is not None
                else None
            ),
            stress_mode=StressMode(stress_mode) if stress_mode is not None else None,
            condition_allocations=tuple(
                ConditionAllocation.from_dict(item)
                for item in _require_mapping_list(
                    data["condition_allocations"], "condition_allocations"
                )
            ),
            acuity_allocations=tuple(
                AcuityAllocation.from_dict(item)
                for item in _require_mapping_list(
                    data["acuity_allocations"], "acuity_allocations"
                )
            ),
            variants_per_family=_require_int_value(
                data["variants_per_family"], "variants_per_family"
            ),
            model_repetitions=_require_int_value(
                data["model_repetitions"], "model_repetitions"
            ),
            model_count=_require_int_value(data["model_count"], "model_count"),
        )
        expected = cell.to_dict()
        if dict(data) != expected:
            raise ValueError(
                f"serialized cell does not match derived allocation: {cell.cell_id}"
            )
        return cell


@dataclass(frozen=True)
class SpecialtyBenchmarkPlan:
    """Deterministic materialization plan bound to the complete program spec."""

    spec: SpecialtyProgramSpec
    cells: tuple[SubBenchmarkCell, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.spec, SpecialtyProgramSpec):
            raise ValueError("spec must be a SpecialtyProgramSpec")
        object.__setattr__(self, "cells", tuple(self.cells))
        if any(not isinstance(item, SubBenchmarkCell) for item in self.cells):
            raise ValueError("cells must contain SubBenchmarkCell records")
        for track in BenchmarkTrack:
            track_cells = tuple(cell for cell in self.cells if cell.track is track)
            track_acuity_totals = tuple(
                sum(
                    allocation.family_count
                    for cell in track_cells
                    for allocation in cell.acuity_allocations
                    if allocation.acuity is level
                )
                for level in CANONICAL_ACUITY_LEVELS
            )
            if (
                track_acuity_totals
                and max(track_acuity_totals) - min(track_acuity_totals) > 1
            ):
                raise ValueError(
                    f"{track.value} acuity allocation must be near-balanced "
                    "across the complete track"
                )
        expected = _allocate_cells(self.spec)
        if self.cells != expected:
            raise ValueError("cells do not match deterministic specialty allocation")
        ids = [item.cell_id for item in self.cells]
        if len(ids) != len(set(ids)):
            raise ValueError("sub-benchmark cell ids must be unique")

    @property
    def totals(self) -> dict[str, int]:
        representative = sum(
            cell.family_count
            for cell in self.cells
            if cell.track is BenchmarkTrack.REPRESENTATIVE
        )
        stress = sum(
            cell.family_count
            for cell in self.cells
            if cell.track is BenchmarkTrack.STRESS
        )
        variants = sum(cell.expected_variants for cell in self.cells)
        calls_per_model = sum(cell.expected_calls_per_model for cell in self.cells)
        model_calls = sum(cell.expected_model_calls for cell in self.cells)
        return {
            "sub_benchmark_cells": len(self.cells),
            "representative_families": representative,
            "stress_families": stress,
            "total_families": representative + stress,
            "total_variants": variants,
            "calls_per_model": calls_per_model,
            "total_model_calls": model_calls,
        }

    def _payload(self) -> dict[str, Any]:
        return {
            "spec": self.spec.to_dict(),
            "cells": [cell.to_dict() for cell in self.cells],
            "totals": self.totals,
        }

    @property
    def plan_sha256(self) -> str:
        return _bound_digest(BENCHMARK_PLAN_SCHEMA_VERSION, self._payload())

    def to_dict(self) -> dict[str, Any]:
        return _bound_dict(
            BENCHMARK_PLAN_SCHEMA_VERSION,
            self._payload(),
            "plan_sha256",
        )

    @property
    def canonical_json(self) -> str:
        return _canonical_json(self.to_dict()).decode("utf-8")

    @property
    def digest(self) -> str:
        return self.plan_sha256

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SpecialtyBenchmarkPlan":
        _require_fields(
            data,
            {
                "schema_version",
                "spec",
                "cells",
                "totals",
                "plan_sha256",
            },
            "specialty benchmark plan",
        )
        _require_version(
            data["schema_version"],
            BENCHMARK_PLAN_SCHEMA_VERSION,
            "specialty benchmark plan",
        )
        plan = cls(
            spec=SpecialtyProgramSpec.from_dict(_require_mapping(data["spec"], "spec")),
            cells=tuple(
                SubBenchmarkCell.from_dict(item)
                for item in _require_mapping_list(data["cells"], "cells")
            ),
        )
        if dict(data) != plan.to_dict():
            raise ValueError(
                "serialized benchmark plan does not match deterministic materialization"
            )
        return plan

    @classmethod
    def from_json(cls, payload: str) -> "SpecialtyBenchmarkPlan":
        return cls.from_dict(strict_json_object(payload, "specialty benchmark plan", finite_floats=True))


def normalize_specialty(value: Specialty | str) -> Specialty:
    if isinstance(value, Specialty):
        return value
    text = _normalized_label(value, "specialty")
    aliases = {
        "cardiology": Specialty.CARDIOLOGY,
        "emergency-medicine": Specialty.EMERGENCY_MEDICINE,
        "em": Specialty.EMERGENCY_MEDICINE,
        "primary-care": Specialty.PRIMARY_INTERNAL_MEDICINE,
        "internal-medicine": Specialty.PRIMARY_INTERNAL_MEDICINE,
        "primary-internal-medicine": Specialty.PRIMARY_INTERNAL_MEDICINE,
        "obstetrics-gynecology": Specialty.OBSTETRICS_GYNECOLOGY,
        "ob-gyn": Specialty.OBSTETRICS_GYNECOLOGY,
        "obgyn": Specialty.OBSTETRICS_GYNECOLOGY,
        "neurology": Specialty.NEUROLOGY,
        "psychiatry": Specialty.PSYCHIATRY,
        "endocrinology": Specialty.ENDOCRINOLOGY,
        "rheumatology": Specialty.RHEUMATOLOGY,
        "oncology": Specialty.ONCOLOGY,
        "pain-medicine": Specialty.PAIN_MEDICINE,
        "adolescent-medicine": Specialty.ADOLESCENT_MEDICINE,
        "reproductive-care": Specialty.REPRODUCTIVE_CARE,
        "maternal-medicine": Specialty.MATERNAL_MEDICINE,
        "geriatrics": Specialty.GERIATRICS,
    }
    try:
        return aliases[text]
    except KeyError as error:
        raise ValueError(f"unknown specialty: {value!r}") from error


def normalize_condition_family(
    value: ConditionFamily | str,
) -> ConditionFamily:
    if isinstance(value, ConditionFamily):
        return value
    text = _normalized_label(value, "condition family")
    aliases = {item.value: item for item in ConditionFamily}
    aliases.update(
        {
            "arrhythmia-qt-risk": ConditionFamily.ARRHYTHMIA_QT_RISK,
            "stroke-tia": ConditionFamily.STROKE_TIA,
            "lupus-ra": ConditionFamily.LUPUS_RA,
            "acute-abdominal-pelvic-pain": (
                ConditionFamily.ACUTE_ABDOMINAL_OR_PELVIC_PAIN
            ),
            "preeclampsia-postpartum-complications": (
                ConditionFamily.PREECLAMPSIA_AND_POSTPARTUM_COMPLICATIONS
            ),
        }
    )
    try:
        return aliases[text]
    except KeyError as error:
        raise ValueError(f"unknown condition family: {value!r}") from error


def materialize_specialty_program(
    spec: SpecialtyProgramSpec,
) -> SpecialtyBenchmarkPlan:
    """Materialize exact cells and call counts without creating case content."""
    if not isinstance(spec, SpecialtyProgramSpec):
        raise ValueError("spec must be a SpecialtyProgramSpec")
    return SpecialtyBenchmarkPlan(spec=spec, cells=_allocate_cells(spec))


def _allocate_cells(
    spec: SpecialtyProgramSpec,
) -> tuple[SubBenchmarkCell, ...]:
    specialties = spec.clinical_scope.specialties
    relationships = spec.clinical_scope.reference_relationships
    stress_modes = spec.clinical_scope.stress_modes
    selections = {
        selection.specialty: selection
        for selection in spec.clinical_scope.condition_selections
    }
    representative_target, stress_target = _target_counts(spec)

    representative_priority = _grid_priority_order(
        len(specialties),
        len(relationships),
    )
    representative_weights = tuple(
        _cell_sampling_weight(
            selections[specialties[specialty_index]],
            spec.clinical_scope.sampling.frame,
        )
        for specialty_index, _ in representative_priority
    )
    representative_counts = _allocate_grid_counts(
        representative_target,
        representative_weights,
        coverage_count=max(len(specialties), len(relationships)),
    )
    representative_by_pair = dict(zip(representative_priority, representative_counts))

    stress_priority = _grid_priority_order(len(specialties), len(stress_modes))
    stress_weights = tuple(
        _cell_sampling_weight(
            selections[specialties[specialty_index]],
            spec.clinical_scope.sampling.frame,
        )
        for specialty_index, _ in stress_priority
    )
    stress_counts = _allocate_grid_counts(
        stress_target,
        stress_weights,
        coverage_count=max(len(specialties), len(stress_modes)),
    )
    stress_by_pair = dict(zip(stress_priority, stress_counts))

    representative_pairs = {
        (specialty_index, relationship_index)
        for specialty_index in range(len(specialties))
        for relationship_index in range(len(relationships))
    }
    if set(representative_by_pair) != representative_pairs:
        raise ValueError("representative allocation grid is incomplete")

    cells: list[SubBenchmarkCell] = []
    representative_acuity_tie_start = 0
    for specialty_index, specialty in enumerate(specialties):
        selection = selections[specialty]
        for relationship_index, relationship in enumerate(relationships):
            family_count = representative_by_pair[(specialty_index, relationship_index)]
            if family_count:
                cells.append(
                    _make_cell(
                        spec,
                        specialty=specialty,
                        track=BenchmarkTrack.REPRESENTATIVE,
                        selection=selection,
                        family_count=family_count,
                        condition_offset=(
                            specialty_index * len(relationships) + relationship_index
                        ),
                        acuity_tie_start=representative_acuity_tie_start,
                        reference_relationship=relationship,
                    )
                )
                representative_acuity_tie_start = (
                    representative_acuity_tie_start + family_count
                ) % len(CANONICAL_ACUITY_LEVELS)
    stress_acuity_tie_start = 0
    for specialty_index, specialty in enumerate(specialties):
        selection = selections[specialty]
        for mode_index, mode in enumerate(stress_modes):
            family_count = stress_by_pair[(specialty_index, mode_index)]
            if family_count:
                cells.append(
                    _make_cell(
                        spec,
                        specialty=specialty,
                        track=BenchmarkTrack.STRESS,
                        selection=selection,
                        family_count=family_count,
                        condition_offset=(
                            specialty_index * len(stress_modes) + mode_index
                        ),
                        acuity_tie_start=stress_acuity_tie_start,
                        stress_mode=mode,
                    )
                )
                stress_acuity_tie_start = (
                    stress_acuity_tie_start + family_count
                ) % len(CANONICAL_ACUITY_LEVELS)
    return tuple(cells)


def _make_cell(
    spec: SpecialtyProgramSpec,
    *,
    specialty: Specialty,
    track: BenchmarkTrack,
    selection: ConditionSelection,
    family_count: int,
    condition_offset: int,
    acuity_tie_start: int,
    reference_relationship: ReferenceRelationship | None = None,
    stress_mode: StressMode | None = None,
) -> SubBenchmarkCell:
    counts = _largest_remainder_counts(
        family_count,
        _condition_sampling_weights(
            selection,
            spec.clinical_scope.sampling.frame,
        ),
        tie_start=condition_offset,
    )
    allocations = tuple(
        ConditionAllocation(condition_family=condition, family_count=count)
        for condition, count in zip(selection.conditions, counts)
        if count
    )
    acuity_counts = _largest_remainder_counts(
        family_count,
        (1.0,) * len(CANONICAL_ACUITY_LEVELS),
        tie_start=acuity_tie_start,
    )
    acuity_allocations = tuple(
        AcuityAllocation(acuity=acuity, family_count=count)
        for acuity, count in zip(CANONICAL_ACUITY_LEVELS, acuity_counts)
    )
    return SubBenchmarkCell(
        specialty=specialty,
        track=track,
        reference_relationship=reference_relationship,
        stress_mode=stress_mode,
        condition_allocations=allocations,
        acuity_allocations=acuity_allocations,
        variants_per_family=spec.variants_per_family,
        model_repetitions=spec.model_repetitions,
        model_count=len(spec.model_ids),
    )


def _target_counts(spec: SpecialtyProgramSpec) -> tuple[int, int]:
    if spec.representative_family_target is None or spec.stress_family_target is None:
        raise ValueError("program family targets must be resolved")
    return spec.representative_family_target, spec.stress_family_target


def _resolve_family_targets(
    scale: ProgramScale,
    scope: ClinicalScope,
    representative_target: int | None,
    stress_target: int | None,
) -> tuple[int, int]:
    if scale is ProgramScale.DEFAULT_PILOT:
        expected = (DEFAULT_REPRESENTATIVE_FAMILIES, DEFAULT_STRESS_FAMILIES)
        supplied = (representative_target, stress_target)
        if supplied not in ((None, None), expected):
            raise ValueError(
                "default-pilot family targets must be exactly 108 representative "
                "and 36 stress families"
            )
        return expected

    if scale is ProgramScale.SMOKE:
        specialty_count = len(scope.specialties)
        expected = (
            specialty_count * len(REFERENCE_RELATIONSHIPS),
            max(specialty_count, len(scope.stress_modes)),
        )
        supplied = (representative_target, stress_target)
        if supplied not in ((None, None), expected):
            raise ValueError("smoke family targets are derived from the clinical scope")
        return expected

    if representative_target is None or stress_target is None:
        raise ValueError(
            f"{scale.value} scale requires explicit representative and stress "
            "family targets"
        )
    _require_positive_int(
        representative_target,
        "representative_family_target",
    )
    _require_positive_int(stress_target, "stress_family_target")
    if scale in SCALE_FAMILY_TARGET_RANGES:
        representative_range, stress_range = SCALE_FAMILY_TARGET_RANGES[scale]
        if (
            not representative_range[0]
            <= representative_target
            <= representative_range[1]
        ):
            raise ValueError(
                f"{scale.value} representative_family_target must be between "
                f"{representative_range[0]} and {representative_range[1]}"
            )
        if not stress_range[0] <= stress_target <= stress_range[1]:
            raise ValueError(
                f"{scale.value} stress_family_target must be between "
                f"{stress_range[0]} and {stress_range[1]}"
            )
    return representative_target, stress_target


def _condition_sampling_weights(
    selection: ConditionSelection,
    frame: SamplingFrame,
) -> tuple[float, float]:
    if frame is SamplingFrame.EQUAL_SPECIALTY:
        return (1.0, 1.0)
    if frame is SamplingFrame.HARM_WEIGHTED:
        return selection.harm_weights
    return selection.prevalence_weights


def _cell_sampling_weight(
    selection: ConditionSelection,
    frame: SamplingFrame,
) -> float:
    if frame in (SamplingFrame.EQUAL_SPECIALTY, SamplingFrame.HYBRID):
        return 1.0
    return sum(_condition_sampling_weights(selection, frame))


def _allocate_grid_counts(
    total: int,
    weights: Sequence[float],
    *,
    coverage_count: int,
) -> tuple[int, ...]:
    """Allocate a grid total while retaining deterministic minimum coverage."""
    _require_positive_int(total, "allocation total")
    if not weights:
        raise ValueError("allocation weights must not be empty")
    if not 1 <= coverage_count <= len(weights):
        raise ValueError("coverage_count must fit inside the allocation grid")

    counts = [0] * len(weights)
    if total >= len(weights):
        counts = [1] * len(weights)
        remaining = total - len(weights)
        candidate_indices = tuple(range(len(weights)))
    else:
        seeded = min(total, coverage_count)
        for index in range(seeded):
            counts[index] = 1
        remaining = total - seeded
        candidate_indices = tuple(
            index for index, count in enumerate(counts) if count == 0
        )

    if remaining:
        increments = _largest_remainder_counts(
            remaining,
            tuple(weights[index] for index in candidate_indices),
        )
        for index, increment in zip(candidate_indices, increments):
            counts[index] += increment
    return tuple(counts)


def _largest_remainder_counts(
    total: int,
    weights: Sequence[float],
    *,
    tie_start: int = 0,
) -> tuple[int, ...]:
    """Use exact decimal ratios and a rotating, deterministic tie break."""
    _require_positive_int(total, "allocation total")
    if not weights:
        raise ValueError("allocation weights must not be empty")
    normalized = tuple(
        _require_positive_finite_number(weight, "allocation weight")
        for weight in weights
    )
    exact_weights = tuple(Fraction(str(weight)) for weight in normalized)
    weight_total = sum(exact_weights, Fraction(0, 1))
    quotas = tuple(
        Fraction(total, 1) * weight / weight_total for weight in exact_weights
    )
    counts = [quota.numerator // quota.denominator for quota in quotas]
    remaining = total - sum(counts)
    start = tie_start % len(weights)
    tie_rank = {index: (index - start) % len(weights) for index in range(len(weights))}
    ranked = sorted(
        range(len(weights)),
        key=lambda index: (
            -(quotas[index] - counts[index]),
            tie_rank[index],
        ),
    )
    for index in ranked[:remaining]:
        counts[index] += 1
    return tuple(counts)


def _grid_priority_order(
    first_dimension_count: int,
    second_dimension_count: int,
) -> tuple[tuple[int, int], ...]:
    """Cover both dimensions before adding the remaining Cartesian cells."""
    pairs: list[tuple[int, int]] = []
    if first_dimension_count <= second_dimension_count:
        pairs.extend(
            (second_index % first_dimension_count, second_index)
            for second_index in range(second_dimension_count)
        )
    else:
        pairs.extend(
            (first_index, first_index % second_dimension_count)
            for first_index in range(first_dimension_count)
        )
    seen = set(pairs)
    for first_index in range(first_dimension_count):
        for second_index in range(second_dimension_count):
            pair = (first_index, second_index)
            if pair not in seen:
                seen.add(pair)
                pairs.append(pair)
    return tuple(pairs)


def _normalized_label(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    text = value.strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[/_]+", "-", text)
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


def _canonical_json(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def _bound_digest(schema_version: str, payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        _canonical_json({"schema_version": schema_version, **payload})
    ).hexdigest()


def _bound_dict(
    schema_version: str,
    payload: Mapping[str, Any],
    digest_field: str,
) -> dict[str, Any]:
    result = {"schema_version": schema_version, **payload}
    result[digest_field] = _bound_digest(schema_version, payload)
    return result


def _require_fields(data: Mapping[str, Any], expected: set[str], name: str) -> None:
    if not isinstance(data, Mapping):
        raise ValueError(f"{name} must be an object")
    actual = set(data)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"{name} fields do not match schema; missing={missing}, extra={extra}"
        )


def _require_version(value: Any, expected: str, name: str) -> None:
    if value != expected:
        raise ValueError(f"unsupported {name} schema version: {value!r}")


def _require_text(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_text_value(value: Any, name: str) -> str:
    _require_text(value, name)
    return value


def _require_optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _require_text_value(value, name)


def _verify_hash_field(value: Any, expected: str, name: str) -> None:
    _require_hash(value, f"{name} hash")
    if value != expected:
        raise ValueError(f"{name} hash does not match its contents")


def _require_bool(value: Any, name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")


def _require_bool_value(value: Any, name: str) -> bool:
    _require_bool(value, name)
    return value


def _require_positive_int(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_nonnegative_int(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def _require_int_value(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _require_positive_finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return normalized


def _require_unique_text_tuple(values: Sequence[Any], name: str) -> None:
    if not values:
        raise ValueError(f"{name} must not be empty")
    for value in values:
        _require_text(value, name)
    if len(values) != len(set(values)):
        raise ValueError(f"{name} values must be unique")


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _require_mapping_list(value: Any, name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return tuple(_require_mapping(item, name) for item in value)


def _require_text_list(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    result = tuple(_require_text_value(item, name) for item in value)
    return result
