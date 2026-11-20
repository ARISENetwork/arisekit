"""Model calls that must return JSON: call_json validates one reply; run_skill renders a skill folder's prompt first."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline import backends
from pipeline.backends import CallProvenance
from pipeline.e2e.constants import SKILLS_ROOT
from arisekit.common.jsonio import duplicate_keys, extract_json, read_json
from arisekit.common.schemas import schema_errors, schema_sha256

PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def skill_file(skill: str, name: str) -> Path:
    """A file in a versioned skill folder, resolved at call time so tests can swap SKILLS_ROOT."""
    return SKILLS_ROOT / skill / name


@dataclass
class SkillOutcome:
    """One JSON model call's result: status "pass" or "failed"; failures are recorded, never raised, with the raw reply."""
    status: str
    output: Any
    raw: str | None
    errors: list[str]
    provenance: CallProvenance


def render(template: str, variables: dict[str, str]) -> str:
    missing = sorted(set(PLACEHOLDER.findall(template)) - set(variables))
    if missing:
        raise ValueError(f"unfilled placeholders: {missing}")
    return PLACEHOLDER.sub(lambda m: variables[m.group(1)], template)


def call_json(backend: str, model: str, system: str, prompt: str, schema: dict[str, Any],
              check: Callable[[Any], list[str]] | None = None,
              normalize_output: Callable[[Any], Any] | None = None,
              reject_duplicate_keys: bool = False, provenance: dict[str, Any] | None = None,
              **backend_kwargs: Any) -> SkillOutcome:
    """Call a backend for one JSON reply, then parse, validate against `schema`, and run `check`.

    Failures are returned, never raised: errors name the failing step, and the raw reply is kept.
    `provenance` leads the record.
    """
    prov: dict[str, Any] = {**(provenance or {}), "backend": backend, "model": model}
    wire_schema = backend_kwargs.get("json_schema")
    raw, output, step = None, None, "call"
    try:
        result = backends.call(backend, model, system, prompt, **backend_kwargs)
        raw, prov = result.text, {**(provenance or {}), **result.provenance}
        if wire_schema is not None:
            prov["json_schema_sha256"] = schema_sha256(wire_schema)
        step = "parse"
        output = extract_json(raw)
        if normalize_output is not None:
            if errors := schema_errors(wire_schema, output, "provider schema") if wire_schema is not None else []:
                return SkillOutcome("failed", output, raw, errors, prov)
            step = "normalize"
            output = normalize_output(output)
            prov["output_normalization"] = normalize_output.__name__
        errors = schema_errors(schema, output)
        if not errors and check is not None:
            step = "check"
            errors = check(output)
        if not errors and reject_duplicate_keys:
            errors = [f"duplicate key {k}" for k in duplicate_keys(raw)]
    except Exception as e:  # noqa: BLE001 recorded as a failed run with whatever the model returned
        return SkillOutcome("failed", output, getattr(e, "raw", raw), [f"{step}: {type(e).__name__}: {e}"], prov)
    return SkillOutcome("failed" if errors else "pass", output, raw, errors, prov)


def skill_prompt(name: str, variables: dict[str, str], prompt_suffix: str = "") -> tuple[str, str]:
    """The system prompt and rendered prompt one skill folder sends; resume checks rebuild them the same way."""
    prompt = render(skill_file(name, "prompt.md").read_text(), variables)
    if prompt_suffix:
        prompt += "\n\n" + prompt_suffix
    return skill_file(name, "system.md").read_text(), prompt


def run_skill(name: str, variables: dict[str, str], backend: str, model: str,
              check: Callable[[Any], list[str]] | None = None, prompt_suffix: str = "",
              normalize_output: Callable[[Any], Any] | None = None, reject_duplicate_keys: bool = False,
              **backend_kwargs: Any) -> SkillOutcome:
    """Render one skill folder's prompt and run it through call_json against the folder's schema."""
    system, prompt = skill_prompt(name, variables, prompt_suffix)
    return call_json(backend, model, system, prompt, read_json(skill_file(name, "schema.json")),
                     check=check, normalize_output=normalize_output, reject_duplicate_keys=reject_duplicate_keys,
                     provenance={"skill": name}, **backend_kwargs)
