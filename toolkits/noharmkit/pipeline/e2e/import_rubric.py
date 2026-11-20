"""Import one supplied text rubric without changing existing project evidence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.e2e import text_v2, text_v2_runtime
from pipeline.e2e.project import Project, RUN_LABEL
from arisekit.common.files import check_destination
from arisekit.common.hashing import sha256
from arisekit.common.logs import now_iso


def import_rubric(project: Project, case_id: str, source: Path, version: str | None = None,
                  dry_run: bool = False) -> dict[str, Any]:
    if "holdout" in str(source).lower() or "holdout" in str(source.resolve()).lower():
        raise ValueError("This source path is excluded from rubric imports")
    if not project.root.is_dir() or not project.items_path.is_file():
        raise ValueError("Create a project and import its case before importing a rubric")
    cases = {item["metadata"]["base_id"] for item in project.items()}
    if case_id not in cases:
        raise ValueError(f"{case_id}: import this case before importing its rubric")
    raw = source.read_bytes()
    adapter = text_v2_runtime.for_project(project)
    envelope = json.loads(raw)
    record = text_v2.unwrap(envelope)
    if not text_v2.is_text_v2(record):
        raise ValueError(f"import-rubric requires a text rubric (format {text_v2.scorer.FORMAT})")
    errors, warnings = adapter.scorer.validate(record, "draft")
    if errors:
        raise ValueError("; ".join(map(text_v2_runtime.readable, errors)))
    if record["caseId"] != case_id:
        raise ValueError(f"rubric caseId {record['caseId']!r} does not match imported case {case_id!r}")
    if version is None:
        used = [int(match.group(1)) for path in (project.root / "answer-tables").glob(f"{case_id}.run*.json")
                if (match := RUN_LABEL.fullmatch(path.name.removeprefix(f"{case_id}.").removesuffix(".json")))]
        version = f"run{max(used, default=0) + 1}"
    if not RUN_LABEL.fullmatch(version):
        raise ValueError("Imported rubrics require a run<k> version; import does not create a human review")
    destinations = [project.artifact(case_id, version, suffix) for suffix in ("json", "status.json", "source.json")]
    for path in destinations:
        check_destination(project.root, path)
        if path.exists():
            raise FileExistsError(f"rubric artifact already exists: {path}; choose a new version")
    scoring_errors = adapter.scoring_errors(record)
    receipt = {"caseId": case_id, "version": version, "format": text_v2.scorer.FORMAT,
               "status": "draft" if scoring_errors else "pass", "errors": [], "warnings": warnings,
               "scoringErrors": scoring_errors, "scorer": "S2", "authority": "imported",
               "source": {"path": str(source), "sha256": sha256(raw)},
               "toolingSourceCommit": adapter.SOURCE_COMMIT}
    if not dry_run:
        project.write_new(destinations[0], record)
        project.write_new(destinations[2], {"importedAt": now_iso(), "source": receipt["source"],
                                           "content": raw.decode("utf-8"), "authority": "imported"})
        project.write_new(destinations[1], receipt)
    return {**receipt, "dryRun": dry_run, "path": str(destinations[0])}
