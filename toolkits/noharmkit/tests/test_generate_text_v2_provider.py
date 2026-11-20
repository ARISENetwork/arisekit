"""Native API generation enforces its wire schema before canonical validation."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import openai
import pytest
from cases import each_case
from conftest import seed_case
from jsonschema import Draft202012Validator

from pipeline import backends, skillrun
from pipeline.e2e.generate_text_v2 import TextV2Generation
from pipeline.e2e.project import Project
from arisekit.common.jsonio import read_json
from arisekit.common.schemas import schema_sha256




def transport(monkeypatch: pytest.MonkeyPatch, *outputs: dict[str, Any]) -> list[dict[str, Any]]:
    pending = iter(outputs)
    requests: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> SimpleNamespace:
        requests.append(kwargs)
        response = json.dumps(next(pending))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=response), finish_reason="stop")],
            usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 3, "completion_tokens": 2, "cost": 0.001}),
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: client)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    return requests


def generator(tmp_path: Path, backend: str) -> TextV2Generation:
    seed_case(tmp_path, with_table=False)
    model = "test/native" if backend == "openrouter" else "test-native"
    return TextV2Generation(Project(tmp_path), "Syn002", backend, model, None, {"reasoning_effort": "high"})




BAD_ID = "not-a-noharm-identifier"








def test_api_generation_identity_binds_the_effective_wire_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    gen = generator(tmp_path, "openrouter")
    original = gen.provider_schema

    def changed_schema() -> dict[str, Any]:
        schema = original()
        schema["properties"]["caseId"]["const"] = "Syn002"
        return schema

    monkeypatch.setattr(gen, "provider_schema", changed_schema)
    assert gen._identity() != gen.identity


