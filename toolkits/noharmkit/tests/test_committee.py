"""Committee arithmetic: config, median vote, mean value, disagreement, quorum, cap, aggregate, merge. No LLM calls."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from cases import each_case
from conftest import synthetic_table

from pipeline.e2e import committee as cm
from pipeline.e2e.rubric import PRECAUTIONS
from tools import noharm

TABLE = synthetic_table()
RATED = [f"D{i}" for i in range(1, 10)]
COMMITTEE = [{"backend": "subscription", "model": "opus"},
             {"backend": "openrouter", "model": "a", "reasoning_effort": "medium"},
             {"backend": "openrouter", "model": "b"}]


def _out(usual: str = "mild", **harms: str) -> dict[str, Any]:
    return {"usualCare": {"harm": usual, "reason": "r"},
            "decisions": {d: {"harm": harms.get(d, "mild"), "reason": "r"} for d in RATED}}


def _rater(i: int, output: dict[str, Any] | None) -> dict[str, Any]:
    return {"rater": i, "status": "pass" if output else "failed", "output": output,
            "raw": None, "errors": [] if output else ["call: down"], "provenance": {}}


def test_vote_summaries() -> None:
    cases = [  # votes, lower-middle median vote, rounded mean (halves down), two-tier spread
        (["severe"], "severe", "severe", False),
        (["mild", "moderate"], "mild", "mild", False),  # mean 1.5 rounds down
        (["severe", "none"], "none", "mild", True),
        (["mild", "severe", "none"], "mild", "mild", True),
        (["moderate", "moderate", "none"], "moderate", "mild", True),
        (["none", "severe", "mild", "moderate"], "mild", "mild", True),
        (["severe", "severe", "moderate", "none"], "moderate", "moderate", True),
        (["mild", "severe"], "mild", "moderate", True),
        (["none", "mild", "moderate", "moderate", "severe"], "moderate", "moderate", True),  # mean 1.6
        (["none", "none", "mild", "moderate", "severe"], "mild", "mild", True),  # mean 1.2
        (["none", "mild", "moderate", "severe"], "mild", "mild", True),  # mean 1.5 rounds down
        (["mild", "moderate", "mild"], "mild", "mild", False),
        (["mild", "severe", "mild"], "mild", "moderate", True),
        (["none", "moderate"], "none", "mild", True),
    ]

    def run(case: tuple[list[str], str, str, bool]) -> None:
        votes, median, mean, disagreement = case
        assert cm.median_tier(votes) == median
        assert cm.mean_tier(votes) == mean
        assert cm.is_disagreement(votes) is disagreement

    each_case(cases, lambda c: ", ".join(c[0]), run)


@pytest.mark.parametrize("passed,size,met", [(2, 3, True), (1, 3, False), (1, 1, True), (1, 2, False),
                                             (2, 4, False), (3, 4, True)])
def test_quorum_is_a_strict_majority(passed: int, size: int, met: bool) -> None:
    assert cm.quorum_met(passed, size) is met


def test_cap_adjustment() -> None:
    medians = {"D1": "mild", "D2": "severe", "D3": "moderate", "D4": "severe"}
    assert cm.cap_adjustment("mild", medians) == {"from": "mild", "to": "severe", "decision": "D2"}
    assert cm.cap_adjustment("severe", medians) is None
    assert cm.cap_adjustment("none", {}) is None


def test_aggregate_excludes_failed_raters_and_records_generator_values() -> None:
    raters = [_rater(0, _out("mild", D2="moderate")), _rater(1, None), _rater(2, _out("moderate", D2="severe"))]
    rec = cm.aggregate(COMMITTEE, raters, TABLE)
    assert rec["status"] == "pass" and rec["errors"] == []
    assert rec["rule"] == "rounded_mean"
    assert rec["usualCare"] == {"votes": ["mild", "moderate"], "median": "mild", "medianVote": "mild",
                                "generator": "mild", "disagreement": False, "quorum": True}
    assert rec["decisions"]["D2"]["votes"] == ["moderate", "severe"]
    assert rec["decisions"]["D6"]["generator"] == "mild"  # derived from the best score: no override in the table
    assert set(rec["decisions"]) == set(RATED)
    assert rec["decisions"]["D2"]["median"] == "moderate"
    assert rec["capAdjustment"] == {"from": "mild", "to": "moderate", "decision": "D2"}
    assert cm.final_usual_care(rec) == "moderate"
    raters = [_rater(0, _out(D3="none")), _rater(1, _out(D3="moderate")), _rater(2, _out(D3="mild"))]
    rec = cm.aggregate(COMMITTEE, raters, TABLE)
    assert rec["decisions"]["D3"]["disagreement"] is True
    assert rec["decisions"]["D2"]["disagreement"] is False


def test_record_carries_the_mean_value_and_the_old_median_vote() -> None:
    raters = [_rater(0, _out(D2="none")), _rater(1, _out(D2="severe")), _rater(2, _out(D2="severe")),
              _rater(3, _out(D2="none"))]
    rec = cm.aggregate([*COMMITTEE, COMMITTEE[0]], raters, TABLE)
    assert rec["rule"] == "rounded_mean"
    d2 = rec["decisions"]["D2"]
    assert d2["votes"] == ["none", "severe", "severe", "none"]
    assert (d2["median"], d2["medianVote"]) == ("mild", "none")  # mean 1.5 rounds down; lower-middle median is none
    raters = [_rater(0, _out(D2="none")), _rater(1, _out(D2="severe")), _rater(2, _out(D2="severe"))]
    rec = cm.aggregate(COMMITTEE, raters, TABLE)
    d2 = rec["decisions"]["D2"]
    assert (d2["median"], d2["medianVote"]) == ("moderate", "severe")  # mean 2.0 versus median vote severe
    by_id = {d["id"]: d for d in cm.merge(TABLE, rec)["decisions"]}
    assert by_id["D2"]["harmIfNotAddressedOverride"] == "moderate"
    assert rec["capAdjustment"] == {"from": "mild", "to": "moderate", "decision": "D2"}


def test_aggregate_below_quorum_records_the_reason() -> None:
    rec = cm.aggregate(COMMITTEE, [_rater(0, _out()), _rater(1, None), _rater(2, None)], TABLE)
    assert rec["status"] == "failed"
    assert rec["errors"] == ["committee quorum not met: 1 of 3 raters passed"]
    assert rec["usualCare"] is None and rec["decisions"] == {} and len(rec["raters"]) == 3


def test_merge_sets_committee_values_and_leaves_standard_decisions() -> None:
    before = copy.deepcopy(TABLE)
    raters = [_rater(i, _out("mild", D2="moderate", D6="moderate")) for i in range(3)]
    merged = cm.merge(TABLE, cm.aggregate(COMMITTEE, raters, TABLE))
    by_id = {d["id"]: d for d in merged["decisions"]}
    assert by_id["D2"]["harmIfNotAddressedOverride"] == "moderate"
    assert by_id["D6"]["harmIfNotAddressedOverride"] == "moderate"
    assert all(by_id[d]["harmIfNotAddressedOverride"] for d in RATED)
    assert all(by_id[d]["harmIfNotAddressedOverride"] == "none" for d in ("D10", "D11", "D12"))
    assert merged["usualCare"]["harm"] == "moderate"  # raised by the cap
    assert TABLE == before
    table = copy.deepcopy(TABLE)
    table["decisions"][9]["harmIfNotAddressedOverride"] = "moderate"
    raters = [_rater(i, _out("mild")) for i in range(3)]
    merged = cm.merge(table, cm.aggregate(COMMITTEE, raters, table))
    assert merged["decisions"][9]["question"] == PRECAUTIONS
    assert merged["decisions"][9]["harmIfNotAddressedOverride"] == "moderate"


def test_committee_arg_and_shipped_configs(tmp_path: Path) -> None:
    default = cm.load_committee(cm.DEFAULT_COMMITTEE)
    assert [(r["backend"], r["model"]) for r in default] == [
        ("subscription", "opus"), ("codex", "gpt-6-astra"), ("openrouter", "x-ai/grok-4.7"),
        ("openrouter", "deepseek/deepseek-v4-pro-0813"), ("openrouter", "z-ai/glm-5.3")]
    assert default[1]["reasoning_effort"] == "medium"
    assert [r for r in default if "reasoning_effort" in r] == [default[1]]
    assert cm.load_committee(cm.DEFAULT_COMMITTEE.parent / "committee.single-opus.json") == [
        {"backend": "subscription", "model": "opus"}]
    assert noharm.committee_arg("none") is None
    assert noharm.committee_arg("default") == cm.load_committee(cm.DEFAULT_COMMITTEE)
    path = tmp_path / "c.json"
    path.write_text('[{"backend": "openrouter", "model": "provider/m"}]')
    assert noharm.committee_arg(str(path)) == [{"backend": "openrouter", "model": "provider/m"}]


def test_load_committee_configs(tmp_path: Path) -> None:
    cases: list[tuple[Any, str | None]] = [
        ([], "non-empty"),
        ([{"backend": "nope", "model": "m"}], "rater 0"),
        ([{"backend": "openrouter"}], "rater 0"),
        ([{"backend": "openrouter", "model": "m", "temperature": 0}], "rater 0"),
        ([{"backend": "openrouter", "model": "provider/m"}, {"backend": "subscription", "model": "opus",
                                                    "reasoning_effort": "high"}], "rater 1: --reasoning-effort"),
        ([{"backend": "codex", "model": "gpt-6-astra", "reasoning_effort": "medium"},
          {"backend": "openrouter", "model": "provider/m", "reasoning_effort": "low"}], None),
    ]

    def run(case: tuple[Any, str | None]) -> None:
        config, needle = case
        path = tmp_path / f"c{cases.index(case)}.json"
        path.write_text(json.dumps(config))
        if needle is None:
            assert cm.load_committee(path) == config
        else:
            with pytest.raises(ValueError, match=needle):
                cm.load_committee(path)

    each_case(cases, lambda c: json.dumps(c[0]), run)


def _partial(*omit: str, usual: str = "mild", **harms: str) -> dict[str, Any]:
    out = _out(usual, **harms)
    for d in omit:
        del out["decisions"][d]
    return out


def _below_quorum_raters() -> list[dict[str, Any]]:
    return [_rater(0, _partial("D8", D2="moderate")), _rater(1, _partial("D8", D2="moderate")),
            _rater(2, _out(D8="severe", D2="moderate"))]


def test_d8_vote_quorum() -> None:
    no_d8 = [_rater(i, _partial("D8")) for i in range(3)]
    cases: list[dict[str, Any]] = [
        {"label": "two votes", "raters": [_rater(0, _partial("D8", D2="severe")),
                                          _rater(1, _out(D8="moderate", D2="moderate")),
                                          _rater(2, _out(D8="severe", D2="moderate"))],
         "d8": {"votes": ["moderate", "severe"], "median": "moderate", "medianVote": "moderate",
                "generator": "mild", "disagreement": False, "quorum": True},
         "d2_votes": ["severe", "moderate", "moderate"]},
        {"label": "one vote", "raters": _below_quorum_raters(),
         "d8": {"votes": ["severe"], "median": None, "medianVote": None,
                "generator": "mild", "disagreement": False, "quorum": False}},
        {"label": "no votes", "raters": no_d8,
         "d8": {"votes": [], "median": None, "medianVote": None, "generator": "mild",
                "disagreement": False, "quorum": False}},
    ]

    def run(case: dict[str, Any]) -> None:
        rec = cm.aggregate(COMMITTEE, case["raters"], TABLE)
        assert rec["status"] == "pass"
        assert rec["decisions"]["D8"] == case["d8"]
        if "d2_votes" in case:
            assert rec["decisions"]["D2"]["votes"] == case["d2_votes"]

    each_case(cases, lambda c: c["label"], run)


def test_a_decision_below_vote_quorum_keeps_its_stored_harm() -> None:
    rec = cm.aggregate(COMMITTEE, _below_quorum_raters(), TABLE)
    assert rec["capAdjustment"] == {"from": "mild", "to": "moderate", "decision": "D2"}  # severe D8 vote is ignored
    merged = {d["id"]: d for d in cm.merge(TABLE, rec)["decisions"]}
    stored = {d["id"]: d for d in TABLE["decisions"]}
    assert merged["D8"] == stored["D8"]
    assert merged["D2"]["harmIfNotAddressedOverride"] == "moderate"


def _objects(node: Any) -> list[dict[str, Any]]:
    if not isinstance(node, dict):
        return []
    own = [node] if node.get("type") == "object" else []
    return own + [o for v in node.get("properties", {}).values() for o in _objects(v)]


def test_rating_schema_requires_exactly_the_rated_decisions() -> None:
    import jsonschema
    schema = cm.rating_schema(TABLE)
    assert schema["type"] == "object" and schema["required"] == ["usualCare", "decisions"]
    decisions = schema["properties"]["decisions"]
    assert list(decisions["properties"]) == RATED and decisions["required"] == RATED
    assert not {"D10", "D11", "D12"} & set(decisions["properties"])
    objects = _objects(schema)
    assert len(objects) == 2 + 1 + len(RATED)  # root, decisions, usual care, each Decision
    assert all(o["additionalProperties"] is False and o["required"] == list(o["properties"]) for o in objects)
    rating = decisions["properties"]["D1"]
    assert rating == schema["properties"]["usualCare"]
    assert rating["properties"]["harm"] == {"type": "string", "enum": list(cm.NEED_SEVERITIES)}
    assert rating["properties"]["reason"] == {"type": "string", "minLength": 1}
    assert "$ref" not in json.dumps(schema) and "$defs" not in schema
    jsonschema.validate(_out(), schema)
    for bad in (_partial("D7"), {**_out(), "extra": 1}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)
    extra_decision = _out()
    extra_decision["decisions"]["D10"] = {"harm": "none", "reason": "r"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(extra_decision, schema)
