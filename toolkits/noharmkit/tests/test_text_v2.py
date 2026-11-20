from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from pipeline import backends
from arisekit.common import llm
from pipeline.e2e import judge, score, text_v2
from pipeline.e2e.import_rubric import import_rubric
from pipeline.e2e.project import Project
from pipeline.e2e.rubric import Rubric
from arisekit.common.jsonio import append_jsonl, read_jsonl

FIXTURES = Path(__file__).parent / "fixtures/text-v2"
PARITY = json.loads((FIXTURES / "rubric-text-v2-parity.json").read_text())["cases"]
ROLE = {"plan": "first", "addOn": "addOn", "alternative": "alternative", "later": "fallback"}






@pytest.mark.parametrize("fixture", PARITY, ids=lambda row: row["name"])
@pytest.mark.parametrize("mode", ["draft", "scoring"])
def test_upstream_validator_parity(fixture: dict[str, Any], mode: str) -> None:
    errors, warnings = text_v2.scorer.validate(fixture["case"], mode)
    assert errors == fixture[mode]["errors"]
    assert warnings == fixture[mode]["warnings"]
















