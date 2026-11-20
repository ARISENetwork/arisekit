"""Pure regression-detection logic for canary monitoring.

This module has no I/O and no model calls: it takes a current reading and
a locked baseline (each a dict or any object exposing `.value` and `.ci`)
and returns an advisory verdict. The verdicts are evidence a human owner
interprets, never a pass/fail gate, so messages read as recommendations
("candidate regression ... human review recommended") and confidence
intervals are honored so a tiny, noisy sample cannot masquerade as a
clean signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RegressionVerdict:
    """Advisory outcome of comparing a current reading to a baseline.

    `is_regression` is a candidate-regression flag for human review, not a
    gate. `delta` is the signed change (current - baseline). `message` is a
    human-readable summary; `recommend_rollback` mirrors `is_regression`
    and is likewise advisory.
    """

    is_regression: bool
    rule: str
    delta: float
    baseline_value: float
    current_value: float
    message: str
    recommend_rollback: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_regression": self.is_regression,
            "rule": self.rule,
            "delta": self.delta,
            "baseline_value": self.baseline_value,
            "current_value": self.current_value,
            "message": self.message,
            "recommend_rollback": self.recommend_rollback,
        }


def _value_ci(obj: Any) -> tuple[float, float]:
    """Extract (value, ci) from a dict or a `.value`/`.ci` object.

    A missing or None `ci` is treated as 0.0 (no interval). A missing
    value is an error: there is nothing to compare.
    """
    if isinstance(obj, dict):
        value = obj.get("value")
        ci = obj.get("ci")
    else:
        value = getattr(obj, "value", None)
        ci = getattr(obj, "ci", None)
    if value is None:
        raise ValueError("reading is missing a 'value'")
    return float(value), (float(ci) if ci is not None else 0.0)


def _worsening(baseline_value: float, current_value: float, higher_is_better: bool) -> float:
    """Signed magnitude of degradation (positive means the metric got worse)."""
    if higher_is_better:
        return baseline_value - current_value
    return current_value - baseline_value


def detect_regression(
    current: Any,
    baseline: Any,
    *,
    rule: str = "ci_nonoverlap",
    threshold: float | None = None,
    higher_is_better: bool = True,
    metric: str | None = None,
) -> RegressionVerdict:
    """Compare a current reading to a baseline and return an advisory verdict.

    `current` and `baseline` are dicts or objects with `.value` and `.ci`
    (a None `ci` counts as 0.0). Rules:

    - "ci_nonoverlap": a candidate regression when the confidence intervals
      do not overlap AND the current side is the worse one.
    - "abs_delta": a candidate regression when the worsening magnitude
      exceeds `threshold` (required).
    - "rel_delta": the same, but relative to abs(baseline value), guarding
      a zero baseline by falling back to the absolute magnitude.

    `metric` is optional and only used to make the message more specific.
    """
    cur_value, cur_ci = _value_ci(current)
    base_value, base_ci = _value_ci(baseline)
    delta = cur_value - base_value

    if rule == "ci_nonoverlap":
        if higher_is_better:
            is_regression = (cur_value + cur_ci) < (base_value - base_ci)
        else:
            is_regression = (cur_value - cur_ci) > (base_value + base_ci)
    elif rule == "abs_delta":
        if threshold is None:
            raise ValueError("the 'abs_delta' rule requires a threshold")
        is_regression = _worsening(base_value, cur_value, higher_is_better) > threshold
    elif rule == "rel_delta":
        if threshold is None:
            raise ValueError("the 'rel_delta' rule requires a threshold")
        worsening = _worsening(base_value, cur_value, higher_is_better)
        denom = abs(base_value)
        if denom == 0.0:
            # Guard divide-by-zero: fall back to the absolute worsening.
            is_regression = worsening > threshold
        else:
            is_regression = (worsening / denom) > threshold
    else:
        raise ValueError(f"unknown regression rule: {rule!r}")

    message = _verdict_message(
        is_regression=is_regression,
        rule=rule,
        base_value=base_value,
        cur_value=cur_value,
        delta=delta,
        metric=metric,
    )
    return RegressionVerdict(
        is_regression=is_regression,
        rule=rule,
        delta=delta,
        baseline_value=base_value,
        current_value=cur_value,
        message=message,
        recommend_rollback=is_regression,
    )


def detect_series_regression(
    series: list[dict[str, Any]],
    baseline: Any,
    *,
    consecutive: int = 3,
    **kw: Any,
) -> RegressionVerdict:
    """Flag a regression from either the baseline rule or a declining trend.

    Two independent signals are combined:

    1. the baseline rule applied to the latest point in `series` (skipped
       when `baseline` is None), via `detect_regression(**kw)`;
    2. a monotonic worsening trend across the last `consecutive` points,
       which needs no baseline at all.

    `series` is a list of dicts each carrying `value` (and optionally `ci`).
    The returned verdict is advisory: a declining trend is evidence for
    human review, not an automatic rollback.
    """
    higher_is_better = bool(kw.get("higher_is_better", True))
    rule = str(kw.get("rule", "ci_nonoverlap"))

    if not series:
        return RegressionVerdict(
            is_regression=False,
            rule=rule,
            delta=0.0,
            baseline_value=0.0,
            current_value=0.0,
            message="no readings in series; nothing to evaluate",
            recommend_rollback=False,
        )

    values = [_value_ci(point)[0] for point in series]
    current_value = values[-1]

    base_verdict: RegressionVerdict | None = None
    if baseline is not None:
        base_verdict = detect_regression(series[-1], baseline, **kw)

    window = values[-consecutive:]
    trend = (
        consecutive >= 2
        and len(window) >= consecutive
        and _monotonic_worsening(window, higher_is_better)
    )

    baseline_flag = base_verdict.is_regression if base_verdict is not None else False
    is_regression = baseline_flag or trend

    if base_verdict is not None:
        baseline_value = base_verdict.baseline_value
        delta = base_verdict.delta
    else:
        baseline_value = window[0]
        delta = current_value - baseline_value

    message = _series_message(
        baseline_flag=baseline_flag,
        base_verdict=base_verdict,
        trend=trend,
        consecutive=consecutive,
    )
    return RegressionVerdict(
        is_regression=is_regression,
        rule=rule,
        delta=delta,
        baseline_value=baseline_value,
        current_value=current_value,
        message=message,
        recommend_rollback=is_regression,
    )


def _monotonic_worsening(values: list[float], higher_is_better: bool) -> bool:
    """True when every step in `values` moves strictly in the worse direction."""
    if len(values) < 2:
        return False
    for prev, nxt in zip(values, values[1:]):
        if higher_is_better:
            if not (nxt < prev):
                return False
        else:
            if not (nxt > prev):
                return False
    return True


def _verdict_message(
    *,
    is_regression: bool,
    rule: str,
    base_value: float,
    cur_value: float,
    delta: float,
    metric: str | None,
) -> str:
    """Compose an advisory, evidence-flavored message for a single comparison."""
    where = f" on {metric}" if metric else ""
    context = f"baseline {base_value:.4f} -> current {cur_value:.4f} (delta {delta:+.4f}, rule {rule})"
    if is_regression:
        return f"candidate regression vs baseline{where}; human review recommended [{context}]"
    return f"within tolerance vs baseline{where} [{context}]"


def _series_message(
    *,
    baseline_flag: bool,
    base_verdict: RegressionVerdict | None,
    trend: bool,
    consecutive: int,
) -> str:
    """Compose an advisory message that names whichever signal(s) fired."""
    if baseline_flag and trend:
        return (
            f"candidate regression vs baseline and a declining trend over the last "
            f"{consecutive} readings; human review recommended"
        )
    if baseline_flag and base_verdict is not None:
        return base_verdict.message
    if trend:
        return (
            f"candidate downward trend over the last {consecutive} readings; "
            f"human review recommended"
        )
    return "within tolerance; no baseline breach and no declining trend"
