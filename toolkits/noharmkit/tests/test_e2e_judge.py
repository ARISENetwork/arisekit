"""Judge: projection without scores or harms, output validation, stage records."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from cases import each_case
from conftest import seed_case, synthetic_table

from pipeline import skillrun
from pipeline.e2e import judge as jd
from pipeline.e2e.project import Project
from pipeline.e2e.rubric import Rubric
from arisekit.common.jsonio import append_jsonl, read_jsonl

TABLE = synthetic_table()
RESPONSE = "Order an Check A and\n  Check B today. Perform action C now."
SCORE_KEYS = {"score", "harmIfRecommendedOverride", "relativeHarmOverride", "alsoTakesCareOf",
              "harmIfNotAddressedOverride", "harmIfDelayedOverride", "usualCare"}


def _keys(x: Any) -> set[str]:
    if isinstance(x, dict):
        return set(x) | set().union(*(_keys(v) for v in x.values()))
    if isinstance(x, list):
        return set().union(*(_keys(v) for v in x)) if x else set()
    return set()


def test_judge_projection() -> None:
    projected = Rubric(TABLE).for_judge()
    assert not (_keys(projected) & SCORE_KEYS)
    assert "score" in TABLE["decisions"][1]["recommendations"][0]  # input untouched
    assert not (_keys(projected) & {"recommendations", "incompleteVersionOf"})
    d2 = projected["decisions"][1]
    assert set(d2) == {"id", "question", "activation", "rows"}
    row = next(r for r in d2["rows"] if r["id"] == "D2.O1")
    assert row["parts"] == ["Check A", "Check B"]
    assert [r["id"] for r in d2["rows"]] == [f"D2.O{i}" for i in range(1, 6)]
    assert set(projected["decisions"][0]) == {"id", "kind", "question", "activation", "rows"}
    d7 = next(d for d in projected["decisions"] if d["id"] == "D7")
    assert all(set(r) <= {"id", "text", "parts", "timing", "equivalents", "drugClass"} for r in d7["rows"])
    tagged = json.loads(json.dumps(TABLE))
    for decision in tagged["decisions"]:
        for row in decision["recommendations"]:
            row["tags"] = ["diagnostic", "medication"]
    assert Rubric(tagged).for_judge() == Rubric(TABLE).for_judge()


def test_schema_rejects_empty_evidence() -> None:
    schema = json.loads((skillrun.SKILLS_ROOT / jd.SKILL / "schema.json").read_text())
    jsonschema.validate(_ok(), schema)
    for mutate in (lambda o: o["decisions"]["D2"]["recommended"][0].update(evidence=""),
                   lambda o: o["decisions"]["D2"].update(unmatched=[{"evidence": "", "provisional": {"outcome": "met"}}]),
                   lambda o: o["offRubric"].append({"evidence": "", "actionable": True, "harm": "none"})):
        out = _ok()
        mutate(out)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(out, schema)


def test_rules_text_is_the_pinned_judge_rules() -> None:
    text = jd.RULES.read_text(encoding="utf-8")
    # Protect the published judge rules against accidental edits.
    assert hashlib.sha256(text.encode()).hexdigest() == "2322c187ab769cf83433d9899c4a055ded99c2f37c5f0931f9b1989fed282df8"


def _ok() -> dict:
    return {"decisions": {"D2": {"recommended": [
        {"rowId": "D2.O1", "role": "first", "evidence": "Order an Check A and Check B today.",
         "partsPresent": ["Check A"]}]}}, "offRubric": []}


def _set_row(**fields: Any) -> Callable[[dict], None]:
    return lambda o: o["decisions"]["D2"]["recommended"][0].update(**fields)


def _without_parts_present(o: dict) -> None:
    del o["decisions"]["D2"]["recommended"][0]["partsPresent"]


def test_judge_errors() -> None:
    cases: list[tuple[str, Callable[[dict], None], Callable[[list[str]], bool]]] = [
        ("whitespace-different valid output", lambda o: None, lambda errors: errors == []),
        ("parts row without partsPresent", _without_parts_present,
         lambda errors: "D2 D2.O1: recommendation has parts; partsPresent is required" in errors),
        ("parts row with empty partsPresent", _set_row(partsPresent=[]), lambda errors: errors == []),
        ("partsPresent on a row scored 1 to 6", lambda o: o["decisions"]["D2"].update(recommended=[
            {"rowId": "D2.O4", "role": "addOn", "evidence": "Order an Check A", "partsPresent": ["Check A"]}]),
         lambda errors: errors == []),
        ("silent decisions omitted", lambda o: o.update(decisions={}), lambda errors: errors == []),
        *[(f"invalid {i}: {needle}", mutate,
           lambda errors, needle=needle: bool(errors) and any(needle in e for e in errors))
          for i, (mutate, needle) in enumerate([
              (_set_row(rowId="D2.O99"), "D2.O99"),
              (_set_row(rowId="D3.O1"), "D3.O1"),
              (_set_row(evidence="order a CT"), "not in the response"),
              (_set_row(partsPresent=["Stress test"]), "Stress test"),
              (lambda o: o["decisions"].update(D99={}), "D99"),
              (lambda o: o["offRubric"].append({"evidence": "nope", "actionable": True, "harm": "mild"}),
               "not in the response"),
          ], 1)],
    ]

    def run(case: tuple[str, Callable[[dict], None], Callable[[list[str]], bool]]) -> None:
        _, mutate, expected = case
        out = _ok()
        mutate(out)
        assert expected(jd.judge_errors(out, TABLE, RESPONSE))

    each_case(cases, lambda c: c[0], run)


def test_stage_skips_error_records_and_writes_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_case(tmp_path)
    resp = tmp_path / "results" / "responses" / "m.jsonl"
    append_jsonl(resp, {"id": "Syn002", "trial": 1, "response": RESPONSE, "runtime": 1, "usage": None})
    append_jsonl(resp, {"id": "Syn002", "trial": 2, "response": None, "error": "429", "runtime": None, "usage": None})
    seen: list[dict] = []

    def fake_run_skill(name: str, variables: dict, backend: str, model: str, **kw: Any) -> Any:
        seen.append(variables)
        return skillrun.SkillOutcome("pass", _ok(), "raw", [], {"model": model})

    monkeypatch.setattr(jd, "run_skill", fake_run_skill)
    [out] = jd.judge(tmp_path, "run1", "openrouter", "openai/gpt-6-astra", workers=1)
    recs = read_jsonl(out)
    assert [(r["id"], r["trial"], r["status"]) for r in recs] == [("Syn002", 1, "pass")]
    assert recs[0]["rubric"] == "run1" and len(recs[0]["rubric_sha256"]) == 64
    assert recs[0]["response_sha256"] == hashlib.sha256(RESPONSE.encode("utf-8")).hexdigest()
    assert recs[0]["case_presentation_sha256"] == hashlib.sha256(seen[0]["case"].encode("utf-8")).hexdigest()
    assert '"score"' not in seen[0]["table"]


def test_stage_refuses_failed_rubric(tmp_path: Path) -> None:
    seed_case(tmp_path)
    append_jsonl(tmp_path / "results" / "responses" / "m.jsonl",
                 {"id": "Syn002", "trial": 1, "response": "x", "runtime": 1, "usage": None})
    Project(tmp_path).artifact("Syn002", "run2").parent.mkdir(parents=True, exist_ok=True)
    Project(tmp_path).artifact("Syn002", "run2", "status.json").write_text('{"status": "failed"}')
    with pytest.raises(ValueError, match="run2 failed validation"):
        jd.judge(tmp_path, "run2", "openrouter", "m", workers=1)


def make_synthetic_judge_run(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Only invented inputs reach the stubbed model and the stage receipts."""
    for case_id in ("Test001", "Test002"):
        append_jsonl(root / "items.jsonl", {"id": case_id, "metadata": {"base_id": case_id}})
        append_jsonl(root / "results" / "responses" / "m.jsonl",
                     {"id": case_id, "trial": 1, "response": case_id + " synthetic response"})
    Project(root).update_provenance(models=["m"])
    monkeypatch.setattr(Project, "case", lambda *_: {"presentation": "Synthetic presentation"})
    monkeypatch.setattr(Project, "table", lambda _project, case_id, _rubric: {"caseId": case_id, "decisions": []})
    return root


@pytest.fixture
def synthetic_judge_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return make_synthetic_judge_run(tmp_path, monkeypatch)


@pytest.mark.parametrize("statuses", [("pass", "pass"), ("pass", "failed"), ("failed", "failed"), ("pass", "unresolved")])
def test_stage_summary_preserves_all_outcome_receipts(
    synthetic_judge_run: Path, monkeypatch: pytest.MonkeyPatch, statuses: tuple[str, str],
) -> None:
    root = synthetic_judge_run

    def stub(_name: str, variables: dict, *_args: object, **_kwargs: object) -> skillrun.SkillOutcome:
        status = statuses[int(variables["response"][6]) - 1]
        return skillrun.SkillOutcome(status, {"decisions": {}, "offRubric": []},
                                     "retained raw output", [] if status == "pass" else ["synthetic failure"], {})

    monkeypatch.setattr(jd, "run_skill", stub)
    written = jd.judge(root, "run1", "subscription", "synthetic", workers=1)
    before = written[0].read_bytes()
    records = read_jsonl(written[0])
    assert [record["status"] for record in records] == list(statuses)
    assert all(record["raw"] == "retained raw output" for record in records)
    problems = jd.judge_problems(root, written)
    assert bool(problems) == any(status != "pass" for status in statuses)
    assert written[0].read_bytes() == before


def test_stage_refuses_existing_receipts_before_any_calls(
    synthetic_judge_run: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = synthetic_judge_run
    append_jsonl(root / "results/responses/a.jsonl", {"id": "Test001", "trial": 1, "response": "New model"})
    old = root / "results/judge/m.jsonl"
    append_jsonl(old, {"id": "Test001", "trial": 1, "status": "failed", "raw": "Saved evidence"})
    before = old.read_bytes()
    calls = []
    monkeypatch.setattr(jd, "run_skill", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="new project/run"):
        jd.judge(root, "run1", "subscription", "synthetic", workers=1)
    assert calls == []
    assert old.read_bytes() == before
    assert not (root / "results/judge/a.jsonl").exists()


@pytest.mark.parametrize("complete", [True, False])
def test_declared_trials_judge_and_summary(
    synthetic_judge_run: Path, monkeypatch: pytest.MonkeyPatch, complete: bool,
) -> None:
    root = synthetic_judge_run
    Project(root).update_provenance(trials=2)
    if complete:
        for case_id in ("Test001", "Test002"):
            append_jsonl(root / "results" / "responses" / "m.jsonl",
                         {"id": case_id, "trial": 2, "response": "Second synthetic response"})
    monkeypatch.setattr(jd, "run_skill", lambda *args, **kwargs:
                        skillrun.SkillOutcome("pass", {"decisions": {}, "offRubric": []}, "raw", [], {}))
    written = jd.judge(root, "run1", "subscription", "synthetic", workers=1)
    assert len(read_jsonl(written[0])) == (4 if complete else 2)
    problems = jd.judge_problems(root, written)
    assert bool(problems) is not complete
    assert not any("duplicate case" in problem for problem in problems)
    if not complete:
        assert any("no response" in problem and "2" in problem for problem in problems)


def test_receipt_created_during_calls_is_not_overwritten(synthetic_judge_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = synthetic_judge_run
    out = root / "results/judge/m.jsonl"
    def race(*args: Any, **kwargs: Any) -> skillrun.SkillOutcome:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("other process evidence\n")
        return skillrun.SkillOutcome("pass", {"decisions": {}, "offRubric": []}, "raw", [], {})
    monkeypatch.setattr(jd, "run_skill", race)
    with pytest.raises(FileExistsError):
        jd.judge(root, "run1", "claude", "synthetic", workers=1)
    assert out.read_text() == "other process evidence\n"


def _receipts(*rows: tuple[str, int, str]) -> Callable[[Path], list[Path]]:
    def setup(root: Path) -> list[Path]:
        path = root / "results" / "judge" / "m.jsonl"
        for case_id, trial, status in rows:
            append_jsonl(path, {"id": case_id, "trial": trial, "status": status, "judge": {}})
        return [path]
    return setup


def _old_receipts_without_responses(root: Path) -> list[Path]:
    (root / "results" / "responses" / "m.jsonl").write_text("")
    _receipts(("Test001", 1, "pass"), ("Test002", 1, "pass"))(root)
    return []


def _complete_receipts_without_responses(root: Path) -> list[Path]:
    paths = _receipts(("Test001", 1, "pass"), ("Test002", 1, "pass"))(root)
    (root / "results" / "responses" / "m.jsonl").write_text("")
    return paths


def _failure_after_passes(root: Path) -> list[Path]:
    [path] = _receipts(("Test001", 1, "pass"), ("Test002", 1, "pass"))(root)
    append_jsonl(path, {"id": "Test001", "trial": 1, "status": "failed", "judge": None,
                        "errors": ["synthetic failure"], "raw": "retained"})
    return [path]


def _no_models(root: Path) -> list[Path]:
    (root / "items.jsonl").write_text("")
    Project(root).update_provenance(models=[])
    return []


def test_judge_problems_cases(tmp_path: Path) -> None:
    cases: list[tuple[str, bool, Callable[[Path], list[Path]], list[str]]] = [
        ("empty responses ignore old receipts", True, _old_receipts_without_responses, ["no judgment receipt"]),
        ("absent models and cases", False, _no_models, ["no response models"]),
        ("one trial, one receipt per case", True,
         _receipts(("Test001", 1, "pass"), ("Test001", 1, "pass"), ("Test001", 2, "pass")),
         ["no passing judgment", "Test002"]),
        ("response coverage with complete receipts", True, _complete_receipts_without_responses, ["no response"]),
        ("failure not masked by a passing duplicate", True, _failure_after_passes, ["failed or unresolved"]),
        ("duplicate passing judgments", True,
         _receipts(("Test001", 1, "pass"), ("Test002", 1, "pass"), ("Test001", 1, "pass")), ["duplicate judgment"]),
    ]

    def run(case: tuple[str, bool, Callable[[Path], list[Path]], list[str]]) -> None:
        label, synthetic, setup, needles = case
        root = tmp_path / label.replace(" ", "-").replace(",", "")
        root.mkdir()
        with pytest.MonkeyPatch.context() as mp:
            if synthetic:
                make_synthetic_judge_run(root, mp)
            paths = setup(root)
            problems = jd.judge_problems(root, paths)
        assert any(all(needle in p for needle in needles) for p in problems)

    each_case(cases, lambda c: c[0], run)


def _dangling_receipt(root: Path, outside: Path) -> tuple[str, Callable[[], bool]]:
    out = root / "results/judge/m.jsonl"
    out.parent.mkdir(parents=True)
    out.symlink_to(root / "absent.jsonl")
    return "claude", lambda: not (root / "absent.jsonl").exists()


def _redirected_folder(root: Path, outside: Path) -> tuple[str, Callable[[], bool]]:
    (root / "results/judge").symlink_to(outside, target_is_directory=True)
    return "subscription", lambda: list(outside.iterdir()) == []


def test_judge_refuses_redirected_storage(tmp_path: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    cases: list[tuple[str, Callable[[Path, Path], tuple[str, Callable[[], bool]]], str]] = [
        ("dangling receipt symlink", _dangling_receipt, "already exist"),
        ("judgment folder redirected outside", _redirected_folder, "storage path"),
    ]

    def run(case: tuple[str, Callable[[Path, Path], tuple[str, Callable[[], bool]]], str]) -> None:
        label, redirect, match = case
        root = tmp_path / label.replace(" ", "-")
        root.mkdir()
        with pytest.MonkeyPatch.context() as mp:
            make_synthetic_judge_run(root, mp)
            backend, target_untouched = redirect(root, tmp_path_factory.mktemp("outside"))
            mp.setattr(jd, "run_skill", lambda *args, **kwargs: pytest.fail("called provider"))
            with pytest.raises(ValueError, match=match):
                jd.judge(root, "run1", backend, "synthetic", workers=1)
        assert target_untouched()

    each_case(cases, lambda c: c[0], run)


def _trials(count: object) -> Callable[[Path], None]:
    return lambda root: Project(root).update_provenance(trials=count)


def _response(model: str, item_id: object, trial: object, text: str, trials: int | None = None) -> Callable[[Path], None]:
    def setup(root: Path) -> None:
        if trials is not None:
            Project(root).update_provenance(trials=trials)
        append_jsonl(root / "results" / "responses" / f"{model}.jsonl", {"id": item_id, "trial": trial, "response": text})
    return setup


def _duplicate_item(root: Path) -> None:
    append_jsonl(root / "items.jsonl", {"id": "Test001", "metadata": {"base_id": "Test001"}})


def test_invalid_inputs_block_judging_before_calls(tmp_path: Path) -> None:
    cases: list[tuple[str, Callable[[Path], None], str]] = [
        *[(f"project trials {count!r}", _trials(count), "trials") for count in [0, -1, True, "2", 2.0, None]],
        ("undeclared trial 2", _response("m", "Test001", 2, "Extra trial."), "unexpected response"),
        ("duplicate response", _response("m", "Test001", 1, "Duplicate synthetic response"), "duplicate response"),
        ("duplicate case id", _duplicate_item, "more than once"),
        *[(f"case id {item_id!r}", _response("m", item_id, 1, "Invalid synthetic case"), "response")
          for item_id in ["Unknown", None, [], 42]],
        *[(f"trial {trial!r} with two declared", _response("z", "Test001", trial, "Invalid synthetic response", 2),
           "response") for trial in [0, -1, True, 1.0, "1", None, [], 3]],
    ]

    def run(case: tuple[str, Callable[[Path], None], str]) -> None:
        _, setup, match = case
        root = tmp_path / f"row{cases.index(case)}"
        root.mkdir()
        calls: list[tuple] = []
        with pytest.MonkeyPatch.context() as mp:
            make_synthetic_judge_run(root, mp)
            setup(root)
            mp.setattr(jd, "run_skill", lambda *args, **kwargs: calls.append(args))
            mp.setattr(jd.Judge, "call", lambda *args: pytest.fail("called the judge"))
            with pytest.raises(ValueError, match=match):
                jd.judge(root, "run1", "subscription", "synthetic", workers=1)
        assert calls == [] and not (root / "results" / "judge").exists()

    each_case(cases, lambda c: c[0], run)
