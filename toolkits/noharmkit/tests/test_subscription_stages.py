"""Offline subscription aliases, stage routing, and generation resume identities."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from cases import each_case
from conftest import seed_case, tagged_synthetic_table

from pipeline import skillrun
from pipeline.e2e.project import Project
from pipeline.e2e import committee as cm
from pipeline.e2e import generate as gen
from pipeline.e2e import judge as jd
from arisekit.common.hashing import json_sha256
from arisekit.common.jsonio import append_jsonl


def test_load_committee(tmp_path: Path) -> None:
    alias_source = ('[{"backend":"claude","model":"opus"},'
                    '{"backend":"codex","model":"gpt","reasoning_effort":"high"}]')
    cases = [
        {"label": "claude alias and codex", "source": alias_source, "expected": [
            {"backend": "subscription", "model": "opus"},
            {"backend": "codex", "model": "gpt", "reasoning_effort": "high"}]},
        {"label": "claude with effort", "source": json.dumps(
            [{"backend": "claude", "model": "opus", "reasoning_effort": "high"}]), "expected": ValueError},
        {"label": "subscription with effort", "source": json.dumps(
            [{"backend": "subscription", "model": "opus", "reasoning_effort": "high"}]), "expected": ValueError},
    ]

    def run(case: dict[str, Any]) -> None:
        path = tmp_path / case["label"].replace(" ", "-") / "committee.json"
        path.parent.mkdir()
        path.write_text(case["source"])
        if case["expected"] is ValueError:
            with pytest.raises(ValueError, match="reasoning-effort applies to codex"):
                cm.load_committee(path)
            return
        assert cm.load_committee(path) == case["expected"]
        assert path.read_text() == case["source"]

    each_case(cases, lambda c: c["label"], run)


def test_generate_forwards_effort_with_committee(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    committee = [{"backend": "codex", "model": "rater"}]
    seed_case(tmp_path, with_table=False)
    calls = []

    def fake(name: str, variables: dict, route: str, model: str, **kwargs: Any) -> skillrun.SkillOutcome:
        calls.append((route, kwargs.get("reasoning_effort")))
        return skillrun.SkillOutcome("pass", tagged_synthetic_table(), "raw", [], {})

    monkeypatch.setattr(gen, "run_skill", fake)
    monkeypatch.setattr(gen.Generation, "with_committee", lambda *args: args[-1])
    assert gen.generate(tmp_path, "Syn002", 1, "codex", "model", workers=1,
                        committee=committee, reasoning_effort="high") == ["pass"]
    assert calls == [("codex", "high")]


def test_generation_keeps_legacy_identity_without_effort(tmp_path: Path) -> None:
    seed_case(tmp_path, with_table=False)
    generation = gen.Generation(Project(tmp_path), "Syn002", "subscription", "opus", None, {})
    case, variables = generation.case, generation.variables
    legacy = {"version": 1, "case_id": "Syn002", "case": case, "backend": "subscription", "model": "opus",
              "variables": variables, "skill": {
                  name: hashlib.sha256((skillrun.SKILLS_ROOT / gen.SKILL / name).read_bytes()).hexdigest()
                  for name in ("system.md", "prompt.md", "schema.json")},
              "prompt": skillrun.render((skillrun.SKILLS_ROOT / gen.SKILL / "prompt.md").read_text(), variables),
              "committee": None}
    assert generation.identity == json_sha256(legacy)


def test_generation_effort_change_preserves_saved_evidence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_case(tmp_path, with_table=False)
    monkeypatch.setattr(gen, "run_skill", lambda *a, **k: skillrun.SkillOutcome(
        "pass", tagged_synthetic_table(), "raw", [], {}))
    assert gen.generate(tmp_path, "Syn002", 1, "codex", "model", workers=1) == ["pass"]
    paths = list((tmp_path / "answer-tables").iterdir())
    before = {path: path.read_bytes() for path in paths}
    monkeypatch.setattr(gen, "run_skill", lambda *a, **k: pytest.fail("must not call a provider"))
    with pytest.raises(ValueError, match="changed generation identity"):
        gen.generate(tmp_path, "Syn002", 1, "codex", "model", workers=1, reasoning_effort="high")
    assert {path: path.read_bytes() for path in paths} == before


def test_subscription_judge_omits_effort(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_case(tmp_path)
    append_jsonl(tmp_path / "results" / "responses" / "model.jsonl",
                 {"id": "Syn002", "trial": 1, "response": "synthetic response"})
    calls = []

    def fake(name: str, variables: dict, route: str, model: str, **kwargs: Any) -> skillrun.SkillOutcome:
        calls.append((route, kwargs.get("reasoning_effort")))
        return skillrun.SkillOutcome("pass", {}, "raw", [], {})

    monkeypatch.setattr(jd, "run_skill", fake)
    jd.judge(tmp_path, "run1", "subscription", "model", reasoning_effort="high", workers=1)
    assert calls == [("subscription", None)]
