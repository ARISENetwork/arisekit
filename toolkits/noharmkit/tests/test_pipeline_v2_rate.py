"""Slot rating: per-family calls for items that lack a current rating. No test calls a provider."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from cases import each_case
from test_pipeline_v2_slots import CHANGED

from pipeline.e2e import pipeline_v2_rate as rate
from pipeline.e2e.pipeline_v2_slots import (
    REPLACEMENT_ORDER,
    _ratings_of,
    item_hashes,
    model_ratings_dir,
    slot_set,
)
from pipeline.e2e.project import Project
from pipeline.skillrun import SkillOutcome

ROUTES = {f: {"backend": "codex", "model": f"m-{f}"} for f in REPLACEMENT_ORDER}












def test_defaults_match_decisions() -> None:
    d = rate.defaults()
    assert d["judge"] == {"backend": "openai", "model": "gpt-6.1-sol", "reasoning_effort": "high"}
    assert d["review"] == {"backend": "openrouter", "model": "anthropic/claude-opus-5.5", "reasoning_effort": "high"}
    assert d["raters"] == {"sol": {"backend": "codex", "model": "gpt-6.1-sol"},
                           "gemini": {"backend": "openrouter", "model": "google/gemini-4-argon",
                                      "reasoning_effort": "high"},
                           "opus": {"backend": "claude", "model": "claude-opus-5-5"}}














RefusalCase = tuple[str, Callable[[Project], None], dict[str, Any], str | None, str]




def test_parse_route() -> None:
    cases: list[tuple[str, tuple[str, dict] | None]] = [
        ("sol=codex/gpt-6.1-sol", ("sol", {"backend": "codex", "model": "gpt-6.1-sol"})),
        ("gemini=openrouter/google/gemini-4-argon@high",
         ("gemini", {"backend": "openrouter", "model": "google/gemini-4-argon", "reasoning_effort": "high"})),
        ("opus=claude/claude-opus-5-5", ("opus", {"backend": "claude", "model": "claude-opus-5-5"})),
        ("codex/gpt-6.1-sol", None),
        ("other=codex/x", None),
        ("sol=codex", None),
        ("opus=claude/claude-opus-5-5@high", None),
        ("sol=nope/x", None),
    ]

    def run(case: tuple[str, tuple[str, dict] | None]) -> None:
        spec, expected = case
        if expected is None:
            with pytest.raises(ValueError):
                rate.parse_route(spec)
        else:
            assert rate.parse_route(spec) == expected

    each_case(cases, lambda c: c[0], run)




