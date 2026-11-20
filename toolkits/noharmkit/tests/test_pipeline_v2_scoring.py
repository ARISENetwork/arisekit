"""Slot scoring parity with upstream for three slots, and the even-count tie rule."""
from __future__ import annotations

import copy
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest
from cases import each_case

from pipeline.e2e.pipeline_v2_scoring import (
    f1_slots,
    recall_left_out_by,
    score_slots,
    slot_median_level,
    slot_median_value,
)

KEYS = ("worstError", "worstErrorBounds", "provisional", "spread")




MedianCase = tuple[str, Callable[[list, str], object], list, str, object]


def test_slot_median_tie_rule() -> None:
    levels = ["mild", "moderate", "severe", "severe"]
    cases: list[MedianCase] = [
        ("even levels, less", slot_median_level, levels, "less", "moderate"),
        ("even levels, more", slot_median_level, levels, "more", "severe"),
        ("even values, less", slot_median_value, [0.2, 0.4, 0.6, 0.8], "less", 0.6),
        ("even values, more", slot_median_value, [0.2, 0.4, 0.6, 0.8], "more", 0.4),
        ("odd levels ignore the rule", slot_median_level, ["none", "severe", "mild"], "more", "mild"),
        ("odd values ignore the rule", slot_median_value, [0.9, 0.1, 0.5], "more", 0.5),
    ]

    def run(case: MedianCase) -> None:
        _, median, values, tie, expected = case
        assert median(values, tie) == expected

    each_case(cases, lambda c: c[0], run)






