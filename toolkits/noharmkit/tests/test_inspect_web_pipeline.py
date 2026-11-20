"""Inspection refuses restricted project paths."""
from pathlib import Path

import pytest

from tools.inspect_web_pipeline import inspect_request


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
