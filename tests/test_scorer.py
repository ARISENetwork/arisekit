import pytest

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


@pytest.mark.parametrize(
    "text",
    [
        "\u22122",  # U+2212 minus sign
        "Answer: \u20132",  # en dash
        "(\u20142)",  # em dash
        "\ufe632",  # small hyphen-minus
        "\uff0d2",  # fullwidth hyphen-minus
        "\u20112",  # non-breaking hyphen
        "\u20122",  # figure dash
    ],
)
def test_numeric_reads_typographic_minus_signs(text):
    scorer = numeric()
    item = BenchmarkItem(id="x", prompt="Q", ground_truth=-2)
    assert scorer.score_item(item, [_result(text)])[0].value == 1.0


def test_numeric_reads_typographic_minus_in_decimal():
    scorer = numeric(atol=0.01)
    item = BenchmarkItem(id="x", prompt="Q", ground_truth=-0.5)
    metrics = scorer.score_item(item, [_result("The change is \u22120.5 mmol/L")])
    assert metrics[0].value == 1.0


@pytest.mark.parametrize("ground_truth", ["\u22122", "\u20132", " \u22122 "])
def test_numeric_accepts_typographic_minus_in_ground_truth(ground_truth):
    scorer = numeric()
    item = BenchmarkItem(id="x", prompt="Q", ground_truth=ground_truth)
    metrics = scorer.score_item(item, [_result("-2"), _result("2")])
    assert metrics[0].value == 0.5
    assert metrics[0].n == 2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("answer\u201442", 42),  # a dash after a word is punctuation
        ("T\u20132", 2),  # a dash after a letter is a hyphen, not a sign
        ("pH\u20137", 7),
    ],
)
def test_numeric_keeps_dashes_used_as_punctuation(text, expected):
    scorer = numeric()
    item = BenchmarkItem(id="x", prompt="Q", ground_truth=expected)
    assert scorer.score_item(item, [_result(text)])[0].value == 1.0


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
