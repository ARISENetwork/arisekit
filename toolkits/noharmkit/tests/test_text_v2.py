import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.e2e import text_v2

FIXTURES = Path(__file__).parent / "fixtures/text-v2"
PARITY = json.loads((FIXTURES / "rubric-text-v2-parity.json").read_text())["cases"]


@pytest.mark.parametrize("fixture,mode", [
    pytest.param(row, mode, id=f"{mode}-{row['name']}")
    for row in PARITY
    for mode in ("scoring", "draft")
    if mode == "scoring" or row["draft"] != row["scoring"] or row["name"] == "valid synthetic case"
])
def test_upstream_validator_parity(fixture: dict[str, Any], mode: str) -> None:
    errors, warnings = text_v2.scorer.validate(fixture["case"], mode)
    assert errors == fixture[mode]["errors"]
    assert warnings == fixture[mode]["warnings"]
