"""Real public command loops with only the provider transport boundary simulated."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import SYNTHETIC, tagged_synthetic_table

from pipeline import backends
from pipeline.e2e.committee import rated_decisions
from pipeline.e2e import committee, generate, judge, text_v2_runtime
from pipeline.e2e.constants import SKILLS_ROOT
from pipeline.e2e.project import Project, sanitize_model
from tools import noharm, run_inference
from arisekit.common.jsonio import read_jsonl


@pytest.mark.parametrize("author_backend", ["claude", "codex", "openrouter"])
def test_full_loop_with_mixed_subscriptions_resume_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, author_backend: str,
) -> None:
    project = tmp_path / "subscriptions"
    table = tagged_synthetic_table()
    complete: dict[str, Any] = {"decisions": {}, "offRubric": []}
    evidence = []
    for decision in table["decisions"]:
        row = next(r for r in decision["recommendations"] if r["score"] == 7 and not r.get("parts"))
        evidence.append(row["text"])
        complete["decisions"][decision["id"]] = {"recommended": [
            {"rowId": row["id"], "role": "first", "evidence": row["text"]},
        ]}
    answers = [" ".join(evidence), "No synthetic actions provided."]
    mappings = {answers[0]: complete, answers[1]: {"decisions": {}, "offRubric": []}}
    systems = {(SKILLS_ROOT / skill / "system.md").read_text(): stage for skill, stage in [
        (generate.SKILL, "generate"), (committee.SKILL, "rate"), (judge.SKILL, "judge"),
    ]}
    calls: list[tuple[str, str, str, dict]] = []
    candidate_counts = {"subscription": 0, "codex": 0}

    def transport(backend: str):
        def reply(model: str, system: str, prompt: str, **kwargs: Any) -> backends.CallResult:
            stage = systems.get(system, "candidate")
            calls.append((backend, model, stage, kwargs))
            if stage == "generate":
                output = json.dumps(table)
            elif stage == "rate":
                output = json.dumps({"usualCare": {"harm": "mild", "reason": "Synthetic"},
                    "decisions": {d["id"]: {"harm": "mild", "reason": "Synthetic"}
                                  for d in rated_decisions(table)}})
            elif stage == "judge":
                response = prompt.split("## Response\n\n", 1)[1].split("\n\nReturn one JSON object:", 1)[0]
                output = json.dumps(mappings[response])
            else:
                # Collection receives only the supplied question, never the expert reference.
                case = json.loads((SYNTHETIC / "Syn002.json").read_text())
                assert system == "" and prompt == case["presentation"]
                candidate_counts[backend] += 1
                count = candidate_counts[backend]
                if backend == "subscription" and count == 1:
                    raise backends.BackendError("Synthetic transport failure", raw="Synthetic failure receipt")
                selected = (count == 3) if backend == "subscription" else (count != 2)
                output = answers[int(selected)]
            return backends.CallResult(output, {"backend": backend, "model": model,
                "resolved_model": f"{model}-synthetic-version", "runtime_s": 0.25,
                "usage": {"input_tokens": 1, "output_tokens": 1}, "cost_usd": None})
        return reply

    for backend in ("subscription", "codex", "openrouter"):
        monkeypatch.setitem(backends.TRANSPORTS, backend, SimpleNamespace(call=transport(backend)))
    monkeypatch.setattr(noharm, "load_env", lambda: None)
    monkeypatch.setattr(run_inference, "load_env", lambda: None)
    monkeypatch.setattr(run_inference, "litellm_completion", lambda model: pytest.fail("subscription fell back to API"))

    def stage(*args: str) -> None:
        monkeypatch.setattr(sys, "argv", ["noharm", *args])
        noharm.main()

    def collect(backend: str, model: str, effort: str | None = None) -> None:
        monkeypatch.setattr(sys, "argv", ["run_inference", str(project), "--backend", backend, "--model", model,
                                         *([] if effort is None else ["--reasoning-effort", effort])])
        run_inference.main()

    stage("create", str(project), "--trials", "3")
    Project(project).update_provenance(judge_scoring_source_commit=text_v2_runtime.CURRENT_COMMIT)
    stage("import", str(project), "--case", "Syn002", "--cases-dir", str(SYNTHETIC))
    route = ["--backend", author_backend]
    if author_backend != "claude":
        route += ["--reasoning-effort", "medium"]
    generation = ["generate", str(project), "--case", "Syn002", "--runs", "1", "--format", "answer-table", *route]
    stage(*generation)
    before = len(calls)
    stage(*generation)
    assert len(calls) == before
    if author_backend == "claude":
        stage(*["subscription" if arg == "claude" else arg for arg in generation])
        assert len(calls) == before
    stage("rate", str(project), "--case", "Syn002", "--rubric", "run1", "--repeats", "1", *route)
    with pytest.raises(SystemExit) as exc:
        collect("claude", "opus")
    assert exc.value.code == 1
    collect("claude", "opus")
    collect("codex", "gpt-6-astra", "medium")
    before = len(calls)
    collect("subscription", "opus")
    collect("codex", "gpt-6-astra", "medium")
    assert len(calls) == before
    stage("judge", str(project), "--rubric", "run1", "--workers", "1", *route)
    stage("score", str(project))
    for model, mean in [("opus", 2 / 3), ("gpt-6-astra", 1 / 3)]:
        stem = sanitize_model(model)
        rows = read_jsonl(project / f"results/{stem}_scored.jsonl")
        assert sorted(r["trial"] for r in rows) == [1, 2, 3]
        assert sum(r["f1"] for r in rows) / 3 == pytest.approx(mean)
        responses = read_jsonl(project / f"results/responses/{stem}.jsonl")
        ready = [r for r in responses if "error" not in r]
        assert len(ready) == 3 and all(r["provider_provenance"]["resolved_model"] for r in ready)
    claude_rows = read_jsonl(project / "results/responses/opus.jsonl")
    assert claude_rows[0]["error"] == "Synthetic transport failure"
    assert claude_rows[0]["provider_raw"] == "Synthetic failure receipt"
    assert candidate_counts == {"subscription": 4, "codex": 3}
    expected_backend = "subscription" if author_backend == "claude" else author_backend
    defaults = {"subscription": "opus", "codex": "gpt-6-astra", "openrouter": "openai/gpt-6-astra"}
    judge_defaults = {"subscription": "opus", "codex": "gpt-6.1-sol", "openrouter": "openai/gpt-6.1-sol"}
    stage_calls = [c for c in calls if c[2] != "candidate"]
    assert all(backend == expected_backend and model == (judge_defaults if stage == "judge" else defaults)[backend]
               for backend, model, stage, _ in stage_calls)
    assert all(kwargs.get("reasoning_effort") == (None if expected_backend == "subscription" else "medium")
               for _, _, _, kwargs in stage_calls)
    assert (project / "results/report.md").is_file()
    if author_backend == "codex":
        before = len(calls)
        source = project / "answer-tables/Syn002.run1.json"
        source_bytes = source.read_bytes()
        with pytest.raises(SystemExit) as exc:
            stage(*["high" if arg == "medium" else arg for arg in generation])
        assert exc.value.code == 2 and len(calls) == before and source.read_bytes() == source_bytes


@pytest.mark.parametrize("arguments", [
    ["generate", "--case", "Syn002", "--backend", "codex", "--model", "opus"],
    ["judge", "--backend", "claude", "--model", "openai/gpt-6-astra"],
    ["generate", "--case", "Syn002", "--backend", "claude", "--reasoning-effort", "high"],
    ["generate", "--case", "Syn002", "--backend", "openrouter", "--model", "opus"],
    ["rate", "--case", "Syn002", "--rubric", "run1", "--backend", "codex", "--committee", "unused.json"],
    ["rate", "--case", "Syn002", "--rubric", "run1", "--model", "opus"],
])
def test_invalid_routes_stop_before_project_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arguments: list[str],
) -> None:
    project = tmp_path / "never-written"
    monkeypatch.setattr(noharm, "load_env", lambda: None)
    monkeypatch.setattr(sys, "argv", ["noharm", arguments[0], str(project), *arguments[1:]])
    with pytest.raises(SystemExit) as exc:
        noharm.main()
    assert exc.value.code == 2 and not project.exists()
