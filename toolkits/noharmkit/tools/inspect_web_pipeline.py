"""Inspect frozen web operations in a disposable copy without dispatching providers."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import backends
from pipeline.e2e import judge, project as project_storage, rubric, score, text_v2, text_v2_runtime
from pipeline.e2e.constants import KIT_ROOT
from pipeline.e2e.generate import Generation
from pipeline.e2e.project import Project
from arisekit.common import files, hashing, jsonio, logs, schemas
from arisekit.common.hashing import json_sha256, sha256
from arisekit.common.jsonio import read_json
from tools import score_answer_table, web_pipeline as durable, web_pipeline_teams as teams


class _SpecCaptured(BaseException):
    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec


class _WouldCallProvider(BaseException):
    pass


def _safe_tree(root: Path) -> list[Path]:
    if ("holdout" in str(root).lower() or root.is_symlink()
            or "holdout" in str(root.resolve()).lower()):
        raise ValueError("Inspection excludes restricted paths and symbolic links")
    files = []
    for path in root.iterdir():
        if "holdout" in path.name.lower() or path.is_symlink():
            raise ValueError("Inspection excludes restricted paths and symbolic links")
        files.extend(_safe_tree(path) if path.is_dir() else [path])
    return files


def _dispatch(project: Project, action: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    if config["version"] == 2:
        return teams.run_stage(project, action, config, None)
    if action["stage"] == "score":
        return durable._score(project, action, None)
    if action["stage"] == "responses":
        return durable._responses(project, config, None)
    return {"generate": durable._generate,
            "judge": durable._judge}[action["stage"]](project, action, config, None)


def _capture(project: Project, spec: dict[str, Any]) -> None:
    raise _SpecCaptured(spec)


def _no_provider(*args: Any, **kwargs: Any) -> None:
    raise _WouldCallProvider()


def _score_source_hashes(project: Project) -> dict[str, str]:
    modules = (durable, teams, score, judge, project_storage, rubric, text_v2, score_answer_table,
               text_v2.scorer, text_v2.scorer.v1, text_v2.scorer.legacy, files, hashing, jsonio, logs, schemas)
    paths = [Path(module.__file__) for module in modules]
    paths.extend(text_v2.scorer.PROFILE_DIR / "judge" / name for name in ("rules.md", "schema.json"))
    paths.extend(durable.skill_file(judge.SKILL, name) for name in ("system.md", "prompt.md", "rules.md", "schema.json"))
    adapter = text_v2_runtime.for_project(project)
    if adapter is not text_v2:
        from pipeline.e2e import noharm_j22_loader
        paths.extend([Path(adapter.__file__), Path(text_v2_runtime.__file__), Path(noharm_j22_loader.__file__),
                      *adapter.source_paths()])
    # Shared helpers live outside the kit, so their keys are ../-relative.
    return {os.path.relpath(path, KIT_ROOT): sha256(path.read_bytes()) for path in paths}


def _repairable_generation_draft(path: Path, folder: Path, version: int) -> bool:
    parts = path.relative_to(folder).parts
    if version == 1:
        return len(parts) == 2 and parts[1] == "draft.json"
    return (len(parts) == 3 and parts[1] == "generation"
            and (parts[2] == "integrator.json" or re.fullmatch(r"member-(0|[1-9][0-9]*)\.json", parts[2]) is not None))


def _wrapper_receipts(project: Project, folder: Path, *, native_generation: bool, version: int
                      ) -> tuple[set[Path], dict[Path, set[Path]]]:
    wrappers: set[Path] = set()
    references_by_path: dict[Path, set[Path]] = {}
    if not folder.exists():
        return wrappers, references_by_path
    for path in folder.rglob("*.json"):
        if path.name == "before-repair.json":
            continue
        saved = read_json(path)
        if (not isinstance(saved, dict) or set(saved) != {"binding", "sha256", "receipt"}
                or not isinstance(saved["receipt"], dict)
                or saved["sha256"] != json_sha256(saved["receipt"])):
            raise ValueError(f"Saved call receipt changed: {path.relative_to(project.root)}")
        receipt = saved["receipt"]
        repairable = (native_generation and _repairable_generation_draft(path, folder, version)
                      and receipt.get("status") == "failed" and receipt.get("output") is not None)
        if receipt.get("status") != "pass" and not repairable:
            raise ValueError(f"Saved call failed: {path.relative_to(project.root)}; use a new project/run")
        wrappers.add(path)
        references_by_path[path] = set()
        provenance = saved["receipt"].get("provenance", {})
        references = [*provenance.get("team_execution", {}).get("calls", []),
                      *provenance.get("rating_team", {}).get("calls", [])]
        references.extend(provenance.get("repair", {}).get(key) for key in ("candidate", "call")
                          if provenance.get("repair", {}).get(key))
        for reference in references:
            relative = Path(reference["path"])
            if relative.is_absolute() or ".." in relative.parts or "holdout" in str(relative).lower():
                raise ValueError("Saved call reference is outside the inspected project")
            content = read_json(project.root / relative)
            referenced = content["receipt"] if isinstance(content, dict) and "binding" in content else content
            if reference["sha256"] != json_sha256(referenced):
                raise ValueError(f"Saved call reference changed: {relative}")
            references_by_path[path].add(project.root / relative)
    return wrappers, references_by_path


def _inspect_copy(value: dict[str, Any]) -> dict[str, Any]:
    project, action, config = durable._request(value)
    durable._import_cases(project, value.get("importCases", []), None, action["stage"])
    if not project.expected():
        raise ValueError("Import cases before running the pipeline")
    if action["stage"] == "score":
        inputs = {str(p.relative_to(project.root)): sha256(p.read_bytes()) for p in _safe_tree(project.root)
                  if p.relative_to(project.root).parts[0] in {"cases", "answer-tables"}
                  or p.name in {"provenance.json", "items.jsonl"}
                  or p.parent.name in {"judge", "responses", "judge-reviews", "severe-review"}}
        identity = json_sha256({"action": action, "config": config, "inputs": inputs,
                                "sources": _score_source_hashes(project)})
        _dispatch(project, action, config)
        return {"status": "ready", "operationIdentity": identity, "reusableCalls": 0,
                "firstMissing": False, "pending": False}
    try:
        with patch.object(durable, "_operation", _capture):
            _dispatch(project, action, config)
    except _SpecCaptured as captured:
        spec = captured.spec
    identity = json_sha256(spec)
    journal = project.root / "web-execution" / f"{spec['stage']}-{identity}.json"
    if journal.exists():
        state = read_json(journal)
        if state.get("identity") != identity or state.get("spec") != spec:
            raise ValueError("The saved web operation has changed")
        if state.get("status") not in {"running", "completed"}:
            raise ValueError("Saved web operation failed; use a new project/run")
    folder = journal.with_suffix("")
    wrappers, references = _wrapper_receipts(
        project, folder, native_generation=action["stage"] == "generate" and action.get("rubricFormat") == "text-v2",
        version=config["version"],
    )
    validated: set[Path] = set()
    completed_cases: set[str] = set()
    original_read = read_json
    original_resume = Generation.resumable

    def tracked_read(path: Path) -> Any:
        result = original_read(path)
        if path in wrappers:
            validated.add(path)
        return result

    def tracked_resume(gen: Generation, run: int) -> bool:
        result = original_resume(gen, run)
        if result:
            completed_cases.add(gen.case_id)
        return result

    pending = False
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(durable, "read_json", tracked_read))
            stack.enter_context(patch.object(teams, "read_json", tracked_read))
            stack.enter_context(patch.object(Generation, "resumable", tracked_resume))
            _dispatch(project, action, config)
    except _WouldCallProvider:
        pending = True
    if pending:
        preserved = set(validated)
        while descendants := {child for parent in preserved for child in references.get(parent, set())} - preserved:
            preserved.update(descendants)
        unchecked = [p for p in wrappers - preserved if p.relative_to(folder).parts[0] not in completed_cases]
        if unchecked:
            raise ValueError("Saved calls exist after the first missing call and their bindings cannot be verified")
    return {"status": "ready", "operationIdentity": identity, "reusableCalls": len(validated),
            "firstMissing": pending, "pending": pending}


def inspect_request(value: Any) -> dict[str, Any]:
    """Inspect a normalized web request without changing its source project or reading provider secrets."""
    identity = None
    try:
        if not isinstance(value, dict) or not isinstance(value.get("project"), str):
            raise ValueError("Provide the normalized web pipeline request")
        if "holdout" in value["project"].lower():
            raise ValueError("Inspection excludes restricted paths and symbolic links")
        source = Path(value["project"])
        if not source.is_absolute() or not source.is_dir():
            raise ValueError("The inspection project must be an existing absolute directory")
        _safe_tree(source)
        with TemporaryDirectory(prefix="noharm-recovery-inspect-") as temporary:
            copied = Path(temporary) / source.name
            shutil.copytree(source, copied)
            with patch.object(backends, "call", _no_provider):
                result = _inspect_copy({**value, "project": str(copied)})
            identity = result["operationIdentity"]
            return result
    except Exception as error:
        return {"status": "blocked", "operationIdentity": identity, "reusableCalls": 0,
                "firstMissing": False, "pending": False, "reason": str(error)}


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
    except ValueError as error:
        request = None
        result = {"status": "blocked", "operationIdentity": None, "reusableCalls": 0,
                  "firstMissing": False, "pending": False, "reason": str(error)}
    else:
        result = inspect_request(request)
    print(json.dumps(result), flush=True)
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
