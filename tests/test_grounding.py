"""Tests for arisekit.evaluation.grounding: judge-backed grounding scorer.

Every model-backed path uses an injected fake client so the suite is fully
offline and deterministic.
"""

from __future__ import annotations

import pytest

from arisekit.client import ModelCall, ModelResponse
from arisekit.evaluation.grounding import (
    GROUNDING_MULTIPLIER,
    GroundingScorer,
    grounding_multiplier,
)
from arisekit.types import BenchmarkItem, RunResult, Trajectory, Turn


class _FakeJudge:
    """Fake ModelClient returning a canned grounding judgment as JSON text."""

    def __init__(self, text: str):
        self.text = text
        self.calls = 0
        self.last_prompt: str | None = None

    def __call__(self, call: ModelCall) -> ModelResponse:
        self.calls += 1
        prompt = call.item.prompt
        self.last_prompt = prompt if isinstance(prompt, str) else str(prompt)
        return ModelResponse(text=self.text)


def _trajectory_result(final: str, tool_result: object) -> RunResult:
    traj = Trajectory(
        turns=[
            Turn(role="tool_call", content={"name": "search_observations"}),
            Turn(role="tool_result", content=tool_result),
            Turn(role="assistant", content=final),
        ],
        final_response=final,
    )
    return RunResult(id="c1", trial=1, response=traj)


# --- grounding_multiplier helper -------------------------------------


def test_grounding_multiplier_integer_anchors():
    for score, expected in GROUNDING_MULTIPLIER.items():
        assert grounding_multiplier(score) == expected


def test_grounding_multiplier_interpolates_half_points():
    # Halfway between 4 (0.95) and 5 (1.0) is 0.975.
    assert abs(grounding_multiplier(4.5) - 0.975) < 1e-9


def test_grounding_multiplier_clamps_out_of_range():
    assert grounding_multiplier(9.0) == 1.0
    assert grounding_multiplier(-1.0) == GROUNDING_MULTIPLIER[1]


# --- GroundingScorer -------------------------------------------------


@pytest.mark.parametrize("temperature", [None, 0.0, 0.5])
def test_grounding_forwards_explicit_temperature_to_client(temperature):
    calls = []

    def judge(call):
        calls.append(call)
        return ModelResponse(text='{"grounding": 5, "fabricated_claims": []}')

    scorer = GroundingScorer(client=judge, temperature=temperature)
    metrics = scorer.score_item(
        BenchmarkItem(id="c1", prompt="Retrieve the family name"),
        [_trajectory_result("Hernandez", {"family": "Hernandez"})],
    )
    assert calls[0].temperature == temperature
    assert metrics[0].n == 1


def test_grounding_keeps_zero_temperature_by_default():
    assert GroundingScorer(client=_FakeJudge("{}")).temperature == 0.0


def test_grounding_metric_matches_canned_score():
    judge = _FakeJudge('{"grounding": 4, "fabricated_claims": []}')
    scorer = GroundingScorer(client=judge)
    item = BenchmarkItem(id="c1", prompt="What is the latest HbA1c?")
    result = _trajectory_result(
        "HbA1c is 9.2% as of 2026-04-10.",
        {"hba1c": "9.2%", "date": "2026-04-10"},
    )

    metrics = scorer.score_item(item, [result])

    by_name = {m.name: m for m in metrics}
    assert "grounding" in by_name
    grounding = by_name["grounding"]
    assert grounding.category == "grounding"
    assert 0.0 <= grounding.value <= 1.0
    # (4 - 1) / 4 = 0.75
    assert abs(grounding.value - 0.75) < 1e-9
    assert grounding.n == 1
    assert judge.calls == 1
    # The retrieved tool-result value is serialized into the judge prompt.
    assert "9.2%" in (judge.last_prompt or "")
    # No penalty metric unless requested.
    assert "grounding_penalty_multiplier" not in by_name


def test_grounding_emits_penalty_multiplier_when_enabled():
    judge = _FakeJudge('{"grounding": 4, "fabricated_claims": []}')
    scorer = GroundingScorer(client=judge, penalty=True)
    item = BenchmarkItem(id="c1", prompt="What is the latest HbA1c?")
    result = _trajectory_result(
        "HbA1c is 9.2% as of 2026-04-10.",
        {"hba1c": "9.2%"},
    )

    metrics = scorer.score_item(item, [result])

    by_name = {m.name: m for m in metrics}
    assert "grounding_penalty_multiplier" in by_name
    multiplier = by_name["grounding_penalty_multiplier"]
    assert multiplier.category == "grounding"
    # Grounding score 4 maps to a 0.95 multiplier.
    assert abs(multiplier.value - 0.95) < 1e-9


def test_grounding_scores_pure_text_answer_with_no_trajectory():
    # A pure-text answer has no retrieved evidence; the judge can still score
    # it (here: low), and the scorer still emits a grounding metric.
    judge = _FakeJudge('{"grounding": 1, "fabricated_claims": ["invented INR"]}')
    scorer = GroundingScorer(client=judge)
    item = BenchmarkItem(id="c2", prompt="What is the INR?")
    result = RunResult(id="c2", trial=1, response="The INR is 3.4.")

    metrics = scorer.score_item(item, [result])

    by_name = {m.name: m.value for m in metrics}
    assert judge.calls == 1
    # (1 - 1) / 4 = 0.0
    assert abs(by_name["grounding"] - 0.0) < 1e-9
    assert "(no tool results retrieved)" in (judge.last_prompt or "")


def test_grounding_skips_errored_trials():
    judge = _FakeJudge('{"grounding": 5, "fabricated_claims": []}')
    scorer = GroundingScorer(client=judge)
    item = BenchmarkItem(id="c1", prompt="Q")
    good = _trajectory_result("A", {"v": 1})
    errored = RunResult(id="c1", trial=2, response="", error="boom")

    metrics = scorer.score_item(item, [good, errored])

    grounding = next(m for m in metrics if m.name == "grounding")
    assert grounding.n == 1
    assert judge.calls == 1
    assert abs(grounding.value - 1.0) < 1e-9


class _SeqJudge:
    """Fake ModelClient returning a different canned text per call."""

    def __init__(self, texts: list[str]):
        self.texts = list(texts)
        self.i = 0

    def __call__(self, call: ModelCall) -> ModelResponse:
        text = self.texts[min(self.i, len(self.texts) - 1)]
        self.i += 1
        return ModelResponse(text=text)


def test_grounding_penalty_averages_per_trial_multipliers():
    # Two trials: perfectly grounded (5) and largely fabricated (1). The penalty
    # is the mean of per-trial multipliers (1.0 + 0.3)/2 = 0.65, NOT the convex
    # multiplier(mean=3) = 0.8 which would under-penalize the fabrication.
    judge = _SeqJudge([
        '{"grounding": 5, "fabricated_claims": []}',
        '{"grounding": 1, "fabricated_claims": ["invented"]}',
    ])
    scorer = GroundingScorer(client=judge, penalty=True)
    item = BenchmarkItem(id="c1", prompt="Q")
    responses = [
        _trajectory_result("grounded answer", {"v": 1}),
        _trajectory_result("fabricated answer", {"v": 2}),
    ]
    by = {m.name: m.value for m in scorer.score_item(item, responses)}
    # grounding metric: normalized mean raw = ((5+1)/2 - 1) / 4 = 0.5
    assert abs(by["grounding"] - 0.5) < 1e-9
    # penalty multiplier: mean of per-trial multipliers = 0.65
    assert abs(by["grounding_penalty_multiplier"] - 0.65) < 1e-9
