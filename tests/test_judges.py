"""Errored-trial handling and score clamping for the LLM judges (offline)."""

from __future__ import annotations

from arisekit.client import ModelCall, ModelResponse
from arisekit.judges import LLMJudge, MultiJudgePanel, _parse_scores
from arisekit.types import BenchmarkItem, RunResult


class _StubJudge:
    """Fake ModelClient returning a fixed JSON judgment."""

    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def __call__(self, call: ModelCall) -> ModelResponse:
        self.calls += 1
        return ModelResponse(text=self.text)


def _responses_with_one_error() -> list[RunResult]:
    return [
        RunResult(id="c1", trial=1, response="good"),
        RunResult(id="c1", trial=2, response="good"),
        RunResult(id="c1", trial=3, response=None, error="API timeout"),
    ]


def test_llm_judge_skips_errored_trials():
    judge = _StubJudge('{"safety": 0.9}')
    scorer = LLMJudge(judge_model="fake", dimensions=["safety"], client=judge)
    metrics = scorer.score_item(BenchmarkItem(id="c1", prompt="q"), _responses_with_one_error())
    m = {x.name: x for x in metrics}["safety"]
    # The errored trial is skipped, so the mean reflects only graded trials
    # (0.9), not diluted to 0.6 by scoring the crash as zero.
    assert abs(m.value - 0.9) < 1e-9
    assert m.n == 2
    assert judge.calls == 2


def test_multi_judge_panel_skips_errored_trials():
    j1 = _StubJudge('{"safety": 0.8}')
    j2 = _StubJudge('{"safety": 1.0}')
    scorer = MultiJudgePanel(judges=["a", "b"], dimensions=["safety"], clients={"a": j1, "b": j2})
    metrics = scorer.score_item(BenchmarkItem(id="c1", prompt="q"), _responses_with_one_error())
    by = {x.name: x.value for x in metrics}
    # Two graded trials x two judges -> mean(0.8,1.0,0.8,1.0) = 0.9; the errored
    # trial contributes no 0.0 diluter.
    assert abs(by["safety"] - 0.9) < 1e-9
    assert abs(by["overall"] - 0.9) < 1e-9


def test_parse_scores_clamps_out_of_range_to_unit_interval():
    # A judge that ignores the 0.0-1.0 scale (emits 1-5 or 0-100) is clamped.
    assert _parse_scores('{"safety": 5}', ["safety"]) == {"safety": 1.0}
    assert _parse_scores('{"safety": -2}', ["safety"]) == {"safety": 0.0}
    assert _parse_scores('{"safety": 0.7}', ["safety"]) == {"safety": 0.7}
