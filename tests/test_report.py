"""Tests for arisekit.report model cards and checklist coverage (offline).

Everything here is deterministic and network-free: a Results-like
``SimpleNamespace`` stands in for a completed run, so no model or judge is
ever called.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from arisekit import Metric
from arisekit.report import (
    Checklist,
    ChecklistReport,
    ModelCard,
    REQUIRES_HUMAN_INPUT,
)


def _fake_results() -> SimpleNamespace:
    """A minimal Results-like object exposing only the fields the card reads."""
    return SimpleNamespace(
        metrics=[Metric("F1", 0.8, ci=0.05, n=100)],
        model="m",
        benchmark="b",
        cost=1.23,
    )


# --- ModelCard -------------------------------------------------------


def test_from_results_populates_key_metrics():
    card = ModelCard.from_results(_fake_results())
    assert len(card.key_metrics) == 1
    row = card.key_metrics[0]
    assert row["metric"] == "F1"
    assert row["value"] == 0.8
    assert row["ci"] == 0.05
    assert row["n"] == 100
    # Basic info carries the measured identity of the run.
    assert card.basic_info["model"] == "m"
    assert card.basic_info["benchmarks"] == ["b"]


def test_from_results_collects_human_input_but_keeps_measured_fields():
    card = ModelCard.from_results(_fake_results())
    # Prose fields a run cannot compute are stamped and collected as dotted keys.
    assert card.human_input_required
    assert all(isinstance(key, str) for key in card.human_input_required)
    # An always-manual prose field must route to a human owner.
    assert any("intended_users" in key for key in card.human_input_required)
    # The measured cost was supplied, so it is not among the outstanding keys.
    assert not any("evaluation_cost_usd" in key for key in card.human_input_required)
    # The sentinel string never leaks into the measured metric row.
    assert REQUIRES_HUMAN_INPUT not in json.dumps(card.key_metrics)


def test_disclaimer_present_and_framed_as_evidence():
    card = ModelCard.from_results(_fake_results())
    assert card.disclaimer
    assert "not a certification" in card.disclaimer.lower()


def test_to_json_round_trips():
    card = ModelCard.from_results(_fake_results())
    text = card.to_json()
    loaded = json.loads(text)
    assert loaded == card.to_dict()
    assert loaded["basic_info"]["model"] == "m"
    assert loaded["disclaimer"] == card.disclaimer


def test_to_markdown_contains_disclaimer_text():
    card = ModelCard.from_results(_fake_results())
    md = card.to_markdown()
    assert card.disclaimer in md
    assert "Requires human input" in md
    assert "F1" in md


# --- Checklist -------------------------------------------------------


def test_load_reads_all_items():
    checklist = Checklist.load("tripod_llm")
    assert checklist.name == "tripod_llm"
    assert len(checklist.items) == 14
    ids = {item.id for item in checklist.items}
    assert "discrimination" in ids
    assert "calibration" in ids
    assert "subgroup" in ids


def test_evaluate_auto_satisfies_minority_and_routes_majority():
    checklist = Checklist.load("tripod_llm")
    report = checklist.evaluate(_fake_results())
    assert isinstance(report, ChecklistReport)
    counts = report.counts
    total = counts["total"]
    # Only metrics and cost auto-satisfy from a bare run: an honest minority.
    assert counts["satisfied"] == 2
    assert counts["satisfied"] < counts["routed"]
    assert counts["satisfied"] * 2 < total
    assert counts["satisfied"] + counts["routed"] + counts["gap"] == total


def test_calibration_and_subgroup_route_with_owning_skill():
    checklist = Checklist.load("tripod_llm")
    report = checklist.evaluate(_fake_results())
    by_id = {status.item.id: status for status in report.statuses}
    # Neither calibration nor subgroup is available from a plain run, so both
    # route to the skill that owns them, and the detail names that skill.
    for item_id in ("calibration", "subgroup"):
        status = by_id[item_id]
        assert status.status == "routed"
        assert status.item.owning_skill is not None
        assert status.item.owning_skill in status.detail


def test_evaluate_can_declare_extra_sources_available():
    checklist = Checklist.load("tripod_llm")
    report = checklist.evaluate(
        _fake_results(),
        available={"calibration", "subgroup"},
    )
    by_id = {status.item.id: status for status in report.statuses}
    assert by_id["calibration"].status == "satisfied"
    assert by_id["subgroup"].status == "satisfied"


def test_evaluate_accepts_plain_metric_list():
    checklist = Checklist.load("tripod_llm")
    report = checklist.evaluate([Metric("F1", 0.8)])
    by_id = {status.item.id: status for status in report.statuses}
    # Metrics present satisfies discrimination; no cost was recorded, so the
    # compute-cost item routes instead.
    assert by_id["discrimination"].status == "satisfied"
    assert by_id["compute_cost"].status == "routed"


def test_checklist_markdown_mentions_auto_satisfied_count():
    checklist = Checklist.load("tripod_llm")
    report = checklist.evaluate(_fake_results())
    md = report.to_markdown()
    counts = report.counts
    assert f"{counts['satisfied']} of {counts['total']}" in md
    assert "auto-satisfied" in md.lower()
    # Framed as coverage, not clearance.
    assert "not a certification" in md.lower()
