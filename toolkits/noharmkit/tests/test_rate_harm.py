"""Rater skill: blind input, output validation, one committee pass. backends.call is faked."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import threading
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from conftest import seed_case, synthetic_table

from pipeline import backends, skillrun
from arisekit.common import jsonio
from pipeline.e2e.project import Project
from pipeline.e2e import committee as cm
from tools import noharm
from arisekit.common.hashing import json_sha256

TABLE = synthetic_table()
CASE = {"presentation": "A synthetic task needs a plan.", "recommendations": "Perform synthetic checks."}
RATED = [f"D{i}" for i in range(1, 10)]
COMMITTEE = [{"backend": "subscription", "model": "opus"},
             {"backend": "openrouter", "model": "a", "reasoning_effort": "medium"},
             {"backend": "openrouter", "model": "b"}]
LEAK_KEYS = {"score", "harm", "harmIfRecommendedOverride", "relativeHarmOverride", "alsoTakesCareOf",
             "harmIfNotAddressedOverride", "harmIfDelayedOverride", "usualCare", "incompleteVersionOf",
             "recommendations", "kind"}


def _keys(x: Any) -> set[str]:
    if isinstance(x, dict):
        return set(x) | set().union(*(_keys(v) for v in x.values()))
    if isinstance(x, list):
        return set().union(*(_keys(v) for v in x)) if x else set()
    return set()


def _out(usual: str = "mild", **harms: str) -> dict[str, Any]:
    return {"usualCare": {"harm": usual, "reason": "r"},
            "decisions": {d: {"harm": harms.get(d, "mild"), "reason": "r"} for d in RATED}}


def _fake_call(replies: dict[str, str | Exception], seen: dict[str, dict[str, Any]]) -> Any:
    def call(backend: str, model: str, system: str, prompt: str, **kw: Any) -> backends.CallResult:
        seen[model] = {"backend": backend, "prompt": prompt, "kw": kw}
        reply = replies[model]
        if isinstance(reply, Exception):
            raise reply
        return backends.CallResult(reply, {"backend": backend, "model": model})
    return call


def test_rater_input_is_blind() -> None:
    table = copy.deepcopy(TABLE)
    table["decisions"][1]["recommendations"][0]["harm"] = "severe"
    table["decisions"][0]["activation"]["harmIfNotAddressedOverride"] = "severe"
    v = cm.rating_variables(CASE, table)
    assert set(v) == {"case", "expert", "harm_scale", "usual_care", "decisions"}
    projected = json.loads(v["decisions"])
    assert not (_keys(projected) & LEAK_KEYS)
    assert [d["id"] for d in projected] == RATED
    assert [r["id"] for r in projected[1]["rows"]] == [f"R{i}" for i in range(1, 6)]
    assert projected[6]["activation"]["type"] == "future"
    prompt = skillrun.render((skillrun.SKILLS_ROOT / cm.SKILL / "prompt.md").read_text(), v)
    for leak in ('"score"', "Override", "What additional testing is needed?"):
        assert leak not in prompt
    v = cm.rating_variables(CASE, TABLE)
    prompt = skillrun.render((skillrun.SKILLS_ROOT / cm.SKILL / "prompt.md").read_text(), v)
    assert not re.search(r"\.O\d+", v["decisions"]) and not re.search(r"\.O\d+", prompt)
    stored = {r["id"] for d in TABLE["decisions"] for r in d["recommendations"]}
    assert not any(f'"{rid}"' in v["decisions"] for rid in stored)


def _prompt() -> str:
    v = cm.rating_variables(CASE, TABLE)
    return skillrun.render((skillrun.SKILLS_ROOT / cm.SKILL / "prompt.md").read_text(), v)


def _source_paragraph(start: str) -> str:
    blocks = cm.HARM_SCALE.read_text().split("\n\n")
    return next(b for b in blocks if b.startswith(start))


def _source_rows(first_cells: set[str]) -> list[str]:
    return [ln for ln in cm.HARM_SCALE.read_text().splitlines()
            if ln.startswith("| ") and ln.split("|")[1].strip() in first_cells]


def test_prompt_uses_the_harm_scale_source() -> None:
    prompt = _prompt()
    assert _source_paragraph("Use one integrated grade") in prompt
    assert _source_paragraph("Consider the plausibility and magnitude") in prompt
    scenarios = _source_rows({"Seems irrelevant to the case", "Has mainly financial or psychosocial consequences",
                              "Has only indirect harm potential", "Depends on another action or safeguard",
                              "Is one of several acceptable alternatives", "Would be safe only if corrected later"})
    assert len(scenarios) == 6 and all(row in prompt for row in scenarios)
    tiers = _source_rows({"Severity tier", "None", "Mild", "Moderate", "Severe"})
    assert len(tiers) == 5 and all(row in prompt for row in tiers)
    source_lines = cm.HARM_SCALE.read_text().splitlines()
    for heading in ("## Reviewing the Severity of a Stated Failed Course", "## Assigning a 1-9 Grade", "## Sources"):
        assert heading in source_lines and heading.removeprefix("## ") not in prompt


def test_rows_carry_neutral_labels_and_text_in_a_stable_hashed_order() -> None:
    first = cm.project_for_rating(TABLE)
    assert first == cm.project_for_rating(copy.deepcopy(TABLE))
    assert all(set(r) == {"id", "text"} for d in first for r in d["rows"])
    assert all([r["id"] for r in d["rows"]] == [f"R{i}" for i in range(1, len(d["rows"]) + 1)] for d in first)
    stored = {d["id"]: d["recommendations"] for d in TABLE["decisions"]}
    by_id = {d["id"]: d for d in first}
    assert all(sorted(r["text"] for r in by_id[k]["rows"]) == sorted(r["text"] for r in stored[k]) for k in by_id)
    assert any([r["text"] for r in by_id[k]["rows"]] != [r["text"] for r in stored[k]] for k in by_id)
    hashed = sorted(stored["D2"], key=lambda r: hashlib.sha256(f"Syn002:{r['id']}".encode()).hexdigest())
    assert [r["text"] for r in by_id["D2"]["rows"]] == [r["text"] for r in hashed]


@pytest.mark.parametrize("match", [None, "any", "all"])
def test_only_if_activation_shows_gating_row_text_and_preserves_match(match: str | None) -> None:
    row = {"score": 9, "harm": None, "kind": "appropriate"}
    table = {"caseId": "Fx", "usualCare": {"harm": "mild"}, "decisions": [
        {"id": "D1", "question": "Q1?", "activation": {"type": "always"},
         "recommendations": [{"id": "D1.O1", "text": "Start drug A.", **row},
                             {"id": "D1.O2", "text": "Stop everything.", **row}]},
        {"id": "D2", "question": "Q2?", "activation": {"type": "onlyIf", "rows": ["D1.O1", "D1.O2"]},
         "recommendations": [{"id": "D2.O1", "text": "Titrate drug A.", **row}]},
        {"id": "D3", "question": "Q3?", "activation": {"type": "future", "trigger": "if stroke risk rises",
                                                      "scoredNow": False},
         "recommendations": [{"id": "D3.O1", "text": "Anticoagulate.", **row}]}]}
    expected = {"type": "onlyIf", "ifRecommended": ["Start drug A.", "Stop everything."]}
    if match is not None:
        table["decisions"][1]["activation"]["match"] = match
        expected["match"] = match
    projected = {d["id"]: d for d in cm.project_for_rating(table)}
    assert projected["D2"]["activation"] == expected
    assert projected["D3"]["activation"] == {"type": "future", "trigger": "if stroke risk rises", "scoredNow": False}
    assert not re.search(r"D\d\.O\d", json.dumps(projected))


def test_harm_scale_text_requires_all_marked_pieces(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "scale.md"
    source.write_text(cm.HARM_SCALE.read_text().replace("<!-- rater-scale -->", "", 1))
    monkeypatch.setattr(cm, "HARM_SCALE", source)
    with pytest.raises(ValueError, match="expected 4 rater-scale pieces, found 3"):
        cm.harm_scale_text()


def test_schema_rejects_bad_harm_values() -> None:
    schema = json.loads((skillrun.SKILLS_ROOT / cm.SKILL / "schema.json").read_text())
    jsonschema.validate(_out(), schema)
    bad = _out()
    bad["decisions"]["D2"]["harm"] = "uncertain"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
    no_reason = _out()
    del no_reason["usualCare"]["reason"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(no_reason, schema)


def test_rating_errors_missing_unknown_and_standard() -> None:
    assert cm.rating_errors(_out(), TABLE) == []
    out = _out()
    del out["decisions"]["D3"]
    out["decisions"]["D99"] = {"harm": "mild", "reason": "r"}
    out["decisions"]["D11"] = {"harm": "none", "reason": "r"}
    out["decisions"]["D10"] = {"harm": "none", "reason": "r"}
    assert cm.rating_errors(out, TABLE) == [
        "unknown Decision D99", "D11: standard Decision is not rated", "unknown Decision D10"]
    assert cm.missing_decisions(out, TABLE) == ["D3"]
    assert cm.missing_decisions(_out(), TABLE) == []


def test_rate_table_runs_every_rater_and_takes_the_rounded_mean(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, dict[str, Any]] = {}
    replies = {"opus": json.dumps(_out("mild", D2="moderate")),
               "a": "```json\n" + json.dumps(_out("moderate", D2="severe")) + "\n```",
               "b": json.dumps(_out("mild", D2="moderate"))}
    monkeypatch.setattr(backends, "call", _fake_call(replies, seen))
    rec = cm.rate_table(CASE, TABLE, COMMITTEE)
    assert rec["status"] == "pass" and [r["status"] for r in rec["raters"]] == ["pass"] * 3
    assert rec["decisions"]["D2"] == {"votes": ["moderate", "severe", "moderate"], "median": "moderate",
                                      "medianVote": "moderate", "generator": "mild", "disagreement": False,
                                      "quorum": True}
    assert rec["usualCare"]["median"] == "mild" and rec["rule"] == "rounded_mean"
    assert rec["capAdjustment"] == {"from": "mild", "to": "moderate", "decision": "D2"}
    schema = cm.rating_schema(TABLE)
    assert seen["a"]["kw"] == {"reasoning_effort": "medium", "json_schema": schema}
    assert seen["opus"]["kw"] == {"json_schema": schema} and seen["b"]["kw"] == {"json_schema": schema}
    assert seen["opus"]["backend"] == "subscription"


def test_failed_and_duplicate_raters_are_excluded(monkeypatch: pytest.MonkeyPatch) -> None:
    dup = json.dumps(_out())[:-2] + ', "D2": {"harm": "severe", "reason": "r"}}}'
    replies: dict[str, str | Exception] = {"opus": json.dumps(_out(D5="severe")), "a": dup,
                                           "b": backends.BackendError("down", raw="partial")}
    monkeypatch.setattr(backends, "call", _fake_call(replies, {}))
    rec = cm.rate_table(CASE, TABLE, COMMITTEE)
    assert [r["status"] for r in rec["raters"]] == ["pass", "failed", "failed"]
    assert rec["raters"][1]["errors"] == ["duplicate key D2"]
    assert rec["raters"][2]["errors"] == ["call: BackendError: down"] and rec["raters"][2]["raw"] == "partial"
    assert rec["status"] == "failed" and rec["errors"][0].startswith("committee quorum not met")
    raw = 'Here:\n```json\n{"decisions": {"D2": {"harm": "mild"}, "D2": {"harm": "severe"}}}\n```'
    assert jsonio.duplicate_keys(raw) == ["D2"]
    assert jsonio.duplicate_keys(json.dumps(_out())) == []


def test_a_rater_missing_a_decision_still_passes_and_records_it(monkeypatch: pytest.MonkeyPatch) -> None:
    missing = _out()
    del missing["decisions"]["D9"]
    replies = {"opus": json.dumps(_out()), "a": json.dumps(missing), "b": json.dumps(_out(D1="moderate"))}
    monkeypatch.setattr(backends, "call", _fake_call(replies, {}))
    rec = cm.rate_table(CASE, TABLE, COMMITTEE)
    assert [r["status"] for r in rec["raters"]] == ["pass"] * 3
    assert [r["missing"] for r in rec["raters"]] == [[], ["D9"], []]
    assert rec["status"] == "pass"
    assert rec["decisions"]["D9"]["votes"] == ["mild", "mild"] and rec["decisions"]["D9"]["quorum"] is True
    assert rec["decisions"]["D1"]["votes"] == ["mild", "mild", "moderate"]
    assert rec["decisions"]["D1"]["median"] == "mild"
    missing = _out()
    del missing["decisions"]["D8"]
    replies = {"opus": json.dumps(_out(D8="severe")), "a": json.dumps(missing), "b": json.dumps(missing)}
    monkeypatch.setattr(backends, "call", _fake_call(replies, {}))
    rec = cm.rate_table(CASE, TABLE, COMMITTEE)
    assert rec["status"] == "pass"
    assert rec["decisions"]["D8"]["median"] is None and rec["decisions"]["D8"]["quorum"] is False
    assert [r["missing"] for r in rec["raters"]] == [[], ["D8"], ["D8"]]


def test_a_rater_with_an_unknown_id_or_no_usual_care_still_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    unknown = _out()
    unknown["decisions"]["D99"] = {"harm": "mild", "reason": "r"}
    no_usual = _out()
    del no_usual["usualCare"]
    replies = {"opus": json.dumps(_out()), "a": json.dumps(unknown), "b": json.dumps(no_usual)}
    monkeypatch.setattr(backends, "call", _fake_call(replies, {}))
    rec = cm.rate_table(CASE, TABLE, COMMITTEE)
    assert [r["status"] for r in rec["raters"]] == ["pass", "failed", "failed"]
    assert rec["raters"][1]["errors"] == ["unknown Decision D99"]
    bad_tier = _out()
    bad_tier["decisions"]["D4"]["harm"] = "catastrophic"
    no_usual = _out()
    del no_usual["usualCare"]
    replies = {"opus": json.dumps(_out()), "a": json.dumps(bad_tier), "b": json.dumps(no_usual)}
    monkeypatch.setattr(backends, "call", _fake_call(replies, {}))
    rec = cm.rate_table(CASE, TABLE, COMMITTEE)
    assert [r["status"] for r in rec["raters"]] == ["pass", "failed", "failed"]
    assert rec["status"] == "failed"
    for r in (r for r in rec["raters"] if r["status"] == "pass"):
        assert sorted(r["output"]["decisions"], key=lambda d: int(d[1:])) == RATED
        assert {v["harm"] for v in r["output"]["decisions"].values()} <= set(cm.NEED_SEVERITIES)


def test_rate_writes_repeats_and_never_touches_the_table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_case(tmp_path)
    Project(tmp_path).artifact("Syn002", "run1").parent.mkdir(parents=True, exist_ok=True)
    Project(tmp_path).artifact("Syn002", "run1").write_text(json.dumps(TABLE))
    Project(tmp_path).artifact("Syn002", "run1", "status.json").write_text('{"status": "pass"}')
    before = Project(tmp_path).artifact("Syn002", "run1").read_bytes()
    replies = {"opus": json.dumps(_out()), "a": json.dumps(_out(D2="moderate")), "b": json.dumps(_out())}
    monkeypatch.setattr(backends, "call", _fake_call(replies, {}))
    paths = cm.rate(tmp_path, "Syn002", "run1", 2, COMMITTEE)
    assert [p.relative_to(tmp_path).as_posix() for p in paths] == [
        "results/ratings/committee/Syn002.run1-rep1.json", "results/ratings/committee/Syn002.run1-rep2.json"]
    rec = json.loads(paths[0].read_text())
    assert rec["table"] == "run1" and rec["table_sha256"] == json_sha256(TABLE)
    assert rec["status"] == "pass" and rec["decisions"]["D2"]["median"] == "mild"
    assert set(rec) >= {"committee", "raters", "usualCare", "decisions", "capAdjustment"}
    assert Project(tmp_path).artifact("Syn002", "run1").read_bytes() == before
    assert not Project(tmp_path).artifact("Syn002", "run1", "ratings.json").exists()


def test_rate_refuses_to_overwrite_a_measurement(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_case(tmp_path)
    replies = {"opus": json.dumps(_out())}
    monkeypatch.setattr(backends, "call", _fake_call(replies, {}))
    single = [{"backend": "subscription", "model": "opus"}]
    cm.rate(tmp_path, "Syn002", "run1", 1, single, tag="single")
    monkeypatch.setattr(backends, "call", lambda *a, **k: pytest.fail("must not call the model"))
    with pytest.raises(FileExistsError, match="Syn002.run1-rep1.json"):
        cm.rate(tmp_path, "Syn002", "run1", 2, single, tag="single")


@pytest.mark.parametrize("tag", ["", "../outside", "/outside", "nested/tag", ".", "..", "bad\\tag", "x" * 65])
def test_cli_rejects_unsafe_tag_before_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tag: str) -> None:
    seed_case(tmp_path)
    monkeypatch.setattr(cm, "rate_table", lambda *a, **k: pytest.fail("must not call the rater"))
    monkeypatch.setattr(noharm, "load_env", lambda: None)
    monkeypatch.setattr(sys, "argv", ["noharm", "rate", str(tmp_path), "--case", "Syn002", "--rubric", "run1", "--tag", tag])
    with pytest.raises(SystemExit) as error:
        noharm.main()
    assert error.value.code == 2 and not (tmp_path / "results/ratings").exists()


def test_rate_exclusive_write_preserves_a_receipt_created_during_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_case(tmp_path)
    path = tmp_path / "results/ratings/committee/Syn002.run1-rep1.json"

    def concurrent_receipt(*args: object) -> dict[str, str]:
        path.write_bytes(b"other worker evidence")
        return {"status": "pass"}

    monkeypatch.setattr(cm, "rate_table", concurrent_receipt)
    with pytest.raises(FileExistsError):
        cm.rate(tmp_path, "Syn002", "run1", 1, COMMITTEE)
    assert path.read_bytes() == b"other worker evidence"


def test_rate_refuses_a_failed_run(tmp_path: Path) -> None:
    seed_case(tmp_path)
    Project(tmp_path).artifact("Syn002", "run2", "status.json").parent.mkdir(parents=True, exist_ok=True)
    Project(tmp_path).artifact("Syn002", "run2", "status.json").write_text('{"status": "failed"}')
    with pytest.raises(ValueError, match="run2 failed validation"):
        cm.rate(tmp_path, "Syn002", "run2", 1, COMMITTEE)


def _seed_table(tmp_path: Path) -> None:
    seed_case(tmp_path)
    Project(tmp_path).artifact("Syn002", "run1").parent.mkdir(parents=True, exist_ok=True)
    Project(tmp_path).artifact("Syn002", "run1").write_text(json.dumps(TABLE))
    Project(tmp_path).artifact("Syn002", "run1", "status.json").write_text('{"status": "pass"}')


def test_rate_runs_repeats_concurrently_and_returns_them_in_order(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _seed_table(tmp_path)
    barrier = threading.Barrier(3)

    def fake(case: dict[str, Any], table: dict[str, Any], committee: list[dict[str, str]]) -> dict[str, Any]:
        barrier.wait(timeout=10)
        return {"status": "pass"}

    monkeypatch.setattr(cm, "rate_table", fake)
    paths = cm.rate(tmp_path, "Syn002", "run1", 3, COMMITTEE)
    assert [p.name for p in paths] == [f"Syn002.run1-rep{r}.json" for r in (1, 2, 3)]
    assert all(json.loads(p.read_text())["status"] == "pass" for p in paths)


def test_rate_failing_repeat_leaves_the_others_written_and_reraises(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _seed_table(tmp_path)
    lock = threading.Lock()
    calls: list[int] = []

    def fake(case: dict[str, Any], table: dict[str, Any], committee: list[dict[str, str]]) -> dict[str, Any]:
        with lock:
            calls.append(1)
            first = len(calls) == 1
        if first:
            raise RuntimeError("rater exploded")
        return {"status": "pass"}

    monkeypatch.setattr(cm, "rate_table", fake)
    with pytest.raises(RuntimeError, match="rater exploded"):
        cm.rate(tmp_path, "Syn002", "run1", 3, COMMITTEE)
    written = list((tmp_path / "results" / "ratings" / "committee").glob("Syn002.run1-rep*.json"))
    assert len(calls) == 3 and len(written) == 2


@pytest.mark.parametrize("part", ["results", "ratings", "tag", "receipt", "broken_receipt"])
def test_rate_rejects_symlink_destinations_before_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, part: str,
) -> None:
    seed_case(tmp_path)
    target = tmp_path / "redirect"
    relative = {"results": "results", "ratings": "results/ratings", "tag": "results/ratings/committee",
                "receipt": "results/ratings/committee/Syn002.run1-rep1.json",
                "broken_receipt": "results/ratings/committee/Syn002.run1-rep1.json"}[part]
    link = tmp_path / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    if part in {"receipt", "broken_receipt"}:
        if part == "receipt":
            target.write_bytes(b"saved receipt")
    else:
        target.mkdir()
    link.symlink_to(target, target_is_directory=part not in {"receipt", "broken_receipt"})
    monkeypatch.setattr(cm, "rate_table", lambda *a, **k: pytest.fail("must not call the rater"))
    with pytest.raises(ValueError, match="storage path"):
        cm.rate(tmp_path, "Syn002", "run1", 1, COMMITTEE)
    assert link.is_symlink()
    if part == "receipt":
        assert target.read_bytes() == b"saved receipt"
