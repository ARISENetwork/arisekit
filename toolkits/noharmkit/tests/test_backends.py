"""Backends: claude -p subprocess, OpenRouter, and the Codex CLI, all mocked."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cases import each_case

from pipeline import backends
from arisekit.common import jsonio, llm
from pipeline.e2e import generate
from pipeline.e2e.constants import KIT_ROOT


def _proc(stdout: str, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class _Sleeps:
    def __init__(self) -> None:
        self.seen: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.seen.append(seconds)


def _sequenced_run(monkeypatch: pytest.MonkeyPatch, *steps: Any) -> dict[str, int]:
    """subprocess.run replays steps in order; an Exception step is raised, a callable step is called."""
    state = {"calls": 0}

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess:
        step = steps[min(state["calls"], len(steps) - 1)]
        state["calls"] += 1
        if isinstance(step, Exception):
            raise step
        return step(cmd, kw) if callable(step) else step

    monkeypatch.setattr(subprocess, "run", fake_run)
    return state


SCHEMA = {"type": "object", "properties": {"color": {"type": "string", "enum": ["red", "blue"]}},
          "required": ["color"], "additionalProperties": False}
# Shape of a live `claude -p --output-format json --json-schema ...` envelope (2.1.280, 2026-09-28), trimmed.
STRUCTURED_ENVELOPE = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 2,
                       "stop_reason": "tool_use", "terminal_reason": "completed",
                       "result": '{"color":"blue"}', "structured_output": {"color": "blue"},
                       "usage": {"output_tokens": 9}, "modelUsage": {"claude-opus-5-5": {}}}


def test_subscription_call_command_env_and_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-stray")
    monkeypatch.setenv("KEEP_ME", "1")
    seen: dict[str, Any] = {}

    def replying(envelope: dict[str, Any]) -> None:
        def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess:
            seen["cmd"], seen["kw"] = cmd, kw
            return _proc(json.dumps(envelope))
        monkeypatch.setattr(subprocess, "run", fake_run)

    replying({"result": "hello", "is_error": False, "usage": {"output_tokens": 1}})
    out = backends.call("subscription", "opus", "SYS", "PROMPT")
    assert out.text == "hello"
    assert seen["cmd"][:4] == ["claude", "-p", "--model", "opus"]
    for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("--tools") + 1] == ""
    assert seen["kw"]["input"] == "PROMPT"
    assert seen["kw"]["cwd"] != str(KIT_ROOT)
    assert "ANTHROPIC_API_KEY" not in seen["kw"]["env"] and seen["kw"]["env"]["KEEP_ME"] == "1"
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-stray"
    assert out.provenance["backend"] == "subscription"
    assert len(out.provenance["prompt_sha256"]) == 64
    assert out.provenance["cost_usd"] is None

    replying(STRUCTURED_ENVELOPE)
    out = backends.call("subscription", "opus", "S", "P")
    assert "--json-schema" not in seen["cmd"]
    assert out.text == '{"color":"blue"}' and "json_schema_enforced" not in out.provenance

    replying({"result": "x", "is_error": False, "modelUsage": {"claude-opus-4-7[1m]": {"outputTokens": 1}}})
    out = backends.call("subscription", "opus", "S", "P")
    assert out.provenance["model"] == "opus" and out.provenance["resolved_model"] == "claude-opus-4-7[1m]"
    replying({"result": "x", "is_error": False, "modelUsage": {"a": {}, "b": {}}})
    assert "resolved_model" not in backends.call("subscription", "opus", "S", "P").provenance


def test_subscription_json_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess:
        seen["cmd"] = cmd
        return _proc(json.dumps({**STRUCTURED_ENVELOPE, "result": "prose that is not the structured output"}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = backends.call("subscription", "opus", "S", "P", json_schema=SCHEMA)
    assert seen["cmd"][seen["cmd"].index("--json-schema") + 1] == json.dumps(SCHEMA, separators=(",", ":"))
    assert json.loads(out.text) == {"color": "blue"}
    assert out.provenance["json_schema_enforced"] is True
    assert out.provenance["resolved_model"] == "claude-opus-5-5"

    envelope = json.dumps({k: v for k, v in STRUCTURED_ENVELOPE.items() if k != "structured_output"})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(envelope))
    with pytest.raises(backends.BackendError, match="structured_output") as err:
        backends.call("subscription", "opus", "S", "P", json_schema=SCHEMA)
    assert err.value.raw == envelope


def test_subscription_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    timeout = subprocess.TimeoutExpired(["claude"], 1)
    cases = [
        {"label": "is_error with message", "step": _proc('{"result": "Not logged in", "is_error": true}'),
         "match": ["Not logged in"], "calls": 1, "sleeps": [], "raw_kept": True},
        {"label": "nonzero exit with stdout", "step": _proc('{"result": "quota", "is_error": true}', 1),
         "match": ["exit 1"], "calls": 1, "sleeps": [], "raw_kept": False},
        {"label": "persistent nonzero exit with empty stdout", "step": _proc("", 2, "boom"),
         "match": ["exit 2", "after 3 attempts"], "calls": 3, "sleeps": [5, 20], "raw_kept": False},
        {"label": "persistent timeout", "step": timeout,
         "match": ["after 3 attempts"], "calls": 3, "sleeps": [5, 20], "raw_kept": False},
    ]

    def run(case: dict[str, Any]) -> None:
        state = _sequenced_run(monkeypatch, case["step"])
        sleeps = _Sleeps()
        with pytest.raises(backends.BackendError, match=case["match"][0]) as err:
            backends.call("subscription", "opus", "S", "P", sleep=sleeps)
        for text in case["match"]:
            assert text in str(err.value)
        assert state["calls"] == case["calls"] and sleeps.seen == case["sleeps"]
        if case["raw_kept"]:
            assert err.value.raw is not None

    each_case(cases, lambda c: c["label"], run)


def _codex_ok(cmd: list[str], kw: dict[str, Any]) -> subprocess.CompletedProcess:
    Path(cmd[cmd.index("-o") + 1]).write_text(FINAL)
    return _proc(_events())


def test_cli_transient_failure_then_success_is_retried(monkeypatch: pytest.MonkeyPatch, codex_auth: Path) -> None:
    subscription_ok = _proc(json.dumps({"result": "fine", "is_error": False}))
    cases = [
        {"label": "subscription exit 1 with empty stdout", "backend": "subscription", "model": "opus",
         "fail": _proc("", 1, "overloaded"), "ok": subscription_ok, "text": "fine", "exit": True},
        {"label": "subscription timeout", "backend": "subscription", "model": "opus",
         "fail": subprocess.TimeoutExpired(["claude"], 1), "ok": subscription_ok, "text": "fine", "exit": False},
        {"label": "codex timeout", "backend": "codex", "model": "m",
         "fail": subprocess.TimeoutExpired(["codex"], 1), "ok": _codex_ok, "text": FINAL, "exit": False},
        {"label": "codex exit 1 with empty stdout", "backend": "codex", "model": "m",
         "fail": _proc("", 1, "connection reset"), "ok": _codex_ok, "text": FINAL, "exit": True},
    ]

    def run(case: dict[str, Any]) -> None:
        state = _sequenced_run(monkeypatch, case["fail"], case["ok"])
        sleeps = _Sleeps()
        out = backends.call(case["backend"], case["model"], "S", "P", sleep=sleeps)
        assert out.text == case["text"] and state["calls"] == 2 and sleeps.seen == [5]
        assert out.provenance["attempts"] == 2 and len(out.provenance["retried_errors"]) == 1
        if case["exit"]:
            assert "exit 1" in out.provenance["retried_errors"][0]

    each_case(cases, lambda c: c["label"], run)


class _FakeCompletions:
    """Replies in order; a reply is content, a (content, finish_reason) pair, or an exception to raise."""

    def __init__(self, *replies: Any) -> None:
        self.replies, self.kwargs, self.calls = list(replies), {}, 0

    def create(self, **kw: Any) -> Any:
        self.kwargs = kw
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        if isinstance(reply, Exception):
            raise reply
        content, finish = reply if isinstance(reply, tuple) else (reply, "stop")
        usage = SimpleNamespace(model_dump=lambda: {"prompt_tokens": 3, "completion_tokens": 2, "cost": 0.01})
        msg = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)], usage=usage,
                               model_dump_json=lambda: "{}")


def _client(*replies: Any) -> Any:
    comps = _FakeCompletions(*replies)
    return SimpleNamespace(chat=SimpleNamespace(completions=comps)), comps


def test_unknown_backend() -> None:
    with pytest.raises(ValueError, match="unknown backend"):
        backends.call("nope", "m", "S", "P")


def test_extract_json() -> None:
    cases = [
        ('{"a": 1}', {"a": 1}),
        ('Here is the table:\n```json\n{"a": 1}\n```\nDone.', {"a": 1}),
        ('Sure. {"a": 1} Hope that helps.', {"a": 1}),
        ("no json here", ValueError),
    ]

    def run(case: tuple[str, Any]) -> None:
        text, expected = case
        if expected is ValueError:
            with pytest.raises(ValueError):
                jsonio.extract_json(text)
        else:
            assert jsonio.extract_json(text) == expected

    each_case(cases, lambda c: c[0], run)


AUTH_TEXT = '{"tokens": "fake-not-a-credential"}'
FINAL = '{"ok": true}'
USAGE = {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 5, "reasoning_output_tokens": 2}


def _events(*extra: dict[str, Any]) -> str:
    evs = [{"type": "thread.started", "thread_id": "t"}, {"type": "turn.started"},
           {"type": "item.completed", "item": {"id": "i0", "type": "reasoning", "text": "hm"}},
           {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": FINAL}},
           *extra, {"type": "turn.completed", "usage": USAGE}]
    return "\n".join(json.dumps(e) for e in evs) + "\n"


@pytest.fixture(autouse=False)
def codex_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    src = tmp_path / "src-codex"
    src.mkdir()
    (src / "auth.json").write_text(AUTH_TEXT)
    monkeypatch.setenv("CODEX_HOME", str(src))
    monkeypatch.setattr(llm, "_codex_version", lambda: "codex-cli 9.9.9")
    return src


def _fake_codex(monkeypatch: pytest.MonkeyPatch, stdout: str, returncode: int = 0,
                last: str | None = FINAL, seen: dict[str, Any] | None = None) -> dict[str, Any]:
    seen = {} if seen is None else seen

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess:
        seen["cmd"], seen["kw"] = cmd, kw
        env = kw["env"]
        seen["auth_mode"] = os.stat(Path(env["CODEX_HOME"]) / "auth.json").st_mode & 0o777
        seen["auth_text"] = (Path(env["CODEX_HOME"]) / "auth.json").read_text()
        seen["dir_modes"] = [os.stat(env[k]).st_mode & 0o777 for k in ("HOME", "CODEX_HOME")]
        if last is not None:
            Path(cmd[cmd.index("-o") + 1]).write_text(last)
        return _proc(stdout, returncode, "err text")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


def test_codex_call_command_env_auth_and_provenance(monkeypatch: pytest.MonkeyPatch, codex_auth: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stray")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-stray2")
    monkeypatch.setenv("KEEP_ME", "1")
    before = dict(os.environ)
    seen = _fake_codex(monkeypatch, _events())
    out = backends.call("codex", "gpt-6-astra", "SYS", "PROMPT", reasoning_effort="medium")
    cmd, kw = seen["cmd"], seen["kw"]
    assert cmd[:2] == ["codex", "exec"]
    for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "--json"):
        assert flag in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert cmd[cmd.index("--model") + 1] == "gpt-6-astra"
    configs = [cmd[i + 1] for i, c in enumerate(cmd) if c == "--config"]
    assert 'model_reasoning_effort="medium"' in configs and "project_doc_max_bytes=0" in configs
    assert 'web_search="disabled"' in configs  # web search is a tool, which the event check rejects
    assert cmd[-1] == "-" and cmd[cmd.index("-C") + 1] == kw["cwd"]
    assert kw["input"] == "System instructions:\nSYS\n\nPROMPT"
    env = kw["env"]
    assert "OPENAI_API_KEY" not in env and "ANTHROPIC_API_KEY" not in env and env["KEEP_ME"] == "1"
    assert env["HOME"] != os.environ["HOME"] and env["CODEX_HOME"] != str(codex_auth)
    assert not Path(env["CODEX_HOME"]).exists()  # temp dirs are cleaned up
    assert seen["auth_mode"] == 0o600 and seen["auth_text"] == AUTH_TEXT and seen["dir_modes"] == [0o700, 0o700]
    assert dict(os.environ) == before
    assert out.text == FINAL
    assert "--output-schema" not in cmd and "json_schema_enforced" not in out.provenance

    out = backends.call("codex", "gpt-6-astra", "S", "P")
    assert out.provenance["backend"] == "codex" and out.provenance["model"] == "gpt-6-astra"
    assert out.provenance["cost_usd"] is None and out.provenance["usage"] == USAGE
    assert out.provenance["cli_version"] == "codex-cli 9.9.9"
    assert len(out.provenance["prompt_sha256"]) == 64

    out = backends.call("codex", "m", "S", "P")
    assert not any("model_reasoning_effort" in c for c in seen["cmd"])
    assert "--output-schema" not in seen["cmd"] and "json_schema_enforced" not in out.provenance


def test_codex_auth_from_default_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "auth.json").write_text(AUTH_TEXT)
    monkeypatch.setattr(llm, "_codex_version", lambda: "v")
    seen = _fake_codex(monkeypatch, _events())
    assert backends.call("codex", "m", "S", "P").text == FINAL
    assert seen["auth_text"] == AUTH_TEXT


def test_codex_rejected_streams_are_not_retried(monkeypatch: pytest.MonkeyPatch, codex_auth: Path) -> None:
    def without_completion(*ending: dict[str, Any]) -> str:
        return "\n".join(_events().splitlines()[:-1] + [json.dumps(e) for e in ending])

    turn_failed = {"type": "turn.failed", "error": {"message": "workspace routing discovery failed"}}
    cases = [
        {"label": "command_execution tool event", "returncode": 0, "match": ["tool"], "stdout": _events(
            {"type": "item.completed", "item": {"id": "x", "type": "command_execution", "command": "ls"}})},
        # No last-message file: the event check must run before the last-message check.
        {"label": "tool event without a last message", "returncode": 0, "match": ["tool"], "writes_last": False,
         "stdout": _events({"type": "item.completed", "item": {"id": "x", "type": "command_execution", "command": "ls"}})},
        {"label": "mcp_tool_call tool event", "returncode": 0, "match": ["tool"], "stdout": _events(
            {"type": "item.started", "item": {"id": "x", "type": "mcp_tool_call"}})},
        {"label": "turn.failed event", "returncode": 0, "match": [], "stdout": _events(
            {"type": "turn.failed", "error": {"message": "boom"}})},
        {"label": "unknown event", "returncode": 0, "match": [], "stdout": _events({"type": "something.new"})},
        {"label": "stream ends without turn.completed", "returncode": 0, "match": ["without turn.completed"],
         "stdout": without_completion()},
        {"label": "stream ends on a top-level error", "returncode": 0, "match": ["without turn.completed"],
         "stdout": without_completion({"type": "error", "message": "workspace routing discovery failed"})},
        {"label": "stream ends on an error item", "returncode": 0, "match": ["without turn.completed"],
         "stdout": without_completion({"type": "item.completed",
                                       "item": {"id": "e", "type": "error", "message": "boom"}})},
        {"label": "stream ends on a new turn", "returncode": 0, "match": ["without turn.completed"],
         "stdout": without_completion({"type": "turn.started"})},
        {"label": "error after turn.completed", "returncode": 0, "match": ["without turn.completed"],
         "stdout": _events() + json.dumps({"type": "error", "message": "boom"})},
        {"label": "trailing non-JSON line", "returncode": 0, "match": ["non-JSON"],
         "stdout": _events() + "not json\n"},
        {"label": "exit 3 after a complete stream", "returncode": 3, "match": ["exit 3"], "stdout": _events()},
        {"label": "exit 1 with turn.failed", "returncode": 1,
         "match": ["workspace routing discovery failed", "exit 1"], "stdout": _events(turn_failed)},
    ]

    def run(case: dict[str, Any]) -> None:
        def rejected(cmd: list[str], kw: dict[str, Any]) -> subprocess.CompletedProcess:
            if case.get("writes_last", True):
                Path(cmd[cmd.index("-o") + 1]).write_text(FINAL)
            return _proc(case["stdout"], case["returncode"], "err text")

        state = _sequenced_run(monkeypatch, rejected, _codex_ok)
        sleeps = _Sleeps()
        with pytest.raises(backends.BackendError, match=case["match"][0] if case["match"] else None) as err:
            backends.call("codex", "m", "S", "P", sleep=sleeps)
        for text in case["match"]:
            assert text in str(err.value)
        assert err.value.raw == case["stdout"]
        assert state["calls"] == 1 and sleeps.seen == []

    each_case(cases, lambda c: c["label"], run)


@pytest.mark.parametrize("warnings", [
    [{"type": "error", "message": "Reconnecting... 2/5 (unexpected status 503 Service Unavailable)"},
     {"type": "error", "message": "Reconnecting... 3/5 (unexpected status 503 Service Unavailable)"}],
    [{"type": "item.completed", "item": {"id": "i2", "type": "error",
      "message": "Falling back from WebSockets to HTTPS transport. workspace routing discovery failed"}}],
])
def test_codex_recovered_errors_keep_answer_usage_and_diagnostics(
    monkeypatch: pytest.MonkeyPatch, codex_auth: Path, warnings: list[dict[str, Any]],
) -> None:
    _fake_codex(monkeypatch, _events(*warnings))
    sleeps = _Sleeps()
    out = backends.call("codex", "m", "S", "P", sleep=sleeps)
    assert out.text == FINAL and out.provenance["usage"] == USAGE
    assert out.provenance["recovered_errors"] == warnings
    assert out.provenance["attempts"] == 1 and sleeps.seen == []


def test_codex_recovered_call_still_requires_valid_skill_output(
    monkeypatch: pytest.MonkeyPatch, codex_auth: Path,
) -> None:
    from pipeline.skillrun import run_skill

    warning = {"type": "error", "message": "Reconnecting... 2/5 (503 Service Unavailable)"}
    _fake_codex(monkeypatch, _events(warning))
    outcome = run_skill(generate.SKILL, {"case_id": "Synthetic001", "case": "Synthetic case",
        "expert": "Synthetic reference", "errors": "", "contract": "Synthetic contract", "guide": "Synthetic guide"},
        "codex", "m")
    assert outcome.status == "failed" and all(e.startswith("schema:") for e in outcome.errors)
    assert outcome.raw == FINAL and outcome.provenance["recovered_errors"] == [warning]


def test_codex_missing_or_empty_last_message_raises(monkeypatch: pytest.MonkeyPatch, codex_auth: Path) -> None:
    def run(last: str | None) -> None:
        def finished(cmd: list[str], kw: dict[str, Any]) -> subprocess.CompletedProcess:
            if last is not None:
                Path(cmd[cmd.index("-o") + 1]).write_text(last)
            return _proc(_events(), 0, "err text")

        state = _sequenced_run(monkeypatch, finished, _codex_ok)
        sleeps = _Sleeps()
        with pytest.raises(backends.BackendError, match="last message"):
            backends.call("codex", "m", "S", "P", sleep=sleeps)
        assert state["calls"] == 1 and sleeps.seen == []

    each_case([None, "", "  \n"], repr, run)


def test_codex_missing_empty_or_symlinked_auth_raises(monkeypatch: pytest.MonkeyPatch, codex_auth: Path,
                                                      tmp_path: Path) -> None:
    def boom(*a: Any, **k: Any) -> Any:
        raise AssertionError("codex must not run without valid auth")

    monkeypatch.setattr(subprocess, "run", boom)
    auth = codex_auth / "auth.json"
    real = tmp_path / "real-auth.json"
    real.write_text(AUTH_TEXT)
    sleeps = _Sleeps()
    auth.unlink()
    with pytest.raises(backends.BackendError, match="auth"):
        backends.call("codex", "m", "S", "P", sleep=sleeps)
    auth.write_text("")
    with pytest.raises(backends.BackendError, match="auth"):
        backends.call("codex", "m", "S", "P", sleep=sleeps)
    auth.unlink()
    auth.symlink_to(real)
    with pytest.raises(backends.BackendError, match="symlink"):
        backends.call("codex", "m", "S", "P", sleep=sleeps)
    assert sleeps.seen == []


def test_codex_writes_the_schema_file_and_passes_it(monkeypatch: pytest.MonkeyPatch, codex_auth: Path) -> None:
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess:
        seen["cmd"] = cmd
        schema_file = Path(cmd[cmd.index("--output-schema") + 1])
        seen["schema"] = json.loads(schema_file.read_text())
        seen["inside_tmp"] = schema_file.parent == Path(kw["cwd"])
        Path(cmd[cmd.index("-o") + 1]).write_text(FINAL)
        return _proc(_events())

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = backends.call("codex", "gpt-6-astra", "S", "P", json_schema=SCHEMA)
    assert seen["schema"] == SCHEMA and seen["inside_tmp"]
    assert seen["cmd"][-1] == "-"
    assert out.provenance["json_schema_enforced"] is True


# ---- OpenRouter requests and transport retries ----

# Shape of the two live failures (OpenRouter, 2026-09-28), trimmed: finish_reason "error", null content.
ERROR_REPLY = (None, "error")


def _http_error(cls: type, status: int) -> Exception:
    import httpx
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    return cls(f"http {status}", response=httpx.Response(status, request=request), body=None)


def test_openrouter_call_request_and_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    import openai

    client, comps = _client("hi")
    out = backends.call("openrouter", "openai/gpt-6-astra", "SYS", "P", reasoning_effort="medium", client=client)
    assert out.text == "hi"
    assert comps.kwargs["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "P"}]
    assert comps.kwargs["extra_body"]["reasoning"] == {"effort": "medium"}
    assert out.provenance["cost_usd"] == 0.01

    seen: dict[str, Any] = {}

    class FakeOpenAI:
        def __init__(self, **kw: Any) -> None:
            seen.update(kw)
            built, seen["comps"] = _client("hi")
            self.chat = built.chat

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    sleeps = _Sleeps()
    out = backends.call("openrouter", "m", "S", "P", sleep=sleeps)
    assert out.text == "hi"
    assert seen["max_retries"] == 0 and seen["base_url"] == llm.OPENROUTER_BASE_URL
    kwargs = seen["comps"].kwargs
    assert "response_format" not in kwargs and "provider" not in kwargs["extra_body"]
    assert "json_schema_enforced" not in out.provenance
    assert out.provenance["attempts"] == 1 and out.provenance["retried_errors"] == [] and sleeps.seen == []


def test_openrouter_schema_request_and_no_repair() -> None:
    client, comps = _client('{"color": "red"}')
    out = backends.call("openrouter", "x-ai/grok-4.7", "S", "P", json_schema=SCHEMA, client=client)
    assert comps.kwargs["response_format"] == {"type": "json_schema", "json_schema": {
        "name": "rating", "strict": True, "schema": SCHEMA}}
    assert comps.kwargs["extra_body"]["provider"] == {"require_parameters": True}
    assert comps.kwargs["extra_body"]["usage"] == {"include": True}
    assert out.provenance["json_schema_enforced"] is True

    client, comps = _client('{"not": "the schema"}')
    sleeps = _Sleeps()
    out = backends.call("openrouter", "m", "S", "P", client=client, json_schema=SCHEMA, sleep=sleeps)
    assert out.text == '{"not": "the schema"}' and comps.calls == 1 and sleeps.seen == []


def test_openrouter_transient_then_success() -> None:
    import httpx
    import openai
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    cases = [
        {"label": "finish_reason error", "first": ERROR_REPLY, "then": '{"color": "red"}', "empty": True},
        {"label": "no finish_reason, null content", "first": (None, None), "then": "ok", "empty": True},
        {"label": "APITimeoutError", "first": openai.APITimeoutError(request=request), "then": "ok", "empty": False},
        {"label": "APIConnectionError", "first": openai.APIConnectionError(request=request), "then": "ok",
         "empty": False},
        {"label": "429", "first": _http_error(openai.RateLimitError, 429), "then": "ok", "empty": False},
        {"label": "502", "first": _http_error(openai.InternalServerError, 502), "then": "ok", "empty": False},
    ]

    def run(case: dict[str, Any]) -> None:
        client, comps = _client(case["first"], case["then"])
        sleeps = _Sleeps()
        out = backends.call("openrouter", "m", "S", "P", client=client, sleep=sleeps)
        assert out.text == case["then"]
        assert comps.calls == 2 and sleeps.seen == [5]
        assert out.provenance["attempts"] == 2 and len(out.provenance["retried_errors"]) == 1
        if case["empty"]:
            assert "empty" in out.provenance["retried_errors"][0]

    each_case(cases, lambda c: c["label"], run)


def test_openrouter_non_transient_failures_are_not_retried() -> None:
    import openai
    cases = [
        {"label": "null content, content_filter", "reply": (None, "content_filter"),
         "error": backends.BackendError, "match": "empty"},
        {"label": "null content, length", "reply": (None, "length"), "error": backends.BackendError, "match": "empty"},
        {"label": "null content, stop", "reply": (None, "stop"), "error": backends.BackendError, "match": "empty"},
        {"label": "http 400", "reply": _http_error(openai.BadRequestError, 400), "error": openai.BadRequestError,
         "match": None},
    ]

    def run(case: dict[str, Any]) -> None:
        client, comps = _client(case["reply"], "never reached")
        sleeps = _Sleeps()
        with pytest.raises(case["error"], match=case["match"]):
            backends.call("openrouter", "m", "S", "P", client=client, sleep=sleeps)
        assert comps.calls == 1 and sleeps.seen == []

    each_case(cases, lambda c: c["label"], run)


def test_openrouter_retry_exhaustion() -> None:
    import openai
    cases = [
        {"label": "three transient replies", "replies": (ERROR_REPLY, ERROR_REPLY, ERROR_REPLY, "never reached"),
         "max_retries": None, "match": "after 3 attempts", "calls": 3, "sleeps": [5, 20], "raw": "{}"},
        {"label": "persistent 503", "replies": (_http_error(openai.InternalServerError, 503),),
         "max_retries": None, "match": "after 3 attempts", "calls": 3, "sleeps": [5, 20], "raw": None},
        {"label": "max_retries 0", "replies": (ERROR_REPLY, "never reached"),
         "max_retries": 0, "match": "after 1 attempt: ", "calls": 1, "sleeps": [], "raw": None},
        {"label": "max_retries 1", "replies": (ERROR_REPLY, ERROR_REPLY, "never reached"),
         "max_retries": 1, "match": "after 2 attempts", "calls": 2, "sleeps": [5], "raw": None},
    ]

    def run(case: dict[str, Any]) -> None:
        client, comps = _client(*case["replies"])
        sleeps = _Sleeps()
        retries = {} if case["max_retries"] is None else {"max_retries": case["max_retries"]}
        with pytest.raises(backends.BackendError, match=case["match"]) as err:
            backends.call("openrouter", "m", "S", "P", client=client, sleep=sleeps, **retries)
        assert comps.calls == case["calls"] and sleeps.seen == case["sleeps"]
        if case["raw"] is not None:
            assert err.value.raw == case["raw"]

    each_case(cases, lambda c: c["label"], run)
