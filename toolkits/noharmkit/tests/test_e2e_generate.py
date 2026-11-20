"""Generate stage: blind prompt, parallel runs, pass and failed records."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from cases import each_case
from conftest import seed_case, synthetic_table, tagged_synthetic_table
from jsonschema import Draft202012Validator, ValidationError

from pipeline import backends, skillrun
from pipeline.answer_table_checks import PRECAUTIONS, TESTING, TREATMENT, table_errors
from pipeline.e2e import committee as cm
from pipeline.e2e import generate as gen
from pipeline.e2e.project import Project
from pipeline.skillrun import skill_file
from arisekit.common.hashing import json_sha256
from arisekit.common.jsonio import read_json

SYNTHETIC_TABLE = tagged_synthetic_table()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    seed_case(tmp_path, with_table=False)
    return tmp_path


def gate(root: Path, table: dict[str, Any]) -> list[str]:
    """Generation.check for the table's case, seeded from the synthetic case."""
    case_file = root / "cases" / f"{table['caseId']}.json"
    if not case_file.exists():
        case_file.write_text((root / "cases/Syn002.json").read_text())
    return gen.Generation(Project(root), table["caseId"], "subscription", "opus", None, {}).check(table)


@pytest.mark.parametrize("errors", [
    "- Mild: Unnecessary test\n- Moderate: Wrong treatment\n- Severe: Missing safety instructions",
    [{"text": "Wrong treatment", "harm": "moderate"}],
])
def test_prompt_is_blind_and_includes_supplied_errors(root: Path, errors: Any) -> None:
    project = Project(root)
    case = {**project.case("Syn002"), "errors": errors,
            "response": "CANDIDATE_RESPONSE_CANARY", "judge": "JUDGE_CANARY"}
    (root / "cases/Syn002.json").write_text(json.dumps(case))
    variables = gen.Generation(project, "Syn002", "subscription", "opus", None, {}).variables
    prompt = skillrun.render(skill_file(gen.SKILL, "prompt.md").read_text(), variables)
    assert "A synthetic task needs a plan." in prompt
    assert (errors if isinstance(errors, str) else json.dumps(errors, ensure_ascii=False)) in prompt
    assert SYNTHETIC_TABLE["decisions"][1]["recommendations"][0]["text"] not in prompt
    assert "CANDIDATE_RESPONSE_CANARY" not in prompt and "JUDGE_CANARY" not in prompt


def test_authoring_example_passes_the_generation_gate(root: Path) -> None:
    example = json.loads(gen.GUIDE.read_text().split("```json\n", 1)[1].split("```", 1)[0])
    Draft202012Validator(read_json(skill_file(gen.SKILL, "schema.json"))).validate(example)
    assert gate(root, example) == []


def _row_tags(tags: list[str]) -> Callable[[], dict[str, Any]]:
    def build() -> dict[str, Any]:
        table = tagged_synthetic_table()
        table["decisions"][0]["recommendations"][0]["tags"] = tags
        return table
    return build


def _without(question: str) -> Callable[[], dict[str, Any]]:
    def build() -> dict[str, Any]:
        table = tagged_synthetic_table()
        table["decisions"] = [d for d in table["decisions"] if d["question"] != question]
        return table
    return build


def test_generation_gate_cases(root: Path) -> None:
    row_id = tagged_synthetic_table()["decisions"][0]["recommendations"][0]["id"]
    case_id = tagged_synthetic_table()["caseId"]
    untagged = "must include descriptive action tags"
    cases: list[tuple[str, Callable[[], dict[str, Any]], bool, Callable[[list[str]], bool]]] = [
        # older untagged rubrics stay valid for review and scoring
        ("untagged table", synthetic_table, True, lambda errors: all(untagged in e for e in errors)),
        ("empty tags", _row_tags([]), False, lambda errors: errors == [
            f"{row_id}: new recommendations must include descriptive action tags (use None for explicit no-action advice)"]),
        ("tags none", _row_tags(["none"]), False, lambda errors: errors == []),
        ("missing testing", _without(TESTING), True,
         lambda errors: errors == [f"{case_id}: missing standard Decision {TESTING!r}"]),
        ("missing treatment", _without(TREATMENT), True,
         lambda errors: errors == [f"{case_id}: missing standard Decision {TREATMENT!r}"]),
    ]

    def run(case: tuple[str, Callable[[], dict[str, Any]], bool, Callable[[list[str]], bool]]) -> None:
        _, build, saves, expected = case
        table = build()
        if saves:
            assert table_errors(table) == []
        assert expected(gate(root, table))

    each_case(cases, lambda c: c[0], run)


@pytest.mark.parametrize("match,valid", [("any", True), ("all", True), (None, True),
                                         ("either", False)])
def test_generation_schema_condition_modes(root: Path, match: Any, valid: bool) -> None:
    table = tagged_synthetic_table()
    decision = table["decisions"][1]
    decision["activation"] = {"type": "onlyIf", "rows": ["D1.O1"], **({} if match is None and valid else {"match": match})}
    decision["recommendations"][0]["tags"] = ["diagnostic", "none"]
    validator = Draft202012Validator(read_json(skill_file(gen.SKILL, "schema.json")))
    if valid:
        validator.validate(table)
        assert gate(root, table) == []
    else:
        with pytest.raises(ValidationError):
            validator.validate(table)


def test_gate_failure_keeps_draft_raw_and_errors(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    incomplete = json.loads(json.dumps(SYNTHETIC_TABLE))
    incomplete["decisions"] = [d for d in incomplete["decisions"] if d["question"] != PRECAUTIONS]
    raw = json.dumps(incomplete)
    monkeypatch.setattr(backends, "call", lambda backend, model, *a, **kw: backends.CallResult(raw, {"model": model}))
    assert gen.generate(root, "Syn002", runs=1, backend="codex", model="test-model", workers=1) == ["failed"]
    status = Project(root).status("Syn002", "run1")
    assert any("missing standard Decision" in e and PRECAUTIONS in e for e in status["errors"])
    assert read_json(Project(root).artifact("Syn002", "run1")) == incomplete
    assert Project(root).artifact("Syn002", "run1", "raw.txt").read_text() == raw


def test_runs_write_pass_and_failed(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    outcomes = iter([
        skillrun.SkillOutcome("pass", SYNTHETIC_TABLE, "raw1", [], {"model": "m"}),
        skillrun.SkillOutcome("failed", None, "garbage", ["parse: no JSON"], {"model": "m"}),
    ])
    seen: list[dict] = []

    def fake_run_skill(name: str, variables: dict, backend: str, model: str, **kw: Any) -> Any:
        assert name == gen.SKILL
        seen.append(kw)
        return next(outcomes)

    monkeypatch.setattr(gen, "run_skill", fake_run_skill)
    monkeypatch.setattr(gen.committee_module, "rate_table", lambda *a, **k: pytest.fail("committee must not run"))
    statuses = gen.generate(root, "Syn002", runs=2, backend="subscription", model="opus", workers=1)
    assert statuses == ["pass", "failed"]
    assert "check" in seen[0]
    assert json.loads(Project(root).artifact("Syn002", "run1").read_text())["caseId"] == "Syn002"
    assert json.loads(Project(root).artifact("Syn002", "run1").read_text()) == SYNTHETIC_TABLE
    assert not Project(root).artifact("Syn002", "run1", "ratings.json").exists()
    assert not Project(root).artifact("Syn002", "run2").exists()
    s2 = json.loads(Project(root).artifact("Syn002", "run2", "status.json").read_text())
    assert s2["status"] == "failed" and s2["errors"] == ["parse: no JSON"]
    assert (root / "answer-tables" / "Syn002.run2.raw.txt").read_text() == "garbage"


def test_passed_runs_are_skipped_and_others_generated(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    calls: list[str] = []

    def fake_run_skill(name: str, variables: dict, backend: str, model: str, **kw: Any) -> Any:
        calls.append(name)
        return skillrun.SkillOutcome("pass", SYNTHETIC_TABLE, "raw", [], {"model": "m"})

    monkeypatch.setattr(gen, "run_skill", fake_run_skill)
    gen.generate(root, "Syn002", runs=1, backend="subscription", model="opus", workers=1)
    original = Project(root).artifact("Syn002", "run1").read_bytes()
    calls.clear()
    statuses = gen.generate(root, "Syn002", runs=2, backend="subscription", model="opus", workers=1)
    assert statuses == ["pass", "pass"] and len(calls) == 1
    assert Project(root).artifact("Syn002", "run1").read_bytes() == original
    assert json.loads(Project(root).artifact("Syn002", "run2").read_text())["caseId"] == "Syn002"


COMMITTEE = [{"backend": "subscription", "model": "opus"}, {"backend": "openrouter", "model": "a"},
             {"backend": "openrouter", "model": "b"}]


def _ratings(table: dict, *harms: dict[str, str] | None) -> dict:
    """A committee record built by the real aggregate from one output per rater (None = failed rater)."""
    raters = []
    for i, h in enumerate(harms):
        out = None if h is None else {
            "usualCare": {"harm": h.get("usualCare", "mild"), "reason": "r"},
            "decisions": {d["id"]: {"harm": h.get(d["id"], "mild"), "reason": "r"}
                          for d in cm.rated_decisions(table)}}
        raters.append({"rater": i, "status": "failed" if out is None else "pass", "output": out,
                       "raw": None, "errors": [] if out else ["call: down"], "provenance": {}})
    return cm.aggregate(COMMITTEE, raters, table)


def _draft(monkeypatch: pytest.MonkeyPatch, outcome: skillrun.SkillOutcome) -> None:
    def fake_run_skill(name: str, variables: dict, backend: str, model: str, **kw: Any) -> Any:
        assert name == gen.SKILL and "check" not in kw  # the gate runs after the merge
        return outcome
    monkeypatch.setattr(gen, "run_skill", fake_run_skill)


def test_committee_values_reach_the_gate(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    _draft(monkeypatch, skillrun.SkillOutcome("pass", SYNTHETIC_TABLE, "raw", [], {"model": "m"}))
    seen: list[dict] = []

    def fake_rate_table(case: dict, table: dict, committee: list) -> dict:
        seen.append(table)
        return _ratings(table, {"D2": "moderate"}, {"D2": "moderate", "D5": "severe"}, {"D2": "severe"})

    monkeypatch.setattr(gen.committee_module, "rate_table", fake_rate_table)
    statuses = gen.generate(root, "Syn002", runs=1, backend="subscription", model="opus",
                            workers=1, committee=COMMITTEE)
    assert statuses == ["pass"]
    assert seen[0] == SYNTHETIC_TABLE
    table = json.loads(Project(root).artifact("Syn002", "run1").read_text())
    by_id = {d["id"]: d for d in table["decisions"]}
    assert by_id["D2"]["harmIfNotAddressedOverride"] == "moderate"
    assert by_id["D5"]["harmIfNotAddressedOverride"] == "moderate"  # votes mild, severe, mild: mean 1.67
    assert by_id["D11"]["harmIfNotAddressedOverride"] == "none"
    assert table["usualCare"]["harm"] == "moderate"  # the cap raised it, so the standard cap rule passes
    ratings = json.loads(Project(root).artifact("Syn002", "run1", "ratings.json").read_text())
    assert ratings["capAdjustment"] == {"from": "mild", "to": "moderate", "decision": "D2"}
    assert ratings["decisions"]["D2"]["generator"] == "mild"
    assert ratings["draft_sha256"] == json_sha256(SYNTHETIC_TABLE)  # the draft the committee rated
    assert ratings["table_sha256"] == json_sha256(table)  # the merged table on disk, which the viewer hashes
    assert ratings["table_sha256"] != ratings["draft_sha256"]


def test_failed_draft_skips_the_committee(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    _draft(monkeypatch, skillrun.SkillOutcome("failed", None, "garbage", ["parse: no JSON"], {}))
    monkeypatch.setattr(gen.committee_module, "rate_table", lambda *a, **k: pytest.fail("committee must not run"))
    assert gen.generate(root, "Syn002", runs=1, backend="subscription", model="opus",
                        workers=1, committee=COMMITTEE) == ["failed"]
    assert not Project(root).artifact("Syn002", "run1", "ratings.json").exists()


def _quorum_failure_is_recorded(root: Path) -> None:
    assert json.loads(Project(root).artifact("Syn002", "run1").read_text()) == SYNTHETIC_TABLE
    assert json.loads(Project(root).artifact("Syn002", "run1", "ratings.json").read_text())["status"] == "failed"
    ratings = json.loads(Project(root).artifact("Syn002", "run1", "ratings.json").read_text())
    assert ratings["table_sha256"] == ratings["draft_sha256"] == json_sha256(SYNTHETIC_TABLE)


def test_committee_run_failures_are_saved(tmp_path: Path) -> None:
    broken = json.loads(json.dumps(SYNTHETIC_TABLE))
    broken["decisions"][5]["recommendations"] = []  # D6: no override, so its harm is derived from the appropriate rows
    cases: list[dict[str, Any]] = [
        {"label": "gate failure on the merged table", "draft": dict(SYNTHETIC_TABLE, caseId="Syn003"),
         "provenance": {}, "raters": ({}, {}, {}), "errors": ["caseId is 'Syn003', expected 'Syn002'"]},
        {"label": "quorum failure", "draft": SYNTHETIC_TABLE, "provenance": {"model": "m"},
         "raters": ({}, None, None), "errors": ["committee quorum not met: 1 of 3 raters passed"],
         "check": _quorum_failure_is_recorded},
        {"label": "unratable draft", "draft": broken, "provenance": {}, "raters": ({}, {}, {}),
         "first_error": "committee: ValueError"},
    ]

    def run(case: dict[str, Any]) -> None:
        root = tmp_path / case["label"].replace(" ", "-")
        seed_case(root, with_table=False)
        with pytest.MonkeyPatch.context() as mp:
            _draft(mp, skillrun.SkillOutcome("pass", case["draft"], "raw", [], case["provenance"]))
            mp.setattr(gen.committee_module, "rate_table",
                       lambda case_, table, committee: _ratings(table, *case["raters"]))
            assert gen.generate(root, "Syn002", runs=1, backend="subscription", model="opus",
                                workers=1, committee=COMMITTEE) == ["failed"]
        status = json.loads(Project(root).artifact("Syn002", "run1", "status.json").read_text())
        if "errors" in case:
            assert status["errors"] == case["errors"]
        else:
            assert status["errors"][0].startswith(case["first_error"])
        if "check" in case:
            case["check"](root)

    each_case(cases, lambda c: c["label"], run)
