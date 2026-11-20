"""Synthetic web stages exercise real persistence with fake OpenRouter transports for both rubric formats."""

from __future__ import annotations

import io
import json
import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from cases import each_case
from conftest import SYNTHETIC, tagged_synthetic_table

from pipeline import backends
from arisekit.common import llm
from pipeline.e2e import committee, judge, text_v2, text_v2_rating, text_v2_runtime
from pipeline.e2e.project import Project
from arisekit.common.jsonio import read_json, read_jsonl
from arisekit.common.schemas import schema_sha256
from tools import web_pipeline as web

CONFIG = {
    "version": 1,
    "generationModel": "test/generator",
    "ratingModels": [],
    "responseModels": ["test/response-a", "test/response-b"],
    "judgeModel": "test/judge",
}
FIXTURES = Path(__file__).parent / "fixtures/text-v2"
ROLE = {"plan": "first", "addOn": "addOn", "alternative": "alternative", "later": "fallback"}
GENERATORS = ["test/generator", "test/generator-b", "test/generator"]


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




def rating_output(record: dict[str, Any]) -> dict[str, Any]:
    def pair(row: dict[str, Any]) -> dict[str, Any]:
        return {"score": row["score"], "harm": row["harm"], "reason": "Synthetic interface test rating."}
    return {"usualCare": pair(record["usualCare"]), "decisions": {
        d["id"]: {"recommendations": {r["id"]: pair(r) for r in d["recommendations"]}}
        for d in record["decisions"]}}


def reading(record: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    return {"profile": text_v2.scorer.PROFILE, "caseId": "Syn002",
            "rubricSha256": text_v2.scorer.rubric_sha256(record), "offRubric": [],
            "decisions": {d["id"]: {
                "applicability": {"state": "applicable", "basis": "always", "evidence": "",
                                  "rationale": "Hand-labeled scorer fixture, not clinical review."},
                "contradiction": {"present": False, "evidence": []}, "unmatched": [], "counselingRows": {},
                "recommended": [{"rowId": rid, "role": ROLE[role], "completeness": "complete",
                                 "actionable": True, "missing": "", "evidence": answer["text"]}
                                for rid, role in answer["matches"].get(d["id"], [])]}
                          for d in record["decisions"]}}














def success(value: dict[str, Any]) -> dict[str, Any]:
    result = web.execute(value)
    assert result["status"] == "completed", result
    return result




def row_dir(tmp_path: Path, label: str) -> Path:
    return tmp_path / re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-")


Check = Callable[[Project, FakeOpenRouter], None]
Fault = Callable[[FakeOpenRouter, pytest.MonkeyPatch], Callable[[], None]]




def no_fault(fake: FakeOpenRouter, monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    return lambda: None


def edit_replies(edit: Callable[[str, str, dict[str, Any], llm.Reply], None]) -> Fault:
    """Fault that rewrites provider replies; edit receives system, prompt, request options and the reply."""
    def install(fake: FakeOpenRouter, monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
        original = fake.request

        def edited(*args: Any, **kwargs: Any) -> llm.Reply:
            reply = original(*args, **kwargs)
            edit(args[1], args[2], kwargs, reply)
            return reply

        monkeypatch.setattr(fake, "request", edited)

        def clear() -> None:
            fake.request = original

        return clear
    return install


def flags(*names: str) -> Fault:
    """Fault that sets NativeProvider flags; clearing resets them."""
    def install(fake: FakeOpenRouter, monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
        for name in names:
            setattr(fake, name, True)

        def clear() -> None:
            for name in names:
                setattr(fake, name, False)

        return clear
    return install


def transport_failure(model: str) -> Fault:
    def install(fake: FakeOpenRouter, monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
        fake.fail = model

        def clear() -> None:
            fake.fail = None

        return clear
    return install


def rewrite_physician_author(change: Callable[[dict[str, Any]], None], *, skip: str | None = None) -> Fault:
    def edit(system: str, prompt: str, options: dict[str, Any], reply: llm.Reply) -> None:
        if "physician author" in system and (skip is None or skip not in system):
            output = json.loads(reply.text)
            change(output)
            reply.text = json.dumps(output)
    return edit_replies(edit)


def interrupt_at(phase: str) -> Callable[[dict[str, Any]], None]:
    def interrupt(event: dict[str, Any]) -> None:
        if event.get("phase") == phase:
            raise KeyboardInterrupt
    return interrupt
























@dataclass(frozen=True)
class SavedFailure:
    label: str
    config: Callable[[], dict[str, Any]]
    setup: list[str]
    stage: str
    fail: str
    options: dict[str, Any] | None = None
    clear: bool = True
    failed: Callable[[Project, FakeOpenRouter, dict[str, Any], int], None] = lambda *_: None










def _set(path: list[str], value: Any) -> Callable[[dict[str, Any]], None]:
    def change(team: dict[str, Any]) -> None:
        target = team
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return change




@dataclass(frozen=True)
class Refusal:
    label: str
    setup: Callable[[Project], dict[str, Any]]
    requests: list[tuple[str, dict[str, Any], str | None]]
    whole_snapshot: bool = True
    judgment_bytes: bool = False
























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


def generation_team(contributors: int, *, ratings: bool) -> dict[str, Any]:
    config = team_config()
    config["teams"]["generation"]["models"] = ["test/generator", "test/generator-b"][:contributors]
    if not ratings:
        config["teams"]["rating"] = {"models": [], "integrator": ""}
    return config


def one_rater_team() -> dict[str, Any]:
    config = team_config()
    config["teams"]["rating"] = {"models": ["test/rater-a"], "integrator": ""}
    return config








def _draft_issues_reach_integrator(output: dict[str, Any]) -> None:
    output["usualCare"]["harm"] = "none"


def _contributors_understate_usual_care() -> Fault:
    def edit(system: str, prompt: str, options: dict[str, Any], reply: llm.Reply) -> None:
        if "physician author" in system:
            if "Reconcile the independent" in system:
                assert '"draft_issues": [' in prompt
                assert "exceeds usual" in prompt
            else:
                output = json.loads(reply.text)
                output["usualCare"]["harm"] = "none"
                reply.text = json.dumps(output)
    return edit_replies(edit)






def _conditional_text(output: dict[str, Any]) -> None:
    output["decisions"][0]["recommendations"][0]["text"] = "Reassess if the synthetic problem persists."








def _missing_tags(output: dict[str, Any]) -> None:
    del output["decisions"][0]["recommendations"][0]["tags"]






def _severe_integrated_usual_care(system: str, prompt: str, options: dict[str, Any], reply: llm.Reply) -> None:
    if "rating potential patient harm" in system and "Reconcile the independent" in system:
        output = json.loads(reply.text)
        output["usualCare"]["harm"] = "severe"
        reply.text = json.dumps(output)










def judgment_config(contributors: int = 2) -> dict[str, Any]:
    config = team_config()
    config["teams"]["responses"] = {"models": ["test/response-a"], "integrator": ""}
    config["teams"]["judge"]["models"] = ["test/judge", "test/judge-b"][:contributors]
    if contributors == 1:
        config["teams"]["judge"]["modelReasoning"] = {"test/judge": "low"}
    return config


def judgment_candidate(valid: bool) -> dict[str, Any]:
    row = {
        "rowId": "D2.O1",
        "evidence": "synthetic model response" if valid else "fabricated evidence",
    }
    if valid:
        row["partsPresent"] = ["Check A"]
    return {"decisions": {"D2": {"recommended": [row]}}, "offRubric": []}




def _judge_replies(valid_from: str, repair_fault: str | None) -> Fault:
    """Judge members return an invalid candidate; the integrator or the repair returns the valid one."""
    def edit(system: str, prompt: str, options: dict[str, Any], reply: llm.Reply) -> None:
        if "answer-table judge" not in system:
            return
        integrated = "Reconcile the independent" in system
        repaired = "Repair the final judgment once" in system
        if valid_from == "integrator" and integrated:
            assert "evidence not in the response" in prompt
            assert "partsPresent is required" in prompt
        output = judgment_candidate(integrated if valid_from == "integrator" else repaired)
        if repaired and repair_fault is not None:
            row = output["decisions"]["D2"]["recommended"][0]
            if repair_fault == "quote":
                row["evidence"] = "fabricated evidence"
            elif repair_fault == "parts":
                row["partsPresent"] = ["Invented part"]
            else:
                output["decisions"] = []
        reply.text = json.dumps(provider_output(output, options["json_schema"]))
    return edit_replies(edit)




def _judge_repairs(fake: FakeOpenRouter) -> list[dict[str, Any]]:
    return [detail for detail in fake.details if "Repair the final judgment once" in detail["system"]]


def _null_optionals(system: str, prompt: str, options: dict[str, Any], reply: llm.Reply) -> None:
    if "answer-table judge" in system:
        output = provider_output(judgment_candidate(True), options["json_schema"])
        assert output["decisions"]["D1"] is None
        assert output["decisions"]["D2"]["contradiction"] is None
        assert output["decisions"]["D2"]["recommended"][0]["role"] is None
        reply.text = json.dumps(output)


def _null_required_harm(system: str, prompt: str, options: dict[str, Any], reply: llm.Reply) -> None:
    if "answer-table judge" in system:
        output = provider_output(
            {
                "decisions": {},
                "offRubric": [
                    {
                        "evidence": "synthetic model response",
                        "actionable": True,
                        "harm": None,
                    }
                ],
            },
            options["json_schema"],
        )
        reply.text = json.dumps(output)














