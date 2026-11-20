"""Reporting artifacts (ASSURE).

Assembles the evidence from a completed run into human-readable
governance artifacts: a CHAI-style applied model card and
reporting-standard checklist coverage. Every artifact is framed as
evidence assembly for a qualified human owner, never as a certification
or a clearance. A run can only fill the measured parts (metrics, cost,
item count); everything else is stamped for human input or routed to the
skill that owns it.
"""

from __future__ import annotations

from arisekit.report.checklist import (
    AUTO_SOURCES,
    Checklist,
    ChecklistItem,
    ChecklistItemStatus,
    ChecklistReport,
)
from arisekit.report.model_card import (
    DISCLAIMER,
    REQUIRES_HUMAN_INPUT,
    ModelCard,
)

__all__ = [
    "ModelCard",
    "REQUIRES_HUMAN_INPUT",
    "DISCLAIMER",
    "Checklist",
    "ChecklistItem",
    "ChecklistItemStatus",
    "ChecklistReport",
    "AUTO_SOURCES",
]
