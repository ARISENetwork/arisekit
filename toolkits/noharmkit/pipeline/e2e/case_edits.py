"""Case text edits recorded by the app's Dataset page, and which rubrics they put out of date.

Mirrors app/lib/dataset-outdated.ts: an edit in cases/<id>.json source_provenance.edits lists every rubric file
that existed when the case text changed, by label and file hash; a reviewed rubric based on an out-of-date
rubric is out of date too."""
from __future__ import annotations

from typing import Any

from arisekit.common.hashing import sha256
from arisekit.common.jsonio import read_json

from pipeline.e2e.project import Project


def case_edits(project: Project, case_id: str) -> list[dict[str, Any]]:
    path = project.root / "cases" / f"{case_id}.json"
    return read_json(path).get("source_provenance", {}).get("edits", []) if path.exists() else []


def _file_sha256(project: Project, case_id: str, label: str) -> str | None:
    for suffix in ("json", "status.json"):
        path = project.artifact(case_id, label, suffix)
        if path.exists():
            return sha256(path.read_bytes())
    return None


def rubric_outdated(project: Project, case_id: str, label: str, _seen: frozenset[str] = frozenset()) -> bool:
    """Whether this rubric was made from case text that has since been edited."""
    edits = case_edits(project, case_id)
    if not edits or label in _seen:
        return False
    sha = _file_sha256(project, case_id, label)
    if any(r.get("version") == label and r.get("file_sha256") == sha for edit in edits for r in edit.get("rubrics", [])):
        return True
    if not label.startswith("reviewed-") or not project.artifact(case_id, label).exists():
        return False
    based_on = (read_json(project.artifact(case_id, label)).get("basedOn") or {}).get("version")
    return isinstance(based_on, str) and rubric_outdated(project, case_id, based_on, _seen | {label})
