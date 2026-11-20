"""Gated LIVE smoke: exercises the two things offline fakes cannot.

These tests make REAL API calls, so they are skipped unless
``ARISEKIT_LIVE=1`` is set. Provider credentials must be configured. They never run in
CI or a normal ``pytest`` invocation.

    ARISEKIT_LIVE=1 python -m pytest tests/test_live_smoke.py -v -s

What they validate that the offline suite cannot:
  1. The litellm tool-calling round-trip: real tool schemas out, a real
     tool_call back, arguments parsed, tool_result fed back in, an answer
     grounded in the retrieved data. (test_live_tool_calling_round_trip)
  2. A real judge returning parseable JSON that the scorers can read.
     (test_live_trajectory_judge, test_live_grounding_scorer)

Everything here is benign clinical-data lookup; no adversarial prompts
are sent to a live model.
"""

from __future__ import annotations

import os
from unittest.mock import Mock

import pytest

from live_smoke_config import client_options, live_enabled
from arisekit import Benchmark, Dataset
from arisekit.agentic import AGENTIC_PASS_CONDITION_SCHEMA_VERSION, PassAtOneScorer
from arisekit.runtime.agent_clients import LiteLLMAgentClient
from arisekit.client import LiteLLMClient
from arisekit.env.fhir import FHIREnvironment, fhir_tools
from arisekit.evaluation.grounding import GroundingScorer
from arisekit.judges.trajectory import TrajectoryJudge
from arisekit.sut import SystemUnderTest
from arisekit.runner import RunnerConfig
from arisekit.types import BenchmarkItem, RunResult, Trajectory, Turn

_LIVE = live_enabled(os.environ)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _LIVE,
        reason="live smoke: set ARISEKIT_LIVE=1 explicitly",
    ),
]

SUT_MODEL = os.environ.get("ARISEKIT_LIVE_MODEL", "gpt-4o-mini")
JUDGE_MODEL = os.environ.get("ARISEKIT_LIVE_JUDGE", "gpt-4o-mini")


@pytest.fixture(autouse=True)
def live_calls(monkeypatch, record_property):
    import litellm

    for route in {SUT_MODEL, JUDGE_MODEL}:
        client_options(route, os.environ)
    calls = []
    completion = litellm.completion

    def bounded_completion(**kwargs):
        if len(calls) >= 4:
            raise RuntimeError("live smoke exceeded four provider calls in one test")
        calls.append(kwargs["model"])
        return completion(**kwargs)

    monkeypatch.setattr(litellm, "completion", bounded_completion)
    yield calls
    record_property("provider_calls", len(calls))
    record_property("model_routes", ",".join(sorted(set(calls))))


def _env() -> FHIREnvironment:
    return FHIREnvironment(
        [
            {
                "resourceType": "Bundle",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Patient",
                            "id": "p1",
                            "name": [{"family": "Hernandez", "given": ["Maria"]}],
                        }
                    },
                    {
                        "resource": {
                            "resourceType": "Observation",
                            "id": "o1",
                            "status": "final",
                            "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "HbA1c"}]},
                            "subject": {"reference": "Patient/p1"},
                            "valueQuantity": {"value": 9.2, "unit": "%"},
                            "effectiveDateTime": "2026-04-10",
                        }
                    },
                ],
            }
        ]
    )


def _benign_trajectory() -> Trajectory:
    """A grounded, benign trajectory: the answer traces to a tool result."""
    return Trajectory(
        turns=[
            Turn(role="tool_call", content={"name": "get_patient"}),
            Turn(
                role="tool_result",
                content={"name": "get_patient", "result": {"name": [{"family": "Hernandez", "given": ["Maria"]}]}},
            ),
            Turn(role="assistant", content="The patient's family name is Hernandez."),
        ],
        final_response="The patient's family name is Hernandez.",
    )


def test_live_tool_calling_round_trip(tmp_path, monkeypatch):
    tools = [tool for tool in fhir_tools(_env()) if tool.name == "get_patient"]
    agent_client = LiteLLMAgentClient(SUT_MODEL, **client_options(SUT_MODEL, os.environ))
    sut = SystemUnderTest.from_agent(
        agent_client,
        tools,
        system_prompt=(
            "You are a clinical data assistant. Use the provided tools to look up "
            "patient data before answering. Answer in one short sentence."
        ),
        name=SUT_MODEL,
        max_iters=3,
    )
    item = BenchmarkItem(
        id="live-1",
        prompt="What is the family (last) name of the patient whose id is p1? Use the tools to look it up.",
        ground_truth={
            "schema_version": AGENTIC_PASS_CONDITION_SCHEMA_VERSION,
            "required_tool_calls": [{"name": "get_patient", "arguments": {"patient_id": "p1"}}],
            "final_response_contains": ["Hernandez"],
        },
    )

    benchmark = Benchmark(
        name="live-fhir-round-trip", dataset=Dataset([item]),
        scorer=PassAtOneScorer(condition_schema=AGENTIC_PASS_CONDITION_SCHEMA_VERSION),
        runner_config=RunnerConfig(max_retries=1, max_calls=3),
    )
    result = benchmark.run(sut, results_dir=tmp_path, auto_manifest=True)
    assert result.summary.errored == 0
    assert result.metrics[0].value == 1.0
    traj = result.raw[0].response
    assert isinstance(traj, Trajectory)

    tool_results = [t for t in traj.turns if t.role == "tool_result"]
    assert tool_results, "the live model did not call any tool"
    assert "hernandez" in str(traj.final_response).lower()

    checkpoint = result.summary.output_path.read_bytes()
    no_inference = Mock(side_effect=AssertionError("completed run dispatched again"))
    with monkeypatch.context() as resumed_patch:
        resumed_patch.setattr("litellm.completion", no_inference)
        resumed = benchmark.run(sut, results_dir=tmp_path, auto_manifest=True)
    no_inference.assert_not_called()
    assert resumed.summary.skipped == 1
    assert resumed.metrics[0].value == 1.0
    assert resumed.summary.output_path.read_bytes() == checkpoint

    print(
        f"\n[SUT] model={SUT_MODEL} "
        f"tools_called={[t.content.get('name') for t in tool_results]} "
        f"tokens={traj.total_tokens} cost=${traj.total_cost:.5f}"
    )
    print(f"[SUT] answer: {traj.final_response}")


def test_live_trajectory_judge():
    scorer = TrajectoryJudge(
        judge_model=JUDGE_MODEL,
        client=LiteLLMClient(JUDGE_MODEL, **client_options(JUDGE_MODEL, os.environ)),
        temperature=None,
        criteria=[
            {"name": "factuality", "weight": 3, "scale": "1-5",
             "guidance": "The stated family name matches the retrieved record."},
            {"name": "grounded", "weight": 2, "scale": "pass-fail",
             "guidance": "Every claim traces to a tool result in the trajectory."},
        ],
    )
    item = BenchmarkItem(id="live-2", prompt="What is the patient's family name?", ground_truth="Hernandez")

    metrics = scorer.score_item(item, [RunResult(id="live-2", trial=1, response=_benign_trajectory())])
    by = {m.name: m.value for m in metrics}

    assert "overall" in by
    assert all(m.n == 1 for m in metrics)
    assert all(0.0 <= v <= 1.0 for v in by.values())
    assert by["overall"] > 0.0, "real judge returned all-zero; likely a JSON parse failure"
    print(f"\n[JUDGE:trajectory] model={JUDGE_MODEL} scores={ {k: round(v, 3) for k, v in by.items()} }")


def test_live_grounding_scorer():
    scorer = GroundingScorer(
        judge_model=JUDGE_MODEL,
        client=LiteLLMClient(JUDGE_MODEL, **client_options(JUDGE_MODEL, os.environ)),
        temperature=None,
    )
    item = BenchmarkItem(id="live-3", prompt="What is the patient's family name?")

    metrics = scorer.score_item(item, [RunResult(id="live-3", trial=1, response=_benign_trajectory())])
    by = {m.name: m.value for m in metrics}

    assert "grounding" in by
    assert all(m.n == 1 for m in metrics)
    assert 0.0 <= by["grounding"] <= 1.0
    assert by["grounding"] > 0.0, "a grounded answer scored 0; likely a JSON parse failure"
    print(f"\n[JUDGE:grounding] model={JUDGE_MODEL} grounding={round(by['grounding'], 3)}")
