import copy
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from cases import each_case

from tools.score_answer_table import RECOMMENDATION_TAGS, score_case, summarize, validation_errors

FIXTURES = Path(__file__).parent / "fixtures" / "answer_table"
CASES: dict[str, Any] = json.loads((FIXTURES / "cases.json").read_text())
SAMPLES: list[dict[str, Any]] = json.loads((FIXTURES / "samples.json").read_text())
RHO = 0.5


def _appropriate(d: dict[str, Any], i: int = 0) -> dict[str, Any]:
    """The Decision's i-th row scored 7-9."""
    return [r for r in d["recommendations"] if r["score"] >= 7][i]


def _below7(d: dict[str, Any], i: int = 0) -> dict[str, Any]:
    """The Decision's i-th row scored 1-6."""
    return [r for r in d["recommendations"] if r["score"] <= 6][i]


@pytest.mark.parametrize("sample", SAMPLES, ids=[f"{s['case']}-{s['label']}" for s in SAMPLES])
def test_mockup_sample_scores(sample: dict[str, Any]) -> None:
    result = score_case(CASES[sample["case"]], {"decisions": sample["judge"]}, RHO)
    for decision_id, (expected, expected_events) in sample["expected"].items():
        got = result["decisions"][decision_id]
        if expected in ("inactive", "provisional"):
            assert got["state"] == expected, decision_id
        else:
            assert got["state"] == "scored", decision_id
            assert got["outcome"] == expected, decision_id
            assert got["credit"] == {"met": 1.0, "partly": RHO, "notMet": 0.0}[expected]
        assert [[e["kind"], e["severity"]] for e in got["events"]] == expected_events, decision_id


def test_samples_cover_every_case() -> None:
    assert {s["case"] for s in SAMPLES} == set(CASES)


def test_unmatched_statement_marks_case_provisional() -> None:
    judge = {"decisions": {"D1": {"unmatched": [{"evidence": "unlisted synthetic action", "provisional": {"outcome": "met"}}]}}}
    assert score_case(CASES["Syn003"], judge, RHO)["provisional"] is True


def test_future_plan_not_scored_now_is_inactive_when_silent_but_harmful_plan_is_charged() -> None:
    case = copy.deepcopy(CASES["Syn002-5"])
    case["decisions"][2]["activation"]["scoredNow"] = False
    silent = score_case(case, {"decisions": {}}, RHO)["decisions"]["D6"]
    assert silent["state"] == "inactive"
    harmful = score_case(case, {"decisions": {"D6": {"recommended": [{"rowId": "D6.2"}]}}}, RHO)["decisions"]["D6"]
    assert [[e["kind"], e["severity"]] for e in harmful["events"]] == [["commission", "severe"]]


@pytest.mark.parametrize("sample", SAMPLES, ids=[f"{s['case']}-{s['label']}" for s in SAMPLES])
def test_action_tags_do_not_change_scores(sample: dict[str, Any]) -> None:
    case = CASES[sample["case"]]
    tagged = copy.deepcopy(case)
    for decision in tagged["decisions"]:
        for index, row in enumerate(decision["recommendations"]):
            row["tags"] = list(RECOMMENDATION_TAGS) if index == 0 else ["none"]
    judge = {"decisions": sample["judge"]}
    assert validation_errors(tagged) == []
    assert score_case(tagged, judge, RHO) == score_case(case, judge, RHO)


def test_scorer_tag_vocabulary_matches_editor() -> None:
    source = (Path(__file__).resolve().parents[1] / "app/lib/answer-table.ts").read_text()
    labels = json.loads(source.split("export const RECOMMENDATION_TAGS = ", 1)[1].split(" as const", 1)[0])
    assert tuple(labels) == RECOMMENDATION_TAGS


def _tags(tags: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(c: dict[str, Any]) -> None:
        _appropriate(c["decisions"][0])["tags"] = tags
    return mutate


def _match(match: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(c: dict[str, Any]) -> None:
        c["decisions"][2]["activation"]["match"] = match
    return mutate


def _usual_care_mild(lower_decisions: bool) -> Callable[[dict[str, Any]], None]:
    def mutate(c: dict[str, Any]) -> None:
        c["usualCare"] = {"harm": "mild"}
        if lower_decisions:
            c["decisions"][1]["harmIfNotAddressedOverride"] = "mild"
            c["decisions"][0]["harmIfNotAddressedOverride"] = "mild"
    return mutate


def test_validation_rejects_malformed_records() -> None:
    malformed: list[tuple[Callable[[dict[str, Any]], Any], str | None]] = [
        (lambda c: _appropriate(c["decisions"][1]).update(score=10), "score must be an integer 1-9"),
        (lambda c: _below7(c["decisions"][1]).update(score=4.5), "score must be an integer 1-9"),
        (lambda c: _below7(c["decisions"][1]).pop("score"), "score must be an integer 1-9"),
        (lambda c: c["decisions"][1].pop("recommendations"), "recommendations must be a list"),
        (lambda c: [r.update(score=6) for r in c["decisions"][1]["recommendations"]],
         "at least one appropriate recommendation (score 7-9) is required"),
        (lambda c: _appropriate(c["decisions"][1]).update(tier="preferred"), "tier is derived"),
        (lambda c: _below7(c["decisions"][1]).update(tier="inappropriate"), "tier is derived"),
        (lambda c: _below7(c["decisions"][1]).update(parts=["a", "b"]), "rows scored 1-6 cannot carry parts"),
        (lambda c: _appropriate(c["decisions"][1]).update(incompleteVersionOf="D5.1"),
         "rows scored 7-9 cannot carry incompleteVersionOf"),
        (lambda c: c["decisions"][1].update(harmIfNotAddressedOverride="none"), "overrides need harmOverrides"),
        (lambda c: c["decisions"][1].update(harmIfDelayedOverride="severe"), None),
        (lambda c: c["decisions"][1].update(harmIfDelayedOverride="uncertain"), "harmIfDelayedOverride must be"),
        (lambda c: c.update(harmOverrides=True) or c["decisions"][1].update(harmIfNotAddressedOverride="uncertain"), "harmIfNotAddressedOverride must be"),
        (lambda c: c.update(harmOverrides=True) or _appropriate(c["decisions"][1]).update(relativeHarmOverride="mild"), "best option has no relative harm"),
        (lambda c: _below7(c["decisions"][1]).update(harmIfRecommendedOverride="none"), "overrides need harmOverrides"),
        (lambda c: c.update(harmOverrides=True) or _below7(c["decisions"][1]).update(harmIfRecommendedOverride="uncertain"),
         "harmIfRecommendedOverride must be"),
        (lambda c: _below7(c["decisions"][2]).update(incompleteVersionOf="D4.1"), "incompleteVersionOf must name an appropriate recommendation"),
        (lambda c: c["decisions"][2]["activation"].update(rows=["D9.9"]), "onlyIf must list existing rows"),
        (lambda c: _appropriate(c["decisions"][2])["parts"].pop(), None),
        (lambda c: _appropriate(c["decisions"][0]).pop("timing"), "need a timing"),
        (lambda c: c["decisions"][0].pop("kind"), "D1 must be the one Follow-up Decision"),
        (lambda c: c["decisions"].append(c["decisions"].pop(0)), "D1 must be the one Follow-up Decision"),
        (lambda c: c["decisions"][1].update(kind="followUp"), "D1 must be the one Follow-up Decision"),
        (lambda c: c["decisions"][0].update(question="What referral is needed?"), "D1 must be the one Follow-up Decision"),
    ]
    cases: list[tuple[str, str, Callable[[dict[str, Any]], Any], str | None, bool]] = [
        # label, fixture, mutation, expected error (None = valid), score_case error must match it
        *[(f"Syn001 malformed {i}: {message or 'valid'}", "Syn001", mutate, message, False)
          for i, (mutate, message) in enumerate(malformed, 1)],
        *[(f"Syn001 tags {tags!r}", "Syn001", _tags(tags), "tags must", True) for tags in [
            None, "medication", ["followup"], ["unknown"], [1], [["diagnostic"]], ["medication", "medication"]]],
        *[(f"Syn001 match {match!r}", "Syn001", _match(match), "condition match must be any or all", True)
          for match in [None, "either", "ALL", True, 1, ["any"]]],
        ("Syn004 self-covering", "Syn004",
         lambda c: _appropriate(c["decisions"][1]).update(alsoTakesCareOf=["D2"]), "alsoTakesCareOf", False),
        ("Syn005 Decision above usual care", "Syn005", _usual_care_mild(False), "exceeds usual-care harm", False),
        ("Syn005 Decisions lowered to usual care", "Syn005", _usual_care_mild(True), None, False),
    ]

    def run(case: tuple[str, str, Callable[[dict[str, Any]], Any], str | None, bool]) -> None:
        _, fixture, mutate, message, raise_matches = case
        record = copy.deepcopy(CASES[fixture])
        mutate(record)
        errors = validation_errors(record)
        if message is None:
            assert errors == []
        else:
            assert any(message in e for e in errors), errors
            with pytest.raises(ValueError, match=message if raise_matches else None):
                score_case(record, {"decisions": {}}, RHO)

    each_case(cases, lambda c: c[0], run)


def _follow_up(decision_id: str, question: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": decision_id, "kind": "followUp", "question": question,
            "activation": {"type": "always"}, "recommendations": rows}


def test_slower_follow_up_is_a_less_preferred_recommendation() -> None:
    case = copy.deepcopy(CASES["Syn001"])
    case["decisions"][0] = _follow_up("D1", "What follow-up or triage is appropriate?", [
        {"id": "D1.O1", "text": "Urgent synthetic follow-up.", "score": 8, "timing": "urgent"},
        {"id": "D1.O2", "text": "Routine synthetic follow-up.", "score": 7, "timing": "routine"},
        {"id": "D1.O3", "text": "No specialist evaluation is needed.", "score": 3},
    ])
    urgent = score_case(case, {"decisions": {"D1": {"recommended": [{"rowId": "D1.O1"}]}}}, RHO)["decisions"]["D1"]
    assert urgent["credit"] == 1.0 and urgent["events"] == []
    routine = score_case(case, {"decisions": {"D1": {"recommended": [{"rowId": "D1.O2"}]}}}, RHO)["decisions"]["D1"]
    assert routine["credit"] == RHO
    assert [[e["kind"], e["severity"]] for e in routine["events"]] == [["relativeHarm", "mild"]]
    refused = score_case(case, {"decisions": {"D1": {"recommended": [{"rowId": "D1.O3"}]}}}, RHO)["decisions"]["D1"]
    assert refused["credit"] == 0.0
    assert [[e["kind"], e["severity"]] for e in refused["events"]] == [["commission", "mild"], ["omission", "moderate"]]


def test_none_need_charges_no_harm_for_silence() -> None:
    case = copy.deepcopy(CASES["Syn004"])
    case["harmOverrides"] = True
    case["decisions"][1]["harmIfNotAddressedOverride"] = "none"
    silent = score_case(case, {"decisions": {}}, RHO)["decisions"]["D2"]
    assert silent["outcome"] == "notMet" and silent["credit"] == 0.0 and silent["events"] == []
    given = score_case(case, {"decisions": {"D2": {"recommended": [{"rowId": "D2.1"}]}}}, RHO)["decisions"]["D2"]
    assert given["outcome"] == "met" and given["events"] == []


def _biologics(scores: tuple[int, ...], overrides: bool = False) -> dict[str, Any]:
    """Syn001 with D4's appropriate recommendations rescored; ranking rules act on scores alone."""
    case = copy.deepcopy(CASES["Syn001"])
    case["harmOverrides"] = overrides
    d4 = case["decisions"][1]
    d4["recommendations"] = [{"id": f"D4.{i + 1}", "text": f"Option {i + 1}.", "score": score}
                             for i, score in enumerate(scores)]
    d4["recommendations"].append({"id": "D4.9", "text": "Combine incompatible actions.", "score": 2})
    case["decisions"][2]["activation"]["rows"] = ["D4.1"]
    return case


def _d4(case: dict[str, Any], rows: list[str], then: str = "fallback") -> dict[str, Any]:
    """D4's result when the response gives `rows`: the first now and the rest as `then`,
    or every row as an alternative."""
    roles = [then if then == "alternative" or i else "first" for i in range(len(rows))]
    judge = {"decisions": {"D4": {"recommended": [{"rowId": r, "role": role} for r, role in zip(rows, roles)]}}}
    return score_case(case, judge, RHO)["decisions"]["D4"]


def _events(result: dict[str, Any]) -> list[list[str]]:
    return [[e["kind"], e["severity"]] for e in result["events"]]


def test_rule4_incomplete_lower_option_charges_residual_omission_and_relative_harm() -> None:
    case = _biologics((9, 7))
    _appropriate(case["decisions"][1], 1)["parts"] = ["Dose", "Monitoring"]
    judge = {"decisions": {"D4": {"recommended": [{"rowId": "D4.2", "partsPresent": ["Dose"]}]}}}
    result = score_case(case, judge, RHO)["decisions"]["D4"]
    assert result["outcome"] == "partly"
    assert _events(result) == [["residualOmission", "moderate"], ["relativeHarm", "moderate"]]


def _second_appropriate(**fields: str) -> Callable[[dict[str, Any]], None]:
    return lambda case: _appropriate(case["decisions"][1], 1).update(**fields)


def _d4_fields(**fields: str) -> Callable[[dict[str, Any]], None]:
    return lambda case: case["decisions"][1].update(**fields)


def _ranked_5(**fields: str) -> Callable[[dict[str, Any]], None]:
    """The 1-6 row rescored to 5, with any of its own fields."""
    return lambda case: _below7(case["decisions"][1]).update(score=5, **fields)


def _ranked_5_and_d4(**fields: str) -> Callable[[dict[str, Any]], None]:
    def edit(case: dict[str, Any]) -> None:
        _below7(case["decisions"][1])["score"] = 5
        case["decisions"][1].update(**fields)
    return edit


def _substitute_has_no_precision(case: dict[str, Any]) -> None:
    judge = {"decisions": {"D4": {"recommended": [{"rowId": "D4.9"}]}}}
    assert score_case(case, judge, RHO)["precision"] == 0.0


UNCERTAIN = ["uncertain", "uncertain"]


def test_d4_ranking_rules() -> None:
    no_edit = None
    cases: list[dict[str, Any]] = [
        # scores, harmOverrides, edit, rows given, role of the later rows, expected outcome / events / last event
        {"label": "rule1 tied best given together", "scores": (9, 9, 7), "edit": no_edit,
         "rows": ["D4.1", "D4.2"], "then": "alternative", "outcome": "met", "events": []},
        {"label": "rule2 best first", "scores": (9, 7), "edit": no_edit, "rows": ["D4.1", "D4.2"], "outcome": "met"},
        {"label": "rule2 lower first", "scores": (9, 7), "edit": no_edit, "rows": ["D4.2", "D4.1"],
         "outcome": "partly", "events": [["relativeHarm", "moderate"]]},
        {"label": "rule2 lower as an alternative", "scores": (9, 7), "edit": no_edit, "rows": ["D4.1", "D4.2"],
         "then": "alternative", "events": [["relativeHarm", "moderate"]]},
        {"label": "rule2 one-point gap", "scores": (9, 8), "edit": no_edit, "rows": ["D4.2"],
         "events": [["relativeHarm", "mild"]]},
        {"label": "rule2 two-point gap", "scores": (9, 7), "edit": no_edit, "rows": ["D4.2"],
         "events": [["relativeHarm", "moderate"]]},
        {"label": "rule2 relative harm override mild", "scores": (9, 7), "overrides": True,
         "edit": _second_appropriate(relativeHarmOverride="mild"), "rows": ["D4.2"],
         "events": [["relativeHarm", "mild"]]},
        {"label": "rule2 relative harm override none", "scores": (9, 7), "overrides": True,
         "edit": _second_appropriate(relativeHarmOverride="none"), "rows": ["D4.2"], "events": []},
        {"label": "best score sets the need", "scores": (9, 7), "edit": no_edit, "rows": [],
         "events": [["omission", "severe"]]},
        {"label": "need override mild", "scores": (9, 7), "overrides": True,
         "edit": _d4_fields(harmIfNotAddressedOverride="mild"), "rows": [], "events": [["omission", "mild"]]},
        {"label": "rule3 ranked row", "scores": (9, 7), "overrides": True, "edit": _ranked_5(), "rows": ["D4.9"],
         "events": [UNCERTAIN, ["omission", "severe"]]},
        {"label": "rule3 ranked row override severe", "scores": (9, 7), "overrides": True,
         "edit": _ranked_5(harmIfRecommendedOverride="severe"), "rows": ["D4.9"],
         "events": [["commission", "severe"], ["omission", "severe"]]},
        {"label": "rule3 ranked row override none", "scores": (9, 7), "overrides": True,
         "edit": _ranked_5(harmIfRecommendedOverride="none"), "rows": ["D4.9"], "events": [["omission", "severe"]]},
        {"label": "decision40 ranked row first", "scores": (8, 7), "edit": _ranked_5(), "rows": ["D4.9", "D4.1"],
         "outcome": "partly", "events": [UNCERTAIN, ["delay", "mild"]]},
        {"label": "decision40 best option first", "scores": (8, 7), "edit": _ranked_5(), "rows": ["D4.1", "D4.9"],
         "outcome": "met"},
        {"label": "decision40 ranked row offered first", "scores": (8, 7), "edit": _ranked_5(),
         "rows": ["D4.9", "D4.1"], "then": "alternative", "outcome": "partly", "events": [UNCERTAIN, ["delay", "mild"]]},
        {"label": "decision40 ranked row as an add-on", "scores": (8, 7), "edit": _ranked_5(),
         "rows": ["D4.1", "D4.9"], "then": "addOn", "outcome": "met", "events": [UNCERTAIN]},
        {"label": "decision40 delay one step below the need", "scores": (9, 7), "edit": _ranked_5(),
         "rows": ["D4.9", "D4.1"], "last_event": ["delay", "moderate"]},
        {"label": "decision40 delay override severe", "scores": (9, 7),
         "edit": _ranked_5_and_d4(harmIfDelayedOverride="severe"), "rows": ["D4.9", "D4.1"],
         "last_event": ["delay", "severe"]},
        {"label": "decision40 delay override none", "scores": (9, 7),
         "edit": _ranked_5_and_d4(harmIfDelayedOverride="none"), "rows": ["D4.9", "D4.1"],
         "outcome": "met", "events": [UNCERTAIN]},
        {"label": "decision41 silent", "scores": (8, 7), "edit": no_edit, "rows": [],
         "events": [["omission", "moderate"]]},
        {"label": "decision41 harmful substitute", "scores": (8, 7), "edit": no_edit, "rows": ["D4.9"],
         "events": [["commission", "moderate"], ["omission", "moderate"]], "check": _substitute_has_no_precision},
    ]

    def run(row: dict[str, Any]) -> None:
        case = _biologics(row["scores"], overrides=row.get("overrides", False))
        if row["edit"] is not None:
            row["edit"](case)
        result = _d4(case, row["rows"], row.get("then", "fallback"))
        if "outcome" in row:
            assert result["outcome"] == row["outcome"]
        if "events" in row:
            assert _events(result) == row["events"]
        if "last_event" in row:
            assert _events(result)[-1] == row["last_event"]
        if "check" in row:
            row["check"](case)

    each_case(cases, lambda c: c["label"], run)


def _syn001_gate(rows: list[str], match: str) -> Callable[[], dict[str, Any]]:
    def build() -> dict[str, Any]:
        case = copy.deepcopy(CASES["Syn001"])
        case["decisions"][2]["activation"] = {"type": "onlyIf", "rows": rows, "match": match}
        return case
    return build


def _biologics_gated_on_d4_2() -> dict[str, Any]:
    case = _biologics((9, 7))
    case["decisions"][2]["activation"]["rows"] = ["D4.2"]
    return case


def _syn001() -> dict[str, Any]:
    return copy.deepcopy(CASES["Syn001"])


def test_d5_activation_state() -> None:
    def given(*rows: tuple[str, str]) -> dict[str, Any]:
        return {"D4": {"recommended": [{"rowId": row, "role": role} for row, role in rows]}}

    every_plan = [("any", ["first", "addOn"], "scored"), ("all", ["first", "addOn"], "scored"),
                  ("any", ["alternative", "alternative"], "scored"), ("all", ["alternative", "alternative"], "inactive"),
                  ("any", ["first", "fallback"], "scored"), ("all", ["first", "fallback"], "inactive"),
                  ("any", ["fallback", "fallback"], "inactive"), ("all", ["fallback", "fallback"], "inactive")]
    all_sources: list[tuple[str, dict[str, Any], str]] = [
        ("any", {"D4": {"recommended": [{"rowId": "D4.1"}]}}, "scored"),
        ("any", {"D1": {"recommended": [{"rowId": "D1.O1"}]}}, "scored"),
        ("all", {"D4": {"recommended": [{"rowId": "D4.1"}]}}, "inactive"),
        ("all", {"D1": {"recommended": [{"rowId": "D1.O1"}]}}, "inactive"),
        ("all", {"D1": {"recommended": [{"rowId": "D1.O1"}]},
                 "D4": {"recommended": [{"rowId": "D4.1"}]}}, "scored"),
        ("any", {"D1": {"recommended": [{"rowId": "D1.O1"}], "contradiction": True},
                 "D4": {"recommended": [{"rowId": "D4.1"}]}}, "scored"),
        ("all", {"D1": {"recommended": [{"rowId": "D1.O1"}], "contradiction": True},
                 "D4": {"recommended": [{"rowId": "D4.1"}]}}, "inactive"),
        ("any", {"D4": {"recommended": [{"rowId": "D4.1"},
                                        {"rowId": "D4.2", "role": "alternative"}]}}, "inactive"),
    ]
    cases: list[tuple[str, Callable[[], dict[str, Any]], dict[str, Any], str]] = [
        *[(f"every plan {match} {'+'.join(roles)}", _syn001_gate(["D4.1", "D4.2"], match),
           given(*zip(["D4.1", "D4.2"], roles)), state) for match, roles, state in every_plan],
        *[(f"all sources {match} {i}", _syn001_gate(["D1.O1", "D4.1"], match), outputs, state)
          for i, (match, outputs, state) in enumerate(all_sources, 1)],
        ("rule6 gate only as the fallback", _biologics_gated_on_d4_2,
         {"D4": {"recommended": [{"rowId": "D4.1"}, {"rowId": "D4.2", "role": "fallback"}]}}, "inactive"),
        ("rule6 gate given now", _biologics_gated_on_d4_2, {"D4": {"recommended": [{"rowId": "D4.2"}]}}, "scored"),
        ("decision42 gate alone", _syn001, {"D4": {"recommended": [{"rowId": "D4.1"}]}}, "scored"),
        ("decision42 gate with an add-on", _syn001,
         {"D4": {"recommended": [{"rowId": "D4.1"}, {"rowId": "D4.4", "role": "addOn"}]}}, "scored"),
        ("decision42 gate as an alternative", _syn001,
         {"D4": {"recommended": [{"rowId": "D4.1", "role": "alternative"}, {"rowId": "D4.2", "role": "alternative"}]}},
         "inactive"),
        ("decision42 gate as the fallback", _syn001,
         {"D4": {"recommended": [{"rowId": "D4.2"}, {"rowId": "D4.1", "role": "fallback"}]}}, "inactive"),
    ]

    def run(case: tuple[str, Callable[[], dict[str, Any]], dict[str, Any], str]) -> None:
        _, build, outputs, state = case
        assert score_case(build(), {"decisions": outputs}, RHO)["decisions"]["D5"]["state"] == state

    each_case(cases, lambda c: c[0], run)


@pytest.mark.parametrize("match", ["any", "all"])
def test_inactive_condition_still_charges_harmful_recommendations(match: str) -> None:
    case = copy.deepcopy(CASES["Syn001"])
    case["decisions"][2]["activation"] = {"type": "onlyIf", "rows": ["D1.O1", "D4.1"], "match": match}
    judge = {"decisions": {
        "D4": {"recommended": [{"rowId": "D4.1", "role": "fallback"}]},
        "D5": {"recommended": [{"rowId": "D5.2"}], "unmatched": [
            {"provisional": {"harm": {"kind": "commission", "severity": "moderate"}}}
        ]},
    }}
    result = score_case(case, judge, RHO)["decisions"]["D5"]
    assert result["state"] == "inactive"
    assert result["credit"] is None
    assert result["provisional"] is True
    assert _events(result) == [["commission", "mild"], ["commission", "moderate"]]


@pytest.mark.parametrize("sample", SAMPLES, ids=[f"{s['case']}-{s['label']}" for s in SAMPLES])
def test_legacy_onlyif_match_defaults_to_any(sample: dict[str, Any]) -> None:
    case = copy.deepcopy(CASES[sample["case"]])
    for decision in case["decisions"]:
        if decision.get("activation", {}).get("type") == "onlyIf":
            decision["activation"]["match"] = "any"
    judge = {"decisions": sample["judge"]}
    assert score_case(case, judge, RHO) == score_case(CASES[sample["case"]], judge, RHO)


def test_onlyif_python_and_editor_scoring_parity() -> None:
    examples: list[dict[str, Any]] = []
    for match in (None, "any", "all"):
        for sources in (["D4.1", "D4.2"], ["D1.O1", "D4.1"]):
            for roles in (["first", "addOn"], ["alternative", "alternative"],
                          ["first", "fallback"], ["fallback", "fallback"]):
                for contradicted in (False, True):
                    case = copy.deepcopy(CASES["Syn001"])
                    case["harmOverrides"] = False
                    case["usualCare"] = {"harm": "severe"}
                    for decision in case["decisions"]:
                        decision.setdefault("activation", {"type": "always"})
                    case["decisions"][2]["activation"] = {"type": "onlyIf", "rows": sources}
                    if match is not None:
                        case["decisions"][2]["activation"]["match"] = match
                    outputs: dict[str, Any] = {}
                    for row, role in zip(sources, roles):
                        source = row.split(".")[0]
                        outputs.setdefault(source, {"recommended": []})["recommended"].append(
                            {"rowId": row, "role": role})
                    if contradicted:
                        outputs[sources[0].split(".")[0]]["contradiction"] = True
                    examples.append({"record": case, "judge": {"decisions": outputs}})
    viewer = Path(__file__).resolve().parents[1] / "app"
    script = """
import { readFileSync } from 'node:fs';
import { scoreAnswerTable } from './lib/answer-score.ts';
const examples = JSON.parse(readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(examples.map(({ record, judge }) => scoreAnswerTable(record, judge, 0.5))));
"""
    result = subprocess.run(["node", "--import", "tsx", "--input-type=module", "-e", script],
                            cwd=viewer, input=json.dumps(examples), text=True, capture_output=True, check=True)
    previews = json.loads(result.stdout)
    assert len(previews) == len(examples)
    for example, preview in zip(examples, previews):
        reference = score_case(example["record"], example["judge"], RHO)
        for decision_id, expected in reference["decisions"].items():
            actual = preview["decisions"][decision_id]
            for field in ("state", "outcome", "credit", "events"):
                assert actual[field] == expected[field], (example, decision_id, field)
        for field in ("worstHarm", "harmCounts"):
            assert preview[field] == reference[field], (example, field)
        for field in ("recall", "precision", "f1"):
            assert preview[field] == pytest.approx(reference[field]), (example, field)


def test_decision41_worst_harm_and_weighted_f1() -> None:
    # Syn001: D1, D4, and D5 each carry a Moderate need (weight 24); D5 is on once the gating action is chosen.
    silent = score_case(CASES["Syn001"], {"decisions": {}}, RHO)
    assert (silent["worstHarm"], silent["recall"], silent["precision"], silent["f1"]) == ("moderate", 0.0, 0.0, 0.0)
    alone = score_case(CASES["Syn001"], {"decisions": {"D4": {"recommended": [{"rowId": "D4.1"}]}}}, RHO)
    assert alone["recall"] == pytest.approx(1 / 3) and alone["precision"] == 1.0 and alone["f1"] == pytest.approx(0.5)
    judge = {"decisions": {"D4": {"recommended": [{"rowId": "D4.1"}, {"rowId": "D4.5", "role": "addOn"}]}}}
    combined = score_case(CASES["Syn001"], judge, RHO)
    assert combined["precision"] == pytest.approx(0.5) and combined["f1"] == pytest.approx(0.4)
    assert combined["harmCounts"] == {"severe": 0, "moderate": 3, "mild": 0, "uncertain": 0, "contradiction": 0}
    assert combined["provisional"] is False


def test_summarize_reports_worst_harm_share_and_mean_f1() -> None:
    results = [score_case(CASES["Syn001"], {"decisions": j}, RHO) for j in (
        {},
        {"D4": {"recommended": [{"rowId": "D4.1"}]}},
    )]
    summary = summarize(results)
    assert summary["responses"] == 2 and summary["worstHarm"]["moderate"] == 2
    assert summary["severeShare"] == 0.0 and summary["meanF1"] == pytest.approx(0.25)


def test_decision42_a_mixed_plan_is_scored_from_what_is_given_now() -> None:
    case = _biologics((9, 7))
    _below7(case["decisions"][1])["score"] = 5
    judge = {"decisions": {"D4": {"recommended": [
        {"rowId": "D4.1"}, {"rowId": "D4.9", "role": "addOn"}, {"rowId": "D4.2", "role": "fallback"}]}}}
    result = score_case(case, judge, RHO)["decisions"]["D4"]
    assert result["outcome"] == "met" and _events(result) == [["uncertain", "uncertain"]]


def test_decision42_rejects_an_unknown_role() -> None:
    with pytest.raises(ValueError, match="role must be one of"):
        score_case(CASES["Syn001"], {"decisions": {"D4": {"recommended": [{"rowId": "D4.1", "role": "preferred"}]}}}, RHO)


def test_decision45_an_extra_is_left_out_of_precision() -> None:
    needed = {"decisions": {"D2": {"recommended": [{"rowId": "D2.O1"}]}}}
    with_extra = {"decisions": {"D2": {"recommended": [{"rowId": "D2.O1"}, {"rowId": "D2.O2", "role": "addOn"}]}}}
    assert score_case(CASES["Syn005"], with_extra, RHO)["precision"] == score_case(CASES["Syn005"], needed, RHO)["precision"]


def test_decision45_does_not_apply_when_the_need_is_none() -> None:
    case = copy.deepcopy(CASES["Syn005"])
    case["decisions"][1]["harmIfNotAddressedOverride"] = "none"
    result = score_case(case, {"decisions": {"D2": {"recommended": [{"rowId": "D2.O2"}]}}}, RHO)["decisions"]["D2"]
    assert result["outcome"] == "partly"


def test_decision47_silence_on_a_none_harm_decision_is_left_out_of_recall() -> None:
    case = copy.deepcopy(CASES["Syn005"])
    judge = {"decisions": {"D1": {"recommended": [{"rowId": "D1.O1"}]},
                           "D2": {"recommended": [{"rowId": "D2.O1"}]}}}
    base = score_case(case, judge, RHO)["recall"]
    case["decisions"].append({"id": "D3", "question": "What additional testing is needed?",
                              "harmIfNotAddressedOverride": "none", "activation": {"type": "always"},
                              "recommendations": [{"id": "D3.O1", "text": "No additional testing is needed.", "score": 8},
                                                  {"id": "D3.O2", "text": "Perform unnecessary test C.", "score": 3}]})
    assert score_case(case, judge, RHO)["recall"] == base == 1.0


def test_decision47_saying_no_additional_testing_leaves_precision_unchanged() -> None:
    base = {"D2": {"recommended": [{"rowId": "D2.O1"}]}}
    padded = {**base, "D4": {"recommended": [{"rowId": "D4.O1"}]}}
    plain = score_case(CASES["Syn006"], {"decisions": base}, RHO)
    extra = score_case(CASES["Syn006"], {"decisions": padded}, RHO)
    assert (extra["precision"], extra["recall"]) == (plain["precision"], plain["recall"])
