"""The portable teaching demo must reproduce its scores without model calls."""
from __future__ import annotations

import shutil
from pathlib import Path

from pipeline.e2e.score import score

DEMO = Path(__file__).resolve().parents[1] / "projects" / "demo"


def test_bundled_demo_scores_reproduce_from_stored_inputs(tmp_path: Path) -> None:
    copied = tmp_path / "demo"
    shutil.copytree(DEMO, copied)
    expected = {
        file.name: file.read_bytes()
        for file in (DEMO / "results").glob("*_scored.jsonl")
    }
    assert set(expected) == {"Model-A_scored.jsonl", "Model-B_scored.jsonl", "Model-C_scored.jsonl"}
    report, problems = score(copied)
    assert problems == []
    assert report is not None
    assert report.read_bytes() == (DEMO / "results" / "report.md").read_bytes()
    assert {
        file.name: file.read_bytes()
        for file in (copied / "results").glob("*_scored.jsonl")
    } == expected
