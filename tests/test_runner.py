"""The resume test is the load-bearing one here.

Kill a run mid-way (simulated by failing the client), let the runner
write what it has, then restart with a healthy client — the completed
rows should be reused and only the failed ones retried.
"""

import json
from pathlib import Path

from arisekit import BenchmarkItem, Dataset
from arisekit.client import ModelCall, ModelResponse
from arisekit.runner import RunnerConfig, run


class EchoClient:
    """Deterministic client. Always returns the prompt text as the answer."""

    model = "echo"

    def __init__(self, *, fail_on: set[str] | None = None):
        self.fail_on = fail_on or set()
        self.calls = 0

    def __call__(self, call: ModelCall) -> ModelResponse:
        self.calls += 1
        if call.item.id in self.fail_on:
            raise RuntimeError(f"forced failure on {call.item.id}")
        return ModelResponse(
            text=str(call.item.prompt),
            tokens_in=10,
            tokens_out=5,
            cost=0.001,
            provider_model="echo-2026-07-01",
            response_id=f"response-{call.item.id}",
        )


def _ds(n: int = 3) -> Dataset:
    items = [BenchmarkItem(id=f"i{i}", prompt=f"Q{i}", ground_truth=f"Q{i}") for i in range(n)]
    return Dataset.from_items(items)


def test_basic_run_writes_jsonl(tmp_path: Path):
    client = EchoClient()
    cfg = RunnerConfig(trials=1, threads=1, results_dir=tmp_path)
    results, summary = run(_ds(3), model=client, benchmark_name="t", config=cfg)
    assert summary.completed == 3
    assert summary.errored == 0
    assert summary.output_path.exists()
    lines = summary.output_path.read_text().strip().split("\n")
    assert len(lines) == 3
    payload = json.loads(lines[0])
    assert payload["error"] is None
    assert payload["metadata"]["cost"] == 0.001
    assert payload["metadata"]["provider_model"] == "echo-2026-07-01"
    assert payload["metadata"]["provider_response_id"] == "response-i0"


def test_resume_skips_completed_rows(tmp_path: Path):
    cfg = RunnerConfig(trials=1, threads=1, max_retries=1, results_dir=tmp_path)
    # First pass: i1 fails; i0 and i2 succeed.
    bad = EchoClient(fail_on={"i1"})
    results1, summary1 = run(_ds(3), model=bad, benchmark_name="t", config=cfg)
    assert summary1.completed == 2
    assert summary1.errored == 1

    # Second pass: healthy client. The runner should skip i0/i2 and
    # only retry i1.
    good = EchoClient()
    results2, summary2 = run(_ds(3), model=good, benchmark_name="t", config=cfg)
    assert good.calls == 1, f"runner should only retry the errored item; called {good.calls} times"
    assert summary2.skipped == 2
    assert summary2.errored == 0

    # The final merged set covers all three items, all successful.
    all_ids = {r.id for r in results2 if r.error is None}
    assert all_ids == {"i0", "i1", "i2"}


def test_retry_then_succeed_within_same_run(tmp_path: Path):
    class FlakyClient:
        model = "flaky"
        def __init__(self) -> None:
            self.calls = 0
        def __call__(self, call: ModelCall) -> ModelResponse:
            self.calls += 1
            if self.calls < 2:
                raise RuntimeError("transient")
            return ModelResponse(text="ok", cost=0.0)

    cfg = RunnerConfig(
        trials=1, threads=1, max_retries=3, retry_backoff=0.0, results_dir=tmp_path,
    )
    flaky = FlakyClient()
    items = [BenchmarkItem(id="only", prompt="Q")]
    results, summary = run(
        Dataset.from_items(items), model=flaky, benchmark_name="t", config=cfg,
    )
    assert summary.completed == 1
    assert summary.errored == 0
    assert flaky.calls == 2
    metadata = results[0].metadata
    assert metadata["attempts"] == 2
    assert [row["outcome"] for row in metadata["attempt_records"]] == [
        "failed",
        "succeeded",
    ]
    assert all(row["latency_seconds"] >= 0 for row in metadata["attempt_records"])
    assert metadata["latency_seconds"] >= 0


def test_parallel_run_persists_all_rows(tmp_path: Path):
    cfg = RunnerConfig(trials=1, threads=4, results_dir=tmp_path)
    client = EchoClient()
    results, summary = run(_ds(20), model=client, benchmark_name="t", config=cfg)
    assert summary.completed == 20
    # All 20 lines should be present and parseable, no interleaving.
    lines = summary.output_path.read_text().strip().split("\n")
    assert len(lines) == 20
    for line in lines:
        json.loads(line)


def test_multiple_trials(tmp_path: Path):
    cfg = RunnerConfig(trials=3, threads=1, results_dir=tmp_path)
    client = EchoClient()
    results, summary = run(_ds(2), model=client, benchmark_name="t", config=cfg)
    assert summary.completed == 6  # 2 items x 3 trials
    trials = {(r.id, r.trial) for r in results}
    assert trials == {("i0", 1), ("i0", 2), ("i0", 3), ("i1", 1), ("i1", 2), ("i1", 3)}


def test_cost_budget_stops_new_calls_and_is_respected_on_resume(tmp_path: Path):
    class CostlyClient(EchoClient):
        def __call__(self, call: ModelCall) -> ModelResponse:
            self.calls += 1
            return ModelResponse(text="ok", cost=0.6)

    cfg = RunnerConfig(
        trials=1,
        threads=1,
        max_retries=1,
        results_dir=tmp_path,
        max_cost=1.0,
    )
    first_client = CostlyClient()
    results, summary = run(
        _ds(4), model=first_client, benchmark_name="budget", config=cfg
    )

    assert first_client.calls == 2
    assert summary.completed == 2
    assert summary.errored == 2
    assert summary.cost_total == 1.2
    assert summary.budget_exhausted is True
    assert sum(result.metadata.get("budget_exhausted") is True for result in results) == 2

    resumed_client = CostlyClient()
    _results, resumed = run(
        _ds(4), model=resumed_client, benchmark_name="budget", config=cfg
    )
    assert resumed_client.calls == 0
    assert resumed.skipped == 2
    assert resumed.budget_exhausted is True


def test_per_call_reservations_prevent_parallel_budget_overshoot(tmp_path: Path):
    class CostlyClient(EchoClient):
        def __call__(self, call: ModelCall) -> ModelResponse:
            self.calls += 1
            return ModelResponse(text="ok", cost=0.6)

    client = CostlyClient()
    results, summary = run(
        _ds(4),
        model=client,
        benchmark_name="reserved-budget",
        config=RunnerConfig(
            threads=4,
            max_retries=1,
            results_dir=tmp_path,
            max_cost=1.0,
            max_cost_per_call=0.6,
            require_known_cost=True,
        ),
    )

    assert client.calls == 1
    assert summary.completed == 1
    assert summary.errored == 3
    assert summary.cost_total == 0.6
    assert summary.budget_exhausted is True
    assert sum(
        result.metadata.get("budget_exhausted") is True for result in results
    ) == 3


def test_reported_cost_above_reserved_bound_fails_closed_and_is_resume_safe(
    tmp_path: Path,
):
    class BoundBreakingClient(EchoClient):
        def __call__(self, call: ModelCall) -> ModelResponse:
            self.calls += 1
            return ModelResponse(text="ok", cost=0.4)

    config = RunnerConfig(
        threads=1,
        max_retries=1,
        results_dir=tmp_path,
        max_cost=10.0,
        max_cost_per_call=0.2,
        require_known_cost=True,
    )
    client = BoundBreakingClient()
    results, summary = run(
        _ds(4),
        model=client,
        benchmark_name="bound-violation",
        config=config,
    )

    assert client.calls == 1
    assert summary.completed == 0
    assert summary.errored == 4
    assert summary.cost_total == 0.4
    assert summary.cost_bound_exceeded is True
    assert all(
        result.metadata.get("cost_bound_exceeded") is True for result in results
    )

    resumed_client = BoundBreakingClient()
    _resumed_results, resumed = run(
        _ds(4),
        model=resumed_client,
        benchmark_name="bound-violation",
        config=config,
    )
    assert resumed_client.calls == 0
    assert resumed.skipped == 4
    assert resumed.cost_total == 0.4
    assert resumed.cost_bound_exceeded is True


def test_dispatched_exception_consumes_reservation_and_stops_retries(
    tmp_path: Path,
):
    class TimeoutClient(EchoClient):
        def __call__(self, call: ModelCall) -> ModelResponse:
            self.calls += 1
            raise TimeoutError("provider timed out after dispatch")

    config = RunnerConfig(
        threads=1,
        max_retries=3,
        retry_backoff=0.0,
        results_dir=tmp_path,
        max_cost=10.0,
        max_cost_per_call=0.4,
        require_known_cost=True,
    )
    client = TimeoutClient()
    results, summary = run(
        _ds(3),
        model=client,
        benchmark_name="dispatched-timeout",
        config=config,
    )

    assert client.calls == 1
    assert summary.completed == 0
    assert summary.errored == 3
    assert summary.calls_total == 1
    assert summary.cost_total == 0.4
    assert summary.cost_unknown is True
    charged = [
        result
        for result in results
        if result.metadata.get("cost_reservation_consumed") is True
    ]
    assert len(charged) == 1
    assert charged[0].metadata["provider_error_type"] == "TimeoutError"
    assert all(result.metadata.get("cost_unknown") is True for result in results)

    resumed_client = TimeoutClient()
    _resumed_results, resumed = run(
        _ds(3),
        model=resumed_client,
        benchmark_name="dispatched-timeout",
        config=config,
    )
    assert resumed_client.calls == 0
    assert resumed.skipped == 3
    assert resumed.cost_total == 0.4
    assert resumed.cost_unknown is True


def test_unknown_provider_cost_fails_closed_before_more_serial_calls(tmp_path: Path):
    class UnknownCostClient(EchoClient):
        def __call__(self, call: ModelCall) -> ModelResponse:
            self.calls += 1
            return ModelResponse(text="ok", cost=0.0, cost_known=False)

    client = UnknownCostClient()
    results, summary = run(
        _ds(4),
        model=client,
        benchmark_name="unknown-cost",
        config=RunnerConfig(
            threads=1,
            max_retries=3,
            retry_backoff=0.0,
            results_dir=tmp_path,
            max_cost=10.0,
            require_known_cost=True,
        ),
    )

    assert client.calls == 1
    assert summary.completed == 0
    assert summary.errored == 4
    assert summary.cost_unknown is True
    assert sum(result.metadata.get("cost_unknown") is True for result in results) == 4


def test_model_call_ceiling_is_exact_and_resume_aware(tmp_path: Path):
    first_client = EchoClient()
    config = RunnerConfig(
        threads=2,
        max_retries=1,
        results_dir=tmp_path,
        max_calls=2,
    )
    results, summary = run(
        _ds(4),
        model=first_client,
        benchmark_name="call-budget",
        config=config,
    )

    assert first_client.calls == 2
    assert summary.calls_total == 2
    assert summary.call_budget_exhausted is True
    assert sum(
        result.metadata.get("call_budget_exhausted") is True for result in results
    ) == 2

    resumed_client = EchoClient()
    _resumed_results, resumed = run(
        _ds(4),
        model=resumed_client,
        benchmark_name="call-budget",
        config=config,
    )
    assert resumed_client.calls == 0
    assert resumed.calls_total == 2
    assert resumed.call_budget_exhausted is True
