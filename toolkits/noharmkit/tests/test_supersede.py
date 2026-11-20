"""Replacing responses collected for an earlier Task: what moves, what stays, and the confirmed collection path."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from arisekit.common.hashing import sha256
from arisekit.common.jsonio import read_json, read_jsonl
from test_response_prompt_collection import (
    entry,
    failure,
    new_project,
    request,
    save_prompts,
    success,
    team_config,
)
from test_web_pipeline import FakeOpenRouter

from pipeline import backends
from pipeline.e2e.project import Project
from tools import supersede
from tools.run_inference import route_binding

CASE = "Syn002"
CONFIG = team_config(prompts=["safety-first"])


def edit_task(project: Project, task: str, absolute: bool = False, changed: tuple[str, ...] = ("task",)) -> None:
    """What the app's Dataset page records on a case text edit (app/lib/dataset-edit.ts)."""
    source_path = project.root / "cases" / f"{CASE}.json"
    folder = project.root / "cases" / "history" / CASE / str(uuid.uuid4())
    folder.mkdir(parents=True)
    (folder / "source.json").write_bytes(source_path.read_bytes())
    responses = [{"model": path.stem, "id": row["id"], "trial": row.get("trial", 1), "response_sha256": sha256(row["response"])}
                 for path in sorted((project.results / "responses").glob("*.jsonl")) for row in read_jsonl(path)
                 ] if "task" in changed else []
    rubrics = [{"version": path.name[len(CASE) + 1:-len(".status.json")], "file_sha256": sha256(path.with_name(
        path.name.replace(".status.json", ".json")).read_bytes())}
               for path in sorted((project.root / "answer-tables").glob(f"{CASE}.*.status.json"))]
    prior = str(folder / "source.json") if absolute else str((folder / "source.json").relative_to(project.root))
    source = read_json(source_path)
    edits = source.get("source_provenance", {}).get("edits", [])
    source["presentation"] = task
    source["source_provenance"] = {**source.get("source_provenance", {}), "edits": [
        *edits, {"edited_at": "2026-11-07T00:00:00Z", "changed": list(changed), "prior_source": prior, "rubrics": rubrics,
                 "responses": responses}]}
    if "task" in changed:
        source_path.write_text(json.dumps(source, indent=2) + "\n")
        items = [{**item, "prompt": task} if item["id"] == CASE else item for item in project.items()]
        project.items_path.write_text("".join(json.dumps(item) + "\n" for item in items))
    else:
        source["recommendations"] = task
        source_path.write_text(json.dumps(source, indent=2) + "\n")


def live_files(project: Project) -> dict[str, bytes]:
    return {str(path.relative_to(project.root)): path.read_bytes() for path in sorted(project.results.rglob("*")) if path.is_file()}


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeOpenRouter:
    fake = FakeOpenRouter()
    monkeypatch.setattr(backends, "TRANSPORTS", {"openrouter": fake})
    return fake


@pytest.fixture
def scored(tmp_path: Path, fake: FakeOpenRouter) -> Project:
    """A project with unprompted and prompted responses judged and scored, then its Task edited."""
    project = new_project(tmp_path / "project")
    save_prompts(project, entry("Safety first", "Think about patient safety first."))
    success(request(project, "generate", CONFIG))
    success(request(project, "responses", CONFIG))
    success(request(project, "responses", CONFIG, prompt="safety-first"))
    success(request(project, "judge", CONFIG, rubric="run1"))
    success(request(project, "score", CONFIG))
    return project


@pytest.mark.parametrize("absolute", [False, True])
def test_moves_every_set_byte_for_byte_and_a_second_run_does_nothing(scored: Project, absolute: bool) -> None:
    before = live_files(scored)
    edit_task(scored, "An edited synthetic task.", absolute)
    preview = supersede.replace_outdated(scored, dry_run=True)
    assert live_files(scored) == before
    assert preview["case_ids"] == [CASE]
    manifest = supersede.replace_outdated(scored)
    moved = {Path(entry["file"]).relative_to("results").parts[0] for entry in manifest["files"]}
    assert moved == {"responses", "judge", "test-response-a_scored.jsonl", "test-response-b_scored.jsonl",
                     "test-response-a+safety-first_scored.jsonl", "test-response-b+safety-first_scored.jsonl"}
    assert len(manifest["files"]) == 12
    for moved in manifest["files"]:
        assert (scored.root / moved["archived_as"]).read_bytes() == before[moved["file"]]
        assert not read_jsonl(scored.root / moved["file"])
    assert (scored.root / manifest["report"]).read_bytes() == before["results/report.md"]
    assert manifest["report"] in scored.report_path.read_text()
    assert set(before) <= set(live_files(scored)), "the app refuses runs that delete project files"
    assert scored.provenance()["superseded"][-1]["case_ids"] == [CASE]
    assert read_json(scored.root / scored.provenance()["superseded"][-1]["manifest"]) == manifest
    after = live_files(scored)
    assert supersede.replace_outdated(scored)["files"] == []
    assert live_files(scored) == after


def test_a_listed_response_that_matches_the_new_task_stays(scored: Project) -> None:
    edit_task(scored, "An edited synthetic task.")
    path = scored.responses_path("test-response-a")
    row = read_jsonl(path)[0]
    current = route_binding(row["model"], "An edited synthetic task.", row["route"])
    path.write_text(json.dumps({**row, "input_sha256": current}) + "\n")
    manifest = supersede.replace_outdated(scored, dry_run=True)
    assert "results/responses/test-response-a.jsonl" not in {entry["file"] for entry in manifest["files"]}
    assert "results/responses/test-response-b.jsonl" in {entry["file"] for entry in manifest["files"]}


def test_an_interrupted_move_finishes_on_the_next_run(scored: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    before = live_files(scored)
    edit_task(scored, "An edited synthetic task.")
    real = os.replace

    def stop_at_responses(source: Any, target: Any) -> None:
        if "/responses/" in str(target):
            raise OSError("interrupted")
        real(source, target)

    monkeypatch.setattr(supersede.os, "replace", stop_at_responses)
    with pytest.raises(OSError):
        supersede.replace_outdated(scored)
    assert all(read_jsonl(path) for path in (scored.results / "responses").glob("*.jsonl"))
    monkeypatch.setattr(supersede.os, "replace", real)
    second = supersede.replace_outdated(scored)
    assert {Path(entry["file"]).parent.name for entry in second["files"]} == {"responses"}
    assert all(not read_jsonl(path) for path in (scored.results / "responses").glob("*.jsonl"))
    archived = [path for path in (scored.results / "superseded").rglob("*.jsonl")]
    for name in ("judge/test-response-a.jsonl", "responses/test-response-a.jsonl"):
        assert any(path.read_bytes() == before[f"results/{name}"] for path in archived)


def test_collection_refuses_until_confirmed_then_the_case_runs_again(scored: Project, fake: FakeOpenRouter) -> None:
    assert "belongs to response collection or autograding" in failure(request(scored, "score", CONFIG, replaceOutdated=True))
    edit_task(scored, "An edited synthetic task.")
    assert "collected for an earlier Task" in failure(request(scored, "responses", CONFIG))
    calls = len(fake.calls)
    success(request(scored, "responses", CONFIG, replaceOutdated=True))
    assert len(fake.calls) == calls + 2
    assert (scored.results / "superseded").is_dir()
    success(request(scored, "responses", CONFIG, prompt="safety-first", replaceOutdated=True))
    success(request(scored, "generate", CONFIG, caseIds=[CASE]))
    success(request(scored, "judge", CONFIG, rubric="run2"))
    success(request(scored, "score", CONFIG))
    assert all(len(read_jsonl(path)) == 1 for path in scored.results.glob("*_scored.jsonl"))


def test_a_solution_edit_moves_only_autograding_then_the_new_rubric_is_judged(scored: Project, fake: FakeOpenRouter) -> None:
    before = live_files(scored)
    edit_task(scored, "An edited synthetic solution.", changed=("solutions",))
    success(request(scored, "generate", CONFIG, caseIds=[CASE]))
    assert supersede.replace_outdated(scored, dry_run=True, scope="responses")["files"] == []
    assert "made before the case text was edited" in failure(request(scored, "judge", CONFIG, rubric="run2"))
    success(request(scored, "judge", CONFIG, rubric="run2", replaceOutdated=True))
    (manifest,) = (scored.results / "superseded").glob("*/manifest.json")
    moved = {entry["file"] for entry in read_json(manifest)["files"]}
    assert moved == {name for name in before if "/judge/" in name or name.endswith("_scored.jsonl")}
    for name in (n for n in before if "/responses/" in n):
        assert (scored.root / name).read_bytes() == before[name]
    assert {row["rubric"] for path in (scored.results / "judge").glob("*.jsonl") for row in read_jsonl(path)} == {"run2"}
    success(request(scored, "score", CONFIG))
