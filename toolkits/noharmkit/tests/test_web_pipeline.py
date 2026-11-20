"""Shared fake provider and team configurations for offline pipeline tests."""
from __future__ import annotations

import json
import re
from typing import Any

from conftest import tagged_synthetic_table

from arisekit.common import llm
from pipeline import backends
from pipeline.e2e import committee


def provider_output(value: Any, schema: dict[str, Any] | None) -> Any:
    if schema is None or value is None:
        return value
    if "anyOf" in schema:
        return provider_output(
            value,
            next(option for option in schema["anyOf"] if option.get("type") != "null"),
        )
    if schema.get("type") == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        return {
            key: provider_output(value.get(key), child)
            for key, child in properties.items()
        } | {key: item for key, item in value.items() if key not in properties}
    if schema.get("type") == "array" and isinstance(value, list):
        return [provider_output(item, schema["items"]) for item in value]
    return value


class FakeOpenRouter(backends.Backend):
    name = "openrouter"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.details: list[dict[str, Any]] = []
        self.fail: str | None = None

    def request(
        self,
        model: str,
        system: str,
        prompt: str,
        *,
        json_schema: dict[str, Any] | None,
        **options: Any,
    ) -> llm.Reply:
        self.calls.append(model)
        self.details.append(
            {
                "model": model,
                "system": system,
                "prompt": prompt,
                "json_schema": json_schema,
                **options,
            }
        )
        if model == self.fail:
            raise backends.BackendError("Synthetic provider failure")
        if "physician author" in system:
            table = tagged_synthetic_table()
            table["caseId"] = re.search(r"record for case (\w+)\.", prompt)[1]
            text = json.dumps(table)
        elif "rating potential patient harm" in system:
            table = tagged_synthetic_table()
            text = json.dumps(
                {
                    "usualCare": {
                        "harm": table["usualCare"]["harm"],
                        "reason": "Synthetic rating",
                    },
                    "decisions": {
                        decision["id"]: {
                            "harm": decision.get("harmIfNotAddressedOverride", "none"),
                            "reason": "Synthetic rating",
                        }
                        for decision in committee.rated_decisions(table)
                    },
                }
            )
        elif "answer-table judge" in system:
            text = json.dumps(
                provider_output({"decisions": {}, "offRubric": []}, json_schema)
            )
        else:
            text = "A synthetic model response."
        return llm.Reply(
            text,
            {"prompt_tokens": 2, "completion_tokens": 3, "cost": 0.001},
            cost=0.001,
        )


def team_config() -> dict[str, Any]:
    return {
        "version": 2,
        "teams": {
            "generation": {
                "models": ["test/generator", "test/generator-b"],
                "integrator": "test/generator",
                "modelReasoning": {"test/generator": "low"},
                "integratorReasoning": {"test/generator": "high"},
            },
            "rating": {
                "models": ["test/rater-a", "test/rater-b"],
                "integrator": "test/rater-a",
                "modelReasoning": {"test/rater-a": "medium", "test/rater-b": "minimal"},
                "integratorReasoning": {"test/rater-a": "high"},
            },
            "responses": {
                "models": ["test/response-a", "test/response-b"],
                "integrator": "test/response-a",
                "modelReasoning": {"test/response-a": "none"},
                "integratorReasoning": {"test/response-a": "max"},
            },
            "judge": {
                "models": ["test/judge", "test/judge-b"],
                "integrator": "test/judge",
                "modelReasoning": {"test/judge": "low", "test/judge-b": "xhigh"},
                "integratorReasoning": {"test/judge": "high"},
            },
        },
    }
