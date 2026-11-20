"""Offline tests for the System Under Test abstraction."""

from __future__ import annotations

import pytest

from arisekit.agentic import (
    AGENTIC_PASS_CONDITION_SCHEMA_VERSION,
    AgentTurnOutput,
)
from arisekit.client import REFERENCE_STUB_MODEL, ModelCall, ModelResponse
from arisekit.sut import (
    AgentSUT,
    FHIRAgentSUT,
    ModelSUT,
    SUTResponse,
    SystemUnderTest,
)
from arisekit.types import BenchmarkItem, Tool, Trajectory


class FakeModelClient:
    """A ModelClient returning a fixed ModelResponse (offline)."""

    def __init__(self, text: str = "hi"):
        self.text = text
        self.model = "fake-model"
        self.calls = 0

    def __call__(self, call: ModelCall) -> ModelResponse:
        self.calls += 1
        return ModelResponse(
            text=self.text,
            tokens_in=3,
            tokens_out=4,
            cost=0.01,
            finish_reason="stop",
            provider_model="fake-model-snapshot",
            response_id="fake-response-id",
        )


class ScriptedAgent:
    """A fake AgentClient: call a tool on turn 1, answer on turn 2."""

    def __init__(self):
        self.turn = 0

    def __call__(self, messages, tools):
        self.turn += 1
        if self.turn == 1:
            return AgentTurnOutput(
                text=None,
                tool_calls=[{"id": "c1", "name": "echo", "arguments": {"v": "9.2"}}],
                tokens_in=5, tokens_out=2, cost=0.02,
            )
        return AgentTurnOutput(text="value is 9.2", tool_calls=[], tokens_in=1, tokens_out=1, cost=0.01)


def _echo_tool() -> Tool:
    return Tool(name="echo", description="echo v",
                parameters={"type": "object", "properties": {"v": {"type": "string"}}},
                fn=lambda v: {"echoed": v})


# --- ModelSUT / resolve ----------------------------------------------


def test_model_sut_respond_returns_text_payload():
    sut = ModelSUT(FakeModelClient("answer"), name="m1")
    r = sut.respond(BenchmarkItem(id="i", prompt="q"))
    assert isinstance(r, SUTResponse)
    assert r.response == "answer"
    assert r.tokens_in == 3 and r.tokens_out == 4 and r.cost == 0.01
    assert r.provider_model == "fake-model-snapshot"
    assert r.response_id == "fake-response-id"


def test_resolve_wraps_string_as_model_sut():
    sut = SystemUnderTest.resolve("gpt-4o-mini")
    assert isinstance(sut, ModelSUT)
    assert sut.name == "gpt-4o-mini"


def test_resolve_passes_through_existing_sut():
    inner = ModelSUT(FakeModelClient(), name="x")
    assert SystemUnderTest.resolve(inner) is inner


def test_from_model_uses_client_model_name():
    sut = SystemUnderTest.from_model(FakeModelClient())
    assert isinstance(sut, ModelSUT) and sut.name == "fake-model"


def test_from_endpoint_builds_model_sut_without_network():
    sut = SystemUnderTest.from_endpoint("http://localhost:1234/v1", "local-model", name="local")
    assert isinstance(sut, ModelSUT) and sut.name == "local"


# --- AgentSUT --------------------------------------------------------


def test_agent_sut_returns_trajectory_with_accumulated_usage():
    sut = SystemUnderTest.from_agent(
        ScriptedAgent(), [_echo_tool()], system_prompt="be terse", name="agent-x"
    )
    assert isinstance(sut, AgentSUT) and sut.name == "agent-x"
    r = sut.respond(BenchmarkItem(id="i", prompt="what is v?"))
    assert isinstance(r.response, Trajectory)
    assert r.response.final_response == "value is 9.2"
    # Usage accumulates over both turns, split correctly: in=5+1, out=2+1.
    assert abs(r.cost - 0.03) < 1e-9
    assert r.tokens_in == 6
    assert r.tokens_out == 3
    assert r.response.total_tokens == 9
    # The tool actually ran against the environment closure.
    tool_results = [t for t in r.response.turns if t.role == "tool_result"]
    assert tool_results[0].content["result"] == {"echoed": "9.2"}


def test_string_agent_propagates_inference_config_to_client():
    sut = SystemUnderTest.from_agent(
        "provider/model",
        [],
        temperature=0.2,
        max_tokens=456,
    )

    assert isinstance(sut, AgentSUT)
    assert sut.agent_client.model == "provider/model"
    assert sut.agent_client.temperature == 0.2
    assert sut.agent_client.max_tokens == 456


def _fhir_bundle(item_id: str = "case-1") -> dict:
    return {
        "resourceType": "Bundle",
        "id": item_id,
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "p1",
                    "name": [{"family": "Hernandez"}],
                }
            }
        ],
    }


def _agentic_item(item_id: str = "case-1") -> BenchmarkItem:
    return BenchmarkItem(
        id=item_id,
        prompt="Look up the patient.",
        ground_truth={
            "schema_version": AGENTIC_PASS_CONDITION_SCHEMA_VERSION,
            "required_tool_calls": [
                {"name": "get_patient", "arguments": {"patient_id": "p1"}}
            ],
            "final_response_contains": ["Hernandez"],
        },
    )


def test_fhir_reference_stub_executes_real_bound_tool_without_provider_call(
    monkeypatch,
):
    def forbidden(*args, **kwargs):
        raise AssertionError("reference stub must not call LiteLLM")

    monkeypatch.setattr(
        "arisekit.runtime.agent_clients.LiteLLMAgentClient.__call__",
        forbidden,
    )
    sut = FHIRAgentSUT(
        REFERENCE_STUB_MODEL,
        {"case-1": _fhir_bundle()},
        allowed_tools=["get_patient"],
        max_iters=3,
    )

    response = sut.respond(_agentic_item())

    assert isinstance(response.response, Trajectory)
    tool_results = [
        turn for turn in response.response.turns if turn.role == "tool_result"
    ]
    assert tool_results[0].content["result"]["name"][0]["family"] == "Hernandez"
    assert response.response.final_response == "Hernandez"
    assert response.cost == 0.0


def test_fhir_agent_uses_a_fresh_environment_for_each_invocation():
    class CreateAndCount:
        def __call__(self, messages, tools):
            tool_messages = [message for message in messages if message["role"] == "tool"]
            if not tool_messages:
                return AgentTurnOutput(
                    tool_calls=[
                        {
                            "id": "create",
                            "name": "create_task",
                            "arguments": {
                                "for_patient_id": "p1",
                                "description": "Follow up",
                            },
                        }
                    ]
                )
            if len(tool_messages) == 1:
                return AgentTurnOutput(
                    tool_calls=[
                        {
                            "id": "search",
                            "name": "search_tasks",
                            "arguments": {"patient_id": "p1"},
                        }
                    ]
                )
            return AgentTurnOutput(text="done")

    item = _agentic_item()
    sut = FHIRAgentSUT(
        CreateAndCount(),
        {item.id: _fhir_bundle()},
        allowed_tools=["create_task", "search_tasks"],
        max_iters=3,
    )

    first = sut.respond(item).response
    second = sut.respond(item).response

    for trajectory in (first, second):
        searches = [
            turn.content["result"]
            for turn in trajectory.turns
            if turn.role == "tool_result" and turn.content["name"] == "search_tasks"
        ]
        assert len(searches) == 1
        assert len(searches[0]) == 1


def test_fhir_agent_resumes_between_writes_without_reusing_resource_ids():
    class TwoWritesThenRead:
        def __init__(self):
            self.calls = 0

        def __call__(self, messages, tools):
            self.calls += 1
            completed = [message for message in messages if message["role"] == "tool"]
            if not completed:
                return AgentTurnOutput(tool_calls=[
                    {"id": f"write-{index}", "name": "create_task", "arguments": {
                        "for_patient_id": "p1", "description": description,
                    }} for index, description in enumerate(("First", "Second"))
                ])
            if len(completed) == 2:
                return AgentTurnOutput(tool_calls=[{
                    "id": "read", "name": "search_tasks", "arguments": {"patient_id": "p1"},
                }])
            return AgentTurnOutput(text="done")

    class Interrupted(Exception):
        pass

    item = _agentic_item()
    checkpoints = []

    def interrupt_after_first_write(checkpoint):
        writes = [turn for turn in checkpoint.response.turns if turn.role == "tool_result"]
        if len(writes) == 1:
            checkpoints.append(checkpoint)
            raise Interrupted

    client = TwoWritesThenRead()
    sut = FHIRAgentSUT(client, {item.id: _fhir_bundle()},
                       allowed_tools=["create_task", "search_tasks"], max_iters=3)
    with pytest.raises(Interrupted):
        sut.respond_checkpointed(item, trial=1, on_checkpoint=interrupt_after_first_write)
    assert client.calls == 1
    restored = sut.respond_checkpointed(item, trial=1, resume_from=checkpoints[0]).response
    assert client.calls == 3
    uninterrupted = FHIRAgentSUT(
        TwoWritesThenRead(), {item.id: _fhir_bundle()},
        allowed_tools=["create_task", "search_tasks"], max_iters=3,
    ).respond(item).response

    for trajectory in (restored, uninterrupted):
        writes = [turn.content["result"] for turn in trajectory.turns
                  if turn.role == "tool_result" and turn.content["name"] == "create_task"]
        assert [(task["id"], task["description"]) for task in writes] == [
            ("task-1", "First"), ("task-2", "Second"),
        ]
        search = next(turn.content["result"] for turn in trajectory.turns
                      if turn.role == "tool_result" and turn.content["name"] == "search_tasks")
        assert [(task["id"], task["description"]) for task in search] == [
            ("task-1", "First"), ("task-2", "Second"),
        ]
    recorded_first = next(turn.content["result"] for turn in checkpoints[0].response.turns
                          if turn.role == "tool_result")
    resumed_first = next(turn.content["result"] for turn in restored.turns if turn.role == "tool_result")
    assert resumed_first == recorded_first
