"""Pre-inference readiness contract for generated-versus-reference studies."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from arisekit.common.validate import exact_fields as _fields, number, sha256_hex, text


SCHEMA_VERSION = "arisekit.parity-readiness.v1"


@dataclass(frozen=True)
class ClinicalReviewReadiness:
    review_artifact_hash: str
    reviewer_ids: tuple[str, ...]
    adjudicator_id: str
    reviewed_family_count: int
    expected_family_count: int
    critical_defect_count: int
    unresolved_disagreement_count: int

    def __post_init__(self) -> None:
        _hash("review_artifact_hash", self.review_artifact_hash)
        reviewers = _texts("reviewer_ids", self.reviewer_ids)
        if len(reviewers) < 2 or len(set(reviewers)) != len(reviewers):
            raise ValueError("clinical review requires at least two distinct reviewers")
        object.__setattr__(self, "reviewer_ids", reviewers)
        _text("adjudicator_id", self.adjudicator_id)
        if self.adjudicator_id in reviewers:
            raise ValueError("clinical adjudicator must be independent of primary reviewers")
        for name in (
            "reviewed_family_count",
            "expected_family_count",
            "critical_defect_count",
            "unresolved_disagreement_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.expected_family_count < 1:
            raise ValueError("expected_family_count must be positive")
        if self.reviewed_family_count > self.expected_family_count:
            raise ValueError("reviewed_family_count cannot exceed expected_family_count")

    @property
    def ready(self) -> bool:
        return (
            self.reviewed_family_count == self.expected_family_count
            and self.critical_defect_count == 0
            and self.unresolved_disagreement_count == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_artifact_hash": self.review_artifact_hash,
            "reviewer_ids": list(self.reviewer_ids),
            "adjudicator_id": self.adjudicator_id,
            "reviewed_family_count": self.reviewed_family_count,
            "expected_family_count": self.expected_family_count,
            "critical_defect_count": self.critical_defect_count,
            "unresolved_disagreement_count": self.unresolved_disagreement_count,
            "ready": self.ready,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ClinicalReviewReadiness":
        fields = {
            "review_artifact_hash",
            "reviewer_ids",
            "adjudicator_id",
            "reviewed_family_count",
            "expected_family_count",
            "critical_defect_count",
            "unresolved_disagreement_count",
            "ready",
        }
        _fields(data, fields, "clinical review readiness")
        result = cls(
            review_artifact_hash=data["review_artifact_hash"],
            reviewer_ids=_string_list(
                "clinical review reviewer_ids",
                data["reviewer_ids"],
            ),
            adjudicator_id=data["adjudicator_id"],
            reviewed_family_count=data["reviewed_family_count"],
            expected_family_count=data["expected_family_count"],
            critical_defect_count=data["critical_defect_count"],
            unresolved_disagreement_count=data["unresolved_disagreement_count"],
        )
        if data["ready"] is not result.ready:
            raise ValueError("serialized clinical readiness does not match evidence")
        return result


@dataclass(frozen=True)
class SourceSimilarityReadiness:
    report_hash: str
    analysis_code_hash: str
    representation_schema_hash: str
    similarity_metric: str
    comparison_count: int
    rejection_threshold: float
    maximum_observed_similarity: float

    def __post_init__(self) -> None:
        for name in ("report_hash", "analysis_code_hash", "representation_schema_hash"):
            _hash(name, getattr(self, name))
        _text("similarity_metric", self.similarity_metric)
        if (
            isinstance(self.comparison_count, bool)
            or not isinstance(self.comparison_count, int)
            or self.comparison_count < 1
        ):
            raise ValueError("comparison_count must be a positive integer")
        for name in ("rejection_threshold", "maximum_observed_similarity"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= float(value) <= 1
            ):
                raise ValueError(f"{name} must be finite and between 0 and 1")
            object.__setattr__(self, name, float(value))

    @property
    def ready(self) -> bool:
        return self.maximum_observed_similarity < self.rejection_threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_hash": self.report_hash,
            "analysis_code_hash": self.analysis_code_hash,
            "representation_schema_hash": self.representation_schema_hash,
            "similarity_metric": self.similarity_metric,
            "comparison_count": self.comparison_count,
            "rejection_threshold": self.rejection_threshold,
            "maximum_observed_similarity": self.maximum_observed_similarity,
            "ready": self.ready,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceSimilarityReadiness":
        fields = {
            "report_hash",
            "analysis_code_hash",
            "representation_schema_hash",
            "similarity_metric",
            "comparison_count",
            "rejection_threshold",
            "maximum_observed_similarity",
            "ready",
        }
        _fields(data, fields, "source similarity readiness")
        result = cls(**{name: data[name] for name in fields - {"ready"}})
        if data["ready"] is not result.ready:
            raise ValueError("serialized source-similarity readiness does not match evidence")
        return result


@dataclass(frozen=True)
class AnalysisReadiness:
    same_vs_same_report_hash: str
    level_margin_lower: float
    level_margin_upper: float
    maximum_profile_distance: float
    bootstrap_draws: int
    bootstrap_seed: int
    clinical_approver: str
    statistical_approver: str
    approved_at: str

    def __post_init__(self) -> None:
        _hash("same_vs_same_report_hash", self.same_vs_same_report_hash)
        lower = _finite("level_margin_lower", self.level_margin_lower)
        upper = _finite("level_margin_upper", self.level_margin_upper)
        profile = _finite("maximum_profile_distance", self.maximum_profile_distance)
        if not lower < 0 < upper:
            raise ValueError("level parity margins must straddle zero")
        if profile <= 0:
            raise ValueError("maximum_profile_distance must be positive")
        object.__setattr__(self, "level_margin_lower", lower)
        object.__setattr__(self, "level_margin_upper", upper)
        object.__setattr__(self, "maximum_profile_distance", profile)
        if (
            isinstance(self.bootstrap_draws, bool)
            or not isinstance(self.bootstrap_draws, int)
            or self.bootstrap_draws < 1000
        ):
            raise ValueError("bootstrap_draws must be an integer of at least 1000")
        if isinstance(self.bootstrap_seed, bool) or not isinstance(
            self.bootstrap_seed,
            int,
        ):
            raise ValueError("bootstrap_seed must be an integer")
        for name in ("clinical_approver", "statistical_approver", "approved_at"):
            _text(name, getattr(self, name))
        if self.clinical_approver == self.statistical_approver:
            raise ValueError("clinical and statistical approvers must be distinct")

    def to_dict(self) -> dict[str, Any]:
        return {
            "same_vs_same_report_hash": self.same_vs_same_report_hash,
            "level_margin_lower": self.level_margin_lower,
            "level_margin_upper": self.level_margin_upper,
            "maximum_profile_distance": self.maximum_profile_distance,
            "bootstrap_draws": self.bootstrap_draws,
            "bootstrap_seed": self.bootstrap_seed,
            "clinical_approver": self.clinical_approver,
            "statistical_approver": self.statistical_approver,
            "approved_at": self.approved_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AnalysisReadiness":
        fields = {
            "same_vs_same_report_hash",
            "level_margin_lower",
            "level_margin_upper",
            "maximum_profile_distance",
            "bootstrap_draws",
            "bootstrap_seed",
            "clinical_approver",
            "statistical_approver",
            "approved_at",
        }
        _fields(data, fields, "analysis readiness")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True)
class ParityReadinessRecord:
    generated_bundle_hash: str
    clinical_review: ClinicalReviewReadiness
    source_similarity: SourceSimilarityReadiness
    analysis: AnalysisReadiness
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _hash("generated_bundle_hash", self.generated_bundle_hash)
        if not isinstance(self.clinical_review, ClinicalReviewReadiness):
            raise ValueError("clinical_review must be ClinicalReviewReadiness")
        if not isinstance(self.source_similarity, SourceSimilarityReadiness):
            raise ValueError("source_similarity must be SourceSimilarityReadiness")
        if not isinstance(self.analysis, AnalysisReadiness):
            raise ValueError("analysis must be AnalysisReadiness")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION!r}")

    @property
    def ready(self) -> bool:
        return self.clinical_review.ready and self.source_similarity.ready

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.clinical_review.ready:
            blockers.append("clinical-review")
        if not self.source_similarity.ready:
            blockers.append("source-similarity")
        return tuple(blockers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_bundle_hash": self.generated_bundle_hash,
            "clinical_review": self.clinical_review.to_dict(),
            "source_similarity": self.source_similarity.to_dict(),
            "analysis": self.analysis.to_dict(),
            "ready": self.ready,
            "blockers": list(self.blockers),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ParityReadinessRecord":
        fields = {
            "schema_version",
            "generated_bundle_hash",
            "clinical_review",
            "source_similarity",
            "analysis",
            "ready",
            "blockers",
        }
        _fields(data, fields, "parity readiness record")
        result = cls(
            generated_bundle_hash=data["generated_bundle_hash"],
            clinical_review=ClinicalReviewReadiness.from_dict(data["clinical_review"]),
            source_similarity=SourceSimilarityReadiness.from_dict(
                data["source_similarity"]
            ),
            analysis=AnalysisReadiness.from_dict(data["analysis"]),
            schema_version=data["schema_version"],
        )
        blockers = _string_list("parity readiness blockers", data["blockers"])
        if data["ready"] is not result.ready or blockers != result.blockers:
            raise ValueError("serialized parity readiness does not match its evidence")
        return result

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()


def _text(name: str, value: Any) -> str:
    return text(value, name, no_outer_whitespace=True)


def _texts(name: str, value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence of strings")
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be a sequence of strings") from exc
    for item in values:
        _text(name, item)
    return values


def _string_list(name: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array of strings")
    return _texts(name, value)


def _hash(name: str, value: Any) -> str:
    return sha256_hex(value, name)


def _finite(name: str, value: Any) -> float:
    return number(value, name)


__all__ = [
    "AnalysisReadiness",
    "ClinicalReviewReadiness",
    "ParityReadinessRecord",
    "SourceSimilarityReadiness",
]
