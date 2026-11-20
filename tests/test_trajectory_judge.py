"""Tests for arisekit.judges.trajectory: anchored rubric trajectory judge.

Every model-backed path uses an injected fake client so the suite is fully
offline and deterministic.
"""

from __future__ import annotations

from arisekit.client import ModelCall, ModelResponse
from arisekit.judges.trajectory import TrajectoryJudge
from arisekit.types import BenchmarkItem, RunResult, Trajectory, Turn

CRITERIA = [
    {"name": "factuality", "weight": 3, "scale": "1-5", "guidance": "Claims are correct."},
    {"name": "no_hallucination", "weight": 2, "scale": "pass-fail", "guidance": "No invented data."},
]


class _FakeJudge:
    """Fake ModelClient returning a canned judgment as JSON text."""

    def __init__(self, text: str):
        self.text = text
        self.calls = 0
        self.last_prompt: str | None = None

    def __call__(self, call: ModelCall) -> ModelResponse:
        self.calls += 1
        prompt = call.item.prompt
        self.last_prompt = prompt if isinstance(prompt, str) else str(prompt)
        return ModelResponse(text=self.text)


class _SeqJudge:
    """Fake ModelClient returning a different canned text per call."""

    def __init__(self, texts: list[str]):
        self.texts = list(texts)
        self.calls = 0

    def __call__(self, call: ModelCall) -> ModelResponse:
        idx = min(self.calls, len(self.texts) - 1)
        self.calls += 1
        return ModelResponse(text=self.texts[idx])


def _trajectory_result(final: str, *, trial: int = 1) -> RunResult:
    traj = Trajectory(
        turns=[
            Turn(role="tool_call", content={"name": "search_observations"}),
            Turn(role="tool_result", content={"hba1c": "9.2%"}),
            Turn(role="assistant", content=final),
        ],
        final_response=final,
    )
    return RunResult(id="c1", trial=trial, response=traj)


def test_emits_per_criterion_and_weighted_overall():
    judge = _FakeJudge('{"factuality": 4, "no_hallucination": "pass"}')
    scorer = TrajectoryJudge(judge_model="fake", criteria=CRITERIA, client=judge)
    item = BenchmarkItem(id="c1", prompt="Summarize the latest HbA1c.")

    metrics = scorer.score_item(item, [_trajectory_result("HbA1c 9.2%.")])

    by_name = {m.name: m for m in metrics}
    # factuality: (4 - 1) / 4 = 0.75
    assert abs(by_name["factuality"].value - 0.75) < 1e-9
    assert by_name["factuality"].category == "overall"
    # pass-fail pass -> 1.0
    assert abs(by_name["no_hallucination"].value - 1.0) < 1e-9
    # overall = (0.75 * 3 + 1.0 * 2) / (3 + 2) = 4.25 / 5 = 0.85
    assert abs(by_name["overall"].value - 0.85) < 1e-9
    assert by_name["overall"].n == 1
    assert judge.calls == 1


def test_pass_fail_fail_normalizes_to_zero():
    judge = _FakeJudge('{"factuality": 2, "no_hallucination": "fail"}')
    scorer = TrajectoryJudge(judge_model="fake", criteria=CRITERIA, client=judge)
    item = BenchmarkItem(id="c1", prompt="Q")

    metrics = scorer.score_item(item, [_trajectory_result("A")])

    by_name = {m.name: m.value for m in metrics}
    # factuality: (2 - 1) / 4 = 0.25 ; no_hallucination fail -> 0.0
    assert abs(by_name["factuality"] - 0.25) < 1e-9
    assert abs(by_name["no_hallucination"] - 0.0) < 1e-9
    # overall = (0.25 * 3 + 0.0 * 2) / 5 = 0.15
    assert abs(by_name["overall"] - 0.15) < 1e-9


def test_half_point_score_normalizes():
    judge = _FakeJudge('{"factuality": 4.5, "no_hallucination": "pass"}')
    scorer = TrajectoryJudge(judge_model="fake", criteria=CRITERIA, client=judge)
    item = BenchmarkItem(id="c1", prompt="Q")

    metrics = scorer.score_item(item, [_trajectory_result("A")])

    factuality = next(m for m in metrics if m.name == "factuality")
    # (4.5 - 1) / 4 = 0.875
    assert abs(factuality.value - 0.875) < 1e-9


def test_averages_across_trials():
    judge = _SeqJudge(
        [
            '{"factuality": 4, "no_hallucination": "pass"}',
            '{"factuality": 2, "no_hallucination": "fail"}',
        ]
    )
    scorer = TrajectoryJudge(judge_model="fake", criteria=CRITERIA, client=judge)
    item = BenchmarkItem(id="c1", prompt="Q")
    responses = [_trajectory_result("A", trial=1), _trajectory_result("B", trial=2)]

    metrics = scorer.score_item(item, responses)

    by_name = {m.name: m for m in metrics}
    # factuality: mean(0.75, 0.25) = 0.5 over two trials
    assert abs(by_name["factuality"].value - 0.5) < 1e-9
    assert by_name["factuality"].n == 2
    # no_hallucination: mean(1.0, 0.0) = 0.5
    assert abs(by_name["no_hallucination"].value - 0.5) < 1e-9
    # overall = (0.5 * 3 + 0.5 * 2) / 5 = 0.5
    assert abs(by_name["overall"].value - 0.5) < 1e-9
    assert judge.calls == 2


def test_trajectory_serialized_into_judge_prompt():
    judge = _FakeJudge('{"factuality": 3, "no_hallucination": "pass"}')
    scorer = TrajectoryJudge(judge_model="fake", criteria=CRITERIA, client=judge)
    item = BenchmarkItem(id="c1", prompt="Summarize.")

    scorer.score_item(item, [_trajectory_result("HbA1c 9.2%.")])

    prompt = judge.last_prompt or ""
    # Tool call, tool result, and criteria guidance all reach the judge.
    assert "search_observations" in prompt
    assert "9.2%" in prompt
    assert "No invented data." in prompt


def test_errored_trials_skipped_in_overall_n():
    judge = _FakeJudge('{"factuality": 4, "no_hallucination": "pass"}')
    scorer = TrajectoryJudge(judge_model="fake", criteria=CRITERIA, client=judge)
    item = BenchmarkItem(id="c1", prompt="Q")
    good = _trajectory_result("A", trial=1)
    errored = RunResult(id="c1", trial=2, response="", error="boom")

    metrics = scorer.score_item(item, [good, errored])

    overall = next(m for m in metrics if m.name == "overall")
    assert overall.n == 1
    assert judge.calls == 1
