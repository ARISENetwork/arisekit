"""Offline response collection: prompts, receipts, resume, and inference routes."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from cases import each_case

from pipeline import backends
from tools import run_inference as module
from tools.run_inference import assemble_prompt, input_binding, run_model
from arisekit.common.jsonio import read_jsonl


def test_assemble_prompt() -> None:
    cases = [("", "case text", "case text"), ("  \n", "case text", "case text"),
             ("Be concise.", "case", "Be concise.\n\ncase")]

    def run(case: tuple[str, str, str]) -> None:
        template, text, expected = case
        assert assemble_prompt(template, text) == expected

    each_case(cases, lambda c: repr(c[0]), run)


def test_run_model_writes_records_and_resumes(tmp_path, monkeypatch):
    caseset = tmp_path
    (caseset / "results" / "responses").mkdir(parents=True)
    items = [{"id": "Kit001", "prompt": "p1", "metadata": {}},
             {"id": "Kit001-0", "prompt": "p2", "metadata": {}}]
    calls = []

    def fake_completion(prompt):
        calls.append(prompt)
        return "resp:" + prompt, 1, {"total_tokens": 3}

    out = run_model(caseset, "openrouter/test/model", items, "",
                    completion_fn=fake_completion)
    recs = [json.loads(l) for l in out.read_text().splitlines()]
    assert [r["id"] for r in recs] == ["Kit001", "Kit001-0"]
    assert recs[0] == {"id": "Kit001", "trial": 1, "response": "resp:p1",
                       "runtime": 1, "usage": {"total_tokens": 3},
                       "model": "openrouter/test/model",
                       "input_sha256": input_binding("openrouter/test/model", "p1")}
    # resume: second invocation makes no new calls
    run_model(caseset, "openrouter/test/model", items, "",
              completion_fn=fake_completion)
    assert len(calls) == 2


@pytest.mark.parametrize("change", ["prompt", "template", "model", "legacy"])
def test_changed_success_refused_without_calls_or_writes(tmp_path, change):
    items = [{"id": "A", "prompt": "original"}]
    calls = []
    def call(prompt):
        calls.append(prompt)
        return "answer", 1, {}
    out = run_model(tmp_path, "a/b", items, "", completion_fn=call)
    model, template = "a/b", ""
    if change == "prompt":
        items[0]["prompt"] = "changed"
    elif change == "template":
        template = "new instruction"
    elif change == "model":
        model = "a-b"  # Same normalized filename, distinct model identity.
    else:
        row = json.loads(out.read_text())
        del row["input_sha256"]
        out.write_text(json.dumps(row) + "\n")
    before = out.read_bytes()
    with pytest.raises(ValueError, match="input binding"):
        run_model(tmp_path, model, items, template, completion_fn=call)
    assert calls == ["original"]
    assert out.read_bytes() == before


def test_failure_receipts_preserved_and_retry_resumes(tmp_path: Path) -> None:
    def raises(prompt: str) -> tuple[str, int, dict]:
        raise RuntimeError("synthetic failure")

    cases = [
        {"label": "completion raises", "model": "m", "prompt": "p", "fail": raises,
         "error": "synthetic failure"},
        {"label": "completion returns no text", "model": "model", "prompt": "synthetic",
         "fail": lambda p: (None, 1, {}), "error": "provider returned empty or non-text response"},
    ]

    def run(case: dict[str, Any]) -> None:
        root = tmp_path / case["label"].replace(" ", "-")
        root.mkdir()
        items = [{"id": "A", "prompt": case["prompt"]}]
        out = run_model(root, case["model"], items, "", completion_fn=case["fail"])
        assert read_jsonl(out)[0]["error"] == case["error"]
        run_model(root, case["model"], items, "", completion_fn=lambda p: ("answer", 1, {}))
        rows = [json.loads(line) for line in out.read_text().splitlines()]
        assert len(rows) == 2 and rows[0]["error"] == case["error"]
        assert rows[1]["response"] == "answer"
        assert [row["response"] for row in rows] == [None, "answer"]
        run_model(root, case["model"], items, "", completion_fn=case["fail"])
        assert len(out.read_text().splitlines()) == 2

    each_case(cases, lambda c: c["label"], run)


@pytest.mark.parametrize("successful", [0, 1, 2])
def test_cli_exit_uses_requested_coverage(tmp_path, monkeypatch, successful):
    from tools import run_inference as module
    (tmp_path / "items.jsonl").write_text(' {"id":"A","prompt":"p"}\n')
    monkeypatch.setattr(module, "load_env", lambda: None)
    calls = []
    def call(prompt):
        calls.append(prompt)
        if len(calls) > successful:
            raise RuntimeError("synthetic failure")
        return "answer", 1, {}
    monkeypatch.setattr(module, "litellm_completion", lambda model: call)
    monkeypatch.setattr("sys.argv", ["run_inference.py", str(tmp_path), "--model", "m", "--trials", "2"])
    if successful < 2:
        with pytest.raises(SystemExit) as exc:
            module.main()
        assert exc.value.code == 1
    else:
        module.main()
    assert json.loads((tmp_path / "provenance.json").read_text())["trials"] == 2


def test_cli_preflights_all_models_before_any_writes(tmp_path, monkeypatch):
    from tools import run_inference as module
    (tmp_path / "items.jsonl").write_text('{"id":"A","prompt":"p"}\n')
    out = tmp_path / "results" / "responses" / "z.jsonl"
    out.parent.mkdir(parents=True)
    out.write_text('{"id":"A","trial":1,"response":"old"}\n')
    monkeypatch.setattr(module, "load_env", lambda: None)
    monkeypatch.setattr(module, "litellm_completion", lambda model: pytest.fail("must not construct client"))
    monkeypatch.setattr("sys.argv", ["run_inference.py", str(tmp_path), "--model", "a", "--model", "z"])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert not (out.parent / "a.jsonl").exists()
    assert not (tmp_path / "provenance.json").exists()


def test_trial_expansion_only_calls_new_pairs(tmp_path):
    items = [{"id": "A", "prompt": "p"}]
    calls = []
    def call(prompt):
        calls.append(prompt)
        return "answer", 1, {}
    out = run_model(tmp_path, "m", items, "", completion_fn=call)
    run_model(tmp_path, "m", items, "", trials=2, completion_fn=call)
    assert len(calls) == 2
    before = out.read_bytes()
    with pytest.raises(ValueError, match="input binding"):
        run_model(tmp_path, "m", items, "", trials=1, completion_fn=call)
    assert out.read_bytes() == before and len(calls) == 2


def invoke(project: Path, monkeypatch: pytest.MonkeyPatch, model: str, backend: str,
           effort: str | None = None) -> None:
    monkeypatch.setattr(module, "load_env", lambda: None)
    monkeypatch.setattr(sys, "argv", ["run_inference", str(project), "--model", model,
                                     "--backend", backend,
                                     *([] if effort is None else ["--reasoning-effort", effort])])
    module.main()


@pytest.mark.parametrize(("backend", "model", "canonical", "effort"), [
    ("claude", "opus", "subscription", None),
    ("subscription", "sonnet", "subscription", None),
    ("codex", "gpt-6-astra", "codex", "high"),
    ("openrouter", "openai/gpt-6-astra", "openrouter", "medium"),
])
def test_cli_routes_and_resumes(tmp_path, monkeypatch, backend, model, canonical, effort):
    (tmp_path / "items.jsonl").write_text('{"id":"A","prompt":"synthetic question"}\n')
    (tmp_path / "provenance.json").write_text('{"trials":2}')
    calls = []
    provenance = {"backend": canonical, "resolved_model": "provider-version", "runtime_s": 1.25,
                  "usage": {"input_tokens": 9}, "attempts": [{"status": "success"}], "cost_usd": None}
    def fake_call(*args, **kwargs):
        calls.append((args, kwargs))
        declared = json.loads((tmp_path / "provenance.json").read_text())
        assert declared["inference"]["model_routes"][model]["backend"] == canonical
        return backends.CallResult("synthetic answer", provenance)
    monkeypatch.setattr(backends, "call", fake_call)
    invoke(tmp_path, monkeypatch, model, backend, effort)
    out = tmp_path / "results/responses" / f"{module.sanitize_model(model)}.jsonl"
    rows = read_jsonl(out)
    assert len(calls) == 2 and [r["trial"] for r in rows] == [1, 2]
    assert calls[0] == ((canonical, model, "", "synthetic question"),
                        {"timeout": 300, **({"reasoning_effort": effort} if effort else {})})
    assert rows[0]["provider_provenance"] == provenance
    assert rows[0]["runtime"] == 1.25 and rows[0]["usage"] == {"input_tokens": 9}
    before = out.read_bytes()
    invoke(tmp_path, monkeypatch, model, backend, effort)
    assert len(calls) == 2 and out.read_bytes() == before


def test_legacy_api_binding_is_unchanged():
    payload = {"version": 1, "model": "m", "messages": [{"role": "user", "content": "p"}]}
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert module.input_binding("m", "p") == expected
    assert module.input_binding("m", "p", backend="codex") != expected
    assert module.input_binding("m", "p", backend="claude") == module.input_binding("m", "p", backend="subscription")
    assert module.input_binding("m", "p", backend="codex", reasoning_effort="high") != module.input_binding("m", "p", backend="codex")


def test_mixed_routes_keep_prior_models_and_outputs(tmp_path, monkeypatch):
    (tmp_path / "items.jsonl").write_text('{"id":"A","prompt":"synthetic"}\n')
    monkeypatch.setattr(module, "litellm_completion", lambda model: lambda prompt: ("API answer", 1, {}))
    monkeypatch.setattr(backends, "call", lambda *a, **kw: backends.CallResult("subscription answer", {}))
    invoke(tmp_path, monkeypatch, "api-model", "api")
    first = tmp_path / "results/responses/api-model.jsonl"
    original = first.read_bytes()
    invoke(tmp_path, monkeypatch, "opus", "claude")
    invoke(tmp_path, monkeypatch, "gpt-6-astra", "codex", "high")
    invoke(tmp_path, monkeypatch, "other-api-model", "api")
    prov = json.loads((tmp_path / "provenance.json").read_text())
    assert prov["models"] == ["api-model", "gpt-6-astra", "opus", "other-api-model"]
    assert prov["inference"]["model_routes"]["gpt-6-astra"]["kwargs"] == {"reasoning_effort": "high"}
    assert first.read_bytes() == original


def test_route_changes_refused_even_after_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = [{"outcome": outcome, "change": change,
              "first_effort": None if (outcome, change) == ("interrupted", "backend") else "high"}
             for outcome in ("successful", "failed", "interrupted") for change in ("backend", "effort")]

    def run(case: dict[str, Any]) -> None:
        project = tmp_path / f"{case['outcome']}-{case['change']}"
        project.mkdir()
        (project / "items.jsonl").write_text('{"id":"A","prompt":"synthetic"}\n')

        def call(*args: Any, **kwargs: Any) -> backends.CallResult:
            if case["outcome"] == "failed":
                raise backends.BackendError("synthetic failure", raw="raw failure")
            if case["outcome"] == "interrupted":
                raise KeyboardInterrupt
            return backends.CallResult("answer", {})

        monkeypatch.setattr(backends, "call", call)
        out = project / "results/responses/gpt-6-astra.jsonl"
        if case["outcome"] == "successful":
            invoke(project, monkeypatch, "gpt-6-astra", "codex", case["first_effort"])
        elif case["outcome"] == "failed":
            with pytest.raises(SystemExit, match="1"):
                invoke(project, monkeypatch, "gpt-6-astra", "codex", case["first_effort"])
            assert read_jsonl(out)[0]["provider_raw"] == "raw failure"
        else:
            with pytest.raises(KeyboardInterrupt):
                invoke(project, monkeypatch, "gpt-6-astra", "codex", case["first_effort"])
        original = out.read_bytes() if out.exists() else None
        monkeypatch.setattr(backends, "call", lambda *a, **kw: pytest.fail("no dispatch"))
        with pytest.raises(SystemExit) as exc:
            invoke(project, monkeypatch, "gpt-6-astra", "api" if case["change"] == "backend" else "codex",
                   None if case["change"] == "backend" else "low")
        assert exc.value.code == 2
        if case["outcome"] == "interrupted":
            assert not out.exists()
        else:
            assert out.read_bytes() == original

    each_case(cases, lambda c: f"{c['outcome']} then {c['change']} change", run)


@pytest.mark.parametrize("response", [None, "", " \n", {"bad": "object"}, 123])
def test_invalid_output_retained_as_failure_then_retried(tmp_path, monkeypatch, response):
    items = [{"id": "A", "prompt": "synthetic"}]
    monkeypatch.setattr(backends, "call", lambda *a, **kw: backends.CallResult(response, {"usage": {"tokens": 1}}))
    out = module.run_model(tmp_path, "opus", items, "", backend="claude")
    rows = read_jsonl(out)
    assert rows[0]["response"] is None and "error" in rows[0]
    assert rows[0]["provider_provenance"]["usage"] == {"tokens": 1}
    monkeypatch.setattr(backends, "call", lambda *a, **kw: backends.CallResult("answer", {}))
    module.run_model(tmp_path, "opus", items, "", backend="subscription")
    assert len(read_jsonl(out)) == 2


@pytest.mark.parametrize("backend", ["api", "claude", "subscription"])
def test_unsupported_effort_rejected_before_writes(tmp_path, monkeypatch, backend):
    (tmp_path / "items.jsonl").write_text('{"id":"A","prompt":"synthetic"}\n')
    with pytest.raises(SystemExit) as exc:
        invoke(tmp_path, monkeypatch, "opus", backend, "high")
    assert exc.value.code == 2
    assert not (tmp_path / "provenance.json").exists()
    assert not (tmp_path / "results").exists()


def test_legacy_api_receipt_cannot_be_reused_on_subscription(tmp_path, monkeypatch):
    items = [{"id": "A", "prompt": "synthetic"}]
    out = module.run_model(tmp_path, "opus", items, "", completion_fn=lambda p: ("answer", 1, {}))
    original = out.read_bytes()
    monkeypatch.setattr(backends, "call", lambda *a, **kw: pytest.fail("no dispatch"))
    with pytest.raises(ValueError, match="changed inference route"):
        module.run_model(tmp_path, "opus", items, "", backend="claude")
    assert out.read_bytes() == original
