"""Public API contract for the local author-iteration milestone."""

from __future__ import annotations

import inspect

import arisekit


def test_authoring_iteration_contracts_are_exported() -> None:
    expected = {
        "BenchmarkScoringError",
        "CapturedResponses",
        "ScoringRevision",
        "RescoreError",
        "ScorerIdentity",
        "load_responses",
        "load_scoring_revision",
        "rescore",
        "ScoreDiff",
        "diff",
        "top_changes",
        "CostPreview",
        "PricingSnapshot",
        "preview_benchmark_cost",
        "BenchmarkSweepSpec",
        "BenchmarkSweepResults",
        "SweepModel",
        "run_benchmark_sweep",
        "sweep_spec_from_package",
        "AgentCostUnknownError",
    }

    assert expected.issubset(arisekit.__all__)
    assert all(hasattr(arisekit, name) for name in expected)
    assert arisekit.SCORING_REVISION_SCHEMA_VERSION == (
        "arisekit.scoring-revision.v1"
    )
    assert arisekit.COST_PREVIEW_SCHEMA_VERSION == "arisekit.cost-preview.v1"
    assert arisekit.SWEEP_SPEC_SCHEMA_VERSION == "arisekit.benchmark-sweep.v1"
    assert arisekit.SWEEP_RESULTS_SCHEMA_VERSION == (
        "arisekit.benchmark-sweep-results.v1"
    )


def test_benchmark_exposes_typed_iteration_conveniences() -> None:
    run_parameters = inspect.signature(arisekit.Benchmark.run).parameters

    assert "bootstrap_seed" in run_parameters
    assert hasattr(arisekit.Benchmark, "rescore")
    assert hasattr(arisekit.Benchmark, "preview_cost")
    assert hasattr(arisekit.Benchmark, "run_many")

