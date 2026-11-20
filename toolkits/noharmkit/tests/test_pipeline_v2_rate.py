"""Route parsing and defaults for slot rating."""

import pytest
from cases import each_case

from pipeline.e2e import pipeline_v2_rate as rate


def test_defaults_match_decisions() -> None:
    d = rate.defaults()
    assert d["judge"] == {"backend": "openai", "model": "gpt-6.1-sol", "reasoning_effort": "high"}
    assert d["review"] == {"backend": "openrouter", "model": "anthropic/claude-opus-5.5", "reasoning_effort": "high"}
    assert d["raters"] == {"sol": {"backend": "codex", "model": "gpt-6.1-sol"},
                           "gemini": {"backend": "openrouter", "model": "google/gemini-4-argon",
                                      "reasoning_effort": "high"},
                           "opus": {"backend": "claude", "model": "claude-opus-5-5"}}


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
