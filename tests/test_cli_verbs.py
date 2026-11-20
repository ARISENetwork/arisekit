"""Offline tests for arisekit.cli_verbs.

Every verb here is pure CSV-in / artifact-out: no model, judge, or network
call is ever made. ``cmd_report`` and ``cmd_compare`` are exercised end to
end against small CSV fixtures written into ``tmp_path``; ``cmd_monitor`` is
exercised with a fake benchmark monkeypatched over the loader, so the canary
path runs entirely in memory.
"""

from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

import arisekit.cli as clim
from arisekit.cli_verbs import (
    cmd_compare,
    cmd_monitor,
    cmd_report,
    metrics_from_csv,
)
from arisekit.monitor import MonitorConfig


# --- fixtures --------------------------------------------------------


def _write_scores_csv(path: Path, rows: list[list[object]]) -> Path:
    """Write a MAST scores CSV (header + rows) and return the path."""
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["benchmark", "model", "category", "metric", "n", "value", "ci"])
        for row in rows:
            writer.writerow(row)
    return path


# --- metrics_from_csv ------------------------------------------------


def test_metrics_from_csv_parses_rows_and_skips_bad_values(tmp_path: Path) -> None:
    path = _write_scores_csv(
        tmp_path / "scores.csv",
        [
            ["b", "m", "overall", "F1", 100, 0.8, 0.05],
            ["b", "m", "", "precision", 100, 0.7, ""],  # blank category, blank ci
            ["b", "m", "overall", "broken", 100, "", 0.01],  # empty value -> skipped
            ["b", "m", "overall", "words", 100, "n/a", 0.01],  # non-float -> skipped
        ],
    )
    metrics = metrics_from_csv(path)
    assert [m.name for m in metrics] == ["F1", "precision"]
    f1 = metrics[0]
    assert f1.value == 0.8
    assert f1.ci == 0.05
    assert f1.n == 100
    # Blank category normalizes to overall; blank ci becomes None.
    precision = metrics[1]
    assert precision.category == "overall"
    assert precision.ci is None


# --- cmd_report ------------------------------------------------------


def test_cmd_report_writes_card_with_disclaimer_and_checklist(tmp_path: Path) -> None:
    scores = _write_scores_csv(
        tmp_path / "scores.csv",
        [
            ["b", "m", "overall", "F1", 100, 0.8, 0.05],
            ["b", "m", "cat1", "precision", 100, 0.7, 0.04],
        ],
    )
    out = tmp_path / "card.md"
    args = SimpleNamespace(
        scores=str(scores),
        model=None,
        compiled=False,
        checklist="tripod_llm",
        output=str(out),
    )
    assert cmd_report(args) == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    # The model-card disclaimer is present and framed as evidence.
    assert "not a certification" in text.lower()
    # The appended checklist coverage report is present.
    assert "coverage report" in text.lower()
    assert "auto-satisfied" in text.lower()
    # The measured metric survives into the card.
    assert "F1" in text


def test_cmd_report_prints_when_no_output(tmp_path: Path, capsys) -> None:
    scores = _write_scores_csv(
        tmp_path / "scores.csv",
        [["b", "m", "overall", "F1", 100, 0.8, 0.05]],
    )
    args = SimpleNamespace(
        scores=str(scores),
        model=None,
        compiled=False,
        checklist=None,
        output=None,
    )
    assert cmd_report(args) == 0
    captured = capsys.readouterr()
    assert "Applied model card" in captured.out


def test_cmd_report_compiled_mode_uses_model(tmp_path: Path, capsys) -> None:
    # Two models in one compiled.csv; only the requested model is carded.
    compiled = _write_scores_csv(
        tmp_path / "compiled.csv",
        [
            ["b1", "m1", "overall", "F1", 100, 0.8, 0.05],
            ["b2", "m2", "overall", "F1", 100, 0.9, 0.05],
        ],
    )
    args = SimpleNamespace(
        scores=str(compiled),
        model="m1",
        compiled=True,
        checklist=None,
        output=None,
    )
    assert cmd_report(args) == 0
    captured = capsys.readouterr()
    assert "m1" in captured.out


# --- cmd_compare -----------------------------------------------------


def test_cmd_compare_writes_scorecard_csv_with_composite(tmp_path: Path, capsys) -> None:
    p1 = _write_scores_csv(
        tmp_path / "alpha.csv",
        [["b", "alpha", "overall", "F1", 100, 0.80, 0.05]],
    )
    p2 = _write_scores_csv(
        tmp_path / "beta.csv",
        [["b", "beta", "overall", "F1", 100, 0.60, 0.05]],
    )
    out = tmp_path / "sc.csv"
    args = SimpleNamespace(
        vendor=[f"alpha={p1}", f"beta={p2}"],
        output=str(out),
        higher_is_better=None,
    )
    assert cmd_compare(args) == 0
    assert out.exists()

    with out.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    first_cells = {row[0] for row in rows if row}
    assert "composite" in first_cells
    assert "rank" in first_cells
    # The scorecard is also rendered to stdout.
    captured = capsys.readouterr()
    assert "Comparative scorecard" in captured.out


def test_cmd_compare_malformed_vendor_returns_2(tmp_path: Path) -> None:
    args = SimpleNamespace(
        vendor=["no-equals-sign"],
        output=None,
        higher_is_better=None,
    )
    assert cmd_compare(args) == 2


def test_cmd_compare_direction_override_applies(tmp_path: Path, capsys) -> None:
    # error_rate is lower-is-better; the override must flip the ranking so the
    # smaller value wins the composite.
    p1 = _write_scores_csv(
        tmp_path / "alpha.csv",
        [["b", "alpha", "overall", "error_rate", 100, 0.10, 0.01]],
    )
    p2 = _write_scores_csv(
        tmp_path / "beta.csv",
        [["b", "beta", "overall", "error_rate", 100, 0.40, 0.01]],
    )
    args = SimpleNamespace(
        vendor=[f"alpha={p1}", f"beta={p2}"],
        output=None,
        higher_is_better="error_rate:false",
    )
    assert cmd_compare(args) == 0
    captured = capsys.readouterr()
    lines = [ln for ln in captured.out.splitlines() if ln.startswith("| 1 |")]
    assert lines and "alpha" in lines[0]


# --- cmd_monitor -----------------------------------------------------


class _FakeMetric:
    """Metric-like exposing exactly the attributes the canary path reads."""

    def __init__(self, name, value, category="overall", ci=None, n=None):
        self.name = name
        self.value = value
        self.category = category
        self.ci = ci
        self.n = n


class _FakeBenchmark:
    """Duck-typed benchmark: ``.name`` plus a ``.run(...)`` with ``.metrics``."""

    def __init__(self, name, metrics):
        self.name = name
        self._metrics = metrics

    def run(self, model, *, trials=None, limit=None, bootstrap=0, results_dir=None):
        return SimpleNamespace(metrics=list(self._metrics))


def test_cmd_monitor_detects_regression(tmp_path: Path, monkeypatch, capsys) -> None:
    cfg_path = tmp_path / "cfg.json"
    MonitorConfig(
        benchmark="demo",
        model="m",
        metric="overall",
        baseline={"value": 0.9, "ci": 0.02},
        rule="ci_nonoverlap",
    ).to_json(cfg_path)

    fake = _FakeBenchmark(
        "demo",
        [_FakeMetric("overall", 0.5, "overall", 0.02, 10)],
    )
    monkeypatch.setattr(clim, "_load_benchmark", lambda name, d: fake)

    args = SimpleNamespace(
        config=str(cfg_path),
        benchmark="demo",
        benchmarks_dir=".",
        model=None,
        timestamp="t0",
    )
    assert cmd_monitor(args) == 0
    captured = capsys.readouterr()
    # The reading drops 0.9 -> 0.5, so a candidate regression is flagged.
    assert "is_regression=True" in captured.out
    assert "recommend_rollback=True" in captured.out
    assert "t0" in captured.out


def test_cmd_monitor_no_baseline_records_canary_only(tmp_path: Path, monkeypatch, capsys) -> None:
    cfg_path = tmp_path / "cfg.json"
    MonitorConfig(benchmark="demo", model="m", metric="overall").to_json(cfg_path)

    fake = _FakeBenchmark(
        "demo",
        [_FakeMetric("overall", 0.7, "overall", 0.02, 10)],
    )
    monkeypatch.setattr(clim, "_load_benchmark", lambda name, d: fake)

    args = SimpleNamespace(
        config=str(cfg_path),
        benchmark="demo",
        benchmarks_dir=".",
        model=None,
        timestamp="t1",
    )
    assert cmd_monitor(args) == 0
    captured = capsys.readouterr()
    assert "no baseline in config; recorded canary only" in captured.out
