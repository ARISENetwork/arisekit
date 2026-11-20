"""Offline CLI coverage for scorer, cost, and model-iteration commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import arisekit.cli as cli


def _parse(tmp_path: Path, *arguments: str) -> argparse.Namespace:
    return cli.build_parser().parse_args(
        [
            "--benchmarks-dir",
            str(tmp_path / "benchmarks"),
            "--results-dir",
            str(tmp_path / "results"),
            *arguments,
        ]
    )


def test_authoring_iteration_subcommands_are_wired(tmp_path: Path):
    rescore = _parse(
        tmp_path,
        "rescore",
        "fixture",
        "--checkpoint",
        "raw.jsonl",
    )
    preview = _parse(
        tmp_path,
        "cost-preview",
        "fixture",
        "--model",
        "provider/model",
    )
    sweep = _parse(
        tmp_path,
        "sweep",
        "fixture",
        "--model",
        "provider/a",
        "--model",
        "provider/b",
    )

    assert rescore.func is cli.cmd_rescore
    assert preview.func is cli.cmd_cost_preview
    assert sweep.func is cli.cmd_sweep
    assert sweep.model == ["provider/a", "provider/b"]


def test_rescore_delegates_explicit_checkpoint_and_reports_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    captured: dict[str, object] = {}
    revision = SimpleNamespace(
        benchmark="fixture",
        model="provider/model",
        revision_digest="a" * 64,
        receipt_path=tmp_path / "scoring-revision.json",
        item_scores_path=tmp_path / "item-scores.jsonl",
        scores_path=tmp_path / "scores.csv",
        diff=SimpleNamespace(improved=2, regressed=1, unchanged=3, added=0, removed=0),
        diff_path=tmp_path / "diff.json",
        report_path=tmp_path / "diff.md",
        missing_trials=(("case-2", 2),),
    )

    class FakeBenchmark:
        def rescore(self, checkpoint, **kwargs):
            captured["checkpoint"] = checkpoint
            captured.update(kwargs)
            return revision

    monkeypatch.setattr(cli, "_load_benchmark", lambda name, root: FakeBenchmark())
    args = _parse(
        tmp_path,
        "rescore",
        "fixture",
        "--checkpoint",
        "raw/provider.jsonl",
        "--baseline",
        "prior/scoring-revision.json",
        "--primary-metric",
        "overall/accuracy",
        "--model",
        "provider/model",
        "--expected-trials",
        "2",
        "--bootstrap",
        "25",
        "--seed",
        "7",
    )

    assert args.func(args) == 0
    assert captured == {
        "checkpoint": "raw/provider.jsonl",
        "baseline": "prior/scoring-revision.json",
        "primary_metric": "overall/accuracy",
        "bootstrap": 25,
        "seed": 7,
        "results_dir": tmp_path / "results",
        "model": "provider/model",
        "expected_trials": 2,
    }
    output = capsys.readouterr().out
    assert f"revision: {'a' * 64}" in output
    assert "changes: improved=2 regressed=1 unchanged=3 added=0 removed=0" in output
    assert "coverage: partial (1 missing trials)" in output


def test_rescore_reports_validation_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    class FakeBenchmark:
        def rescore(self, checkpoint, **kwargs):
            raise ValueError("checkpoint does not match benchmark snapshot")

    monkeypatch.setattr(cli, "_load_benchmark", lambda name, root: FakeBenchmark())
    args = _parse(
        tmp_path,
        "rescore",
        "fixture",
        "--checkpoint",
        "raw.jsonl",
    )

    assert args.func(args) == 2
    assert (
        "cannot re-score benchmark: checkpoint does not match benchmark snapshot"
        in capsys.readouterr().out
    )


def test_cost_preview_rejects_partial_explicit_pricing_before_loading_benchmark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    def unexpected_load(name, root):
        raise AssertionError("benchmark must not load for invalid pricing")

    monkeypatch.setattr(cli, "_load_benchmark", unexpected_load)
    args = _parse(
        tmp_path,
        "cost-preview",
        "fixture",
        "--model",
        "provider/model",
        "--input-usd-per-million",
        "1.25",
    )

    assert args.func(args) == 2
    assert "explicit pricing requires both input and output" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("ready", "blockers", "expected_status"),
    [
        (True, (), 0),
        (False, ("PRICING_UNKNOWN",), 1),
    ],
)
def test_cost_preview_writes_receipt_and_returns_readiness_status_without_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ready: bool,
    blockers: tuple[str, ...],
    expected_status: int,
):
    captured: dict[str, object] = {}
    output_path = tmp_path / "preview.json"

    class FakePreview:
        digest = "b" * 64
        ready_for_paid_run = ready
        blocker_codes = blockers

        def write(self, path):
            captured["written"] = Path(path)
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(json.dumps({"preview_digest": self.digest}), encoding="utf-8")

        def to_dict(self):
            return {
                "benchmark": {"name": "fixture"},
                "run": {"model_route": "provider/model"},
                "cost": {
                    "nominal_upper_bound_usd": "0.012500000000",
                    "retry_upper_bound_usd": "0.025000000000",
                },
                "budget": {"status": "within-budget" if ready else "unknown"},
            }

    class FakeBenchmark:
        def preview_cost(self, model, **kwargs):
            captured["model"] = model
            captured.update(kwargs)
            return FakePreview()

        def run(self, *args, **kwargs):
            raise AssertionError("cost preview must not dispatch a benchmark run")

    monkeypatch.setattr(cli, "_load_benchmark", lambda name, root: FakeBenchmark())
    args = _parse(
        tmp_path,
        "cost-preview",
        "fixture",
        "--model",
        "provider/model",
        "--trials",
        "3",
        "--limit",
        "4",
        "--max-tokens",
        "512",
        "--input-usd-per-million",
        "1.25",
        "--output-usd-per-million",
        "2.50",
        "--pricing-provider",
        "provider",
        "--output",
        str(output_path),
    )

    assert args.func(args) == expected_status
    assert captured["model"] == "provider/model"
    assert captured["trials"] == 3
    assert captured["limit"] == 4
    assert captured["max_tokens"] == 512
    pricing = captured["pricing"]
    assert pricing is not None
    assert pricing.model_route == "provider/model"
    assert pricing.provider == "provider"
    assert captured["written"] == output_path
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "preview_digest": "b" * 64
    }
    output = capsys.readouterr().out
    assert f"ready for paid run: {'yes' if ready else 'no'}" in output
    if blockers:
        assert "blockers: PRICING_UNKNOWN" in output


def test_python_benchmark_sweep_builds_ordered_spec_and_delegates_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    import arisekit.analysis.sweep as sweep_module

    captured: dict[str, object] = {}

    class FakeBenchmark:
        name = "fixture"
        runner_config = SimpleNamespace(trials=2, threads=3)
        allowed_model_routes = ("provider/a", "provider/b")

        def run(self, *args, **kwargs):
            raise AssertionError("the CLI must delegate execution to the sweep runner")

    def fake_run(benchmark, spec, **kwargs):
        captured["benchmark"] = benchmark
        captured["spec"] = spec
        captured.update(kwargs)
        return SimpleNamespace(
            spec=spec,
            execution_digest="c" * 64,
            succeeded=2,
            partial=0,
            failed=0,
            not_run=0,
            cost=0.125,
            calls_total=6,
            receipt_path=tmp_path / "sweep-results.json",
            scores_path=tmp_path / "sweep-scores.csv",
            report_path=tmp_path / "sweep-report.md",
            complete=True,
        )

    benchmark = FakeBenchmark()
    monkeypatch.setattr(cli, "_load_benchmark", lambda name, root: benchmark)
    monkeypatch.setattr(sweep_module, "run_benchmark_sweep", fake_run)
    args = _parse(
        tmp_path,
        "sweep",
        "fixture",
        "--model",
        "provider/a",
        "--model",
        "provider/b",
        "--provider",
        "provider/a=first-provider",
        "--model-trials",
        "provider/a=2",
        "--model-trials",
        "provider/b=4",
        "--threads",
        "4",
        "--limit",
        "5",
        "--bootstrap",
        "20",
        "--seed",
        "9",
        "--max-cost",
        "1.5",
        "--max-calls",
        "10",
    )

    assert args.func(args) == 0
    spec = captured["spec"]
    assert [model.model for model in spec.models] == ["provider/a", "provider/b"]
    assert [model.provider for model in spec.models] == ["first-provider", "litellm"]
    assert [model.trials for model in spec.models] == [2, 4]
    assert spec.threads == 4
    assert spec.limit == 5
    assert spec.bootstrap == 20
    assert spec.bootstrap_seed == 9
    assert spec.max_cost == 1.5
    assert spec.max_calls == 10
    assert captured["benchmark"] is benchmark
    assert captured["results_dir"] == tmp_path / "results"
    assert captured["provider_authorizations"] == {}
    output = capsys.readouterr().out
    assert f"sweep: {'c' * 64}" in output
    assert "succeeded=2 partial=0 failed=0 not-run=0 cost=$0.1250 calls=6" in output


def test_scaffolded_sweep_requires_ready_manifest_before_package_or_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    import arisekit.runnable as runnable_module
    import arisekit.analysis.sweep as sweep_module

    benchmark_dir = tmp_path / "benchmarks" / "fixture"
    package_dir = benchmark_dir / "package"
    package_dir.mkdir(parents=True)
    (package_dir / "benchmark.json").write_text("{}\n", encoding="utf-8")
    (benchmark_dir / "runnable-benchmark.json").write_text("{}\n", encoding="utf-8")
    verified: list[tuple[Path, object]] = []
    draft = SimpleNamespace(readiness="smoke-pending")

    monkeypatch.setattr(
        cli,
        "_load_benchmark",
        lambda name, root: SimpleNamespace(name="fixture"),
    )
    monkeypatch.setattr(runnable_module, "load_manifest", lambda path: draft)
    monkeypatch.setattr(
        runnable_module,
        "verify_assets",
        lambda root, manifest: verified.append((Path(root), manifest)),
    )
    monkeypatch.setattr(
        cli,
        "_load_runtime_package",
        lambda path: (_ for _ in ()).throw(
            AssertionError("package must not load until readiness passes")
        ),
    )
    monkeypatch.setattr(
        sweep_module,
        "run_benchmark_sweep",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("sweep must not dispatch until readiness passes")
        ),
    )
    args = _parse(tmp_path, "sweep", "fixture")

    assert args.func(args) == 2
    assert verified == [(benchmark_dir, draft)]
    assert (
        "scaffolded benchmark must pass its exact smoke test before a sweep"
        in capsys.readouterr().out
    )
