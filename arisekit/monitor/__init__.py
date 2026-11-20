"""Scheduled canary monitoring for ARISEKit benchmarks.

Turn any benchmark into a canary that a host scheduler (cron, Airflow,
GitHub Actions) re-runs against a deployed endpoint. Each run appends a
dated metric reading to a CSV time series and, when a locked baseline is
configured, produces an advisory verdict flagging candidate regressions
for human review. Verdicts are evidence a human owner interprets, never a
pass/fail gate.

Typical host-scheduler entry point::

    from arisekit.monitor import MonitorConfig, latest_vs_baseline
    config = MonitorConfig.from_json("canary.json")
    run, verdict = latest_vs_baseline(config, my_benchmark)
"""

from __future__ import annotations

from arisekit.monitor.canary import (
    CanaryRun,
    SERIES_HEADER,
    latest_vs_baseline,
    read_series,
    run_canary,
)
from arisekit.monitor.config import MonitorConfig
from arisekit.monitor.drift import (
    RegressionVerdict,
    detect_regression,
    detect_series_regression,
)

__all__ = [
    "MonitorConfig",
    "CanaryRun",
    "SERIES_HEADER",
    "run_canary",
    "read_series",
    "latest_vs_baseline",
    "detect_regression",
    "detect_series_regression",
    "RegressionVerdict",
]
