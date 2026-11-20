"""Fail-closed contracts for target-specific stress benchmarks.

A stress benchmark is a regression artifact for one model snapshot. Acquisition
may use only exact discovery and calibration cohorts. Validation uses a sealed,
disjoint cohort and a preregistered decision rule. A terminal lifecycle is
derived from the bound validation evidence; it is never accepted as an
unverified caller assertion.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from arisekit.common.hashing import canonical_sha256 as _digest
from arisekit.common.records import CanonicalRecord
from arisekit.common.validate import number, sha256_hex


SCHEMA_VERSION = "arisekit.stress-benchmark-spec.v2"
VALIDATION_SCHEMA_VERSION = "arisekit.stress-validation-record.v2"
CLAIM_SCOPE = "target-specific-stress-only"


class StressLifecycle(str, Enum):
    EXPLORATORY = "exploratory"
    FROZEN = "frozen"
    VALIDATED = "validated"
    INVALID = "invalid"
    INCONCLUSIVE = "inconclusive"
    RETIRED = "retired"


class AcquisitionInputSplit(str, Enum):
    """Splits permitted to influence acquisition."""

    DISCOVERY = "discovery"
    CALIBRATION = "calibration"


class CohortRole(str, Enum):
    DISCOVERY = "discovery"
    CALIBRATION = "calibration"
    SEALED_VALIDATION = "sealed-validation"


class ResidualSignalRole(str, Enum):
    DISCOVERY = "discovery"
    HELDOUT_CONFIRMATION = "heldout-confirmation"


class MetricDirection(str, Enum):
    HIGHER_IS_FAILURE = "higher-is-failure"
    LOWER_IS_FAILURE = "lower-is-failure"


class ValidationEstimand(str, Enum):
    TARGET_SPECIFICITY_FAILURE_LIFT = "target-specificity-failure-lift"


class ConfidenceIntervalRule(str, Enum):
    """How confidence bounds map to terminal decisions."""

    TWO_SIDED_SEPARATION = "two-sided-separation"


class ConfidenceIntervalMethod(str, Enum):
    PAIRED_CLUSTER_BOOTSTRAP = "paired-cluster-bootstrap"


class ValidationResamplingUnit(str, Enum):
    CASE_CLUSTER = "case-cluster"


class MultiplicityMethod(str, Enum):
    NONE = "none"
    BONFERRONI = "bonferroni"


class StressValidationVerdict(str, Enum):
    VALIDATED = "validated"
    INVALID = "invalid"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class _TerminalProof:
    validation_record_hash: str
    lifecycle: StressLifecycle
    acquisition_digest: str


@dataclass(frozen=True)
class ModelSnapshot:
    model: str
    family: str
    snapshot: str

    def __post_init__(self) -> None:
        for name in ("model", "family", "snapshot"):
            _require_text(name, getattr(self, name))

    def to_dict(self) -> dict[str, str]:
        return {
            "model": self.model,
            "family": self.family,
            "snapshot": self.snapshot,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelSnapshot":
        fields = {"model", "family", "snapshot"}
        _require_fields(data, fields, "model snapshot")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True)
class CohortManifest(CanonicalRecord):
    """Exact membership for one immutable study cohort."""

    role: CohortRole
    item_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", CohortRole(self.role))
        hashes = _hash_tuple("cohort item_hashes", self.item_hashes)
        if not hashes:
            raise ValueError("cohort item_hashes must not be empty")
        if len(set(hashes)) != len(hashes):
            raise ValueError("cohort item_hashes must be unique")
        object.__setattr__(self, "item_hashes", tuple(sorted(hashes)))

    @property
    def item_count(self) -> int:
        return len(self.item_hashes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "item_count": self.item_count,
            "item_hashes": list(self.item_hashes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CohortManifest":
        fields = {"role", "item_count", "item_hashes"}
        _require_fields(data, fields, "cohort manifest")
        result = cls(
            role=CohortRole(data["role"]),
            item_hashes=tuple(data["item_hashes"]),
        )
        item_count = data["item_count"]
        if (
            isinstance(item_count, bool)
            or not isinstance(item_count, int)
            or item_count < 1
            or item_count != result.item_count
        ):
            raise ValueError("cohort item_count does not match exact membership")
        return result


@dataclass(frozen=True)
class ResidualSignalValidation(CanonicalRecord):
    """One residual-signal result against baselines and a permutation null."""

    role: ResidualSignalRole
    cohort_hash: str
    difficulty_baseline_comparison_hash: str
    ability_baseline_comparison_hash: str
    residualization_code_hash: str
    residual_signal_hash: str
    permutation_null_hash: str
    observed_residual_statistic: float
    permutation_draw_count: int
    permutation_exceedance_count: int
    tail_probability: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", ResidualSignalRole(self.role))
        for name in (
            "cohort_hash",
            "difficulty_baseline_comparison_hash",
            "ability_baseline_comparison_hash",
            "residualization_code_hash",
            "residual_signal_hash",
            "permutation_null_hash",
        ):
            _require_hash(name, getattr(self, name))
        if (
            self.difficulty_baseline_comparison_hash
            == self.ability_baseline_comparison_hash
        ):
            raise ValueError(
                "difficulty and ability baseline comparisons must be distinct"
            )
        statistic = _finite_number(
            "observed_residual_statistic", self.observed_residual_statistic
        )
        object.__setattr__(self, "observed_residual_statistic", statistic)
        if (
            isinstance(self.permutation_draw_count, bool)
            or not isinstance(self.permutation_draw_count, int)
            or self.permutation_draw_count < 1
        ):
            raise ValueError("permutation_draw_count must be a positive integer")
        if (
            isinstance(self.permutation_exceedance_count, bool)
            or not isinstance(self.permutation_exceedance_count, int)
            or self.permutation_exceedance_count < 0
            or self.permutation_exceedance_count > self.permutation_draw_count
        ):
            raise ValueError(
                "permutation_exceedance_count must be between zero and draw count"
            )
        probability = _closed_probability("tail_probability", self.tail_probability)
        expected_probability = (
            self.permutation_exceedance_count + 1
        ) / (self.permutation_draw_count + 1)
        if not math.isclose(
            probability, expected_probability, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError(
                "tail_probability must equal the finite-sample permutation estimate"
            )
        object.__setattr__(self, "tail_probability", probability)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "cohort_hash": self.cohort_hash,
            "difficulty_baseline_comparison_hash": (
                self.difficulty_baseline_comparison_hash
            ),
            "ability_baseline_comparison_hash": (
                self.ability_baseline_comparison_hash
            ),
            "residualization_code_hash": self.residualization_code_hash,
            "residual_signal_hash": self.residual_signal_hash,
            "permutation_null_hash": self.permutation_null_hash,
            "observed_residual_statistic": self.observed_residual_statistic,
            "permutation_draw_count": self.permutation_draw_count,
            "permutation_exceedance_count": self.permutation_exceedance_count,
            "tail_probability": self.tail_probability,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResidualSignalValidation":
        fields = {
            "role",
            "cohort_hash",
            "difficulty_baseline_comparison_hash",
            "ability_baseline_comparison_hash",
            "residualization_code_hash",
            "residual_signal_hash",
            "permutation_null_hash",
            "observed_residual_statistic",
            "permutation_draw_count",
            "permutation_exceedance_count",
            "tail_probability",
        }
        _require_fields(data, fields, "residual signal validation")
        return cls(
            role=ResidualSignalRole(data["role"]),
            cohort_hash=data["cohort_hash"],
            difficulty_baseline_comparison_hash=(
                data["difficulty_baseline_comparison_hash"]
            ),
            ability_baseline_comparison_hash=(
                data["ability_baseline_comparison_hash"]
            ),
            residualization_code_hash=data["residualization_code_hash"],
            residual_signal_hash=data["residual_signal_hash"],
            permutation_null_hash=data["permutation_null_hash"],
            observed_residual_statistic=data["observed_residual_statistic"],
            permutation_draw_count=data["permutation_draw_count"],
            permutation_exceedance_count=data["permutation_exceedance_count"],
            tail_probability=data["tail_probability"],
        )


@dataclass(frozen=True)
class AcquisitionEvidence(CanonicalRecord):
    """Discovery signal plus an independently hashed held-out confirmation."""

    discovery: ResidualSignalValidation
    heldout_confirmation: ResidualSignalValidation
    selection_policy_hash: str
    heldout_statistic_minimum: float
    heldout_tail_probability_maximum: float

    def __post_init__(self) -> None:
        if not isinstance(self.discovery, ResidualSignalValidation):
            raise ValueError("discovery must be ResidualSignalValidation")
        if not isinstance(self.heldout_confirmation, ResidualSignalValidation):
            raise ValueError(
                "heldout_confirmation must be ResidualSignalValidation"
            )
        if self.discovery.role is not ResidualSignalRole.DISCOVERY:
            raise ValueError("discovery signal must have discovery role")
        if (
            self.heldout_confirmation.role
            is not ResidualSignalRole.HELDOUT_CONFIRMATION
        ):
            raise ValueError(
                "heldout confirmation signal must have heldout-confirmation role"
            )
        if self.discovery.cohort_hash == self.heldout_confirmation.cohort_hash:
            raise ValueError(
                "discovery and held-out confirmation cohorts must differ"
            )
        if self.discovery.digest == self.heldout_confirmation.digest:
            raise ValueError(
                "discovery and held-out confirmation evidence must differ"
            )
        if (
            self.discovery.residualization_code_hash
            != self.heldout_confirmation.residualization_code_hash
        ):
            raise ValueError(
                "discovery and held-out confirmation must use the same "
                "residualization code"
            )
        if (
            self.discovery.permutation_null_hash
            == self.heldout_confirmation.permutation_null_hash
        ):
            raise ValueError(
                "discovery and held-out confirmation require distinct "
                "permutation-null artifacts"
            )
        _require_hash("selection_policy_hash", self.selection_policy_hash)
        minimum = _finite_number(
            "heldout_statistic_minimum", self.heldout_statistic_minimum
        )
        maximum_probability = _probability(
            "heldout_tail_probability_maximum",
            self.heldout_tail_probability_maximum,
        )
        object.__setattr__(self, "heldout_statistic_minimum", minimum)
        object.__setattr__(
            self,
            "heldout_tail_probability_maximum",
            maximum_probability,
        )
        if self.heldout_confirmation.observed_residual_statistic < minimum:
            raise ValueError(
                "held-out residual statistic does not meet preregistered minimum"
            )
        if self.heldout_confirmation.tail_probability > maximum_probability:
            raise ValueError(
                "held-out residual signal does not meet preregistered "
                "permutation threshold"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "discovery": self.discovery.to_dict(),
            "heldout_confirmation": self.heldout_confirmation.to_dict(),
            "selection_policy_hash": self.selection_policy_hash,
            "heldout_statistic_minimum": self.heldout_statistic_minimum,
            "heldout_tail_probability_maximum": (
                self.heldout_tail_probability_maximum
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AcquisitionEvidence":
        fields = {
            "discovery",
            "heldout_confirmation",
            "selection_policy_hash",
            "heldout_statistic_minimum",
            "heldout_tail_probability_maximum",
        }
        _require_fields(data, fields, "acquisition evidence")
        return cls(
            discovery=ResidualSignalValidation.from_dict(data["discovery"]),
            heldout_confirmation=ResidualSignalValidation.from_dict(
                data["heldout_confirmation"]
            ),
            selection_policy_hash=data["selection_policy_hash"],
            heldout_statistic_minimum=data["heldout_statistic_minimum"],
            heldout_tail_probability_maximum=(
                data["heldout_tail_probability_maximum"]
            ),
        )


@dataclass(frozen=True)
class AcquisitionLineage(CanonicalRecord):
    """Exact discovery and calibration inputs to stress-item acquisition."""

    discovery: CohortManifest
    calibration: CohortManifest
    evidence: AcquisitionEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.discovery, CohortManifest):
            raise ValueError("discovery must be CohortManifest")
        if not isinstance(self.calibration, CohortManifest):
            raise ValueError("calibration must be CohortManifest")
        if self.discovery.role is not CohortRole.DISCOVERY:
            raise ValueError("discovery cohort must have discovery role")
        if self.calibration.role is not CohortRole.CALIBRATION:
            raise ValueError("calibration cohort must have calibration role")
        overlap = set(self.discovery.item_hashes) & set(self.calibration.item_hashes)
        if overlap:
            raise ValueError("discovery and calibration cohorts must be disjoint")
        if not isinstance(self.evidence, AcquisitionEvidence):
            raise ValueError("evidence must be AcquisitionEvidence")
        if self.evidence.discovery.cohort_hash != self.discovery.digest:
            raise ValueError(
                "discovery residual signal does not match discovery cohort"
            )
        if (
            self.evidence.heldout_confirmation.cohort_hash
            != self.calibration.digest
        ):
            raise ValueError(
                "held-out residual confirmation does not match calibration cohort"
            )

    @property
    def acquisition_evidence_hash(self) -> str:
        return self.evidence.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "discovery": self.discovery.to_dict(),
            "calibration": self.calibration.to_dict(),
            "evidence": self.evidence.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AcquisitionLineage":
        fields = {"discovery", "calibration", "evidence"}
        _require_fields(data, fields, "acquisition lineage")
        return cls(
            discovery=CohortManifest.from_dict(data["discovery"]),
            calibration=CohortManifest.from_dict(data["calibration"]),
            evidence=AcquisitionEvidence.from_dict(data["evidence"]),
        )


@dataclass(frozen=True)
class JudgePanelMember:
    """One exact judge snapshot and its inference configuration."""

    id: str
    snapshot: ModelSnapshot
    role: str
    configuration_hash: str

    def __post_init__(self) -> None:
        _require_text("judge member id", self.id)
        if not isinstance(self.snapshot, ModelSnapshot):
            raise ValueError("judge member snapshot must be ModelSnapshot")
        _require_text("judge member role", self.role)
        _require_hash("judge member configuration_hash", self.configuration_hash)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "snapshot": self.snapshot.to_dict(),
            "role": self.role,
            "configuration_hash": self.configuration_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "JudgePanelMember":
        fields = {"id", "snapshot", "role", "configuration_hash"}
        _require_fields(data, fields, "judge panel member")
        return cls(
            id=data["id"],
            snapshot=ModelSnapshot.from_dict(data["snapshot"]),
            role=data["role"],
            configuration_hash=data["configuration_hash"],
        )


@dataclass(frozen=True)
class JudgePanel(CanonicalRecord):
    """Canonical judge membership plus panel-level configuration."""

    members: tuple[JudgePanelMember, ...]
    aggregation_method: str
    panel_configuration_hash: str

    def __post_init__(self) -> None:
        if isinstance(self.members, (str, bytes)):
            raise ValueError("judge panel members must be a sequence")
        members = tuple(self.members)
        if not members or not all(isinstance(member, JudgePanelMember) for member in members):
            raise ValueError("judge panel must contain JudgePanelMember values")
        ids = [member.id for member in members]
        if len(set(ids)) != len(ids):
            raise ValueError("judge panel member ids must be unique")
        snapshots = [
            (
                member.snapshot.model,
                member.snapshot.family,
                member.snapshot.snapshot,
            )
            for member in members
        ]
        if len(set(snapshots)) != len(snapshots):
            raise ValueError("judge panel member snapshots must be unique")
        object.__setattr__(self, "members", tuple(sorted(members, key=lambda member: member.id)))
        _require_text("judge panel aggregation_method", self.aggregation_method)
        _require_hash("judge panel panel_configuration_hash", self.panel_configuration_hash)

    def to_dict(self) -> dict[str, Any]:
        return {
            "members": [member.to_dict() for member in self.members],
            "aggregation_method": self.aggregation_method,
            "panel_configuration_hash": self.panel_configuration_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "JudgePanel":
        fields = {"members", "aggregation_method", "panel_configuration_hash"}
        _require_fields(data, fields, "judge panel")
        return cls(
            members=tuple(JudgePanelMember.from_dict(value) for value in data["members"]),
            aggregation_method=data["aggregation_method"],
            panel_configuration_hash=data["panel_configuration_hash"],
        )


@dataclass(frozen=True)
class SampleSizeRule:
    minimum_selected_n: int
    minimum_control_n: int
    require_equal_groups: bool = False

    def __post_init__(self) -> None:
        for name in ("minimum_selected_n", "minimum_control_n"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.require_equal_groups, bool):
            raise ValueError("require_equal_groups must be boolean")

    def is_satisfied(self, selected_n: int, control_n: int) -> bool:
        return (
            selected_n >= self.minimum_selected_n
            and control_n >= self.minimum_control_n
            and (not self.require_equal_groups or selected_n == control_n)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "minimum_selected_n": self.minimum_selected_n,
            "minimum_control_n": self.minimum_control_n,
            "require_equal_groups": self.require_equal_groups,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SampleSizeRule":
        fields = {
            "minimum_selected_n",
            "minimum_control_n",
            "require_equal_groups",
        }
        _require_fields(data, fields, "sample-size rule")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True)
class MultiplicityRule:
    method: MultiplicityMethod
    hypothesis_count: int
    hypothesis_family_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", MultiplicityMethod(self.method))
        if (
            isinstance(self.hypothesis_count, bool)
            or not isinstance(self.hypothesis_count, int)
            or self.hypothesis_count < 1
        ):
            raise ValueError("hypothesis_count must be a positive integer")
        if self.method is MultiplicityMethod.NONE and self.hypothesis_count != 1:
            raise ValueError("uncorrected validation requires hypothesis_count=1")
        _require_hash("hypothesis_family_hash", self.hypothesis_family_hash)

    def adjusted_confidence_level(self, nominal_confidence_level: float) -> float:
        if self.method is MultiplicityMethod.NONE:
            return nominal_confidence_level
        return 1.0 - ((1.0 - nominal_confidence_level) / self.hypothesis_count)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method.value,
            "hypothesis_count": self.hypothesis_count,
            "hypothesis_family_hash": self.hypothesis_family_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MultiplicityRule":
        fields = {"method", "hypothesis_count", "hypothesis_family_hash"}
        _require_fields(data, fields, "multiplicity rule")
        return cls(
            method=MultiplicityMethod(data["method"]),
            hypothesis_count=data["hypothesis_count"],
            hypothesis_family_hash=data["hypothesis_family_hash"],
        )


@dataclass(frozen=True)
class ValidationDecisionRule(CanonicalRecord):
    """Preregistered rule that deterministically maps evidence to a verdict."""

    metric: str
    metric_direction: MetricDirection
    estimand: ValidationEstimand
    validated_target_lift_minimum: float
    validated_specificity_minimum: float
    invalid_target_lift_maximum: float
    invalid_specificity_maximum: float
    nominal_confidence_level: float
    confidence_interval_rule: ConfidenceIntervalRule
    confidence_interval_method: ConfidenceIntervalMethod
    confidence_interval_draw_count: int
    resampling_unit: ValidationResamplingUnit
    sample_size: SampleSizeRule
    multiplicity: MultiplicityRule

    def __post_init__(self) -> None:
        _require_text("validation metric", self.metric)
        object.__setattr__(self, "metric_direction", MetricDirection(self.metric_direction))
        object.__setattr__(self, "estimand", ValidationEstimand(self.estimand))
        object.__setattr__(
            self,
            "confidence_interval_rule",
            ConfidenceIntervalRule(self.confidence_interval_rule),
        )
        object.__setattr__(
            self,
            "confidence_interval_method",
            ConfidenceIntervalMethod(self.confidence_interval_method),
        )
        object.__setattr__(
            self,
            "resampling_unit",
            ValidationResamplingUnit(self.resampling_unit),
        )
        if (
            isinstance(self.confidence_interval_draw_count, bool)
            or not isinstance(self.confidence_interval_draw_count, int)
            or self.confidence_interval_draw_count < 1
        ):
            raise ValueError(
                "confidence_interval_draw_count must be a positive integer"
            )
        for estimand in ("target_lift", "specificity"):
            validated_name = f"validated_{estimand}_minimum"
            invalid_name = f"invalid_{estimand}_maximum"
            validated = _finite_number(validated_name, getattr(self, validated_name))
            invalid = _finite_number(invalid_name, getattr(self, invalid_name))
            if invalid > validated:
                raise ValueError(
                    f"{invalid_name} cannot exceed {validated_name}"
                )
            object.__setattr__(self, validated_name, validated)
            object.__setattr__(self, invalid_name, invalid)
        confidence = _probability(
            "nominal_confidence_level", self.nominal_confidence_level
        )
        object.__setattr__(self, "nominal_confidence_level", confidence)
        if not isinstance(self.sample_size, SampleSizeRule):
            raise ValueError("sample_size must be SampleSizeRule")
        if not isinstance(self.multiplicity, MultiplicityRule):
            raise ValueError("multiplicity must be MultiplicityRule")

    @property
    def required_confidence_level(self) -> float:
        return self.multiplicity.adjusted_confidence_level(
            self.nominal_confidence_level
        )

    def decide(
        self,
        *,
        selected_n: int,
        control_n: int,
        target_lift_ci: tuple[float, float],
        target_specificity_ci: tuple[float, float],
    ) -> StressValidationVerdict:
        if not self.sample_size.is_satisfied(selected_n, control_n):
            return StressValidationVerdict.INCONCLUSIVE
        target_lower, target_upper = target_lift_ci
        specificity_lower, specificity_upper = target_specificity_ci
        if (
            target_lower >= self.validated_target_lift_minimum
            and specificity_lower >= self.validated_specificity_minimum
        ):
            return StressValidationVerdict.VALIDATED
        if (
            target_upper <= self.invalid_target_lift_maximum
            or specificity_upper <= self.invalid_specificity_maximum
        ):
            return StressValidationVerdict.INVALID
        return StressValidationVerdict.INCONCLUSIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "metric_direction": self.metric_direction.value,
            "estimand": self.estimand.value,
            "validated_target_lift_minimum": self.validated_target_lift_minimum,
            "validated_specificity_minimum": self.validated_specificity_minimum,
            "invalid_target_lift_maximum": self.invalid_target_lift_maximum,
            "invalid_specificity_maximum": self.invalid_specificity_maximum,
            "nominal_confidence_level": self.nominal_confidence_level,
            "required_confidence_level": self.required_confidence_level,
            "confidence_interval_rule": self.confidence_interval_rule.value,
            "confidence_interval_method": self.confidence_interval_method.value,
            "confidence_interval_draw_count": self.confidence_interval_draw_count,
            "resampling_unit": self.resampling_unit.value,
            "sample_size": self.sample_size.to_dict(),
            "multiplicity": self.multiplicity.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ValidationDecisionRule":
        fields = {
            "metric",
            "metric_direction",
            "estimand",
            "validated_target_lift_minimum",
            "validated_specificity_minimum",
            "invalid_target_lift_maximum",
            "invalid_specificity_maximum",
            "nominal_confidence_level",
            "required_confidence_level",
            "confidence_interval_rule",
            "confidence_interval_method",
            "confidence_interval_draw_count",
            "resampling_unit",
            "sample_size",
            "multiplicity",
        }
        _require_fields(data, fields, "validation decision rule")
        result = cls(
            metric=data["metric"],
            metric_direction=MetricDirection(data["metric_direction"]),
            estimand=ValidationEstimand(data["estimand"]),
            validated_target_lift_minimum=data[
                "validated_target_lift_minimum"
            ],
            validated_specificity_minimum=data[
                "validated_specificity_minimum"
            ],
            invalid_target_lift_maximum=data["invalid_target_lift_maximum"],
            invalid_specificity_maximum=data[
                "invalid_specificity_maximum"
            ],
            nominal_confidence_level=data["nominal_confidence_level"],
            confidence_interval_rule=ConfidenceIntervalRule(
                data["confidence_interval_rule"]
            ),
            confidence_interval_method=ConfidenceIntervalMethod(
                data["confidence_interval_method"]
            ),
            confidence_interval_draw_count=data[
                "confidence_interval_draw_count"
            ],
            resampling_unit=ValidationResamplingUnit(data["resampling_unit"]),
            sample_size=SampleSizeRule.from_dict(data["sample_size"]),
            multiplicity=MultiplicityRule.from_dict(data["multiplicity"]),
        )
        serialized_required_confidence = _probability(
            "required_confidence_level", data["required_confidence_level"]
        )
        if not math.isclose(
            serialized_required_confidence,
            result.required_confidence_level,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "required_confidence_level does not match multiplicity rule"
            )
        return result


@dataclass(frozen=True)
class MatchingControl:
    """Predeclared rule for selected-to-control matching."""

    method: str
    features: tuple[str, ...]
    reference_pool_hash: str
    controls_per_selected: int = 1
    maximum_distance: float | None = None
    require_disjoint: bool = False
    maximum_control_reuse: int = 1

    def __post_init__(self) -> None:
        _require_text("matching method", self.method)
        features = _text_tuple("matching features", self.features)
        if not features:
            raise ValueError("matching features must not be empty")
        if len(set(features)) != len(features):
            raise ValueError("matching features must be unique")
        object.__setattr__(self, "features", tuple(sorted(features)))
        _require_hash("reference_pool_hash", self.reference_pool_hash)
        for name in ("controls_per_selected", "maximum_control_reuse"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.maximum_distance is not None:
            value = _nonnegative_number("maximum_distance", self.maximum_distance)
            object.__setattr__(self, "maximum_distance", value)
        if not isinstance(self.require_disjoint, bool):
            raise ValueError("require_disjoint must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "features": list(self.features),
            "reference_pool_hash": self.reference_pool_hash,
            "controls_per_selected": self.controls_per_selected,
            "maximum_distance": self.maximum_distance,
            "require_disjoint": self.require_disjoint,
            "maximum_control_reuse": self.maximum_control_reuse,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MatchingControl":
        fields = {
            "method",
            "features",
            "reference_pool_hash",
            "controls_per_selected",
            "maximum_distance",
            "require_disjoint",
            "maximum_control_reuse",
        }
        _require_fields(data, fields, "matching control")
        return cls(
            method=data["method"],
            features=tuple(data["features"]),
            reference_pool_hash=data["reference_pool_hash"],
            controls_per_selected=data["controls_per_selected"],
            maximum_distance=data["maximum_distance"],
            require_disjoint=data["require_disjoint"],
            maximum_control_reuse=data["maximum_control_reuse"],
        )


@dataclass(frozen=True)
class FeatureDistance:
    feature: str
    value: float

    def __post_init__(self) -> None:
        _require_text("distance feature", self.feature)
        object.__setattr__(self, "value", _nonnegative_number("distance", self.value))

    def to_dict(self) -> dict[str, Any]:
        return {"feature": self.feature, "value": self.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FeatureDistance":
        _require_fields(data, {"feature", "value"}, "feature distance")
        return cls(feature=data["feature"], value=data["value"])


@dataclass(frozen=True)
class MatchedPair:
    selected_item_hash: str
    control_item_hash: str
    distances: tuple[FeatureDistance, ...]

    def __post_init__(self) -> None:
        _require_hash("selected_item_hash", self.selected_item_hash)
        _require_hash("control_item_hash", self.control_item_hash)
        if self.selected_item_hash == self.control_item_hash:
            raise ValueError("a matched pair cannot reuse the selected item as control")
        if isinstance(self.distances, (str, bytes)):
            raise ValueError("matched-pair distances must be a sequence")
        distances = tuple(self.distances)
        if not distances or not all(
            isinstance(distance, FeatureDistance) for distance in distances
        ):
            raise ValueError("matched-pair distances must contain FeatureDistance values")
        names = [distance.feature for distance in distances]
        if len(set(names)) != len(names):
            raise ValueError("matched-pair distance features must be unique")
        object.__setattr__(
            self, "distances", tuple(sorted(distances, key=lambda value: value.feature))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_item_hash": self.selected_item_hash,
            "control_item_hash": self.control_item_hash,
            "distances": [distance.to_dict() for distance in self.distances],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MatchedPair":
        fields = {"selected_item_hash", "control_item_hash", "distances"}
        _require_fields(data, fields, "matched pair")
        return cls(
            selected_item_hash=data["selected_item_hash"],
            control_item_hash=data["control_item_hash"],
            distances=tuple(
                FeatureDistance.from_dict(value) for value in data["distances"]
            ),
        )


@dataclass(frozen=True)
class MatchedCohortDiagnostics:
    selected_cohort_hash: str
    control_cohort_hash: str
    selected_count: int
    control_count: int
    calipers: tuple[FeatureDistance, ...]
    observed_maximum_distances: tuple[FeatureDistance, ...]
    selected_control_disjoint: bool
    maximum_control_reuse: int
    unmatched_selected_count: int

    def __post_init__(self) -> None:
        _require_hash("selected_cohort_hash", self.selected_cohort_hash)
        _require_hash("control_cohort_hash", self.control_cohort_hash)
        for name in (
            "selected_count",
            "control_count",
            "maximum_control_reuse",
            "unmatched_selected_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.selected_count < 1 or self.control_count < 1:
            raise ValueError("matched cohort counts must be positive")
        if self.maximum_control_reuse < 1:
            raise ValueError("maximum_control_reuse must be positive")
        if self.unmatched_selected_count > self.selected_count:
            raise ValueError("unmatched_selected_count cannot exceed selected_count")
        if not isinstance(self.selected_control_disjoint, bool):
            raise ValueError("selected_control_disjoint must be boolean")
        for name in ("calipers", "observed_maximum_distances"):
            values = tuple(getattr(self, name))
            if not values or not all(
                isinstance(value, FeatureDistance) for value in values
            ):
                raise ValueError(f"{name} must contain FeatureDistance values")
            features = [value.feature for value in values]
            if len(set(features)) != len(features):
                raise ValueError(f"{name} features must be unique")
            object.__setattr__(
                self, name, tuple(sorted(values, key=lambda value: value.feature))
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_cohort_hash": self.selected_cohort_hash,
            "control_cohort_hash": self.control_cohort_hash,
            "selected_count": self.selected_count,
            "control_count": self.control_count,
            "calipers": [value.to_dict() for value in self.calipers],
            "observed_maximum_distances": [
                value.to_dict() for value in self.observed_maximum_distances
            ],
            "selected_control_disjoint": self.selected_control_disjoint,
            "maximum_control_reuse": self.maximum_control_reuse,
            "unmatched_selected_count": self.unmatched_selected_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MatchedCohortDiagnostics":
        fields = {
            "selected_cohort_hash",
            "control_cohort_hash",
            "selected_count",
            "control_count",
            "calipers",
            "observed_maximum_distances",
            "selected_control_disjoint",
            "maximum_control_reuse",
            "unmatched_selected_count",
        }
        _require_fields(data, fields, "matched cohort diagnostics")
        return cls(
            selected_cohort_hash=data["selected_cohort_hash"],
            control_cohort_hash=data["control_cohort_hash"],
            selected_count=data["selected_count"],
            control_count=data["control_count"],
            calipers=tuple(FeatureDistance.from_dict(value) for value in data["calipers"]),
            observed_maximum_distances=tuple(
                FeatureDistance.from_dict(value)
                for value in data["observed_maximum_distances"]
            ),
            selected_control_disjoint=data["selected_control_disjoint"],
            maximum_control_reuse=data["maximum_control_reuse"],
            unmatched_selected_count=data["unmatched_selected_count"],
        )


@dataclass(frozen=True)
class MatchedCohortManifest(CanonicalRecord):
    """Exact selected/control membership, assignments, and checked diagnostics."""

    selected_item_hashes: tuple[str, ...]
    control_item_hashes: tuple[str, ...]
    pairs: tuple[MatchedPair, ...]
    diagnostics: MatchedCohortDiagnostics

    def __post_init__(self) -> None:
        selected = _unique_sorted_hashes(
            "selected_item_hashes", self.selected_item_hashes
        )
        controls = _unique_sorted_hashes("control_item_hashes", self.control_item_hashes)
        object.__setattr__(self, "selected_item_hashes", selected)
        object.__setattr__(self, "control_item_hashes", controls)
        if not isinstance(self.diagnostics, MatchedCohortDiagnostics):
            raise ValueError("diagnostics must be MatchedCohortDiagnostics")
        if isinstance(self.pairs, (str, bytes)):
            raise ValueError("pairs must be a sequence")
        pairs = tuple(self.pairs)
        if not pairs or not all(isinstance(pair, MatchedPair) for pair in pairs):
            raise ValueError("pairs must contain MatchedPair values")
        pair_keys = [
            (pair.selected_item_hash, pair.control_item_hash) for pair in pairs
        ]
        if len(set(pair_keys)) != len(pair_keys):
            raise ValueError("matched pairs must be unique")
        object.__setattr__(
            self,
            "pairs",
            tuple(
                sorted(
                    pairs,
                    key=lambda pair: (
                        pair.selected_item_hash,
                        pair.control_item_hash,
                    ),
                )
            ),
        )
        self._validate_intrinsic_diagnostics()

    @classmethod
    def create(
        cls,
        *,
        selected_item_hashes: Sequence[str],
        control_item_hashes: Sequence[str],
        pairs: Sequence[MatchedPair],
        matching_controls: Sequence[MatchingControl],
    ) -> "MatchedCohortManifest":
        selected = _unique_sorted_hashes(
            "selected_item_hashes", selected_item_hashes
        )
        controls = _unique_sorted_hashes("control_item_hashes", control_item_hashes)
        pair_values = tuple(pairs)
        if not pair_values or not all(
            isinstance(pair, MatchedPair) for pair in pair_values
        ):
            raise ValueError("pairs must contain MatchedPair values")
        _validate_matching_controls(matching_controls)
        calipers = _matching_calipers(matching_controls)
        observed = _observed_maximum_distances(pair_values)
        selected_with_matches = {pair.selected_item_hash for pair in pair_values}
        reuse = Counter(pair.control_item_hash for pair in pair_values)
        diagnostics = MatchedCohortDiagnostics(
            selected_cohort_hash=_member_digest("selected", selected),
            control_cohort_hash=_member_digest("control", controls),
            selected_count=len(selected),
            control_count=len(controls),
            calipers=tuple(
                FeatureDistance(feature, value)
                for feature, value in sorted(calipers.items())
            ),
            observed_maximum_distances=tuple(
                FeatureDistance(feature, value)
                for feature, value in sorted(observed.items())
            ),
            selected_control_disjoint=not bool(set(selected) & set(controls)),
            maximum_control_reuse=max(reuse.values(), default=0),
            unmatched_selected_count=len(set(selected) - selected_with_matches),
        )
        result = cls(
            selected_item_hashes=selected,
            control_item_hashes=controls,
            pairs=pair_values,
            diagnostics=diagnostics,
        )
        result.validate_against(matching_controls)
        return result

    def _validate_intrinsic_diagnostics(self) -> None:
        selected = set(self.selected_item_hashes)
        controls = set(self.control_item_hashes)
        for pair in self.pairs:
            if pair.selected_item_hash not in selected:
                raise ValueError("matched pair references an undeclared selected item")
            if pair.control_item_hash not in controls:
                raise ValueError("matched pair references an undeclared control item")
        used_controls = {pair.control_item_hash for pair in self.pairs}
        if used_controls != controls:
            raise ValueError("control_item_hashes must exactly match controls used by pairs")
        selected_with_matches = {pair.selected_item_hash for pair in self.pairs}
        reuse = Counter(pair.control_item_hash for pair in self.pairs)
        expected_values: dict[str, Any] = {
            "selected_cohort_hash": _member_digest(
                "selected", self.selected_item_hashes
            ),
            "control_cohort_hash": _member_digest(
                "control", self.control_item_hashes
            ),
            "selected_count": len(self.selected_item_hashes),
            "control_count": len(self.control_item_hashes),
            "selected_control_disjoint": not bool(selected & controls),
            "maximum_control_reuse": max(reuse.values(), default=0),
            "unmatched_selected_count": len(selected - selected_with_matches),
        }
        for name, expected in expected_values.items():
            if getattr(self.diagnostics, name) != expected:
                raise ValueError(f"matched cohort diagnostic {name} is not reproducible")
        observed = {
            value.feature: value.value
            for value in self.diagnostics.observed_maximum_distances
        }
        if observed != _observed_maximum_distances(self.pairs):
            raise ValueError(
                "matched cohort observed maximum distances are not reproducible"
            )

    def validate_against(self, controls: Sequence[MatchingControl]) -> None:
        """Validate assignments and diagnostics against preregistered controls."""
        controls_tuple = tuple(controls)
        if not controls_tuple or not all(
            isinstance(control, MatchingControl) for control in controls_tuple
        ):
            raise ValueError("matching controls must contain MatchingControl values")
        per_selected = {control.controls_per_selected for control in controls_tuple}
        if len(per_selected) != 1:
            raise ValueError(
                "matching controls must agree on controls_per_selected"
            )
        expected_per_selected = next(iter(per_selected))
        assignment_counts = Counter(pair.selected_item_hash for pair in self.pairs)
        if set(assignment_counts) != set(self.selected_item_hashes):
            raise ValueError("every selected item must have matched controls")
        if any(value != expected_per_selected for value in assignment_counts.values()):
            raise ValueError("matched-pair count violates controls_per_selected")

        feature_calipers = _matching_calipers(controls_tuple)
        actual_calipers = {
            value.feature: value.value for value in self.diagnostics.calipers
        }
        if actual_calipers != feature_calipers:
            raise ValueError("matched cohort calipers do not match matching controls")
        expected_features = set(feature_calipers)
        for pair in self.pairs:
            pair_distances = {
                distance.feature: distance.value for distance in pair.distances
            }
            if set(pair_distances) != expected_features:
                raise ValueError(
                    "matched pair distances must cover every matching feature exactly"
                )
            exceeded = [
                feature
                for feature, value in pair_distances.items()
                if value > feature_calipers[feature]
            ]
            if exceeded:
                raise ValueError(
                    "matched pair exceeds caliper for: " + ", ".join(sorted(exceeded))
                )
        if any(control.require_disjoint for control in controls_tuple):
            if not self.diagnostics.selected_control_disjoint:
                raise ValueError("matching rule requires disjoint selected and controls")
        maximum_reuse = min(
            control.maximum_control_reuse for control in controls_tuple
        )
        if self.diagnostics.maximum_control_reuse > maximum_reuse:
            raise ValueError("matched cohort exceeds maximum_control_reuse")

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_item_hashes": list(self.selected_item_hashes),
            "control_item_hashes": list(self.control_item_hashes),
            "pairs": [pair.to_dict() for pair in self.pairs],
            "diagnostics": self.diagnostics.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MatchedCohortManifest":
        fields = {
            "selected_item_hashes",
            "control_item_hashes",
            "pairs",
            "diagnostics",
        }
        _require_fields(data, fields, "matched cohort manifest")
        return cls(
            selected_item_hashes=tuple(data["selected_item_hashes"]),
            control_item_hashes=tuple(data["control_item_hashes"]),
            pairs=tuple(MatchedPair.from_dict(value) for value in data["pairs"]),
            diagnostics=MatchedCohortDiagnostics.from_dict(data["diagnostics"]),
        )


@dataclass(frozen=True)
class StressBenchmarkSpec(CanonicalRecord):
    """Frozen acquisition and validation contract for one target snapshot."""

    id: str
    target: ModelSnapshot
    acquisition_panel: tuple[ModelSnapshot, ...]
    excluded_lineages: tuple[str, ...]
    acquisition_panel_hash: str
    acquisition_lineage: AcquisitionLineage
    sealed_validation_cohort: CohortManifest
    discovery_split_hash: str
    calibration_split_hash: str
    sealed_validation_split_hash: str
    acquisition_evidence_hash: str
    acquisition_input_splits: tuple[AcquisitionInputSplit, ...]
    residualization_method: str
    acquisition_method: str
    difficulty_matching: MatchingControl
    source_matching: MatchingControl
    case_matching: MatchingControl
    prompt_hash: str
    rubric_hash: str
    judge_panel: JudgePanel
    judge_hash: str
    validation_rule: ValidationDecisionRule
    source_revision: str
    lifecycle: StressLifecycle = StressLifecycle.EXPLORATORY
    validation_record_hash: str | None = None
    claim_scope: str = CLAIM_SCOPE
    schema_version: str = SCHEMA_VERSION
    _terminal_proof: _TerminalProof | None = field(
        default=None, repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        _require_text("id", self.id)
        _require_text("residualization_method", self.residualization_method)
        _require_text("acquisition_method", self.acquisition_method)
        _require_text("source_revision", self.source_revision)
        object.__setattr__(self, "lifecycle", StressLifecycle(self.lifecycle))
        if not isinstance(self.target, ModelSnapshot):
            raise ValueError("target must be ModelSnapshot")
        for name in ("difficulty_matching", "source_matching", "case_matching"):
            if not isinstance(getattr(self, name), MatchingControl):
                raise ValueError(f"{name} must be MatchingControl")
        if not isinstance(self.acquisition_lineage, AcquisitionLineage):
            raise ValueError("acquisition_lineage must be AcquisitionLineage")
        if not isinstance(self.sealed_validation_cohort, CohortManifest):
            raise ValueError("sealed_validation_cohort must be CohortManifest")
        if self.sealed_validation_cohort.role is not CohortRole.SEALED_VALIDATION:
            raise ValueError(
                "sealed_validation_cohort must have sealed-validation role"
            )
        if not isinstance(self.judge_panel, JudgePanel):
            raise ValueError("judge_panel must be JudgePanel")
        if not isinstance(self.validation_rule, ValidationDecisionRule):
            raise ValueError("validation_rule must be ValidationDecisionRule")
        if (
            self.validation_rule.estimand
            is not ValidationEstimand.TARGET_SPECIFICITY_FAILURE_LIFT
        ):
            raise ValueError(
                "stress validation must use target-specificity failure lift"
            )

        panel = tuple(self.acquisition_panel)
        if not panel:
            raise ValueError("acquisition_panel must not be empty")
        if not all(isinstance(member, ModelSnapshot) for member in panel):
            raise ValueError("acquisition_panel must contain ModelSnapshot values")
        panel_keys = {
            (member.model, member.family, member.snapshot) for member in panel
        }
        if len(panel_keys) != len(panel):
            raise ValueError("acquisition_panel members must be unique")
        panel = tuple(
            sorted(panel, key=lambda member: (member.family, member.model, member.snapshot))
        )
        object.__setattr__(self, "acquisition_panel", panel)
        if self.acquisition_panel_hash != _model_panel_digest(panel):
            raise ValueError(
                "acquisition_panel_hash does not match canonical panel members"
            )

        excluded = _text_tuple("excluded_lineages", self.excluded_lineages)
        if not excluded:
            raise ValueError("excluded_lineages must not be empty")
        if len(set(excluded)) != len(excluded):
            raise ValueError("excluded_lineages must be unique")
        excluded = tuple(sorted(excluded))
        object.__setattr__(self, "excluded_lineages", excluded)
        if self.target.family not in excluded:
            raise ValueError("target family must be listed in excluded_lineages")
        leaked = sorted({member.family for member in panel} & set(excluded))
        if leaked:
            raise ValueError(
                f"acquisition_panel contains excluded model lineages: {', '.join(leaked)}"
            )
        if any(member.model == self.target.model for member in panel):
            raise ValueError("target model cannot appear in acquisition_panel")

        for name in (
            "acquisition_panel_hash",
            "discovery_split_hash",
            "calibration_split_hash",
            "sealed_validation_split_hash",
            "acquisition_evidence_hash",
            "prompt_hash",
            "rubric_hash",
            "judge_hash",
        ):
            _require_hash(name, getattr(self, name))
        if self.discovery_split_hash != self.acquisition_lineage.discovery.digest:
            raise ValueError(
                "discovery_split_hash does not match exact discovery cohort"
            )
        if self.calibration_split_hash != self.acquisition_lineage.calibration.digest:
            raise ValueError(
                "calibration_split_hash does not match exact calibration cohort"
            )
        if self.sealed_validation_split_hash != self.sealed_validation_cohort.digest:
            raise ValueError(
                "sealed_validation_split_hash does not match exact sealed cohort"
            )
        if (
            self.acquisition_evidence_hash
            != self.acquisition_lineage.acquisition_evidence_hash
        ):
            raise ValueError(
                "acquisition_evidence_hash does not match acquisition lineage"
            )
        acquisition_items = set(self.acquisition_lineage.discovery.item_hashes) | set(
            self.acquisition_lineage.calibration.item_hashes
        )
        sealed_overlap = acquisition_items & set(
            self.sealed_validation_cohort.item_hashes
        )
        if sealed_overlap:
            raise ValueError(
                "sealed validation cases cannot appear in acquisition cohorts"
            )
        split_hashes = {
            self.discovery_split_hash,
            self.calibration_split_hash,
            self.sealed_validation_split_hash,
        }
        if len(split_hashes) != 3:
            raise ValueError(
                "discovery, calibration, and sealed validation splits must differ"
            )
        if self.sealed_validation_split_hash in {
            self.acquisition_panel_hash,
            self.acquisition_evidence_hash,
        }:
            raise ValueError("sealed validation artifacts cannot be acquisition inputs")

        if isinstance(self.acquisition_input_splits, (str, bytes)):
            raise ValueError("acquisition_input_splits must be a sequence")
        input_splits = tuple(
            AcquisitionInputSplit(value) for value in self.acquisition_input_splits
        )
        required_splits = {
            AcquisitionInputSplit.DISCOVERY,
            AcquisitionInputSplit.CALIBRATION,
        }
        if set(input_splits) != required_splits or len(input_splits) != 2:
            raise ValueError(
                "acquisition_input_splits must contain exact discovery and calibration"
            )
        object.__setattr__(
            self,
            "acquisition_input_splits",
            (
                AcquisitionInputSplit.DISCOVERY,
                AcquisitionInputSplit.CALIBRATION,
            ),
        )

        if self.judge_hash != self.judge_panel.digest:
            raise ValueError("judge_hash does not match canonical judge panel")
        _validate_matching_controls(self.matching_controls)

        outcome_lifecycles = {
            StressLifecycle.VALIDATED,
            StressLifecycle.INVALID,
            StressLifecycle.INCONCLUSIVE,
        }
        if self.lifecycle in outcome_lifecycles:
            if self.validation_record_hash is None:
                raise ValueError(
                    f"{self.lifecycle.value} specs require a validation_record_hash"
                )
            _require_hash("validation_record_hash", self.validation_record_hash)
            expected_proof = _TerminalProof(
                validation_record_hash=self.validation_record_hash,
                lifecycle=self.lifecycle,
                acquisition_digest=self.acquisition_digest,
            )
            if self._terminal_proof != expected_proof:
                raise ValueError(
                    "terminal lifecycle requires a verified validation record; "
                    "use finalize_validation() or from_dict(..., validation_record=...)"
                )
        else:
            if self.validation_record_hash is not None:
                raise ValueError(
                    f"{self.lifecycle.value} specs cannot contain validation_record_hash"
                )
            if self._terminal_proof is not None:
                raise ValueError("non-terminal specs cannot contain terminal proof")
        if self.validation_record_hash is not None:
            forbidden_hashes = {
                self.acquisition_panel_hash,
                self.discovery_split_hash,
                self.calibration_split_hash,
                self.sealed_validation_split_hash,
                self.acquisition_evidence_hash,
            }
            if self.validation_record_hash in forbidden_hashes:
                raise ValueError(
                    "validation_record_hash cannot be reused as acquisition evidence"
                )

        if self.claim_scope != CLAIM_SCOPE:
            raise ValueError(f"claim_scope must be {CLAIM_SCOPE!r}")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION!r}")

    @property
    def matching_controls(self) -> tuple[MatchingControl, ...]:
        return (
            self.difficulty_matching,
            self.source_matching,
            self.case_matching,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "claim_scope": self.claim_scope,
            "id": self.id,
            "target": self.target.to_dict(),
            "acquisition_panel": [
                member.to_dict() for member in self.acquisition_panel
            ],
            "excluded_lineages": list(self.excluded_lineages),
            "acquisition_panel_hash": self.acquisition_panel_hash,
            "acquisition_lineage": self.acquisition_lineage.to_dict(),
            "sealed_validation_cohort": self.sealed_validation_cohort.to_dict(),
            "discovery_split_hash": self.discovery_split_hash,
            "calibration_split_hash": self.calibration_split_hash,
            "sealed_validation_split_hash": self.sealed_validation_split_hash,
            "acquisition_evidence_hash": self.acquisition_evidence_hash,
            "acquisition_input_splits": [
                split.value for split in self.acquisition_input_splits
            ],
            "residualization_method": self.residualization_method,
            "acquisition_method": self.acquisition_method,
            "difficulty_matching": self.difficulty_matching.to_dict(),
            "source_matching": self.source_matching.to_dict(),
            "case_matching": self.case_matching.to_dict(),
            "prompt_hash": self.prompt_hash,
            "rubric_hash": self.rubric_hash,
            "judge_panel": self.judge_panel.to_dict(),
            "judge_hash": self.judge_hash,
            "validation_rule": self.validation_rule.to_dict(),
            "source_revision": self.source_revision,
            "lifecycle": self.lifecycle.value,
            "validation_record_hash": self.validation_record_hash,
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        validation_record: StressValidationRecord | None = None,
    ) -> "StressBenchmarkSpec":
        fields = {
            "schema_version",
            "claim_scope",
            "id",
            "target",
            "acquisition_panel",
            "excluded_lineages",
            "acquisition_panel_hash",
            "acquisition_lineage",
            "sealed_validation_cohort",
            "discovery_split_hash",
            "calibration_split_hash",
            "sealed_validation_split_hash",
            "acquisition_evidence_hash",
            "acquisition_input_splits",
            "residualization_method",
            "acquisition_method",
            "difficulty_matching",
            "source_matching",
            "case_matching",
            "prompt_hash",
            "rubric_hash",
            "judge_panel",
            "judge_hash",
            "validation_rule",
            "source_revision",
            "lifecycle",
            "validation_record_hash",
        }
        _require_fields(data, fields, "stress benchmark spec")
        lifecycle = StressLifecycle(data["lifecycle"])
        proof: _TerminalProof | None = None
        outcome_lifecycles = {
            StressLifecycle.VALIDATED,
            StressLifecycle.INVALID,
            StressLifecycle.INCONCLUSIVE,
        }
        if lifecycle in outcome_lifecycles:
            if validation_record is None:
                raise ValueError(
                    "terminal stress specs require the bound validation_record"
                )
            if data["validation_record_hash"] != validation_record.digest:
                raise ValueError(
                    "serialized validation_record_hash does not match record"
                )
            if lifecycle is not validation_record.lifecycle:
                raise ValueError(
                    "serialized lifecycle does not match derived validation verdict"
                )
            proof = _TerminalProof(
                validation_record_hash=validation_record.digest,
                lifecycle=lifecycle,
                acquisition_digest=validation_record.spec_digest,
            )
        result = cls(
            id=data["id"],
            target=ModelSnapshot.from_dict(data["target"]),
            acquisition_panel=tuple(
                ModelSnapshot.from_dict(member)
                for member in data["acquisition_panel"]
            ),
            excluded_lineages=tuple(data["excluded_lineages"]),
            acquisition_panel_hash=data["acquisition_panel_hash"],
            acquisition_lineage=AcquisitionLineage.from_dict(
                data["acquisition_lineage"]
            ),
            sealed_validation_cohort=CohortManifest.from_dict(
                data["sealed_validation_cohort"]
            ),
            discovery_split_hash=data["discovery_split_hash"],
            calibration_split_hash=data["calibration_split_hash"],
            sealed_validation_split_hash=data["sealed_validation_split_hash"],
            acquisition_evidence_hash=data["acquisition_evidence_hash"],
            acquisition_input_splits=tuple(
                AcquisitionInputSplit(value)
                for value in data["acquisition_input_splits"]
            ),
            residualization_method=data["residualization_method"],
            acquisition_method=data["acquisition_method"],
            difficulty_matching=MatchingControl.from_dict(
                data["difficulty_matching"]
            ),
            source_matching=MatchingControl.from_dict(data["source_matching"]),
            case_matching=MatchingControl.from_dict(data["case_matching"]),
            prompt_hash=data["prompt_hash"],
            rubric_hash=data["rubric_hash"],
            judge_panel=JudgePanel.from_dict(data["judge_panel"]),
            judge_hash=data["judge_hash"],
            validation_rule=ValidationDecisionRule.from_dict(
                data["validation_rule"]
            ),
            source_revision=data["source_revision"],
            lifecycle=lifecycle,
            validation_record_hash=data["validation_record_hash"],
            claim_scope=data["claim_scope"],
            schema_version=data["schema_version"],
            _terminal_proof=proof,
        )
        if validation_record is not None:
            validation_record.validate_against(result)
        return result

    @property
    def acquisition_digest(self) -> str:
        """Identity stable across the later validation lifecycle transition."""
        payload = self.to_dict()
        payload.pop("lifecycle")
        payload.pop("validation_record_hash")
        return _digest(payload)

    def finalize_validation(
        self, record: StressValidationRecord
    ) -> "StressBenchmarkSpec":
        """Return the lifecycle transition derived from sealed evidence."""
        if self.lifecycle is not StressLifecycle.FROZEN:
            raise ValueError("only a frozen stress spec can be finalized")
        if not isinstance(record, StressValidationRecord):
            raise ValueError("record must be StressValidationRecord")
        record.validate_evidence_against(self)
        payload = self.to_dict()
        payload["lifecycle"] = record.lifecycle.value
        payload["validation_record_hash"] = record.digest
        return self.from_dict(payload, validation_record=record)


@dataclass(frozen=True)
class StressValidationRecord(CanonicalRecord):
    """Sealed evidence whose verdict is computed from its decision rule."""

    spec_digest: str
    sealed_validation_split_hash: str
    target: ModelSnapshot
    comparison_panel_hash: str
    comparison_panel_results_hash: str
    judge_panel_hash: str
    decision_rule: ValidationDecisionRule
    matched_cohort: MatchedCohortManifest
    metric: str
    metric_direction: MetricDirection
    selected_n: int
    control_n: int
    target_selected_mean: float
    target_control_mean: float
    panel_selected_mean: float
    panel_control_mean: float
    target_lift_ci: tuple[float, float]
    target_specificity_ci: tuple[float, float]
    confidence_level: float
    confidence_interval_artifact_hash: str
    analysis_hash: str
    claim_scope: str = CLAIM_SCOPE
    schema_version: str = VALIDATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "spec_digest",
            "sealed_validation_split_hash",
            "comparison_panel_hash",
            "comparison_panel_results_hash",
            "judge_panel_hash",
            "confidence_interval_artifact_hash",
            "analysis_hash",
        ):
            _require_hash(name, getattr(self, name))
        if not isinstance(self.target, ModelSnapshot):
            raise ValueError("target must be ModelSnapshot")
        if not isinstance(self.decision_rule, ValidationDecisionRule):
            raise ValueError("decision_rule must be ValidationDecisionRule")
        if not isinstance(self.matched_cohort, MatchedCohortManifest):
            raise ValueError("matched_cohort must be MatchedCohortManifest")
        _require_text("metric", self.metric)
        object.__setattr__(
            self, "metric_direction", MetricDirection(self.metric_direction)
        )
        if self.metric != self.decision_rule.metric:
            raise ValueError("metric does not match preregistered decision rule")
        if self.metric_direction is not self.decision_rule.metric_direction:
            raise ValueError(
                "metric_direction does not match preregistered decision rule"
            )
        for name in ("selected_n", "control_n"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.selected_n != len(self.matched_cohort.selected_item_hashes):
            raise ValueError("selected_n does not match matched cohort membership")
        if self.control_n != len(self.matched_cohort.control_item_hashes):
            raise ValueError("control_n does not match matched cohort membership")
        for name in (
            "target_selected_mean",
            "target_control_mean",
            "panel_selected_mean",
            "panel_control_mean",
        ):
            object.__setattr__(
                self, name, _finite_number(name, getattr(self, name))
            )
        for name in ("target_lift_ci", "target_specificity_ci"):
            object.__setattr__(
                self, name, _confidence_interval(name, getattr(self, name))
            )
        confidence = _probability("confidence_level", self.confidence_level)
        if not math.isclose(
            confidence,
            self.decision_rule.required_confidence_level,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "confidence_level does not match preregistered multiplicity rule"
            )
        object.__setattr__(self, "confidence_level", confidence)
        if not _interval_contains(self.target_lift_ci, self.target_failure_lift):
            raise ValueError("target_lift_ci does not contain target failure lift")
        if not _interval_contains(
            self.target_specificity_ci, self.target_specificity_lift
        ):
            raise ValueError(
                "target_specificity_ci does not contain target-specificity lift"
            )
        if self.claim_scope != CLAIM_SCOPE:
            raise ValueError(f"claim_scope must be {CLAIM_SCOPE!r}")
        if self.schema_version != VALIDATION_SCHEMA_VERSION:
            raise ValueError("unsupported stress validation record schema")

    @property
    def target_failure_lift(self) -> float:
        return self._failure_lift(
            self.target_selected_mean, self.target_control_mean
        )

    @property
    def panel_failure_lift(self) -> float:
        return self._failure_lift(
            self.panel_selected_mean, self.panel_control_mean
        )

    @property
    def target_specificity_lift(self) -> float:
        return self.target_failure_lift - self.panel_failure_lift

    def _failure_lift(self, selected: float, control: float) -> float:
        raw = selected - control
        if self.metric_direction is MetricDirection.LOWER_IS_FAILURE:
            raw = -raw
        return raw

    @property
    def verdict(self) -> StressValidationVerdict:
        return self.decision_rule.decide(
            selected_n=self.selected_n,
            control_n=self.control_n,
            target_lift_ci=self.target_lift_ci,
            target_specificity_ci=self.target_specificity_ci,
        )

    @property
    def lifecycle(self) -> StressLifecycle:
        return {
            StressValidationVerdict.VALIDATED: StressLifecycle.VALIDATED,
            StressValidationVerdict.INVALID: StressLifecycle.INVALID,
            StressValidationVerdict.INCONCLUSIVE: StressLifecycle.INCONCLUSIVE,
        }[self.verdict]

    def validate_evidence_against(self, spec: StressBenchmarkSpec) -> None:
        """Bind sealed evidence to the frozen acquisition specification."""
        if self.spec_digest != spec.acquisition_digest:
            raise ValueError(
                "validation record spec_digest does not match stress spec"
            )
        if self.sealed_validation_split_hash != spec.sealed_validation_split_hash:
            raise ValueError(
                "validation record sealed split does not match stress spec"
            )
        if self.target != spec.target:
            raise ValueError("validation record target does not match stress spec")
        if self.comparison_panel_hash != spec.acquisition_panel_hash:
            raise ValueError(
                "validation record comparison panel does not match stress spec"
            )
        if self.judge_panel_hash != spec.judge_hash:
            raise ValueError(
                "validation record judge panel does not match stress spec"
            )
        if self.decision_rule != spec.validation_rule:
            raise ValueError(
                "validation record decision rule does not match stress spec"
            )
        self.matched_cohort.validate_against(spec.matching_controls)
        matched_items = set(self.matched_cohort.selected_item_hashes) | set(
            self.matched_cohort.control_item_hashes
        )
        if matched_items != set(spec.sealed_validation_cohort.item_hashes):
            raise ValueError(
                "matched selected/control membership must exactly partition "
                "the sealed validation cohort"
            )

    def validate_against(self, spec: StressBenchmarkSpec) -> None:
        """Validate evidence and its derived lifecycle transition."""
        self.validate_evidence_against(spec)
        if spec.lifecycle is not self.lifecycle:
            raise ValueError(
                "stress spec lifecycle does not match derived validation verdict"
            )
        if spec.validation_record_hash != self.digest:
            raise ValueError(
                "stress spec validation_record_hash does not match record"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "claim_scope": self.claim_scope,
            "spec_digest": self.spec_digest,
            "sealed_validation_split_hash": self.sealed_validation_split_hash,
            "target": self.target.to_dict(),
            "comparison_panel_hash": self.comparison_panel_hash,
            "comparison_panel_results_hash": self.comparison_panel_results_hash,
            "judge_panel_hash": self.judge_panel_hash,
            "decision_rule": self.decision_rule.to_dict(),
            "matched_cohort": self.matched_cohort.to_dict(),
            "metric": self.metric,
            "metric_direction": self.metric_direction.value,
            "selected_n": self.selected_n,
            "control_n": self.control_n,
            "target_selected_mean": self.target_selected_mean,
            "target_control_mean": self.target_control_mean,
            "panel_selected_mean": self.panel_selected_mean,
            "panel_control_mean": self.panel_control_mean,
            "target_lift_ci": list(self.target_lift_ci),
            "target_specificity_ci": list(self.target_specificity_ci),
            "confidence_level": self.confidence_level,
            "confidence_interval_artifact_hash": (
                self.confidence_interval_artifact_hash
            ),
            "verdict": self.verdict.value,
            "analysis_hash": self.analysis_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StressValidationRecord":
        fields = {
            "schema_version",
            "claim_scope",
            "spec_digest",
            "sealed_validation_split_hash",
            "target",
            "comparison_panel_hash",
            "comparison_panel_results_hash",
            "judge_panel_hash",
            "decision_rule",
            "matched_cohort",
            "metric",
            "metric_direction",
            "selected_n",
            "control_n",
            "target_selected_mean",
            "target_control_mean",
            "panel_selected_mean",
            "panel_control_mean",
            "target_lift_ci",
            "target_specificity_ci",
            "confidence_level",
            "confidence_interval_artifact_hash",
            "verdict",
            "analysis_hash",
        }
        _require_fields(data, fields, "stress validation record")
        result = cls(
            spec_digest=data["spec_digest"],
            sealed_validation_split_hash=data["sealed_validation_split_hash"],
            target=ModelSnapshot.from_dict(data["target"]),
            comparison_panel_hash=data["comparison_panel_hash"],
            comparison_panel_results_hash=data[
                "comparison_panel_results_hash"
            ],
            judge_panel_hash=data["judge_panel_hash"],
            decision_rule=ValidationDecisionRule.from_dict(
                data["decision_rule"]
            ),
            matched_cohort=MatchedCohortManifest.from_dict(
                data["matched_cohort"]
            ),
            metric=data["metric"],
            metric_direction=MetricDirection(data["metric_direction"]),
            selected_n=data["selected_n"],
            control_n=data["control_n"],
            target_selected_mean=data["target_selected_mean"],
            target_control_mean=data["target_control_mean"],
            panel_selected_mean=data["panel_selected_mean"],
            panel_control_mean=data["panel_control_mean"],
            target_lift_ci=tuple(data["target_lift_ci"]),
            target_specificity_ci=tuple(data["target_specificity_ci"]),
            confidence_level=data["confidence_level"],
            confidence_interval_artifact_hash=(
                data["confidence_interval_artifact_hash"]
            ),
            analysis_hash=data["analysis_hash"],
            claim_scope=data["claim_scope"],
            schema_version=data["schema_version"],
        )
        if data["verdict"] != result.verdict.value:
            raise ValueError(
                "serialized verdict does not match decision-rule result"
            )
        return result


def _validate_matching_controls(controls: Sequence[MatchingControl]) -> None:
    controls_tuple = tuple(controls)
    if not controls_tuple or not all(
        isinstance(control, MatchingControl) for control in controls_tuple
    ):
        raise ValueError("matching controls must contain MatchingControl values")
    per_selected = {control.controls_per_selected for control in controls_tuple}
    if len(per_selected) != 1:
        raise ValueError("matching controls must agree on controls_per_selected")
    _matching_calipers(controls_tuple)


def _matching_calipers(
    controls: Sequence[MatchingControl],
) -> dict[str, float]:
    calipers: dict[str, float] = {}
    for control in controls:
        if control.maximum_distance is None:
            raise ValueError(
                "every matching control requires maximum_distance for validation"
            )
        for feature in control.features:
            prior = calipers.get(feature)
            if prior is not None and not math.isclose(
                prior, control.maximum_distance, rel_tol=0.0, abs_tol=1e-12
            ):
                raise ValueError(
                    f"matching feature {feature!r} has conflicting calipers"
                )
            calipers[feature] = control.maximum_distance
    if not calipers:
        raise ValueError("matching controls must declare at least one feature")
    return calipers


def _observed_maximum_distances(
    pairs: Iterable[MatchedPair],
) -> dict[str, float]:
    maxima: dict[str, float] = {}
    for pair in pairs:
        for distance in pair.distances:
            maxima[distance.feature] = max(
                maxima.get(distance.feature, 0.0), distance.value
            )
    return maxima


def _model_panel_digest(panel: Sequence[ModelSnapshot]) -> str:
    return _digest([member.to_dict() for member in panel])


def _member_digest(label: str, hashes: Sequence[str]) -> str:
    return _digest({"role": label, "item_hashes": list(sorted(hashes))})


def _require_text(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _text_tuple(name: str, value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence of strings")
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be a sequence of strings") from exc
    for item in values:
        _require_text(name, item)
    return values


def _require_hash(name: str, value: Any) -> str:
    return sha256_hex(value, name)


def _hash_tuple(name: str, value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be a sequence") from exc
    for item in values:
        _require_hash(name, item)
    return values


def _unique_sorted_hashes(name: str, value: Any) -> tuple[str, ...]:
    hashes = _hash_tuple(name, value)
    if not hashes:
        raise ValueError(f"{name} must not be empty")
    if len(set(hashes)) != len(hashes):
        raise ValueError(f"{name} must be unique")
    return tuple(sorted(hashes))


def _finite_number(name: str, value: Any) -> float:
    return number(value, name)


def _nonnegative_number(name: str, value: Any) -> float:
    return number(value, name, minimum=0)


def _probability(name: str, value: Any) -> float:
    return number(value, name, exclusive_minimum=0, exclusive_maximum=1)


def _closed_probability(name: str, value: Any) -> float:
    result = _finite_number(name, value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1 inclusive")
    return result


def _confidence_interval(name: str, value: Any) -> tuple[float, float]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must contain lower and upper bounds")
    try:
        interval = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{name} must contain lower and upper bounds") from exc
    if len(interval) != 2:
        raise ValueError(f"{name} must contain lower and upper bounds")
    lower = _finite_number(f"{name} lower", interval[0])
    upper = _finite_number(f"{name} upper", interval[1])
    if lower > upper:
        raise ValueError(f"{name} lower bound cannot exceed upper bound")
    return (lower, upper)


def _interval_contains(interval: tuple[float, float], value: float) -> bool:
    return interval[0] <= value <= interval[1]


def _require_fields(data: Mapping[str, Any], fields: set[str], label: str) -> None:
    if not isinstance(data, Mapping):
        raise ValueError(f"{label} must be an object")
    present = set(data)
    missing = fields - present
    unknown = present - fields
    if missing or unknown:
        raise ValueError(
            f"invalid {label} fields; missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )


__all__ = [
    "AcquisitionEvidence",
    "AcquisitionInputSplit",
    "AcquisitionLineage",
    "CohortManifest",
    "CohortRole",
    "ConfidenceIntervalMethod",
    "ConfidenceIntervalRule",
    "FeatureDistance",
    "JudgePanel",
    "JudgePanelMember",
    "MatchedCohortDiagnostics",
    "MatchedCohortManifest",
    "MatchedPair",
    "MatchingControl",
    "MetricDirection",
    "ModelSnapshot",
    "MultiplicityMethod",
    "MultiplicityRule",
    "ResidualSignalRole",
    "ResidualSignalValidation",
    "SampleSizeRule",
    "StressBenchmarkSpec",
    "StressLifecycle",
    "StressValidationRecord",
    "StressValidationVerdict",
    "ValidationDecisionRule",
    "ValidationEstimand",
    "ValidationResamplingUnit",
]
