"""Text rubric model rating coverage, independent votes and strict prospective validation."""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from pipeline.e2e import text_v2_rating as rating
from pipeline.skillrun import SkillOutcome, skill_prompt

COMMITTEE = [{"backend": "openrouter", "model": "provider/one"},
             {"backend": "openrouter", "model": "provider/two"}]




def output(rubric: dict[str, Any]) -> dict[str, Any]:
    def pair(row: dict[str, Any]) -> dict[str, Any]:
        return {"score": row["score"], "harm": row["harm"], "reason": "Fixture clinical rationale."}
    return {"usualCare": pair(rubric["usualCare"]), "decisions": {
        d["id"]: {"recommendations": {r["id"]: pair(r) for r in d["recommendations"]}}
        for d in rubric["decisions"]}}


def rater(index: int, out: dict[str, Any] | None) -> dict[str, Any]:
    return {"rater": index, "status": "pass" if out else "failed", "missing": [], "output": out,
            "raw": json.dumps(out), "errors": [] if out else ["fixture provider failure"], "provenance": {}}






















def test_standalone_rejects_legacy_before_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from conftest import seed_case
    seed_case(tmp_path)
    monkeypatch.setattr(rating, "rate_table", lambda *args: pytest.fail("must preflight before provider calls"))
    with pytest.raises(ValueError, match="needs a rubric in the text rubric format"):
        rating.rate(tmp_path, "Syn002", "run1", 1, COMMITTEE)
