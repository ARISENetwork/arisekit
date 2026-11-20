"""Run a benchmark as a scheduled canary and append a dated time series.

`run_canary` re-runs any benchmark (duck-typed: it just needs `.name` and a
`.run(...)` that returns an object with `.metrics`) against a deployed model,
extracts the single watched metric, and appends one dated row to a CSV time
series. `latest_vs_baseline` layers the advisory regression check from
`drift` on top. Nothing here depends on an interactive harness: a cron job,
Airflow task, or GitHub Actions step can import and call these directly.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arisekit.monitor.config import MonitorConfig
from arisekit.monitor.drift import RegressionVerdict, detect_regression


SERIES_HEADER = ["timestamp", "benchmark", "model", "category", "metric", "n", "value", "ci"]


@dataclass
class CanaryRun:
    """One dated reading of the watched metric from a canary re-run."""

    timestamp: str
    benchmark: str
    model: str
    category: str
    metric: str
    value: float
    ci: float | None
    n: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "benchmark": self.benchmark,
            "model": self.model,
            "category": self.category,
            "metric": self.metric,
            "value": self.value,
            "ci": self.ci,
            "n": self.n,
        }


def run_canary(
    benchmark: Any,
    config: MonitorConfig,
    *,
    model: str | None = None,
    timestamp: str | None = None,
    results_dir: str | Path | None = None,
) -> CanaryRun:
    """Re-run `benchmark`, select the watched metric, and append a series row.

    `benchmark` is duck-typed: it must expose `.name` and a
    `.run(model, *, trials, limit, bootstrap, results_dir)` returning an
    object whose `.metrics` is a list of metric-likes (each with `.name`,
    `.value`, `.category`, `.ci`, `.n`). `timestamp` is injectable for
    deterministic tests; it defaults to the current UTC time in ISO format.
    """
    model_id = model if model is not None else config.model
    when = timestamp if timestamp is not None else datetime.now(timezone.utc).isoformat()

    results = benchmark.run(
        model_id,
        trials=config.trials,
        limit=config.limit,
        bootstrap=config.bootstrap,
        results_dir=results_dir,
    )
    metrics = list(getattr(results, "metrics", []))
    chosen = _select_metric(metrics, config.metric, config.category)
    if chosen is None:
        raise ValueError(
            f"no metric matching (metric={config.metric!r}, category={config.category!r}) "
            f"in benchmark results"
        )

    run = CanaryRun(
        timestamp=when,
        benchmark=getattr(benchmark, "name", config.benchmark),
        model=model_id,
        category=getattr(chosen, "category", config.category),
        metric=getattr(chosen, "name", config.metric),
        value=float(chosen.value),
        ci=(float(chosen.ci) if getattr(chosen, "ci", None) is not None else None),
        n=(int(chosen.n) if getattr(chosen, "n", None) is not None else None),
    )

    if config.series_path:
        _append_series_row(config.series_path, run)
    return run


def read_series(path: str | Path) -> list[CanaryRun]:
    """Read a canary time-series CSV back into CanaryRun rows (empty if missing)."""
    p = Path(path)
    if not p.exists():
        return []
    rows: list[CanaryRun] = []
    with p.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(
                CanaryRun(
                    timestamp=row.get("timestamp", ""),
                    benchmark=row.get("benchmark", ""),
                    model=row.get("model", ""),
                    category=row.get("category", ""),
                    metric=row.get("metric", ""),
                    value=float(row["value"]),
                    ci=_opt_float(row.get("ci")),
                    n=_opt_int(row.get("n")),
                )
            )
    return rows


def latest_vs_baseline(
    config: MonitorConfig,
    benchmark: Any,
    **kw: Any,
) -> tuple[CanaryRun, RegressionVerdict | None]:
    """Run a canary, then compare it to the locked baseline in `config`.

    Extra keyword arguments (`model`, `timestamp`, `results_dir`) are
    forwarded to `run_canary`. When `config.baseline` is None there is
    nothing to compare against, so the verdict is None.
    """
    run = run_canary(benchmark, config, **kw)
    if config.baseline is None:
        return run, None
    current = {"value": run.value, "ci": run.ci}
    verdict = detect_regression(
        current,
        config.baseline,
        rule=config.rule,
        threshold=config.threshold,
        higher_is_better=config.higher_is_better,
        metric=run.metric,
    )
    return run, verdict


# --- internal helpers ------------------------------------------------


def _select_metric(metrics: list[Any], metric_name: str, category: str) -> Any | None:
    """Pick the metric matching (name, category), with sensible fallbacks.

    Exact (name, category) match wins. Failing that, an "overall" request
    falls back to any metric named "overall" and then to the first metric.
    As a last resort a name-only match is used.
    """
    for m in metrics:
        if getattr(m, "name", None) == metric_name and getattr(m, "category", None) == category:
            return m
    if metric_name == "overall":
        for m in metrics:
            if getattr(m, "name", None) == "overall":
                return m
        if metrics:
            return metrics[0]
    for m in metrics:
        if getattr(m, "name", None) == metric_name:
            return m
    return None


def _append_series_row(path: str | Path, run: CanaryRun) -> None:
    """Append one row to the series CSV, writing the header if the file is new."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_header = not p.exists() or p.stat().st_size == 0
    with p.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        if write_header:
            writer.writerow(SERIES_HEADER)
        writer.writerow([
            run.timestamp,
            run.benchmark,
            run.model,
            run.category,
            run.metric,
            run.n if run.n is not None else "",
            f"{run.value:.6f}",
            f"{run.ci:.6f}" if run.ci is not None else "",
        ])


def _opt_float(value: Any) -> float | None:
    """Parse a possibly-empty CSV cell into a float or None."""
    if value is None or value == "":
        return None
    return float(value)


def _opt_int(value: Any) -> int | None:
    """Parse a possibly-empty CSV cell into an int or None."""
    if value is None or value == "":
        return None
    return int(value)
