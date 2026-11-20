"""Reporting-standard checklist coverage (ASSURE).

Loads a paraphrased reporting-standard checklist (e.g. a TRIPOD-LLM
adaptation) and evaluates how much of it a completed run can auto-satisfy.

Be honest: a run auto-satisfies only a minority of checklist items (the
measured performance metrics, and the evaluation cost when a spend is
recorded). Everything a run cannot compute routes to the upstream skill
that owns it, so the coverage report reads as a map of outstanding work,
never as a certification.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# auto_source kinds a run could conceivably fill. A plain run supplies
# only "metrics" (always) and "cost" (when a positive spend is recorded);
# "calibration" and "subgroup" require the caller to declare them present.
AUTO_SOURCES = ("metrics", "calibration", "subgroup", "cost")

_CHECKLIST_DIR = Path(__file__).parent / "checklists"


@dataclass
class ChecklistItem:
    """One reporting-standard item.

    ``auto_source`` names the run-derived evidence kind that would satisfy
    the item (or ``None`` if no run can). ``owning_skill`` names the
    upstream skill responsible for the item when a run cannot fill it.
    """

    id: str
    text: str
    section: str
    auto_source: str | None
    owning_skill: str | None


@dataclass
class Checklist:
    """A named list of checklist items, loaded from packaged JSON."""

    name: str
    items: list[ChecklistItem]

    @classmethod
    def load(cls, name: str) -> "Checklist":
        """Load ``checklists/{name}.json`` shipped alongside this module."""
        path = _CHECKLIST_DIR / f"{name}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        items = [
            ChecklistItem(
                id=str(entry["id"]),
                text=str(entry["text"]),
                section=str(entry["section"]),
                auto_source=entry.get("auto_source"),
                owning_skill=entry.get("owning_skill"),
            )
            for entry in data
        ]
        return cls(name=name, items=items)

    def evaluate(
        self,
        results_or_metrics: Any,
        *,
        available: set[str] | None = None,
    ) -> "ChecklistReport":
        """Score each item as satisfied / routed / gap against a run.

        ``results_or_metrics`` may be a Results-like object (read for
        ``.metrics`` and ``.cost``) or a plain list of metrics. Present
        auto-source kinds are: ``metrics`` whenever any metric exists;
        ``cost`` when a positive cost is recorded; and any kind the caller
        explicitly passes via ``available`` (a bare run has neither
        ``calibration`` nor ``subgroup``, so those items route by default).
        """
        metrics_present, cost = _extract(results_or_metrics)

        present: set[str] = set(available) if available else set()
        if metrics_present:
            present.add("metrics")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost > 0:
            present.add("cost")

        statuses: list[ChecklistItemStatus] = []
        for item in self.items:
            if item.auto_source is not None and item.auto_source in present:
                status = "satisfied"
                detail = f"Auto-satisfied from the run (source: {item.auto_source})."
            elif item.owning_skill is not None:
                status = "routed"
                detail = f"Routes to skill: {item.owning_skill}."
            else:
                status = "gap"
                detail = "No run-derived source and no owning skill; manual gap."
            statuses.append(ChecklistItemStatus(item=item, status=status, detail=detail))

        return ChecklistReport(name=self.name, statuses=statuses)


@dataclass
class ChecklistItemStatus:
    """The verdict for one item against one run."""

    item: ChecklistItem
    status: str  # "satisfied" | "routed" | "gap"
    detail: str


@dataclass
class ChecklistReport:
    """Coverage of a checklist by a single run.

    Framed as evidence coverage, not clearance: it states plainly how few
    items a run auto-satisfies and where the rest route.
    """

    name: str
    statuses: list[ChecklistItemStatus] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        """Tally of satisfied / routed / gap, plus the total item count."""
        tally = {"satisfied": 0, "routed": 0, "gap": 0}
        for status in self.statuses:
            tally[status.status] = tally.get(status.status, 0) + 1
        tally["total"] = len(self.statuses)
        return tally

    def to_markdown(self) -> str:
        """Render a coverage report grouped by status."""
        counts = self.counts
        satisfied = counts["satisfied"]
        total = counts["total"]
        routed = counts["routed"]
        gap = counts["gap"]

        lines: list[str] = []
        lines.append(f"# {self.name} coverage report")
        lines.append("")
        lines.append(
            f"**{satisfied} of {total} items auto-satisfied from the run; "
            f"the remaining {routed + gap} route to their owning skill.**"
        )
        lines.append("")
        lines.append(
            "This is an evidence-coverage report, not a certification. Auto-satisfied "
            "items reflect only what the run measured; a qualified human owner must "
            "complete and interpret the routed items before any decision."
        )
        lines.append("")

        lines.append(f"## Auto-satisfied ({satisfied})")
        lines.extend(_status_bullets(self.statuses, "satisfied"))
        lines.append("")

        lines.append(f"## Routed to skills ({routed})")
        lines.extend(_status_bullets(self.statuses, "routed"))
        lines.append("")

        lines.append(f"## Gaps ({gap})")
        lines.extend(_status_bullets(self.statuses, "gap"))
        lines.append("")

        return "\n".join(lines)


# --- helpers ---------------------------------------------------------


def _extract(results_or_metrics: Any) -> tuple[bool, Any]:
    """Return (metrics_present, cost) from a Results-like object or list."""
    if results_or_metrics is None:
        return False, None
    if isinstance(results_or_metrics, (list, tuple)):
        return len(results_or_metrics) > 0, None
    metrics = getattr(results_or_metrics, "metrics", None)
    cost = getattr(results_or_metrics, "cost", None)
    return bool(metrics), cost


def _status_bullets(statuses: list[ChecklistItemStatus], want: str) -> list[str]:
    rows = [s for s in statuses if s.status == want]
    if not rows:
        return ["- (none)"]
    return [f"- [{s.item.section}] {s.item.id}: {s.detail}" for s in rows]
