"""Score stage: coverage by model and (id, trial), rubric identity, offRubric flag, report."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from cases import each_case
from conftest import seed_case, synthetic_table

from pipeline.e2e import score as sc
from pipeline.e2e.project import Project
from arisekit.common.hashing import json_sha256, sha256
from arisekit.common.jsonio import append_jsonl, read_jsonl

HASH = json_sha256(synthetic_table())
OK = {"id": "Syn002", "trial": 1, "response": "Order an Check A.", "runtime": 1, "usage": None}
JUDGED = {"id": "Syn002", "trial": 1, "caseId": "Syn002", "rubric": "run1", "rubric_sha256": HASH,
          "status": "pass", "provenance": {"backend": "openrouter", "model": "openai/gpt-6-astra"},
          "judge": {"decisions": {"D2": {"recommended": [
              {"rowId": "D2.O1", "role": "first", "evidence": "Order an Check A.", "partsPresent": ["Check A"]}]}},
              "offRubric": [{"evidence": "x", "actionable": True, "harm": "mild"}]}}


@pytest.mark.parametrize("off,expected", [
    ([], False),
    ([{"evidence": "x", "actionable": True, "harm": "none"}], False),
    ([{"evidence": "x", "actionable": False, "harm": "severe"}], False),
    ([{"evidence": "x", "actionable": True, "harm": "mild"}], True),
])
def test_offrubric_provisional(off: list, expected: bool) -> None:
    assert sc.offrubric_provisional({"decisions": {}, "offRubric": off}) is expected


def _setup(tmp_path: Path, response: dict = OK, judged: dict | None = JUDGED, models: list[str] | None = None) -> Path:
    seed_case(tmp_path)
    Project(tmp_path).update_provenance(models=models or ["m"])
    append_jsonl(tmp_path / "results" / "responses" / "m.jsonl", response)
    if judged:
        append_jsonl(tmp_path / "results" / "judge" / "m.jsonl", {
            "response_sha256": sha256(OK["response"]),
            "case_presentation_sha256": sha256(Project(tmp_path).case("Syn002")["presentation"]),
            **judged})
    return tmp_path


def test_score_writes_scored_and_report(tmp_path: Path) -> None:
    report, problems = sc.score(_setup(tmp_path))
    assert problems == []
    [line] = (tmp_path / "results" / "m_scored.jsonl").read_text().splitlines()
    rec = json.loads(line)
    assert rec["provisional"] is True and rec["offRubricProvisional"] is True
    assert rec["rubric_sha256"] == HASH
    assert rec["judgment_sha256"] == json_sha256(JUDGED["judge"])
    text = report.read_text()
    assert "LLM-provisional" in text and "not frozen" in text and "excludes off-rubric harm" in text
    assert "| m |" in text
    assert "Rubric: run1. Judge: openrouter/openai/gpt-6-astra." in text


def _write_reviewed(root: Path, record: dict) -> None:
    Project(root).artifact("Syn002", "reviewed-dw").parent.mkdir(parents=True, exist_ok=True)
    Project(root).artifact("Syn002", "reviewed-dw").write_text(json.dumps({
        "record": record, "basedOn": {"version": "run1", "sha256": HASH}, "reviewer": "dw",
        "timing": {}, "savedAt": "2026-09-28T00:00:00Z"}))
    Project(root).artifact("Syn002", "reviewed-dw", "status.json").write_text(json.dumps({"status": "pass", "errors": []}))


def test_reviewed_rubric_scores_then_goes_stale_when_edited(tmp_path: Path) -> None:
    reference = synthetic_table()
    root = _setup(tmp_path, judged={**JUDGED, "rubric": "reviewed-dw"})
    _write_reviewed(root, reference)
    report, problems = sc.score(root)
    assert report is not None and problems == []
    _write_reviewed(root, {**reference, "decisions": reference["decisions"][:-1]})
    report, problems = sc.score(root)
    assert report is None and any("stale judgment" in p and "reviewed-dw" in p for p in problems)


def make_synthetic_run(tmp_path: Path) -> tuple[Path, dict]:
    """A self-contained nonclinical case with one recommendation."""
    case = {"presentation": "Synthetic café case.\n  Context.", "recommendations": "Action A."}
    table = {"caseId": "Test001", "usualCare": {"harm": "mild"}, "decisions": [
        {"id": "D1", "kind": "followUp", "question": "What follow-up or triage is appropriate?",
         "recommendations": [{"id": "D1.O1", "text": "Action A.", "score": 7, "timing": "routine"}]}]}
    (tmp_path / "cases").mkdir()
    (tmp_path / "cases" / "Test001.json").write_text(json.dumps(case))
    append_jsonl(tmp_path / "items.jsonl", {"id": "Test001", "metadata": {"base_id": "Test001"}})
    Project(tmp_path).update_provenance(models=["m"])
    append_jsonl(tmp_path / "results" / "responses" / "m.jsonl",
                 {"id": "Test001", "trial": 1, "response": "Action A.\n"})
    Project(tmp_path).artifact("Test001", "run1").parent.mkdir()
    Project(tmp_path).artifact("Test001", "run1").write_text(json.dumps(table))
    Project(tmp_path).artifact("Test001", "run1", "status.json").write_text('{"status":"pass"}')
    judged = {"id": "Test001", "trial": 1, "caseId": "Test001", "rubric": "run1", "status": "pass",
              "rubric_sha256": json_sha256(table), "response_sha256": sha256("Action A.\n"),
              "case_presentation_sha256": sha256(case["presentation"]),
              "judge": {"decisions": {"D1": {"recommended": [
                  {"rowId": "D1.O1", "role": "first", "evidence": "Action A."}]}}, "offRubric": []}}
    append_jsonl(tmp_path / "results" / "judge" / "m.jsonl", judged)
    return tmp_path, judged


@pytest.fixture
def synthetic_run(tmp_path: Path) -> tuple[Path, dict]:
    return make_synthetic_run(tmp_path)


def synthetic_project(root: Path) -> tuple[Path, dict]:
    """The same one-recommendation case with an unterminated response and a plain presentation."""
    case = {"presentation": "Invented workflow example.", "recommendations": "Action A."}
    table = {"caseId": "Test001", "usualCare": {"harm": "mild"}, "decisions": [
        {"id": "D1", "kind": "followUp", "question": "What follow-up or triage is appropriate?",
         "recommendations": [{"id": "D1.O1", "text": "Action A.", "score": 7,
                              "timing": "routine"}]}]}
    (root / "cases").mkdir()
    (root / "cases" / "Test001.json").write_text(json.dumps(case))
    append_jsonl(root / "items.jsonl", {"id": "Test001", "metadata": {"base_id": "Test001"}})
    Project(root).update_provenance(models=["m"])
    append_jsonl(root / "results" / "responses" / "m.jsonl",
                 {"id": "Test001", "trial": 1, "response": "Action A."})
    Project(root).artifact("Test001", "run1").parent.mkdir()
    Project(root).artifact("Test001", "run1").write_text(json.dumps(table))
    Project(root).artifact("Test001", "run1", "status.json").write_text('{"status":"pass"}')
    record = {"id": "Test001", "trial": 1, "caseId": "Test001", "rubric": "run1", "status": "pass",
              "rubric_sha256": json_sha256(table), "response_sha256": sha256("Action A."),
              "case_presentation_sha256": sha256(case["presentation"]),
              "judge": {"decisions": {"D1": {"recommended": [
                  {"rowId": "D1.O1", "role": "first", "evidence": "Action A."}]}}, "offRubric": []}}
    append_jsonl(root / "results" / "judge" / "m.jsonl", record)
    return root, record


def _with_items(count: int) -> Callable[[Path], Path]:
    def setup(root: Path) -> Path:
        synthetic_project(root)
        item = read_jsonl(root / "items.jsonl")[0]
        (root / "items.jsonl").write_text("".join(json.dumps(item) + "\n" for _ in range(count)))
        return root
    return setup


def _with_undeclared_trial(root: Path) -> Path:
    synthetic_project(root)
    append_jsonl(root / "results" / "responses" / "m.jsonl", {"id": "Test001", "trial": 2, "response": "Action B."})
    return root


def test_incomplete_or_stale_inputs_block_the_report(tmp_path: Path) -> None:
    clean, _ = synthetic_project(tmp_path)
    report, problems = sc.score(clean)
    assert report is not None and problems == []
    assert len(read_jsonl(clean / "results" / "m_scored.jsonl")) == 1

    cases: list[dict[str, Any]] = [
        {"label": "failed inference", "partial_report": True, "needles": ["no response"],
         "setup": lambda root: _setup(root, response={**OK, "response": None, "error": "429"}, judged=None)},
        {"label": "missing declared model", "needles": ["openrouter-google-x", "no response for"],
         "setup": lambda root: _setup(root, models=["m", "openrouter/google/x"])},
        {"label": "stale rubric", "needles": ["stale"],
         "setup": lambda root: _setup(root, judged={**JUDGED, "rubric_sha256": "0" * 64})},
        {"label": "no items", "needles": [], "setup": _with_items(0)},
        {"label": "duplicate item", "needles": [], "setup": _with_items(2)},
        {"label": "undeclared second trial", "needles": ["unexpected response"], "setup": _with_undeclared_trial},
    ]

    def run(case: dict[str, Any]) -> None:
        root = tmp_path / case["label"].replace(" ", "-")
        root.mkdir()
        root = case["setup"](root)
        report, problems = sc.score(root)
        assert report is None and problems
        if case["needles"]:
            assert any(all(needle in p for needle in case["needles"]) for p in problems)
        assert not (root / "results" / "report.md").exists()
        assert not (root / "results" / "m_scored.jsonl").exists()
        if case.get("partial_report"):
            report, problems = sc.score(root, allow_partial=True)
            assert report is not None and problems

    each_case(cases, lambda c: c["label"], run)


@pytest.mark.parametrize("field", ["response_sha256", "case_presentation_sha256"])
def test_missing_input_binding_fails_closed(synthetic_run: tuple[Path, dict], field: str) -> None:
    root, judged = synthetic_run
    del judged[field]
    path = root / "results" / "judge" / "m.jsonl"
    path.write_text(json.dumps(judged) + "\n")
    before = path.read_bytes()
    report, problems = sc.score(root)
    assert report is None and any(field in p for p in problems)
    assert path.read_bytes() == before
    report, problems = sc.score(root, allow_partial=True)
    assert report is not None and problems
    assert (root / "results" / "m_scored.jsonl").read_text() == ""


def _rewrite_response(root: Path, judged: dict) -> None:
    path = root / "results" / "responses" / "m.jsonl"
    record = json.loads(path.read_text())
    record["response"] = record["response"].rstrip()
    path.write_text(json.dumps(record) + "\n")


def _rewrite_presentation(root: Path, judged: dict) -> None:
    path = root / "cases" / "Test001.json"
    record = json.loads(path.read_text())
    record["presentation"] += " "
    path.write_text(json.dumps(record) + "\n")


def _add_second_trial_with_another_response(root: Path, judged: dict) -> None:
    Project(root).update_provenance(trials=2)
    append_jsonl(root / "results" / "responses" / "m.jsonl",
                 {"id": "Test001", "trial": 2, "response": "Action B."})
    append_jsonl(root / "results" / "judge" / "m.jsonl", {**judged, "trial": 2})


def test_changed_input_bytes_block_old_judgment(tmp_path: Path) -> None:
    cases: list[tuple[str, Callable[[Path, dict], None], str]] = [
        ("response", _rewrite_response, "response_sha256"),
        ("case presentation", _rewrite_presentation, "case_presentation_sha256"),
        ("second trial response", _add_second_trial_with_another_response, "response_sha256"),
    ]

    def run(case: tuple[str, Callable[[Path, dict], None], str]) -> None:
        label, change, needle = case
        root = tmp_path / label.replace(" ", "-")
        root.mkdir()
        root, judged = make_synthetic_run(root)
        assert sc.score(root)[1] == []
        change(root, judged)
        report, problems = sc.score(root)
        assert report is None and any(needle in p for p in problems)

    each_case(cases, lambda c: c[0], run)


@pytest.mark.parametrize("reviewer", ["dw", "wrong"])
def test_report_uses_saved_review_provenance_for_mixed_tables(
    synthetic_run: tuple[Path, dict], reviewer: str,
) -> None:
    root, judged = synthetic_run
    table = Project(root).table("Test001", "run1")
    Project(root).artifact("Test001", "reviewed-dw").write_text(json.dumps({
        "record": table, "reviewer": reviewer, "savedAt": "2026-10-04T12:00:00Z",
        "basedOn": {"version": "run1", "sha256": json_sha256(table)}}))
    Project(root).artifact("Test001", "reviewed-dw", "status.json").write_text('{"status":"pass"}')
    Project(root).update_provenance(models=["m", "n"])
    (root / "results" / "responses" / "n.jsonl").write_bytes(
        (root / "results" / "responses" / "m.jsonl").read_bytes())
    append_jsonl(root / "results" / "judge" / "n.jsonl", {**judged, "rubric": "reviewed-dw"})
    report, problems = sc.score(root)
    assert report is not None and problems == []
    text = report.read_text()
    count = int(reviewer == "dw")
    assert f"Tables with passing saved review provenance: {count}" in text
    assert f"without verified saved review provenance: {2 - count}" in text
    assert "Judgments are LLM-provisional" in text
    assert "does not establish clinical acceptance" in text
    assert "No clinician has reviewed" not in text


def test_failed_review_status_is_not_scored(synthetic_run: tuple[Path, dict]) -> None:
    root, judged = synthetic_run
    Project(root).artifact("Test001", "reviewed-dw", "status.json").write_text('{"status":"failed"}')
    (root / "results" / "judge" / "m.jsonl").write_text(json.dumps({**judged, "rubric": "reviewed-dw"}))
    with pytest.raises(ValueError, match="reviewed-dw failed validation"):
        sc.score(root)


@pytest.mark.parametrize("complete", [True, False])
def test_score_requires_every_declared_trial(synthetic_run: tuple[Path, dict], complete: bool) -> None:
    root, judged = synthetic_run
    Project(root).update_provenance(trials=3)
    for trial in range(2, 4 if complete else 3):
        append_jsonl(root / "results" / "responses" / "m.jsonl",
                     {"id": "Test001", "trial": trial, "response": "Action A.\n"})
        append_jsonl(root / "results" / "judge" / "m.jsonl", {**judged, "trial": trial})
    report, problems = sc.score(root)
    assert (report is not None) is complete
    assert bool(problems) is not complete
    if complete:
        records = read_jsonl(root / "results" / "m_scored.jsonl")
        assert [record["trial"] for record in records] == [1, 2, 3]
        assert len({record["f1"] for record in records}) == 1
    else:
        assert any("no response" in problem and "3" in problem for problem in problems)


@pytest.mark.parametrize("count", [0, -1, True, 2.0, "2", None, []])
@pytest.mark.parametrize("partial", [True, False])
def test_invalid_declared_count_never_writes(
    synthetic_run: tuple[Path, dict], count: object, partial: bool,
) -> None:
    root, _ = synthetic_run
    Project(root).update_provenance(trials=count)
    report, problems = sc.score(root, allow_partial=partial)
    assert report is None and any("project trials" in problem for problem in problems)
    assert not (root / "results" / "report.md").exists()
    assert not (root / "results" / "m_scored.jsonl").exists()


def _judgments(*records: dict) -> Callable[[Path, dict], None]:
    def change(root: Path, judged: dict) -> None:
        (root / "results" / "judge" / "m.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    return change


def _duplicate_judgment(root: Path, judged: dict) -> None:
    append_jsonl(root / "results" / "judge" / "m.jsonl", judged)


def _conflicting_duplicates(unmatched_first: bool) -> Callable[[Path, dict], None]:
    def change(root: Path, judged: dict) -> None:
        unmatched = {**judged, "judge": {"decisions": {}, "offRubric": []}}
        _judgments(*([unmatched, judged] if unmatched_first else [judged, unmatched]))(root, judged)
    return change


def _error_pass_then_clean(root: Path, judged: dict) -> None:
    flawed = {**judged, "errors": ["synthetic error"], "judge": {"decisions": {}, "offRubric": []}}
    _judgments(flawed, judged)(root, judged)


def _duplicate_response(root: Path, judged: dict) -> None:
    append_jsonl(root / "results" / "responses" / "m.jsonl", {"id": "Test001", "trial": 1, "response": "Action A.\n"})


def _invalid_pair(trial: object) -> Callable[[Path, dict], None]:
    def change(root: Path, judged: dict) -> None:
        append_jsonl(root / "results" / "responses" / "m.jsonl",
                     {"id": "Test001", "trial": trial, "response": "Action A.\n"})
        append_jsonl(root / "results" / "judge" / "m.jsonl", {**judged, "trial": trial})
    return change


def _error_bearing_judgment(root: Path, judged: dict) -> None:
    _judgments({**judged, "errors": ["synthetic error"]})(root, judged)


def _bound_to_another_case(root: Path, judged: dict) -> None:
    other = {"caseId": "Test002", "usualCare": {"harm": "severe"}, "decisions": [
        {"id": "D1", "kind": "followUp", "question": "What follow-up or triage is appropriate?",
         "recommendations": [{"id": "D1.O1", "text": "Action B.", "score": 7, "timing": "routine"}]}]}
    project = Project(root)
    project.artifact("Test002", "run1").write_text(json.dumps(other))
    project.artifact("Test002", "run1", "status.json").write_text('{"status":"pass"}')
    _judgments({**judged, "caseId": "Test002", "rubric_sha256": json_sha256(other)})(root, judged)


def test_partial_report_excludes_bad_pairs(tmp_path: Path) -> None:
    cases: list[tuple[str, Callable[[Path, dict], None], list[str], list[int]]] = [
        ("duplicate judgment", _duplicate_judgment, ["duplicate judgment"], []),
        ("conflicting duplicates, matched first", _conflicting_duplicates(False), ["duplicate judgment"], []),
        ("conflicting duplicates, unmatched first", _conflicting_duplicates(True), ["duplicate judgment"], []),
        ("error-bearing pass and clean duplicate", _error_pass_then_clean,
         ["duplicate judgment", "failed or unresolved"], []),
        ("duplicate response", _duplicate_response, ["duplicate response"], []),
        *[(f"invalid trial {trial!r}", _invalid_pair(trial), [], [1]) for trial in [True, 1.0, "1", [], 2]],
        ("error-bearing judgment", _error_bearing_judgment, ["failed or unresolved"], []),
        ("judgment bound to another case", _bound_to_another_case, ["case identity changed"], []),
    ]

    def run(case: tuple[str, Callable[[Path, dict], None], list[str], list[int]]) -> None:
        _, change, needles, scored = case
        root = tmp_path / f"row{cases.index(case)}"
        root.mkdir()
        root, judged = make_synthetic_run(root)
        change(root, judged)
        report, problems = sc.score(root, allow_partial=True)
        assert report is not None and problems
        for needle in needles:
            assert any(needle in problem for problem in problems)
        assert [record["trial"] for record in read_jsonl(root / "results" / "m_scored.jsonl")] == scored

    each_case(cases, lambda c: c[0], run)
