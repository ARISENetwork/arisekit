"""Prospective text rubric generation uses current rules without rewriting legacy evidence."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, NoReturn

import pytest
from conftest import seed_case
from jsonschema import Draft202012Validator
from test_web_pipeline import team_config

from pipeline import backends, skillrun
from arisekit.common import llm
from pipeline.e2e import generate, text_v2, text_v2_rating, text_v2_runtime
from pipeline.e2e.generate_text_v2 import TextV2Generation
from pipeline.e2e.project import Project
from arisekit.common.jsonio import read_json
from tools import noharm
from tools import web_pipeline_teams as teams





@pytest.fixture
def project(tmp_path: Path) -> Project:
    seed_case(tmp_path, with_table=False)
    return Project(tmp_path)


def generator(project: Project, **kwargs: Any) -> TextV2Generation:
    return generate.make_generation(project, "Syn002", "codex", "test-model", None, kwargs, "text-v2")


def run(project: Project, **kwargs: Any) -> list[str]:
    return generate.generate(project.root, "Syn002", 1, "codex", "test-model", workers=1,
                             rubric_format="text-v2", **kwargs)


def transport(monkeypatch: pytest.MonkeyPatch, *outputs: Any) -> list[dict[str, Any]]:
    pending = iter(outputs)
    calls = []

    def fake_call(backend: str, model: str, system: str, prompt: str, **kwargs: Any) -> backends.CallResult:
        calls.append({"backend": backend, "model": model, "system": system, "prompt": prompt, "kwargs": kwargs})
        output = next(pending)
        if isinstance(output, Exception):
            raise output
        return backends.CallResult(json.dumps(output), {"backend": backend, "model": model,
                                                        "prompt_sha256": llm.prompt_sha256(system, prompt)})

    monkeypatch.setattr(backends, "call", fake_call)
    return calls






def test_cli_explicit_legacy_format_uses_unchanged_generation(
    project: Project, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from conftest import tagged_synthetic_table
    calls = transport(monkeypatch, tagged_synthetic_table())
    monkeypatch.setattr(noharm, "load_env", lambda: None)
    monkeypatch.setattr(sys, "argv", ["noharm", "generate", str(project.root), "--case", "Syn002", "--runs", "1",
                                      "--backend", "codex", "--model", "test-model", "--format", "answer-table"])
    noharm.main()
    assert '"harmOverrides": true' in calls[0]["prompt"]
    assert "format" not in project.table("Syn002", "run1")
    gen = generate.make_generation(project, "Syn002", "codex", "test-model", None, {}, "answer-table")
    assert type(gen) is generate.Generation and gen.skill_name == generate.SKILL
    assert gen.native_format == "answer-table"






def test_provider_failure_does_not_trigger_repair(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = transport(monkeypatch, RuntimeError("Synthetic provider failure"))
    assert run(project) == ["failed"] and len(calls) == 1
    assert not project.artifact("Syn002", "run1", "draft.json").exists()






def test_text_v2_team_identity_changes_with_rating_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A rating-rules change is covered end to end by
    # test_web_pipeline_text_v2.py::test_native_v2_changed_rating_rules_require_a_fresh_generation_identity.
    project = Project(tmp_path / "project")
    seed_case(project.root, with_table=False)
    skill_root = tmp_path / "skills"
    for name, files in {
        "generate-text-v2": ("system.md", "prompt.md", "schema.json", "contract-v2.md", "authoring-rules.md"),
        "rate-text-v2": ("system.md", "prompt.md", "schema.json"),
    }.items():
        folder = skill_root / name
        folder.mkdir(parents=True)
        for filename in files:
            (folder / filename).write_bytes(skillrun.skill_file(name, filename).read_bytes())
    rules = tmp_path / "rating-rules.md"
    rules.write_bytes(text_v2_rating.AUTHORING_RULES.read_bytes())
    monkeypatch.setattr(skillrun, "SKILLS_ROOT", skill_root)
    monkeypatch.setattr(text_v2_rating, "AUTHORING_RULES", rules)

    identities: list[str] = []

    class IdentityCaptured(Exception):
        pass

    def capture_identity(_: Project, spec: dict[str, Any]) -> NoReturn:
        identities.append(spec["cases"]["Syn002"])
        raise IdentityCaptured

    def reject_call(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Identity preflight must not call a provider")

    monkeypatch.setattr(teams.durable, "_operation", capture_identity)
    monkeypatch.setattr(backends, "call", reject_call)
    action = {"stage": "generate", "rubricFormat": "text-v2"}
    config = team_config()["teams"]
    with pytest.raises(IdentityCaptured):
        teams._generate(project, action, config, None)
    target = skill_root / "rate-text-v2/prompt.md"
    target.write_bytes(target.read_bytes() + b"\nRevised rating contract.\n")
    with pytest.raises(IdentityCaptured):
        teams._generate(project, action, config, None)

    assert identities[0] != identities[1], "Changed rating prompt must invalidate the team generation identity"




def rating_output(record: dict[str, Any]) -> dict[str, Any]:
    return {"usualCare": {**record["usualCare"], "reason": "Synthetic rating fixture."},
            "decisions": {decision["id"]: {"recommendations": {
                item["id"]: {"score": item["score"], "harm": item["harm"], "reason": "Synthetic rating fixture."}
                for item in decision["recommendations"]}} for decision in record["decisions"]}}






