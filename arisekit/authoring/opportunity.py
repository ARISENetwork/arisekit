"""Portable evidence contract for portfolio benchmark opportunities.

The contract records a frozen recommendation input. It does not turn a
geometric gap into a clinical need, generate a benchmark, or admit one to a
leaderboard. Conceptual portfolio signals and missing score cells are separate
tracks because the latter calls for data collection, not benchmark design.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from arisekit.common.records import CanonicalRecord
from arisekit.common.validate import sha256_hex


SCHEMA_VERSION = "arisekit.portfolio-opportunity.v2"
QUEUE_SCHEMA_VERSION = "arisekit.portfolio-action-queue.v1"
DECISION_SCOPE = "portfolio-planning-only"
_QUEUE_FIELDS = ("action", "target", "rationale", "utility", "cost")


class OpportunitySignal(str, Enum):
    COVERAGE_GAP = "conceptual-coverage-gap"
    REDUNDANCY = "conceptual-redundancy"
    SATURATION = "conceptual-saturation"
    MISSING_RESULT_CELLS = "missing-result-cells"


class OpportunityTrack(str, Enum):
    BENCHMARK_DESIGN = "benchmark-design"
    PORTFOLIO_MAINTENANCE = "portfolio-maintenance"
    RESULT_COLLECTION = "result-collection"


class PortfolioActionKind(str, Enum):
    """Action names emitted by the MAST portfolio collection queue."""

    HARDEN_ITEMS = "harden_items"
    CELL_FILL = "cell_fill"
    NEW_BENCHMARK = "new_benchmark"
    PERSIST_ITEMS = "persist_items"
    LABEL_COLLECT = "label_collect"


class NeedReviewStatus(str, Enum):
    PROPOSED = "proposed"
    CLINICIAN_ATTESTED = "clinician-attested"


class EvidenceAccessClass(str, Enum):
    PUBLIC = "public"
    PRIVATE_SANITIZED = "private-sanitized"


class FingerprintStatisticDirection(str, Enum):
    GREATER_OR_EQUAL = "greater-than-or-equal"
    LESS_OR_EQUAL = "less-than-or-equal"


@dataclass(frozen=True)
class EvidenceBoundary:
    """Release boundary for portfolio evidence, never the private source itself."""

    access_class: EvidenceAccessClass
    released_artifact_hash: str
    reviewed_by: str
    reviewed_at: str
    contains_raw_records: bool = False
    contains_direct_identifiers: bool = False
    private_source_hash: str | None = None
    sanitization_code_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "access_class", EvidenceAccessClass(self.access_class))
        _require_hash("released_artifact_hash", self.released_artifact_hash)
        _require_text("reviewed_by", self.reviewed_by)
        _require_text("reviewed_at", self.reviewed_at)
        if not isinstance(self.contains_raw_records, bool):
            raise ValueError("contains_raw_records must be boolean")
        if not isinstance(self.contains_direct_identifiers, bool):
            raise ValueError("contains_direct_identifiers must be boolean")
        if self.contains_raw_records or self.contains_direct_identifiers:
            raise ValueError(
                "released portfolio evidence cannot contain raw records or direct identifiers"
            )
        if self.access_class is EvidenceAccessClass.PRIVATE_SANITIZED:
            if self.private_source_hash is None or self.sanitization_code_hash is None:
                raise ValueError(
                    "private-sanitized evidence requires private source and sanitization hashes"
                )
            _require_hash("private_source_hash", self.private_source_hash)
            _require_hash("sanitization_code_hash", self.sanitization_code_hash)
        elif (
            self.private_source_hash is not None
            or self.sanitization_code_hash is not None
        ):
            raise ValueError(
                "public evidence cannot carry private-source sanitization metadata"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_class": self.access_class.value,
            "released_artifact_hash": self.released_artifact_hash,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "contains_raw_records": self.contains_raw_records,
            "contains_direct_identifiers": self.contains_direct_identifiers,
            "private_source_hash": self.private_source_hash,
            "sanitization_code_hash": self.sanitization_code_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceBoundary":
        fields = {
            "access_class",
            "released_artifact_hash",
            "reviewed_by",
            "reviewed_at",
            "contains_raw_records",
            "contains_direct_identifiers",
            "private_source_hash",
            "sanitization_code_hash",
        }
        _require_fields(data, fields, "evidence boundary")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True)
class PortfolioActionCandidate:
    """One ranked action preserved from a released MAST collection queue."""

    rank: int
    action: PortfolioActionKind
    target: str
    rationale: str
    utility: float
    cost: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.rank, bool)
            or not isinstance(self.rank, int)
            or self.rank < 1
        ):
            raise ValueError("portfolio action rank must be a positive integer")
        object.__setattr__(self, "action", PortfolioActionKind(self.action))
        for name in ("target", "rationale", "cost"):
            _require_text(name, getattr(self, name))
        if (
            isinstance(self.utility, bool)
            or not isinstance(self.utility, (int, float))
            or not math.isfinite(self.utility)
            or not 0.0 <= float(self.utility) <= 1.0
        ):
            raise ValueError("portfolio action utility must be between 0 and 1")
        object.__setattr__(self, "utility", float(self.utility))

    @property
    def track(self) -> OpportunityTrack:
        if self.action is PortfolioActionKind.NEW_BENCHMARK:
            return OpportunityTrack.BENCHMARK_DESIGN
        if self.action is PortfolioActionKind.HARDEN_ITEMS:
            return OpportunityTrack.PORTFOLIO_MAINTENANCE
        return OpportunityTrack.RESULT_COLLECTION

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "action": self.action.value,
            "target": self.target,
            "rationale": self.rationale,
            "utility": self.utility,
            "cost": self.cost,
            "track": self.track.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PortfolioActionCandidate":
        fields = {
            "rank",
            "action",
            "target",
            "rationale",
            "utility",
            "cost",
            "track",
        }
        _require_fields(data, fields, "portfolio action candidate")
        candidate = cls(
            rank=data["rank"],
            action=PortfolioActionKind(data["action"]),
            target=data["target"],
            rationale=data["rationale"],
            utility=data["utility"],
            cost=data["cost"],
        )
        if data["track"] != candidate.track.value:
            raise ValueError("serialized track does not match portfolio action")
        return candidate


@dataclass(frozen=True)
class PortfolioActionQueue(CanonicalRecord):
    """Versioned, hash-bound import of the MAST portfolio action queue."""

    source_artifact: str
    source_revision: str
    source_sha256: str
    analysis_code_hash: str
    evidence_boundary: EvidenceBoundary
    actions: tuple[PortfolioActionCandidate, ...]
    decision_scope: str = DECISION_SCOPE
    schema_version: str = QUEUE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text("source_artifact", self.source_artifact)
        artifact = PurePosixPath(self.source_artifact)
        if (
            "\\" in self.source_artifact
            or artifact.is_absolute()
            or any(part in {"", ".", ".."} for part in artifact.parts)
        ):
            raise ValueError("source_artifact must be a safe relative logical path")
        if artifact.as_posix() != self.source_artifact:
            raise ValueError("source_artifact must use canonical POSIX separators")
        _require_text("source_revision", self.source_revision)
        _require_hash("source_sha256", self.source_sha256)
        _require_hash("analysis_code_hash", self.analysis_code_hash)
        if not isinstance(self.evidence_boundary, EvidenceBoundary):
            raise ValueError("evidence_boundary must be EvidenceBoundary")
        if self.evidence_boundary.released_artifact_hash != self.source_sha256:
            raise ValueError("evidence boundary must bind the released portfolio queue")
        actions = tuple(self.actions)
        if not actions or not all(
            isinstance(action, PortfolioActionCandidate) for action in actions
        ):
            raise ValueError("portfolio action queue must contain actions")
        expected_ranks = tuple(range(1, len(actions) + 1))
        if tuple(action.rank for action in actions) != expected_ranks:
            raise ValueError("portfolio action ranks must be contiguous and ordered")
        keys = tuple((action.action, action.target) for action in actions)
        if len(set(keys)) != len(keys):
            raise ValueError("portfolio action queue contains duplicate action targets")
        object.__setattr__(self, "actions", actions)
        if self.decision_scope != DECISION_SCOPE:
            raise ValueError(f"decision_scope must be {DECISION_SCOPE!r}")
        if self.schema_version != QUEUE_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {QUEUE_SCHEMA_VERSION!r}")

    def by_track(self, track: OpportunityTrack) -> tuple[PortfolioActionCandidate, ...]:
        normalized = OpportunityTrack(track)
        return tuple(action for action in self.actions if action.track is normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_scope": self.decision_scope,
            "source_artifact": self.source_artifact,
            "source_revision": self.source_revision,
            "source_sha256": self.source_sha256,
            "analysis_code_hash": self.analysis_code_hash,
            "evidence_boundary": self.evidence_boundary.to_dict(),
            "action_count": len(self.actions),
            "actions": [action.to_dict() for action in self.actions],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PortfolioActionQueue":
        fields = {
            "schema_version",
            "decision_scope",
            "source_artifact",
            "source_revision",
            "source_sha256",
            "analysis_code_hash",
            "evidence_boundary",
            "action_count",
            "actions",
        }
        _require_fields(data, fields, "portfolio action queue")
        raw_actions = data["actions"]
        if not isinstance(raw_actions, list):
            raise ValueError("portfolio action queue actions must be a list")
        queue = cls(
            source_artifact=data["source_artifact"],
            source_revision=data["source_revision"],
            source_sha256=data["source_sha256"],
            analysis_code_hash=data["analysis_code_hash"],
            evidence_boundary=EvidenceBoundary.from_dict(data["evidence_boundary"]),
            actions=tuple(
                PortfolioActionCandidate.from_dict(action) for action in raw_actions
            ),
            decision_scope=data["decision_scope"],
            schema_version=data["schema_version"],
        )
        if (
            isinstance(data["action_count"], bool)
            or not isinstance(data["action_count"], int)
            or data["action_count"] != len(queue.actions)
        ):
            raise ValueError("portfolio action_count does not match actions")
        return queue


def load_portfolio_action_queue(
    path: str | Path,
    *,
    expected_sha256: str,
    analysis_code_hash: str,
    source_revision: str,
    evidence_boundary: EvidenceBoundary,
    source_artifact: str = "data_collection_queue.csv",
) -> PortfolioActionQueue:
    """Load the exact released MAST queue after verifying its expected bytes."""

    _require_hash("expected_sha256", expected_sha256)
    supplied = Path(path).expanduser()
    if supplied.is_symlink():
        raise ValueError("portfolio queue input must not be a symlink")
    resolved = supplied.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"portfolio queue not found: {resolved}")
    payload = resolved.read_bytes()
    observed_sha256 = hashlib.sha256(payload).hexdigest()
    if observed_sha256 != expected_sha256:
        raise ValueError("portfolio queue bytes do not match expected_sha256")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("portfolio queue must be UTF-8") from exc

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if tuple(reader.fieldnames or ()) != _QUEUE_FIELDS:
            raise ValueError(
                "portfolio queue header must be " + ",".join(_QUEUE_FIELDS)
            )
        actions: list[PortfolioActionCandidate] = []
        for rank, row in enumerate(reader, start=1):
            if set(row) != set(_QUEUE_FIELDS) or any(
                value is None for value in row.values()
            ):
                raise ValueError(f"portfolio queue row {rank} has invalid columns")
            try:
                utility = float(row["utility"])
            except ValueError as exc:
                raise ValueError(
                    f"portfolio queue row {rank} utility is not numeric"
                ) from exc
            actions.append(
                PortfolioActionCandidate(
                    rank=rank,
                    action=PortfolioActionKind(row["action"]),
                    target=row["target"],
                    rationale=row["rationale"],
                    utility=utility,
                    cost=row["cost"],
                )
            )
    except csv.Error as exc:
        raise ValueError(f"portfolio queue is malformed CSV: {exc}") from exc

    return PortfolioActionQueue(
        source_artifact=source_artifact,
        source_revision=source_revision,
        source_sha256=observed_sha256,
        analysis_code_hash=analysis_code_hash,
        evidence_boundary=evidence_boundary,
        actions=tuple(actions),
    )


@dataclass(frozen=True)
class ResultCell:
    """One absent benchmark-model-metric observation."""

    benchmark_id: str
    model_id: str
    metric: str

    def __post_init__(self) -> None:
        for name in ("benchmark_id", "model_id", "metric"):
            _require_text(name, getattr(self, name))

    def to_dict(self) -> dict[str, str]:
        return {
            "benchmark_id": self.benchmark_id,
            "model_id": self.model_id,
            "metric": self.metric,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResultCell":
        _require_fields(data, {"benchmark_id", "model_id", "metric"}, "result cell")
        return cls(
            benchmark_id=data["benchmark_id"],
            model_id=data["model_id"],
            metric=data["metric"],
        )


@dataclass(frozen=True)
class FingerprintSignalValidation:
    """Predeclared checks that distinguish a portfolio signal from raw difficulty."""

    difficulty_ability_baseline_hash: str
    residual_analysis_hash: str
    permutation_null_hash: str
    discovery_split_hash: str
    heldout_split_hash: str
    statistic_direction: FingerprintStatisticDirection
    discovery_threshold: float
    heldout_threshold: float
    maximum_permutation_p_value: float
    permutation_draws: int
    observed_statistic: float
    permutation_p_value: float
    heldout_statistic: float

    def __post_init__(self) -> None:
        for name in (
            "difficulty_ability_baseline_hash",
            "residual_analysis_hash",
            "permutation_null_hash",
            "discovery_split_hash",
            "heldout_split_hash",
        ):
            _require_hash(name, getattr(self, name))
        if self.discovery_split_hash == self.heldout_split_hash:
            raise ValueError(
                "discovery and heldout fingerprint splits must be distinct"
            )
        object.__setattr__(
            self,
            "statistic_direction",
            FingerprintStatisticDirection(self.statistic_direction),
        )
        if (
            isinstance(self.permutation_draws, bool)
            or not isinstance(self.permutation_draws, int)
            or self.permutation_draws < 100
        ):
            raise ValueError("permutation_draws must be an integer of at least 100")
        for name in (
            "discovery_threshold",
            "heldout_threshold",
            "observed_statistic",
            "heldout_statistic",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be finite")
        for name in ("maximum_permutation_p_value", "permutation_p_value"):
            if not _unit_interval(getattr(self, name)):
                raise ValueError(f"{name} must be between 0 and 1")

    @property
    def confirmed(self) -> bool:
        if self.statistic_direction is FingerprintStatisticDirection.GREATER_OR_EQUAL:
            discovery_passed = self.observed_statistic >= self.discovery_threshold
            heldout_passed = self.heldout_statistic >= self.heldout_threshold
        else:
            discovery_passed = self.observed_statistic <= self.discovery_threshold
            heldout_passed = self.heldout_statistic <= self.heldout_threshold
        return (
            self.permutation_p_value <= self.maximum_permutation_p_value
            and discovery_passed
            and heldout_passed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "difficulty_ability_baseline_hash": self.difficulty_ability_baseline_hash,
            "residual_analysis_hash": self.residual_analysis_hash,
            "permutation_null_hash": self.permutation_null_hash,
            "discovery_split_hash": self.discovery_split_hash,
            "heldout_split_hash": self.heldout_split_hash,
            "statistic_direction": self.statistic_direction.value,
            "discovery_threshold": self.discovery_threshold,
            "heldout_threshold": self.heldout_threshold,
            "maximum_permutation_p_value": self.maximum_permutation_p_value,
            "permutation_draws": self.permutation_draws,
            "observed_statistic": self.observed_statistic,
            "permutation_p_value": self.permutation_p_value,
            "heldout_statistic": self.heldout_statistic,
            "confirmed": self.confirmed,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FingerprintSignalValidation":
        fields = {
            "difficulty_ability_baseline_hash",
            "residual_analysis_hash",
            "permutation_null_hash",
            "discovery_split_hash",
            "heldout_split_hash",
            "statistic_direction",
            "discovery_threshold",
            "heldout_threshold",
            "maximum_permutation_p_value",
            "permutation_draws",
            "observed_statistic",
            "permutation_p_value",
            "heldout_statistic",
            "confirmed",
        }
        _require_fields(data, fields, "fingerprint signal validation")
        result = cls(
            **{
                name: data[name]
                for name in fields
                if name not in {"confirmed", "statistic_direction"}
            },
            statistic_direction=FingerprintStatisticDirection(
                data["statistic_direction"]
            ),
        )
        if data["confirmed"] is not result.confirmed:
            raise ValueError(
                "serialized fingerprint confirmation does not match its evidence"
            )
        return result


@dataclass(frozen=True)
class ConstructCoordinates:
    """Auditable a-priori location in benchmark construct space."""

    cognitive: Mapping[str, float]
    domain: Mapping[str, float]
    modality: Mapping[str, float]
    task_format: str
    scoring_method: str
    ground_truth_source: str
    ground_truth_reliability: float
    specialty_breadth: str
    realism: str
    harm_sensitivity: str
    scale_items: int
    source_origin: str
    coding_confidence: str

    def __post_init__(self) -> None:
        for name in (
            "task_format",
            "scoring_method",
            "ground_truth_source",
            "specialty_breadth",
            "realism",
            "harm_sensitivity",
            "source_origin",
        ):
            _require_text(name, getattr(self, name))
        if self.specialty_breadth not in {"narrow", "moderate", "broad"}:
            raise ValueError("specialty_breadth must be narrow, moderate, or broad")
        if self.coding_confidence not in {"low", "medium", "high"}:
            raise ValueError("coding_confidence must be low, medium, or high")
        if (
            isinstance(self.scale_items, bool)
            or not isinstance(self.scale_items, int)
            or self.scale_items < 1
        ):
            raise ValueError("scale_items must be a positive integer")
        object.__setattr__(
            self, "cognitive", _freeze_weights("cognitive", self.cognitive)
        )
        object.__setattr__(self, "domain", _freeze_weights("domain", self.domain))
        object.__setattr__(self, "modality", _freeze_weights("modality", self.modality))
        if not _unit_interval(self.ground_truth_reliability):
            raise ValueError("ground_truth_reliability must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "cognitive": dict(self.cognitive),
            "domain": dict(self.domain),
            "modality": dict(self.modality),
            "task_format": self.task_format,
            "scoring_method": self.scoring_method,
            "ground_truth_source": self.ground_truth_source,
            "ground_truth_reliability": self.ground_truth_reliability,
            "specialty_breadth": self.specialty_breadth,
            "realism": self.realism,
            "harm_sensitivity": self.harm_sensitivity,
            "scale_items": self.scale_items,
            "source_origin": self.source_origin,
            "coding_confidence": self.coding_confidence,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConstructCoordinates":
        fields = {
            "cognitive",
            "domain",
            "modality",
            "task_format",
            "scoring_method",
            "ground_truth_source",
            "ground_truth_reliability",
            "specialty_breadth",
            "realism",
            "harm_sensitivity",
            "scale_items",
            "source_origin",
            "coding_confidence",
        }
        _require_fields(data, fields, "construct coordinates")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True)
class OpportunityEvidence:
    """Hashes of the frozen geometry inputs and analysis artifacts."""

    portfolio_snapshot_hash: str
    construct_schema_hash: str
    result_matrix_hash: str
    analysis_code_hash: str
    signal_evidence_hash: str
    source_revision: str
    signal_validation: FingerprintSignalValidation | None = None

    def __post_init__(self) -> None:
        for name in (
            "portfolio_snapshot_hash",
            "construct_schema_hash",
            "result_matrix_hash",
            "analysis_code_hash",
            "signal_evidence_hash",
        ):
            _require_hash(name, getattr(self, name))
        _require_text("source_revision", self.source_revision)
        if self.signal_validation is not None and not isinstance(
            self.signal_validation,
            FingerprintSignalValidation,
        ):
            raise ValueError(
                "signal_validation must be FingerprintSignalValidation or null"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolio_snapshot_hash": self.portfolio_snapshot_hash,
            "construct_schema_hash": self.construct_schema_hash,
            "result_matrix_hash": self.result_matrix_hash,
            "analysis_code_hash": self.analysis_code_hash,
            "signal_evidence_hash": self.signal_evidence_hash,
            "source_revision": self.source_revision,
            "signal_validation": (
                self.signal_validation.to_dict()
                if self.signal_validation is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OpportunityEvidence":
        fields = {
            "portfolio_snapshot_hash",
            "construct_schema_hash",
            "result_matrix_hash",
            "analysis_code_hash",
            "signal_evidence_hash",
            "source_revision",
            "signal_validation",
        }
        _require_fields(data, fields, "opportunity evidence")
        values = {name: data[name] for name in fields}
        validation = values.pop("signal_validation")
        return cls(
            **values,
            signal_validation=(
                FingerprintSignalValidation.from_dict(validation)
                if validation is not None
                else None
            ),
        )


@dataclass(frozen=True)
class ClinicalNeedOwnership:
    """The human-owned clinical need that geometry may inform, not decide."""

    need_statement: str
    clinical_owner: str
    owner_role: str
    intended_users: tuple[str, ...]
    review_status: NeedReviewStatus = NeedReviewStatus.PROPOSED
    attestation_hash: str | None = None

    def __post_init__(self) -> None:
        _require_text("need_statement", self.need_statement)
        _require_text("clinical_owner", self.clinical_owner)
        _require_text("owner_role", self.owner_role)
        users = _text_tuple("intended_users", self.intended_users)
        if not users:
            raise ValueError("intended_users must not be empty")
        if len(set(users)) != len(users):
            raise ValueError("intended_users must be unique")
        object.__setattr__(self, "intended_users", users)
        object.__setattr__(self, "review_status", NeedReviewStatus(self.review_status))
        if self.review_status is NeedReviewStatus.CLINICIAN_ATTESTED:
            if self.attestation_hash is None:
                raise ValueError("clinician-attested needs require attestation_hash")
            _require_hash("attestation_hash", self.attestation_hash)
        elif self.attestation_hash is not None:
            raise ValueError("proposed needs cannot carry an attestation_hash")

    def to_dict(self) -> dict[str, Any]:
        return {
            "need_statement": self.need_statement,
            "clinical_owner": self.clinical_owner,
            "owner_role": self.owner_role,
            "intended_users": list(self.intended_users),
            "review_status": self.review_status.value,
            "attestation_hash": self.attestation_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ClinicalNeedOwnership":
        fields = {
            "need_statement",
            "clinical_owner",
            "owner_role",
            "intended_users",
            "review_status",
            "attestation_hash",
        }
        _require_fields(data, fields, "clinical need ownership")
        return cls(
            need_statement=data["need_statement"],
            clinical_owner=data["clinical_owner"],
            owner_role=data["owner_role"],
            intended_users=tuple(data["intended_users"]),
            review_status=NeedReviewStatus(data["review_status"]),
            attestation_hash=data["attestation_hash"],
        )


@dataclass(frozen=True)
class PilotTargets:
    """Predeclared scale and measurement targets for a candidate pilot."""

    item_count: int
    model_count: int
    trials_per_item: int
    primary_metrics: tuple[str, ...]
    minimum_headroom: float | None = None
    minimum_tier_count: int | None = None

    def __post_init__(self) -> None:
        for name in ("item_count", "model_count", "trials_per_item"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        metrics = _text_tuple("primary_metrics", self.primary_metrics)
        if not metrics:
            raise ValueError("primary_metrics must not be empty")
        if len(set(metrics)) != len(metrics):
            raise ValueError("primary_metrics must be unique")
        object.__setattr__(self, "primary_metrics", metrics)
        if self.minimum_headroom is not None and not _unit_interval(
            self.minimum_headroom
        ):
            raise ValueError("minimum_headroom must be between 0 and 1")
        if self.minimum_tier_count is not None:
            if (
                isinstance(self.minimum_tier_count, bool)
                or not isinstance(self.minimum_tier_count, int)
                or self.minimum_tier_count < 1
                or self.minimum_tier_count > self.model_count
            ):
                raise ValueError("minimum_tier_count must be between 1 and model_count")

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_count": self.item_count,
            "model_count": self.model_count,
            "trials_per_item": self.trials_per_item,
            "primary_metrics": list(self.primary_metrics),
            "minimum_headroom": self.minimum_headroom,
            "minimum_tier_count": self.minimum_tier_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PilotTargets":
        fields = {
            "item_count",
            "model_count",
            "trials_per_item",
            "primary_metrics",
            "minimum_headroom",
            "minimum_tier_count",
        }
        _require_fields(data, fields, "pilot targets")
        return cls(
            item_count=data["item_count"],
            model_count=data["model_count"],
            trials_per_item=data["trials_per_item"],
            primary_metrics=tuple(data["primary_metrics"]),
            minimum_headroom=data["minimum_headroom"],
            minimum_tier_count=data["minimum_tier_count"],
        )


@dataclass(frozen=True)
class PortfolioOpportunity(CanonicalRecord):
    """Frozen planning evidence for one portfolio action candidate."""

    id: str
    signal: OpportunitySignal
    evidence: OpportunityEvidence
    evidence_boundary: EvidenceBoundary
    construct_coordinates: ConstructCoordinates | None = None
    clinical_need: ClinicalNeedOwnership | None = None
    pilot_targets: PilotTargets | None = None
    maintenance_action: str | None = None
    collection_protocol_hash: str | None = None
    missing_result_cells: tuple[ResultCell, ...] = ()
    decision_scope: str = DECISION_SCOPE
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text("id", self.id)
        object.__setattr__(self, "signal", OpportunitySignal(self.signal))
        if not isinstance(self.evidence, OpportunityEvidence):
            raise ValueError("evidence must be OpportunityEvidence")
        if not isinstance(self.evidence_boundary, EvidenceBoundary):
            raise ValueError("evidence_boundary must be EvidenceBoundary")
        if (
            self.evidence_boundary.released_artifact_hash
            != self.evidence.signal_evidence_hash
        ):
            raise ValueError(
                "evidence boundary must bind the released signal-evidence artifact"
            )
        if self.construct_coordinates is not None and not isinstance(
            self.construct_coordinates, ConstructCoordinates
        ):
            raise ValueError(
                "construct_coordinates must be ConstructCoordinates or null"
            )
        if self.clinical_need is not None and not isinstance(
            self.clinical_need, ClinicalNeedOwnership
        ):
            raise ValueError("clinical_need must be ClinicalNeedOwnership or null")
        if self.pilot_targets is not None and not isinstance(
            self.pilot_targets, PilotTargets
        ):
            raise ValueError("pilot_targets must be PilotTargets or null")
        cells = tuple(self.missing_result_cells)
        if not all(isinstance(cell, ResultCell) for cell in cells):
            raise ValueError("missing_result_cells must contain ResultCell values")
        object.__setattr__(self, "missing_result_cells", cells)
        if len({(c.benchmark_id, c.model_id, c.metric) for c in cells}) != len(cells):
            raise ValueError("missing_result_cells must be unique")
        if self.signal is OpportunitySignal.COVERAGE_GAP:
            if self.evidence.signal_validation is None:
                raise ValueError(
                    "coverage-gap opportunities require validated fingerprint evidence"
                )
            if not self.evidence.signal_validation.confirmed:
                raise ValueError(
                    "coverage-gap fingerprint evidence must pass its frozen rule"
                )
            if self.construct_coordinates is None:
                raise ValueError(
                    "coverage-gap opportunities require construct coordinates"
                )
            if self.clinical_need is None or self.pilot_targets is None:
                raise ValueError(
                    "coverage-gap opportunities require a clinical need and pilot targets"
                )
            if self.maintenance_action is not None:
                raise ValueError(
                    "coverage-gap opportunities cannot carry maintenance actions"
                )
            if self.collection_protocol_hash is not None:
                raise ValueError(
                    "coverage-gap opportunities cannot carry collection protocols"
                )
            if cells:
                raise ValueError(
                    "coverage-gap opportunities cannot contain missing result cells"
                )
        elif self.signal in (
            OpportunitySignal.REDUNDANCY,
            OpportunitySignal.SATURATION,
        ):
            if self.evidence.signal_validation is None:
                raise ValueError(
                    "portfolio-maintenance opportunities require validated fingerprint evidence"
                )
            if not self.evidence.signal_validation.confirmed:
                raise ValueError(
                    "portfolio-maintenance fingerprint evidence must pass its frozen rule"
                )
            if self.construct_coordinates is None:
                raise ValueError(
                    "portfolio-maintenance opportunities require construct coordinates"
                )
            if self.clinical_need is not None or self.pilot_targets is not None:
                raise ValueError(
                    "redundancy and saturation route to maintenance, not clinical benchmark pilots"
                )
            _require_text("maintenance_action", self.maintenance_action)
            if self.collection_protocol_hash is not None or cells:
                raise ValueError(
                    "portfolio-maintenance opportunities cannot carry result-collection fields"
                )
        else:
            if self.evidence.signal_validation is not None:
                raise ValueError(
                    "missing-result-cells evidence cannot claim a fingerprint signal"
                )
            if not cells:
                raise ValueError(
                    "missing-result-cells opportunities require missing cells"
                )
            if any(
                value is not None
                for value in (
                    self.construct_coordinates,
                    self.clinical_need,
                    self.pilot_targets,
                    self.maintenance_action,
                )
            ):
                raise ValueError(
                    "missing-result-cells routes to collection, not benchmark design or maintenance"
                )
            _require_hash("collection_protocol_hash", self.collection_protocol_hash)
        if self.decision_scope != DECISION_SCOPE:
            raise ValueError(f"decision_scope must be {DECISION_SCOPE!r}")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION!r}")

    @property
    def track(self) -> OpportunityTrack:
        if self.signal is OpportunitySignal.MISSING_RESULT_CELLS:
            return OpportunityTrack.RESULT_COLLECTION
        if self.signal in (OpportunitySignal.REDUNDANCY, OpportunitySignal.SATURATION):
            return OpportunityTrack.PORTFOLIO_MAINTENANCE
        return OpportunityTrack.BENCHMARK_DESIGN

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_scope": self.decision_scope,
            "id": self.id,
            "signal": self.signal.value,
            "track": self.track.value,
            "evidence": self.evidence.to_dict(),
            "evidence_boundary": self.evidence_boundary.to_dict(),
            "construct_coordinates": (
                self.construct_coordinates.to_dict()
                if self.construct_coordinates is not None
                else None
            ),
            "clinical_need": (
                self.clinical_need.to_dict() if self.clinical_need is not None else None
            ),
            "pilot_targets": (
                self.pilot_targets.to_dict() if self.pilot_targets is not None else None
            ),
            "maintenance_action": self.maintenance_action,
            "collection_protocol_hash": self.collection_protocol_hash,
            "missing_result_cells": [
                cell.to_dict() for cell in self.missing_result_cells
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PortfolioOpportunity":
        fields = {
            "schema_version",
            "decision_scope",
            "id",
            "signal",
            "track",
            "evidence",
            "evidence_boundary",
            "construct_coordinates",
            "clinical_need",
            "pilot_targets",
            "maintenance_action",
            "collection_protocol_hash",
            "missing_result_cells",
        }
        _require_fields(data, fields, "portfolio opportunity")
        opportunity = cls(
            id=data["id"],
            signal=OpportunitySignal(data["signal"]),
            evidence=OpportunityEvidence.from_dict(data["evidence"]),
            evidence_boundary=EvidenceBoundary.from_dict(data["evidence_boundary"]),
            construct_coordinates=(
                ConstructCoordinates.from_dict(data["construct_coordinates"])
                if data["construct_coordinates"] is not None
                else None
            ),
            clinical_need=(
                ClinicalNeedOwnership.from_dict(data["clinical_need"])
                if data["clinical_need"] is not None
                else None
            ),
            pilot_targets=(
                PilotTargets.from_dict(data["pilot_targets"])
                if data["pilot_targets"] is not None
                else None
            ),
            maintenance_action=data["maintenance_action"],
            collection_protocol_hash=data["collection_protocol_hash"],
            missing_result_cells=tuple(
                ResultCell.from_dict(cell) for cell in data["missing_result_cells"]
            ),
            decision_scope=data["decision_scope"],
            schema_version=data["schema_version"],
        )
        if data["track"] != opportunity.track.value:
            raise ValueError("serialized track does not match opportunity signal")
        return opportunity


def _freeze_weights(name: str, values: Mapping[str, float]) -> Mapping[str, float]:
    if not isinstance(values, Mapping) or not values:
        raise ValueError(f"{name} weights must be a non-empty object")
    frozen: dict[str, float] = {}
    for key, value in values.items():
        _require_text(f"{name} key", key)
        if not _unit_interval(value):
            raise ValueError(f"{name}.{key} must be between 0 and 1")
        frozen[key] = float(value)
    if not math.isclose(sum(frozen.values()), 1.0, abs_tol=1e-6):
        raise ValueError(f"{name} weights must sum to 1")
    return MappingProxyType(frozen)


def _unit_interval(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and 0.0 <= float(value) <= 1.0
    )


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


def _require_fields(data: Mapping[str, Any], fields: set[str], label: str) -> None:
    if not isinstance(data, Mapping):
        raise ValueError(f"{label} must be an object")
    present = set(data)
    missing = fields - present
    unknown = present - fields
    if missing or unknown:
        raise ValueError(
            f"invalid {label} fields; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


__all__ = [
    "ClinicalNeedOwnership",
    "ConstructCoordinates",
    "EvidenceAccessClass",
    "EvidenceBoundary",
    "FingerprintStatisticDirection",
    "FingerprintSignalValidation",
    "NeedReviewStatus",
    "OpportunityEvidence",
    "OpportunitySignal",
    "OpportunityTrack",
    "PilotTargets",
    "PortfolioActionCandidate",
    "PortfolioActionKind",
    "PortfolioActionQueue",
    "PortfolioOpportunity",
    "ResultCell",
    "load_portfolio_action_queue",
]
