"""Smoke test: discover the demo benchmark via the CLI helper and run it
against a stub client so the whole loop (load -> run -> score -> CSV)
gets exercised without hitting a real model."""

import csv
from pathlib import Path

from arisekit.cli import _load_benchmark
from arisekit.client import ModelCall, ModelResponse


REPO_ROOT = Path(__file__).resolve().parent.parent


class TriviaStub:
    """Knows the 5 demo answers; anything else returns empty."""

    model = "trivia-stub"
    _answers = {
        "demo-1": "Paris",
        "demo-2": "4",
        "demo-3": "heart",
        "demo-4": "C",
        "demo-5": "Jupiter",
    }

    def __call__(self, call: ModelCall) -> ModelResponse:
        return ModelResponse(text=self._answers.get(call.item.id, ""), cost=0.0001)


def test_demo_benchmark_loads_and_runs(tmp_path: Path):
    bench = _load_benchmark("demo", REPO_ROOT / "benchmarks")
    assert bench.name == "demo"
    assert len(bench.dataset) == 5
    assert bench.dataset.system_prompt is not None

    results = bench.run(model=TriviaStub(), results_dir=tmp_path)
    assert results.summary.completed == 5
    assert results.summary.errored == 0
    # Perfect score from the stub.
    assert abs(results.metrics[0].value - 1.0) < 1e-9

    # The scores CSV uses the documented MAST shape.
    scores_csv = tmp_path / "scores" / "demo" / "trivia-stub.csv"
    assert scores_csv.exists()
    with scores_csv.open() as fh:
        rows = list(csv.DictReader(fh))
    assert rows == [
        {
            "benchmark": "demo",
            "model": "trivia-stub",
            "category": "overall",
            "metric": "accuracy",
            "n": "5",
            "value": f"{1.0:.6f}",
            "ci": "0.000000",
        }
    ]
