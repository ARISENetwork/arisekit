from arisekit import (
    BenchmarkItem,
    Metric,
    RunResult,
    compose_scorers,
    contains,
    deferred,
    exact_match,
    numeric,
    regex_match,
)
from arisekit.scorer import choice


def _result(text: str, *, trial: int = 1, error: str | None = None) -> RunResult:
    return RunResult(id="x", trial=trial, response=text, error=error)


def test_exact_match_is_case_insensitive_by_default():
    scorer = exact_match()
    item = BenchmarkItem(id="x", prompt="Q", ground_truth="Paris")
    metrics = scorer.score_item(item, [_result("paris"), _result("Berlin")])
    assert len(metrics) == 1
    assert metrics[0].name == "accuracy"
    assert metrics[0].value == 0.5
    assert metrics[0].n == 2


def test_exact_match_treats_errored_trial_as_zero():
    scorer = exact_match()
    item = BenchmarkItem(id="x", prompt="Q", ground_truth="A")
    metrics = scorer.score_item(item, [_result("A"), _result("", error="boom")])
    assert metrics[0].value == 0.5


def test_contains_accepts_list_of_alternatives():
    scorer = contains()
    item = BenchmarkItem(id="x", prompt="Q", ground_truth=["dyspnea", "shortness of breath"])
    metrics = scorer.score_item(
        item,
        [_result("Patient with shortness of breath"), _result("Acute pain")],
    )
    assert metrics[0].value == 0.5


def test_regex_match_uses_search():
    scorer = regex_match(r"answer:\s*(\d+)")
    item = BenchmarkItem(id="x", prompt="Q", ground_truth=None)
    metrics = scorer.score_item(
        item,
        [_result("the answer: 42 stands"), _result("nope")],
    )
    assert metrics[0].value == 0.5


def test_numeric_with_tolerance():
    scorer = numeric(atol=0.5)
    item = BenchmarkItem(id="x", prompt="Q", ground_truth=42)
    metrics = scorer.score_item(
        item,
        [_result("the answer is 42.3"), _result("around 50")],
    )
    assert metrics[0].value == 0.5


def test_choice_picks_first_option_in_response():
    scorer = choice(choices=["A", "B", "C"])
    item = BenchmarkItem(id="x", prompt="Q", ground_truth="B")
    metrics = scorer.score_item(item, [_result("I think B is correct"), _result("A")])
    assert metrics[0].value == 0.5


def test_compose_scorers_concatenates_metrics():
    scorer = compose_scorers(
        exact_match(name="exact"),
        contains(name="contains"),
    )
    item = BenchmarkItem(id="x", prompt="Q", ground_truth="paris")
    metrics = scorer.score_item(item, [_result("Paris is the capital")])
    assert {m.name for m in metrics} == {"exact", "contains"}
    by_name = {m.name: m.value for m in metrics}
    assert by_name["exact"] == 0.0
    assert by_name["contains"] == 1.0


def test_deferred_scorer_emits_no_placeholder_metric():
    item = BenchmarkItem(id="x", prompt="Q")
    assert deferred().score_item(item, [_result("answer")]) == []
