from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from arisekit.agentic import AgentTurnOutput
from arisekit import BenchmarkItem, Dataset
from arisekit.dispatch import DispatchLedger, DispatchStopped
from arisekit.runner import RunnerConfig, run
from arisekit.sut import SystemUnderTest
from arisekit.types import Tool


def test_explicit_reserved_failure_continues_other_cases_and_keeps_uncertain_cost(tmp_path):
    from arisekit.client import ModelResponse
    class TerminalPromptBlock(RuntimeError):
        pass
    calls = []
    def model(call):
        calls.append(call.item.id)
        if call.item.id == "blocked":
            raise TerminalPromptBlock("Retained block")
        return ModelResponse(text="valid", cost=.01, cost_known=True)
    cfg = RunnerConfig(results_dir=tmp_path, max_retries=1, threads=1, max_cost=1,
        max_cost_per_call=.2, require_known_cost=True, reserved_failure_types=("TerminalPromptBlock",))
    rows, summary = run(Dataset.from_items([BenchmarkItem("blocked", "question"), BenchmarkItem("next", "question")]),
        model=model, benchmark_name="covered", config=cfg)
    assert calls == ["blocked", "next"]
    assert rows[0].error and rows[0].metadata["cost_unknown"]
    assert rows[1].response == "valid" and rows[1].error is None
    assert summary.cost_unknown and summary.cost_total == pytest.approx(.21)
    from arisekit.benchmark import Benchmark
    from arisekit.scorer import DeferredScorer
    calls.clear()
    class CoveredModel:
        model = "covered-fixture"
        def __call__(self, call):
            return model(call)
    result = Benchmark(name="covered-api", dataset=Dataset.from_items([
        BenchmarkItem("blocked", "question"), BenchmarkItem("next", "question")]),
        scorer=DeferredScorer(), runner_config=cfg).run(CoveredModel(), auto_manifest=True)
    assert calls == ["blocked", "next"] and result.summary.cost_unknown


def test_confirmed_pre_dispatch_denial_is_zero_cost_and_resumes_after_admission(tmp_path):
    from arisekit.dispatch import ProviderRequestNotSent
    from arisekit.sut import SUTResponse
    cfg = RunnerConfig(max_cost=1, max_cost_per_call=.2, max_calls=1, require_known_cost=True)
    path = tmp_path / "admission.jsonl"
    ledger = DispatchLedger(path, cfg, {})
    with pytest.raises(ProviderRequestNotSent, match="daily budget"):
        ledger.invoke(("one", 1), "request", lambda: (_ for _ in ()).throw(ProviderRequestNotSent("daily budget")), agent=False)
    assert ledger.usage()["provider_calls"] == 0 and ledger.usage()["cost"] == 0
    assert ledger.usage()["cost_known"] and not ledger.usage()["cost_unknown"]
    ledger.close()
    resumed = DispatchLedger(path, cfg, {})
    assert resumed.usage()["provider_calls"] == 0
    result = resumed.invoke(("one", 1), "request", lambda: SUTResponse("admitted", cost=.01, cost_known=True), agent=False)
    assert result.response == "admitted"
    assert resumed.usage()["provider_calls"] == 1 and resumed.usage()["cost"] == .01
    resumed.close()


def agent(counter, *, cost=0.2):
    def call(messages, tools):
        counter.append(len(messages))
        if not any(m["role"] == "tool" for m in messages):
            return AgentTurnOutput(
                tool_calls=[{"id": "read", "name": "read", "arguments": {}}], cost=cost
            )
        return AgentTurnOutput(text="done", cost=cost)

    return SystemUnderTest.from_agent(
        call,
        [Tool("read", "read", {"type": "object", "properties": {}}, lambda: "ok")],
        name="agent",
    )


def test_agent_call_ceiling_stops_between_turns_and_resumes(tmp_path):
    calls = []
    cfg = RunnerConfig(results_dir=tmp_path, max_retries=1, max_calls=1)
    ds = Dataset.from_items([BenchmarkItem("one", "question")])
    rows, summary = run(ds, model=agent(calls), benchmark_name="t", config=cfg)
    assert len(calls) == 1 and summary.calls_total == 1
    assert rows[0].metadata["stop_reason"] == "call_budget_exhausted"
    assert len(rows[0].response.turns) == 2
    rows, summary = run(
        ds, model=agent(calls), benchmark_name="t", config=replace(cfg, max_calls=2)
    )
    assert len(calls) == 2 and summary.completed == 1
    assert summary.cost_total == pytest.approx(0.4)


def test_agent_parallel_reservations_bound_all_trajectories(tmp_path):
    calls = []
    cfg = RunnerConfig(
        results_dir=tmp_path,
        max_retries=1,
        threads=4,
        max_cost=0.6,
        max_cost_per_call=0.2,
    )
    rows, summary = run(
        Dataset.from_items([BenchmarkItem(str(i), "question") for i in range(4)]),
        model=agent(calls),
        benchmark_name="t",
        config=cfg,
    )
    assert len(calls) == 3 and summary.calls_total == 3
    assert summary.cost_total == pytest.approx(0.6)
    assert summary.budget_exhausted


def test_returned_response_replayed_after_missing_turn_checkpoint(tmp_path):
    cfg = RunnerConfig(
        results_dir=tmp_path, max_calls=1, max_cost=1, max_cost_per_call=0.2
    )
    path = tmp_path / "calls.jsonl"
    ledger = DispatchLedger(path, cfg, {})
    result = ledger.invoke(
        ("one", 1),
        "same-request",
        lambda: AgentTurnOutput(text="retained", cost=0.1),
        agent=True,
    )
    ledger.close()
    resumed = DispatchLedger(path, cfg, {})

    def never():
        raise AssertionError("must replay without a second dispatch")

    assert resumed.invoke(("one", 1), "same-request", never, agent=True) == result
    assert resumed.usage()["provider_calls"] == 1
    resumed.close()


def test_interruption_retains_reservation_and_blocks_unknown_spend(tmp_path):
    cfg = RunnerConfig(
        results_dir=tmp_path, max_cost=1, max_cost_per_call=0.3, max_calls=3
    )
    path = tmp_path / "calls.jsonl"
    ledger = DispatchLedger(path, cfg, {})

    def interrupt():
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        ledger.invoke(("one", 1), "request", interrupt, agent=True)
    ledger.close()
    resumed = DispatchLedger(path, cfg, {})
    assert resumed.usage()["cost"] == 0.3
    assert resumed.usage()["provider_calls"] == 1
    with pytest.raises(DispatchStopped, match="unknown"):
        resumed.invoke(("two", 1), "another", lambda: None, agent=True)
    resumed.close()


def test_journal_lock_and_corruption_fail_before_dispatch(tmp_path):
    path = tmp_path / "calls.jsonl"
    cfg = RunnerConfig()
    ledger = DispatchLedger(path, cfg, {})
    with pytest.raises(BlockingIOError):
        DispatchLedger(path, cfg, {})
    ledger.close()
    with path.open("a") as f:
        f.write("{truncated")
    with pytest.raises(ValueError):
        DispatchLedger(path, cfg, {})


def test_reserved_recovery_does_not_waive_unknown_success_or_other_errors(tmp_path):
    from arisekit.sut import SUTResponse
    cfg = RunnerConfig(max_cost=2, max_cost_per_call=.5, require_known_cost=True)
    for name, failure in [('unknown-output', lambda: SUTResponse('answer', cost_known=False)),
                          ('other-error', lambda: (_ for _ in ()).throw(ValueError('failure')))]:
        ledger = DispatchLedger(tmp_path / (name + '.jsonl'), cfg, {},
                                reserved_failure_types=frozenset({'TimeoutError'}))
        with pytest.raises(DispatchStopped, match='unknown'):
            ledger.invoke(('first', 1), 'one', failure, agent=False)
        with pytest.raises(DispatchStopped, match='unknown'):
            ledger.invoke(('second', 1), 'two', lambda: SUTResponse('not dispatched'), agent=False)
        assert ledger.usage()['provider_calls'] == 1
        ledger.close()


def test_agent_spending_limit_requires_a_reservation_before_dispatch(tmp_path):
    calls = []
    with pytest.raises(ValueError, match="reservation bound"):
        run(
            Dataset.from_items([BenchmarkItem("a", "q")]),
            model=agent(calls),
            benchmark_name="t",
            config=RunnerConfig(results_dir=tmp_path, max_cost=1),
        )
    assert not calls


def test_agent_replays_paid_output_if_checkpoint_write_was_interrupted(tmp_path):
    from arisekit.sut import AgentSUT

    calls = []
    original = agent(calls)

    class InterruptedCheckpoint(AgentSUT):
        def respond_checkpointed(self, item, **kwargs):
            def interrupt(checkpoint):
                raise KeyboardInterrupt()

            kwargs["on_checkpoint"] = interrupt
            return super().respond_checkpointed(item, **kwargs)

    first = InterruptedCheckpoint(original.agent_client, original.tools, name="agent")
    cfg = RunnerConfig(
        results_dir=tmp_path, max_cost=1, max_cost_per_call=0.2, max_calls=2
    )
    ds = Dataset.from_items([BenchmarkItem("a", "q")])
    with pytest.raises(KeyboardInterrupt):
        run(ds, model=first, benchmark_name="t", config=cfg)
    assert len(calls) == 1
    rows, summary = run(ds, model=original, benchmark_name="t", config=cfg)
    assert len(calls) == 2 and summary.calls_total == 2
    assert summary.completed == 1 and summary.cost_total == pytest.approx(0.4)
