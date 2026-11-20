"""Recovery inspection uses native cache checks without provider calls or source writes."""
from __future__ import annotations

import copy
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from cases import each_case
from conftest import SYNTHETIC
from test_web_pipeline import CONFIG
from test_web_pipeline import team_config

from pipeline import backends
from pipeline.e2e import text_v2
from pipeline.e2e.project import Project
from arisekit.common.hashing import json_sha256, sha256
from arisekit.common.jsonio import read_json
from tools import web_pipeline as web
from tools.inspect_web_pipeline import inspect_request


def _snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): sha256(p.read_bytes()) for p in root.rglob("*") if p.is_file()}




def _request(project: Project, version: int, stage: str) -> dict[str, Any]:
    action = {"stage": stage}
    if stage == "generate":
        action["rubricFormat"] = "text-v2"
    elif stage in {"judge", "score"}:
        action["rubric"] = "run1"
    return {"project": str(project.root), "config": copy.deepcopy(CONFIG) if version == 1 else team_config(),
            "action": action}




def _partial_generation(project: Project) -> dict[str, Any]:
    request = _request(project, 2, "generate")

    def interrupt(event: dict[str, Any]) -> None:
        if event.get("phase") == "generation":
            raise RuntimeError("Simulated publication interruption")

    result = web.execute(request, interrupt)
    assert result["status"] == "failed"
    return request






def _partial_judging(project: Project) -> dict[str, Any]:
    for stage in ("generate", "responses"):
        assert web.execute(_request(project, 2, stage))["status"] == "completed"
    request = _request(project, 2, "judge")

    def interrupt(event: dict[str, Any]) -> None:
        if event.get("completed") == 1:
            raise RuntimeError("Simulated publication interruption")

    assert web.execute(request, interrupt)["status"] == "failed"
    return request






def _failed_status(receipt: dict[str, Any]) -> None:
    receipt["status"] = "failed"


def _altered_model(receipt: dict[str, Any]) -> None:
    receipt["provenance"]["model"] = "test/altered"
















def test_excluded_tree_is_blocked(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "holdout").mkdir()
    result = inspect_request({"project": str(root), "action": {}, "config": {}})
    assert result["status"] == "blocked"
    assert "restricted paths" in result["reason"]


def test_literal_excluded_path_is_rejected_before_filesystem_check(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_check(path: Path) -> bool:
        pytest.fail("An excluded literal path must be rejected before filesystem access")

    monkeypatch.setattr(Path, "is_dir", unexpected_check)
    result = inspect_request({"project": "/unopened/holdout/project", "action": {}, "config": {}})
    assert result["status"] == "blocked"
    assert "restricted paths" in result["reason"]




