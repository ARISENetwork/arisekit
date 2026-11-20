"""Frozen study-design choices for specialty benchmark programs.

This module records decisions that clinical, statistical, and operational
owners must supply. It does not choose margins, sample sizes, endpoints,
physicians, or approval identities. The resulting digest can be bound into a
``SpecialtyProgramSpec`` and its later real-versus-synthetic comparison.
Physician allocation protocols and seeds are preregistered in the design;
realized family and assignment manifests are created afterward and bind both
the design and materialized specialty plan.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from arisekit.common.jsonio import strict_json_object
from arisekit.common.records import CanonicalPropertyRecord
from arisekit.common.validate import (
    enum_member,
    exact_fields as _fields,
    identifier,
    number,
    positive_int,
    sha256_hex,
    text,
)
from arisekit.authoring.specialty import (
    BenchmarkTrack,
    ReferenceRelationship,
    SpecialtyBenchmarkPlan,
)


SCHEMA_VERSION = "arisekit.specialty-study-design.v2"
PHYSICIAN_FAMILY_MANIFEST_SCHEMA_VERSION = "arisekit.physician-family-manifest.v3"
PHYSICIAN_ASSIGNMENT_MANIFEST_SCHEMA_VERSION = (
    "arisekit.physician-assignment-manifest.v1"
)
_ID_RE = re.compile(r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$")


class PhysicianInclusionStrategy(str, Enum):
    MODEL_ONLY_FEASIBILITY = "model-only-feasibility"
    CLINICIAN_EVALUATION_ONLY = "clinician-evaluation-only"
    DESCRIPTIVE_BASELINE = "descriptive-physician-baseline"
    FULL_HEAD_TO_HEAD = "full-head-to-head"
    ASSISTED_UNASSISTED_CROSSOVER = "assisted-unassisted-crossover"


class EndpointKind(str, Enum):
    ABSOLUTE_PERFORMANCE = "absolute-performance"
    PAIRED_RELATIONSHIP = "paired-relationship"
    SAFETY_GUARDRAIL = "safety-guardrail"
    SUBGROUP = "subgroup"
    MODEL_MINUS_PHYSICIAN = "model-minus-physician"


class MarginUnit(str, Enum):
    RATE_DIFFERENCE = "rate-difference"
    STANDARD_DEVIATIONS = "standard-deviations"
    ABSOLUTE_SCORE = "absolute-score"
    SAFETY_RATE = "safety-rate"


class SampleSizeTier(str, Enum):
    FEASIBILITY = "feasibility"
    DESCRIPTIVE_PILOT = "descriptive-pilot"
    COMPARATIVE_STUDY = "comparative-study"
    ILLUSTRATIVE_PILOT_DEFAULT = "illustrative-pilot-default"
    CUSTOM = "custom"


class MultiplicityMethod(str, Enum):
    DESCRIPTIVE_CI_ONLY = "descriptive-confidence-intervals-only"
    ONE_PRIMARY_NO_ADJUSTMENT = "one-primary-no-adjustment"
    BONFERRONI = "bonferroni"
    HOLM = "holm"
    FIXED_SEQUENCE = "fixed-sequence"
    HIERARCHICAL = "hierarchical"
    FALSE_DISCOVERY_RATE = "false-discovery-rate"


@dataclass(frozen=True, slots=True)
class EvaluationConditionMatch:
    """Whether physician and model evaluation conditions are comparable."""

    specialty_matched: bool
    time_matched: bool
    interface_matched: bool
    tools_matched: bool
    retrieval_matched: bool
    assistance_matched: bool
    notes: str

    def __post_init__(self) -> None:
        for name in (
            "specialty_matched",
            "time_matched",
            "interface_matched",
            "tools_matched",
            "retrieval_matched",
            "assistance_matched",
        ):
            _boolean(name, getattr(self, name))
        _text("evaluation condition notes", self.notes)

    @property
    def all_matched(self) -> bool:
        return all(
            (
                self.specialty_matched,
                self.time_matched,
                self.interface_matched,
                self.tools_matched,
                self.retrieval_matched,
                self.assistance_matched,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "specialty_matched": self.specialty_matched,
            "time_matched": self.time_matched,
            "interface_matched": self.interface_matched,
            "tools_matched": self.tools_matched,
            "retrieval_matched": self.retrieval_matched,
            "assistance_matched": self.assistance_matched,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvaluationConditionMatch":
        fields = {
            "specialty_matched",
            "time_matched",
            "interface_matched",
            "tools_matched",
            "retrieval_matched",
            "assistance_matched",
            "notes",
        }
        _fields(data, fields, "evaluation condition match")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True, slots=True)
class PhysicianPlan:
    """Preregistered physician allocation and assignment contract."""

    strategy: PhysicianInclusionStrategy | str
    rationale: str
    target_physicians: int | None
    representative_family_count: int | None
    responses_per_variant: int | None
    family_allocation_protocol_hash: str | None
    family_allocation_seed_hash: str | None
    assignment_protocol_hash: str | None
    assignment_seed_hash: str | None
    prohibits_companion_variant_exposure: bool
    evaluation_conditions: EvaluationConditionMatch
    pilot_default: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "strategy",
            _enum(
                PhysicianInclusionStrategy,
                self.strategy,
                "physician inclusion strategy",
            ),
        )
        _text("physician plan rationale", self.rationale)
        _boolean(
            "prohibits_companion_variant_exposure",
            self.prohibits_companion_variant_exposure,
        )
        _boolean("pilot_default", self.pilot_default)
        if not isinstance(self.evaluation_conditions, EvaluationConditionMatch):
            raise ValueError("evaluation_conditions must be EvaluationConditionMatch")

        answering = {
            PhysicianInclusionStrategy.DESCRIPTIVE_BASELINE,
            PhysicianInclusionStrategy.FULL_HEAD_TO_HEAD,
            PhysicianInclusionStrategy.ASSISTED_UNASSISTED_CROSSOVER,
        }
        if self.strategy is PhysicianInclusionStrategy.MODEL_ONLY_FEASIBILITY:
            optional = (
                self.target_physicians,
                self.representative_family_count,
                self.responses_per_variant,
                self.family_allocation_protocol_hash,
                self.family_allocation_seed_hash,
                self.assignment_protocol_hash,
                self.assignment_seed_hash,
            )
            if any(value is not None for value in optional):
                raise ValueError(
                    "model-only feasibility cannot declare physician assignments"
                )
            if self.pilot_default:
                raise ValueError(
                    "the supplied physician pilot default is a descriptive baseline"
                )
            return

        _positive_int("target_physicians", self.target_physicians)
        if self.strategy is PhysicianInclusionStrategy.CLINICIAN_EVALUATION_ONLY:
            if any(
                value is not None
                for value in (
                    self.representative_family_count,
                    self.responses_per_variant,
                    self.family_allocation_protocol_hash,
                    self.family_allocation_seed_hash,
                    self.assignment_protocol_hash,
                    self.assignment_seed_hash,
                )
            ):
                raise ValueError(
                    "clinician-evaluation-only reviewers do not answer case variants"
                )
            if self.pilot_default:
                raise ValueError(
                    "the supplied physician pilot default is a descriptive baseline"
                )
            return

        if self.strategy not in answering:
            raise ValueError("unsupported physician inclusion strategy")
        _positive_int("representative_family_count", self.representative_family_count)
        _positive_int("responses_per_variant", self.responses_per_variant)
        for name in (
            "family_allocation_protocol_hash",
            "family_allocation_seed_hash",
            "assignment_protocol_hash",
            "assignment_seed_hash",
        ):
            _hash(name, getattr(self, name))
        if not self.prohibits_companion_variant_exposure:
            raise ValueError(
                "a physician answerer must not see both variants of one family"
            )
        if (
            self.strategy is PhysicianInclusionStrategy.FULL_HEAD_TO_HEAD
            and not self.evaluation_conditions.all_matched
        ):
            raise ValueError(
                "full head-to-head comparison requires all evaluation conditions "
                "to be matched"
            )
        if self.pilot_default:
            if self.strategy is not PhysicianInclusionStrategy.DESCRIPTIVE_BASELINE:
                raise ValueError(
                    "the supplied pilot default must use a descriptive baseline"
                )
            if not 12 <= self.target_physicians <= 20:
                raise ValueError(
                    "pilot-default target_physicians must be between 12 and 20"
                )
            if not 40 <= self.representative_family_count <= 50:
                raise ValueError(
                    "pilot-default representative family count must be 40 to 50"
                )
            if self.responses_per_variant not in (2, 3):
                raise ValueError(
                    "pilot-default responses per variant must be two or three"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "rationale": self.rationale,
            "target_physicians": self.target_physicians,
            "representative_family_count": self.representative_family_count,
            "responses_per_variant": self.responses_per_variant,
            "family_allocation_protocol_hash": (self.family_allocation_protocol_hash),
            "family_allocation_seed_hash": self.family_allocation_seed_hash,
            "assignment_protocol_hash": self.assignment_protocol_hash,
            "assignment_seed_hash": self.assignment_seed_hash,
            "prohibits_companion_variant_exposure": (
                self.prohibits_companion_variant_exposure
            ),
            "evaluation_conditions": self.evaluation_conditions.to_dict(),
            "pilot_default": self.pilot_default,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PhysicianPlan":
        fields = {
            "strategy",
            "rationale",
            "target_physicians",
            "representative_family_count",
            "responses_per_variant",
            "family_allocation_protocol_hash",
            "family_allocation_seed_hash",
            "assignment_protocol_hash",
            "assignment_seed_hash",
            "prohibits_companion_variant_exposure",
            "evaluation_conditions",
            "pilot_default",
        }
        _fields(data, fields, "physician plan")
        return cls(
            strategy=data["strategy"],
            rationale=data["rationale"],
            target_physicians=data["target_physicians"],
            representative_family_count=data["representative_family_count"],
            responses_per_variant=data["responses_per_variant"],
            family_allocation_protocol_hash=data["family_allocation_protocol_hash"],
            family_allocation_seed_hash=data["family_allocation_seed_hash"],
            assignment_protocol_hash=data["assignment_protocol_hash"],
            assignment_seed_hash=data["assignment_seed_hash"],
            prohibits_companion_variant_exposure=data[
                "prohibits_companion_variant_exposure"
            ],
            evaluation_conditions=EvaluationConditionMatch.from_dict(
                data["evaluation_conditions"]
            ),
            pilot_default=data["pilot_default"],
        )


@dataclass(frozen=True, slots=True)
class PhysicianAssignment:
    """One physician response assignment for one family variant."""

    physician_id: str
    case_family_id: str
    variant_id: str

    def __post_init__(self) -> None:
        for name in ("physician_id", "case_family_id", "variant_id"):
            _identifier(name, getattr(self, name))

    def to_dict(self) -> dict[str, str]:
        return {
            "physician_id": self.physician_id,
            "case_family_id": self.case_family_id,
            "variant_id": self.variant_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PhysicianAssignment":
        fields = {"physician_id", "case_family_id", "variant_id"}
        _fields(data, fields, "physician assignment")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True, slots=True)
class PhysicianFamily:
    """One authoritative paired family available to physician raters."""

    case_family_id: str
    plan_cell_id: str
    variant_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier("case_family_id", self.case_family_id)
        _identifier("plan_cell_id", self.plan_cell_id)
        variants = _identifier_tuple("variant_ids", self.variant_ids)
        if len(variants) < 2:
            raise ValueError(
                "physician family must identify at least two companion variants"
            )
        object.__setattr__(self, "variant_ids", tuple(sorted(variants)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_family_id": self.case_family_id,
            "plan_cell_id": self.plan_cell_id,
            "variant_ids": list(self.variant_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PhysicianFamily":
        fields = {"case_family_id", "plan_cell_id", "variant_ids"}
        _fields(data, fields, "physician family")
        return cls(
            case_family_id=data["case_family_id"],
            plan_cell_id=data["plan_cell_id"],
            variant_ids=data["variant_ids"],
        )


@dataclass(frozen=True, slots=True)
class PhysicianFamilyManifest(CanonicalPropertyRecord):
    """Realized representative families bound after the design is frozen."""

    study_design_sha256: str
    plan_sha256: str
    archetype_id: str
    track: BenchmarkTrack | str
    families: tuple[PhysicianFamily, ...]
    schema_version: str = PHYSICIAN_FAMILY_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PHYSICIAN_FAMILY_MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                "unsupported physician family manifest schema "
                f"{self.schema_version!r}"
            )
        _hash("study_design_sha256", self.study_design_sha256)
        _hash("plan_sha256", self.plan_sha256)
        _identifier("archetype_id", self.archetype_id)
        if self.archetype_id not in {"noharm", "paired-specialty-equity"}:
            raise ValueError(
                "physician family archetype must be noharm or "
                "paired-specialty-equity"
            )
        object.__setattr__(
            self,
            "track",
            _enum(BenchmarkTrack, self.track, "physician family track"),
        )
        if self.track is not BenchmarkTrack.REPRESENTATIVE:
            raise ValueError(
                "physician family manifest must use the representative track"
            )
        families = tuple(self.families)
        if not families or not all(
            isinstance(family, PhysicianFamily) for family in families
        ):
            raise ValueError(
                "physician family manifest must contain PhysicianFamily records"
            )
        if len({family.case_family_id for family in families}) != len(families):
            raise ValueError("physician family IDs must be unique")
        expected_variants = 5 if self.archetype_id == "noharm" else 2
        if any(len(family.variant_ids) != expected_variants for family in families):
            raise ValueError(
                f"{self.archetype_id} physician families require exactly "
                f"{expected_variants} evaluated variants"
            )
        variant_ids = [
            variant_id for family in families for variant_id in family.variant_ids
        ]
        if len(set(variant_ids)) != len(variant_ids):
            raise ValueError("physician family variant IDs must be globally unique")
        object.__setattr__(
            self,
            "families",
            tuple(sorted(families, key=lambda family: family.case_family_id)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "study_design_sha256": self.study_design_sha256,
            "plan_sha256": self.plan_sha256,
            "archetype_id": self.archetype_id,
            "track": self.track.value,
            "families": [family.to_dict() for family in self.families],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PhysicianFamilyManifest":
        fields = {
            "schema_version",
            "study_design_sha256",
            "plan_sha256",
            "archetype_id",
            "track",
            "families",
        }
        _fields(data, fields, "physician family manifest")
        return cls(
            schema_version=data["schema_version"],
            study_design_sha256=data["study_design_sha256"],
            plan_sha256=data["plan_sha256"],
            archetype_id=data["archetype_id"],
            track=data["track"],
            families=tuple(
                PhysicianFamily.from_dict(value) for value in data["families"]
            ),
        )

    @classmethod
    def from_json(cls, payload: str) -> "PhysicianFamilyManifest":
        return cls.from_dict(strict_json_object(payload, "physician family manifest"))

    def validate_against(
        self,
        study_design: "SpecialtyStudyDesign",
        specialty_plan: SpecialtyBenchmarkPlan,
    ) -> None:
        """Verify both preregistered artifacts before accepting this subset."""

        if not isinstance(study_design, SpecialtyStudyDesign):
            raise ValueError("study_design must be a SpecialtyStudyDesign")
        if not isinstance(specialty_plan, SpecialtyBenchmarkPlan):
            raise ValueError("specialty_plan must be a SpecialtyBenchmarkPlan")
        study_design.validate_against_plan(specialty_plan)
        if self.study_design_sha256 != study_design.digest:
            raise ValueError("physician family manifest does not bind the study design")
        if self.plan_sha256 != specialty_plan.plan_sha256:
            raise ValueError(
                "physician family manifest does not bind the specialty plan"
            )
        if self.archetype_id != specialty_plan.spec.archetype.value:
            raise ValueError(
                "physician family manifest archetype does not match the "
                "specialty plan"
            )
        cells = {
            cell.cell_id: cell
            for cell in specialty_plan.cells
            if cell.track is BenchmarkTrack.REPRESENTATIVE
        }
        per_cell: dict[str, int] = {}
        for family in self.families:
            if family.plan_cell_id not in cells:
                raise ValueError(
                    "physician family references a non-representative plan cell"
                )
            per_cell[family.plan_cell_id] = per_cell.get(family.plan_cell_id, 0) + 1
        for cell_id, family_count in per_cell.items():
            if family_count > cells[cell_id].family_count:
                raise ValueError(
                    "physician family manifest exceeds a plan cell family count"
                )


@dataclass(frozen=True, slots=True)
class PhysicianAssignmentManifest(CanonicalPropertyRecord):
    """Realized assignments bound after design and family materialization."""

    study_design_sha256: str
    plan_sha256: str
    family_subset_manifest_hash: str
    responses_per_variant: int
    assignments: tuple[PhysicianAssignment, ...]
    schema_version: str = PHYSICIAN_ASSIGNMENT_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PHYSICIAN_ASSIGNMENT_MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                "unsupported physician assignment manifest schema "
                f"{self.schema_version!r}"
            )
        _hash("study_design_sha256", self.study_design_sha256)
        _hash("plan_sha256", self.plan_sha256)
        _hash("family_subset_manifest_hash", self.family_subset_manifest_hash)
        _positive_int("responses_per_variant", self.responses_per_variant)
        assignments = tuple(self.assignments)
        if not assignments or not all(
            isinstance(value, PhysicianAssignment) for value in assignments
        ):
            raise ValueError("assignments must contain PhysicianAssignment records")
        identities = {
            (value.physician_id, value.case_family_id, value.variant_id)
            for value in assignments
        }
        if len(identities) != len(assignments):
            raise ValueError("physician assignments must be unique")
        physician_families = {
            (value.physician_id, value.case_family_id) for value in assignments
        }
        if len(physician_families) != len(assignments):
            raise ValueError(
                "one physician cannot see both variants of the same family"
            )
        by_family_variant: dict[tuple[str, str], int] = {}
        family_variants: dict[str, set[str]] = {}
        for value in assignments:
            key = (value.case_family_id, value.variant_id)
            by_family_variant[key] = by_family_variant.get(key, 0) + 1
            family_variants.setdefault(value.case_family_id, set()).add(
                value.variant_id
            )
        if any(len(variants) < 2 for variants in family_variants.values()):
            raise ValueError(
                "each physician family must contain at least two assigned variants"
            )
        if any(
            count != self.responses_per_variant for count in by_family_variant.values()
        ):
            raise ValueError(
                "every variant must receive the frozen number of physician responses"
            )
        object.__setattr__(
            self,
            "assignments",
            tuple(
                sorted(
                    assignments,
                    key=lambda value: (
                        value.case_family_id,
                        value.variant_id,
                        value.physician_id,
                    ),
                )
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "study_design_sha256": self.study_design_sha256,
            "plan_sha256": self.plan_sha256,
            "family_subset_manifest_hash": self.family_subset_manifest_hash,
            "responses_per_variant": self.responses_per_variant,
            "assignments": [value.to_dict() for value in self.assignments],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PhysicianAssignmentManifest":
        fields = {
            "schema_version",
            "study_design_sha256",
            "plan_sha256",
            "family_subset_manifest_hash",
            "responses_per_variant",
            "assignments",
        }
        _fields(data, fields, "physician assignment manifest")
        return cls(
            schema_version=data["schema_version"],
            study_design_sha256=data["study_design_sha256"],
            plan_sha256=data["plan_sha256"],
            family_subset_manifest_hash=data["family_subset_manifest_hash"],
            responses_per_variant=data["responses_per_variant"],
            assignments=tuple(
                PhysicianAssignment.from_dict(value) for value in data["assignments"]
            ),
        )

    @classmethod
    def from_json(cls, payload: str) -> "PhysicianAssignmentManifest":
        return cls.from_dict(
            strict_json_object(payload, "physician assignment manifest")
        )

    @property
    def family_count(self) -> int:
        return len({value.case_family_id for value in self.assignments})

    def validate_against(
        self,
        study_design: "SpecialtyStudyDesign",
        *,
        family_manifest: PhysicianFamilyManifest,
        specialty_plan: SpecialtyBenchmarkPlan,
    ) -> None:
        if not isinstance(study_design, SpecialtyStudyDesign):
            raise ValueError("study_design must be a SpecialtyStudyDesign")
        if not isinstance(family_manifest, PhysicianFamilyManifest):
            raise ValueError("family_manifest must be PhysicianFamilyManifest")
        family_manifest.validate_against(study_design, specialty_plan)
        if self.study_design_sha256 != study_design.digest:
            raise ValueError(
                "physician assignment manifest does not bind the study design"
            )
        if self.plan_sha256 != specialty_plan.plan_sha256:
            raise ValueError(
                "physician assignment manifest does not bind the specialty plan"
            )
        if self.family_subset_manifest_hash != family_manifest.digest:
            raise ValueError(
                "physician assignment manifest does not bind the family manifest"
            )
        plan = study_design.physician_plan
        if plan.responses_per_variant != self.responses_per_variant:
            raise ValueError("physician response targets differ")
        if plan.representative_family_count != self.family_count:
            raise ValueError("physician family target differs from assignments")
        physician_count = len({value.physician_id for value in self.assignments})
        if plan.target_physicians != physician_count:
            raise ValueError("physician target differs from assignment roster")
        expected = {
            (family.case_family_id, variant_id)
            for family in family_manifest.families
            for variant_id in family.variant_ids
        }
        observed = {
            (assignment.case_family_id, assignment.variant_id)
            for assignment in self.assignments
        }
        if observed != expected:
            raise ValueError(
                "physician assignments do not match the authoritative companion "
                "variant manifest"
            )


@dataclass(frozen=True, slots=True)
class DecisionMargin:
    value: float
    unit: MarginUnit | str
    justification: str
    clinical_approval_hash: str
    statistical_approval_hash: str

    def __post_init__(self) -> None:
        value = _finite("decision margin value", self.value)
        if value <= 0:
            raise ValueError("decision margin value must be positive")
        object.__setattr__(
            self, "unit", _enum(MarginUnit, self.unit, "decision margin unit")
        )
        if self.unit in {MarginUnit.RATE_DIFFERENCE, MarginUnit.SAFETY_RATE}:
            if value > 1:
                raise ValueError(
                    f"{self.unit.value} margin must be no greater than one"
                )
        object.__setattr__(self, "value", value)
        _text("decision margin justification", self.justification)
        _hash("clinical_approval_hash", self.clinical_approval_hash)
        _hash("statistical_approval_hash", self.statistical_approval_hash)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit.value,
            "justification": self.justification,
            "clinical_approval_hash": self.clinical_approval_hash,
            "statistical_approval_hash": self.statistical_approval_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecisionMargin":
        fields = {
            "value",
            "unit",
            "justification",
            "clinical_approval_hash",
            "statistical_approval_hash",
        }
        _fields(data, fields, "decision margin")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True, slots=True)
class EndpointSpec:
    endpoint_id: str
    kind: EndpointKind | str
    metric: str
    estimand: str
    primary: bool
    relationship: ReferenceRelationship | str | None = None
    margin: DecisionMargin | None = None
    reports_each_variant: bool = False
    adjudicates_every_severe_error: bool = False

    def __post_init__(self) -> None:
        _identifier("endpoint_id", self.endpoint_id)
        object.__setattr__(
            self, "kind", _enum(EndpointKind, self.kind, "endpoint kind")
        )
        _text("endpoint metric", self.metric)
        _text("endpoint estimand", self.estimand)
        _boolean("endpoint primary", self.primary)
        _boolean("reports_each_variant", self.reports_each_variant)
        _boolean(
            "adjudicates_every_severe_error",
            self.adjudicates_every_severe_error,
        )
        if self.relationship is not None:
            object.__setattr__(
                self,
                "relationship",
                _enum(
                    ReferenceRelationship,
                    self.relationship,
                    "endpoint relationship",
                ),
            )
        if self.kind is EndpointKind.PAIRED_RELATIONSHIP:
            if self.relationship is None:
                raise ValueError("paired relationship endpoint requires a relationship")
        elif self.relationship is not None:
            raise ValueError(
                "only paired relationship endpoints may declare a relationship"
            )
        if self.margin is not None and not isinstance(self.margin, DecisionMargin):
            raise ValueError("endpoint margin must be DecisionMargin or null")
        if (
            self.kind is EndpointKind.ABSOLUTE_PERFORMANCE
            and not self.reports_each_variant
        ):
            raise ValueError(
                "absolute performance must be reported separately for each variant"
            )
        if (
            self.kind is EndpointKind.SAFETY_GUARDRAIL
            and not self.adjudicates_every_severe_error
        ):
            raise ValueError("every severe-error event must trigger adjudication")
        if self.kind is not EndpointKind.SAFETY_GUARDRAIL:
            if self.adjudicates_every_severe_error:
                raise ValueError(
                    "severe-error adjudication belongs to a safety guardrail"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint_id": self.endpoint_id,
            "kind": self.kind.value,
            "metric": self.metric,
            "estimand": self.estimand,
            "primary": self.primary,
            "relationship": (
                self.relationship.value if self.relationship is not None else None
            ),
            "margin": self.margin.to_dict() if self.margin is not None else None,
            "reports_each_variant": self.reports_each_variant,
            "adjudicates_every_severe_error": (self.adjudicates_every_severe_error),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EndpointSpec":
        fields = {
            "endpoint_id",
            "kind",
            "metric",
            "estimand",
            "primary",
            "relationship",
            "margin",
            "reports_each_variant",
            "adjudicates_every_severe_error",
        }
        _fields(data, fields, "endpoint specification")
        return cls(
            endpoint_id=data["endpoint_id"],
            kind=data["kind"],
            metric=data["metric"],
            estimand=data["estimand"],
            primary=data["primary"],
            relationship=data["relationship"],
            margin=(
                DecisionMargin.from_dict(data["margin"])
                if data["margin"] is not None
                else None
            ),
            reports_each_variant=data["reports_each_variant"],
            adjudicates_every_severe_error=data["adjudicates_every_severe_error"],
        )


@dataclass(frozen=True, slots=True)
class SampleSizeDesign:
    tier: SampleSizeTier | str
    representative_families: int
    stress_families: int
    model_repetitions_per_variant: int
    simulation_artifact_hash: str
    assumption_manifest_hash: str
    independent_analysis_unit: str = "case-family"
    repetitions_replace_families: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "tier", _enum(SampleSizeTier, self.tier, "sample size tier")
        )
        _positive_int("representative_families", self.representative_families)
        _positive_int("stress_families", self.stress_families)
        _positive_int(
            "model_repetitions_per_variant",
            self.model_repetitions_per_variant,
        )
        if (
            self.model_repetitions_per_variant not in (1, 3)
            and self.model_repetitions_per_variant < 5
        ):
            raise ValueError("model repetitions must be one, three, or at least five")
        _hash("simulation_artifact_hash", self.simulation_artifact_hash)
        _hash("assumption_manifest_hash", self.assumption_manifest_hash)
        if self.independent_analysis_unit != "case-family":
            raise ValueError("the independent analysis unit must be case-family")
        _boolean("repetitions_replace_families", self.repetitions_replace_families)
        if self.repetitions_replace_families:
            raise ValueError(
                "model repetitions do not replace independent case families"
            )
        ranges = {
            SampleSizeTier.FEASIBILITY: ((30, 48), (18, 24)),
            SampleSizeTier.DESCRIPTIVE_PILOT: ((96, 120), (30, 48)),
            SampleSizeTier.COMPARATIVE_STUDY: ((300, 500), (60, 100)),
            SampleSizeTier.ILLUSTRATIVE_PILOT_DEFAULT: ((108, 108), (36, 36)),
        }
        if self.tier in ranges:
            representative, stress = ranges[self.tier]
            if (
                not representative[0]
                <= self.representative_families
                <= representative[1]
            ):
                raise ValueError(
                    f"{self.tier.value} representative families must be within "
                    f"{representative}"
                )
            if not stress[0] <= self.stress_families <= stress[1]:
                raise ValueError(
                    f"{self.tier.value} stress families must be within {stress}"
                )
        if (
            self.tier is SampleSizeTier.ILLUSTRATIVE_PILOT_DEFAULT
            and self.model_repetitions_per_variant != 3
        ):
            raise ValueError(
                "illustrative pilot default requires three model repetitions"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "representative_families": self.representative_families,
            "stress_families": self.stress_families,
            "model_repetitions_per_variant": self.model_repetitions_per_variant,
            "simulation_artifact_hash": self.simulation_artifact_hash,
            "assumption_manifest_hash": self.assumption_manifest_hash,
            "independent_analysis_unit": self.independent_analysis_unit,
            "repetitions_replace_families": self.repetitions_replace_families,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SampleSizeDesign":
        fields = {
            "tier",
            "representative_families",
            "stress_families",
            "model_repetitions_per_variant",
            "simulation_artifact_hash",
            "assumption_manifest_hash",
            "independent_analysis_unit",
            "repetitions_replace_families",
        }
        _fields(data, fields, "sample size design")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True, slots=True)
class MultiplicityPlan:
    method: MultiplicityMethod | str
    endpoint_ids: tuple[str, ...]
    primary_endpoint_ids: tuple[str, ...]
    confirmatory_claims: bool
    nominal_alpha: float | None
    ordering: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "method",
            _enum(MultiplicityMethod, self.method, "multiplicity method"),
        )
        endpoint_ids = _identifier_tuple("endpoint_ids", self.endpoint_ids)
        primary_ids = _identifier_tuple(
            "primary_endpoint_ids", self.primary_endpoint_ids, minimum=0
        )
        if not set(primary_ids).issubset(endpoint_ids):
            raise ValueError("primary endpoint IDs must be in endpoint_ids")
        object.__setattr__(self, "endpoint_ids", tuple(sorted(endpoint_ids)))
        object.__setattr__(self, "primary_endpoint_ids", tuple(sorted(primary_ids)))
        _boolean("confirmatory_claims", self.confirmatory_claims)
        ordering = _identifier_tuple("multiplicity ordering", self.ordering, minimum=0)
        object.__setattr__(self, "ordering", ordering)
        _text("multiplicity rationale", self.rationale)

        if self.method is MultiplicityMethod.DESCRIPTIVE_CI_ONLY:
            if self.confirmatory_claims or self.nominal_alpha is not None:
                raise ValueError(
                    "descriptive CI-only analysis cannot make confirmatory claims "
                    "or declare nominal alpha"
                )
            if ordering:
                raise ValueError("descriptive CI-only analysis has no test ordering")
        elif self.method is MultiplicityMethod.FALSE_DISCOVERY_RATE:
            if self.confirmatory_claims:
                raise ValueError(
                    "false-discovery-rate is reserved for exploratory analyses"
                )
            alpha = _finite("nominal_alpha", self.nominal_alpha)
            if not 0 < alpha < 1:
                raise ValueError("nominal_alpha must be between zero and one")
            object.__setattr__(self, "nominal_alpha", alpha)
        else:
            if not self.confirmatory_claims:
                raise ValueError(
                    "inferential multiplicity methods require confirmatory_claims"
                )
            if not primary_ids:
                raise ValueError(
                    "confirmatory multiplicity methods require primary endpoints"
                )
            alpha = _finite("nominal_alpha", self.nominal_alpha)
            if not 0 < alpha < 1:
                raise ValueError("nominal_alpha must be between zero and one")
            object.__setattr__(self, "nominal_alpha", alpha)
        if (
            self.method is MultiplicityMethod.ONE_PRIMARY_NO_ADJUSTMENT
            and len(primary_ids) != 1
        ):
            raise ValueError(
                "one-primary-no-adjustment requires exactly one primary endpoint"
            )
        sequence_methods = {
            MultiplicityMethod.FIXED_SEQUENCE,
            MultiplicityMethod.HIERARCHICAL,
        }
        if self.method in sequence_methods:
            if set(ordering) != set(primary_ids) or len(ordering) != len(primary_ids):
                raise ValueError(
                    "ordered multiplicity methods must order every primary endpoint"
                )
        elif ordering:
            raise ValueError(
                "ordering is only valid for fixed-sequence or hierarchical methods"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method.value,
            "endpoint_ids": list(self.endpoint_ids),
            "primary_endpoint_ids": list(self.primary_endpoint_ids),
            "confirmatory_claims": self.confirmatory_claims,
            "nominal_alpha": self.nominal_alpha,
            "ordering": list(self.ordering),
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MultiplicityPlan":
        fields = {
            "method",
            "endpoint_ids",
            "primary_endpoint_ids",
            "confirmatory_claims",
            "nominal_alpha",
            "ordering",
            "rationale",
        }
        _fields(data, fields, "multiplicity plan")
        return cls(
            method=data["method"],
            endpoint_ids=data["endpoint_ids"],
            primary_endpoint_ids=data["primary_endpoint_ids"],
            confirmatory_claims=data["confirmatory_claims"],
            nominal_alpha=data["nominal_alpha"],
            ordering=data["ordering"],
            rationale=data["rationale"],
        )


@dataclass(frozen=True, slots=True)
class SpecialtyStudyDesign(CanonicalPropertyRecord):
    """Complete approved design digest for one specialty benchmark program."""

    design_id: str
    archetype_id: str
    physician_plan: PhysicianPlan
    endpoints: tuple[EndpointSpec, ...]
    sample_size: SampleSizeDesign
    multiplicity: MultiplicityPlan
    approved_parity_decision_rule_hash: str
    clinical_approval_hash: str
    statistical_approval_hash: str
    operations_approval_hash: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _identifier("design_id", self.design_id)
        _identifier("archetype_id", self.archetype_id)
        if not isinstance(self.physician_plan, PhysicianPlan):
            raise ValueError("physician_plan must be PhysicianPlan")
        endpoints = tuple(self.endpoints)
        if not endpoints or not all(
            isinstance(endpoint, EndpointSpec) for endpoint in endpoints
        ):
            raise ValueError("endpoints must contain EndpointSpec records")
        if len({endpoint.endpoint_id for endpoint in endpoints}) != len(endpoints):
            raise ValueError("endpoint IDs must be unique")
        object.__setattr__(
            self,
            "endpoints",
            tuple(sorted(endpoints, key=lambda endpoint: endpoint.endpoint_id)),
        )
        if not isinstance(self.sample_size, SampleSizeDesign):
            raise ValueError("sample_size must be SampleSizeDesign")
        if not isinstance(self.multiplicity, MultiplicityPlan):
            raise ValueError("multiplicity must be MultiplicityPlan")
        endpoint_ids = {endpoint.endpoint_id for endpoint in endpoints}
        primary_ids = {
            endpoint.endpoint_id for endpoint in endpoints if endpoint.primary
        }
        if set(self.multiplicity.endpoint_ids) != endpoint_ids:
            raise ValueError("multiplicity plan must account for every endpoint")
        if set(self.multiplicity.primary_endpoint_ids) != primary_ids:
            raise ValueError(
                "multiplicity primary IDs must match endpoint primary flags"
            )
        for name in (
            "approved_parity_decision_rule_hash",
            "clinical_approval_hash",
            "statistical_approval_hash",
            "operations_approval_hash",
        ):
            _hash(name, getattr(self, name))
        if self.archetype_id in {"paired-equity", "paired-specialty-equity"}:
            self._validate_paired_equity_panel()
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION!r}")

    def _validate_paired_equity_panel(self) -> None:
        relationship_endpoints = {
            endpoint.relationship: endpoint
            for endpoint in self.endpoints
            if endpoint.kind is EndpointKind.PAIRED_RELATIONSHIP and endpoint.primary
        }
        if set(relationship_endpoints) != set(ReferenceRelationship):
            raise ValueError(
                "paired-equity primary endpoints must cover invariant, "
                "differentiated, and information-required relationships"
            )
        if any(endpoint.margin is None for endpoint in relationship_endpoints.values()):
            raise ValueError(
                "paired-equity primary relationship endpoints require "
                "owner-approved margins"
            )
        if not any(
            endpoint.kind is EndpointKind.ABSOLUTE_PERFORMANCE
            and endpoint.reports_each_variant
            for endpoint in self.endpoints
        ):
            raise ValueError(
                "paired-equity design must report absolute performance by variant"
            )
        if not any(
            endpoint.kind is EndpointKind.SAFETY_GUARDRAIL
            and endpoint.adjudicates_every_severe_error
            and endpoint.reports_each_variant
            for endpoint in self.endpoints
        ):
            raise ValueError(
                "paired-equity design requires a by-variant severe-error "
                "adjudication guardrail"
            )

    def validate_against_plan(self, plan: SpecialtyBenchmarkPlan) -> None:
        """Verify that this approved design is the one materialized by ``plan``."""
        if not isinstance(plan, SpecialtyBenchmarkPlan):
            raise ValueError("plan must be a SpecialtyBenchmarkPlan")
        if plan.spec.study_design_hash != self.digest:
            raise ValueError(
                "specialty benchmark plan does not bind this study-design digest"
            )
        if self.archetype_id != plan.spec.archetype.value:
            raise ValueError(
                "study-design archetype does not match the specialty benchmark plan"
            )
        if (
            self.sample_size.representative_families
            != plan.spec.representative_family_target
        ):
            raise ValueError(
                "study-design representative family target does not match the plan"
            )
        if self.sample_size.stress_families != plan.spec.stress_family_target:
            raise ValueError(
                "study-design stress family target does not match the plan"
            )
        if (
            self.sample_size.model_repetitions_per_variant
            != plan.spec.model_repetitions
        ):
            raise ValueError("study-design model repetitions do not match the plan")
        physician_families = self.physician_plan.representative_family_count
        if (
            physician_families is not None
            and physician_families > self.sample_size.representative_families
        ):
            raise ValueError(
                "physician representative family subset exceeds the "
                "study-design representative sample"
            )

    def validate_comparison(
        self,
        *,
        allocator_archetype_id: str,
        registry_archetype_id: str,
        endpoint_id: str,
        margin_unit: str,
        margin_value: float,
        decision_rule_hash: str,
        track: BenchmarkTrack | str,
    ) -> None:
        """Verify one registry comparison against approved endpoint semantics."""

        if allocator_archetype_id != self.archetype_id:
            raise ValueError(
                "study-design archetype does not match the comparison source plan"
            )
        expected_registry = {
            "noharm": "noharm",
            "paired-specialty-equity": "paired-equity",
        }.get(self.archetype_id)
        if registry_archetype_id != expected_registry:
            raise ValueError(
                "registry archetype does not match the approved study design"
            )
        _hash("comparison decision_rule_hash", decision_rule_hash)
        if decision_rule_hash != self.approved_parity_decision_rule_hash:
            raise ValueError(
                "comparison decision rule does not match the approved parity "
                "decision rule"
            )
        endpoint = self._comparison_endpoint(endpoint_id)
        track_value = _enum(BenchmarkTrack, track, "comparison track")
        if track_value is BenchmarkTrack.REPRESENTATIVE and not endpoint.primary:
            raise ValueError(
                "representative comparison endpoint is not an approved primary"
            )
        if endpoint.endpoint_id not in self.multiplicity.endpoint_ids:
            raise ValueError(
                "comparison endpoint is absent from the approved multiplicity plan"
            )
        if endpoint.margin is None:
            raise ValueError("comparison endpoint lacks an owner-approved study margin")
        unit_map = {
            MarginUnit.RATE_DIFFERENCE: "rate-difference",
            MarginUnit.SAFETY_RATE: "rate-difference",
            MarginUnit.STANDARD_DEVIATIONS: "standardized-difference",
            MarginUnit.ABSOLUTE_SCORE: "absolute-score",
        }
        if unit_map[endpoint.margin.unit] != margin_unit:
            raise ValueError(
                "comparison margin unit does not match the approved study endpoint"
            )
        value = _finite("comparison margin value", margin_value)
        if value != endpoint.margin.value:
            raise ValueError(
                "comparison margin value does not match the approved study endpoint"
            )

    def _comparison_endpoint(self, endpoint_id: str) -> EndpointSpec:
        _identifier("comparison endpoint_id", endpoint_id)
        if self.archetype_id == "noharm":
            matches = tuple(
                endpoint
                for endpoint in self.endpoints
                if endpoint.endpoint_id == endpoint_id
            )
        else:
            relationship_by_endpoint = {
                "invariant-unjustified-discordance": (
                    EndpointKind.PAIRED_RELATIONSHIP,
                    ReferenceRelationship.INVARIANT,
                ),
                "differentiated-correct-rate": (
                    EndpointKind.PAIRED_RELATIONSHIP,
                    ReferenceRelationship.DIFFERENTIATED,
                ),
                "information-seeking-rate": (
                    EndpointKind.PAIRED_RELATIONSHIP,
                    ReferenceRelationship.INFORMATION_REQUIRED,
                ),
                "severe-error-rate": (EndpointKind.SAFETY_GUARDRAIL, None),
            }
            try:
                kind, relationship = relationship_by_endpoint[endpoint_id]
            except KeyError as exc:
                raise ValueError(
                    "comparison endpoint is not supported by the paired study " "design"
                ) from exc
            matches = tuple(
                endpoint
                for endpoint in self.endpoints
                if endpoint.kind is kind and endpoint.relationship is relationship
            )
        if len(matches) != 1:
            raise ValueError(
                "comparison endpoint does not map to exactly one approved "
                "study endpoint"
            )
        return matches[0]

    def validate_physician_assignments(
        self,
        plan: SpecialtyBenchmarkPlan,
        *,
        family_manifest: PhysicianFamilyManifest,
        assignment_manifest: PhysicianAssignmentManifest,
    ) -> None:
        """Validate the complete physician subset and assignment chain."""

        self.validate_against_plan(plan)
        answering = {
            PhysicianInclusionStrategy.DESCRIPTIVE_BASELINE,
            PhysicianInclusionStrategy.FULL_HEAD_TO_HEAD,
            PhysicianInclusionStrategy.ASSISTED_UNASSISTED_CROSSOVER,
        }
        if self.physician_plan.strategy not in answering:
            raise ValueError("this physician strategy does not assign case variants")
        assignment_manifest.validate_against(
            self,
            family_manifest=family_manifest,
            specialty_plan=plan,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "design_id": self.design_id,
            "archetype_id": self.archetype_id,
            "physician_plan": self.physician_plan.to_dict(),
            "endpoints": [endpoint.to_dict() for endpoint in self.endpoints],
            "sample_size": self.sample_size.to_dict(),
            "multiplicity": self.multiplicity.to_dict(),
            "approved_parity_decision_rule_hash": (
                self.approved_parity_decision_rule_hash
            ),
            "clinical_approval_hash": self.clinical_approval_hash,
            "statistical_approval_hash": self.statistical_approval_hash,
            "operations_approval_hash": self.operations_approval_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SpecialtyStudyDesign":
        fields = {
            "schema_version",
            "design_id",
            "archetype_id",
            "physician_plan",
            "endpoints",
            "sample_size",
            "multiplicity",
            "approved_parity_decision_rule_hash",
            "clinical_approval_hash",
            "statistical_approval_hash",
            "operations_approval_hash",
        }
        _fields(data, fields, "specialty study design")
        return cls(
            schema_version=data["schema_version"],
            design_id=data["design_id"],
            archetype_id=data["archetype_id"],
            physician_plan=PhysicianPlan.from_dict(data["physician_plan"]),
            endpoints=tuple(
                EndpointSpec.from_dict(endpoint) for endpoint in data["endpoints"]
            ),
            sample_size=SampleSizeDesign.from_dict(data["sample_size"]),
            multiplicity=MultiplicityPlan.from_dict(data["multiplicity"]),
            approved_parity_decision_rule_hash=data[
                "approved_parity_decision_rule_hash"
            ],
            clinical_approval_hash=data["clinical_approval_hash"],
            statistical_approval_hash=data["statistical_approval_hash"],
            operations_approval_hash=data["operations_approval_hash"],
        )

    @classmethod
    def from_json(cls, payload: str) -> "SpecialtyStudyDesign":
        return cls.from_dict(strict_json_object(payload, "specialty study design"))


def _text(name: str, value: Any) -> str:
    return text(value, name, no_outer_whitespace=True)


def _identifier(name: str, value: Any) -> str:
    return identifier(value, name, _ID_RE, check_text=lambda v: _text(name, v))


def _identifier_tuple(
    name: str, values: Sequence[str], *, minimum: int = 1
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a sequence")
    result = tuple(_identifier(name, value) for value in values)
    if len(result) < minimum:
        raise ValueError(f"{name} must contain at least {minimum} values")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must contain unique values")
    return result


def _enum(enum_type: type[Enum], value: Any, name: str) -> Any:
    return enum_member(value, enum_type, name)


def _hash(name: str, value: Any) -> str:
    return sha256_hex(value, name)


def _boolean(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _positive_int(name: str, value: Any) -> int:
    return positive_int(value, name)


def _finite(name: str, value: Any) -> float:
    return number(value, name)


__all__ = [
    "DecisionMargin",
    "EndpointKind",
    "EndpointSpec",
    "EvaluationConditionMatch",
    "MarginUnit",
    "MultiplicityMethod",
    "MultiplicityPlan",
    "PhysicianAssignment",
    "PhysicianAssignmentManifest",
    "PhysicianFamily",
    "PhysicianFamilyManifest",
    "PhysicianInclusionStrategy",
    "PhysicianPlan",
    "PHYSICIAN_ASSIGNMENT_MANIFEST_SCHEMA_VERSION",
    "PHYSICIAN_FAMILY_MANIFEST_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "SampleSizeDesign",
    "SampleSizeTier",
    "SpecialtyStudyDesign",
]
