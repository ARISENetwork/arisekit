"""Statistical primitives shared across ARISEKit: means, quantiles, intervals, and rank agreement."""
from __future__ import annotations

import math
import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from statistics import fmean

from arisekit.common.validate import number

# Two-sided 95% normal critical value (the 97.5th percentile, about 1.96); stored CIs depend on this exact value.
Z_95 = 1.959964


def mean(values: Iterable[float], *, empty: float | None = None) -> float:
    """The arithmetic mean. An empty input returns `empty` when given, and otherwise raises ValueError."""
    materialized = tuple(values)
    if not materialized:
        if empty is not None:
            return empty
        raise ValueError("cannot average an empty sequence")
    return sum(materialized) / len(materialized)


def quantile(ordered: Sequence[float], probability: float, *, weighted: bool = False) -> float:
    """Linear-interpolation quantile of already sorted values. The interpolation is ordered[lower] + f *
    (ordered[upper] - ordered[lower]), or with weighted ordered[lower] * (1 - f) + ordered[upper] * f; the two
    can differ in the last floating-point bit, so each caller keeps the form its stored results used."""
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    if weighted:
        return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def percentile_interval(draws: Sequence[float], confidence: float, point_estimate: float, *,
                        quantile_fn: Callable[[Sequence[float], float], float] = quantile) -> tuple[float, float]:
    """Percentile bootstrap interval at `confidence`, widened to contain the point estimate."""
    ordered = sorted(draws)
    alpha = (1.0 - confidence) / 2.0
    lower = quantile_fn(ordered, alpha)
    upper = quantile_fn(ordered, 1.0 - alpha)
    return min(lower, point_estimate), max(upper, point_estimate)


def normal_ci(values: list[float], center: float) -> float:
    """Normal-approximation 95% CI half-width on the mean."""
    n = len(values)
    if n <= 1:
        return 0.0
    var = sum((v - center) ** 2 for v in values) / (n - 1)
    se = math.sqrt(var / n)
    return Z_95 * se


def bootstrap_ci(values: list[float], *, iters: int, rng: random.Random) -> float:
    """Percentile-bootstrap 95% CI half-width on the mean."""
    n = len(values)
    if n <= 1 or iters <= 0:
        return 0.0
    samples: list[float] = []
    for _ in range(iters):
        draw = [values[rng.randrange(n)] for _ in range(n)]
        samples.append(sum(draw) / n)
    samples.sort()
    lo = samples[int(0.025 * iters)]
    hi = samples[int(0.975 * iters) - 1]
    # Half-width of the symmetric CI around the point estimate.
    return (hi - lo) / 2.0


def average_ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks, with tied values sharing the average of their positions."""
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        average_rank = ((start + 1) + end) / 2.0
        for position in range(start, end):
            ranks[order[position]] = average_rank
        start = end
    return ranks


def spearman_rank_agreement(
    first: Mapping[str, float], second: Mapping[str, float]
) -> float:
    """Return Spearman correlation using average ranks for exact ties."""

    if not isinstance(first, Mapping) or not isinstance(second, Mapping):
        raise ValueError("Spearman inputs must be mappings")
    if set(first) != set(second) or len(first) < 2:
        raise ValueError("Spearman inputs must contain the same model panel")
    names = sorted(first)
    first_values = [number(first[name], f"first score {name}") for name in names]
    second_values = [number(second[name], f"second score {name}") for name in names]
    first_ranks = average_ranks(first_values)
    second_ranks = average_ranks(second_values)
    first_mean = fmean(first_ranks)
    second_mean = fmean(second_ranks)
    numerator = sum(
        (left - first_mean) * (right - second_mean)
        for left, right in zip(first_ranks, second_ranks)
    )
    first_ss = sum((rank - first_mean) ** 2 for rank in first_ranks)
    second_ss = sum((rank - second_mean) ** 2 for rank in second_ranks)
    denominator = math.sqrt(first_ss * second_ss)
    if denominator == 0.0:
        raise ValueError("Spearman rank agreement is undefined for an all-tied arm")
    return max(-1.0, min(1.0, numerator / denominator))
