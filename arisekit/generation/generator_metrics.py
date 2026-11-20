"""Descriptive model-profile diagnostics; no inferred agreement thresholds.

Scores are aligned by model, with larger values indicating better performance.
"""
from __future__ import annotations

import math
from typing import Sequence


def _paired(reference, candidate):
    if len(reference) != len(candidate):
        raise ValueError("Profiles must contain the same aligned models")
    try:
        valid = all(not isinstance(v, bool) and math.isfinite(v) for v in (*reference, *candidate))
    except TypeError:
        valid = False
    if not valid:
        raise ValueError("Profile scores must be finite numbers")


def _ranks(values):
    return [1 + sum(other > value for other in values)
            + (sum(other == value for other in values) - 1) / 2 for value in values]


def _pairs(reference, candidate):
    counts = dict(concordant=0, discordant=0, reference_only_ties=0,
                  candidate_only_ties=0, both_tied=0)
    for i in range(len(reference)):
        for j in range(i):
            a, b = reference[i] - reference[j], candidate[i] - candidate[j]
            key = ("both_tied" if a == b == 0 else "reference_only_ties" if a == 0
                   else "candidate_only_ties" if b == 0 else "concordant" if a * b > 0
                   else "discordant")
            counts[key] += 1
    return counts


def spearman_rho(reference: Sequence[float], candidate: Sequence[float]) -> float | None:
    """Pearson correlation of average ranks, retaining ties."""
    _paired(reference, candidate)
    n = len(reference)
    if n < 2:
        return None
    a, b = _ranks(reference), _ranks(candidate)
    center = (n + 1) / 2
    denominator = math.sqrt(sum((v - center) ** 2 for v in a) * sum((v - center) ** 2 for v in b))
    return sum((x - center) * (y - center) for x, y in zip(a, b)) / denominator if denominator else None


def somers_d(reference: Sequence[float], candidate: Sequence[float]) -> float | None:
    """D(candidate | reference): pairs untied in the reference form the denominator."""
    _paired(reference, candidate)
    counts = _pairs(reference, candidate)
    denominator = counts["concordant"] + counts["discordant"] + counts["candidate_only_ties"]
    return (counts["concordant"] - counts["discordant"]) / denominator if denominator else None


def rank_biased_overlap_a(reference: Sequence[float], candidate: Sequence[float], *, persistence: float) -> dict:
    """RBO-a for a complete common panel; average over independent tie permutations.

    Corsi and Urbano (2024), equations 3 and 9. The common finite universe gives
    agreement one beyond its length. This API does not evaluate truncated or
    non-conjoint lists. Identical tied profiles can consequently score below one.
    """
    _paired(reference, candidate)
    if isinstance(persistence, bool) or not math.isfinite(persistence) or not 0 < persistence < 1:
        raise ValueError("RBO persistence must lie strictly between zero and one")
    n = len(reference)
    if not n:
        return {"score": None, "persistence": persistence, "prefix_weight": None,
                "tail_weight": None, "agreement_by_depth": []}
    def contributions(values, depth):
        return [min(1, max(0, (depth - sum(other > v for other in values))
                    / sum(other == v for other in values))) for v in values]
    agreements = [sum(x * y for x, y in zip(contributions(reference, d), contributions(candidate, d))) / d
                  for d in range(1, n + 1)]
    tail = persistence ** n
    score = min(1, (1 - persistence) * sum(a * persistence ** d for d, a in enumerate(agreements)) + tail)
    return {"score": score, "persistence": persistence, "prefix_weight": 1 - tail,
            "tail_weight": tail, "agreement_by_depth": agreements}


def profile_diagnostics(
    reference: Sequence[float], candidate: Sequence[float], *,
    rbo_persistence: float | None = None, top_k: int | None = None,
    agreement_tolerance: float | None = None, tdi_probability: float | None = None,
) -> dict:
    """Report ranking and value agreement across model means, not individual items.

    Optional settings must be supplied by the analysis plan. Missing settings do
    not become implicit tolerances, top-k choices or pass/fail rules. Degenerate
    estimates remain None; ICC estimates are not clipped to nonnegative values.
    """
    _paired(reference, candidate)
    n = len(reference)
    if top_k is not None and (type(top_k) is not int or top_k < 1 or (n and top_k > n)):
        raise ValueError("top_k must be a positive integer no greater than panel size")
    if agreement_tolerance is not None and (isinstance(agreement_tolerance, bool)
            or not math.isfinite(agreement_tolerance) or agreement_tolerance < 0):
        raise ValueError("Agreement tolerance must be finite and nonnegative")
    if tdi_probability is not None and (isinstance(tdi_probability, bool)
            or not math.isfinite(tdi_probability) or not 0 < tdi_probability <= 1):
        raise ValueError("TDI probability must lie in (0, 1]")
    counts = _pairs(reference, candidate)
    total_pairs = sum(counts.values())
    rbo = None
    if rbo_persistence is not None:
        rbo = rank_biased_overlap_a(reference, candidate, persistence=rbo_persistence)
        rbo.update(variant="a", scope="complete common model panel",
                   reference_self=rank_biased_overlap_a(reference, reference, persistence=rbo_persistence)["score"],
                   candidate_self=rank_biased_overlap_a(candidate, candidate, persistence=rbo_persistence)["score"])
    top = None
    if top_k is not None:
        left = {i for i, v in enumerate(reference) if v >= sorted(reference, reverse=True)[top_k - 1]} if n else set()
        right = {i for i, v in enumerate(candidate) if v >= sorted(candidate, reverse=True)[top_k - 1]} if n else set()
        top = {"k": top_k, "boundary_ties": "include entire tie group", "reference_count": len(left),
               "candidate_count": len(right), "intersection_count": len(left & right),
               "union_count": len(left | right), "jaccard": len(left & right) / len(left | right) if left or right else None}
    deltas = [y - x for x, y in zip(reference, candidate)]
    absolute = sorted(abs(d) for d in deltas)
    ccc = icc = None
    both_constant = n and len(set(reference)) == len(set(candidate)) == 1
    if n >= 2 and both_constant:
        ccc = icc = 0.0 if reference[0] != candidate[0] else None
    elif n >= 2:
        mx, my = sum(reference) / n, sum(candidate) / n
        vx, vy = (sum((v - mean) ** 2 for v in values) / n
                  for values, mean in ((reference, mx), (candidate, my)))
        covariance = sum((x - mx) * (y - my) for x, y in zip(reference, candidate)) / n
        denominator = vx + vy + (mx - my) ** 2
        ccc = 2 * covariance / denominator if denominator else None
        grand = (mx + my) / 2
        row_means = [(x + y) / 2 for x, y in zip(reference, candidate)]
        msr = 2 * sum((r - grand) ** 2 for r in row_means) / (n - 1)
        msc = n * ((mx - grand) ** 2 + (my - grand) ** 2)
        mse = sum((x - r - mx + grand) ** 2 + (y - r - my + grand) ** 2
                  for x, y, r in zip(reference, candidate, row_means)) / (n - 1)
        denominator = msr + mse + 2 * (msc - mse) / n
        icc = (msr - mse) / denominator if denominator > 0 else None
    return {"schema_version": "arisekit.model-profile-diagnostics.v1", "n_models": n, "unit": "paired model mean scores",
            "rank": {"spearman_rho": spearman_rho(reference, candidate),
                     "somers_d_candidate_given_reference": somers_d(reference, candidate),
                     "pair_counts": counts,
                     "net_pair_probability": (counts["concordant"] - counts["discordant"]) / total_pairs if total_pairs else None},
            "top_weighted": {"rbo": rbo, "top_k": top},
            "values": {"lins_ccc": ccc, "ccc_moment_normalization": "1/n",
                       "icc_a1": icc, "icc_definition": "two-way mixed, absolute agreement, single measurement; two fixed benchmark methods",
                       "mean_bias": sum(deltas) / n if n else None,
                       "root_mean_squared_difference": math.sqrt(sum(d * d for d in deltas) / n) if n else None,
                       "coverage_probability": {"tolerance": agreement_tolerance, "inclusive_boundary": True,
                           "estimate": sum(d <= agreement_tolerance for d in absolute) / n if n and agreement_tolerance is not None else None},
                       "total_deviation_index": {"probability": tdi_probability, "estimator": "empirical inverse CDF, without interpolation",
                           "estimate": absolute[math.ceil(n * tdi_probability) - 1] if n and tdi_probability is not None else None}}}
