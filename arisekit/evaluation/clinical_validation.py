"""Frozen clinician-validation contracts and an evidence-derived release gate.

The clinical validation unit is one opaque review item. A frozen plan declares
the exact sampled items, their strata, and their clinician assignments before
observations are collected. The gate then compares evaluator labels with a
clinician consensus or an independent adjudication. Missing evidence is
inconclusive; complete evidence that misses a threshold is rejected.

No public API accepts a caller-supplied gate verdict.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from arisekit.common.jsonio import strict_json_object
from arisekit.common.records import StrictCanonicalRecord
from arisekit.common.validate import exact_fields as _fields, integer, number, sha256_hex, text, timestamp


PLAN_SCHEMA_VERSION = "arisekit.clinical-validation-plan.v1"
RESULTS_SCHEMA_VERSION = "arisekit.clinical-validation-results.v1"
ADJUDICATION_SCHEMA_VERSION = "arisekit.clinical-adjudication.v1"

SAMPLING_METHODS = ("complete-enumeration", "stratified-random")
COHORTS = ("representative", "stress")
RELATIONSHIPS = ("differentiated", "information-required", "invariant")

_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{5,127}$")
_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_PLACEHOLDER_RE = re.compile(
    r"^(?:tbd|todo|unknown|n/?a|none|null|placeholder|"
    r"fill(?:[- ]?me)?[- ]?in|not[- ]?set)$",
    re.IGNORECASE,
)


class ValidationVerdict(str, Enum):
    """Possible evidence-derived states of the clinical release gate."""

    ENGINEERING_ONLY = "engineering-only"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class _Canonical(StrictCanonicalRecord):
    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class StratificationCell(_Canonical):
    """One prespecified clinical stratum and its exact sampled item IDs."""

    cell_id: str
    specialty: str
    cohort: str
    relationship: str
    opaque_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text("cell_id", self.cell_id)
        _text("specialty", self.specialty)
        _choice("cohort", self.cohort, COHORTS)
        _choice("relationship", self.relationship, RELATIONSHIPS)
        opaque_ids = _opaque_ids("opaque_ids", self.opaque_ids)
        if not opaque_ids:
            raise ValueError("opaque_ids must contain at least one item")
        object.__setattr__(self, "opaque_ids", opaque_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "specialty": self.specialty,
            "cohort": self.cohort,
            "relationship": self.relationship,
            "opaque_ids": list(self.opaque_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StratificationCell":
        fields = {"cell_id", "specialty", "cohort", "relationship", "opaque_ids"}
        _fields(data, fields, "stratification cell")
        return cls(
            cell_id=data["cell_id"],
            specialty=data["specialty"],
            cohort=data["cohort"],
            relationship=data["relationship"],
            opaque_ids=_json_string_array("opaque_ids", data["opaque_ids"]),
        )


@dataclass(frozen=True)
class ClinicianAssignment(_Canonical):
    """Exact primary-clinician assignment for one opaque item."""

    opaque_id: str
    reviewer_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _opaque_id("opaque_id", self.opaque_id)
        reviewers = _distinct_texts("reviewer_ids", self.reviewer_ids)
        if not reviewers:
            raise ValueError("reviewer_ids must contain at least one reviewer")
        object.__setattr__(self, "reviewer_ids", reviewers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "opaque_id": self.opaque_id,
            "reviewer_ids": list(self.reviewer_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ClinicianAssignment":
        fields = {"opaque_id", "reviewer_ids"}
        _fields(data, fields, "clinician assignment")
        return cls(
            opaque_id=data["opaque_id"],
            reviewer_ids=_json_string_array("reviewer_ids", data["reviewer_ids"]),
        )


@dataclass(frozen=True)
class ClinicianSamplingPlan(_Canonical):
    """Frozen sampling method, clinician roster, and item assignments."""

    method: str
    selection_seed: int
    reviewer_ids: tuple[str, ...]
    reviewers_per_item: int
    assignments: tuple[ClinicianAssignment, ...]

    def __post_init__(self) -> None:
        _choice("method", self.method, SAMPLING_METHODS)
        _integer("selection_seed", self.selection_seed)
        reviewers = _distinct_texts("reviewer_ids", self.reviewer_ids)
        if len(reviewers) < 2:
            raise ValueError("reviewer_ids must contain at least two clinicians")
        object.__setattr__(self, "reviewer_ids", reviewers)
        _positive_integer("reviewers_per_item", self.reviewers_per_item)
        if self.reviewers_per_item < 2:
            raise ValueError("reviewers_per_item must be at least two")
        if self.reviewers_per_item > len(reviewers):
            raise ValueError("reviewers_per_item cannot exceed the reviewer roster")
        assignments = _typed_tuple(
            "assignments",
            self.assignments,
            ClinicianAssignment,
        )
        assignments = tuple(sorted(assignments, key=lambda item: item.opaque_id))
        _unique_by("assignments", assignments, lambda item: item.opaque_id)
        if not assignments:
            raise ValueError("assignments must contain at least one item")
        roster = set(reviewers)
        used_reviewers: set[str] = set()
        for assignment in assignments:
            if len(assignment.reviewer_ids) != self.reviewers_per_item:
                raise ValueError(
                    f"assignment {assignment.opaque_id!r} must contain exactly "
                    "reviewers_per_item reviewers"
                )
            unknown = set(assignment.reviewer_ids) - roster
            if unknown:
                raise ValueError(
                    f"assignment {assignment.opaque_id!r} contains reviewers "
                    f"outside the frozen roster: {sorted(unknown)}"
                )
            used_reviewers.update(assignment.reviewer_ids)
        if used_reviewers != roster:
            raise ValueError("every frozen reviewer must appear in an assignment")
        object.__setattr__(self, "assignments", assignments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "selection_seed": self.selection_seed,
            "reviewer_ids": list(self.reviewer_ids),
            "reviewers_per_item": self.reviewers_per_item,
            "assignments": [item.to_dict() for item in self.assignments],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ClinicianSamplingPlan":
        fields = {
            "method",
            "selection_seed",
            "reviewer_ids",
            "reviewers_per_item",
            "assignments",
        }
        _fields(data, fields, "clinician sampling plan")
        return cls(
            method=data["method"],
            selection_seed=data["selection_seed"],
            reviewer_ids=_json_string_array("reviewer_ids", data["reviewer_ids"]),
            reviewers_per_item=data["reviewers_per_item"],
            assignments=_json_objects(
                "assignments",
                data["assignments"],
                ClinicianAssignment.from_dict,
            ),
        )


@dataclass(frozen=True)
class CriterionThresholds(_Canonical):
    """Prespecified acceptance thresholds and minimum denominators."""

    minimum_agreement: float
    minimum_severe_error_sensitivity: float
    minimum_severe_error_specificity: float
    maximum_harmful_action_false_negative_rate: float
    maximum_critical_omission_false_negative_rate: float
    maximum_continuous_score_mae: float
    continuous_score_minimum: float
    continuous_score_maximum: float
    minimum_severe_error_positives: int
    minimum_severe_error_negatives: int
    minimum_harmful_action_positives: int
    minimum_critical_omission_positives: int

    def __post_init__(self) -> None:
        for name in (
            "minimum_agreement",
            "minimum_severe_error_sensitivity",
            "minimum_severe_error_specificity",
            "maximum_harmful_action_false_negative_rate",
            "maximum_critical_omission_false_negative_rate",
        ):
            object.__setattr__(self, name, _unit_interval(name, getattr(self, name)))
        score_minimum = _finite(
            "continuous_score_minimum",
            self.continuous_score_minimum,
        )
        score_maximum = _finite(
            "continuous_score_maximum",
            self.continuous_score_maximum,
        )
        if score_minimum >= score_maximum:
            raise ValueError(
                "continuous_score_minimum must be less than "
                "continuous_score_maximum"
            )
        object.__setattr__(self, "continuous_score_minimum", score_minimum)
        object.__setattr__(self, "continuous_score_maximum", score_maximum)
        maximum_mae = _finite(
            "maximum_continuous_score_mae",
            self.maximum_continuous_score_mae,
        )
        if maximum_mae < 0 or maximum_mae > score_maximum - score_minimum:
            raise ValueError(
                "maximum_continuous_score_mae must be between zero and the "
                "continuous score range"
            )
        object.__setattr__(self, "maximum_continuous_score_mae", maximum_mae)
        for name in (
            "minimum_severe_error_positives",
            "minimum_severe_error_negatives",
            "minimum_harmful_action_positives",
            "minimum_critical_omission_positives",
        ):
            _positive_integer(name, getattr(self, name))

    def to_dict(self) -> dict[str, Any]:
        return {
            "minimum_agreement": self.minimum_agreement,
            "minimum_severe_error_sensitivity": (
                self.minimum_severe_error_sensitivity
            ),
            "minimum_severe_error_specificity": (
                self.minimum_severe_error_specificity
            ),
            "maximum_harmful_action_false_negative_rate": (
                self.maximum_harmful_action_false_negative_rate
            ),
            "maximum_critical_omission_false_negative_rate": (
                self.maximum_critical_omission_false_negative_rate
            ),
            "maximum_continuous_score_mae": self.maximum_continuous_score_mae,
            "continuous_score_minimum": self.continuous_score_minimum,
            "continuous_score_maximum": self.continuous_score_maximum,
            "minimum_severe_error_positives": self.minimum_severe_error_positives,
            "minimum_severe_error_negatives": self.minimum_severe_error_negatives,
            "minimum_harmful_action_positives": (
                self.minimum_harmful_action_positives
            ),
            "minimum_critical_omission_positives": (
                self.minimum_critical_omission_positives
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CriterionThresholds":
        fields = {
            "minimum_agreement",
            "minimum_severe_error_sensitivity",
            "minimum_severe_error_specificity",
            "maximum_harmful_action_false_negative_rate",
            "maximum_critical_omission_false_negative_rate",
            "maximum_continuous_score_mae",
            "continuous_score_minimum",
            "continuous_score_maximum",
            "minimum_severe_error_positives",
            "minimum_severe_error_negatives",
            "minimum_harmful_action_positives",
            "minimum_critical_omission_positives",
        }
        _fields(data, fields, "criterion thresholds")
        return cls(**{field: data[field] for field in fields})


@dataclass(frozen=True)
class EscalationRules(_Canonical):
    """Prespecified evaluator-disagreement triggers and adjudicator roster.

    Any disagreement among primary clinicians is always escalated. The boolean
    fields control whether a disagreement between the evaluator and any primary
    clinician also requires adjudication.
    """

    adjudicator_ids: tuple[str, ...]
    adjudicators_per_item: int
    escalate_acceptability_disagreement: bool
    escalate_severe_error_disagreement: bool
    escalate_harmful_action_disagreement: bool
    escalate_critical_omission_disagreement: bool
    continuous_score_absolute_difference: float

    def __post_init__(self) -> None:
        adjudicators = _distinct_texts("adjudicator_ids", self.adjudicator_ids)
        if not adjudicators:
            raise ValueError("adjudicator_ids must contain at least one clinician")
        object.__setattr__(self, "adjudicator_ids", adjudicators)
        _positive_integer("adjudicators_per_item", self.adjudicators_per_item)
        if self.adjudicators_per_item > len(adjudicators):
            raise ValueError(
                "adjudicators_per_item cannot exceed the adjudicator roster"
            )
        for name in (
            "escalate_acceptability_disagreement",
            "escalate_severe_error_disagreement",
            "escalate_harmful_action_disagreement",
            "escalate_critical_omission_disagreement",
        ):
            _boolean(name, getattr(self, name))
        difference = _finite(
            "continuous_score_absolute_difference",
            self.continuous_score_absolute_difference,
        )
        if difference <= 0:
            raise ValueError(
                "continuous_score_absolute_difference must be positive"
            )
        object.__setattr__(
            self,
            "continuous_score_absolute_difference",
            difference,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjudicator_ids": list(self.adjudicator_ids),
            "adjudicators_per_item": self.adjudicators_per_item,
            "escalate_acceptability_disagreement": (
                self.escalate_acceptability_disagreement
            ),
            "escalate_severe_error_disagreement": (
                self.escalate_severe_error_disagreement
            ),
            "escalate_harmful_action_disagreement": (
                self.escalate_harmful_action_disagreement
            ),
            "escalate_critical_omission_disagreement": (
                self.escalate_critical_omission_disagreement
            ),
            "continuous_score_absolute_difference": (
                self.continuous_score_absolute_difference
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EscalationRules":
        fields = {
            "adjudicator_ids",
            "adjudicators_per_item",
            "escalate_acceptability_disagreement",
            "escalate_severe_error_disagreement",
            "escalate_harmful_action_disagreement",
            "escalate_critical_omission_disagreement",
            "continuous_score_absolute_difference",
        }
        _fields(data, fields, "escalation rules")
        return cls(
            adjudicator_ids=_json_string_array(
                "adjudicator_ids",
                data["adjudicator_ids"],
            ),
            **{field: data[field] for field in fields - {"adjudicator_ids"}},
        )


@dataclass(frozen=True)
class RandomAuditRules(_Canonical):
    """Deterministic within-cell audit selection applied after escalation."""

    fraction_per_cell: float
    minimum_per_cell: int
    random_seed: int

    def __post_init__(self) -> None:
        fraction = _unit_interval("fraction_per_cell", self.fraction_per_cell)
        object.__setattr__(self, "fraction_per_cell", fraction)
        _nonnegative_integer("minimum_per_cell", self.minimum_per_cell)
        _integer("random_seed", self.random_seed)
        if fraction == 0 and self.minimum_per_cell == 0:
            raise ValueError(
                "random audit must specify a positive fraction or minimum_per_cell"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fraction_per_cell": self.fraction_per_cell,
            "minimum_per_cell": self.minimum_per_cell,
            "random_seed": self.random_seed,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RandomAuditRules":
        fields = {"fraction_per_cell", "minimum_per_cell", "random_seed"}
        _fields(data, fields, "random audit rules")
        return cls(**{field: data[field] for field in fields})


@dataclass(frozen=True)
class FrozenValidationPlan(_Canonical):
    """Versioned, immutable clinical calibration and validation plan."""

    study_artifact_hash: str
    response_review_artifact_hash: str
    pair_review_artifact_hash: str
    stratification_cells: tuple[StratificationCell, ...]
    clinician_sampling: ClinicianSamplingPlan
    thresholds: CriterionThresholds
    escalation: EscalationRules
    random_audit: RandomAuditRules
    clinical_approver_id: str
    statistical_approver_id: str
    frozen_at: str
    schema_version: str = PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PLAN_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {PLAN_SCHEMA_VERSION!r}")
        for name in (
            "study_artifact_hash",
            "response_review_artifact_hash",
            "pair_review_artifact_hash",
        ):
            _hash(name, getattr(self, name))
        cells = _typed_tuple(
            "stratification_cells",
            self.stratification_cells,
            StratificationCell,
        )
        cells = tuple(sorted(cells, key=lambda cell: cell.cell_id))
        if not cells:
            raise ValueError("stratification_cells must contain at least one cell")
        _unique_by("stratification_cells", cells, lambda cell: cell.cell_id)
        _unique_by(
            "stratification cell definitions",
            cells,
            lambda cell: (cell.specialty, cell.cohort, cell.relationship),
        )
        all_opaque_ids = [opaque_id for cell in cells for opaque_id in cell.opaque_ids]
        if len(set(all_opaque_ids)) != len(all_opaque_ids):
            raise ValueError(
                "opaque IDs must appear in exactly one stratification cell"
            )
        object.__setattr__(self, "stratification_cells", cells)
        if not isinstance(self.clinician_sampling, ClinicianSamplingPlan):
            raise ValueError("clinician_sampling must be ClinicianSamplingPlan")
        if not isinstance(self.thresholds, CriterionThresholds):
            raise ValueError("thresholds must be CriterionThresholds")
        if not isinstance(self.escalation, EscalationRules):
            raise ValueError("escalation must be EscalationRules")
        if not isinstance(self.random_audit, RandomAuditRules):
            raise ValueError("random_audit must be RandomAuditRules")
        assigned = {
            assignment.opaque_id for assignment in self.clinician_sampling.assignments
        }
        sampled = set(all_opaque_ids)
        if assigned != sampled:
            raise ValueError(
                "clinician assignments must exactly cover sampled opaque IDs; "
                f"missing={sorted(sampled - assigned)}, "
                f"unknown={sorted(assigned - sampled)}"
            )
        overlap = set(self.clinician_sampling.reviewer_ids) & set(
            self.escalation.adjudicator_ids
        )
        if overlap:
            raise ValueError(
                "primary reviewers and adjudicators must be independent; "
                f"overlap={sorted(overlap)}"
            )
        _text("clinical_approver_id", self.clinical_approver_id)
        _text("statistical_approver_id", self.statistical_approver_id)
        if self.clinical_approver_id == self.statistical_approver_id:
            raise ValueError("clinical and statistical approvers must be distinct")
        _timestamp("frozen_at", self.frozen_at)

    @property
    def opaque_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                opaque_id
                for cell in self.stratification_cells
                for opaque_id in cell.opaque_ids
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "study_artifact_hash": self.study_artifact_hash,
            "response_review_artifact_hash": self.response_review_artifact_hash,
            "pair_review_artifact_hash": self.pair_review_artifact_hash,
            "stratification_cells": [
                cell.to_dict() for cell in self.stratification_cells
            ],
            "clinician_sampling": self.clinician_sampling.to_dict(),
            "thresholds": self.thresholds.to_dict(),
            "escalation": self.escalation.to_dict(),
            "random_audit": self.random_audit.to_dict(),
            "clinical_approver_id": self.clinical_approver_id,
            "statistical_approver_id": self.statistical_approver_id,
            "frozen_at": self.frozen_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FrozenValidationPlan":
        fields = {
            "schema_version",
            "study_artifact_hash",
            "response_review_artifact_hash",
            "pair_review_artifact_hash",
            "stratification_cells",
            "clinician_sampling",
            "thresholds",
            "escalation",
            "random_audit",
            "clinical_approver_id",
            "statistical_approver_id",
            "frozen_at",
        }
        _fields(data, fields, "frozen validation plan")
        return cls(
            schema_version=data["schema_version"],
            study_artifact_hash=data["study_artifact_hash"],
            response_review_artifact_hash=data["response_review_artifact_hash"],
            pair_review_artifact_hash=data["pair_review_artifact_hash"],
            stratification_cells=_json_objects(
                "stratification_cells",
                data["stratification_cells"],
                StratificationCell.from_dict,
            ),
            clinician_sampling=ClinicianSamplingPlan.from_dict(
                _mapping("clinician_sampling", data["clinician_sampling"])
            ),
            thresholds=CriterionThresholds.from_dict(
                _mapping("thresholds", data["thresholds"])
            ),
            escalation=EscalationRules.from_dict(
                _mapping("escalation", data["escalation"])
            ),
            random_audit=RandomAuditRules.from_dict(
                _mapping("random_audit", data["random_audit"])
            ),
            clinical_approver_id=data["clinical_approver_id"],
            statistical_approver_id=data["statistical_approver_id"],
            frozen_at=data["frozen_at"],
        )


@dataclass(frozen=True)
class ClinicianValidationObservation(_Canonical):
    """One primary clinician's labels paired with the frozen evaluator output."""

    opaque_id: str
    cell_id: str
    reviewer_id: str
    clinician_acceptable: bool
    evaluator_acceptable: bool
    clinician_severe_error: bool
    evaluator_severe_error: bool
    clinician_harmful_action: bool
    evaluator_harmful_action: bool
    clinician_critical_omission: bool
    evaluator_critical_omission: bool
    clinician_continuous_score: float
    evaluator_continuous_score: float

    def __post_init__(self) -> None:
        _opaque_id("opaque_id", self.opaque_id)
        _text("cell_id", self.cell_id)
        _text("reviewer_id", self.reviewer_id)
        for name in (
            "clinician_acceptable",
            "evaluator_acceptable",
            "clinician_severe_error",
            "evaluator_severe_error",
            "clinician_harmful_action",
            "evaluator_harmful_action",
            "clinician_critical_omission",
            "evaluator_critical_omission",
        ):
            _boolean(name, getattr(self, name))
        for name in (
            "clinician_continuous_score",
            "evaluator_continuous_score",
        ):
            object.__setattr__(self, name, _finite(name, getattr(self, name)))

    @property
    def clinician_values(self) -> tuple[bool, bool, bool, bool, float]:
        return (
            self.clinician_acceptable,
            self.clinician_severe_error,
            self.clinician_harmful_action,
            self.clinician_critical_omission,
            self.clinician_continuous_score,
        )

    @property
    def evaluator_values(self) -> tuple[bool, bool, bool, bool, float]:
        return (
            self.evaluator_acceptable,
            self.evaluator_severe_error,
            self.evaluator_harmful_action,
            self.evaluator_critical_omission,
            self.evaluator_continuous_score,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "opaque_id": self.opaque_id,
            "cell_id": self.cell_id,
            "reviewer_id": self.reviewer_id,
            "clinician_acceptable": self.clinician_acceptable,
            "evaluator_acceptable": self.evaluator_acceptable,
            "clinician_severe_error": self.clinician_severe_error,
            "evaluator_severe_error": self.evaluator_severe_error,
            "clinician_harmful_action": self.clinician_harmful_action,
            "evaluator_harmful_action": self.evaluator_harmful_action,
            "clinician_critical_omission": self.clinician_critical_omission,
            "evaluator_critical_omission": self.evaluator_critical_omission,
            "clinician_continuous_score": self.clinician_continuous_score,
            "evaluator_continuous_score": self.evaluator_continuous_score,
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "ClinicianValidationObservation":
        fields = {
            "opaque_id",
            "cell_id",
            "reviewer_id",
            "clinician_acceptable",
            "evaluator_acceptable",
            "clinician_severe_error",
            "evaluator_severe_error",
            "clinician_harmful_action",
            "evaluator_harmful_action",
            "clinician_critical_omission",
            "evaluator_critical_omission",
            "clinician_continuous_score",
            "evaluator_continuous_score",
        }
        _fields(data, fields, "clinician validation observation")
        return cls(**{field: data[field] for field in fields})


@dataclass(frozen=True)
class ObservedValidationResults(_Canonical):
    """Observed clinician comparisons bound to one exact frozen plan."""

    plan_hash: str
    study_artifact_hash: str
    response_review_artifact_hash: str
    pair_review_artifact_hash: str
    reviewer_ids: tuple[str, ...]
    observations: tuple[ClinicianValidationObservation, ...]
    completed_at: str
    schema_version: str = RESULTS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESULTS_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {RESULTS_SCHEMA_VERSION!r}")
        for name in (
            "plan_hash",
            "study_artifact_hash",
            "response_review_artifact_hash",
            "pair_review_artifact_hash",
        ):
            _hash(name, getattr(self, name))
        reviewers = _distinct_texts("reviewer_ids", self.reviewer_ids)
        if not reviewers:
            raise ValueError("reviewer_ids must contain at least one reviewer")
        object.__setattr__(self, "reviewer_ids", reviewers)
        observations = _typed_tuple(
            "observations",
            self.observations,
            ClinicianValidationObservation,
        )
        observations = tuple(
            sorted(observations, key=lambda item: (item.opaque_id, item.reviewer_id))
        )
        if not observations:
            raise ValueError("observations must contain at least one result")
        _unique_by(
            "observations",
            observations,
            lambda item: (item.opaque_id, item.reviewer_id),
        )
        object.__setattr__(self, "observations", observations)
        _timestamp("completed_at", self.completed_at)

    def validate_against(self, plan: FrozenValidationPlan) -> None:
        if not isinstance(plan, FrozenValidationPlan):
            raise ValueError("plan must be FrozenValidationPlan")
        bindings = (
            ("plan_hash", self.plan_hash, plan.digest),
            (
                "study_artifact_hash",
                self.study_artifact_hash,
                plan.study_artifact_hash,
            ),
            (
                "response_review_artifact_hash",
                self.response_review_artifact_hash,
                plan.response_review_artifact_hash,
            ),
            (
                "pair_review_artifact_hash",
                self.pair_review_artifact_hash,
                plan.pair_review_artifact_hash,
            ),
        )
        for name, actual, expected in bindings:
            if actual != expected:
                raise ValueError(f"validation results {name} does not match the plan")
        if self.reviewer_ids != plan.clinician_sampling.reviewer_ids:
            raise ValueError(
                "validation results reviewer_ids do not match the frozen roster"
            )
        assignments = {
            assignment.opaque_id: assignment
            for assignment in plan.clinician_sampling.assignments
        }
        cells = {
            opaque_id: cell.cell_id
            for cell in plan.stratification_cells
            for opaque_id in cell.opaque_ids
        }
        expected_keys = {
            (assignment.opaque_id, reviewer_id)
            for assignment in plan.clinician_sampling.assignments
            for reviewer_id in assignment.reviewer_ids
        }
        observed_keys = {
            (observation.opaque_id, observation.reviewer_id)
            for observation in self.observations
        }
        unknown = observed_keys - expected_keys
        if unknown:
            raise ValueError(
                "validation results contain observations outside frozen "
                f"assignments: {sorted(unknown)}"
            )
        minimum = plan.thresholds.continuous_score_minimum
        maximum = plan.thresholds.continuous_score_maximum
        grouped: dict[str, list[ClinicianValidationObservation]] = {}
        for observation in self.observations:
            if observation.cell_id != cells[observation.opaque_id]:
                raise ValueError(
                    f"observation {observation.opaque_id!r} cell_id does not "
                    "match its frozen stratum"
                )
            if observation.reviewer_id not in assignments[
                observation.opaque_id
            ].reviewer_ids:
                raise ValueError("observation reviewer is not assigned to its item")
            for name, value in (
                ("clinician_continuous_score", observation.clinician_continuous_score),
                ("evaluator_continuous_score", observation.evaluator_continuous_score),
            ):
                if not minimum <= value <= maximum:
                    raise ValueError(
                        f"{name} for {observation.opaque_id!r} is outside the "
                        "frozen score range"
                    )
            grouped.setdefault(observation.opaque_id, []).append(observation)
        for opaque_id, item_observations in grouped.items():
            evaluator_values = {
                observation.evaluator_values for observation in item_observations
            }
            if len(evaluator_values) != 1:
                raise ValueError(
                    f"evaluator outputs for {opaque_id!r} are not identical "
                    "across clinician observations"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_hash": self.plan_hash,
            "study_artifact_hash": self.study_artifact_hash,
            "response_review_artifact_hash": self.response_review_artifact_hash,
            "pair_review_artifact_hash": self.pair_review_artifact_hash,
            "reviewer_ids": list(self.reviewer_ids),
            "observations": [
                observation.to_dict() for observation in self.observations
            ],
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        plan: FrozenValidationPlan,
    ) -> "ObservedValidationResults":
        fields = {
            "schema_version",
            "plan_hash",
            "study_artifact_hash",
            "response_review_artifact_hash",
            "pair_review_artifact_hash",
            "reviewer_ids",
            "observations",
            "completed_at",
        }
        _fields(data, fields, "observed validation results")
        result = cls(
            schema_version=data["schema_version"],
            plan_hash=data["plan_hash"],
            study_artifact_hash=data["study_artifact_hash"],
            response_review_artifact_hash=data["response_review_artifact_hash"],
            pair_review_artifact_hash=data["pair_review_artifact_hash"],
            reviewer_ids=_json_string_array("reviewer_ids", data["reviewer_ids"]),
            observations=_json_objects(
                "observations",
                data["observations"],
                ClinicianValidationObservation.from_dict,
            ),
            completed_at=data["completed_at"],
        )
        result.validate_against(plan)
        return result


@dataclass(frozen=True)
class AdjudicationRecord(_Canonical):
    """Independent consensus for one escalated or randomly audited item."""

    opaque_id: str
    cell_id: str
    adjudicator_ids: tuple[str, ...]
    acceptable: bool
    severe_error: bool
    harmful_action: bool
    critical_omission: bool
    continuous_score: float
    decision_reason: str
    adjudicated_at: str

    def __post_init__(self) -> None:
        _opaque_id("opaque_id", self.opaque_id)
        _text("cell_id", self.cell_id)
        adjudicators = _distinct_texts("adjudicator_ids", self.adjudicator_ids)
        if not adjudicators:
            raise ValueError("adjudicator_ids must contain at least one adjudicator")
        object.__setattr__(self, "adjudicator_ids", adjudicators)
        for name in (
            "acceptable",
            "severe_error",
            "harmful_action",
            "critical_omission",
        ):
            _boolean(name, getattr(self, name))
        object.__setattr__(
            self,
            "continuous_score",
            _finite("continuous_score", self.continuous_score),
        )
        _meaningful_text("decision_reason", self.decision_reason, minimum_length=8)
        _timestamp("adjudicated_at", self.adjudicated_at)

    @property
    def clinician_values(self) -> tuple[bool, bool, bool, bool, float]:
        return (
            self.acceptable,
            self.severe_error,
            self.harmful_action,
            self.critical_omission,
            self.continuous_score,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "opaque_id": self.opaque_id,
            "cell_id": self.cell_id,
            "adjudicator_ids": list(self.adjudicator_ids),
            "acceptable": self.acceptable,
            "severe_error": self.severe_error,
            "harmful_action": self.harmful_action,
            "critical_omission": self.critical_omission,
            "continuous_score": self.continuous_score,
            "decision_reason": self.decision_reason,
            "adjudicated_at": self.adjudicated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdjudicationRecord":
        fields = {
            "opaque_id",
            "cell_id",
            "adjudicator_ids",
            "acceptable",
            "severe_error",
            "harmful_action",
            "critical_omission",
            "continuous_score",
            "decision_reason",
            "adjudicated_at",
        }
        _fields(data, fields, "adjudication record")
        return cls(
            opaque_id=data["opaque_id"],
            cell_id=data["cell_id"],
            adjudicator_ids=_json_string_array(
                "adjudicator_ids",
                data["adjudicator_ids"],
            ),
            acceptable=data["acceptable"],
            severe_error=data["severe_error"],
            harmful_action=data["harmful_action"],
            critical_omission=data["critical_omission"],
            continuous_score=data["continuous_score"],
            decision_reason=data["decision_reason"],
            adjudicated_at=data["adjudicated_at"],
        )


@dataclass(frozen=True)
class AdjudicationBundle(_Canonical):
    """Adjudications bound to exact validation results and artifact hashes."""

    plan_hash: str
    validation_results_hash: str
    study_artifact_hash: str
    response_review_artifact_hash: str
    pair_review_artifact_hash: str
    adjudicator_ids: tuple[str, ...]
    records: tuple[AdjudicationRecord, ...]
    completed_at: str
    schema_version: str = ADJUDICATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ADJUDICATION_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {ADJUDICATION_SCHEMA_VERSION!r}")
        for name in (
            "plan_hash",
            "validation_results_hash",
            "study_artifact_hash",
            "response_review_artifact_hash",
            "pair_review_artifact_hash",
        ):
            _hash(name, getattr(self, name))
        adjudicators = _distinct_texts("adjudicator_ids", self.adjudicator_ids)
        if not adjudicators:
            raise ValueError("adjudicator_ids must contain at least one adjudicator")
        object.__setattr__(self, "adjudicator_ids", adjudicators)
        records = _typed_tuple("records", self.records, AdjudicationRecord)
        records = tuple(sorted(records, key=lambda record: record.opaque_id))
        if not records:
            raise ValueError("records must contain at least one adjudication")
        _unique_by("records", records, lambda record: record.opaque_id)
        object.__setattr__(self, "records", records)
        _timestamp("completed_at", self.completed_at)

    def validate_against(
        self,
        plan: FrozenValidationPlan,
        results: ObservedValidationResults,
    ) -> None:
        results.validate_against(plan)
        bindings = (
            ("plan_hash", self.plan_hash, plan.digest),
            ("validation_results_hash", self.validation_results_hash, results.digest),
            (
                "study_artifact_hash",
                self.study_artifact_hash,
                plan.study_artifact_hash,
            ),
            (
                "response_review_artifact_hash",
                self.response_review_artifact_hash,
                plan.response_review_artifact_hash,
            ),
            (
                "pair_review_artifact_hash",
                self.pair_review_artifact_hash,
                plan.pair_review_artifact_hash,
            ),
        )
        for name, actual, expected in bindings:
            if actual != expected:
                raise ValueError(f"adjudication bundle {name} does not match")
        if self.adjudicator_ids != plan.escalation.adjudicator_ids:
            raise ValueError(
                "adjudication bundle adjudicator_ids do not match the frozen roster"
            )
        assignment_by_id = {
            assignment.opaque_id: assignment
            for assignment in plan.clinician_sampling.assignments
        }
        cell_by_id = {
            opaque_id: cell.cell_id
            for cell in plan.stratification_cells
            for opaque_id in cell.opaque_ids
        }
        minimum = plan.thresholds.continuous_score_minimum
        maximum = plan.thresholds.continuous_score_maximum
        roster = set(plan.escalation.adjudicator_ids)
        for record in self.records:
            if record.opaque_id not in assignment_by_id:
                raise ValueError(
                    f"adjudication {record.opaque_id!r} is not a sampled item"
                )
            if record.cell_id != cell_by_id[record.opaque_id]:
                raise ValueError(
                    f"adjudication {record.opaque_id!r} cell_id does not match "
                    "its frozen stratum"
                )
            if len(record.adjudicator_ids) != plan.escalation.adjudicators_per_item:
                raise ValueError(
                    f"adjudication {record.opaque_id!r} must contain exactly "
                    "adjudicators_per_item adjudicators"
                )
            if not set(record.adjudicator_ids) <= roster:
                raise ValueError(
                    f"adjudication {record.opaque_id!r} contains an adjudicator "
                    "outside the frozen roster"
                )
            if set(record.adjudicator_ids) & set(
                assignment_by_id[record.opaque_id].reviewer_ids
            ):
                raise ValueError(
                    f"adjudication {record.opaque_id!r} is not independent of "
                    "its primary reviewers"
                )
            if not minimum <= record.continuous_score <= maximum:
                raise ValueError(
                    f"adjudication {record.opaque_id!r} continuous_score is "
                    "outside the frozen score range"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_hash": self.plan_hash,
            "validation_results_hash": self.validation_results_hash,
            "study_artifact_hash": self.study_artifact_hash,
            "response_review_artifact_hash": self.response_review_artifact_hash,
            "pair_review_artifact_hash": self.pair_review_artifact_hash,
            "adjudicator_ids": list(self.adjudicator_ids),
            "records": [record.to_dict() for record in self.records],
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        plan: FrozenValidationPlan,
        results: ObservedValidationResults,
    ) -> "AdjudicationBundle":
        fields = {
            "schema_version",
            "plan_hash",
            "validation_results_hash",
            "study_artifact_hash",
            "response_review_artifact_hash",
            "pair_review_artifact_hash",
            "adjudicator_ids",
            "records",
            "completed_at",
        }
        _fields(data, fields, "adjudication bundle")
        bundle = cls(
            schema_version=data["schema_version"],
            plan_hash=data["plan_hash"],
            validation_results_hash=data["validation_results_hash"],
            study_artifact_hash=data["study_artifact_hash"],
            response_review_artifact_hash=data["response_review_artifact_hash"],
            pair_review_artifact_hash=data["pair_review_artifact_hash"],
            adjudicator_ids=_json_string_array(
                "adjudicator_ids",
                data["adjudicator_ids"],
            ),
            records=_json_objects(
                "records",
                data["records"],
                AdjudicationRecord.from_dict,
            ),
            completed_at=data["completed_at"],
        )
        bundle.validate_against(plan, results)
        return bundle


@dataclass(frozen=True)
class ValidationMetrics(_Canonical):
    """Item-level metrics calculated after required adjudication."""

    item_count: int
    agreement: float
    severe_error_sensitivity: float
    severe_error_specificity: float
    harmful_action_false_negative_rate: float
    critical_omission_false_negative_rate: float
    continuous_score_mae: float
    severe_error_positives: int
    severe_error_negatives: int
    harmful_action_positives: int
    critical_omission_positives: int

    def __post_init__(self) -> None:
        _positive_integer("item_count", self.item_count)
        for name in (
            "agreement",
            "severe_error_sensitivity",
            "severe_error_specificity",
            "harmful_action_false_negative_rate",
            "critical_omission_false_negative_rate",
        ):
            object.__setattr__(self, name, _unit_interval(name, getattr(self, name)))
        mae = _finite("continuous_score_mae", self.continuous_score_mae)
        if mae < 0:
            raise ValueError("continuous_score_mae must be non-negative")
        object.__setattr__(self, "continuous_score_mae", mae)
        for name in (
            "severe_error_positives",
            "severe_error_negatives",
            "harmful_action_positives",
            "critical_omission_positives",
        ):
            _nonnegative_integer(name, getattr(self, name))

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_count": self.item_count,
            "agreement": self.agreement,
            "severe_error_sensitivity": self.severe_error_sensitivity,
            "severe_error_specificity": self.severe_error_specificity,
            "harmful_action_false_negative_rate": (
                self.harmful_action_false_negative_rate
            ),
            "critical_omission_false_negative_rate": (
                self.critical_omission_false_negative_rate
            ),
            "continuous_score_mae": self.continuous_score_mae,
            "severe_error_positives": self.severe_error_positives,
            "severe_error_negatives": self.severe_error_negatives,
            "harmful_action_positives": self.harmful_action_positives,
            "critical_omission_positives": self.critical_omission_positives,
        }


_GATE_TOKEN = object()


@dataclass(frozen=True, init=False)
class ClinicalValidationGate(_Canonical):
    """A gate decision that can only be built by evidence evaluation."""

    verdict: ValidationVerdict
    reasons: tuple[str, ...]
    plan_hash: str | None
    validation_results_hash: str | None
    adjudication_hash: str | None
    expected_observation_count: int
    observed_observation_count: int
    required_adjudication_count: int
    observed_adjudication_count: int
    metrics: ValidationMetrics | None

    def __init__(
        self,
        *,
        _token: object,
        verdict: ValidationVerdict,
        reasons: tuple[str, ...],
        plan_hash: str | None,
        validation_results_hash: str | None,
        adjudication_hash: str | None,
        expected_observation_count: int,
        observed_observation_count: int,
        required_adjudication_count: int,
        observed_adjudication_count: int,
        metrics: ValidationMetrics | None,
    ) -> None:
        if _token is not _GATE_TOKEN:
            raise TypeError(
                "ClinicalValidationGate verdicts are derived by "
                "evaluate_clinical_validation()"
            )
        object.__setattr__(self, "verdict", verdict)
        object.__setattr__(self, "reasons", reasons)
        object.__setattr__(self, "plan_hash", plan_hash)
        object.__setattr__(
            self,
            "validation_results_hash",
            validation_results_hash,
        )
        object.__setattr__(self, "adjudication_hash", adjudication_hash)
        object.__setattr__(
            self,
            "expected_observation_count",
            expected_observation_count,
        )
        object.__setattr__(
            self,
            "observed_observation_count",
            observed_observation_count,
        )
        object.__setattr__(
            self,
            "required_adjudication_count",
            required_adjudication_count,
        )
        object.__setattr__(
            self,
            "observed_adjudication_count",
            observed_adjudication_count,
        )
        object.__setattr__(self, "metrics", metrics)

    @classmethod
    def _derive(
        cls,
        *,
        verdict: ValidationVerdict,
        reasons: Sequence[str] = (),
        plan: FrozenValidationPlan | None = None,
        results: ObservedValidationResults | None = None,
        adjudications: AdjudicationBundle | None = None,
        expected_observation_count: int = 0,
        required_adjudication_count: int = 0,
        metrics: ValidationMetrics | None = None,
    ) -> "ClinicalValidationGate":
        return cls(
            _token=_GATE_TOKEN,
            verdict=verdict,
            reasons=tuple(reasons),
            plan_hash=plan.digest if plan is not None else None,
            validation_results_hash=results.digest if results is not None else None,
            adjudication_hash=(
                adjudications.digest if adjudications is not None else None
            ),
            expected_observation_count=expected_observation_count,
            observed_observation_count=(
                len(results.observations) if results is not None else 0
            ),
            required_adjudication_count=required_adjudication_count,
            observed_adjudication_count=(
                len(adjudications.records) if adjudications is not None else 0
            ),
            metrics=metrics,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "reasons": list(self.reasons),
            "plan_hash": self.plan_hash,
            "validation_results_hash": self.validation_results_hash,
            "adjudication_hash": self.adjudication_hash,
            "expected_observation_count": self.expected_observation_count,
            "observed_observation_count": self.observed_observation_count,
            "required_adjudication_count": self.required_adjudication_count,
            "observed_adjudication_count": self.observed_adjudication_count,
            "metrics": self.metrics.to_dict() if self.metrics is not None else None,
        }


def required_adjudication_ids(
    plan: FrozenValidationPlan,
    results: ObservedValidationResults,
) -> tuple[str, ...]:
    """Return the deterministic union of escalations and random audits."""

    results.validate_against(plan)
    grouped = _observations_by_item(results)
    required: set[str] = set()
    rules = plan.escalation
    for opaque_id, observations in grouped.items():
        clinician_values = {
            observation.clinician_values for observation in observations
        }
        if len(clinician_values) > 1:
            required.add(opaque_id)
        for observation in observations:
            if (
                rules.escalate_acceptability_disagreement
                and observation.clinician_acceptable
                is not observation.evaluator_acceptable
            ):
                required.add(opaque_id)
            if (
                rules.escalate_severe_error_disagreement
                and observation.clinician_severe_error
                is not observation.evaluator_severe_error
            ):
                required.add(opaque_id)
            if (
                rules.escalate_harmful_action_disagreement
                and observation.clinician_harmful_action
                is not observation.evaluator_harmful_action
            ):
                required.add(opaque_id)
            if (
                rules.escalate_critical_omission_disagreement
                and observation.clinician_critical_omission
                is not observation.evaluator_critical_omission
            ):
                required.add(opaque_id)
            if (
                abs(
                    observation.clinician_continuous_score
                    - observation.evaluator_continuous_score
                )
                >= rules.continuous_score_absolute_difference
            ):
                required.add(opaque_id)

    for cell in plan.stratification_cells:
        audit_count = max(
            plan.random_audit.minimum_per_cell,
            math.ceil(plan.random_audit.fraction_per_cell * len(cell.opaque_ids)),
        )
        audit_count = min(audit_count, len(cell.opaque_ids))
        ranked = sorted(
            cell.opaque_ids,
            key=lambda opaque_id: hashlib.sha256(
                (
                    f"{plan.random_audit.random_seed}:{plan.digest}:"
                    f"{cell.cell_id}:{opaque_id}"
                ).encode("utf-8")
            ).hexdigest(),
        )
        required.update(ranked[:audit_count])
    return tuple(sorted(required))


def evaluate_clinical_validation(
    *,
    plan: FrozenValidationPlan | None = None,
    results: ObservedValidationResults | None = None,
    adjudications: AdjudicationBundle | None = None,
) -> ClinicalValidationGate:
    """Derive the clinical gate verdict from exact evidence coverage.

    ``engineering-only`` means clinical validation has not produced evidence.
    ``inconclusive`` means evidence was submitted but is incomplete or has an
    insufficient prespecified denominator. Hash or identity mismatches raise
    ``ValueError`` instead of being converted into a verdict.
    """

    if plan is None:
        if results is not None or adjudications is not None:
            raise ValueError("results or adjudications cannot be supplied without a plan")
        return ClinicalValidationGate._derive(
            verdict=ValidationVerdict.ENGINEERING_ONLY,
            reasons=("clinical validation plan is not frozen",),
        )
    expected_keys = {
        (assignment.opaque_id, reviewer_id)
        for assignment in plan.clinician_sampling.assignments
        for reviewer_id in assignment.reviewer_ids
    }
    expected_observations = len(expected_keys)
    if results is None:
        if adjudications is not None:
            raise ValueError("adjudications cannot be supplied without results")
        return ClinicalValidationGate._derive(
            verdict=ValidationVerdict.ENGINEERING_ONLY,
            reasons=("clinician validation results are not available",),
            plan=plan,
            expected_observation_count=expected_observations,
        )
    results.validate_against(plan)
    if adjudications is not None:
        adjudications.validate_against(plan, results)
    observed_keys = {
        (observation.opaque_id, observation.reviewer_id)
        for observation in results.observations
    }
    if observed_keys != expected_keys:
        missing_observations = sorted(expected_keys - observed_keys)
        return ClinicalValidationGate._derive(
            verdict=ValidationVerdict.INCONCLUSIVE,
            reasons=(
                f"missing {len(missing_observations)} assigned clinician "
                "observations",
            ),
            plan=plan,
            results=results,
            adjudications=adjudications,
            expected_observation_count=expected_observations,
        )

    required_ids = set(required_adjudication_ids(plan, results))
    if adjudications is None:
        return ClinicalValidationGate._derive(
            verdict=ValidationVerdict.INCONCLUSIVE,
            reasons=(
                f"missing adjudications for {len(required_ids)} escalated or "
                "audited items",
            ),
            plan=plan,
            results=results,
            expected_observation_count=expected_observations,
            required_adjudication_count=len(required_ids),
        )
    observed_adjudication_ids = {
        record.opaque_id for record in adjudications.records
    }
    if observed_adjudication_ids != required_ids:
        missing_adjudications = required_ids - observed_adjudication_ids
        extra_adjudications = observed_adjudication_ids - required_ids
        return ClinicalValidationGate._derive(
            verdict=ValidationVerdict.INCONCLUSIVE,
            reasons=(
                "adjudication coverage does not exactly match the prespecified "
                f"selection; missing={len(missing_adjudications)}, "
                f"extra={len(extra_adjudications)}",
            ),
            plan=plan,
            results=results,
            adjudications=adjudications,
            expected_observation_count=expected_observations,
            required_adjudication_count=len(required_ids),
        )

    metrics = _calculate_metrics(plan, results, adjudications)
    thresholds = plan.thresholds
    denominator_failures: list[str] = []
    for denominator_label, denominator_actual, denominator_minimum in (
        (
            "severe-error positives",
            metrics.severe_error_positives,
            thresholds.minimum_severe_error_positives,
        ),
        (
            "severe-error negatives",
            metrics.severe_error_negatives,
            thresholds.minimum_severe_error_negatives,
        ),
        (
            "harmful-action positives",
            metrics.harmful_action_positives,
            thresholds.minimum_harmful_action_positives,
        ),
        (
            "critical-omission positives",
            metrics.critical_omission_positives,
            thresholds.minimum_critical_omission_positives,
        ),
    ):
        if denominator_actual < denominator_minimum:
            denominator_failures.append(
                f"{denominator_label} {denominator_actual} is below "
                f"{denominator_minimum}"
            )
    if denominator_failures:
        return ClinicalValidationGate._derive(
            verdict=ValidationVerdict.INCONCLUSIVE,
            reasons=denominator_failures,
            plan=plan,
            results=results,
            adjudications=adjudications,
            expected_observation_count=expected_observations,
            required_adjudication_count=len(required_ids),
            metrics=metrics,
        )

    failures: list[str] = []
    comparisons = (
        (
            "agreement",
            metrics.agreement,
            thresholds.minimum_agreement,
            "minimum",
        ),
        (
            "severe-error sensitivity",
            metrics.severe_error_sensitivity,
            thresholds.minimum_severe_error_sensitivity,
            "minimum",
        ),
        (
            "severe-error specificity",
            metrics.severe_error_specificity,
            thresholds.minimum_severe_error_specificity,
            "minimum",
        ),
        (
            "harmful-action false-negative rate",
            metrics.harmful_action_false_negative_rate,
            thresholds.maximum_harmful_action_false_negative_rate,
            "maximum",
        ),
        (
            "critical-omission false-negative rate",
            metrics.critical_omission_false_negative_rate,
            thresholds.maximum_critical_omission_false_negative_rate,
            "maximum",
        ),
        (
            "continuous-score MAE",
            metrics.continuous_score_mae,
            thresholds.maximum_continuous_score_mae,
            "maximum",
        ),
    )
    for metric_label, metric_actual, metric_threshold, direction in comparisons:
        failed = (
            metric_actual < metric_threshold
            if direction == "minimum"
            else metric_actual > metric_threshold
        )
        if failed:
            failures.append(
                f"{metric_label} {metric_actual:.6g} failed {direction} "
                f"{metric_threshold:.6g}"
            )
    return ClinicalValidationGate._derive(
        verdict=(
            ValidationVerdict.REJECTED
            if failures
            else ValidationVerdict.ACCEPTED
        ),
        reasons=failures,
        plan=plan,
        results=results,
        adjudications=adjudications,
        expected_observation_count=expected_observations,
        required_adjudication_count=len(required_ids),
        metrics=metrics,
    )


def load_validation_plan(path: str | Path) -> FrozenValidationPlan:
    """Load a plan from strict JSON, rejecting duplicate object keys."""

    return FrozenValidationPlan.from_dict(_load_json_object(path))


def load_validation_results(
    path: str | Path,
    *,
    plan: FrozenValidationPlan,
) -> ObservedValidationResults:
    """Load validation results and verify all frozen artifact bindings."""

    return ObservedValidationResults.from_dict(_load_json_object(path), plan=plan)


def load_adjudications(
    path: str | Path,
    *,
    plan: FrozenValidationPlan,
    results: ObservedValidationResults,
) -> AdjudicationBundle:
    """Load adjudications and verify their plan and results bindings."""

    return AdjudicationBundle.from_dict(
        _load_json_object(path),
        plan=plan,
        results=results,
    )


def _calculate_metrics(
    plan: FrozenValidationPlan,
    results: ObservedValidationResults,
    adjudications: AdjudicationBundle,
) -> ValidationMetrics:
    grouped = _observations_by_item(results)
    adjudicated = {record.opaque_id: record for record in adjudications.records}
    agreement = 0
    severe_true_positive = 0
    severe_true_negative = 0
    severe_positives = 0
    severe_negatives = 0
    harmful_false_negative = 0
    harmful_positives = 0
    omission_false_negative = 0
    omission_positives = 0
    absolute_errors: list[float] = []

    for opaque_id in plan.opaque_ids:
        observations = grouped[opaque_id]
        evaluator = observations[0].evaluator_values
        if opaque_id in adjudicated:
            clinician = adjudicated[opaque_id].clinician_values
        else:
            clinician_values = {
                observation.clinician_values for observation in observations
            }
            if len(clinician_values) != 1:
                raise ValueError(
                    f"unadjudicated clinician disagreement for {opaque_id!r}"
                )
            clinician = next(iter(clinician_values))
        (
            clinician_acceptable,
            clinician_severe,
            clinician_harmful,
            clinician_omission,
            clinician_score,
        ) = clinician
        (
            evaluator_acceptable,
            evaluator_severe,
            evaluator_harmful,
            evaluator_omission,
            evaluator_score,
        ) = evaluator
        agreement += int(clinician_acceptable is evaluator_acceptable)
        if clinician_severe:
            severe_positives += 1
            severe_true_positive += int(evaluator_severe)
        else:
            severe_negatives += 1
            severe_true_negative += int(not evaluator_severe)
        if clinician_harmful:
            harmful_positives += 1
            harmful_false_negative += int(not evaluator_harmful)
        if clinician_omission:
            omission_positives += 1
            omission_false_negative += int(not evaluator_omission)
        absolute_errors.append(abs(clinician_score - evaluator_score))

    count = len(plan.opaque_ids)
    return ValidationMetrics(
        item_count=count,
        agreement=agreement / count,
        severe_error_sensitivity=(
            severe_true_positive / severe_positives if severe_positives else 0.0
        ),
        severe_error_specificity=(
            severe_true_negative / severe_negatives if severe_negatives else 0.0
        ),
        harmful_action_false_negative_rate=(
            harmful_false_negative / harmful_positives
            if harmful_positives
            else 0.0
        ),
        critical_omission_false_negative_rate=(
            omission_false_negative / omission_positives
            if omission_positives
            else 0.0
        ),
        continuous_score_mae=sum(absolute_errors) / count,
        severe_error_positives=severe_positives,
        severe_error_negatives=severe_negatives,
        harmful_action_positives=harmful_positives,
        critical_omission_positives=omission_positives,
    )


def _observations_by_item(
    results: ObservedValidationResults,
) -> dict[str, list[ClinicianValidationObservation]]:
    grouped: dict[str, list[ClinicianValidationObservation]] = {}
    for observation in results.observations:
        grouped.setdefault(observation.opaque_id, []).append(observation)
    return grouped


def _load_json_object(path: str | Path) -> Mapping[str, Any]:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot load clinical validation JSON {source}: {exc}") from exc
    return strict_json_object(text, f"clinical validation JSON {source}")


def _mapping(name: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _json_string_array(name: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array of strings")
    return tuple(value)


def _json_objects(
    name: str,
    value: Any,
    loader: Any,
) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array of objects")
    return tuple(loader(_mapping(name, item)) for item in value)


def _typed_tuple(name: str, value: Any, item_type: type[Any]) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be a sequence") from exc
    if any(not isinstance(item, item_type) for item in values):
        raise ValueError(f"{name} contains an invalid item")
    return values


def _text(name: str, value: Any) -> str:
    return text(value, name, no_outer_whitespace=True,
                placeholder=lambda v: _PLACEHOLDER_RE.fullmatch(v) is not None or "<placeholder>" in v.lower())


def _meaningful_text(name: str, value: Any, *, minimum_length: int) -> None:
    _text(name, value)
    if len(value) < minimum_length:
        raise ValueError(f"{name} must contain at least {minimum_length} characters")


def _distinct_texts(name: str, value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence of strings")
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be a sequence of strings") from exc
    for item in values:
        _text(name, item)
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not contain duplicates")
    return tuple(sorted(values))


def _opaque_id(name: str, value: Any) -> None:
    _text(name, value)
    if _OPAQUE_ID_RE.fullmatch(value) is None:
        raise ValueError(
            f"{name} must be an opaque identifier containing 6-128 safe characters"
        )


def _opaque_ids(name: str, value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence of opaque identifiers")
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be a sequence of opaque identifiers") from exc
    for item in values:
        _opaque_id(name, item)
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not contain duplicates")
    return tuple(sorted(values))


def _choice(name: str, value: Any, choices: Sequence[str]) -> None:
    if value not in choices:
        raise ValueError(f"{name} must be one of {list(choices)}")


def _hash(name: str, value: Any) -> str:
    return sha256_hex(value, name)


def _timestamp(name: str, value: Any) -> datetime:
    return timestamp(value, name, check_text=lambda v: _text(name, v), pattern=_RFC3339_RE)


def _finite(name: str, value: Any) -> float:
    return number(value, name)


def _unit_interval(name: str, value: Any) -> float:
    return number(value, name, minimum=0, maximum=1)


def _integer(name: str, value: Any) -> int:
    return integer(value, name)


def _positive_integer(name: str, value: Any) -> None:
    _integer(name, value)
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _nonnegative_integer(name: str, value: Any) -> None:
    _integer(name, value)
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _boolean(name: str, value: Any) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")


def _unique_by(name: str, values: Sequence[Any], key: Any) -> None:
    keys = [key(value) for value in values]
    if len(set(keys)) != len(keys):
        raise ValueError(f"{name} must not contain duplicates")


__all__ = [
    "ADJUDICATION_SCHEMA_VERSION",
    "COHORTS",
    "PLAN_SCHEMA_VERSION",
    "RELATIONSHIPS",
    "RESULTS_SCHEMA_VERSION",
    "SAMPLING_METHODS",
    "AdjudicationBundle",
    "AdjudicationRecord",
    "ClinicalValidationGate",
    "ClinicianAssignment",
    "ClinicianSamplingPlan",
    "ClinicianValidationObservation",
    "CriterionThresholds",
    "EscalationRules",
    "FrozenValidationPlan",
    "ObservedValidationResults",
    "RandomAuditRules",
    "StratificationCell",
    "ValidationMetrics",
    "ValidationVerdict",
    "evaluate_clinical_validation",
    "load_adjudications",
    "load_validation_plan",
    "load_validation_results",
    "required_adjudication_ids",
]
