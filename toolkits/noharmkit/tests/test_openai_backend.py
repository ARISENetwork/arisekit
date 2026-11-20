"""Direct OpenAI endpoint, judge routing, and judge concurrency checks, without live calls."""
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import sys

import pytest
from cases import each_case
from conftest import seed_case

from pipeline import backends
from pipeline.backends import resolve_route
from pipeline.e2e import judge as judging
from pipeline.skillrun import SkillOutcome
from tools import noharm
from arisekit.common.jsonio import append_jsonl


def client_for(*replies: Any) -> tuple[Any, list[dict[str, Any]]]:
    seen = []

    def create(**kwargs: Any) -> Any:
        seen.append(kwargs)
        reply = replies[min(len(seen) - 1, len(replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply), finish_reason="stop")],
            usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 10, "completion_tokens": 5}),
            model="gpt-6.1-sol", _request_id="request-1", model_dump_json=lambda: "{}")

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), seen


def test_direct_openai_call(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    import openai
    client, calls = client_for('{"decisions": {}}')
    constructed = []
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unrelated.example")
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: constructed.append(kwargs) or client)
    out = backends.call("openai", "gpt-6.1-sol", "rules", "case", reasoning_effort="medium")
    assert constructed == [{"base_url": "https://api.openai.com/v1", "api_key": "fake-key",
                            "timeout": 600, "max_retries": 0}]
    assert calls == [{"model": "gpt-6.1-sol", "messages": [
        {"role": "system", "content": "rules"}, {"role": "user", "content": "case"}],
        "reasoning_effort": "medium"}]
    assert out.provenance["backend"] == "openai"
    assert out.provenance["request_id"] == "request-1"
    assert out.provenance["reasoning_effort"] == "medium"
    assert out.provenance["cost_usd"] is None

    error = openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1"))
    client, calls = client_for(error, "answer")
    sleeps = []
    out = backends.call("openai", "gpt-6.1-sol", "rules", "case", client=client, sleep=sleeps.append)
    assert len(calls) == 2 and sleeps == [5]
    assert out.provenance["attempts"] == 2 and len(out.provenance["retried_errors"]) == 1
    assert out.provenance["backend"] == "openai"


def test_direct_route_keeps_exact_model_and_effort() -> None:
    assert resolve_route("openai", "gpt-6.1-sol", "medium") == (
        "openai", "gpt-6.1-sol", {"reasoning_effort": "medium"})
    with pytest.raises(ValueError, match="direct OpenAI"):
        resolve_route("openai", "openai/gpt-6.1-sol", "medium")
    with pytest.raises(ValueError, match="direct OpenAI"):
        resolve_route("openai", "opus")


def test_cli_refuses_missing_api_key_before_judging(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools import noharm
    from pipeline.e2e import judge

    def missing_key(name: str) -> str:
        raise RuntimeError(f"{name} is not set")

    monkeypatch.setattr(noharm, "load_env", lambda: None)
    monkeypatch.setattr(noharm, "require", missing_key)
    monkeypatch.setattr(judge, "judge", lambda *args: pytest.fail("must not judge without credentials"))
    monkeypatch.setattr(sys, "argv", ["noharm", "judge", "unused", "--backend", "openai",
                                     "--model", "gpt-6.1-sol", "--reasoning-effort", "medium"])
    with pytest.raises(SystemExit) as error:
        noharm.main()
    assert error.value.code == 2


@pytest.mark.parametrize("backend,effort", [(None, None), (None, "low"), ("openai", "low")])
def test_cli_judge_defaults_and_effort_override(
    monkeypatch: pytest.MonkeyPatch, backend: str | None, effort: str | None,
) -> None:
    from tools import noharm
    from pipeline.e2e import judge

    calls = []

    def fake_judge(*args: Any, **kwargs: Any) -> list:
        calls.append(args)
        return []

    monkeypatch.setattr(noharm, "load_env", lambda: None)
    monkeypatch.setattr(noharm, "require", lambda name: "fake-key")
    monkeypatch.setattr(judge, "judge", fake_judge)
    monkeypatch.setattr(judge, "judge_problems", lambda *args: [])
    argv = ["noharm", "judge", "unused"]
    if backend is not None:
        argv += ["--backend", backend]
    if effort is not None:
        argv += ["--reasoning-effort", effort]
    monkeypatch.setattr(sys, "argv", argv)
    noharm.main()

    resolved_backend = backend or "openrouter"
    expected_model = "openai/gpt-6.1-sol" if resolved_backend == "openrouter" else "gpt-6.1-sol"
    assert len(calls) == 1
    assert calls[0][2:5] == (resolved_backend, expected_model, effort or "high")


@pytest.mark.parametrize(("backend", "requested", "expected"), [
    ("openai", None, 24), ("openrouter", None, 24),
    ("codex", None, 8), ("subscription", None, 8), ("openai", 5, 5),
])
def test_judge_concurrency_defaults_and_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    backend: str, requested: int | None, expected: int,
) -> None:
    seed_case(tmp_path)
    append_jsonl(tmp_path / "results/responses/m.jsonl", {"id": "Syn002", "trial": 1, "response": "Invented answer"})
    monkeypatch.setattr(judging, "run_skill", lambda *args, **kwargs:
                        SkillOutcome("pass", {"decisions": {}, "offRubric": []}, "raw", [], {}))
    executor = judging.ThreadPoolExecutor
    configured = []

    def pool(*, max_workers: int) -> Any:
        configured.append(max_workers)
        return executor(max_workers=max_workers)

    monkeypatch.setattr(judging, "ThreadPoolExecutor", pool)
    judging.judge(tmp_path, "run1", backend, "synthetic", workers=requested)
    assert configured == [expected]


def _judge_cli(monkeypatch: pytest.MonkeyPatch, *flags: str) -> list:
    calls = []
    monkeypatch.setattr(judging, "judge", lambda *args, **kwargs: calls.append((args, kwargs)) or [])
    monkeypatch.setattr(judging, "judge_problems", lambda *args: [])
    monkeypatch.setattr(noharm, "load_env", lambda: None)
    monkeypatch.setattr(noharm, "require", lambda name: "fake credential")
    monkeypatch.setattr(sys, "argv", ["noharm", "judge", "unused", "--backend", "openai", "--model", "gpt-6.1-sol", *flags])
    noharm.main()
    return calls


def test_judge_cli_count_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = [
        {"label": "--workers 7", "flags": ["--workers", "7"], "workers": 7},
        {"label": "--workers 0", "flags": ["--workers", "0"], "workers": None},
        {"label": "--timeout 0", "flags": ["--timeout", "0"], "workers": None},
    ]

    def run(case: dict[str, Any]) -> None:
        if case["workers"] is not None:
            assert _judge_cli(monkeypatch, *case["flags"])[0][0][-1] == case["workers"]
            return
        with pytest.raises(SystemExit) as exc:
            _judge_cli(monkeypatch, *case["flags"])
        assert exc.value.code == 2

    each_case(cases, lambda c: c["label"], run)
