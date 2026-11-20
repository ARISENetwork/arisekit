"""Saved response prompts and the identity of prompted response sets."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from arisekit.common.hashing import sha256
from cases import each_case

from pipeline.e2e.project import Project
from pipeline.e2e.response_prompts import (
    UNPROMPTED_SHA256,
    load_prompts,
    prompt_id,
    set_id,
    set_prompt,
    set_template,
    used_prompts,
)

TEXT = "Think about patient safety first."
APP_FIXTURE = Path(__file__).parent / "fixtures" / "response-prompts" / "prompts.json"


def entry(name: str, text: str = TEXT, sha: str | None = None) -> dict:
    return {"id": prompt_id(name), "name": name, "text": text, "sha256": sha or sha256(text), "savedAt": "2026-11-06T00:00:00Z"}


def write_prompts(project: Project, *entries: dict) -> None:
    (project.root / "prompts.json").write_text(json.dumps({"version": 1, "prompts": list(entries)}))


def declare(project: Project, set_prompts: dict) -> None:
    project.update_provenance(inference={"set_prompts": set_prompts})


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return Project.create(tmp_path / "p")


def test_prompt_and_set_ids() -> None:
    cases: list[tuple[str, Callable[[], str], str]] = [
        ("prompt id slugs punctuation", lambda: prompt_id("Safety first!"), "safety-first"),
        ("prompt id collapses spaces", lambda: prompt_id("  Step  by step "), "step-by-step"),
        ("unprompted set id is the model", lambda: set_id("openai/gpt-x", None), "openai/gpt-x"),
        ("prompted set id", lambda: set_id("openai/gpt-x", "safety-first"), "openai/gpt-x+safety-first"),
    ]

    def run(case: tuple[str, Callable[[], str], str]) -> None:
        _, actual, expected = case
        assert actual() == expected

    each_case(cases, lambda c: c[0], run)


def _no_file(project: Project) -> None:
    pass


def _one_entry(project: Project) -> None:
    write_prompts(project, entry("Safety first"))


def _app_fixture(project: Project) -> None:
    (project.root / "prompts.json").write_text(APP_FIXTURE.read_text())


def _equal(actual: object, expected: object) -> None:
    assert actual == expected


def test_load_prompts_reads(tmp_path: Path) -> None:
    cases: list[tuple[str, Callable[[Project], None], Callable[[dict[str, Any]], None]]] = [
        ("missing file is empty", _no_file, lambda prompts: _equal(prompts, {})),
        ("keys by id", _one_entry, lambda prompts: _equal(prompts["safety-first"]["text"], TEXT)),
        ("app format", _app_fixture, lambda prompts: (
            _equal(list(prompts), ["safety-first"]), _equal(prompts["safety-first"]["text"], "Think safely."))),
    ]

    def run(case: tuple[str, Callable[[Project], None], Callable[[dict[str, Any]], None]]) -> None:
        label, setup, check = case
        project = Project.create(tmp_path / label.replace(" ", "-"))
        setup(project)
        check(load_prompts(project))

    each_case(cases, lambda c: c[0], run)


def test_load_prompts_refuses(tmp_path: Path) -> None:
    cases: list[tuple[str, Callable[[Project], None], str | None]] = [
        ("tampered hash", lambda p: write_prompts(p, entry("Safety first", sha="0" * 64)), "safety-first"),
        ("duplicate ids", lambda p: write_prompts(p, entry("Safety first"), entry("safety-first")), "duplicate"),
        ("invalid JSON", lambda p: (p.root / "prompts.json").write_text("{not json"), None),
        ("entry missing fields", lambda p: (p.root / "prompts.json").write_text(
            json.dumps({"version": 1, "prompts": [{"id": "x"}]})), None),
    ]

    def run(case: tuple[str, Callable[[Project], None], str | None]) -> None:
        label, setup, match = case
        project = Project.create(tmp_path / label.replace(" ", "-"))
        setup(project)
        with pytest.raises(ValueError, match=match):
            load_prompts(project)

    each_case(cases, lambda c: c[0], run)


def test_declared_set_prompts_and_templates(project: Project) -> None:
    assert UNPROMPTED_SHA256 == sha256("")
    assert set_prompt(project, "m") is None
    assert used_prompts(project) == set()
    assert set_template(project, "m", "legacy {x}") == "legacy {x}"

    write_prompts(project, entry("Safety first"))
    assert set_template(project, "m+safety-first", "legacy") == "legacy"

    declared = {"m+safety-first": {"id": "safety-first", "name": "Safety first", "sha256": sha256(TEXT)}}
    declare(project, declared)
    assert set_prompt(project, "m+safety-first") == declared["m+safety-first"]
    assert set_prompt(project, "m") is None
    assert used_prompts(project) == {"safety-first"}
    assert set_template(project, "m+safety-first", "legacy") == TEXT
    assert set_template(project, "m", "legacy") == "legacy"

    write_prompts(project, entry("Safety first", text="Edited after collection."))
    with pytest.raises(ValueError, match="safety-first"):
        set_template(project, "m+safety-first", "legacy")
