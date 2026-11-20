"""Offline tests for arisekit.monitor.

Regression detection is pure and exhaustively tested across all three
rules in both directions. The canary path is exercised with a FAKE
benchmark (a small class exposing `.name` and `.run(...)`) so no model is
ever called and nothing touches the network.
"""

from pathlib import Path

from arisekit.monitor import (
    CanaryRun,
    MonitorConfig,
    detect_regression,
    detect_series_regression,
    latest_vs_baseline,
    read_series,
    run_canary,
)


# --- fakes -----------------------------------------------------------


class FakeMetric:
    """Metric-like with the attributes run_canary reads."""

    def __init__(self, name, value, category="overall", ci=None, n=None):
        self.name = name
        self.value = value
        self.category = category
        self.ci = ci
        self.n = n


class FakeResults:
    def __init__(self, metrics):
        self.metrics = metrics


class FakeBenchmark:
    """Duck-typed benchmark: `.name` plus a `.run(...)` returning `.metrics`."""

    def __init__(self, name, metrics):
        self.name = name
        self._metrics = metrics
        self.calls = []

    def run(self, model, *, trials=None, limit=None, bootstrap=0, results_dir=None):
        self.calls.append(
            {
                "model": model,
                "trials": trials,
                "limit": limit,
                "bootstrap": bootstrap,
                "results_dir": results_dir,
            }
        )
        return FakeResults(list(self._metrics))


# --- detect_regression: ci_nonoverlap --------------------------------


def test_ci_nonoverlap_overlapping_is_not_regression():
    current = {"value": 0.87, "ci": 0.05}
    baseline = {"value": 0.90, "ci": 0.05}
    verdict = detect_regression(current, baseline, rule="ci_nonoverlap")
    assert verdict.is_regression is False
    assert verdict.recommend_rollback is False
    assert "within tolerance" in verdict.message
    assert abs(verdict.delta - (-0.03)) < 1e-9


def test_ci_nonoverlap_clear_drop_is_regression():
    current = {"value": 0.80, "ci": 0.02}
    baseline = {"value": 0.90, "ci": 0.02}
    verdict = detect_regression(current, baseline, rule="ci_nonoverlap")
    assert verdict.is_regression is True
    assert verdict.recommend_rollback is True
    assert "human review recommended" in verdict.message


def test_ci_nonoverlap_lower_is_better_regression():
    # Error rate went up and the intervals do not overlap.
    current = {"value": 0.20, "ci": 0.01}
    baseline = {"value": 0.10, "ci": 0.01}
    verdict = detect_regression(
        current, baseline, rule="ci_nonoverlap", higher_is_better=False
    )
    assert verdict.is_regression is True


def test_ci_nonoverlap_lower_is_better_improvement_not_regression():
    # Error rate dropped: an improvement, never a regression.
    current = {"value": 0.05, "ci": 0.01}
    baseline = {"value": 0.10, "ci": 0.01}
    verdict = detect_regression(
        current, baseline, rule="ci_nonoverlap", higher_is_better=False
    )
    assert verdict.is_regression is False


def test_ci_none_treated_as_zero():
    current = {"value": 0.80, "ci": None}
    baseline = {"value": 0.90}  # missing ci key entirely
    verdict = detect_regression(current, baseline, rule="ci_nonoverlap")
    assert verdict.is_regression is True


# --- detect_regression: abs_delta ------------------------------------


def test_abs_delta_over_threshold_is_regression():
    verdict = detect_regression(
        {"value": 0.80}, {"value": 0.90}, rule="abs_delta", threshold=0.05
    )
    assert verdict.is_regression is True


def test_abs_delta_boundary_is_strict():
    # Worsening exactly equal to the threshold is NOT a regression (strict >).
    verdict = detect_regression(
        {"value": 0.80}, {"value": 0.90}, rule="abs_delta", threshold=0.10
    )
    assert verdict.is_regression is False
    # Just under the boundary flips it.
    verdict2 = detect_regression(
        {"value": 0.80}, {"value": 0.90}, rule="abs_delta", threshold=0.099
    )
    assert verdict2.is_regression is True


def test_abs_delta_lower_is_better():
    verdict = detect_regression(
        {"value": 0.20},
        {"value": 0.10},
        rule="abs_delta",
        threshold=0.05,
        higher_is_better=False,
    )
    assert verdict.is_regression is True


def test_abs_delta_requires_threshold():
    try:
        detect_regression({"value": 0.8}, {"value": 0.9}, rule="abs_delta")
    except ValueError as exc:
        assert "threshold" in str(exc)
    else:
        raise AssertionError("expected ValueError when abs_delta has no threshold")


# --- detect_regression: rel_delta ------------------------------------


def test_rel_delta_over_threshold_is_regression():
    # 20% relative drop exceeds a 10% threshold.
    verdict = detect_regression(
        {"value": 0.80}, {"value": 1.00}, rule="rel_delta", threshold=0.10
    )
    assert verdict.is_regression is True


def test_rel_delta_under_threshold_not_regression():
    verdict = detect_regression(
        {"value": 0.80}, {"value": 1.00}, rule="rel_delta", threshold=0.25
    )
    assert verdict.is_regression is False


def test_rel_delta_zero_baseline_guard():
    # abs(baseline) == 0 must not divide by zero; falls back to abs worsening.
    verdict = detect_regression(
        {"value": -0.5}, {"value": 0.0}, rule="rel_delta", threshold=0.1
    )
    assert verdict.is_regression is True


def test_unknown_rule_raises():
    try:
        detect_regression({"value": 0.8}, {"value": 0.9}, rule="nope")
    except ValueError as exc:
        assert "rule" in str(exc)
    else:
        raise AssertionError("expected ValueError on unknown rule")


# --- detect_series_regression ----------------------------------------


def test_series_flags_monotonic_decline_without_baseline():
    series = [{"value": 0.90}, {"value": 0.85}, {"value": 0.80}]
    verdict = detect_series_regression(series, None, consecutive=3)
    assert verdict.is_regression is True
    assert "trend" in verdict.message
    assert abs(verdict.current_value - 0.80) < 1e-9


def test_series_no_decline_is_not_regression():
    series = [{"value": 0.90}, {"value": 0.85}, {"value": 0.88}]
    verdict = detect_series_regression(series, None, consecutive=3)
    assert verdict.is_regression is False


def test_series_lower_is_better_rising_trend_flags():
    # For an error-rate metric, a steadily rising series is the decline.
    series = [{"value": 0.10}, {"value": 0.15}, {"value": 0.22}]
    verdict = detect_series_regression(
        series, None, consecutive=3, higher_is_better=False
    )
    assert verdict.is_regression is True


def test_series_empty_is_safe():
    verdict = detect_series_regression([], None)
    assert verdict.is_regression is False


def test_series_baseline_rule_also_fires():
    # No monotonic trend, but the latest point breaches the baseline CI.
    series = [{"value": 0.90, "ci": 0.01}, {"value": 0.95, "ci": 0.01}, {"value": 0.80, "ci": 0.01}]
    baseline = {"value": 0.90, "ci": 0.01}
    verdict = detect_series_regression(
        series, baseline, consecutive=3, rule="ci_nonoverlap"
    )
    assert verdict.is_regression is True


# --- run_canary + read_series ----------------------------------------


def test_run_canary_appends_row_and_read_series(tmp_path: Path):
    series_path = tmp_path / "series.csv"
    config = MonitorConfig(
        benchmark="demo",
        model="deployed-model",
        metric="overall",
        category="overall",
        series_path=str(series_path),
    )
    bench = FakeBenchmark(
        "demo", [FakeMetric("overall", 0.82, ci=0.03, n=100)]
    )

    run = run_canary(bench, config, timestamp="2026-07-12T00:00:00+00:00")
    assert isinstance(run, CanaryRun)
    assert run.timestamp == "2026-07-12T00:00:00+00:00"
    assert run.benchmark == "demo"
    assert run.model == "deployed-model"
    assert run.metric == "overall"
    assert abs(run.value - 0.82) < 1e-9
    assert run.n == 100

    # The fake benchmark received the forwarded run parameters.
    assert bench.calls[-1]["model"] == "deployed-model"

    rows = read_series(series_path)
    assert len(rows) == 1
    assert rows[0].timestamp == "2026-07-12T00:00:00+00:00"
    assert abs(rows[0].value - 0.82) < 1e-6
    assert rows[0].ci is not None and abs(rows[0].ci - 0.03) < 1e-6
    assert rows[0].n == 100

    # A second run appends without re-writing the header.
    run_canary(bench, config, timestamp="2026-07-13T00:00:00+00:00")
    rows2 = read_series(series_path)
    assert len(rows2) == 2
    assert rows2[1].timestamp == "2026-07-13T00:00:00+00:00"


def test_run_canary_model_override_and_no_series(tmp_path: Path):
    config = MonitorConfig(benchmark="demo", model="config-model", series_path=None)
    bench = FakeBenchmark("demo", [FakeMetric("overall", 0.5)])
    run = run_canary(bench, config, model="override-model", timestamp="t0")
    assert run.model == "override-model"
    # No series_path means nothing is written; read_series of a missing file is empty.
    assert read_series(tmp_path / "missing.csv") == []


def test_run_canary_metric_selection_fallback_to_first():
    config = MonitorConfig(benchmark="demo", model="m", metric="overall")
    # No metric literally named "overall": fall back to the first metric.
    bench = FakeBenchmark("demo", [FakeMetric("accuracy", 0.7)])
    run = run_canary(bench, config, timestamp="t0")
    assert run.metric == "accuracy"
    assert abs(run.value - 0.7) < 1e-9


def test_run_canary_exact_category_selection():
    config = MonitorConfig(
        benchmark="demo", model="m", metric="f1", category="cardiology"
    )
    bench = FakeBenchmark(
        "demo",
        [
            FakeMetric("f1", 0.6, category="overall"),
            FakeMetric("f1", 0.9, category="cardiology"),
        ],
    )
    run = run_canary(bench, config, timestamp="t0")
    assert run.category == "cardiology"
    assert abs(run.value - 0.9) < 1e-9


def test_run_canary_no_matching_metric_raises():
    config = MonitorConfig(benchmark="demo", model="m", metric="precision")
    bench = FakeBenchmark("demo", [FakeMetric("accuracy", 0.7)])
    try:
        run_canary(bench, config, timestamp="t0")
    except ValueError as exc:
        assert "precision" in str(exc)
    else:
        raise AssertionError("expected ValueError when no metric matches")


# --- latest_vs_baseline ----------------------------------------------


def test_latest_vs_baseline_no_baseline_returns_none_verdict():
    config = MonitorConfig(benchmark="demo", model="m", baseline=None)
    bench = FakeBenchmark("demo", [FakeMetric("overall", 0.8)])
    run, verdict = latest_vs_baseline(config, bench, timestamp="t0")
    assert isinstance(run, CanaryRun)
    assert verdict is None


def test_latest_vs_baseline_flags_regression():
    config = MonitorConfig(
        benchmark="demo",
        model="m",
        rule="ci_nonoverlap",
        baseline={"value": 0.90, "ci": 0.02},
    )
    bench = FakeBenchmark("demo", [FakeMetric("overall", 0.80, ci=0.02)])
    run, verdict = latest_vs_baseline(config, bench, timestamp="t0")
    assert verdict is not None
    assert verdict.is_regression is True
    assert "overall" in verdict.message


# --- MonitorConfig JSON round-trip -----------------------------------


def test_config_json_roundtrip_string():
    config = MonitorConfig(
        benchmark="noharm",
        model="gpt-x",
        metric="F1_weighted",
        category="overall",
        rule="abs_delta",
        threshold=0.05,
        higher_is_better=True,
        bootstrap=2000,
        trials=3,
        limit=100,
        series_path="results/canary/noharm.csv",
        baseline={"value": 0.7, "ci": 0.02},
    )
    text = config.to_json()
    restored = MonitorConfig.from_json(text)
    assert restored == config


def test_config_json_roundtrip_file(tmp_path: Path):
    config = MonitorConfig(benchmark="b", model="m", baseline={"value": 0.5})
    path = tmp_path / "canary.json"
    written = config.to_json(path)
    assert isinstance(written, str)
    assert path.exists()
    restored = MonitorConfig.from_json(path)
    assert restored == config


def test_config_from_dict_ignores_unknown_keys():
    data = {"benchmark": "b", "model": "m", "unexpected": 123}
    config = MonitorConfig.from_dict(data)
    assert config.benchmark == "b"
    assert config.model == "m"
    assert config.metric == "overall"
