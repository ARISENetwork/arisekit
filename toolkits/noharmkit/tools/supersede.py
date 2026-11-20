"""Move outputs that an edit to the case text put out of date out of the live results.

Judgments (with their scores) qualify when they were made against a rubric the app shows as out of date: one an
edit listed by file hash, or a review based on one. A response row (with its judgment and score) qualifies only
when both hold:
- a Task edit recorded in cases/<id>.json source_provenance.edits lists it (file, item, trial, text hash), the
  rule the app uses for "Out of date: Task updated";
- its stored input binding is the binding of that edit's earlier Task, so the edit is what put it out of date.
Every other mismatch is left for collection or judging to refuse. Rows are copied byte for byte into
results/superseded/<time>/ and checked before the live files are rewritten without them. Responses are rewritten
last, so an interrupted move leaves them in place and running it again finishes the job."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from arisekit.common.hashing import sha256
from arisekit.common.jsonio import json_text, read_json
from arisekit.common.logs import now_iso

from pipeline.e2e.case_edits import case_edits, rubric_outdated
from pipeline.e2e.project import Pair, Project, record_pair, sanitize_model
from pipeline.e2e.response_prompts import set_template
from tools.run_inference import assemble_prompt, inference_route, route_binding


def _lines(path: Path) -> list[str]:
    return path.read_text().splitlines(keepends=True) if path.exists() else []


def _task_edits(project: Project, case_ids: list[str] | None) -> dict[str, list[dict[str, Any]]]:
    cases = sorted(path.stem for path in (project.root / "cases").glob("*.json")) if case_ids is None else case_ids
    edits = {}
    for case_id in cases:
        if task := [edit for edit in case_edits(project, case_id) if "task" in edit.get("changed", [])]:
            edits[case_id] = task
    return edits


def _earlier_task(project: Project, edit: dict[str, Any]) -> str:
    """The Task the case had before this edit, from the copy the app kept."""
    # Early edits stored an absolute path; only the part from cases/history on names the copy inside this project.
    parts = Path(edit["prior_source"]).parts
    starts = [index for index in range(len(parts) - 1) if parts[index:index + 2] == ("cases", "history")]
    if not starts or ".." in parts[starts[-1]:]:
        raise ValueError(f"Edit history is not inside the project: {edit['prior_source']}")
    return read_json(project.root.joinpath(*parts[starts[-1]:]))["presentation"]


def _eligible(project: Project, edits: dict[str, list[dict[str, Any]]]) -> dict[tuple[str, str, int], str]:
    """Live responses a Task edit put out of date: (file stem, item id, trial) -> case id."""
    bases = {item["id"]: item["metadata"]["base_id"] for item in project.items()}
    listed: dict[tuple[str, str, int, str], list[tuple[str, str]]] = {}
    for case_id, task_edits in edits.items():
        for edit in task_edits:
            earlier = _earlier_task(project, edit)
            for entry in edit.get("responses", []):
                if bases.get(entry["id"]) == case_id:
                    key = (entry["model"], entry["id"], entry["trial"], entry["response_sha256"])
                    listed.setdefault(key, []).append((case_id, earlier))
    found = {}
    for path in sorted((project.results / "responses").glob("*.jsonl")):
        template = None
        for line in _lines(path):
            if not line.strip():
                continue
            row = json.loads(line)
            item_id, trial = record_pair(row)
            if not isinstance(row.get("response"), str):
                continue
            candidates = listed.get((path.stem, item_id, trial, sha256(row["response"])), [])
            if not candidates:
                continue
            if template is None:
                # Prompts are recorded under the set name; the file name replaces its "/" and ":".
                names = [name for name in project.provenance().get("inference", {}).get("set_prompts", {})
                         if sanitize_model(name) == path.stem]
                template = set_template(project, names[0], "") if names else ""
            route = row.get("route", inference_route(row["model"]))
            for case_id, earlier in candidates:
                if row.get("input_sha256") == route_binding(row["model"], assemble_prompt(template, earlier), route):
                    found[(path.stem, item_id, trial)] = case_id
                    break
    return found


def _stale_judgments(project: Project, case_ids: list[str] | None) -> dict[tuple[str, str, int], str]:
    """Live judgments made against a rubric that an edit to the case text put out of date: key -> case id."""
    outdated: dict[tuple[str, str], bool] = {}
    found = {}
    for path in sorted((project.results / "judge").glob("*.jsonl")):
        for line in _lines(path):
            if not line.strip():
                continue
            row = json.loads(line)
            case_id, label = row.get("caseId"), row.get("rubric")
            if not isinstance(case_id, str) or not isinstance(label, str) or (case_ids is not None and case_id not in case_ids):
                continue
            if (case_id, label) not in outdated:
                outdated[(case_id, label)] = rubric_outdated(project, case_id, label)
            if outdated[(case_id, label)]:
                found[(path.stem, *record_pair(row))] = case_id
    return found


def _split(path: Path, moving: set[Pair]) -> tuple[list[str], list[str]]:
    kept, moved = [], []
    for line in _lines(path):
        (moved if line.strip() and record_pair(json.loads(line)) in moving else kept).append(line)
    return kept, moved


def replace_outdated(project: Project, case_ids: list[str] | None = None, dry_run: bool = False,
                     scope: Literal["responses", "judgments", "all"] = "all") -> dict[str, Any]:
    """Move outputs an edit to the case text put out of date, for the given cases (default: all): responses made
    from an earlier Task with their judgments and scores ("responses"), judgments made against an out-of-date
    rubric with their scores ("judgments"), or both. Returns the manifest; with dry_run, or when nothing
    qualifies, nothing is written."""
    found = _eligible(project, _task_edits(project, case_ids)) if scope != "judgments" else {}
    stale = _stale_judgments(project, case_ids) if scope != "responses" else {}
    by_stem: dict[str, dict[str, set[Pair]]] = {}
    for kinds, keys in ((("scored", "judgments", "responses"), found), (("scored", "judgments"), stale)):
        for stem, item_id, trial in keys:
            for kind in kinds:
                by_stem.setdefault(kind, {}).setdefault(stem, set()).add((item_id, trial))
    at = now_iso("microseconds")  # a rerun right after an interrupted move needs its own folder
    folder = project.results / "superseded" / at.replace(":", "")
    files, rewrites = [], []
    # Scores and judgments before responses: the responses still being live is what makes a rerun finish the move.
    for kind in ("scored", "judgments", "responses"):
        for stem, pairs in sorted(by_stem.get(kind, {}).items()):
            live = getattr(project, f"{kind}_path")(stem)
            kept, moved = _split(live, pairs)
            if not moved:
                continue
            relative = live.relative_to(project.results)
            files.append({"file": str(live.relative_to(project.root)), "archived_as": str((folder / relative).relative_to(project.root)),
                          "rows": [dict(zip(("id", "trial"), record_pair(json.loads(line))), line_sha256=sha256(line))
                                   for line in moved]})
            rewrites.append((live, folder / relative, kept, moved))
    cases = sorted({*found.values(), *stale.values()})
    report = project.report_path
    manifest = {
        "superseded_at": at, "reason": "case-text-edit", "case_ids": cases,
        "edits": {case_id: [edit["edited_at"] for edit in case_edits(project, case_id)] for case_id in cases},
        "files": files,
        **({"report": str((folder / "report.md").relative_to(project.root))} if files and report.exists() else {}),
    }
    if dry_run or not files:
        return manifest
    folder.mkdir(parents=True)
    for _, archived, _, moved in rewrites:
        archived.parent.mkdir(parents=True, exist_ok=True)
        with archived.open("x") as handle:
            handle.write("".join(moved))
        if archived.read_text() != "".join(moved):
            raise OSError(f"Archive copy does not match: {archived}")
    (folder / "manifest.json").write_text(json_text(manifest))
    history = project.provenance().get("superseded", [])
    project.update_provenance(superseded=[*history, {"at": at, "manifest": str((folder / "manifest.json").relative_to(project.root)),
                                                     "case_ids": cases}])
    if "report" in manifest:
        # The app refuses runs that delete project files, so the live report is replaced, not removed.
        archived = folder / "report.md"
        archived.write_bytes(report.read_bytes())
        if archived.read_bytes() != report.read_bytes():
            raise OSError(f"Archive copy does not match: {archived}")
        note = (f"# Report\n\nScores for {', '.join(cases)} were moved to {folder.relative_to(project.root)}/ "
                f"after the case text was edited (see manifest.json there). The earlier report is {manifest['report']}. "
                "Compute scores again to rebuild this report.\n")
        rewrites.insert(0, (report, archived, [note], []))
    for live, _, kept, _ in rewrites:
        temporary = live.with_name(live.name + ".superseding")
        temporary.write_text("".join(kept))
        os.replace(temporary, live)
    return manifest
