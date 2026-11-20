"""Descriptive method comparisons for paired model accuracy scores.

No statistic in this module is a generator acceptance threshold.
"""

from __future__ import annotations

import math
from fractions import Fraction
from statistics import fmean


def kendall_tau_b(original, generated):
    if len(original) != len(generated) or len(original) < 2:
        raise ValueError("Rank comparison needs at least two paired model scores")
    if any(not math.isfinite(value) for value in [*original, *generated]):
        raise ValueError("Rank comparison needs finite scores")
    counts = dict(concordant=0, discordant=0, tied_original_only=0, tied_generated_only=0, tied_both=0)
    for left in range(len(original)):
        for right in range(left):
            a, b = original[left] - original[right], generated[left] - generated[right]
            key = ("tied_both" if a == b == 0 else "tied_original_only" if a == 0 else
                   "tied_generated_only" if b == 0 else "concordant" if a * b > 0 else "discordant")
            counts[key] += 1
    untied = counts["concordant"] + counts["discordant"]
    denominator = math.sqrt((untied + counts["tied_original_only"]) * (untied + counts["tied_generated_only"]))
    return {"tau_b": (counts["concordant"] - counts["discordant"]) / denominator if denominator else None,
            **counts, "model_pairs": len(original) * (len(original) - 1) // 2}


DEFAULT_ANALYSIS = {
    "rbo_p": 0.9,
    "tdi_probability": 0.9,
    "coverage_tolerance_pp": None,
    "deming_error_ratio": None,
}


def analysis_options(settings=None):
    if settings is not None and not isinstance(settings, dict):
        raise ValueError("Analysis settings must be an object")
    settings = {} if settings is None else settings
    if set(settings) - set(DEFAULT_ANALYSIS):
        raise ValueError("Unknown analysis settings")
    result = {**DEFAULT_ANALYSIS, **settings}
    for name, value in result.items():
        if value is None and name in ("coverage_tolerance_pp", "deming_error_ratio"):
            continue
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"{name} must be finite and numeric")
        valid = (0 < value < 1 if name == "rbo_p" else
                 0 < value <= 1 if name == "tdi_probability" else
                 0 <= value <= 100 if name == "coverage_tolerance_pp" else value > 0)
        if not valid:
            raise ValueError(f"Invalid {name}")
    return result


def _rank_bounds(values):
    return [(1 + sum(other > value for other in values), sum(other >= value for other in values))
            for value in values]


def _pearson(x, y):
    a, b = fmean(x), fmean(y)
    xx, yy = math.fsum((v - a) ** 2 for v in x), math.fsum((v - b) ** 2 for v in y)
    return math.fsum((u - a) * (v - b) for u, v in zip(x, y)) / math.sqrt(xx * yy) if xx and yy else None


def _rbo(bounds_x, bounds_y, p):
    n = len(bounds_x)
    agreement = []
    for depth in range(1, n + 1):
        contributions = [[min(1, max(0, (depth - top + 1) / (bottom - top + 1)))
                          for top, bottom in bounds] for bounds in (bounds_x, bounds_y)]
        agreement.append(math.fsum(a * b for a, b in zip(*contributions)) / depth)
    base = (1 - p) * sum(p ** i * value for i, value in enumerate(agreement))
    tail = p ** n
    return {"p": p, "rbo_a_ext": base + tail, "prefix_weighted_sum": base,
            "prefix_normalized_overlap": base / (1 - tail), "tail_mass": tail,
            "agreement_by_depth": agreement,
            "tail_policy": "Complete identical model roster; agreement is 1 at and beyond its final depth."}


def _weighted_tau(x, y, bounds_x):
    weights = [1 / top for top, _ in bounds_x]
    concordance, x_weights, y_weights = [], [], []
    for i in range(len(x)):
        for j in range(i):
            a, b = x[i] - x[j], y[i] - y[j]
            weight = weights[i] + weights[j]
            x_weights.append(weight * (a != 0))
            y_weights.append(weight * (b != 0))
            concordance.append(weight * (1 if a * b > 0 else -1 if a * b < 0 else 0))
    numerator, untied_x, untied_y = map(math.fsum, (concordance, x_weights, y_weights))
    return numerator / math.sqrt(untied_x * untied_y) if untied_x and untied_y else None


def _icc(x, y):
    n, k = len(x), 2
    row_means = [(a + b) / k for a, b in zip(x, y)]
    means, grand = [fmean(x), fmean(y)], fmean(row_means)
    rows = k * sum((v - grand) ** 2 for v in row_means) / (n - 1)
    columns = n * sum((v - grand) ** 2 for v in means) / (k - 1)
    error = sum((v - row - col + grand) ** 2
                for pair, row in zip(zip(x, y), row_means) for v, col in zip(pair, means)) / ((n - 1) * (k - 1))
    denominator = rows + (k - 1) * error + k * (columns - error) / n
    return {"value": (rows - error) / denominator if denominator else None,
            "form": "ICC(A,1)", "model": "two-way mixed; OG and generated methods fixed",
            "definition": "absolute agreement", "type": "single measurement",
            "targets": "models", "mean_squares": {"targets": rows, "methods": columns, "error": error}}


def _deming(x, y, ratio):
    if ratio is None:
        return {"status": "not-estimated-error-ratio-unspecified", "slope": None, "intercept": None}
    a, b = fmean(x), fmean(y)
    xx, yy = fmean((v - a) ** 2 for v in x), fmean((v - b) ** 2 for v in y)
    xy = fmean((u - a) * (v - b) for u, v in zip(x, y))
    if not xy:
        return {"status": "undefined-zero-covariance", "slope": None, "intercept": None}
    delta = yy - ratio * xx
    root = math.hypot(delta, 2 * math.sqrt(ratio) * xy)
    # Rationalization prevents cancellation when the negative delta dominates.
    slope = (delta + root) / (2 * xy) if delta >= 0 else 2 * xy * ratio / (root - delta)
    return {"status": "descriptive-estimate", "slope": slope, "intercept": b - slope * a,
            "error_variance_ratio_generated_over_original": ratio, "intercept_unit": "accuracy fraction"}


def paired_score_diagnostics(original, generated, *, settings=None):
    """Compare complete paired model accuracies in [0, 1], with higher better."""
    options = analysis_options(settings)
    counts = kendall_tau_b(original, generated)
    if any(not 0 <= value <= 1 for value in [*original, *generated]):
        raise ValueError("Model accuracies must be fractions in [0, 1]")
    n = len(original)
    bounds_x, bounds_y = _rank_bounds(original), _rank_bounds(generated)
    rx, ry = [[(top + bottom) / 2 for top, bottom in bounds] for bounds in (bounds_x, bounds_y)]
    eligible = counts["concordant"] + counts["discordant"] + counts["tied_generated_only"]
    top_k = []
    for k in range(1, n + 1):
        x = {i for i, (top, _) in enumerate(bounds_x) if top <= k}
        y = {i for i, (top, _) in enumerate(bounds_y) if top <= k}
        top_k.append({"k": k, "original_set_size": len(x), "generated_set_size": len(y),
                      "intersection": len(x & y), "union": len(x | y), "jaccard": len(x & y) / len(x | y)})
    differences = [b - a for a, b in zip(original, generated)]
    absolute = sorted(abs(v) for v in differences)
    probability, tolerance = options["tdi_probability"], options["coverage_tolerance_pp"]
    # The empirical inverse CDF guarantees at least the requested observed coverage.
    tdi = absolute[math.ceil(Fraction(str(probability)) * n) - 1]
    roundoff = 1e-12 if tolerance else 0
    within = None if tolerance is None else sum(
        value <= tolerance / 100 or math.isclose(value, tolerance / 100, rel_tol=0, abs_tol=roundoff)
        for value in absolute)
    return {
        "unit": "paired per-model accuracy; one observation per solver model",
        "models": n,
        "rank": {"spearman_rho": _pearson(rx, ry),
            "spearman_ties": "midranks",
            "somers_d_generated_given_original": (counts["concordant"] - counts["discordant"]) / eligible if eligible else None,
            "somers_denominator_original_untied_pairs": eligible,
            "weighted_kendall_tau": _weighted_tau(original, generated, bounds_x),
            "weighted_kendall_policy": "Vigna additive hyperbolic; external zero-based OG competition ranks; tied OG models have equal weight",
            "spearman_footrule": sum(abs(a - b) for a, b in zip(rx, ry)),
            "reference_order_status": "all-original-scores-tied" if not eligible else "observed-ordering"},
        "leaderboard": {"rbo": _rbo(bounds_x, bounds_y, options["rbo_p"]),
            "rbo_sensitivity": [_rbo(bounds_x, bounds_y, p) for p in (.8, .9, .95)],
            "rbo_ties": "RBO-a: expected overlap over independent uniform permutations within each tie group",
            "top_k": top_k, "top_k_ties": "include the complete boundary tie group; actual set sizes reported"},
        "values": {"icc_absolute_single": _icc(original, generated),
            "deming": _deming(original, generated, options["deming_error_ratio"]),
            "empirical_tdi": {"probability": probability, "value_pp": 100 * tdi,
                "observed_coverage": sum(v <= tdi for v in absolute) / n,
                "method": "empirical inverse CDF: absolute discrepancy at ceil(probability * models); no population tolerance bound"},
            "coverage_probability": {"status": "descriptive-estimate" if tolerance is not None else "not-estimated-margin-unspecified",
                "tolerance_pp": tolerance, "boundary_roundoff_tolerance_pp": 100 * roundoff, "within": within, "models": n,
                "value": within / n if within is not None else None}},
        "inference": "Descriptive fixed-roster diagnostics; no equivalence test or acceptance threshold. Existing tau-b intervals are separate.",
    }
