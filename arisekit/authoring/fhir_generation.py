"""Contracts for autonomous generation of FHIR agent benchmark candidates.

The generator is an untrusted proposer. It may write an instruction and a
declarative task specification, but it cannot act as the source of clinical
truth and it cannot mark its own output clinically valid. Ground truth must be
derived from a pinned FHIR state, an explicit rule included with the task, or a
machine-executable protocol. A fixed engineering gate then checks the compiled
candidate before it can be packaged for model evaluation.

Passing this gate means only that the candidate is reproducible and internally
testable. Human clinical validation remains a separate, later study.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from arisekit.common.jsonio import strict_canonical_json as _canonical_json
from arisekit.common.records import StrictCanonicalRecord
from arisekit.common.validate import identifier, sha256_hex, tuple_of, unique
from arisekit.types import BenchmarkItem


TASK_SPEC_SCHEMA_VERSION = "arisekit.autonomous-fhir-task.v1"
ENGINEERING_GATE_SCHEMA_VERSION = "arisekit.autonomous-fhir-gate.v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_FHIR_RESOURCE_RE = re.compile(r"^(?:\*|[A-Z][A-Za-z0-9]{1,63})$")


class TruthSourceKind(str, Enum):
    """Sources from which an automated compiler may derive gold behavior."""

    FHIR_STATE = "fhir-state"
    TASK_SUPPLIED_RULE = "task-supplied-rule"
    EXECUTABLE_PROTOCOL = "executable-protocol"


class TaskBranch(str, Enum):
    """Observable branch the generated case is designed to exercise."""

    READ_ONLY = "read-only"
    ACTION_REQUIRED = "action-required"
    NO_ACTION_REQUIRED = "no-action-required"
    CLARIFICATION_REQUIRED = "clarification-required"


class ConstraintPhase(str, Enum):
    """World-state view against which a constraint is evaluated."""

    INITIAL = "initial"
    TERMINAL = "terminal"
    DELTA = "delta"


class ConstraintOperator(str, Enum):
    """Whitelisted operators for deterministic task verification."""

    EXISTS = "exists"
    NOT_EXISTS = "not-exists"
    EQUALS = "equals"
    EQUIVALENT = "equivalent"
    CONTAINS = "contains"
    COUNT_EQUALS = "count-equals"
    DELTA_COUNT_EQUALS = "delta-count-equals"
    WITHIN_RANGE = "within-range"


class ResponseNormalizer(str, Enum):
    """Deterministic normalizers allowed in an engineering gold contract."""

    EXACT = "exact"
    CASEFOLD = "casefold"
    NUMERIC_TOLERANCE = "numeric-tolerance"
    UCUM = "ucum"
    FHIR_INSTANT = "fhir-instant"
    TERMINOLOGY_EQUIVALENCE = "terminology-equivalence"


class AutomatedCheckName(str, Enum):
    """Checks every generated candidate must pass before packaging."""

    SOURCE_RESOLUTION = "source-resolution"
    DETERMINISTIC_REPLAY = "deterministic-replay"
    ORACLE_SUCCESS = "oracle-success"
    NULL_AGENT_REJECTION = "null-agent-rejection"
    FORMAT_INVARIANCE = "format-invariance"
    SAFETY_MUTATION_SENSITIVITY = "safety-mutation-sensitivity"


class EngineeringStatus(str, Enum):
    """Possible outcomes of the automated gate.

    There is intentionally no clinically validated value.
    """

    ENGINEERING_CANDIDATE = "engineering-candidate"
    REJECTED = "rejected"


@dataclass(frozen=True)
class TruthSource:
    """One immutable, non-LLM authority used to compile expected behavior."""

    source_id: str
    kind: TruthSourceKind
    locator: str
    sha256: str

    def __post_init__(self) -> None:
        _identifier("source_id", self.source_id)
        object.__setattr__(self, "kind", TruthSourceKind(self.kind))
        _nonempty("locator", self.locator)
        _sha256("sha256", self.sha256)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "kind": self.kind.value,
            "locator": self.locator,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class SearchParameter:
    """One deterministic FHIR search parameter."""

    name: str
    value: str | int | float | bool

    def __post_init__(self) -> None:
        _nonempty("search parameter name", self.name)
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("search parameter value must be finite")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value}


@dataclass(frozen=True)
class EvidenceRequirement:
    """FHIR evidence the agent must obtain before it may finish the task."""

    evidence_id: str
    resource_type: str
    search_parameters: tuple[SearchParameter, ...]
    projection: str
    source_ids: tuple[str, ...]
    must_be_observed_by_agent: bool = True

    def __post_init__(self) -> None:
        _identifier("evidence_id", self.evidence_id)
        _resource_type(self.resource_type)
        _nonempty("projection", self.projection)
        params = _typed_tuple(
            "search_parameters", self.search_parameters, SearchParameter
        )
        _unique(params, lambda item: item.name, "search parameter names")
        object.__setattr__(self, "search_parameters", params)
        object.__setattr__(self, "source_ids", _source_ids(self.source_ids))
        if not isinstance(self.must_be_observed_by_agent, bool):
            raise TypeError("must_be_observed_by_agent must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "resource_type": self.resource_type,
            "search_parameters": [item.to_dict() for item in self.search_parameters],
            "projection": self.projection,
            "source_ids": list(self.source_ids),
            "must_be_observed_by_agent": self.must_be_observed_by_agent,
        }


@dataclass(frozen=True)
class StateConstraint:
    """One required or prohibited fact about the initial, terminal, or delta state."""

    constraint_id: str
    phase: ConstraintPhase
    resource_type: str
    selector: tuple[SearchParameter, ...]
    path: str
    operator: ConstraintOperator
    expected: Any
    source_ids: tuple[str, ...]
    critical: bool = False

    def __post_init__(self) -> None:
        _identifier("constraint_id", self.constraint_id)
        object.__setattr__(self, "phase", ConstraintPhase(self.phase))
        object.__setattr__(self, "operator", ConstraintOperator(self.operator))
        _resource_type(self.resource_type)
        _nonempty("path", self.path)
        selector = _typed_tuple("selector", self.selector, SearchParameter)
        _unique(selector, lambda item: item.name, "selector parameter names")
        object.__setattr__(self, "selector", selector)
        object.__setattr__(self, "source_ids", _source_ids(self.source_ids))
        _canonical_json(self.expected)
        if not isinstance(self.critical, bool):
            raise TypeError("critical must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "phase": self.phase.value,
            "resource_type": self.resource_type,
            "selector": [item.to_dict() for item in self.selector],
            "path": self.path,
            "operator": self.operator.value,
            "expected": _json_detach(self.expected),
            "source_ids": list(self.source_ids),
            "critical": self.critical,
        }


@dataclass(frozen=True)
class ResponseRequirement:
    """One deterministic requirement for the clinician-facing final response."""

    field_id: str
    value_type: str
    source_ids: tuple[str, ...]
    normalizer: ResponseNormalizer = ResponseNormalizer.EXACT
    tolerance: float | None = None
    required: bool = True

    def __post_init__(self) -> None:
        _identifier("field_id", self.field_id)
        object.__setattr__(self, "normalizer", ResponseNormalizer(self.normalizer))
        _nonempty("value_type", self.value_type)
        object.__setattr__(self, "source_ids", _source_ids(self.source_ids))
        if not isinstance(self.required, bool):
            raise TypeError("required must be a boolean")
        if self.normalizer == ResponseNormalizer.NUMERIC_TOLERANCE:
            if self.tolerance is None or not math.isfinite(self.tolerance):
                raise ValueError(
                    "numeric-tolerance response requirements need a finite tolerance"
                )
            if self.tolerance < 0:
                raise ValueError("response tolerance cannot be negative")
        elif self.tolerance is not None:
            raise ValueError(
                "response tolerance is valid only with numeric-tolerance normalization"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "value_type": self.value_type,
            "source_ids": list(self.source_ids),
            "normalizer": self.normalizer.value,
            "tolerance": self.tolerance,
            "required": self.required,
        }


@dataclass(frozen=True)
class GenerationLineage:
    """Pinned inputs needed to reproduce an autonomous generation event."""

    generator_model: str
    generator_family: str
    generator_prompt_sha256: str
    generation_code_sha256: str
    source_bundle_sha256s: tuple[str, ...]
    seed: int
    generated_at: str

    def __post_init__(self) -> None:
        _nonempty("generator_model", self.generator_model)
        _nonempty("generator_family", self.generator_family)
        _sha256("generator_prompt_sha256", self.generator_prompt_sha256)
        _sha256("generation_code_sha256", self.generation_code_sha256)
        bundle_hashes = tuple(sorted(self.source_bundle_sha256s))
        if not bundle_hashes:
            raise ValueError("source_bundle_sha256s must not be empty")
        for digest in bundle_hashes:
            _sha256("source bundle hash", digest)
        if len(set(bundle_hashes)) != len(bundle_hashes):
            raise ValueError("source_bundle_sha256s must be unique")
        object.__setattr__(self, "source_bundle_sha256s", bundle_hashes)
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TypeError("seed must be an integer")
        _rfc3339("generated_at", self.generated_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generator_model": self.generator_model,
            "generator_family": self.generator_family,
            "generator_prompt_sha256": self.generator_prompt_sha256,
            "generation_code_sha256": self.generation_code_sha256,
            "source_bundle_sha256s": list(self.source_bundle_sha256s),
            "seed": self.seed,
            "generated_at": self.generated_at,
        }


@dataclass(frozen=True)
class AutonomousFHIRTaskSpec(StrictCanonicalRecord):
    """Declarative, compiler-ready specification for one generated task."""

    task_id: str
    family_id: str
    capability: str
    branch: TaskBranch
    patient_id: str
    frozen_time: str
    instruction: str
    context: str
    truth_sources: tuple[TruthSource, ...]
    evidence_requirements: tuple[EvidenceRequirement, ...]
    required_outcomes: tuple[StateConstraint, ...]
    forbidden_outcomes: tuple[StateConstraint, ...]
    response_requirements: tuple[ResponseRequirement, ...]
    lineage: GenerationLineage
    schema_version: str = TASK_SPEC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != TASK_SPEC_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {TASK_SPEC_SCHEMA_VERSION!r}"
            )
        _identifier("task_id", self.task_id)
        _identifier("family_id", self.family_id)
        _nonempty("capability", self.capability)
        object.__setattr__(self, "branch", TaskBranch(self.branch))
        _identifier("patient_id", self.patient_id)
        _rfc3339("frozen_time", self.frozen_time)
        _nonempty("instruction", self.instruction)
        if not isinstance(self.context, str):
            raise TypeError("context must be a string")
        if not isinstance(self.lineage, GenerationLineage):
            raise TypeError("lineage must be a GenerationLineage")

        truth_sources = _typed_tuple("truth_sources", self.truth_sources, TruthSource)
        if not truth_sources:
            raise ValueError("truth_sources must not be empty")
        _unique(truth_sources, lambda item: item.source_id, "truth source IDs")
        object.__setattr__(self, "truth_sources", truth_sources)

        evidence = _typed_tuple(
            "evidence_requirements", self.evidence_requirements, EvidenceRequirement
        )
        required = _typed_tuple(
            "required_outcomes", self.required_outcomes, StateConstraint
        )
        forbidden = _typed_tuple(
            "forbidden_outcomes", self.forbidden_outcomes, StateConstraint
        )
        responses = _typed_tuple(
            "response_requirements", self.response_requirements, ResponseRequirement
        )
        _unique(evidence, lambda item: item.evidence_id, "evidence IDs")
        _unique(
            required + forbidden,
            lambda item: item.constraint_id,
            "constraint IDs",
        )
        _unique(responses, lambda item: item.field_id, "response field IDs")
        object.__setattr__(self, "evidence_requirements", evidence)
        object.__setattr__(self, "required_outcomes", required)
        object.__setattr__(self, "forbidden_outcomes", forbidden)
        object.__setattr__(self, "response_requirements", responses)

        known_sources = {item.source_id for item in truth_sources}
        for item in (*evidence, *required, *forbidden, *responses):
            unknown = set(item.source_ids) - known_sources
            if unknown:
                raise ValueError(
                    f"{type(item).__name__} references unknown truth sources: "
                    f"{sorted(unknown)}"
                )

        if self.branch in {
            TaskBranch.NO_ACTION_REQUIRED,
            TaskBranch.CLARIFICATION_REQUIRED,
        } and not any(item.must_be_observed_by_agent for item in evidence):
            raise ValueError(
                f"{self.branch.value} tasks require agent-observed evidence so an "
                "empty finish cannot pass"
            )
        if self.branch == TaskBranch.ACTION_REQUIRED:
            if not required:
                raise ValueError("action-required tasks need a required outcome")
            if not any(item.critical for item in forbidden):
                raise ValueError(
                    "action-required tasks need at least one critical forbidden outcome"
                )
        if self.branch in {TaskBranch.READ_ONLY, TaskBranch.NO_ACTION_REQUIRED}:
            if not responses:
                raise ValueError(
                    f"{self.branch.value} tasks need a deterministic response requirement"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "family_id": self.family_id,
            "capability": self.capability,
            "branch": self.branch.value,
            "patient_id": self.patient_id,
            "frozen_time": self.frozen_time,
            "instruction": self.instruction,
            "context": self.context,
            "truth_sources": [item.to_dict() for item in self.truth_sources],
            "evidence_requirements": [
                item.to_dict() for item in self.evidence_requirements
            ],
            "required_outcomes": [item.to_dict() for item in self.required_outcomes],
            "forbidden_outcomes": [
                item.to_dict() for item in self.forbidden_outcomes
            ],
            "response_requirements": [
                item.to_dict() for item in self.response_requirements
            ],
            "lineage": self.lineage.to_dict(),
        }


@dataclass(frozen=True)
class AutomatedCheckResult:
    """Evidence for one fixed engineering check."""

    name: AutomatedCheckName
    passed: bool
    evidence_sha256: str
    details: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", AutomatedCheckName(self.name))
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be a boolean")
        _sha256("evidence_sha256", self.evidence_sha256)
        _nonempty("details", self.details)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name.value,
            "passed": self.passed,
            "evidence_sha256": self.evidence_sha256,
            "details": self.details,
        }


@dataclass(frozen=True)
class EngineeringGateResult(StrictCanonicalRecord):
    """Derived automated gate for one exact task specification."""

    task_spec_sha256: str
    checks: tuple[AutomatedCheckResult, ...]
    schema_version: str = ENGINEERING_GATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ENGINEERING_GATE_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {ENGINEERING_GATE_SCHEMA_VERSION!r}"
            )
        _sha256("task_spec_sha256", self.task_spec_sha256)
        checks = _typed_tuple("checks", self.checks, AutomatedCheckResult)
        _unique(checks, lambda item: item.name, "automated check names")
        expected = set(AutomatedCheckName)
        actual = {item.name for item in checks}
        if actual != expected:
            missing = sorted(item.value for item in expected - actual)
            extra = sorted(item.value for item in actual - expected)
            raise ValueError(
                f"checks must contain the exact engineering gate; missing={missing}, "
                f"extra={extra}"
            )
        object.__setattr__(
            self,
            "checks",
            tuple(sorted(checks, key=lambda item: item.name.value)),
        )

    @property
    def status(self) -> EngineeringStatus:
        if all(item.passed for item in self.checks):
            return EngineeringStatus.ENGINEERING_CANDIDATE
        return EngineeringStatus.REJECTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_spec_sha256": self.task_spec_sha256,
            "status": self.status.value,
            "clinical_validity": "not-established",
            "checks": [item.to_dict() for item in self.checks],
        }


def build_engineering_gate(
    task_spec: AutonomousFHIRTaskSpec,
    checks: tuple[AutomatedCheckResult, ...],
) -> EngineeringGateResult:
    """Bind automated check evidence to one exact generated task."""

    return EngineeringGateResult(task_spec_sha256=task_spec.digest, checks=checks)


def benchmark_item_from_candidate(
    task_spec: AutonomousFHIRTaskSpec,
    gate: EngineeringGateResult,
) -> BenchmarkItem:
    """Package a passing engineering candidate without a clinical-validity claim."""

    if gate.task_spec_sha256 != task_spec.digest:
        raise ValueError("engineering gate does not bind the supplied task specification")
    if gate.status != EngineeringStatus.ENGINEERING_CANDIDATE:
        raise ValueError("rejected candidates cannot become benchmark items")

    prompt = task_spec.instruction
    if task_spec.context.strip():
        prompt = f"{prompt}\n\nContext:\n{task_spec.context}"
    return BenchmarkItem(
        id=task_spec.task_id,
        prompt=prompt,
        metadata={
            "benchmark_pattern": "autonomous-fhir-agent",
            "family_id": task_spec.family_id,
            "capability": task_spec.capability,
            "branch": task_spec.branch.value,
            "patient_id": task_spec.patient_id,
            "frozen_time": task_spec.frozen_time,
            "task_spec_sha256": task_spec.digest,
            "engineering_gate_sha256": gate.digest,
            "generation_status": gate.status.value,
            "clinical_validity": "not-established",
            "human_validation_required": True,
        },
        ground_truth={
            "task_spec": task_spec.to_dict(),
            "engineering_gate": gate.to_dict(),
        },
    )


def _identifier(name: str, value: Any) -> str:
    return identifier(value, name, _ID_RE, check_text=lambda v: _nonempty(name, v))


def _resource_type(value: Any) -> str:
    text = _nonempty("resource_type", value)
    if not _FHIR_RESOURCE_RE.fullmatch(text):
        raise ValueError("resource_type must be a FHIR resource name or '*'")
    return text


def _nonempty(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _sha256(name: str, value: Any) -> str:
    return sha256_hex(value, name)


def _rfc3339(name: str, value: Any) -> str:
    text = _nonempty(name, value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return text


def _source_ids(values: Any) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not values:
        raise ValueError("source_ids must be a non-empty tuple")
    out = tuple(_identifier("source_id", item) for item in values)
    if len(set(out)) != len(out):
        raise ValueError("source_ids must be unique")
    return out


def _typed_tuple(name: str, values: Any, expected_type: type) -> tuple:
    return tuple_of(values, expected_type, name)


def _unique(values: tuple, key: Any, label: str) -> None:
    unique(values, label, key=key)


def _json_detach(value: Any) -> Any:
    return json.loads(_canonical_json(value))


__all__ = [
    "TASK_SPEC_SCHEMA_VERSION",
    "ENGINEERING_GATE_SCHEMA_VERSION",
    "TruthSourceKind",
    "TaskBranch",
    "ConstraintPhase",
    "ConstraintOperator",
    "ResponseNormalizer",
    "AutomatedCheckName",
    "EngineeringStatus",
    "TruthSource",
    "SearchParameter",
    "EvidenceRequirement",
    "StateConstraint",
    "ResponseRequirement",
    "GenerationLineage",
    "AutonomousFHIRTaskSpec",
    "AutomatedCheckResult",
    "EngineeringGateResult",
    "build_engineering_gate",
    "benchmark_item_from_candidate",
]
