"""Rater slots derived from reviewed rubrics and model rating receipts."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from cases import each_case

from pipeline.e2e.pipeline_v2_slots import (
    _ratings_of,
    item_hashes,
    model_ratings_dir,
    shared_label,
    slot_set,
    text_sha256,
)
from pipeline.e2e.project import Project

FAMILIES = ("sol", "gemini", "opus")
USUAL, CHANGED = "usualCare", "C2/C2.1"


def keys(table: dict) -> list[str]:
    return list(item_hashes(table))






















SlotOrderCase = tuple[str, list[tuple[str, str, int]], str | None, list[str], list[str | None], int | None]






























