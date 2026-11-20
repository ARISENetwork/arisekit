"""Per-turn agent journals resume without contaminating final checkpoints."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from arisekit.agentic import AgentTurnOutput
from arisekit.dataset import Dataset
from arisekit.run_manifest import RunManifest
from arisekit.runner import (
    RunnerConfig,
    load_turn_checkpoints,
    run as run_dataset,
    turn_path,
)
from arisekit.sut import SystemUnderTest
from arisekit.types import RunResult, Tool, Trajectory, Turn


class ContinueFromMessages:
    """Call one read tool, then answer; optionally fail after retrieval."""

    def __init__(self, *, fail_after_tool: bool = False, final_cost: float = 0.2):
        self.fail_after_tool = fail_after_tool
        self.final_cost = final_cost
        self.calls = 0

    def __call__(self, messages, tools):
        self.calls += 1
        has_tool_result = any(message.get("role") == "tool" for message in messages)
        if not has_tool_result:
            return AgentTurnOutput(
                tool_calls=[
                    {
                        "id": "read-1",
                        "name": "read_chart",
                        "arguments": {"patient_id": "p1"},
                    }
                ],
                tokens_in=3,
                tokens_out=2,
                cost=0.1,
            )
        if self.fail_after_tool:
            raise RuntimeError("interrupted after retrieval")
        return AgentTurnOutput(
            text="The chart says stable.",
            tokens_in=4,
            tokens_out=3,
            cost=self.final_cost,
        )


class NeverCallClient:
    def __init__(self):
        self.calls = 0

    def __call__(self, messages, tools):
        self.calls += 1
        raise AssertionError("terminal checkpoint should not call the model")


def _dataset() -> Dataset:
    return Dataset.from_items([{"id": "case-1", "prompt": "Review patient p1."}])


def _read_tool(counter: dict[str, int]) -> Tool:
    def read_chart(patient_id: str):
        counter["calls"] += 1
        return {"patient_id": patient_id, "status": "stable"}

    return Tool(
        name="read_chart",
        description="Read a fixed chart.",
        parameters={
            "type": "object",
            "properties": {"patient_id": {"type": "string"}},
            "required": ["patient_id"],
        },
        fn=read_chart,
    )


def _manifest(*, model: str, trials: int = 1, label: str = "a") -> RunManifest:
    digest = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
    return RunManifest(
        benchmark_arm="general-medicine",
        benchmark_content_hash=digest(f"content-{label}"),
        prompt_hash=digest("prompt"),
        code_hash=digest("code"),
        model=model,
        provider="test",
        trials=trials,
        selection={},
        source_revision="test",
    )


def test_interrupted_agent_resumes_without_repeating_tool_or_usage(tmp_path: Path):
    counter = {"calls": 0}
    config = RunnerConfig(results_dir=tmp_path, max_retries=1)
    first_client = ContinueFromMessages(fail_after_tool=True)
    first_sut = SystemUnderTest.from_agent(
        first_client,
        [_read_tool(counter)],
        name="resume-agent",
    )

    first_results, first_summary = run_dataset(
        _dataset(),
        model=first_sut,
        benchmark_name="general-medicine",
        config=config,
    )

    assert first_summary.errored == 1
    assert first_summary.cost_total == pytest.approx(0.1)
    assert first_summary.calls_total == 2
    assert first_results[0].metadata["provider_calls"] == 2
    assert counter["calls"] == 1

    resumed_client = ContinueFromMessages()
    resumed_sut = SystemUnderTest.from_agent(
        resumed_client,
        [_read_tool(counter)],
        name="resume-agent",
    )
    results, summary = run_dataset(
        _dataset(),
        model=resumed_sut,
        benchmark_name="general-medicine",
        config=config,
    )

    assert summary.completed == 1
    assert summary.errored == 0
    assert summary.cost_total == pytest.approx(0.3)
    assert summary.calls_total == 3
    assert resumed_client.calls == 1
    assert counter["calls"] == 1
    trajectory = results[0].response
    assert isinstance(trajectory, Trajectory)
    assert trajectory.total_tokens_in == 7
    assert trajectory.total_tokens_out == 5
    assert trajectory.total_cost == pytest.approx(0.3)

    final_lines = [
        json.loads(line)
        for line in summary.output_path.read_text(encoding="utf-8").splitlines()
    ]
    assert all(
        row["metadata"].get("checkpoint_kind") is None for row in final_lines
    )
    journal = summary.output_path.with_suffix(".turns.jsonl")
    assert journal.is_file()
    assert all(
        json.loads(line)["metadata"]["checkpoint_kind"] == "trajectory"
        for line in journal.read_text(encoding="utf-8").splitlines()
    )


def test_terminal_turn_checkpoint_is_promoted_without_model_call(tmp_path: Path):
    config = RunnerConfig(results_dir=tmp_path)
    path = turn_path(config, "general-medicine", "terminal-agent")
    path.parent.mkdir(parents=True)
    trajectory = Trajectory(
        turns=[Turn(role="assistant", content="Already complete.")],
        final_response="Already complete.",
        total_tokens=5,
        total_tokens_in=3,
        total_tokens_out=2,
        total_cost=0.05,
    )
    checkpoint = RunResult(
        id="case-1",
        trial=1,
        response=trajectory,
        metadata={
            "checkpoint_kind": "trajectory",
            "checkpoint_sequence": 1,
            "checkpoint_complete": True,
            "tokens_in": 3,
            "tokens_out": 2,
            "cost": 0.05,
            "provider_calls": 1,
        },
    )
    path.write_text(
        json.dumps(checkpoint.to_dict(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    client = NeverCallClient()
    sut = SystemUnderTest.from_agent(client, [], name="terminal-agent")

    results, summary = run_dataset(
        _dataset(),
        model=sut,
        benchmark_name="general-medicine",
        config=config,
    )

    assert client.calls == 0
    assert summary.completed == 1
    assert summary.cost_total == pytest.approx(0.05)
    assert summary.calls_total == 1
    assert results[0].response.final_response == "Already complete."
    assert len(summary.output_path.read_text(encoding="utf-8").splitlines()) == 1


def test_turn_checkpoints_are_isolated_by_trial(tmp_path: Path):
    counter = {"calls": 0}
    config = RunnerConfig(results_dir=tmp_path, trials=2)
    path = turn_path(config, "general-medicine", "trial-agent")
    path.parent.mkdir(parents=True)
    partial = Trajectory(
        turns=[
            Turn(
                role="assistant",
                content={
                    "text": None,
                    "tool_calls": [
                        {
                            "id": "read-1",
                            "name": "read_chart",
                            "arguments": {"patient_id": "p1"},
                        }
                    ],
                },
            ),
            Turn(
                role="tool_result",
                content={
                    "id": "read-1",
                    "name": "read_chart",
                    "result": {"patient_id": "p1", "status": "stable"},
                },
            ),
        ],
        total_tokens=5,
        total_tokens_in=3,
        total_tokens_out=2,
        total_cost=0.1,
    )
    checkpoint = RunResult(
        id="case-1",
        trial=1,
        response=partial,
        metadata={
            "checkpoint_kind": "trajectory",
            "checkpoint_sequence": 1,
            "checkpoint_complete": False,
            "tokens_in": 3,
            "tokens_out": 2,
            "cost": 0.1,
            "provider_calls": 1,
        },
    )
    path.write_text(json.dumps(checkpoint.to_dict()) + "\n", encoding="utf-8")
    client = ContinueFromMessages()
    sut = SystemUnderTest.from_agent(
        client,
        [_read_tool(counter)],
        name="trial-agent",
    )

    results, summary = run_dataset(
        _dataset(),
        model=sut,
        benchmark_name="general-medicine",
        config=config,
    )

    assert summary.completed == 2
    assert {(result.id, result.trial) for result in results} == {
        ("case-1", 1),
        ("case-1", 2),
    }
    assert counter["calls"] == 1
    checkpoints = load_turn_checkpoints(path)
    assert set(checkpoints) == {("case-1", 1), ("case-1", 2)}
    assert checkpoints[("case-1", 1)].provider_calls == 2
    assert checkpoints[("case-1", 2)].provider_calls == 2


def test_manifest_digest_namespaces_and_validates_turn_journal(tmp_path: Path):
    counter = {"calls": 0}
    config = RunnerConfig(results_dir=tmp_path, max_retries=1)
    client = ContinueFromMessages(fail_after_tool=True)
    sut = SystemUnderTest.from_agent(
        client,
        [_read_tool(counter)],
        name="manifest-agent",
    )
    manifest_a = _manifest(model="manifest-agent", label="a")

    _results, summary = run_dataset(
        _dataset(),
        model=sut,
        benchmark_name="general-medicine",
        config=config,
        manifest=manifest_a,
    )

    journal_a = summary.output_path.with_suffix(".turns.jsonl")
    assert manifest_a.digest in journal_a.parts
    assert load_turn_checkpoints(
        journal_a,
        manifest_digest=manifest_a.digest,
    )
    with pytest.raises(ValueError, match="manifest digest"):
        load_turn_checkpoints(journal_a, manifest_digest="f" * 64)

    manifest_b = _manifest(model="manifest-agent", label="b")
    journal_b = turn_path(
        config,
        "general-medicine",
        "manifest-agent",
        manifest_digest=manifest_b.digest,
    )
    assert journal_b != journal_a
    assert load_turn_checkpoints(journal_b, manifest_digest=manifest_b.digest) == {}
