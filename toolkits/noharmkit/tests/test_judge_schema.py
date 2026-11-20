"""Strict provider schemas preserve the canonical judgment and exact evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from cases import each_case
from conftest import seed_case, synthetic_table
from jsonschema import Draft202012Validator, ValidationError

from pipeline import backends, skillrun
from pipeline.e2e import judge as jd
from pipeline.e2e.judge import provider_schema
from pipeline.e2e.project import Project
from arisekit.common.jsonio import append_jsonl, read_jsonl
from arisekit.common.schemas import omit_null_fields


CANONICAL_SCHEMA = json.loads(
    (skillrun.SKILLS_ROOT / jd.SKILL / "schema.json").read_text()
)
EVIDENCE = "**Check A**\nThen check B."


def _wire() -> dict[str, Any]:
    decisions = {decision["id"]: None for decision in synthetic_table()["decisions"]}
    decisions["D2"] = {
        "recommended": [{
            "rowId": "D2.O1", "role": None, "evidence": EVIDENCE,
            "partsPresent": ["Check A", "Check B"], "via": None,
        }],
        "contradiction": False,
        "unmatched": [{
            "evidence": "Separate action.",
            "provisional": {"outcome": "partly", "harm": None},
        }],
    }
    return {"decisions": decisions, "offRubric": []}


def _schemas(value: Any) -> Any:
    """Walk schema nodes, including nullable anyOf branches and array items."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _schemas(child)
    elif isinstance(value, list):
        for child in value:
            yield from _schemas(child)


def test_provider_schema_shape() -> None:
    schema = provider_schema(synthetic_table())
    Draft202012Validator.check_schema(schema)
    assert schema["type"] == "object" and "anyOf" not in schema
    objects = [node for node in _schemas(schema) if node.get("type") == "object"]
    assert len(objects) > 5
    for node in objects:
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])
    tagged = synthetic_table()
    untagged_schema = provider_schema(tagged)
    for decision in tagged["decisions"]:
        for row in decision["recommendations"]:
            row["tags"] = ["diagnostic", "medication"]
    assert provider_schema(tagged) == untagged_schema
    table = synthetic_table()
    original = copy.deepcopy(table)
    table["decisions"][0]["id"] = "case-specific-id"
    schema = provider_schema(table)
    assert set(schema["properties"]["decisions"]["properties"]) == {
        decision["id"] for decision in table["decisions"]
    }
    assert "D1" not in schema["properties"]["decisions"]["properties"]
    original["decisions"][0]["id"] = "case-specific-id"
    assert table == original


def test_judge_rules_example_obeys_the_canonical_schema() -> None:
    rules = (skillrun.SKILLS_ROOT / "judge-answer-table/rules.md").read_text()
    example = json.loads(rules.split("```json\n", 1)[1].split("```", 1)[0])
    Draft202012Validator(CANONICAL_SCHEMA).validate(example)


def test_nullable_wire_output_becomes_a_valid_canonical_judgment() -> None:
    wire = _wire()
    original = copy.deepcopy(wire)
    Draft202012Validator(provider_schema(synthetic_table())).validate(wire)
    normalized = omit_null_fields(wire)
    Draft202012Validator(CANONICAL_SCHEMA).validate(normalized)
    assert set(normalized["decisions"]) == {"D2"}
    assert normalized["decisions"]["D2"]["recommended"][0] == {
        "rowId": "D2.O1", "evidence": EVIDENCE,
        "partsPresent": ["Check A", "Check B"],
    }
    assert normalized["decisions"]["D2"]["unmatched"][0]["provisional"] == {
        "outcome": "partly",
    }
    assert wire == original
    data = {
        "omit": None, "false": False, "zero": 0, "empty": "", "array": [],
        "object": {}, "nested": [{"quote": EVIDENCE, "omit": None}],
    }
    assert omit_null_fields(data) == {
        "false": False, "zero": 0, "empty": "", "array": [], "object": {},
        "nested": [{"quote": EVIDENCE}],
    }


@pytest.mark.parametrize("change", [
    lambda wire: wire["decisions"].update(unknown=None),
    lambda wire: wire["decisions"].pop("D1"),
    lambda wire: wire["decisions"]["D2"]["recommended"][0].update(evidence=None),
    lambda wire: wire["decisions"]["D2"]["recommended"][0].update(rowId=None),
    lambda wire: wire["decisions"]["D2"].update(contradiction="false"),
    lambda wire: wire.update(offRubric=None),
])
def test_wire_schema_rejects_unknown_missing_or_invalid_fields(change: Any) -> None:
    wire = _wire()
    change(wire)
    with pytest.raises(ValidationError):
        Draft202012Validator(provider_schema(synthetic_table())).validate(wire)


def test_run_skill_forwards_schema_and_suffix_but_preserves_raw_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "judge"
    folder.mkdir()
    (folder / "system.md").write_text("SYS")
    (folder / "prompt.md").write_text("Response: {{response}}")
    (folder / "schema.json").write_text(json.dumps(CANONICAL_SCHEMA))
    schema = provider_schema(synthetic_table())
    raw = json.dumps(_wire(), indent=2)
    seen: dict[str, Any] = {}

    def fake_call(backend: str, model: str, system: str, prompt: str, **kwargs: Any) -> Any:
        seen.update(backend=backend, model=model, system=system, prompt=prompt, kwargs=kwargs)
        return backends.CallResult(raw, {"json_schema_enforced": True})

    monkeypatch.setattr(backends, "call", fake_call)
    monkeypatch.setattr(skillrun, "SKILLS_ROOT", tmp_path)
    outcome = skillrun.run_skill(
        "judge", {"response": EVIDENCE}, "openai", "gpt-6.1-sol", json_schema=schema, reasoning_effort="medium",
        prompt_suffix="Use null for omitted fields.", normalize_output=omit_null_fields,
    )
    assert outcome.status == "pass" and outcome.errors == []
    assert outcome.raw == raw
    assert outcome.output == omit_null_fields(_wire())
    assert outcome.provenance["json_schema_enforced"] is True
    assert outcome.provenance["output_normalization"] == "omit_null_fields"
    assert seen["backend"] == "openai" and seen["model"] == "gpt-6.1-sol"
    assert seen["system"] == "SYS"
    assert seen["prompt"].startswith(f"Response: {EVIDENCE}")
    assert seen["prompt"].endswith("Use null for omitted fields.")
    assert seen["kwargs"] == {"json_schema": schema, "reasoning_effort": "medium"}


def _unknown_decision(wire: dict[str, Any]) -> None:
    wire["decisions"]["unknown"] = None


def _empty_evidence(wire: dict[str, Any]) -> None:
    wire["decisions"]["D2"]["recommended"][0]["evidence"] = ""


def test_run_skill_rejects_bad_wire_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "judge"
    folder.mkdir()
    (folder / "system.md").write_text("SYS")
    (folder / "prompt.md").write_text("PROMPT")
    (folder / "schema.json").write_text(json.dumps(CANONICAL_SCHEMA))
    wire_schema = provider_schema(synthetic_table())
    monkeypatch.setattr(skillrun, "SKILLS_ROOT", tmp_path)
    cases: list[tuple[str, Callable[[dict[str, Any]], None], bool]] = [
        # the wire schema rejects an unknown Decision before nulls are removed
        ("unknown Decision", _unknown_decision, False),
        # canonical validation still rejects empty evidence after normalization
        ("empty evidence", _empty_evidence, True),
    ]

    def run(case: tuple[str, Callable[[dict[str, Any]], None], bool]) -> None:
        _, change, normalizes = case
        wire = _wire()
        change(wire)
        raw = json.dumps(wire)
        normalized: list[Any] = []

        def normalize(value: Any) -> Any:
            normalized.append(value)
            return omit_null_fields(value)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(backends, "call", lambda *args, **kwargs: backends.CallResult(raw, {}))
            outcome = skillrun.run_skill(
                "judge", {}, "openai", "gpt-6.1-sol",
                json_schema=wire_schema, normalize_output=normalize,
            )
        assert outcome.status == "failed" and outcome.errors
        assert outcome.raw == raw
        if normalizes:
            assert any("schema:" in error for error in outcome.errors)
        else:
            assert normalized == []

    each_case(cases, lambda c: c[0], run)


def test_judge_flushes_each_completed_receipt_while_another_call_is_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_case(tmp_path)
    Project(tmp_path).update_provenance(models=["m"], trials=2)
    for trial, response in ((1, "first response"), (2, "second response")):
        append_jsonl(tmp_path / "results/responses/m.jsonl", {
            "id": "Syn002", "trial": trial, "response": response,
        })
    pending = threading.Event()
    release = threading.Event()
    failures: list[BaseException] = []
    written: list[Path] = []

    def fake_skill(name: str, variables: dict, backend: str, model: str, **kwargs: Any) -> Any:
        if variables["response"] == "second response":
            pending.set()
            if not release.wait(timeout=10):
                raise TimeoutError("test did not release the pending call")
        return skillrun.SkillOutcome("pass", {"decisions": {}, "offRubric": []}, "raw", [], {})

    def run() -> None:
        try:
            written.extend(jd.judge(tmp_path, "run1", "openai", "gpt-6.1-sol", workers=2))
        except BaseException as error:
            failures.append(error)

    monkeypatch.setattr(jd, "run_skill", fake_skill)
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert pending.wait(timeout=5), "the second call never started"
        receipt = tmp_path / "results/judge/m.jsonl"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if receipt.exists() and receipt.stat().st_size:
                break
            threading.Event().wait(timeout=0.01)
        assert worker.is_alive(), "judging finished before releasing the second call"
        rows = read_jsonl(receipt)
        assert len(rows) == 1 and rows[0]["trial"] == 1 and rows[0]["status"] == "pass"
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive() and failures == []
    assert len(written) == 1
    assert sorted(row["trial"] for row in read_jsonl(written[0])) == [1, 2]


def test_shared_pool_finishes_other_model_while_first_model_is_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_case(tmp_path)
    Project(tmp_path).update_provenance(models=["a", "b"], trials=1)
    for model in ("a", "b"):
        append_jsonl(tmp_path / f"results/responses/{model}.jsonl", {
            "id": "Syn002", "trial": 1, "response": model,
        })
    pending = threading.Event()
    release = threading.Event()
    failures: list[BaseException] = []

    def fake_skill(name: str, variables: dict, backend: str, model: str, **kwargs: Any) -> Any:
        if variables["response"] == "a":
            pending.set()
            if not release.wait(timeout=10):
                raise TimeoutError("test did not release model a")
        return skillrun.SkillOutcome("pass", {"decisions": {}, "offRubric": []}, "raw", [], {})

    def run() -> None:
        try:
            jd.judge(tmp_path, "run1", "openai", "gpt-6.1-sol", workers=2)
        except BaseException as error:
            failures.append(error)

    monkeypatch.setattr(jd, "run_skill", fake_skill)
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert pending.wait(timeout=5)
        receipt = tmp_path / "results/judge/b.jsonl"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if receipt.exists() and receipt.stat().st_size:
                break
            threading.Event().wait(timeout=0.01)
        assert worker.is_alive()
        assert len(read_jsonl(receipt)) == 1
        assert not (tmp_path / "results/judge/a.jsonl").exists()
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive() and failures == []
    assert len(read_jsonl(tmp_path / "results/judge/a.jsonl")) == 1


def make_partial_resume_run(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[str]]:
    """Eighteen completed calls, one failed quote, and two missing jobs."""
    seed_case(root)
    Project(root).update_provenance(models=["m"], trials=20)
    for trial in range(1, 19):
        append_jsonl(root / "results/responses/m.jsonl", {
            "id": "Syn002", "trial": trial, "response": f"synthetic response {trial}",
        })
    calls: list[str] = []

    def fake_call(backend: str, model: str, system: str, prompt: str, **kwargs: Any) -> Any:
        response = prompt.split("## Response\n\n", 1)[1].split("\n\nReturn one", 1)[0]
        calls.append(response)
        wire = {"decisions": {
            decision["id"]: None for decision in synthetic_table()["decisions"]
        }, "offRubric": []}
        wire["decisions"]["D1"] = {
            "recommended": [{
                "rowId": "D1.O1", "role": None,
                "evidence": "fabricated quote" if response == "synthetic response 1" else response,
                "partsPresent": None, "via": None,
            }], "contradiction": False, "unmatched": [],
        }
        return backends.CallResult(json.dumps(wire), {
            "backend": backend, "model": model, "reasoning_effort": kwargs["reasoning_effort"],
            "prompt_sha256": hashlib.sha256(f"{system}\n\n{prompt}".encode()).hexdigest(),
            "json_schema_enforced": True,
        })

    monkeypatch.setattr(backends, "call", fake_call)
    jd.judge(root, "run1", "openai", "gpt-6.1-sol", workers=24)
    for trial in (19, 20):
        append_jsonl(root / "results/responses/m.jsonl", {
            "id": "Syn002", "trial": trial, "response": f"synthetic response {trial}",
        })
    assert len(calls) == 18
    calls.clear()
    return root, calls


@pytest.fixture
def partial_resume_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[str]]:
    return make_partial_resume_run(tmp_path, monkeypatch)


def test_explicit_resume_skips_all_18_receipts_and_preserves_failed_quote(
    partial_resume_run: tuple[Path, list[str]],
) -> None:
    root, calls = partial_resume_run
    receipt = root / "results/judge/m.jsonl"
    original = receipt.read_bytes()
    old_rows = read_jsonl(receipt)
    assert sum(row["status"] == "failed" for row in old_rows) == 1
    written = jd.judge(
        root, "run1", "openai", "gpt-6.1-sol", workers=24, resume=True, timeout=45,
    )
    assert sorted(calls) == ["synthetic response 19", "synthetic response 20"]
    assert written == [receipt]
    assert receipt.read_bytes().startswith(original)
    new_rows = read_jsonl(receipt)
    assert len(new_rows) == 20
    assert new_rows[:18] == old_rows
    assert all(row["provenance"]["request_timeout_s"] == 45 for row in new_rows[18:])
    assert sum(row["status"] == "failed" for row in new_rows) == 1
    assert any("no passing judgment" in problem for problem in jd.judge_problems(root, written))


def _rewrite(path: Path, change: Callable[[list[dict[str, Any]]], None]) -> None:
    rows = read_jsonl(path)
    change(rows)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _stale(field: str) -> Callable[[Path], None]:
    def change_receipt(rows: list[dict[str, Any]]) -> None:
        target = rows[0]
        parts = field.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = "stale-value"
    return lambda root: _rewrite(root / "results/judge/m.jsonl", change_receipt)


def _changed_response(root: Path) -> None:
    _rewrite(root / "results/responses/m.jsonl", lambda rows: rows[0].update(response="changed source answer"))


def _duplicate_receipt(root: Path) -> None:
    receipt = root / "results/judge/m.jsonl"
    append_jsonl(receipt, read_jsonl(receipt)[0])


def _passing(change: Callable[[dict[str, Any]], None]) -> Callable[[Path], None]:
    def change_receipt(rows: list[dict[str, Any]]) -> None:
        change(next(row for row in rows if row["status"] == "pass"))
    return lambda root: _rewrite(root / "results/judge/m.jsonl", change_receipt)


def _first_quote(text: str) -> Callable[[dict[str, Any]], None]:
    return lambda row: row["judge"]["decisions"]["D1"]["recommended"][0].update(evidence=text)


def test_resume_refuses_before_any_calls(tmp_path: Path) -> None:
    no_longer_passes = "evidence checks|unresolved status"
    cases: list[tuple[str, Callable[[Path], None], str | None]] = [
        *[(f"stale {field}", _stale(field), None) for field in [
            "response_sha256", "rubric_sha256", "case_presentation_sha256",
            "provenance.prompt_sha256", "provenance.json_schema_sha256",
            "provenance.model", "provenance.reasoning_effort", "provenance.backend"]],
        ("changed response", _changed_response, None),
        ("duplicate receipt", _duplicate_receipt, "duplicate or unexpected"),
        ("invalid role", _passing(lambda row: row["judge"]["decisions"]["D1"]["recommended"][0].update(
            role="invalid-role")), "evidence checks"),
        ("fabricated evidence", _passing(_first_quote("a quote the response never made")), no_longer_passes),
        ("errors", _passing(lambda row: row.update(errors=["synthetic error"])), no_longer_passes),
        ("unresolved status", _passing(lambda row: row.update(status="pending")), no_longer_passes),
    ]

    def run(case: tuple[str, Callable[[Path], None], str | None]) -> None:
        label, change, match = case
        row_root = tmp_path / label.replace(" ", "-")
        row_root.mkdir()
        with pytest.MonkeyPatch.context() as mp:
            root, calls = make_partial_resume_run(row_root, mp)
            change(root)
            receipt = root / "results/judge/m.jsonl"
            before = receipt.read_bytes()
            with pytest.raises(ValueError, match=match):
                jd.judge(root, "run1", "openai", "gpt-6.1-sol", resume=True)
        assert calls == [] and receipt.read_bytes() == before

    each_case(cases, lambda c: c[0], run)


def _one_syn002_response(root: Path, mp: pytest.MonkeyPatch) -> Path:
    seed_case(root)
    Project(root).update_provenance(models=["m"])
    append_jsonl(root / "results/responses/m.jsonl", {
        "id": "Syn002", "trial": 1, "response": "synthetic response",
    })
    return root


def _two_invented_cases(root: Path, mp: pytest.MonkeyPatch) -> Path:
    from test_e2e_judge import make_synthetic_judge_run

    return make_synthetic_judge_run(root, mp)


def test_judge_route_kwargs(tmp_path: Path) -> None:
    cases: list[dict[str, Any]] = [
        *[{"label": f"{backend} timeout {configured}", "setup": _one_syn002_response, "backend": backend,
           "model": "synthetic", "kwargs": {"timeout": configured}, "calls": 1, "timeout": expected}
          for backend in ["openai", "openrouter"] for configured, expected in [(None, 120), (45, 45)]],
        *[{"label": f"{backend} keeps its own timeout", "setup": _one_syn002_response, "backend": backend,
           "model": "synthetic", "kwargs": {}, "calls": 1, "timeout": None} for backend in ["claude", "codex"]],
        {"label": "direct openai keeps medium effort", "setup": _two_invented_cases, "backend": "openai",
         "model": "gpt-6.1-sol", "kwargs": {"reasoning_effort": "medium"}, "calls": 2, "timeout": 120,
         "effort": "medium"},
    ]

    def run(case: dict[str, Any]) -> None:
        root = tmp_path / case["label"].replace(" ", "-")
        root.mkdir()
        calls: list[dict[str, Any]] = []

        def fake_skill(name: str, variables: dict, backend: str, model: str, **kwargs: Any) -> Any:
            calls.append({"backend": backend, "model": model, **kwargs})
            return skillrun.SkillOutcome("pass", {"decisions": {}, "offRubric": []}, "raw", [], {})

        with pytest.MonkeyPatch.context() as mp:
            case["setup"](root, mp)
            mp.setattr(jd, "run_skill", fake_skill)
            written = jd.judge(root, "run1", case["backend"], case["model"], workers=1, **case["kwargs"])
            assert len(written) == 1 and len(calls) == case["calls"]
            if case["timeout"] is None:
                assert "timeout" not in calls[0]
            else:
                assert calls[0]["timeout"] == case["timeout"]
                assert read_jsonl(written[0])[0]["provenance"]["request_timeout_s"] == case["timeout"]
            if "effort" in case:
                assert all((call["backend"], call["model"], call["reasoning_effort"])
                           == (case["backend"], case["model"], case["effort"]) for call in calls)
                assert jd.judge_problems(root, written) == []

    each_case(cases, lambda c: c["label"], run)
