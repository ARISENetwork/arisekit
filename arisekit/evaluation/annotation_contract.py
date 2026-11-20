"""Boundary between study methodology and annotation operations."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arisekit.common.jsonio import freeze_json, thaw_json as _thaw_json
from arisekit.common.records import CanonicalPropertyRecord, CanonicalRecord
from arisekit.common.validate import (
    exact_fields,
    identifier,
    number as _finite,
    positive_int as _positive_int,
    sha256_hex as _sha256,
    text as _text,
)


POLICY_SCHEMA_VERSION = "arisekit.annotation-study-policy.v1"
EXECUTION_SCHEMA_VERSION = "arisekit.annotation-execution.v1"
RESULT_SCHEMA_VERSION = "arisekit.annotation-result.v1"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class StudyAnnotationPolicy(CanonicalPropertyRecord):
    """Frozen methodology owned by ``study-design``."""

    population: str
    credential_requirements: Mapping[str, Any]
    panel_size_per_item: int
    calibration_policy: Mapping[str, Any]
    irr_method: str
    irr_threshold: float
    adjudication_policy: Mapping[str, Any]
    schema_version: str = POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != POLICY_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {POLICY_SCHEMA_VERSION!r}")
        _text(self.population, "population")
        _positive_int(self.panel_size_per_item, "panel_size_per_item")
        _text(self.irr_method, "irr_method")
        threshold = _finite(self.irr_threshold, "irr_threshold")
        if not 0 <= threshold <= 1:
            raise ValueError("irr_threshold must be between zero and one")
        object.__setattr__(self, "irr_threshold", threshold)
        for name in (
            "credential_requirements",
            "calibration_policy",
            "adjudication_policy",
        ):
            value = _freeze_json(getattr(self, name), name)
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "population": self.population,
            "credential_requirements": _thaw_json(self.credential_requirements),
            "panel_size_per_item": self.panel_size_per_item,
            "calibration_policy": _thaw_json(self.calibration_policy),
            "irr_method": self.irr_method,
            "irr_threshold": self.irr_threshold,
            "adjudication_policy": _thaw_json(self.adjudication_policy),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StudyAnnotationPolicy":
        expected = {
            "schema_version",
            "population",
            "credential_requirements",
            "panel_size_per_item",
            "calibration_policy",
            "irr_method",
            "irr_threshold",
            "adjudication_policy",
        }
        _fields(data, expected, "annotation study policy")
        for name in (
            "credential_requirements",
            "calibration_policy",
            "adjudication_policy",
        ):
            if not isinstance(data[name], Mapping):
                raise ValueError(f"{name} must be an object")
        return cls(**{name: data[name] for name in expected})


def load_study_policy(path: str | Path) -> StudyAnnotationPolicy:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load annotation study policy: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("annotation study policy must be a JSON object")
    return StudyAnnotationPolicy.from_dict(raw)


def write_study_policy(
    path: str | Path,
    policy: StudyAnnotationPolicy,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = (policy.canonical_json + "\n").encode("utf-8")
    fd, raw_temp = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, destination)
    finally:
        if temp.exists():
            temp.unlink()
    return destination


@dataclass(frozen=True)
class AnnotationAssignment:
    item_id: str
    rater_id: str

    def __post_init__(self) -> None:
        _identifier(self.item_id, "item_id")
        _identifier(self.rater_id, "rater_id")

    def to_dict(self) -> dict[str, str]:
        return {"item_id": self.item_id, "rater_id": self.rater_id}


@dataclass(frozen=True)
class AnnotationExecutionSpec(CanonicalRecord):
    """Operational plan owned by Annotation; methodology remains by digest."""

    annotation_id: str
    study_policy_digest: str
    item_bundle_digest: str
    assignments: tuple[AnnotationAssignment, ...]
    output_artifact: str
    schema_version: str = EXECUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {EXECUTION_SCHEMA_VERSION!r}")
        _identifier(self.annotation_id, "annotation_id")
        _sha256(self.study_policy_digest, "study_policy_digest")
        _sha256(self.item_bundle_digest, "item_bundle_digest")
        _text(self.output_artifact, "output_artifact")
        assignments = tuple(self.assignments)
        if not assignments:
            raise ValueError("assignments must not be empty")
        pairs = [(entry.item_id, entry.rater_id) for entry in assignments]
        if len(pairs) != len(set(pairs)):
            raise ValueError("assignments contain duplicate item/rater pairs")
        object.__setattr__(self, "assignments", assignments)

    def validate_against(self, policy: StudyAnnotationPolicy) -> None:
        if self.study_policy_digest != policy.digest:
            raise ValueError("annotation execution references a different study policy")
        counts = Counter(assignment.item_id for assignment in self.assignments)
        undersized = sorted(
            item_id
            for item_id, count in counts.items()
            if count < policy.panel_size_per_item
        )
        if undersized:
            raise ValueError(
                "annotation assignments do not satisfy panel_size_per_item for: "
                + ", ".join(undersized)
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "annotation_id": self.annotation_id,
            "study_policy_digest": self.study_policy_digest,
            "item_bundle_digest": self.item_bundle_digest,
            "assignments": [entry.to_dict() for entry in self.assignments],
            "output_artifact": self.output_artifact,
        }


@dataclass(frozen=True)
class AnnotationLabel:
    item_id: str
    label: Any
    irr_value: float | None
    adjudicated: bool

    def __post_init__(self) -> None:
        _identifier(self.item_id, "item_id")
        object.__setattr__(self, "label", _freeze_json(self.label, "label"))
        if self.irr_value is not None:
            value = _finite(self.irr_value, "irr_value")
            if not 0 <= value <= 1:
                raise ValueError("irr_value must be between zero and one")
            object.__setattr__(self, "irr_value", value)
        if not isinstance(self.adjudicated, bool):
            raise ValueError("adjudicated must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "label": _thaw_json(self.label),
            "irr_value": self.irr_value,
            "adjudicated": self.adjudicated,
        }


@dataclass(frozen=True)
class AnnotationResultBundle(CanonicalRecord):
    annotation_execution_digest: str
    study_policy_digest: str
    item_bundle_digest: str
    labels: tuple[AnnotationLabel, ...]
    schema_version: str = RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESULT_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {RESULT_SCHEMA_VERSION!r}")
        for name in (
            "annotation_execution_digest",
            "study_policy_digest",
            "item_bundle_digest",
        ):
            _sha256(getattr(self, name), name)
        labels = tuple(self.labels)
        if not labels:
            raise ValueError("labels must not be empty")
        ids = [label.item_id for label in labels]
        if len(ids) != len(set(ids)):
            raise ValueError("labels contain duplicate item ids")
        object.__setattr__(self, "labels", labels)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "annotation_execution_digest": self.annotation_execution_digest,
            "study_policy_digest": self.study_policy_digest,
            "item_bundle_digest": self.item_bundle_digest,
            "labels": [label.to_dict() for label in self.labels],
        }


def _freeze_json(value: Any, path: str) -> Any:
    return freeze_json(value, path, sort_keys=True)


def _fields(data: Any, expected: set[str], label: str) -> None:
    exact_fields(data, expected, label, kind=None)


def _identifier(value: Any, label: str) -> str:
    return identifier(value, label, _ID_RE)


__all__ = [
    "EXECUTION_SCHEMA_VERSION",
    "POLICY_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION",
    "AnnotationAssignment",
    "AnnotationExecutionSpec",
    "AnnotationLabel",
    "AnnotationResultBundle",
    "StudyAnnotationPolicy",
    "load_study_policy",
    "write_study_policy",
]
