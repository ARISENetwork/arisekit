"""Dormant, advisory-only identifier signal hook.

ARISEKit assumes benchmark inputs have already been stripped by the owning
institution.  This module can record coarse heuristic signals in the
background, but it never redacts data, blocks a workflow, or represents a
privacy or de-identification determination.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any


SCHEMA_VERSION = "arisekit.privacy-signal.v1"
DISCLAIMER = (
    "No signals detected means only that the configured heuristics found no "
    "matches. It is not a privacy, disclosure, or compliance determination."
)


class PrivacySignalStatus(str, Enum):
    NOT_ASSESSED = "not_assessed"
    SIGNALS_DETECTED = "signals_detected"
    NO_SIGNALS_DETECTED = "no_signals_detected"


@dataclass(frozen=True)
class PrivacySignalAssessment:
    status: PrivacySignalStatus
    signal_counts: Mapping[str, int]
    detector_id: str = "arisekit.passive-identifier-heuristics"
    detector_version: str = "1"
    schema_version: str = SCHEMA_VERSION
    disclaimer: str = DISCLAIMER

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION!r}")
        if not isinstance(self.status, PrivacySignalStatus):
            object.__setattr__(self, "status", PrivacySignalStatus(self.status))
        if not self.detector_id.strip() or not self.detector_version.strip():
            raise ValueError("detector identity must not be empty")
        if self.disclaimer != DISCLAIMER:
            raise ValueError("privacy signal assessment must preserve the canonical disclaimer")
        counts: dict[str, int] = {}
        for category, count in self.signal_counts.items():
            if not isinstance(category, str) or not category.strip():
                raise ValueError("signal category must be a non-empty string")
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise ValueError("signal counts must be positive integers")
            counts[category] = count
        if self.status == PrivacySignalStatus.NOT_ASSESSED and counts:
            raise ValueError("not_assessed cannot contain signals")
        if self.status == PrivacySignalStatus.SIGNALS_DETECTED and not counts:
            raise ValueError("signals_detected requires at least one signal")
        if self.status == PrivacySignalStatus.NO_SIGNALS_DETECTED and counts:
            raise ValueError("no_signals_detected cannot contain signals")
        object.__setattr__(
            self,
            "signal_counts",
            MappingProxyType(dict(sorted(counts.items()))),
        )

    @classmethod
    def not_assessed(cls) -> "PrivacySignalAssessment":
        return cls(
            status=PrivacySignalStatus.NOT_ASSESSED,
            signal_counts={},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "signal_counts": dict(self.signal_counts),
            "detector_id": self.detector_id,
            "detector_version": self.detector_version,
            "disclaimer": self.disclaimer,
        }


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "email_like",
        re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", re.I),
    ),
    (
        "phone_like",
        re.compile(r"(?<!\d)(?:\+?1[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?!\d)"),
    ),
    (
        "ssn_like",
        re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
    ),
    (
        "mrn_labeled",
        re.compile(r"\b(?:MRN|medical record(?: number)?)\s*[:#-]?\s*[A-Z0-9-]{5,}\b", re.I),
    ),
    (
        "ip_address_like",
        re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"),
    ),
    (
        "url_like",
        re.compile(r"\bhttps?://[^\s<>()]+", re.I),
    ),
)


def assess_text_signals(fields: Mapping[str, str]) -> PrivacySignalAssessment:
    """Return only category counts; matched text and field values are discarded."""

    if not isinstance(fields, Mapping):
        raise TypeError("fields must be a mapping of field name to text")
    counts: Counter[str] = Counter()
    for name, value in fields.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("field names must be non-empty strings")
        if not isinstance(value, str):
            raise ValueError(f"field {name!r} must contain text")
        for category, pattern in _PATTERNS:
            counts[category] += sum(1 for _ in pattern.finditer(value))
    signals = {category: count for category, count in counts.items() if count > 0}
    return PrivacySignalAssessment(
        status=(
            PrivacySignalStatus.SIGNALS_DETECTED
            if signals
            else PrivacySignalStatus.NO_SIGNALS_DETECTED
        ),
        signal_counts=signals,
    )


__all__ = [
    "DISCLAIMER",
    "SCHEMA_VERSION",
    "PrivacySignalAssessment",
    "PrivacySignalStatus",
    "assess_text_signals",
]
