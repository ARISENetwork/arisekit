"""table_errors: the app's save validator plus the standard authoring rules."""
from __future__ import annotations

import copy
from collections.abc import Callable

from cases import each_case
from conftest import synthetic_table

from pipeline.answer_table_checks import NO_PRECAUTIONS, PRECAUTIONS, table_errors

FOLLOW_UP = "What follow-up or triage is appropriate?"


def _synthetic_record() -> dict:
    return synthetic_table()


def _decision(rec: dict, question: str) -> dict:
    return next(d for d in rec["decisions"] if d["question"] == question)


def _unchanged(rec: dict) -> None:
    pass


def _empty_question(rec: dict) -> None:
    rec["decisions"][1]["question"] = ""


def _single_mode(rec: dict) -> None:
    rec["harmOverrides"] = False


def _without_precautions(rec: dict) -> None:
    rec["decisions"] = [d for d in rec["decisions"] if d["question"] != PRECAUTIONS]


def _made_future(question: str) -> Callable[[dict], None]:
    def mutate(rec: dict) -> None:
        _decision(rec, question)["activation"] = {"type": "future", "trigger": "A synthetic future event",
                                                  "scoredNow": False}
    return mutate


def _precautions_answer(text: str, harm: str) -> Callable[[dict], None]:
    def mutate(rec: dict) -> None:
        decision = _decision(rec, PRECAUTIONS)
        decision["recommendations"] = [{"id": f"{decision['id']}.O1", "text": text, "score": 9}]
        decision["harmIfNotAddressedOverride"] = harm
    return mutate


def _future_without_scored_now(rec: dict) -> None:
    future = next(d for d in rec["decisions"] if d["activation"]["type"] == "future")
    del future["activation"]["scoredNow"]


def test_table_errors_cases() -> None:
    cases: list[tuple[str, Callable[[dict], None], Callable[[str], bool] | None]] = [
        ("synthetic record", _unchanged, None),
        ("empty question", _empty_question, lambda e: e.startswith("validator:")),
        ("not dual mode", _single_mode, lambda e: "not dual mode" in e),
        ("missing return precautions", _without_precautions,
         lambda e: "missing standard Decision" in e and PRECAUTIONS in e),
        ("future follow-up", _made_future(FOLLOW_UP), lambda e: "must always be active" in e),
        ("future return precautions", _made_future(PRECAUTIONS), lambda e: "must always be active" in e),
        ("no specific precautions with harm none", _precautions_answer(NO_PRECAUTIONS, "none"), None),
        ("no specific precautions with harm mild", _precautions_answer(NO_PRECAUTIONS, "mild"),
         lambda e: "no specific precautions requires harm none" in e),
        ("another no-action host", _precautions_answer("No further care is needed.", "none"),
         lambda e: "ad hoc host Decision remains" in e),
        ("future without scoredNow", _future_without_scored_now,
         lambda e: e.startswith("scorer:") and "scoredNow" in e),
    ]

    def run(case: tuple[str, Callable[[dict], None], Callable[[str], bool] | None]) -> None:
        _, mutate, expected = case
        rec = _synthetic_record()
        mutate(rec)
        before = copy.deepcopy(rec)
        errors = table_errors(rec)
        assert rec == before
        assert all(e.startswith(("validator:", "scorer:", "standard:")) for e in errors)
        if expected is None:
            assert errors == []
        else:
            assert any(expected(e) for e in errors)

    each_case(cases, lambda c: c[0], run)
