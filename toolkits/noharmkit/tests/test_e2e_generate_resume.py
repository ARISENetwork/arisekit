"""Synthetic generation resume checks. No corpus inputs or model calls."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from cases import each_case
from conftest import tagged_synthetic_table

from pipeline import skillrun
from pipeline.e2e import generate as gen
from pipeline.e2e.project import Project
from arisekit.common.hashing import json_sha256


def seed_synthetic(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (root / "cases").mkdir()
    (root / "cases" / "Synthetic.json").write_text(json.dumps({
        "presentation": "A synthetic sorting task.", "recommendations": "Sort the blue tokens first."}))
    table = tagged_synthetic_table()
    table["caseId"] = "Synthetic"
    monkeypatch.setattr(gen, "table_errors", lambda record: [])
    monkeypatch.setattr(gen, "run_skill", lambda *a, **k: skillrun.SkillOutcome("pass", table, "raw", [], {}))
    return root


@pytest.fixture
def synthetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return seed_synthetic(tmp_path, monkeypatch)


def run(root: Path, **kwargs: Any) -> list[str]:
    return gen.generate(root, "Synthetic", kwargs.pop("runs", 1), kwargs.pop("backend", "subscription"),
                        kwargs.pop("model", "synthetic-model"), workers=1, **kwargs)


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in (root / "answer-tables").iterdir() if p.is_file()}


def forbid_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gen, "run_skill", lambda *a, **k: pytest.fail("unexpected model call"))
    monkeypatch.setattr(gen.committee_module, "rate_table", lambda *a, **k: pytest.fail("unexpected committee call"))


def test_resume_reuses_passes_and_retries_failures(synthetic: Path) -> None:
    assert run(synthetic) == ["pass"]
    before = snapshot(synthetic)
    with pytest.MonkeyPatch.context() as mp:
        forbid_calls(mp)
        assert run(synthetic) == ["pass"]
    assert snapshot(synthetic) == before
    Project(synthetic).artifact("Synthetic", "run1", "status.json").write_text('{"status":"failed"}')
    assert run(synthetic) == ["pass"]


def _change_plain_run(root: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    status_path = Project(root).artifact("Synthetic", "run1", "status.json")
    if change in {"binding", "historical"}:
        status = json.loads(status_path.read_text())
        status.pop("table_sha256" if change == "binding" else "generation_sha256")
        status_path.write_text(json.dumps(status))
    elif change in {"table", "schema_invalid"}:
        path = Project(root).artifact("Synthetic", "run1")
        table = json.loads(path.read_text())
        table["usualCare"]["harm"] = "invalid" if change == "schema_invalid" else "none"
        path.write_text(json.dumps(table))
        if change == "schema_invalid":
            status = json.loads(status_path.read_text())
            status["table_sha256"] = json_sha256(table)
            status_path.write_text(json.dumps(status))
    elif change == "case":
        (root / "cases" / "Synthetic.json").write_text(json.dumps({
            "presentation": "Changed synthetic task", "recommendations": "Sort red first"}))
    elif change in {"model", "backend"}:
        kwargs[change] = "codex" if change == "backend" else "changed"
    elif change == "committee":
        kwargs["committee"] = [{"backend": "subscription", "model": "synthetic-rater"}]
    elif change == "invalid":
        monkeypatch.setattr(gen, "table_errors", lambda record: ["synthetic validation failure"])
    elif change in {"missing table", "empty table"}:
        table = Project(root).artifact("Synthetic", "run1")
        if change == "missing table":
            table.unlink()
        else:
            table.write_text("")
    else:
        skill_root = root / "skills"
        target = skill_root / gen.SKILL
        target.mkdir(parents=True)
        for filename in ("system.md", "prompt.md", "schema.json"):
            (target / filename).write_bytes((skillrun.SKILLS_ROOT / gen.SKILL / filename).read_bytes())
        path = target / ("schema.json" if change == "schema" else f"{change}.md")
        path.write_bytes(path.read_bytes() + b"\n")
        monkeypatch.setattr(skillrun, "SKILLS_ROOT", skill_root)
    return kwargs


def _change_committee_run(root: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> dict[str, Any]:
    committee = [{"backend": "subscription", "model": "synthetic-rater"}]
    monkeypatch.setattr(gen.Generation, "with_committee", lambda *a: a[-1])
    run(root, committee=committee)
    if change == "settings":
        committee = [{**committee[0], "reasoning_effort": "high"}]
    elif change == "scale":
        monkeypatch.setattr(gen.committee_module, "harm_scale_text", lambda: "changed scale")
    else:
        skill_root = root / "skills"
        for skill in (gen.SKILL, gen.committee_module.SKILL):
            target = skill_root / skill
            target.mkdir(parents=True)
            for filename in ("system.md", "prompt.md", "schema.json"):
                (target / filename).write_bytes((skillrun.SKILLS_ROOT / skill / filename).read_bytes())
        path = skill_root / gen.committee_module.SKILL / ("schema.json" if change == "schema" else f"{change}.md")
        path.write_bytes(path.read_bytes() + b"\n")
        monkeypatch.setattr(skillrun, "SKILLS_ROOT", skill_root)
    return {"committee": committee}


def test_resume_refuses_changed_inputs(tmp_path: Path) -> None:
    plain = ["table", "binding", "historical", "case", "model", "backend", "committee", "invalid", "schema_invalid",
             "prompt", "system", "schema", "missing table", "empty table"]
    cases = [*[("plain", change) for change in plain],
             *[("committee", change) for change in ["settings", "prompt", "system", "schema", "scale"]]]

    def run_case(case: tuple[str, str]) -> None:
        initial, change = case
        root = tmp_path / f"{initial}-{change}".replace(" ", "-")
        root.mkdir()
        with pytest.MonkeyPatch.context() as mp:
            seed_synthetic(root, mp)
            if initial == "committee":
                kwargs = _change_committee_run(root, mp, change)
            else:
                run(root)
                kwargs = _change_plain_run(root, mp, change)
            before = snapshot(root)
            forbid_calls(mp)
            with pytest.raises(ValueError, match="Cannot resume"):
                run(root, **kwargs)
            assert snapshot(root) == before

    each_case(cases, lambda c: f"{c[0]} run, changed {c[1]}", run_case)


def test_all_passed_slots_preflight_before_writes(synthetic: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run(synthetic, runs=2)
    # Slot one needs regeneration, but slot two's historic pass is unbound.
    Project(synthetic).artifact("Synthetic", "run1", "status.json").write_text('{"status":"failed"}')
    Project(synthetic).artifact("Synthetic", "run2", "status.json").write_text('{"status":"pass"}')
    before = snapshot(synthetic)
    forbid_calls(monkeypatch)
    with pytest.raises(ValueError, match="run2"):
        run(synthetic, runs=3)
    assert snapshot(synthetic) == before


def test_retries_preserve_all_failed_artifact_bytes_before_calls(
    synthetic: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = Project(synthetic).rubric_files("Synthetic", "run1")
    paths[0].parent.mkdir()
    original = {path.name: payload for path, payload in zip(paths, [
        b"not JSON\r\n", b'{ "status": "failed" }\r\n', b"opaque ratings\x00", b"old raw\r\n"])}
    for path in paths:
        path.write_bytes(original[path.name])
    history = synthetic / "answer-tables/history/Synthetic.run1"

    def retry(*args: object, **kwargs: object) -> skillrun.SkillOutcome:
        [saved] = history.iterdir()
        assert {path.name: path.read_bytes() for path in saved.iterdir()} == original
        assert not any(path.exists() for path in paths)
        return skillrun.SkillOutcome("failed", None, None, ["provider failure"], {})

    monkeypatch.setattr(gen, "run_skill", retry)
    assert run(synthetic) == ["failed"]
    first = next(history.iterdir())
    first_before = {path.name: path.read_bytes() for path in first.iterdir()}
    current_status = Project(synthetic).artifact("Synthetic", "run1", "status.json").read_bytes()
    monkeypatch.setattr(gen, "run_skill", lambda *a, **k:
                        skillrun.SkillOutcome("failed", None, "new raw", ["parse failure"], {}))
    assert run(synthetic) == ["failed"]
    assert {path.name: path.read_bytes() for path in first.iterdir()} == first_before
    [second] = [folder for folder in history.iterdir() if folder != first]
    assert {path.name: path.read_bytes() for path in second.iterdir()} == {
        "Synthetic.run1.status.json": current_status}
    assert not Project(synthetic).artifact("Synthetic", "run1").exists()
    assert not Project(synthetic).artifact("Synthetic", "run1", "ratings.json").exists()


def test_generation_does_not_replace_evidence_created_during_call(
    synthetic: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Project(synthetic).artifact("Synthetic", "run1")

    def concurrent_receipt(*args: object, **kwargs: object) -> skillrun.SkillOutcome:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"another worker's opaque evidence")
        return skillrun.SkillOutcome("pass", {"caseId": "Synthetic"}, "new raw", [], {})

    monkeypatch.setattr(gen, "run_skill", concurrent_receipt)
    with pytest.raises(FileExistsError):
        run(synthetic)
    assert path.read_bytes() == b"another worker's opaque evidence"


def test_generation_checks_later_slots_before_archiving_failed_evidence(
    synthetic: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = Project(synthetic).artifact("Synthetic", "run1", "status.json")
    status.parent.mkdir()
    status.write_bytes(b'{"status":"failed"}\n')
    before = status.read_bytes()
    bad = synthetic / "answer-tables/Synthetic.run2.raw.txt"
    bad.symlink_to(synthetic / "missing-target")
    forbid_calls(monkeypatch)
    with pytest.raises(ValueError, match="storage path"):
        run(synthetic, runs=2)
    assert status.read_bytes() == before
    assert not (synthetic / "answer-tables/history").exists()


@pytest.mark.parametrize("redirect", ["raw", "status", "table", "ratings", "history"])
def test_generation_refuses_redirected_storage_before_calls_or_archives(
    synthetic: Path, monkeypatch: pytest.MonkeyPatch, redirect: str,
) -> None:
    (synthetic / "answer-tables").mkdir()
    target = synthetic / "safe-target"
    if redirect == "history":
        target.mkdir()
        link = synthetic / "answer-tables/history"
        link.symlink_to(target, target_is_directory=True)
    else:
        target.write_bytes(b"saved opaque evidence")
        suffix = {"table": "json", "status": "status.json", "ratings": "ratings.json", "raw": "raw.txt"}[redirect]
        link = synthetic / f"answer-tables/Synthetic.run1.{suffix}"
        link.symlink_to(target)
    before = target.read_bytes() if target.is_file() else list(target.iterdir())
    forbid_calls(monkeypatch)
    with pytest.raises(ValueError, match="storage path"):
        run(synthetic)
    assert link.is_symlink()
    assert (target.read_bytes() if target.is_file() else list(target.iterdir())) == before
