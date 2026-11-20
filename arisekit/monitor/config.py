"""Configuration for scheduled canary monitoring.

A MonitorConfig is a plain, JSON-serializable description of one canary:
which benchmark to re-run, against which deployed model, which metric to
watch, and how to decide whether the latest reading is a candidate
regression versus a locked baseline. It is deliberately host-agnostic so
any scheduler (cron, Airflow, GitHub Actions) can load it from a file and
hand it to `run_canary` without importing an interactive harness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MonitorConfig:
    """Everything a scheduled canary needs, as serializable fields.

    - `benchmark` / `model`: identifiers for the canary target.
    - `metric` / `category`: which aggregated metric to track.
    - `rule`: regression rule name understood by `drift.detect_regression`.
    - `threshold`: magnitude threshold for the abs/rel delta rules.
    - `higher_is_better`: metric direction (accuracy up, error rate down).
    - `bootstrap` / `trials` / `limit`: forwarded to the benchmark run.
    - `series_path`: where the dated metric time series is appended.
    - `baseline`: optional locked reference, e.g. {"value": .., "ci": ..}.
    """

    benchmark: str
    model: str
    metric: str = "overall"
    category: str = "overall"
    rule: str = "ci_nonoverlap"
    threshold: float | None = None
    higher_is_better: bool = True
    bootstrap: int = 0
    trials: int | None = None
    limit: int | None = None
    series_path: str | None = None
    baseline: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict of every field."""
        return {
            "benchmark": self.benchmark,
            "model": self.model,
            "metric": self.metric,
            "category": self.category,
            "rule": self.rule,
            "threshold": self.threshold,
            "higher_is_better": self.higher_is_better,
            "bootstrap": self.bootstrap,
            "trials": self.trials,
            "limit": self.limit,
            "series_path": self.series_path,
            "baseline": dict(self.baseline) if self.baseline is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MonitorConfig":
        """Build a MonitorConfig from a dict, ignoring unknown keys."""
        threshold = data.get("threshold")
        baseline = data.get("baseline")
        return cls(
            benchmark=str(data["benchmark"]),
            model=str(data["model"]),
            metric=str(data.get("metric", "overall")),
            category=str(data.get("category", "overall")),
            rule=str(data.get("rule", "ci_nonoverlap")),
            threshold=float(threshold) if threshold is not None else None,
            higher_is_better=bool(data.get("higher_is_better", True)),
            bootstrap=int(data.get("bootstrap", 0)),
            trials=_opt_int(data.get("trials")),
            limit=_opt_int(data.get("limit")),
            series_path=_opt_str(data.get("series_path")),
            baseline=dict(baseline) if isinstance(baseline, dict) else None,
        )

    def to_json(self, path: str | Path | None = None) -> str:
        """Serialize to a JSON string; also write it to `path` if given."""
        text = json.dumps(self.to_dict(), indent=2, sort_keys=True)
        if path is not None:
            out = Path(path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + "\n", encoding="utf-8")
        return text

    @classmethod
    def from_json(cls, path_or_str: str | Path) -> "MonitorConfig":
        """Load from a JSON file path if it exists, else parse as a JSON string."""
        text = str(path_or_str)
        try:
            candidate = Path(text)
            if candidate.exists():
                text = candidate.read_text(encoding="utf-8")
        except OSError:
            # `path_or_str` was JSON content that is not a valid path on this OS.
            pass
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("MonitorConfig JSON must decode to an object")
        return cls.from_dict(data)


def _opt_int(value: Any) -> int | None:
    """Coerce to int, preserving None."""
    return int(value) if value is not None else None


def _opt_str(value: Any) -> str | None:
    """Coerce to str, preserving None."""
    return str(value) if value is not None else None
