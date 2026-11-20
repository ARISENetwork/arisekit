"""Skill runner: render, call, parse, schema-check, custom check."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from cases import each_case

from pipeline import backends, skillrun


@pytest.fixture
def skill_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(skillrun, "SKILLS_ROOT", tmp_path)
    d = tmp_path / "echo"
    d.mkdir()
    (d / "system.md").write_text("SYS")
    (d / "prompt.md").write_text("Case: {{case}}")
    (d / "schema.json").write_text(json.dumps({
        "type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}}))
    return tmp_path


def _fake(text: str) -> Any:
    def call(backend: str, model: str, system: str, prompt: str, **kw: Any) -> backends.CallResult:
        assert system == "SYS" and prompt == "Case: X"
        return backends.CallResult(text, {"backend": backend, "model": model})
    return call


def test_render() -> None:
    with pytest.raises(ValueError, match="unfilled"):
        skillrun.render("{{a}} {{b}}", {"a": "1"})
    assert skillrun.render('{"x": {{a}}}', {"a": "1"}) == '{"x": 1}'


def test_run_skill_outcomes(monkeypatch: pytest.MonkeyPatch, skill_root: Path) -> None:
    def down(*a: Any, **k: Any) -> None:
        raise backends.BackendError("down", raw="partial")

    def check_raises(o: Any) -> list[str]:
        raise KeyError("rowId")

    unset = object()
    cases = [
        {"label": "pass", "call": _fake('{"n": 3}'), "check": None,
         "status": "pass", "output": {"n": 3}, "raw": unset, "errors": [], "prefix": None},
        {"label": "schema failure", "call": _fake('{"n": "three"}'), "check": None,
         "status": "failed", "output": unset, "raw": '{"n": "three"}', "errors": None, "prefix": "schema:"},
        {"label": "custom check after schema", "call": _fake('{"n": 3}'), "check": lambda o: ["too small"],
         "status": "failed", "output": unset, "raw": unset, "errors": ["too small"], "prefix": None},
        {"label": "call error", "call": down, "check": None,
         "status": "failed", "output": unset, "raw": "partial", "errors": ["call: BackendError: down"],
         "prefix": None},
        {"label": "unparseable output", "call": _fake("sorry"), "check": None,
         "status": "failed", "output": unset, "raw": unset, "errors": None, "prefix": "parse:"},
        {"label": "check exception keeps finished work", "call": _fake('{"n": 3}'), "check": check_raises,
         "status": "failed", "output": {"n": 3}, "raw": '{"n": 3}', "errors": ["check: KeyError: 'rowId'"],
         "prefix": None},
    ]

    def run(case: dict[str, Any]) -> None:
        monkeypatch.setattr(backends, "call", case["call"])
        kwargs = {} if case["check"] is None else {"check": case["check"]}
        out = skillrun.run_skill("echo", {"case": "X"}, "openrouter", "m", **kwargs)
        assert out.status == case["status"]
        if case["output"] is not unset:
            assert out.output == case["output"]
        if case["raw"] is not unset:
            assert out.raw == case["raw"]
        if case["errors"] is not None:
            assert out.errors == case["errors"]
        if case["prefix"] is not None:
            assert out.errors[0].startswith(case["prefix"])
        assert out.provenance["skill"] == "echo"

    each_case(cases, lambda c: c["label"], run)
