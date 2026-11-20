"""Tests for arisekit.compare comparative scorecards (pure, offline)."""

from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

from arisekit import Metric
from arisekit.compare import Cell, Scorecard, comparative_scorecard


def _uniformly_best_suite() -> dict[str, object]:
    """Three vendors; ``alpha`` is best on every criterion (incl. lowest cost).

    ``alpha`` and ``beta`` are plain metric lists; ``gamma`` is a Results-like
    ``SimpleNamespace`` with a ``.metrics`` attribute to exercise duck-typing.
    """
    alpha = [
        Metric(name="accuracy", value=0.9),
        Metric(name="safety", value=0.9),
        Metric(name="cost", value=0.1),
    ]
    beta = [
        Metric(name="accuracy", value=0.5),
        Metric(name="safety", value=0.5),
        Metric(name="cost", value=0.5),
    ]
    gamma = SimpleNamespace(
        metrics=[
            Metric(name="accuracy", value=0.3),
            Metric(name="safety", value=0.3),
            Metric(name="cost", value=0.9),
        ]
    )
    return {"alpha": alpha, "beta": beta, "gamma": gamma}


def test_criteria_discovered_and_ordered():
    sc = comparative_scorecard(
        _uniformly_best_suite(),
        higher_is_better={"accuracy": True, "safety": True, "cost": False},
    )
    # Union of names across vendors, sorted.
    assert sc.criteria == ["accuracy", "cost", "safety"]
    assert sc.vendors == ["alpha", "beta", "gamma"]


def test_criteria_can_be_restricted_and_ordered():
    sc = comparative_scorecard(
        _uniformly_best_suite(),
        criteria=["safety", "accuracy"],
        higher_is_better=True,
    )
    assert sc.criteria == ["safety", "accuracy"]
    assert "cost" not in sc.cells


def test_composite_in_unit_range_and_best_vendor_ranks_first():
    sc = comparative_scorecard(
        _uniformly_best_suite(),
        higher_is_better={"accuracy": True, "safety": True, "cost": False},
    )
    for value in sc.composite.values():
        assert 0.0 <= value <= 1.0
    # alpha is best on every criterion -> composite 1.0 and rank 1.
    assert sc.ranking[0] == "alpha"
    assert abs(sc.composite["alpha"] - 1.0) < 1e-9
    assert sc.ranking == ["alpha", "beta", "gamma"]


def test_duck_typing_incorporates_results_like_object():
    sc = comparative_scorecard(_uniformly_best_suite())
    # gamma arrived as a SimpleNamespace with .metrics and is fully present.
    assert "gamma" in sc.vendors
    assert "gamma" in sc.composite
    assert sc.cells["accuracy"]["gamma"].value == 0.3


def test_lower_is_better_inverts():
    a = [Metric(name="cost", value=0.2)]
    b = [Metric(name="cost", value=0.8)]
    sc = comparative_scorecard({"a": a, "b": b}, higher_is_better={"cost": False})
    # Lower cost should help the composite.
    assert sc.composite["a"] > sc.composite["b"]
    assert sc.ranking[0] == "a"
    # With the direction flipped, the higher cost would win instead.
    sc_up = comparative_scorecard({"a": a, "b": b}, higher_is_better=True)
    assert sc_up.composite["b"] > sc_up.composite["a"]


def test_missing_criterion_is_excluded_not_imputed():
    # b never reports "safety"; it must not be penalized with an implicit 0.
    a = [Metric(name="accuracy", value=0.4), Metric(name="safety", value=0.1)]
    b = [Metric(name="accuracy", value=0.6)]
    sc = comparative_scorecard({"a": a, "b": b})
    assert "b" not in sc.cells["safety"]
    # b's composite rests only on accuracy (its best-normalized criterion).
    assert abs(sc.composite["b"] - 1.0) < 1e-9


def test_overall_category_preferred_over_others():
    metrics = [
        Metric(name="accuracy", value=0.2, category="pediatrics"),
        Metric(name="accuracy", value=0.9, category="overall"),
    ]
    sc = comparative_scorecard({"a": metrics})
    assert sc.cells["accuracy"]["a"].value == 0.9


def test_pairwise_flags_distinguishable_vs_overlapping():
    a = [Metric(name="accuracy", value=0.90, ci=0.02)]
    b = [Metric(name="accuracy", value=0.80, ci=0.02)]
    c = [Metric(name="accuracy", value=0.85, ci=0.10)]
    sc = comparative_scorecard({"a": a, "b": b, "c": c})
    pw = sc.pairwise("accuracy")
    # [0.88,0.92] vs [0.78,0.82] are disjoint.
    assert pw[("a", "b")] == "distinguishable"
    # c's wide interval overlaps both.
    assert pw[("a", "c")] == "overlapping"
    assert pw[("b", "c")] == "overlapping"


def test_pairwise_treats_missing_ci_as_overlapping():
    a = [Metric(name="acc", value=0.9, ci=None)]
    b = [Metric(name="acc", value=0.1, ci=0.01)]
    sc = comparative_scorecard({"a": a, "b": b})
    assert sc.pairwise("acc")[("a", "b")] == "overlapping"


def test_to_csv_has_vendor_columns_and_composite_row(tmp_path: Path):
    sc = comparative_scorecard(
        _uniformly_best_suite(),
        higher_is_better={"accuracy": True, "safety": True, "cost": False},
    )
    out = sc.to_csv(tmp_path / "scorecard.csv")
    assert out.exists()
    with out.open() as fh:
        rows = list(csv.reader(fh))
    header = rows[0]
    assert header[0] == "criterion"
    for vendor in ("alpha", "beta", "gamma"):
        assert vendor in header
    labels = [r[0] for r in rows]
    assert "composite" in labels
    assert "rank" in labels
    # A criterion cell renders as value(ci) / value; here CIs are absent.
    acc_row = next(r for r in rows if r[0] == "accuracy")
    assert acc_row[header.index("alpha")] == "0.900"


def test_to_markdown_contains_ranking_order():
    sc = comparative_scorecard(
        _uniformly_best_suite(),
        higher_is_better={"accuracy": True, "safety": True, "cost": False},
    )
    md = sc.to_markdown()
    for vendor in ("alpha", "beta", "gamma"):
        assert vendor in md
    # Best-first ordering is reflected in the table body.
    assert md.index("alpha") < md.index("beta") < md.index("gamma")


def test_cell_dataclass_defaults():
    cell = Cell(value=0.5)
    assert cell.ci is None
    assert cell.n is None
    assert isinstance(comparative_scorecard({"a": []}), Scorecard)


def test_all_equal_lower_is_better_stays_neutral():
    # All vendors tie on a lower-is-better criterion: it must be neutral (1.0),
    # not flipped to 0.0 (which would assign the WORST score to a tie).
    data = {
        "A": [Metric("cost", 2.0), Metric("acc", 1.0)],
        "B": [Metric("cost", 2.0), Metric("acc", 0.0)],
    }
    sc = comparative_scorecard(data, higher_is_better={"cost": False, "acc": True})
    # cost ties -> neutral for both; acc discriminates -> A best on composite.
    assert sc.ranking[0] == "A"
    assert sc.composite["A"] > sc.composite["B"]
    assert abs(sc.composite["A"] - 1.0) < 1e-9


def test_single_vendor_lower_is_better_is_neutral_not_worst():
    # A sole reporter of a lower-is-better criterion (span == 0) is neutral 1.0,
    # not 0.0.
    sc = comparative_scorecard({"only": [Metric("err", 0.1)]}, higher_is_better={"err": False})
    assert abs(sc.composite["only"] - 1.0) < 1e-9
