"""Aggregation across items, with confidence intervals.

For v0.1 we use mean ± normal-approximation 95% CI half-width when n
is large enough to be meaningful, and percentile-bootstrap CI when
explicitly requested. That keeps the dependency surface to the stdlib.

Scorers produce per-item Metric values; this module reduces those into
per-benchmark, per-category aggregates.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from arisekit.common.stats import Z_95, bootstrap_ci as _bootstrap_ci, normal_ci as _normal_ci  # Z_95 is re-exported
from arisekit.types import Metric


@dataclass(frozen=True)
class ScoreChange:
    """One item-level metric change between two scoring revisions."""

    item_id: str
    category: str
    metric: str
    before: float | None
    after: float | None
    delta: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "category": self.category,
            "metric": self.metric,
            "before": self.before,
            "after": self.after,
            "delta": self.delta,
        }


@dataclass(frozen=True)
class AggregateChange:
    """One aggregate metric change between two scoring revisions."""

    category: str
    metric: str
    before: float | None
    after: float | None
    delta: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "metric": self.metric,
            "before": self.before,
            "after": self.after,
            "delta": self.delta,
        }


@dataclass(frozen=True)
class ScoreDiff:
    """Actionable delta between two item-level score collections."""

    primary_category: str
    primary_metric: str
    improved: int
    regressed: int
    unchanged: int
    added: int
    removed: int
    item_changes: tuple[ScoreChange, ...]
    aggregate_changes: tuple[AggregateChange, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_metric": {
                "category": self.primary_category,
                "metric": self.primary_metric,
            },
            "summary": {
                "improved": self.improved,
                "regressed": self.regressed,
                "unchanged": self.unchanged,
                "added": self.added,
                "removed": self.removed,
            },
            "item_changes": [value.to_dict() for value in self.item_changes],
            "aggregate_changes": [
                value.to_dict() for value in self.aggregate_changes
            ],
        }


def aggregate(
    per_item_metrics: Iterable[list[Metric]],
    *,
    bootstrap: int = 0,
    seed: int | None = None,
) -> list[Metric]:
    """Combine per-item metric lists into one aggregated list.

    Items are grouped by (name, category). For each group:
    - value = mean over items
    - n = number of items contributing
    - ci = 95% half-width via normal-approx (default) or percentile
      bootstrap if bootstrap > 0.
    """
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for metrics in per_item_metrics:
        for m in metrics:
            buckets[(m.name, m.category)].append(float(m.value))

    out: list[Metric] = []
    rng = random.Random(seed) if seed is not None else random.Random()
    for (name, category), values in buckets.items():
        n = len(values)
        if n == 0:
            out.append(Metric(name=name, value=0.0, category=category, n=0, ci=None))
            continue
        mean = sum(values) / n
        if n <= 1:
            ci: float | None = None
        elif bootstrap > 0:
            ci = _bootstrap_ci(values, iters=bootstrap, rng=rng)
        else:
            ci = _normal_ci(values, mean)
        out.append(Metric(name=name, value=mean, category=category, n=n, ci=ci))
    return out


def diff(
    old_scores: Any,
    new_scores: Any,
    *,
    primary_metric: str | tuple[str, str] | None = None,
) -> ScoreDiff:
    """Compare two per-item score collections without re-running inference.

    Inputs may be ``[(item_id, [Metric, ...]), ...]`` or objects exposing a
    ``per_item`` attribute. ``primary_metric`` can be ``"category/name"`` or
    a ``(category, name)`` tuple. It is required when more than one metric is
    present because an item can improve on one dimension and regress on
    another.
    """

    old_per_item = _per_item(old_scores, "old_scores")
    new_per_item = _per_item(new_scores, "new_scores")
    old = _score_index(old_per_item, "old_scores")
    new = _score_index(new_per_item, "new_scores")
    identities = sorted({key[1:] for key in old} | {key[1:] for key in new})
    if not identities:
        raise ValueError("cannot diff score collections with no metrics")
    primary = _primary_metric(primary_metric, identities)

    changes: list[ScoreChange] = []
    for item_id, category, metric in sorted(set(old) | set(new)):
        before = old.get((item_id, category, metric))
        after = new.get((item_id, category, metric))
        changes.append(
            ScoreChange(
                item_id=item_id,
                category=category,
                metric=metric,
                before=before,
                after=after,
                delta=(after - before if before is not None and after is not None else None),
            )
        )

    primary_changes = [
        value
        for value in changes
        if (value.category, value.metric) == primary
    ]
    improved = sum(
        value.delta is not None and value.delta > 0 for value in primary_changes
    )
    regressed = sum(
        value.delta is not None and value.delta < 0 for value in primary_changes
    )
    unchanged = sum(value.delta == 0 for value in primary_changes)
    added = sum(value.before is None for value in primary_changes)
    removed = sum(value.after is None for value in primary_changes)

    old_aggregates = {
        (metric.category, metric.name): metric.value
        for metric in aggregate(_metric_groups(old_per_item))
    }
    new_aggregates = {
        (metric.category, metric.name): metric.value
        for metric in aggregate(_metric_groups(new_per_item))
    }
    aggregate_changes: list[AggregateChange] = []
    for category, metric in sorted(set(old_aggregates) | set(new_aggregates)):
        before = old_aggregates.get((category, metric))
        after = new_aggregates.get((category, metric))
        aggregate_changes.append(
            AggregateChange(
                category=category,
                metric=metric,
                before=before,
                after=after,
                delta=(after - before if before is not None and after is not None else None),
            )
        )

    return ScoreDiff(
        primary_category=primary[0],
        primary_metric=primary[1],
        improved=improved,
        regressed=regressed,
        unchanged=unchanged,
        added=added,
        removed=removed,
        item_changes=tuple(changes),
        aggregate_changes=tuple(aggregate_changes),
    )


def top_changes(score_diff: ScoreDiff, *, limit: int = 10) -> list[ScoreChange]:
    """Return the largest comparable item changes in deterministic order."""

    if not isinstance(score_diff, ScoreDiff):
        raise TypeError("score_diff must be a ScoreDiff")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    comparable = [value for value in score_diff.item_changes if value.delta is not None]
    return sorted(
        comparable,
        key=lambda value: (
            -abs(value.delta or 0.0),
            value.item_id,
            value.category,
            value.metric,
        ),
    )[:limit]


def _score_index(values: Any, label: str) -> dict[tuple[str, str, str], float]:
    out: dict[tuple[str, str, str], float] = {}
    for item_id, metrics in _per_item(values, label):
        if not isinstance(item_id, str) or not item_id:
            raise ValueError(f"{label} contains an invalid item id")
        if not isinstance(metrics, Sequence) or isinstance(metrics, (str, bytes)):
            raise ValueError(f"{label} metrics for {item_id!r} must be a sequence")
        for metric in metrics:
            if not isinstance(metric, Metric):
                raise TypeError(f"{label} metrics must contain Metric objects")
            if isinstance(metric.value, bool):
                raise ValueError(f"{label} contains a boolean metric value")
            value = float(metric.value)
            if not math.isfinite(value):
                raise ValueError(f"{label} contains a non-finite metric")
            key = (item_id, metric.category, metric.name)
            if key in out:
                raise ValueError(f"{label} contains duplicate metric {key!r}")
            out[key] = value
    return out


def _metric_groups(values: Any) -> list[list[Metric]]:
    return [list(metrics) for _, metrics in _per_item(values, "scores")]


def _per_item(values: Any, label: str) -> list[tuple[str, Sequence[Metric]]]:
    candidate = getattr(values, "per_item", values)
    if isinstance(candidate, (str, bytes)) or not isinstance(candidate, Iterable):
        raise TypeError(f"{label} must be per-item scores or expose per_item")
    normalized: list[tuple[str, Sequence[Metric]]] = []
    seen: set[str] = set()
    for entry in candidate:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError(f"{label} entries must be (item_id, metrics) pairs")
        if not isinstance(entry[0], str) or not entry[0]:
            raise ValueError(f"{label} contains an invalid item id")
        if entry[0] in seen:
            raise ValueError(f"{label} contains duplicate item id {entry[0]!r}")
        seen.add(entry[0])
        normalized.append((entry[0], entry[1]))
    return normalized


def _primary_metric(
    value: str | tuple[str, str] | None,
    identities: list[tuple[str, str]],
) -> tuple[str, str]:
    if value is None:
        if len(identities) != 1:
            rendered = ", ".join(f"{category}/{name}" for category, name in identities)
            raise ValueError(
                "primary_metric is required when multiple metrics are present: "
                + rendered
            )
        return identities[0]
    if isinstance(value, str):
        if "/" not in value:
            raise ValueError("primary_metric text must use 'category/name'")
        category, name = value.split("/", 1)
        selected = (category, name)
    elif isinstance(value, tuple) and len(value) == 2:
        selected = value
    else:
        raise TypeError("primary_metric must be 'category/name' or a pair")
    if selected not in identities:
        raise ValueError(
            f"primary metric {selected[0]}/{selected[1]} is not present"
        )
    return selected
