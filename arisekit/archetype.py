"""Versioned contracts for synthetic-versus-reference benchmark programs.

Archetypes describe evaluation structure. They do not certify that generated
cases are clinically valid, representative, licensed, or suitable for MAST.
Program manifests bind the evidence needed to run a structural parity study and
fail closed when a reference, specialty pairing, or model-separation rule is
not pinned.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

from arisekit.common.hashing import canonical_sha256 as _digest
from arisekit.common.records import CanonicalPropertyRecord, CanonicalRecord
from arisekit.common.validate import (
    checked_tuple,
    enum_member as _enum,
    exact_fields as _fields,
    identifier,
    number,
    sha256_hex,
    text,
    unique,
)
from arisekit.authoring.specialty import (
    BenchmarkTrack,
    SpecialtyBenchmarkPlan,
    normalize_specialty,
)
from arisekit.authoring.specialty_inventory import SpecialtyCellInventory


ARCHETYPE_SCHEMA_VERSION = "arisekit.benchmark-archetype.v1"
REGISTRY_SCHEMA_VERSION = "arisekit.benchmark-archetype-registry.v1"
PROGRAM_SCHEMA_VERSION = "arisekit.synthetic-benchmark-program.v2"
SPECIALTY_SOURCE_BINDING_SCHEMA_VERSION = "arisekit.specialty-source-plan-binding.v2"
STRUCTURAL_CLAIM_SCOPE = "structural-parity-research-only"
CLINICAL_VALIDITY_STATUS = "not-established"

_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$")
_PLACEHOLDERS = frozenset(
    {
        "?",
        "example",
        "n/a",
        "na",
        "none",
        "pending",
        "placeholder",
        "tbd",
        "todo",
        "unknown",
    }
)


class ArchetypeId(str, Enum):
    """Evaluation shapes supported by the initial MAST registry."""

    NOHARM = "noharm"
    SCT = "sct"
    MEDAGENTBENCH = "medagentbench"
    REXRANK = "rexrank"
    CPC = "cpc"
    PAIRED_EQUITY = "paired-equity"


class ReferenceAccessClass(str, Enum):
    PUBLIC = "public"
    RESTRICTED = "restricted"
    PRIVATE = "private"


class ReferenceAuthority(str, Enum):
    """Authorities accepted for a real/reference benchmark arm."""

    UPSTREAM_RELEASE = "upstream-release"
    DATA_OWNER_AUTHORIZATION = "data-owner-authorization"


class SpecialtySupport(str, Enum):
    SUPPORTED = "supported"
    CONDITIONAL = "conditional"
    UNSUPPORTED = "unsupported"


class InputKind(str, Enum):
    CASE_DATA = "case-data"
    EXPERT_REFERENCE = "expert-reference"
    ACTION_RUBRIC = "action-rubric"
    JUDGE_GUIDANCE = "judge-guidance"
    TOOL_SANDBOX = "tool-sandbox"
    STATE_ORACLE = "state-oracle"
    CLINICAL_IMAGE = "clinical-image"
    REPORT_REFERENCE = "report-reference"
    DIAGNOSTIC_OUTCOME = "diagnostic-outcome"
    DIFFERENTIAL_REFERENCE = "differential-reference"


class ExecutionMode(str, Enum):
    SINGLE_TURN = "single-turn"
    AGENTIC = "agentic"
    MULTIMODAL = "multimodal"


class VariantSelectionPolicy(str, Enum):
    """How evaluated logical variant slots relate to authored topology."""

    VARIABLE = "variable"
    FIXED = "fixed"
    BASELINE_PLUS_PERTURBATION_SUBSET = "baseline-plus-perturbation-subset"


class JudgePolicy(str, Enum):
    NONE = "none"
    REQUIRED = "required"
    ADJUDICATION_ONLY = "adjudication-only"


class EndpointDirection(str, Enum):
    HIGHER_IS_BETTER = "higher-is-better"
    LOWER_IS_BETTER = "lower-is-better"


class MarginUnit(str, Enum):
    ABSOLUTE_SCORE = "absolute-score"
    RATE_DIFFERENCE = "rate-difference"
    STANDARDIZED_DIFFERENCE = "standardized-difference"
    PROFILE_DISTANCE = "profile-distance"


@dataclass(frozen=True, slots=True)
class RequiredInput:
    """One load-bearing input required by an archetype."""

    input_id: str
    kind: InputKind | str
    description: str
    clinician_lock_required: bool

    def __post_init__(self) -> None:
        _identifier("required input id", self.input_id)
        object.__setattr__(self, "kind", _enum(self.kind, InputKind, "input kind"))
        _text("required input description", self.description)
        _boolean("clinician_lock_required", self.clinician_lock_required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_id": self.input_id,
            "kind": InputKind(self.kind).value,
            "description": self.description,
            "clinician_lock_required": self.clinician_lock_required,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RequiredInput":
        fields = {
            "input_id",
            "kind",
            "description",
            "clinician_lock_required",
        }
        _fields(data, fields, "required input")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True, slots=True)
class ScorerJudgeContract:
    """The scoring stages and judge boundary for an archetype."""

    scorer_id: str
    stages: tuple[str, ...]
    item_score_fields: tuple[str, ...]
    judge_policy: JudgePolicy | str
    judge_output_fields: tuple[str, ...]
    aggregation_unit: str
    description: str

    def __post_init__(self) -> None:
        _identifier("scorer id", self.scorer_id)
        object.__setattr__(
            self,
            "stages",
            _identifier_tuple("scorer stages", self.stages),
        )
        object.__setattr__(
            self,
            "item_score_fields",
            _identifier_tuple("item score fields", self.item_score_fields),
        )
        object.__setattr__(
            self,
            "judge_policy",
            _enum(self.judge_policy, JudgePolicy, "judge policy"),
        )
        judge_fields = _identifier_tuple(
            "judge output fields",
            self.judge_output_fields,
            minimum=0,
        )
        object.__setattr__(self, "judge_output_fields", judge_fields)
        if self.judge_policy is JudgePolicy.REQUIRED and not judge_fields:
            raise ValueError("required judge policy needs judge output fields")
        if self.judge_policy is JudgePolicy.NONE and judge_fields:
            raise ValueError("judge-free scorer cannot declare judge output fields")
        _identifier("aggregation unit", self.aggregation_unit)
        _text("scorer description", self.description)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scorer_id": self.scorer_id,
            "stages": list(self.stages),
            "item_score_fields": list(self.item_score_fields),
            "judge_policy": JudgePolicy(self.judge_policy).value,
            "judge_output_fields": list(self.judge_output_fields),
            "aggregation_unit": self.aggregation_unit,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScorerJudgeContract":
        fields = {
            "scorer_id",
            "stages",
            "item_score_fields",
            "judge_policy",
            "judge_output_fields",
            "aggregation_unit",
            "description",
        }
        _fields(data, fields, "scorer and judge contract")
        return cls(
            scorer_id=data["scorer_id"],
            stages=tuple(data["stages"]),
            item_score_fields=tuple(data["item_score_fields"]),
            judge_policy=data["judge_policy"],
            judge_output_fields=tuple(data["judge_output_fields"]),
            aggregation_unit=data["aggregation_unit"],
            description=data["description"],
        )


@dataclass(frozen=True, slots=True)
class BenchmarkTopology:
    """Execution shape and nested analysis units."""

    execution_mode: ExecutionMode | str
    input_modalities: tuple[str, ...]
    item_hierarchy: tuple[str, ...]
    family_shape: str
    fixed_variants_per_family: int | None
    variant_selection_policy: VariantSelectionPolicy | str
    canonical_evaluated_variants_per_family: int | None
    requires_checkpoint_per_turn: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "execution_mode",
            _enum(self.execution_mode, ExecutionMode, "execution mode"),
        )
        object.__setattr__(
            self,
            "input_modalities",
            _identifier_tuple("input modalities", self.input_modalities),
        )
        object.__setattr__(
            self,
            "item_hierarchy",
            _identifier_tuple("item hierarchy", self.item_hierarchy),
        )
        _identifier("family shape", self.family_shape)
        if self.fixed_variants_per_family is not None and (
            isinstance(self.fixed_variants_per_family, bool)
            or not isinstance(self.fixed_variants_per_family, int)
            or self.fixed_variants_per_family < 1
        ):
            raise ValueError(
                "fixed_variants_per_family must be a positive integer or null"
            )
        object.__setattr__(
            self,
            "variant_selection_policy",
            _enum(
                self.variant_selection_policy,
                VariantSelectionPolicy,
                "variant selection policy",
            ),
        )
        canonical = self.canonical_evaluated_variants_per_family
        if canonical is not None and (
            isinstance(canonical, bool)
            or not isinstance(canonical, int)
            or canonical < 1
        ):
            raise ValueError(
                "canonical_evaluated_variants_per_family must be a positive "
                "integer or null"
            )
        if (
            self.variant_selection_policy is VariantSelectionPolicy.VARIABLE
            and self.fixed_variants_per_family is not None
        ):
            raise ValueError("variable variant selection cannot declare a fixed count")
        if (
            self.variant_selection_policy is VariantSelectionPolicy.FIXED
            and self.fixed_variants_per_family is None
        ):
            raise ValueError("fixed variant selection requires a fixed count")
        if (
            self.variant_selection_policy
            is VariantSelectionPolicy.BASELINE_PLUS_PERTURBATION_SUBSET
            and (
                self.fixed_variants_per_family is None
                or canonical is None
                or canonical > self.fixed_variants_per_family
                or canonical < 2
            )
        ):
            raise ValueError(
                "baseline-plus-perturbation selection requires a canonical count "
                "between 2 and the authored maximum"
            )
        if (
            self.variant_selection_policy is VariantSelectionPolicy.FIXED
            and canonical is not None
            and canonical != self.fixed_variants_per_family
        ):
            raise ValueError(
                "fixed variant selection canonical count must equal the fixed count"
            )
        _boolean("requires_checkpoint_per_turn", self.requires_checkpoint_per_turn)
        if (
            self.execution_mode is ExecutionMode.AGENTIC
            and not self.requires_checkpoint_per_turn
        ):
            raise ValueError("agentic topology requires checkpointing every turn")

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_mode": ExecutionMode(self.execution_mode).value,
            "input_modalities": list(self.input_modalities),
            "item_hierarchy": list(self.item_hierarchy),
            "family_shape": self.family_shape,
            "fixed_variants_per_family": self.fixed_variants_per_family,
            "variant_selection_policy": VariantSelectionPolicy(
                self.variant_selection_policy
            ).value,
            "canonical_evaluated_variants_per_family": (
                self.canonical_evaluated_variants_per_family
            ),
            "requires_checkpoint_per_turn": self.requires_checkpoint_per_turn,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkTopology":
        fields = {
            "execution_mode",
            "input_modalities",
            "item_hierarchy",
            "family_shape",
            "fixed_variants_per_family",
            "variant_selection_policy",
            "canonical_evaluated_variants_per_family",
            "requires_checkpoint_per_turn",
        }
        _fields(data, fields, "benchmark topology")
        return cls(
            execution_mode=data["execution_mode"],
            input_modalities=tuple(data["input_modalities"]),
            item_hierarchy=tuple(data["item_hierarchy"]),
            family_shape=data["family_shape"],
            fixed_variants_per_family=data["fixed_variants_per_family"],
            variant_selection_policy=data["variant_selection_policy"],
            canonical_evaluated_variants_per_family=data[
                "canonical_evaluated_variants_per_family"
            ],
            requires_checkpoint_per_turn=data["requires_checkpoint_per_turn"],
        )


@dataclass(frozen=True, slots=True)
class InvariantField:
    """A field that must have the same meaning in both comparison arms."""

    field_id: str
    scope: str
    description: str

    def __post_init__(self) -> None:
        _identifier("invariant field id", self.field_id)
        _identifier("invariant field scope", self.scope)
        _text("invariant field description", self.description)

    def to_dict(self) -> dict[str, str]:
        return {
            "field_id": self.field_id,
            "scope": self.scope,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InvariantField":
        fields = {"field_id", "scope", "description"}
        _fields(data, fields, "invariant field")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True, slots=True)
class ParityEndpoint:
    """One permitted generated-versus-reference estimand."""

    endpoint_id: str
    metric: str
    estimand: str
    direction: EndpointDirection | str
    margin_unit: MarginUnit | str
    bounded_range: tuple[float, float] | None

    def __post_init__(self) -> None:
        _identifier("parity endpoint id", self.endpoint_id)
        _identifier("parity endpoint metric", self.metric)
        _text("parity endpoint estimand", self.estimand)
        object.__setattr__(
            self,
            "direction",
            _enum(self.direction, EndpointDirection, "endpoint direction"),
        )
        object.__setattr__(
            self,
            "margin_unit",
            _enum(self.margin_unit, MarginUnit, "margin unit"),
        )
        if self.bounded_range is not None:
            values = tuple(self.bounded_range)
            if len(values) != 2:
                raise ValueError("bounded_range must have lower and upper bounds")
            lower = _finite("bounded range lower", values[0])
            upper = _finite("bounded range upper", values[1])
            if lower >= upper:
                raise ValueError("bounded_range lower must be below upper")
            object.__setattr__(self, "bounded_range", (lower, upper))

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint_id": self.endpoint_id,
            "metric": self.metric,
            "estimand": self.estimand,
            "direction": EndpointDirection(self.direction).value,
            "margin_unit": MarginUnit(self.margin_unit).value,
            "bounded_range": (
                list(self.bounded_range) if self.bounded_range is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ParityEndpoint":
        fields = {
            "endpoint_id",
            "metric",
            "estimand",
            "direction",
            "margin_unit",
            "bounded_range",
        }
        _fields(data, fields, "parity endpoint")
        raw_range = data["bounded_range"]
        return cls(
            endpoint_id=data["endpoint_id"],
            metric=data["metric"],
            estimand=data["estimand"],
            direction=data["direction"],
            margin_unit=data["margin_unit"],
            bounded_range=tuple(raw_range) if raw_range is not None else None,
        )


@dataclass(frozen=True, slots=True)
class SpecialtyApplicability:
    """Whether an archetype can be authored for one specialty."""

    specialty_id: str
    support: SpecialtySupport | str
    requirement_ids: tuple[str, ...] = ()
    rationale: str = ""

    def __post_init__(self) -> None:
        _identifier("specialty id", self.specialty_id)
        object.__setattr__(
            self,
            "support",
            _enum(self.support, SpecialtySupport, "specialty support"),
        )
        requirements = _identifier_tuple(
            "applicability requirement ids",
            self.requirement_ids,
            minimum=0,
        )
        object.__setattr__(self, "requirement_ids", requirements)
        _text("applicability rationale", self.rationale)
        if self.support is SpecialtySupport.SUPPORTED and requirements:
            raise ValueError(
                "supported specialty applicability cannot require extra evidence"
            )
        if self.support is SpecialtySupport.CONDITIONAL and not requirements:
            raise ValueError(
                "conditional specialty applicability requires evidence IDs"
            )
        if self.support is SpecialtySupport.UNSUPPORTED and requirements:
            raise ValueError(
                "unsupported specialty applicability cannot be unlocked by evidence"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "specialty_id": self.specialty_id,
            "support": SpecialtySupport(self.support).value,
            "requirement_ids": list(self.requirement_ids),
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SpecialtyApplicability":
        fields = {"specialty_id", "support", "requirement_ids", "rationale"}
        _fields(data, fields, "specialty applicability")
        return cls(
            specialty_id=data["specialty_id"],
            support=data["support"],
            requirement_ids=tuple(data["requirement_ids"]),
            rationale=data["rationale"],
        )


@dataclass(frozen=True, slots=True)
class BenchmarkArchetype(CanonicalPropertyRecord):
    """Immutable authoring and evaluation contract for one benchmark shape."""

    archetype_id: ArchetypeId | str
    name: str
    required_inputs: tuple[RequiredInput, ...]
    scorer_judge: ScorerJudgeContract
    topology: BenchmarkTopology
    invariant_fields: tuple[InvariantField, ...]
    parity_endpoints: tuple[ParityEndpoint, ...]
    applicability: tuple[SpecialtyApplicability, ...]
    permitted_reference_access: tuple[ReferenceAccessClass | str, ...]
    schema_version: str = ARCHETYPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "archetype_id",
            _enum(self.archetype_id, ArchetypeId, "archetype id"),
        )
        _text("archetype name", self.name)
        required = _typed_tuple(
            "required_inputs", self.required_inputs, RequiredInput, minimum=1
        )
        _unique(required, lambda item: item.input_id, "required input IDs")
        object.__setattr__(self, "required_inputs", required)
        if not isinstance(self.scorer_judge, ScorerJudgeContract):
            raise ValueError("scorer_judge must be ScorerJudgeContract")
        if not isinstance(self.topology, BenchmarkTopology):
            raise ValueError("topology must be BenchmarkTopology")
        invariants = _typed_tuple(
            "invariant_fields", self.invariant_fields, InvariantField, minimum=1
        )
        _unique(invariants, lambda item: item.field_id, "invariant field IDs")
        object.__setattr__(self, "invariant_fields", invariants)
        endpoints = _typed_tuple(
            "parity_endpoints", self.parity_endpoints, ParityEndpoint, minimum=1
        )
        _unique(endpoints, lambda item: item.endpoint_id, "parity endpoint IDs")
        object.__setattr__(self, "parity_endpoints", endpoints)
        applicability = _typed_tuple(
            "applicability",
            self.applicability,
            SpecialtyApplicability,
            minimum=1,
        )
        _unique(
            applicability,
            lambda item: item.specialty_id,
            "specialty applicability IDs",
        )
        object.__setattr__(self, "applicability", applicability)
        access = tuple(
            _enum(value, ReferenceAccessClass, "reference access class")
            for value in self.permitted_reference_access
        )
        if not access or len(set(access)) != len(access):
            raise ValueError(
                "permitted_reference_access must contain unique access classes"
            )
        object.__setattr__(
            self,
            "permitted_reference_access",
            tuple(sorted(access, key=lambda value: value.value)),
        )
        if self.schema_version != ARCHETYPE_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {ARCHETYPE_SCHEMA_VERSION!r}")

    def endpoint(self, endpoint_id: str) -> ParityEndpoint:
        for endpoint in self.parity_endpoints:
            if endpoint.endpoint_id == endpoint_id:
                return endpoint
        raise ValueError(
            f"endpoint {endpoint_id!r} is not supported by "
            f"{ArchetypeId(self.archetype_id).value}"
        )

    def specialty(self, specialty_id: str) -> SpecialtyApplicability:
        for applicability in self.applicability:
            if applicability.specialty_id == specialty_id:
                return applicability
        raise ValueError(
            f"specialty {specialty_id!r} is not registered for "
            f"{ArchetypeId(self.archetype_id).value}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "archetype_id": ArchetypeId(self.archetype_id).value,
            "name": self.name,
            "required_inputs": [value.to_dict() for value in self.required_inputs],
            "scorer_judge": self.scorer_judge.to_dict(),
            "topology": self.topology.to_dict(),
            "invariant_fields": [value.to_dict() for value in self.invariant_fields],
            "parity_endpoints": [value.to_dict() for value in self.parity_endpoints],
            "applicability": [value.to_dict() for value in self.applicability],
            "permitted_reference_access": [
                ReferenceAccessClass(value).value
                for value in self.permitted_reference_access
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkArchetype":
        fields = {
            "schema_version",
            "archetype_id",
            "name",
            "required_inputs",
            "scorer_judge",
            "topology",
            "invariant_fields",
            "parity_endpoints",
            "applicability",
            "permitted_reference_access",
        }
        _fields(data, fields, "benchmark archetype")
        return cls(
            schema_version=data["schema_version"],
            archetype_id=data["archetype_id"],
            name=data["name"],
            required_inputs=tuple(
                RequiredInput.from_dict(value) for value in data["required_inputs"]
            ),
            scorer_judge=ScorerJudgeContract.from_dict(data["scorer_judge"]),
            topology=BenchmarkTopology.from_dict(data["topology"]),
            invariant_fields=tuple(
                InvariantField.from_dict(value) for value in data["invariant_fields"]
            ),
            parity_endpoints=tuple(
                ParityEndpoint.from_dict(value) for value in data["parity_endpoints"]
            ),
            applicability=tuple(
                SpecialtyApplicability.from_dict(value)
                for value in data["applicability"]
            ),
            permitted_reference_access=tuple(data["permitted_reference_access"]),
        )


@dataclass(frozen=True, slots=True)
class BenchmarkArchetypeRegistry(CanonicalPropertyRecord):
    """Exact set of archetypes and specialty identifiers used by a program."""

    registry_id: str
    specialties: tuple[str, ...]
    archetypes: tuple[BenchmarkArchetype, ...]
    schema_version: str = REGISTRY_SCHEMA_VERSION
    _by_id: Mapping[ArchetypeId, BenchmarkArchetype] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _identifier("registry id", self.registry_id)
        specialties = _identifier_tuple("registry specialties", self.specialties)
        object.__setattr__(self, "specialties", specialties)
        archetypes = _typed_tuple(
            "registry archetypes",
            self.archetypes,
            BenchmarkArchetype,
            minimum=1,
        )
        _unique(
            archetypes,
            lambda item: ArchetypeId(item.archetype_id),
            "registry archetype IDs",
        )
        expected = set(specialties)
        for archetype in archetypes:
            actual = {item.specialty_id for item in archetype.applicability}
            if actual != expected:
                missing = sorted(expected - actual)
                extra = sorted(actual - expected)
                raise ValueError(
                    f"{ArchetypeId(archetype.archetype_id).value} applicability "
                    f"must cover every registry specialty; missing={missing}, "
                    f"extra={extra}"
                )
        object.__setattr__(self, "archetypes", archetypes)
        object.__setattr__(
            self,
            "_by_id",
            MappingProxyType(
                {
                    ArchetypeId(archetype.archetype_id): archetype
                    for archetype in archetypes
                }
            ),
        )
        if self.schema_version != REGISTRY_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {REGISTRY_SCHEMA_VERSION!r}")

    def get(self, archetype_id: ArchetypeId | str) -> BenchmarkArchetype:
        try:
            return self._by_id[ArchetypeId(archetype_id)]
        except (KeyError, ValueError) as exc:
            raise ValueError(f"unknown benchmark archetype: {archetype_id!r}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "registry_id": self.registry_id,
            "specialties": list(self.specialties),
            "archetypes": [value.to_dict() for value in self.archetypes],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkArchetypeRegistry":
        fields = {"schema_version", "registry_id", "specialties", "archetypes"}
        _fields(data, fields, "benchmark archetype registry")
        return cls(
            schema_version=data["schema_version"],
            registry_id=data["registry_id"],
            specialties=tuple(data["specialties"]),
            archetypes=tuple(
                BenchmarkArchetype.from_dict(value) for value in data["archetypes"]
            ),
        )


@dataclass(frozen=True, slots=True)
class ModelRoute:
    """Pinned model route used for generation, solving, or judging."""

    route_id: str
    provider: str
    model: str
    snapshot: str
    family: str
    runtime_config_hash: str

    def __post_init__(self) -> None:
        _identifier("model route id", self.route_id)
        for name in ("provider", "model", "snapshot", "family"):
            _text(f"model route {name}", getattr(self, name))
        _hash("runtime_config_hash", self.runtime_config_hash)

    def to_dict(self) -> dict[str, str]:
        return {
            "route_id": self.route_id,
            "provider": self.provider,
            "model": self.model,
            "snapshot": self.snapshot,
            "family": self.family,
            "runtime_config_hash": self.runtime_config_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelRoute":
        fields = {
            "route_id",
            "provider",
            "model",
            "snapshot",
            "family",
            "runtime_config_hash",
        }
        _fields(data, fields, "model route")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True, slots=True)
class ReferenceBundleBinding:
    """Pinned real benchmark bundle and the authority that supplied it."""

    access_class: ReferenceAccessClass | str
    bundle_hash: str
    manifest_hash: str
    source_revision: str
    authority: ReferenceAuthority | str
    authority_digest: str
    private_use_authorization_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "access_class",
            _enum(self.access_class, ReferenceAccessClass, "reference access class"),
        )
        _hash("reference bundle_hash", self.bundle_hash)
        _hash("reference manifest_hash", self.manifest_hash)
        _text("reference source_revision", self.source_revision)
        object.__setattr__(
            self,
            "authority",
            _enum(self.authority, ReferenceAuthority, "reference authority"),
        )
        _hash("reference authority_digest", self.authority_digest)
        if self.access_class is ReferenceAccessClass.PUBLIC:
            if self.authority is not ReferenceAuthority.UPSTREAM_RELEASE:
                raise ValueError(
                    "public reference must be bound to an upstream release authority"
                )
            if self.private_use_authorization_digest is not None:
                raise ValueError(
                    "public reference cannot carry private-use authorization"
                )
        else:
            if self.authority is not ReferenceAuthority.DATA_OWNER_AUTHORIZATION:
                raise ValueError(
                    "restricted/private reference requires data-owner authority"
                )
            if self.private_use_authorization_digest is None:
                raise ValueError(
                    "restricted/private source use requires authorization digest"
                )
            _hash(
                "private_use_authorization_digest",
                self.private_use_authorization_digest,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_class": ReferenceAccessClass(self.access_class).value,
            "bundle_hash": self.bundle_hash,
            "manifest_hash": self.manifest_hash,
            "source_revision": self.source_revision,
            "authority": ReferenceAuthority(self.authority).value,
            "authority_digest": self.authority_digest,
            "private_use_authorization_digest": (self.private_use_authorization_digest),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReferenceBundleBinding":
        fields = {
            "access_class",
            "bundle_hash",
            "manifest_hash",
            "source_revision",
            "authority",
            "authority_digest",
            "private_use_authorization_digest",
        }
        _fields(data, fields, "reference bundle binding")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True, slots=True)
class SyntheticBundleBinding:
    """Pinned generated arm and its generation and human-review evidence."""

    bundle_hash: str
    manifest_hash: str
    generation_lineage_hash: str
    clinical_review_hash: str
    rights_review_hash: str
    generator: ModelRoute

    def __post_init__(self) -> None:
        for name in (
            "bundle_hash",
            "manifest_hash",
            "generation_lineage_hash",
            "clinical_review_hash",
            "rights_review_hash",
        ):
            _hash(f"synthetic {name}", getattr(self, name))
        if not isinstance(self.generator, ModelRoute):
            raise ValueError("synthetic generator must be ModelRoute")

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_hash": self.bundle_hash,
            "manifest_hash": self.manifest_hash,
            "generation_lineage_hash": self.generation_lineage_hash,
            "clinical_review_hash": self.clinical_review_hash,
            "rights_review_hash": self.rights_review_hash,
            "generator": self.generator.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SyntheticBundleBinding":
        fields = {
            "bundle_hash",
            "manifest_hash",
            "generation_lineage_hash",
            "clinical_review_hash",
            "rights_review_hash",
            "generator",
        }
        _fields(data, fields, "synthetic bundle binding")
        return cls(
            bundle_hash=data["bundle_hash"],
            manifest_hash=data["manifest_hash"],
            generation_lineage_hash=data["generation_lineage_hash"],
            clinical_review_hash=data["clinical_review_hash"],
            rights_review_hash=data["rights_review_hash"],
            generator=ModelRoute.from_dict(data["generator"]),
        )


@dataclass(frozen=True, slots=True)
class ApplicabilityEvidence:
    requirement_id: str
    evidence_hash: str

    def __post_init__(self) -> None:
        _identifier("applicability requirement id", self.requirement_id)
        _hash("applicability evidence_hash", self.evidence_hash)

    def to_dict(self) -> dict[str, str]:
        return {
            "requirement_id": self.requirement_id,
            "evidence_hash": self.evidence_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ApplicabilityEvidence":
        fields = {"requirement_id", "evidence_hash"}
        _fields(data, fields, "applicability evidence")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True, slots=True)
class ParityMargin:
    unit: MarginUnit | str
    value: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "unit", _enum(self.unit, MarginUnit, "parity margin unit")
        )
        value = _finite("parity margin value", self.value)
        if value <= 0:
            raise ValueError("parity margin value must be positive")
        object.__setattr__(self, "value", value)

    def to_dict(self) -> dict[str, Any]:
        return {"unit": MarginUnit(self.unit).value, "value": self.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ParityMargin":
        fields = {"unit", "value"}
        _fields(data, fields, "parity margin")
        return cls(unit=data["unit"], value=data["value"])


@dataclass(frozen=True, slots=True)
class SpecialtyPlanCellBinding:
    """One selected allocation cell from a frozen specialty plan."""

    cell_id: str
    family_count: int
    cell_sha256: str

    def __post_init__(self) -> None:
        _text("specialty plan cell id", self.cell_id)
        if (
            isinstance(self.family_count, bool)
            or not isinstance(self.family_count, int)
            or self.family_count < 1
        ):
            raise ValueError("specialty plan cell family_count must be positive")
        _hash("specialty plan cell_sha256", self.cell_sha256)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "family_count": self.family_count,
            "cell_sha256": self.cell_sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SpecialtyPlanCellBinding":
        fields = {"cell_id", "family_count", "cell_sha256"}
        _fields(data, fields, "specialty plan cell binding")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True, slots=True)
class SpecialtySourcePlanBinding:
    """Exact bridge from a clinician-locked specialty plan to one comparison.

    The binding contains no clinical case content. It binds one specialty and
    one representative or stress track to the exact planning, authorization,
    materialized-cell inventory, study-design, and solver repetition inputs
    that must be used by the comparison.
    """

    allocator_archetype_id: str
    specialty_id: str
    track: BenchmarkTrack | str
    spec_sha256: str
    plan_sha256: str
    clinical_scope_sha256: str
    clinical_lock_sha256: str
    authorization_sha256s: tuple[str, ...]
    planned_cells: tuple[SpecialtyPlanCellBinding, ...]
    cell_inventory_sha256: str
    materialized_bundle_sha256: str
    study_design_sha256: str
    model_route_ids: tuple[str, ...]
    model_repetitions: int
    schema_version: str = SPECIALTY_SOURCE_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SPECIALTY_SOURCE_BINDING_SCHEMA_VERSION:
            raise ValueError(
                "unsupported specialty source-plan binding schema "
                f"{self.schema_version!r}"
            )
        _identifier("allocator archetype id", self.allocator_archetype_id)
        registry_archetype_id_for_specialty(self.allocator_archetype_id)
        _identifier("specialty source-plan specialty id", self.specialty_id)
        object.__setattr__(
            self,
            "track",
            _enum(self.track, BenchmarkTrack, "specialty source-plan track"),
        )
        for name in (
            "spec_sha256",
            "plan_sha256",
            "clinical_scope_sha256",
            "clinical_lock_sha256",
            "cell_inventory_sha256",
            "materialized_bundle_sha256",
            "study_design_sha256",
        ):
            _hash(f"specialty source-plan {name}", getattr(self, name))

        authorizations = tuple(self.authorization_sha256s)
        if not authorizations:
            raise ValueError(
                "specialty source-plan binding requires authorization hashes"
            )
        for value in authorizations:
            _hash("specialty source-plan authorization hash", value)
        if len(set(authorizations)) != len(authorizations):
            raise ValueError(
                "specialty source-plan authorization hashes must be unique"
            )
        object.__setattr__(self, "authorization_sha256s", tuple(sorted(authorizations)))

        cells = _typed_tuple(
            "specialty source-plan planned cells",
            self.planned_cells,
            SpecialtyPlanCellBinding,
            minimum=1,
        )
        _unique(cells, lambda value: value.cell_id, "specialty plan cell IDs")
        expected_prefix = f"{self.specialty_id}--{self.track.value}--"
        if any(not value.cell_id.startswith(expected_prefix) for value in cells):
            raise ValueError(
                "specialty source-plan cells must match the bound specialty and track"
            )
        object.__setattr__(
            self, "planned_cells", tuple(sorted(cells, key=lambda value: value.cell_id))
        )

        route_ids = tuple(self.model_route_ids)
        if not 1 <= len(route_ids) <= 4:
            raise ValueError(
                "specialty source-plan model_route_ids must contain one to four routes"
            )
        for route_id in route_ids:
            _identifier("specialty source-plan model route id", route_id)
        if len(set(route_ids)) != len(route_ids):
            raise ValueError("specialty source-plan model route IDs must be unique")
        object.__setattr__(self, "model_route_ids", route_ids)
        if (
            isinstance(self.model_repetitions, bool)
            or not isinstance(self.model_repetitions, int)
            or self.model_repetitions < 1
        ):
            raise ValueError("specialty source-plan model_repetitions must be positive")

    @classmethod
    def _from_specialty_plan_evidence(
        cls,
        plan: SpecialtyBenchmarkPlan,
        *,
        specialty: str | Enum,
        track: BenchmarkTrack | str,
        cell_inventory_sha256: str,
        materialized_bundle_sha256: str,
        study_design_sha256: str,
    ) -> "SpecialtySourcePlanBinding":
        """Build from already validated evidence.

        This helper is private because bare digests do not prove that a
        reviewed inventory artifact exists. Public construction goes through
        ``from_specialty_inventory``.
        """

        if not isinstance(plan, SpecialtyBenchmarkPlan):
            raise ValueError("plan must be a SpecialtyBenchmarkPlan")
        if study_design_sha256 != plan.spec.study_design_hash:
            raise ValueError(
                "study design hash is stale relative to the specialty plan"
            )
        specialty_value = normalize_specialty(specialty)
        track_value = BenchmarkTrack(track)
        selected_cells = tuple(
            cell
            for cell in plan.cells
            if cell.specialty is specialty_value and cell.track is track_value
        )
        if not selected_cells:
            raise ValueError(
                "specialty plan has no cells for the requested specialty and track"
            )
        return cls(
            allocator_archetype_id=plan.spec.archetype.value,
            specialty_id=specialty_value.value,
            track=track_value,
            spec_sha256=plan.spec.spec_sha256,
            plan_sha256=plan.plan_sha256,
            clinical_scope_sha256=plan.spec.clinical_scope.scope_sha256,
            clinical_lock_sha256=plan.spec.clinical_lock.lock_sha256,
            authorization_sha256s=tuple(
                authorization.authorization_sha256
                for authorization in plan.spec.data_authorizations
            ),
            planned_cells=tuple(
                SpecialtyPlanCellBinding(
                    cell_id=cell.cell_id,
                    family_count=cell.family_count,
                    cell_sha256=_digest(cell.to_dict()),
                )
                for cell in selected_cells
            ),
            cell_inventory_sha256=cell_inventory_sha256,
            materialized_bundle_sha256=materialized_bundle_sha256,
            study_design_sha256=plan.spec.study_design_hash,
            model_route_ids=plan.spec.model_ids,
            model_repetitions=plan.spec.model_repetitions,
        )

    @classmethod
    def from_specialty_plan(
        cls,
        plan: SpecialtyBenchmarkPlan,
        *,
        inventory: SpecialtyCellInventory,
        study_design_sha256: str,
    ) -> "SpecialtySourcePlanBinding":
        """Bind a plan through its typed reviewed cell inventory."""

        return cls.from_specialty_inventory(
            plan,
            inventory,
            study_design_sha256=study_design_sha256,
        )

    @classmethod
    def from_specialty_inventory(
        cls,
        plan: SpecialtyBenchmarkPlan,
        inventory: SpecialtyCellInventory,
        *,
        study_design_sha256: str,
    ) -> "SpecialtySourcePlanBinding":
        """Bind a plan through a typed, exact authored-cell inventory."""

        if not isinstance(inventory, SpecialtyCellInventory):
            raise ValueError("inventory must be a SpecialtyCellInventory")
        inventory.validate_plan_slice(plan)
        return cls._from_specialty_plan_evidence(
            plan,
            specialty=inventory.specialty,
            track=inventory.track,
            cell_inventory_sha256=inventory.inventory_sha256,
            materialized_bundle_sha256=inventory.export_bundle_sha256,
            study_design_sha256=study_design_sha256,
        )

    def validate_inventory(self, inventory: SpecialtyCellInventory) -> None:
        """Fail unless a typed inventory is the exact artifact bound here."""

        if not isinstance(inventory, SpecialtyCellInventory):
            raise ValueError("inventory must be a SpecialtyCellInventory")
        checks = (
            (
                "allocator archetype",
                inventory.allocator_archetype_id.value,
                self.allocator_archetype_id,
            ),
            ("specialty", inventory.specialty.value, self.specialty_id),
            ("track", inventory.track, self.track),
            ("spec digest", inventory.spec_sha256, self.spec_sha256),
            ("plan digest", inventory.plan_sha256, self.plan_sha256),
            (
                "inventory digest",
                inventory.inventory_sha256,
                self.cell_inventory_sha256,
            ),
            (
                "materialized bundle digest",
                inventory.export_bundle_sha256,
                self.materialized_bundle_sha256,
            ),
        )
        for label, actual, expected in checks:
            if actual != expected:
                raise ValueError(
                    f"specialty cell inventory {label} does not match the "
                    "source-plan binding"
                )

        expected_cells = {
            cell.cell_id: (cell.family_count, cell.cell_sha256)
            for cell in self.planned_cells
        }
        actual_cells = {
            cell.cell_id: (cell.expected_family_count, cell.cell_sha256)
            for cell in inventory.cells
        }
        if actual_cells != expected_cells:
            raise ValueError(
                "specialty cell inventory cells do not match the source-plan binding"
            )

    @property
    def registry_archetype_id(self) -> ArchetypeId:
        return registry_archetype_id_for_specialty(self.allocator_archetype_id)

    @property
    def planned_family_count(self) -> int:
        return sum(cell.family_count for cell in self.planned_cells)

    @property
    def plan_cell_manifest_sha256(self) -> str:
        return _digest([cell.to_dict() for cell in self.planned_cells])

    @property
    def authorization_set_sha256(self) -> str:
        return _digest(list(self.authorization_sha256s))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "allocator_archetype_id": self.allocator_archetype_id,
            "registry_archetype_id": self.registry_archetype_id.value,
            "specialty_id": self.specialty_id,
            "track": self.track.value,
            "spec_sha256": self.spec_sha256,
            "plan_sha256": self.plan_sha256,
            "clinical_scope_sha256": self.clinical_scope_sha256,
            "clinical_lock_sha256": self.clinical_lock_sha256,
            "authorization_sha256s": list(self.authorization_sha256s),
            "authorization_set_sha256": self.authorization_set_sha256,
            "planned_cells": [cell.to_dict() for cell in self.planned_cells],
            "plan_cell_manifest_sha256": self.plan_cell_manifest_sha256,
            "cell_inventory_sha256": self.cell_inventory_sha256,
            "materialized_bundle_sha256": self.materialized_bundle_sha256,
            "study_design_sha256": self.study_design_sha256,
            "planned_family_count": self.planned_family_count,
            "model_route_ids": list(self.model_route_ids),
            "model_repetitions": self.model_repetitions,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["binding_sha256"] = _digest(payload)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SpecialtySourcePlanBinding":
        fields = {
            "schema_version",
            "allocator_archetype_id",
            "registry_archetype_id",
            "specialty_id",
            "track",
            "spec_sha256",
            "plan_sha256",
            "clinical_scope_sha256",
            "clinical_lock_sha256",
            "authorization_sha256s",
            "authorization_set_sha256",
            "planned_cells",
            "plan_cell_manifest_sha256",
            "cell_inventory_sha256",
            "materialized_bundle_sha256",
            "study_design_sha256",
            "planned_family_count",
            "model_route_ids",
            "model_repetitions",
            "binding_sha256",
        }
        _fields(data, fields, "specialty source-plan binding")
        payload = {name: data[name] for name in fields - {"binding_sha256"}}
        if _digest(payload) != data["binding_sha256"]:
            raise ValueError("specialty source-plan binding hash mismatch")
        result = cls(
            schema_version=data["schema_version"],
            allocator_archetype_id=data["allocator_archetype_id"],
            specialty_id=data["specialty_id"],
            track=data["track"],
            spec_sha256=data["spec_sha256"],
            plan_sha256=data["plan_sha256"],
            clinical_scope_sha256=data["clinical_scope_sha256"],
            clinical_lock_sha256=data["clinical_lock_sha256"],
            authorization_sha256s=tuple(data["authorization_sha256s"]),
            planned_cells=tuple(
                SpecialtyPlanCellBinding.from_dict(value)
                for value in data["planned_cells"]
            ),
            cell_inventory_sha256=data["cell_inventory_sha256"],
            materialized_bundle_sha256=data["materialized_bundle_sha256"],
            study_design_sha256=data["study_design_sha256"],
            model_route_ids=tuple(data["model_route_ids"]),
            model_repetitions=data["model_repetitions"],
        )
        if result.to_dict() != dict(data):
            raise ValueError("specialty source-plan binding is not canonically derived")
        return result

    @property
    def digest(self) -> str:
        return _digest(self._payload())


@dataclass(frozen=True, slots=True)
class SyntheticComparison(CanonicalRecord):
    """One archetype-specialty comparison selected for a program."""

    comparison_id: str
    archetype_id: ArchetypeId | str
    specialty_id: str
    reference: ReferenceBundleBinding
    synthetic: SyntheticBundleBinding
    endpoint_id: str
    margin: ParityMargin
    decision_rule_hash: str
    track: BenchmarkTrack | str = BenchmarkTrack.REPRESENTATIVE
    source_plan_binding: SpecialtySourcePlanBinding | None = None
    applicability_evidence: tuple[ApplicabilityEvidence, ...] = ()
    claim_scope: str = STRUCTURAL_CLAIM_SCOPE
    clinical_validity_status: str = CLINICAL_VALIDITY_STATUS

    def __post_init__(self) -> None:
        _identifier("comparison id", self.comparison_id)
        object.__setattr__(
            self,
            "archetype_id",
            _enum(self.archetype_id, ArchetypeId, "comparison archetype id"),
        )
        _identifier("comparison specialty id", self.specialty_id)
        if not isinstance(self.reference, ReferenceBundleBinding):
            raise ValueError("reference must be ReferenceBundleBinding")
        if not isinstance(self.synthetic, SyntheticBundleBinding):
            raise ValueError("synthetic must be SyntheticBundleBinding")
        if self.reference.bundle_hash == self.synthetic.bundle_hash:
            raise ValueError("reference and synthetic bundles must be distinct")
        _identifier("comparison endpoint id", self.endpoint_id)
        if not isinstance(self.margin, ParityMargin):
            raise ValueError("margin must be ParityMargin")
        _hash("comparison decision_rule_hash", self.decision_rule_hash)
        object.__setattr__(
            self, "track", _enum(self.track, BenchmarkTrack, "comparison track")
        )
        source_bound_archetypes = {
            ArchetypeId.NOHARM,
            ArchetypeId.PAIRED_EQUITY,
        }
        if self.archetype_id in source_bound_archetypes:
            if not isinstance(self.source_plan_binding, SpecialtySourcePlanBinding):
                raise ValueError(
                    "NOHARM and paired-equity comparisons require a "
                    "SpecialtySourcePlanBinding"
                )
        elif self.source_plan_binding is not None and not isinstance(
            self.source_plan_binding, SpecialtySourcePlanBinding
        ):
            raise ValueError(
                "source_plan_binding must be SpecialtySourcePlanBinding or null"
            )
        if self.source_plan_binding is not None:
            if self.source_plan_binding.specialty_id != self.specialty_id:
                raise ValueError(
                    "specialty source-plan binding does not match comparison specialty"
                )
            if self.source_plan_binding.track is not self.track:
                raise ValueError(
                    "specialty source-plan binding does not match comparison track"
                )
            if self.source_plan_binding.registry_archetype_id is not self.archetype_id:
                raise ValueError(
                    "specialty allocator archetype does not match comparison archetype"
                )
        evidence = _typed_tuple(
            "applicability_evidence",
            self.applicability_evidence,
            ApplicabilityEvidence,
            minimum=0,
        )
        _unique(
            evidence,
            lambda item: item.requirement_id,
            "applicability evidence requirement IDs",
        )
        object.__setattr__(self, "applicability_evidence", evidence)
        if self.claim_scope != STRUCTURAL_CLAIM_SCOPE:
            raise ValueError(
                "synthetic comparison can claim structural parity research only"
            )
        if self.clinical_validity_status != CLINICAL_VALIDITY_STATUS:
            raise ValueError("structural emulation cannot declare clinical validity")

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "archetype_id": ArchetypeId(self.archetype_id).value,
            "specialty_id": self.specialty_id,
            "reference": self.reference.to_dict(),
            "synthetic": self.synthetic.to_dict(),
            "endpoint_id": self.endpoint_id,
            "margin": self.margin.to_dict(),
            "decision_rule_hash": self.decision_rule_hash,
            "track": self.track.value,
            "source_plan_binding": (
                self.source_plan_binding.to_dict()
                if self.source_plan_binding is not None
                else None
            ),
            "applicability_evidence": [
                value.to_dict() for value in self.applicability_evidence
            ],
            "claim_scope": self.claim_scope,
            "clinical_validity_status": self.clinical_validity_status,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SyntheticComparison":
        fields = {
            "comparison_id",
            "archetype_id",
            "specialty_id",
            "reference",
            "synthetic",
            "endpoint_id",
            "margin",
            "decision_rule_hash",
            "track",
            "source_plan_binding",
            "applicability_evidence",
            "claim_scope",
            "clinical_validity_status",
        }
        _fields(data, fields, "synthetic comparison")
        return cls(
            comparison_id=data["comparison_id"],
            archetype_id=data["archetype_id"],
            specialty_id=data["specialty_id"],
            reference=ReferenceBundleBinding.from_dict(data["reference"]),
            synthetic=SyntheticBundleBinding.from_dict(data["synthetic"]),
            endpoint_id=data["endpoint_id"],
            margin=ParityMargin.from_dict(data["margin"]),
            decision_rule_hash=data["decision_rule_hash"],
            track=data["track"],
            source_plan_binding=(
                SpecialtySourcePlanBinding.from_dict(data["source_plan_binding"])
                if data["source_plan_binding"] is not None
                else None
            ),
            applicability_evidence=tuple(
                ApplicabilityEvidence.from_dict(value)
                for value in data["applicability_evidence"]
            ),
            claim_scope=data["claim_scope"],
            clinical_validity_status=data["clinical_validity_status"],
        )


@dataclass(frozen=True, slots=True)
class ComparisonCell:
    """Deterministic reference-versus-synthetic cell for one solver."""

    cell_id: str
    comparison_id: str
    archetype_id: str
    specialty_id: str
    solver_route_id: str
    reference_bundle_hash: str
    synthetic_bundle_hash: str
    endpoint_id: str
    evaluation_contract_hash: str

    def to_dict(self) -> dict[str, str]:
        return {
            "cell_id": self.cell_id,
            "comparison_id": self.comparison_id,
            "archetype_id": self.archetype_id,
            "specialty_id": self.specialty_id,
            "solver_route_id": self.solver_route_id,
            "reference_bundle_hash": self.reference_bundle_hash,
            "synthetic_bundle_hash": self.synthetic_bundle_hash,
            "endpoint_id": self.endpoint_id,
            "evaluation_contract_hash": self.evaluation_contract_hash,
        }


@dataclass(frozen=True, slots=True)
class SyntheticBenchmarkProgram(CanonicalPropertyRecord):
    """Frozen archetype-by-specialty comparison program.

    The registry object is required when constructing or loading a manifest.
    Only its digest is serialized, so a stale or substituted registry cannot be
    used without an explicit mismatch.
    """

    program_id: str
    registry: BenchmarkArchetypeRegistry = field(repr=False, compare=False)
    comparisons: tuple[SyntheticComparison, ...]
    solver_panel: tuple[ModelRoute, ...]
    judge_panel: tuple[ModelRoute, ...]
    program_review_hash: str
    schema_version: str = PROGRAM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _identifier("program id", self.program_id)
        if not isinstance(self.registry, BenchmarkArchetypeRegistry):
            raise ValueError("registry must be BenchmarkArchetypeRegistry")
        comparisons = _typed_tuple(
            "program comparisons",
            self.comparisons,
            SyntheticComparison,
            minimum=1,
        )
        _unique(
            comparisons,
            lambda item: item.comparison_id,
            "program comparison IDs",
        )
        coordinates = [
            (
                ArchetypeId(item.archetype_id),
                item.specialty_id,
                item.endpoint_id,
                BenchmarkTrack(item.track),
            )
            for item in comparisons
        ]
        if len(set(coordinates)) != len(coordinates):
            raise ValueError(
                "program cannot repeat an archetype-specialty-endpoint-track "
                "comparison"
            )
        object.__setattr__(self, "comparisons", comparisons)
        solvers = _typed_tuple("solver_panel", self.solver_panel, ModelRoute, minimum=3)
        if len(solvers) > 4:
            raise ValueError("solver_panel must contain three or four model routes")
        _unique(solvers, lambda item: item.route_id, "solver route IDs")
        _unique(solvers, lambda item: _family(item.family), "solver families")
        object.__setattr__(self, "solver_panel", solvers)
        judges = _typed_tuple("judge_panel", self.judge_panel, ModelRoute, minimum=0)
        _unique(judges, lambda item: item.route_id, "judge route IDs")
        _unique(judges, lambda item: _family(item.family), "judge families")
        object.__setattr__(self, "judge_panel", judges)
        _hash("program_review_hash", self.program_review_hash)
        if self.schema_version != PROGRAM_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {PROGRAM_SCHEMA_VERSION!r}")

        requires_judge = False
        permits_judge = False
        generator_families: set[str] = set()
        for comparison in comparisons:
            archetype = self.registry.get(comparison.archetype_id)
            applicability = archetype.specialty(comparison.specialty_id)
            if applicability.support is SpecialtySupport.UNSUPPORTED:
                raise ValueError(
                    f"unsupported specialty/archetype pair: "
                    f"{comparison.specialty_id} x "
                    f"{ArchetypeId(comparison.archetype_id).value}"
                )
            evidence_ids = {
                item.requirement_id for item in comparison.applicability_evidence
            }
            expected_ids = set(applicability.requirement_ids)
            if evidence_ids != expected_ids:
                raise ValueError(
                    f"applicability evidence for {comparison.comparison_id!r} "
                    f"must exactly match {sorted(expected_ids)}"
                )
            if (
                comparison.reference.access_class
                not in archetype.permitted_reference_access
            ):
                raise ValueError(
                    f"{ArchetypeId(archetype.archetype_id).value} does not permit "
                    f"{ReferenceAccessClass(comparison.reference.access_class).value} "
                    "reference access"
                )
            endpoint = archetype.endpoint(comparison.endpoint_id)
            if comparison.margin.unit is not endpoint.margin_unit:
                raise ValueError(
                    f"margin unit for {comparison.comparison_id!r} must be "
                    f"{MarginUnit(endpoint.margin_unit).value}"
                )
            if endpoint.bounded_range is not None:
                span = endpoint.bounded_range[1] - endpoint.bounded_range[0]
                if comparison.margin.value >= span:
                    raise ValueError(
                        f"margin for {comparison.comparison_id!r} must be smaller "
                        "than the endpoint range"
                    )
            source_binding = comparison.source_plan_binding
            if source_binding is not None:
                expected_route_ids = tuple(route.route_id for route in solvers)
                if source_binding.model_route_ids != expected_route_ids:
                    raise ValueError(
                        f"specialty source-plan model route IDs for "
                        f"{comparison.comparison_id!r} do not match the exact "
                        "program solver panel"
                    )
                if (
                    comparison.synthetic.clinical_review_hash
                    != source_binding.clinical_lock_sha256
                ):
                    raise ValueError(
                        f"synthetic clinical review for "
                        f"{comparison.comparison_id!r} is stale relative to the "
                        "specialty clinical lock"
                    )
                if (
                    comparison.synthetic.rights_review_hash
                    != source_binding.authorization_set_sha256
                ):
                    raise ValueError(
                        f"synthetic rights review for "
                        f"{comparison.comparison_id!r} is stale relative to the "
                        "specialty data authorizations"
                    )
                if (
                    comparison.synthetic.manifest_hash
                    != source_binding.cell_inventory_sha256
                ):
                    raise ValueError(
                        f"synthetic manifest for {comparison.comparison_id!r} "
                        "does not match the bound specialty cell inventory"
                    )
                if (
                    comparison.synthetic.bundle_hash
                    != source_binding.materialized_bundle_sha256
                ):
                    raise ValueError(
                        f"synthetic bundle for {comparison.comparison_id!r} "
                        "does not match the bundle bound by the specialty "
                        "cell inventory"
                    )
            policy = JudgePolicy(archetype.scorer_judge.judge_policy)
            requires_judge = requires_judge or policy is JudgePolicy.REQUIRED
            permits_judge = permits_judge or policy is not JudgePolicy.NONE
            generator_families.add(_family(comparison.synthetic.generator.family))

        if requires_judge and not judges:
            raise ValueError("selected archetype requires a pinned judge panel")
        if judges and not permits_judge:
            raise ValueError("judge panel supplied for judge-free archetypes")

        solver_families = {_family(value.family) for value in solvers}
        judge_families = {_family(value.family) for value in judges}
        overlaps = {
            "generator/solver": generator_families & solver_families,
            "generator/judge": generator_families & judge_families,
            "solver/judge": solver_families & judge_families,
        }
        for label, families in overlaps.items():
            if families:
                raise ValueError(
                    f"{label} family overlap is prohibited: {sorted(families)}"
                )

    @property
    def registry_digest(self) -> str:
        return self.registry.digest

    def comparison(self, comparison_id: str) -> SyntheticComparison:
        """Return one exact comparison or fail on a stale identifier."""

        _identifier("comparison id", comparison_id)
        for comparison in self.comparisons:
            if comparison.comparison_id == comparison_id:
                return comparison
        raise ValueError(
            f"comparison {comparison_id!r} is not registered in "
            f"program {self.program_id!r}"
        )

    def judge_panel_for(self, comparison_id: str) -> tuple[ModelRoute, ...]:
        """Return only the judge routes permitted by one comparison's scorer."""

        comparison = self.comparison(comparison_id)
        archetype = self.registry.get(comparison.archetype_id)
        if JudgePolicy(archetype.scorer_judge.judge_policy) is JudgePolicy.NONE:
            return ()
        return self.judge_panel

    def evaluation_contract_payload(self, comparison_id: str) -> dict[str, Any]:
        """Return the complete deterministic evaluation contract for one comparison."""

        comparison = self.comparison(comparison_id)
        archetype = self.registry.get(comparison.archetype_id)
        return {
            "contract_schema_version": "arisekit.program-evaluation-contract.v2",
            "program_schema_version": self.schema_version,
            "program_id": self.program_id,
            "registry_digest": self.registry_digest,
            "archetype": archetype.to_dict(),
            "comparison": comparison.to_dict(),
            "solver_panel": [value.to_dict() for value in self.solver_panel],
            "judge_panel": [
                value.to_dict() for value in self.judge_panel_for(comparison_id)
            ],
            "program_review_hash": self.program_review_hash,
        }

    def evaluation_contract_digest(self, comparison_id: str) -> str:
        """Hash the full scorer, judge, route, bundle, endpoint, and rule contract."""

        return _digest(self.evaluation_contract_payload(comparison_id))

    @property
    def comparison_cells(self) -> tuple[ComparisonCell, ...]:
        cells: list[ComparisonCell] = []
        for comparison in self.comparisons:
            evaluation_contract_hash = self.evaluation_contract_digest(
                comparison.comparison_id
            )
            judge_digest = _digest(
                [
                    value.to_dict()
                    for value in self.judge_panel_for(comparison.comparison_id)
                ]
            )
            for solver in self.solver_panel:
                payload = {
                    "program_schema_version": self.schema_version,
                    "program_id": self.program_id,
                    "registry_digest": self.registry_digest,
                    "comparison": comparison.to_dict(),
                    "solver": solver.to_dict(),
                    "judge_panel_digest": judge_digest,
                    "program_review_hash": self.program_review_hash,
                }
                suffix = _digest(payload)[:16]
                cell_id = f"{comparison.comparison_id}--{solver.route_id}--{suffix}"
                cells.append(
                    ComparisonCell(
                        cell_id=cell_id,
                        comparison_id=comparison.comparison_id,
                        archetype_id=ArchetypeId(comparison.archetype_id).value,
                        specialty_id=comparison.specialty_id,
                        solver_route_id=solver.route_id,
                        reference_bundle_hash=comparison.reference.bundle_hash,
                        synthetic_bundle_hash=comparison.synthetic.bundle_hash,
                        endpoint_id=comparison.endpoint_id,
                        evaluation_contract_hash=evaluation_contract_hash,
                    )
                )
        return tuple(cells)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "program_id": self.program_id,
            "registry_digest": self.registry_digest,
            "comparisons": [value.to_dict() for value in self.comparisons],
            "solver_panel": [value.to_dict() for value in self.solver_panel],
            "judge_panel": [value.to_dict() for value in self.judge_panel],
            "program_review_hash": self.program_review_hash,
            "comparison_cells": [value.to_dict() for value in self.comparison_cells],
            "claim_scope": STRUCTURAL_CLAIM_SCOPE,
            "clinical_validity_status": CLINICAL_VALIDITY_STATUS,
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        registry: BenchmarkArchetypeRegistry,
    ) -> "SyntheticBenchmarkProgram":
        fields = {
            "schema_version",
            "program_id",
            "registry_digest",
            "comparisons",
            "solver_panel",
            "judge_panel",
            "program_review_hash",
            "comparison_cells",
            "claim_scope",
            "clinical_validity_status",
        }
        _fields(data, fields, "synthetic benchmark program")
        if data["registry_digest"] != registry.digest:
            raise ValueError("program registry digest does not match supplied registry")
        if data["claim_scope"] != STRUCTURAL_CLAIM_SCOPE:
            raise ValueError("program claim scope is not structural parity research")
        if data["clinical_validity_status"] != CLINICAL_VALIDITY_STATUS:
            raise ValueError("program cannot serialize clinical validity")
        result = cls(
            schema_version=data["schema_version"],
            program_id=data["program_id"],
            registry=registry,
            comparisons=tuple(
                SyntheticComparison.from_dict(value) for value in data["comparisons"]
            ),
            solver_panel=tuple(
                ModelRoute.from_dict(value) for value in data["solver_panel"]
            ),
            judge_panel=tuple(
                ModelRoute.from_dict(value) for value in data["judge_panel"]
            ),
            program_review_hash=data["program_review_hash"],
        )
        expected_cells = [value.to_dict() for value in result.comparison_cells]
        if data["comparison_cells"] != expected_cells:
            raise ValueError(
                "serialized comparison cells do not match bound program inputs"
            )
        return result


SPECIALTY_IDS = (
    "cardiology",
    "emergency-medicine",
    "primary-internal-medicine",
    "obstetrics-gynecology",
    "neurology",
    "psychiatry",
    "endocrinology",
    "rheumatology",
    "oncology",
    "pain-medicine",
    "adolescent-medicine",
    "reproductive-care",
    "maternal-medicine",
    "geriatrics",
)

SPECIALTY_ARCHETYPE_ADAPTER = MappingProxyType(
    {
        "noharm": ArchetypeId.NOHARM,
        "paired-specialty-equity": ArchetypeId.PAIRED_EQUITY,
    }
)


def registry_archetype_id_for_specialty(value: str | Enum) -> ArchetypeId:
    """Map the specialty allocator vocabulary to the comparison registry."""

    raw = value.value if isinstance(value, Enum) else value
    if not isinstance(raw, str):
        raise ValueError("specialty archetype must be text or a string enum")
    try:
        return SPECIALTY_ARCHETYPE_ADAPTER[raw]
    except KeyError as exc:
        raise ValueError(
            f"specialty archetype {raw!r} has no comparison-registry adapter"
        ) from exc


def builtin_archetype_registry() -> BenchmarkArchetypeRegistry:
    """Return the reviewed initial registry as a new immutable value."""

    return BenchmarkArchetypeRegistry(
        registry_id="mast-clinical-archetypes-2026-07",
        specialties=SPECIALTY_IDS,
        archetypes=(
            _noharm_archetype(),
            _sct_archetype(),
            _medagentbench_archetype(),
            _rexrank_archetype(),
            _cpc_archetype(),
            _paired_equity_archetype(),
        ),
    )


def _noharm_archetype() -> BenchmarkArchetype:
    return BenchmarkArchetype(
        archetype_id=ArchetypeId.NOHARM,
        name="NOHARM rubric safety",
        required_inputs=(
            _input(
                "base-cases", InputKind.CASE_DATA, True, "Specialty case presentations."
            ),
            _input(
                "atomic-actions",
                InputKind.ACTION_RUBRIC,
                True,
                "Bipolar action rubrics with dependencies and alternatives.",
            ),
            _input(
                "matching-guidance",
                InputKind.JUDGE_GUIDANCE,
                True,
                "Aliases, gates, disqualifiers, and review guidance.",
            ),
            _input(
                "source-references",
                InputKind.EXPERT_REFERENCE,
                True,
                "Evidence for clinically appropriate management.",
            ),
        ),
        scorer_judge=ScorerJudgeContract(
            scorer_id="noharm-staged-action-scoring",
            stages=(
                "action-match",
                "deterministic-rules",
                "ambiguity-review",
                "override",
                "severity",
            ),
            item_score_fields=("precision", "recall", "f1", "severity-weighted-f1"),
            judge_policy=JudgePolicy.REQUIRED,
            judge_output_fields=("matches", "reviewed-overrides", "severity"),
            aggregation_unit="base-case",
            description="Stage action matching before deterministic aggregation and base-case bootstrap.",
        ),
        topology=BenchmarkTopology(
            execution_mode=ExecutionMode.SINGLE_TURN,
            input_modalities=("text",),
            item_hierarchy=("specialty", "base-case", "variant", "trial"),
            family_shape="baseline-plus-invariant-perturbations",
            fixed_variants_per_family=11,
            variant_selection_policy=(
                VariantSelectionPolicy.BASELINE_PLUS_PERTURBATION_SUBSET
            ),
            canonical_evaluated_variants_per_family=5,
            requires_checkpoint_per_turn=False,
        ),
        invariant_fields=_invariants(
            ("response-contract", "benchmark", "Identical response instructions."),
            ("action-semantics", "base-case", "Atomic action meanings remain fixed."),
            (
                "perturbation-answer",
                "variant",
                "Perturbations preserve the correct management.",
            ),
            (
                "judge-pipeline",
                "program",
                "Both arms use the same staged judge assets.",
            ),
        ),
        parity_endpoints=(
            _endpoint(
                "severity-weighted-f1-level",
                "severity-weighted-f1",
                "Difference in base-case aggregated score.",
                MarginUnit.ABSOLUTE_SCORE,
                (0.0, 1.0),
            ),
            _endpoint(
                "centered-model-profile",
                "centered-model-profile-distance",
                "Distance between centered solver performance profiles.",
                MarginUnit.PROFILE_DISTANCE,
                None,
                lower=True,
            ),
        ),
        applicability=_uniform_applicability(SpecialtySupport.SUPPORTED),
        permitted_reference_access=tuple(ReferenceAccessClass),
    )


def _sct_archetype() -> BenchmarkArchetype:
    return BenchmarkArchetype(
        archetype_id=ArchetypeId.SCT,
        name="SCT expert concordance",
        required_inputs=(
            _input(
                "uncertain-scenarios",
                InputKind.CASE_DATA,
                True,
                "Clinical scenarios with a proposed hypothesis or action.",
            ),
            _input(
                "expert-distributions",
                InputKind.EXPERT_REFERENCE,
                True,
                "Locked expert response distributions for each item.",
            ),
        ),
        scorer_judge=ScorerJudgeContract(
            scorer_id="sct-expert-concordance",
            stages=("response-normalization", "expert-concordance"),
            item_score_fields=("concordance",),
            judge_policy=JudgePolicy.NONE,
            judge_output_fields=(),
            aggregation_unit="item",
            description="Score the selected ordinal response against the frozen expert distribution.",
        ),
        topology=BenchmarkTopology(
            execution_mode=ExecutionMode.SINGLE_TURN,
            input_modalities=("text",),
            item_hierarchy=("specialty", "scenario", "item", "trial"),
            family_shape="scenario-hypothesis-evidence",
            fixed_variants_per_family=None,
            variant_selection_policy=VariantSelectionPolicy.VARIABLE,
            canonical_evaluated_variants_per_family=None,
            requires_checkpoint_per_turn=False,
        ),
        invariant_fields=_invariants(
            ("ordinal-scale", "benchmark", "Both arms use the same response scale."),
            (
                "expert-weighting",
                "program",
                "Expert concordance weights are computed identically.",
            ),
            (
                "scenario-uncertainty",
                "item",
                "Items test decisions under uncertainty rather than recall.",
            ),
        ),
        parity_endpoints=(
            _endpoint(
                "expert-concordance-level",
                "concordance",
                "Difference in mean expert-concordance score.",
                MarginUnit.ABSOLUTE_SCORE,
                (0.0, 1.0),
            ),
            _endpoint(
                "centered-model-profile",
                "centered-model-profile-distance",
                "Distance between centered solver performance profiles.",
                MarginUnit.PROFILE_DISTANCE,
                None,
                lower=True,
            ),
        ),
        applicability=_uniform_applicability(SpecialtySupport.SUPPORTED),
        permitted_reference_access=tuple(ReferenceAccessClass),
    )


def _medagentbench_archetype() -> BenchmarkArchetype:
    requirements = ("executable-tool-sandbox", "state-transition-oracle")
    return BenchmarkArchetype(
        archetype_id=ArchetypeId.MEDAGENTBENCH,
        name="MedAgentBench agentic clinical tasks",
        required_inputs=(
            _input(
                "task-prompts",
                InputKind.CASE_DATA,
                True,
                "Clinically scoped task requests.",
            ),
            _input(
                "tool-sandbox",
                InputKind.TOOL_SANDBOX,
                False,
                "Isolated tools with fixed schemas and fixtures.",
            ),
            _input(
                "state-oracle",
                InputKind.STATE_ORACLE,
                True,
                "Expected terminal state and prohibited transitions.",
            ),
        ),
        scorer_judge=ScorerJudgeContract(
            scorer_id="agentic-state-transition",
            stages=(
                "trajectory-validation",
                "terminal-state-check",
                "safety-adjudication",
            ),
            item_score_fields=("task-success", "prohibited-transition", "turn-count"),
            judge_policy=JudgePolicy.ADJUDICATION_ONLY,
            judge_output_fields=("safety-adjudication",),
            aggregation_unit="task",
            description="Score tool trajectory and terminal state; use review only for ambiguous safety events.",
        ),
        topology=BenchmarkTopology(
            execution_mode=ExecutionMode.AGENTIC,
            input_modalities=("text", "tools"),
            item_hierarchy=("specialty", "task", "turn"),
            family_shape="task-tool-trajectory",
            fixed_variants_per_family=None,
            variant_selection_policy=VariantSelectionPolicy.VARIABLE,
            canonical_evaluated_variants_per_family=None,
            requires_checkpoint_per_turn=True,
        ),
        invariant_fields=_invariants(
            ("tool-schema", "program", "Both arms expose identical tool contracts."),
            ("initial-state", "task", "Initial sandbox state is fixed and reset."),
            (
                "terminal-oracle",
                "task",
                "Success and prohibited states have identical meaning.",
            ),
        ),
        parity_endpoints=(
            _endpoint(
                "task-success-rate",
                "task-success",
                "Difference in successful terminal-state rate.",
                MarginUnit.RATE_DIFFERENCE,
                (0.0, 1.0),
            ),
            _endpoint(
                "unsafe-transition-rate",
                "prohibited-transition",
                "Difference in prohibited-transition rate.",
                MarginUnit.RATE_DIFFERENCE,
                (0.0, 1.0),
                lower=True,
            ),
        ),
        applicability=_uniform_applicability(
            SpecialtySupport.CONDITIONAL,
            requirement_ids=requirements,
            rationale="Requires an executable specialty workflow and a reviewed state oracle.",
        ),
        permitted_reference_access=tuple(ReferenceAccessClass),
    )


def _rexrank_archetype() -> BenchmarkArchetype:
    conditional = {
        specialty: SpecialtyApplicability(
            specialty_id=specialty,
            support=SpecialtySupport.CONDITIONAL,
            requirement_ids=("paired-clinical-images", "specialist-report-reference"),
            rationale="Requires a clinically relevant image modality and specialist-authored report reference.",
        )
        for specialty in SPECIALTY_IDS
        if specialty
        not in {
            "psychiatry",
            "endocrinology",
            "rheumatology",
            "pain-medicine",
            "adolescent-medicine",
        }
    }
    unsupported = {
        specialty: SpecialtyApplicability(
            specialty_id=specialty,
            support=SpecialtySupport.UNSUPPORTED,
            rationale="The initial registry has no reviewed image-report task definition for this specialty.",
        )
        for specialty in SPECIALTY_IDS
        if specialty not in conditional
    }
    applicability = tuple(
        (conditional | unsupported)[specialty] for specialty in SPECIALTY_IDS
    )
    return BenchmarkArchetype(
        archetype_id=ArchetypeId.REXRANK,
        name="ReXrank multimodal report quality",
        required_inputs=(
            _input(
                "clinical-images",
                InputKind.CLINICAL_IMAGE,
                True,
                "Rights-cleared diagnostic images.",
            ),
            _input(
                "reference-reports",
                InputKind.REPORT_REFERENCE,
                True,
                "Specialist-authored findings and impression.",
            ),
            _input(
                "report-rubric",
                InputKind.ACTION_RUBRIC,
                True,
                "Finding, omission, and contradiction rubric.",
            ),
        ),
        scorer_judge=ScorerJudgeContract(
            scorer_id="multimodal-report-quality",
            stages=(
                "finding-extraction",
                "report-comparison",
                "critical-finding-review",
            ),
            item_score_fields=(
                "report-quality",
                "critical-finding-recall",
                "contradiction-rate",
            ),
            judge_policy=JudgePolicy.REQUIRED,
            judge_output_fields=("matched-findings", "omissions", "contradictions"),
            aggregation_unit="study",
            description="Compare generated and reference findings with critical-error review.",
        ),
        topology=BenchmarkTopology(
            execution_mode=ExecutionMode.MULTIMODAL,
            input_modalities=("text", "image"),
            item_hierarchy=("specialty", "study", "image", "trial"),
            family_shape="image-context-report",
            fixed_variants_per_family=None,
            variant_selection_policy=VariantSelectionPolicy.VARIABLE,
            canonical_evaluated_variants_per_family=None,
            requires_checkpoint_per_turn=False,
        ),
        invariant_fields=_invariants(
            (
                "image-fidelity",
                "study",
                "Images are not altered between scoring paths.",
            ),
            (
                "report-sections",
                "benchmark",
                "Both arms use the same report response contract.",
            ),
            (
                "criticality-rules",
                "program",
                "Critical-finding rules and judges are frozen.",
            ),
        ),
        parity_endpoints=(
            _endpoint(
                "report-quality-level",
                "report-quality",
                "Difference in study-level report quality.",
                MarginUnit.ABSOLUTE_SCORE,
                (0.0, 1.0),
            ),
            _endpoint(
                "critical-finding-recall",
                "critical-finding-recall",
                "Difference in critical-finding recall.",
                MarginUnit.RATE_DIFFERENCE,
                (0.0, 1.0),
            ),
        ),
        applicability=applicability,
        permitted_reference_access=tuple(ReferenceAccessClass),
    )


def _cpc_archetype() -> BenchmarkArchetype:
    return BenchmarkArchetype(
        archetype_id=ArchetypeId.CPC,
        name="CPC diagnostic reasoning",
        required_inputs=(
            _input(
                "diagnostic-cases",
                InputKind.CASE_DATA,
                True,
                "Cases with staged clinical evidence.",
            ),
            _input(
                "final-diagnoses",
                InputKind.DIAGNOSTIC_OUTCOME,
                True,
                "Adjudicated final diagnoses.",
            ),
            _input(
                "differential-references",
                InputKind.DIFFERENTIAL_REFERENCE,
                True,
                "Expert differential and evidence links.",
            ),
        ),
        scorer_judge=ScorerJudgeContract(
            scorer_id="diagnostic-ranking",
            stages=(
                "diagnosis-normalization",
                "rank-scoring",
                "reasoning-adjudication",
            ),
            item_score_fields=(
                "diagnosis-rank",
                "top-k-accuracy",
                "evidence-consistency",
            ),
            judge_policy=JudgePolicy.ADJUDICATION_ONLY,
            judge_output_fields=("evidence-consistency",),
            aggregation_unit="case",
            description="Score diagnosis ranking deterministically and adjudicate evidence consistency.",
        ),
        topology=BenchmarkTopology(
            execution_mode=ExecutionMode.SINGLE_TURN,
            input_modalities=("text",),
            item_hierarchy=("specialty", "case", "evidence-stage", "trial"),
            family_shape="staged-diagnostic-case",
            fixed_variants_per_family=None,
            variant_selection_policy=VariantSelectionPolicy.VARIABLE,
            canonical_evaluated_variants_per_family=None,
            requires_checkpoint_per_turn=False,
        ),
        invariant_fields=_invariants(
            (
                "diagnosis-vocabulary",
                "benchmark",
                "Diagnosis normalization is identical.",
            ),
            ("evidence-order", "case", "Evidence stages retain their clinical order."),
            ("rank-scoring", "program", "Both arms use the same rank metric."),
        ),
        parity_endpoints=(
            _endpoint(
                "diagnosis-rank-level",
                "diagnosis-rank",
                "Difference in mean normalized diagnosis-rank score.",
                MarginUnit.ABSOLUTE_SCORE,
                (0.0, 1.0),
            ),
            _endpoint(
                "top-k-diagnostic-accuracy",
                "top-k-accuracy",
                "Difference in top-k diagnostic accuracy.",
                MarginUnit.RATE_DIFFERENCE,
                (0.0, 1.0),
            ),
        ),
        applicability=_uniform_applicability(SpecialtySupport.SUPPORTED),
        permitted_reference_access=tuple(ReferenceAccessClass),
    )


def _paired_equity_archetype() -> BenchmarkArchetype:
    return BenchmarkArchetype(
        archetype_id=ArchetypeId.PAIRED_EQUITY,
        name="Paired clinical equity",
        required_inputs=(
            _input(
                "paired-cases",
                InputKind.CASE_DATA,
                True,
                "Case pairs with separately represented clinical and demographic variables.",
            ),
            _input(
                "own-reference-rubrics",
                InputKind.ACTION_RUBRIC,
                True,
                "Clinician-locked reference and safety rubric for each variant.",
            ),
            _input(
                "relationship-attestations",
                InputKind.EXPERT_REFERENCE,
                True,
                "Attested invariant, differentiated, or information-required relationship.",
            ),
            _input(
                "pair-judge-guidance",
                InputKind.JUDGE_GUIDANCE,
                True,
                "Response and pair-level review instructions.",
            ),
        ),
        scorer_judge=ScorerJudgeContract(
            scorer_id="paired-clinical-equity",
            stages=("response-review", "pair-review", "specialty-aggregation"),
            item_score_fields=(
                "absolute-quality",
                "severe-error",
                "unjustified-discordance",
                "correct-differentiation",
                "safe-information-seeking",
            ),
            judge_policy=JudgePolicy.REQUIRED,
            judge_output_fields=(
                "response-judgment",
                "pair-judgment",
                "severe-error-adjudication",
            ),
            aggregation_unit="case-pair",
            description=(
                "Score each response against its own reference before computing "
                "relationship-specific paired contrasts."
            ),
        ),
        topology=BenchmarkTopology(
            execution_mode=ExecutionMode.SINGLE_TURN,
            input_modalities=("text",),
            item_hierarchy=(
                "specialty",
                "relationship",
                "case-pair",
                "variant",
                "trial",
            ),
            family_shape="paired-reference-relationship",
            fixed_variants_per_family=2,
            variant_selection_policy=VariantSelectionPolicy.FIXED,
            canonical_evaluated_variants_per_family=2,
            requires_checkpoint_per_turn=False,
        ),
        invariant_fields=_invariants(
            (
                "relationship-label",
                "case-pair",
                "The clinical relationship is clinician-attested before model runs.",
            ),
            (
                "own-reference-scoring",
                "variant",
                "Each response is scored against its own clinical reference.",
            ),
            (
                "paired-analysis",
                "program",
                "Both arms use identical relationship-specific contrast rules.",
            ),
            (
                "representative-stress-separation",
                "benchmark",
                "Representative and targeted stress estimates remain separate.",
            ),
        ),
        parity_endpoints=(
            _endpoint(
                "invariant-unjustified-discordance",
                "unjustified-discordance",
                "Difference in unjustified discordance rate for invariant pairs.",
                MarginUnit.RATE_DIFFERENCE,
                (0.0, 1.0),
                lower=True,
            ),
            _endpoint(
                "differentiated-correct-rate",
                "correct-differentiation",
                "Difference in correct differentiation rate.",
                MarginUnit.RATE_DIFFERENCE,
                (0.0, 1.0),
            ),
            _endpoint(
                "information-seeking-rate",
                "safe-information-seeking",
                "Difference in safe information-seeking rate.",
                MarginUnit.RATE_DIFFERENCE,
                (0.0, 1.0),
            ),
            _endpoint(
                "severe-error-rate",
                "severe-error",
                "Difference in severe-error rate, reported with absolute rates.",
                MarginUnit.RATE_DIFFERENCE,
                (0.0, 1.0),
                lower=True,
            ),
        ),
        applicability=_uniform_applicability(SpecialtySupport.SUPPORTED),
        permitted_reference_access=tuple(ReferenceAccessClass),
    )


def _input(
    input_id: str,
    kind: InputKind,
    clinician_lock_required: bool,
    description: str,
) -> RequiredInput:
    return RequiredInput(
        input_id=input_id,
        kind=kind,
        description=description,
        clinician_lock_required=clinician_lock_required,
    )


def _endpoint(
    endpoint_id: str,
    metric: str,
    estimand: str,
    margin_unit: MarginUnit,
    bounded_range: tuple[float, float] | None,
    *,
    lower: bool = False,
) -> ParityEndpoint:
    return ParityEndpoint(
        endpoint_id=endpoint_id,
        metric=metric,
        estimand=estimand,
        direction=(
            EndpointDirection.LOWER_IS_BETTER
            if lower
            else EndpointDirection.HIGHER_IS_BETTER
        ),
        margin_unit=margin_unit,
        bounded_range=bounded_range,
    )


def _invariants(*values: tuple[str, str, str]) -> tuple[InvariantField, ...]:
    return tuple(
        InvariantField(field_id=field_id, scope=scope, description=description)
        for field_id, scope, description in values
    )


def _uniform_applicability(
    support: SpecialtySupport,
    *,
    requirement_ids: tuple[str, ...] = (),
    rationale: str = "The evaluation structure is authorable for this specialty.",
) -> tuple[SpecialtyApplicability, ...]:
    return tuple(
        SpecialtyApplicability(
            specialty_id=specialty,
            support=support,
            requirement_ids=requirement_ids,
            rationale=rationale,
        )
        for specialty in SPECIALTY_IDS
    )


def _text(name: str, value: Any) -> str:
    return text(value, name, no_outer_whitespace=True, placeholder=lambda v: v.casefold() in _PLACEHOLDERS)


def _identifier(name: str, value: Any) -> str:
    return identifier(value, name, _ID_RE, check_text=lambda v: _text(name, v))


def _identifier_tuple(name: str, values: Sequence[Any], *, minimum: int = 1) -> tuple[str, ...]:
    return checked_tuple(values, name, check=lambda v: _identifier(name, v), minimum=minimum, distinct=True)


def _typed_tuple(name: str, values: Sequence[Any], expected_type: type, *, minimum: int) -> tuple[Any, ...]:
    return checked_tuple(values, name, item_type=expected_type, minimum=minimum)


def _unique(values: Sequence[Any], key: Any, name: str) -> None:
    unique(values, name, key=key)


def _boolean(name: str, value: Any) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")


def _hash(name: str, value: Any) -> str:
    return sha256_hex(value, name)


def _finite(name: str, value: Any) -> float:
    return number(value, name)


def _family(value: str) -> str:
    _text("model family", value)
    return value.casefold()
