"""Read-only audit of exact native evidence from earlier judge rules and the scorer, including unresolved results."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from cases import each_case

from pipeline.e2e import score, text_v2
from pipeline.e2e.import_rubric import import_rubric
from pipeline.e2e.project import Project
from arisekit.common.hashing import sha256
from arisekit.common.jsonio import append_jsonl, read_jsonl
from pipeline.e2e import text_v2_runtime
from tools.audit_text_v2_api import audit_project
from tools.run_inference import inference_route, input_binding

FIXTURES = Path(__file__).parent / "fixtures/text-v2"








def _coverage(kind: str, operation: str) -> Callable[[Project], None]:
    def change(project: Project) -> None:
        path = {"response": project.responses_path("test-benchmark"), "judgment": project.judgments_path("test-benchmark"),
                "score": project.scored_path("test-benchmark")}[kind]
        [record] = read_jsonl(path)
        path.write_text("" if operation == "missing" else (json.dumps(record) + "\n") * 2)
    return change




def test_audit_rejects_excluded_root_before_reading(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="excluded path"):
        audit_project(tmp_path / "holdout")
