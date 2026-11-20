"""The runner drives a SUT (text or agentic) with resume and cost intact."""

from __future__ import annotations

from pathlib import Path

from arisekit.agentic import AgentTurnOutput
from arisekit.client import ModelCall, ModelResponse
from arisekit.dataset import Dataset
from arisekit.runner import RunnerConfig, run as run_dataset
from arisekit.sut import SystemUnderTest
from arisekit.types import Trajectory


class FakeTextClient:
    def __init__(self):
        self.model = "fake"
        self.calls = 0

    def __call__(self, call: ModelCall) -> ModelResponse:
        self.calls += 1
        return ModelResponse(text=f"ans:{call.item.id}", tokens_in=2, tokens_out=3, cost=0.005, finish_reason="stop")


class AnswerNowAgent:
    """A fake AgentClient that answers immediately (no tool call)."""

    def __call__(self, messages, tools):
        content = messages[-1]["content"]
        text = content if isinstance(content, str) else ""
        return AgentTurnOutput(text=f"done-{text}", tool_calls=[], tokens_in=1, tokens_out=1, cost=0.002)


def _ds() -> Dataset:
    return Dataset.from_items([{"id": "a", "prompt": "qa"}, {"id": "b", "prompt": "qb"}], name="t")


def test_runner_drives_text_model_client_with_resume(tmp_path: Path):
    cfg = RunnerConfig(results_dir=tmp_path)
    client = FakeTextClient()

    results, summary = run_dataset(_ds(), model=client, benchmark_name="t", config=cfg)
    assert summary.completed == 2 and summary.errored == 0
    by_id = {r.id: r for r in results}
    assert by_id["a"].response == "ans:a"
    assert abs(summary.cost_total - 0.01) < 1e-9  # 2 items * 0.005

    # Resume: a second run reuses the checkpoint and calls the client zero more times.
    calls_before = client.calls
    _, summary2 = run_dataset(_ds(), model=client, benchmark_name="t", config=cfg)
    assert summary2.skipped == 2
    assert client.calls == calls_before


def test_runner_drives_agentic_sut(tmp_path: Path):
    cfg = RunnerConfig(results_dir=tmp_path)
    sut = SystemUnderTest.from_agent(AnswerNowAgent(), [], name="agent-run")

    results, summary = run_dataset(_ds(), model=sut, benchmark_name="agentic", config=cfg)
    assert summary.completed == 2
    by_id = {r.id: r for r in results}
    resp = by_id["a"].response
    assert isinstance(resp, Trajectory)
    assert resp.final_response == "done-qa"
    # Agentic usage is tracked through the same cost machinery.
    assert abs(summary.cost_total - 0.004) < 1e-9  # 2 items * 0.002


def test_runner_output_path_uses_sut_name(tmp_path: Path):
    cfg = RunnerConfig(results_dir=tmp_path)
    sut = SystemUnderTest.from_agent(AnswerNowAgent(), [], name="my-agent")
    _, summary = run_dataset(_ds(), model=sut, benchmark_name="agentic", config=cfg)
    assert summary.output_path.name == "my-agent.jsonl"


def test_runner_threads_gt_one_persists_all_rows(tmp_path: Path):
    # Concurrency: many items over 4 threads must all persist exactly once,
    # uncorrupted, under the shared write lock.
    cfg = RunnerConfig(results_dir=tmp_path, threads=4)
    client = FakeTextClient()
    ds = Dataset.from_items([{"id": f"i{k}", "prompt": f"q{k}"} for k in range(12)], name="t")

    results, summary = run_dataset(ds, model=client, benchmark_name="par", config=cfg)
    assert summary.completed == 12 and summary.errored == 0
    assert sorted(r.id for r in results) == sorted(f"i{k}" for k in range(12))

    # Resume finds all 12 and re-calls the client zero more times.
    calls_before = client.calls
    _, summary2 = run_dataset(ds, model=client, benchmark_name="par", config=cfg)
    assert summary2.skipped == 12
    assert client.calls == calls_before


class RecoveringClient:
    """Raises while mode='fail', then succeeds once mode is flipped to 'ok'."""

    def __init__(self):
        self.model = "recovering"
        self.mode = "fail"
        self.calls = 0

    def __call__(self, call: ModelCall) -> ModelResponse:
        self.calls += 1
        if self.mode == "fail":
            raise RuntimeError("boom")
        return ModelResponse(text=f"ans:{call.item.id}", tokens_in=1, tokens_out=1,
                             cost=0.001, finish_reason="stop")


def test_runner_resume_after_error_retries_then_skips(tmp_path: Path):
    cfg = RunnerConfig(results_dir=tmp_path, threads=1, max_retries=1)
    ds = Dataset.from_items([{"id": "a", "prompt": "qa"}], name="t")
    client = RecoveringClient()

    # First run: the item errors out and is checkpointed as errored.
    _, s1 = run_dataset(ds, model=client, benchmark_name="err", config=cfg)
    assert s1.errored == 1 and s1.completed == 0
    calls_after_fail = client.calls  # 1

    # Second run: an errored row is NOT treated as done, so it is retried,
    # and now succeeds.
    client.mode = "ok"
    results2, s2 = run_dataset(ds, model=client, benchmark_name="err", config=cfg)
    assert s2.skipped == 0
    assert s2.completed == 1
    assert client.calls == calls_after_fail + 1
    assert {r.id: r for r in results2}["a"].response == "ans:a"

    # Third run: the now-successful row IS skipped.
    _, s3 = run_dataset(ds, model=client, benchmark_name="err", config=cfg)
    assert s3.skipped == 1
    assert client.calls == calls_after_fail + 1
