"""Buyer-side comparative scorecards (DECIDE).

Run one identical rubric/case suite across several vendors or models, then
reduce their per-criterion metrics into a ranked scorecard: per-criterion
means with confidence intervals, pairwise CI-overlap significance flags,
and a weighted composite in 0..1.

This module is pure: it consumes already-computed :class:`~arisekit.types.Metric`
lists (or ``Results``-like objects that expose ``.metrics``) and does no model
inference, so it is fully deterministic and offline-testable.

The output is decision-support evidence a human owner interprets, not a
certified recommendation or a pass/fail clearance. When a criterion rests on
few items the cell carries its ``n`` and ``ci`` so small-sample uncertainty
stays visible rather than being rounded away into false precision.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Cell:
    """One vendor's result on one criterion.

    ``value`` is the point estimate, ``ci`` the 95% half-width (``None`` when
    unknown), and ``n`` the number of items behind the estimate (``None`` when
    unknown). A missing (vendor, criterion) combination has no cell at all
    rather than a zero-valued one.
    """

    value: float
    ci: float | None = None
    n: int | None = None


@dataclass
class Scorecard:
    """A ranked comparison of vendors across shared criteria.

    ``cells`` is indexed ``cells[criterion][vendor]``; a vendor missing from a
    criterion's inner dict simply did not report that criterion. ``composite``
    and ``ranking`` are derived from cross-vendor min-max normalization under
    ``weights`` and ``directions`` (see :func:`comparative_scorecard`).
    """

    vendors: list[str]
    criteria: list[str]
    cells: dict[str, dict[str, Cell]]
    weights: dict[str, float]
    directions: dict[str, bool]
    composite: dict[str, float]
    ranking: list[str]

    def pairwise(self, criterion: str) -> dict[tuple[str, str], str]:
        """Flag every vendor pair on ``criterion`` by CI overlap.

        Returns a mapping ``(vendor_a, vendor_b) -> flag`` for each unordered
        pair of vendors that both reported ``criterion``, in vendor order.
        The flag is ``"distinguishable"`` when the two 95% intervals do not
        overlap and ``"overlapping"`` otherwise. A pair where either cell lacks
        a CI is reported as ``"overlapping"``: absent uncertainty is not
        evidence of a real difference.
        """
        column = self.cells.get(criterion, {})
        present = [v for v in self.vendors if v in column]
        out: dict[tuple[str, str], str] = {}
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                va, vb = present[i], present[j]
                overlap = _ci_overlap(column[va], column[vb])
                out[(va, vb)] = "overlapping" if overlap else "distinguishable"
        return out

    def to_csv(self, path: str | Path) -> Path:
        """Write a vendor-in-columns pivot of the scorecard.

        One row per criterion holds ``value(ci)`` per vendor (blank when the
        vendor did not report that criterion), followed by a ``composite`` row
        and a ``rank`` row (1 = best). The header is
        ``["criterion", *vendors]``.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rank_of = {vendor: idx + 1 for idx, vendor in enumerate(self.ranking)}
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["criterion", *self.vendors])
            for criterion in self.criteria:
                column = self.cells.get(criterion, {})
                row = [criterion]
                for vendor in self.vendors:
                    cell = column.get(vendor)
                    row.append(_fmt_cell_csv(cell) if cell is not None else "")
                writer.writerow(row)
            writer.writerow(
                ["composite", *(f"{self.composite.get(v, 0.0):.3f}" for v in self.vendors)]
            )
            writer.writerow(
                ["rank", *(str(rank_of.get(v, "")) for v in self.vendors)]
            )
            # Carry the framing that to_markdown shows, so a forwarded CSV is
            # not read as a certified ranking. A single trailing comment row
            # (no blank line) keeps every row's first cell populated for
            # header-based readers.
            writer.writerow(
                ["# decision-support evidence, not a certified recommendation or pass/fail clearance"]
            )
        return path

    def to_markdown(self) -> str:
        """Render a ranked table (best vendor first) as GitHub-flavored Markdown.

        Rows are vendors in ranking order; columns are rank, vendor, composite,
        and one column per criterion showing ``value (±ci)``.
        """
        header = ["Rank", "Vendor", "Composite", *self.criteria]
        lines = [
            "Comparative scorecard (decision-support evidence, not a certified recommendation).",
            "",
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        for rank, vendor in enumerate(self.ranking, start=1):
            cols = [
                str(rank),
                vendor,
                f"{self.composite.get(vendor, 0.0):.3f}",
            ]
            for criterion in self.criteria:
                cell = self.cells.get(criterion, {}).get(vendor)
                cols.append(_fmt_cell_md(cell))
            lines.append("| " + " | ".join(cols) + " |")
        return "\n".join(lines)


def comparative_scorecard(
    results_by_vendor: dict[str, Any],
    *,
    criteria: list[str] | None = None,
    weights: dict[str, float] | None = None,
    higher_is_better: dict[str, bool] | bool = True,
) -> Scorecard:
    """Build a ranked :class:`Scorecard` from per-vendor metrics.

    ``results_by_vendor`` maps a vendor label to either a ``Results``-like
    object exposing ``.metrics`` (a list of :class:`~arisekit.types.Metric`)
    or directly to such a list. The mapping is duck-typed: if the value has a
    ``.metrics`` attribute it is used, otherwise the value is treated as the
    metrics list itself.

    Each metric contributes one criterion keyed by its ``name``. When the same
    name appears under multiple categories, the ``"overall"`` category wins.
    If ``criteria`` is given the scorecard is restricted to and ordered by it;
    otherwise criteria are the sorted union of names across all vendors.

    ``higher_is_better`` sets criterion direction: a bool applies to every
    criterion, a dict applies per criterion (unlisted criteria default to
    higher-is-better). The composite min-max normalizes each criterion's
    values across vendors to 0..1 (all-equal -> everyone gets 1.0), flips the
    normalized value for lower-is-better criteria, and takes a weighted mean
    across the criteria a vendor actually reported. Missing criteria are
    excluded from that vendor's normalization and from its own composite
    denominator; they are never imputed as 0. ``weights`` default to equal and
    are normalized to sum to 1. Ranking is by composite descending (stable, so
    ties keep input order).
    """
    vendors = list(results_by_vendor.keys())

    # Duck-type each vendor's metrics, keyed by name with overall preferred.
    per_vendor: dict[str, dict[str, Any]] = {}
    for vendor in vendors:
        metrics = _extract_metrics(results_by_vendor[vendor])
        chosen: dict[str, Any] = {}
        for metric in metrics:
            name = metric.name
            existing = chosen.get(name)
            if existing is None or (
                metric.category == "overall" and existing.category != "overall"
            ):
                chosen[name] = metric
        per_vendor[vendor] = chosen

    # Criteria universe.
    if criteria is not None:
        criteria_list = list(criteria)
    else:
        names: set[str] = set()
        for chosen in per_vendor.values():
            names.update(chosen.keys())
        criteria_list = sorted(names)

    # Cells indexed [criterion][vendor].
    cells: dict[str, dict[str, Cell]] = {c: {} for c in criteria_list}
    for vendor in vendors:
        chosen = per_vendor[vendor]
        for criterion in criteria_list:
            metric = chosen.get(criterion)
            if metric is None:
                continue
            cells[criterion][vendor] = Cell(
                value=float(metric.value), ci=metric.ci, n=metric.n
            )

    directions = _resolve_directions(criteria_list, higher_is_better)
    weight_map = _resolve_weights(criteria_list, weights)

    composite = _composite_scores(vendors, criteria_list, cells, directions, weight_map)
    ranking = sorted(vendors, key=lambda v: composite.get(v, 0.0), reverse=True)

    return Scorecard(
        vendors=vendors,
        criteria=criteria_list,
        cells=cells,
        weights=weight_map,
        directions=directions,
        composite=composite,
        ranking=ranking,
    )


# --- internal helpers ------------------------------------------------


def _extract_metrics(value: Any) -> list[Any]:
    """Return the metrics list for a vendor, duck-typing ``.metrics``."""
    metrics = getattr(value, "metrics", value)
    return list(metrics)


def _resolve_directions(
    criteria: list[str],
    higher_is_better: dict[str, bool] | bool,
) -> dict[str, bool]:
    """Map each criterion to a higher-is-better flag."""
    if isinstance(higher_is_better, bool):
        return {c: higher_is_better for c in criteria}
    return {c: bool(higher_is_better.get(c, True)) for c in criteria}


def _resolve_weights(
    criteria: list[str],
    weights: dict[str, float] | None,
) -> dict[str, float]:
    """Normalize weights to sum to 1 across the criteria, defaulting to equal.

    When ``weights`` is provided, criteria absent from it get 0. If the total
    is non-positive (empty criteria, or all-zero weights) the weighting falls
    back to equal so the composite stays defined.
    """
    if not criteria:
        return {}
    if weights is None:
        base = {c: 1.0 for c in criteria}
    else:
        base = {c: float(weights.get(c, 0.0)) for c in criteria}
    total = sum(base.values())
    if total <= 0.0:
        base = {c: 1.0 for c in criteria}
        total = float(len(criteria))
    return {c: base[c] / total for c in criteria}


def _composite_scores(
    vendors: list[str],
    criteria: list[str],
    cells: dict[str, dict[str, Cell]],
    directions: dict[str, bool],
    weights: dict[str, float],
) -> dict[str, float]:
    """Weighted mean of cross-vendor min-max-normalized cell values, per vendor."""
    # Per-criterion normalized value keyed by vendor.
    normalized: dict[str, dict[str, float]] = {}
    for criterion in criteria:
        column = cells.get(criterion, {})
        values = [cell.value for cell in column.values()]
        if not values:
            normalized[criterion] = {}
            continue
        vmin, vmax = min(values), max(values)
        span = vmax - vmin
        higher = directions.get(criterion, True)
        norm_column: dict[str, float] = {}
        for vendor, cell in column.items():
            norm = 1.0 if span == 0.0 else (cell.value - vmin) / span
            # Guard the flip: an all-equal or sole-reporter criterion (span==0)
            # stays neutral (1.0) in BOTH directions, per the documented
            # "all-equal -> everyone gets 1.0" contract. Without the guard a
            # tied lower-is-better criterion would flip to 0.0 (worst).
            if not higher and span != 0.0:
                norm = 1.0 - norm
            norm_column[vendor] = norm
        normalized[criterion] = norm_column

    composite: dict[str, float] = {}
    for vendor in vendors:
        numerator = 0.0
        denominator = 0.0
        for criterion in criteria:
            norm_column = normalized.get(criterion, {})
            if vendor not in norm_column:
                continue
            weight = weights.get(criterion, 0.0)
            numerator += weight * norm_column[vendor]
            denominator += weight
        composite[vendor] = numerator / denominator if denominator > 0.0 else 0.0
    return composite


def _ci_overlap(a: Cell, b: Cell) -> bool:
    """Whether two cells' 95% intervals overlap (True when either CI is None)."""
    if a.ci is None or b.ci is None:
        return True
    a_lo, a_hi = a.value - a.ci, a.value + a.ci
    b_lo, b_hi = b.value - b.ci, b.value + b.ci
    return a_lo <= b_hi and b_lo <= a_hi


def _fmt_cell_csv(cell: Cell) -> str:
    """Format a cell as ``value(ci)`` (or bare ``value`` when CI is unknown)."""
    if cell.ci is None:
        return f"{cell.value:.3f}"
    return f"{cell.value:.3f}({cell.ci:.3f})"


def _fmt_cell_md(cell: Cell | None) -> str:
    """Format a cell for Markdown as ``value (±ci)``, or ``n/a`` when absent."""
    if cell is None:
        return "n/a"
    if cell.ci is None:
        return f"{cell.value:.3f}"
    return f"{cell.value:.3f} (±{cell.ci:.3f})"
