"""Agentic executor loop plus pass@1 scoring, driven by a scripted fake."""

from arisekit import BenchmarkItem, RunResult
from arisekit.agentic import (
    AGENTIC_PASS_CONDITION_SCHEMA_VERSION,
    AgentTurnOutput,
    PassAtOneScorer,
    run_agent,
)
from arisekit.env.fhir import FHIREnvironment, fhir_tools
from arisekit.types import Trajectory, Turn


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
                    }
                ],
            }
        ]
    )


class ScriptedAgentClient:
    """Fake AgentClient: call a tool on turn 1, answer on turn 2. Offline."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return AgentTurnOutput(
                text=None,
                tool_calls=[
                    {"id": "c1", "name": "get_patient", "arguments": {"patient_id": "p1"}}
                ],
            )
        return AgentTurnOutput(text="The patient is Maria Hernandez.", tool_calls=[])


def test_run_agent_executes_tool_then_answers():
    client = ScriptedAgentClient()
    tools = fhir_tools(_env())
    item = BenchmarkItem(id="t1", prompt="Who is patient p1?")

    traj = run_agent(client, item, tools)

    assert isinstance(traj, Trajectory)
    assert traj.final_response == "The patient is Maria Hernandez."
    # There is exactly one tool_result turn, and it carries the tool output.
    tool_results = [t for t in traj.turns if t.role == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0].content["name"] == "get_patient"
    assert tool_results[0].content["result"]["name"][0]["family"] == "Hernandez"


def test_run_agent_records_error_for_unknown_tool():
    class BadToolClient:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return AgentTurnOutput(
                    text=None,
                    tool_calls=[{"id": "c1", "name": "no_such_tool", "arguments": {}}],
                )
            return AgentTurnOutput(text="done", tool_calls=[])

    traj = run_agent(BadToolClient(), BenchmarkItem(id="t", prompt="go"), fhir_tools(_env()))
    tool_results = [t for t in traj.turns if t.role == "tool_result"]
    assert "error" in tool_results[0].content["result"]
    assert traj.final_response == "done"


def test_run_agent_caps_at_max_iters():
    class LoopingClient:
        def __call__(self, messages, tools):
            return AgentTurnOutput(
                text="still working",
                tool_calls=[{"id": "c", "name": "get_patient", "arguments": {"patient_id": "p1"}}],
            )

    traj = run_agent(LoopingClient(), BenchmarkItem(id="t", prompt="go"), fhir_tools(_env()), max_iters=3)
    assistant_turns = [t for t in traj.turns if t.role == "assistant"]
    assert len(assistant_turns) == 3
    # Best-effort final response is the last turn's text.
    assert traj.final_response == "still working"


def test_pass_at_one_substring_check():
    traj = Trajectory(turns=[], final_response="The patient is Maria Hernandez.")
    result = RunResult(id="t1", trial=1, response=traj)

    passing = PassAtOneScorer()
    item_hit = BenchmarkItem(id="t1", prompt="q", ground_truth="Maria")
    metrics = passing.score_item(item_hit, [result])
    assert metrics[0].name == "pass_at_1"
    assert metrics[0].value == 1.0

    item_miss = BenchmarkItem(id="t1", prompt="q", ground_truth="Nonexistent")
    assert passing.score_item(item_miss, [result])[0].value == 0.0


def test_pass_at_one_plain_text_response_falls_back_to_substring():
    result = RunResult(id="t1", trial=1, response="Hello Maria")
    item = BenchmarkItem(id="t1", prompt="q", ground_truth=["hello", "maria"])
    assert PassAtOneScorer().score_item(item, [result])[0].value == 1.0


def test_pass_at_one_tool_call_check():
    client = ScriptedAgentClient()
    traj = run_agent(client, BenchmarkItem(id="t1", prompt="q"), fhir_tools(_env()))
    result = RunResult(id="t1", trial=1, response=traj)

    scorer = PassAtOneScorer()
    hit = BenchmarkItem(id="t1", prompt="q", ground_truth={"tool_calls": ["get_patient"]})
    assert scorer.score_item(hit, [result])[0].value == 1.0

    miss = BenchmarkItem(id="t1", prompt="q", ground_truth={"tool_calls": ["search_observations"]})
    assert scorer.score_item(miss, [result])[0].value == 0.0


def test_pass_at_one_check_works_on_trajectory_dict():
    traj = Trajectory(turns=[], final_response="answer text")
    result = RunResult(id="t1", trial=1, response=traj.to_dict())
    item = BenchmarkItem(id="t1", prompt="q", ground_truth="answer")
    assert PassAtOneScorer().score_item(item, [result])[0].value == 1.0


def _condition() -> dict:
    return {
        "schema_version": AGENTIC_PASS_CONDITION_SCHEMA_VERSION,
        "required_tool_calls": [
            {"name": "get_patient", "arguments": {"patient_id": "p1"}}
        ],
        "final_response_contains": ["Maria", "Hernandez"],
    }


def _condition_trajectory(*, arguments=None, result=None, final="Maria Hernandez"):
    return Trajectory(
        turns=[
            Turn(
                role="assistant",
                content={
                    "text": None,
                    "tool_calls": [
                        {
                            "id": "lookup-1",
                            "name": "get_patient",
                            "arguments": arguments or {"patient_id": "p1"},
                        }
                    ],
                },
            ),
            Turn(
                role="tool_result",
                content={
                    "id": "lookup-1",
                    "name": "get_patient",
                    "result": result or {"resourceType": "Patient", "id": "p1"},
                },
            ),
            Turn(role="assistant", content=final),
        ],
        final_response=final,
    )


def test_versioned_pass_condition_requires_successful_exact_call_and_all_text():
    scorer = PassAtOneScorer(
        condition_schema=AGENTIC_PASS_CONDITION_SCHEMA_VERSION
    )
    item = BenchmarkItem(id="t1", prompt="q", ground_truth=_condition())

    passing = RunResult(id="t1", trial=1, response=_condition_trajectory())
    assert scorer.score_item(item, [passing])[0].value == 1.0

    wrong_args = RunResult(
        id="t1",
        trial=1,
        response=_condition_trajectory(arguments={"patient_id": "p2"}),
    )
    assert scorer.score_item(item, [wrong_args])[0].value == 0.0

    failed_call = RunResult(
        id="t1",
        trial=1,
        response=_condition_trajectory(result={"error": "not found"}),
    )
    assert scorer.score_item(item, [failed_call])[0].value == 0.0

    missing_text = RunResult(
        id="t1",
        trial=1,
        response=_condition_trajectory(final="Maria"),
    )
    assert scorer.score_item(item, [missing_text])[0].value == 0.0


def test_versioned_pass_condition_does_not_credit_intent_without_result():
    trajectory = _condition_trajectory()
    trajectory.turns = [trajectory.turns[0], trajectory.turns[-1]]
    scorer = PassAtOneScorer(
        condition_schema=AGENTIC_PASS_CONDITION_SCHEMA_VERSION
    )
    item = BenchmarkItem(id="t1", prompt="q", ground_truth=_condition())

    result = RunResult(id="t1", trial=1, response=trajectory)

    assert scorer.score_item(item, [result])[0].value == 0.0


def test_versioned_pass_condition_rejects_reused_call_id():
    trajectory = _condition_trajectory()
    duplicate = Turn(
        role=trajectory.turns[0].role,
        content=trajectory.turns[0].content,
    )
    trajectory.turns.insert(1, duplicate)
    scorer = PassAtOneScorer(
        condition_schema=AGENTIC_PASS_CONDITION_SCHEMA_VERSION
    )
    item = BenchmarkItem(id="t1", prompt="q", ground_truth=_condition())

    result = RunResult(id="t1", trial=1, response=trajectory)

    assert scorer.score_item(item, [result])[0].value == 0.0
