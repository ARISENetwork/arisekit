"""Model-call plumbing shared by ARISEKit's clients and toolkits: the litellm core used by the benchmark clients, and
transports (prompt in, reply text plus call provenance out). Subscription CLIs (claude, codex) run isolated from user
settings and tools; API transports (openrouter, openai) use the openai SDK. Each transport can enforce a JSON schema on
the reply.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, ClassVar, TypedDict

from arisekit.common.hashing import sha256
from arisekit.common.logs import now_iso


# litellm clients
# Request fields a caller's `extra` cannot override; the client sets them itself.
RESERVED_EXTRA_KEYS = frozenset({
    "api_base", "api_key", "base_url", "fallback", "fallbacks", "max_tokens", "messages", "model", "router",
    "routing_strategy", "temperature", "timeout",
})


def validated_extra(value: dict[str, Any] | None, label: str) -> dict[str, Any] | None:
    """A copy of caller-supplied provider arguments, refusing provider retries and reserved fields."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a dictionary or null")
    if value.get("num_retries", 0) != 0:
        raise ValueError("provider retries must be disabled; the runner accounts for retries")
    reserved = sorted(RESERVED_EXTRA_KEYS & set(value))
    if reserved:
        raise ValueError(f"{label} cannot override reserved request fields: {', '.join(reserved)}")
    return dict(value)


class LiteLLMBase:
    """Settings, request arguments, and cost accounting shared by the litellm-backed clients. Subclasses build the
    messages and read the reply; litellm is imported only when a request is made. With disable_provider_retries
    (the default) requests send num_retries=0, leaving retries to the caller; otherwise litellm's defaults apply."""
    extra_label: ClassVar[str] = "client extra"
    disable_provider_retries: ClassVar[bool] = True

    def __init__(
        self,
        model: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = 120.0,
        api_base: str | None = None,
        api_key: str | None = None,
        extra: dict[str, Any] | None = None,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.api_base = api_base
        self.api_key = api_key
        self.extra = validated_extra(extra, self.extra_label)

    def _complete(self, messages: list[dict[str, Any]], *, temperature: float | None, max_tokens: int | None,
                  request: dict[str, Any] | None = None, extra: dict[str, Any] | None = None) -> Any:
        """One litellm.completion call; `extra` is applied after this client's own."""
        import litellm  # type: ignore

        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if self.disable_provider_retries:
            kwargs["num_retries"] = 0
        kwargs.update(request or {})
        for key, value in (("temperature", temperature), ("max_tokens", max_tokens), ("timeout", self.timeout),
                           ("api_base", self.api_base), ("api_key", self.api_key)):
            if value is not None:
                kwargs[key] = value
        if self.extra:
            kwargs.update(self.extra)
        if extra:
            kwargs.update(extra)
        return litellm.completion(**kwargs)

    @staticmethod
    def _cost(response: Any) -> tuple[float, bool]:
        """The reply's cost in USD and whether it is known: the provider's reported cost, else litellm's estimate."""
        import litellm  # type: ignore

        hidden = getattr(response, "_hidden_params", {}) or {}
        reported = hidden.get("response_cost")
        if reported is None:
            reported = getattr(getattr(response, "usage", None), "cost", None)
        if reported is not None:
            return float(reported), True
        try:
            calculated = litellm.completion_cost(completion_response=response)
            if calculated is None:
                return 0.0, False
            return float(calculated), True
        except Exception:  # noqa: BLE001
            return 0.0, False


# Transport endpoints and CLI settings
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"
RETRY_SLEEPS = (5, 20)  # seconds before the second and third attempt
CLAUDE_FLAGS = ["--tools", "", "--setting-sources", "", "--strict-mcp-config",
                "--disable-slash-commands", "--no-session-persistence", "--output-format", "json"]
CODEX_EVENTS = {"thread.started", "turn.started", "turn.completed", "turn.failed",
                "item.started", "item.completed", "error"}
CODEX_ITEMS = {"agent_message", "reasoning"}


# Errors and call records
class BackendError(RuntimeError):
    """A failed call. `retryable` marks transport failures where no answer was produced; `raw` keeps any reply."""
    def __init__(self, message: str, raw: str | None = None, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.raw = raw
        self.retryable = retryable


class CallProvenance(TypedDict, total=False):
    """How one model reply was produced; stored with the reply. Toolkits extend it with their own fields."""
    backend: str
    model: str
    prompt_sha256: str
    started_at: str
    runtime_s: float
    usage: Any
    cost_usd: float | None
    json_schema_enforced: bool
    attempts: int
    retried_errors: list[str]
    # Backend-specific details.
    resolved_model: str
    request_id: str | None
    reasoning_effort: str | None
    endpoint: str
    cli_version: str
    recovered_errors: list[dict[str, Any]]


@dataclass
class CallResult:
    text: str
    provenance: CallProvenance


@dataclass
class Reply:
    """What one transport returns before the shared provenance is added."""
    text: str
    usage: Any
    cost: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def prompt_sha256(system: str, prompt: str) -> str:
    """Identity of the exact model input, recorded on every call and compared on resume."""
    return sha256(f"{system}\n\n{prompt}")


# Transports
class Backend(ABC):
    """One provider transport. `call` times the request and records the provenance every backend shares."""
    name: ClassVar[str]

    def call(self, model: str, system: str, prompt: str, *, json_schema: dict[str, Any] | None = None,
             **options: Any) -> CallResult:
        started, t0 = now_iso(), time.monotonic()
        reply = self.request(model, system, prompt, json_schema=json_schema, **options)
        provenance: CallProvenance = {"backend": self.name, "model": model, "prompt_sha256": prompt_sha256(system, prompt),
                      "started_at": started, "runtime_s": round(time.monotonic() - t0, 2),
                      "usage": reply.usage, "cost_usd": reply.cost, **reply.extra}
        if json_schema is not None:
            provenance["json_schema_enforced"] = True
        return CallResult(reply.text, provenance)

    @abstractmethod
    def request(self, model: str, system: str, prompt: str, *, json_schema: dict[str, Any] | None,
                **options: Any) -> Reply:
        """Send one request and return the reply text, usage, cost, and backend-specific provenance."""


# Subscription CLIs
def _run_cli(label: str, cmd: list[str], *, prompt: str, cwd: str, env: dict[str, str],
             timeout: int) -> subprocess.CompletedProcess:
    """Run a subscription CLI. A timeout, or an exit with no output, produced no answer and is retryable."""
    try:
        return subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd, env=env,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired as e:
        raise BackendError(f"{label} timed out after {timeout}s", retryable=True) from e


def _exit_error(message: str, proc: subprocess.CompletedProcess) -> BackendError:
    """A CLI exit that printed nothing produced no answer, so it can be retried."""
    return BackendError(message, proc.stdout, retryable=not proc.stdout.strip())


class ClaudeCLI(Backend):
    """`claude -p` on the user's plan, with every tool, setting source, MCP server, and slash command off.

    `--bare` is not used because it disables subscription login.
    """
    name = "subscription"

    def request(self, model: str, system: str, prompt: str, *, json_schema: dict[str, Any] | None,
                timeout: int = 1800) -> Reply:
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}  # never bill the API
        schema = ["--json-schema", json.dumps(json_schema, separators=(",", ":"))] if json_schema is not None else []
        with tempfile.TemporaryDirectory() as cwd:
            proc = _run_cli("claude -p", ["claude", "-p", "--model", model, "--system-prompt", system, *CLAUDE_FLAGS,
                                          *schema], prompt=prompt, cwd=cwd, env=env, timeout=timeout)
        if proc.returncode != 0 or not proc.stdout.strip():
            raise _exit_error(f"claude -p exit {proc.returncode}: {proc.stderr.strip()[:500]}", proc)
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise BackendError(f"claude -p returned non-JSON: {e}", proc.stdout) from e
        if out.get("is_error") or not out.get("result"):
            raise BackendError(f"claude -p error: {str(out.get('result'))[:500]}", proc.stdout)
        if json_schema is not None and not isinstance(out.get("structured_output"), dict):
            raise BackendError("claude -p returned no structured_output for the JSON schema", proc.stdout)
        resolved = out.get("modelUsage") or {}
        text = out["result"] if json_schema is None else json.dumps(out["structured_output"])
        # total_cost_usd is notional on a subscription, so it is not recorded as cost.
        return Reply(text, out.get("usage"), extra={"resolved_model": next(iter(resolved))} if len(resolved) == 1 else {})


@cache
def _codex_version() -> str:
    proc = subprocess.run(["codex", "--version"], capture_output=True, text=True, check=False)
    return proc.stdout.strip()


def _copy_codex_auth(home: Path, codex_home: Path) -> None:
    source_dir = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    auth = source_dir / "auth.json"
    if auth.is_symlink():
        raise BackendError(f"codex auth file {auth} is a symlink; refusing to copy it")
    if not auth.is_file() or auth.stat().st_size == 0:
        raise BackendError(f"codex auth file {auth} is missing or empty; run `codex login`")
    for d in (home, codex_home):
        d.mkdir(mode=0o700)
    dest = codex_home / "auth.json"
    shutil.copyfile(auth, dest)
    dest.chmod(0o600)


def _check_codex_events(stdout: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Require completion without tool use; retain errors recovered within the turn."""
    usage: dict[str, Any] | None = None
    completed = False
    recovered_errors: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError as e:
            raise BackendError(f"codex emitted a non-JSON event line: {e}", stdout) from e
        kind = ev.get("type") if isinstance(ev, dict) else None
        if kind not in CODEX_EVENTS:
            raise BackendError(f"codex emitted unexpected event {kind!r}", stdout)
        if kind == "turn.failed":
            raise BackendError(f"codex {kind}: {json.dumps(ev)[:500]}", stdout)
        if kind == "turn.started":
            completed = False
        if kind == "error":
            recovered_errors.append(ev)
            completed = False
        if kind in ("item.started", "item.completed"):
            item_type = (ev.get("item") or {}).get("type")
            if item_type == "error":
                recovered_errors.append(ev)
                completed = False
            elif item_type not in CODEX_ITEMS:
                raise BackendError(f"codex used a tool ({item_type!r}); tools are not allowed", stdout)
        if kind == "turn.completed":
            usage = ev.get("usage")
            completed = True
    if not completed:
        detail = f": {json.dumps(recovered_errors[-1])[:500]}" if recovered_errors else ""
        raise BackendError(f"codex stream ended without turn.completed{detail}", stdout)
    return usage or {}, recovered_errors


class CodexCLI(Backend):
    """`codex exec` in a temporary HOME holding only a copy of the auth file: read-only sandbox, no user config."""
    name = "codex"

    def request(self, model: str, system: str, prompt: str, *, json_schema: dict[str, Any] | None,
                reasoning_effort: str | None = None, timeout: int = 1800) -> Reply:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home, codex_home, last = root / "home", root / "codex-home", root / "last.txt"
            _copy_codex_auth(home, codex_home)
            env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")}
            env["HOME"], env["CODEX_HOME"] = str(home), str(codex_home)
            effort = ["--config", f'model_reasoning_effort="{reasoning_effort}"'] if reasoning_effort else []
            schema: list[str] = []
            if json_schema is not None:
                schema_file = root / "schema.json"
                schema_file.write_text(json.dumps(json_schema))
                schema = ["--output-schema", str(schema_file)]
            cmd = ["codex", "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
                   "--sandbox", "read-only", "--model", model, *effort, "--config", "project_doc_max_bytes=0",
                   "--config", 'web_search="disabled"',
                   *schema, "--json", "-o", str(last), "-C", tmp, "-"]
            proc = _run_cli("codex exec", cmd, prompt=f"System instructions:\n{system}\n\n{prompt}",
                            cwd=tmp, env=env, timeout=timeout)
            if proc.returncode != 0:
                detail = proc.stderr.strip()[:500]
                if proc.stdout.strip():
                    try:
                        _check_codex_events(proc.stdout)
                    except BackendError as error:
                        detail = str(error)
                raise _exit_error(f"codex exec exit {proc.returncode}: {detail}", proc)
            usage, recovered_errors = _check_codex_events(proc.stdout)
            text = last.read_text() if last.is_file() else ""
        if not text.strip():
            raise BackendError("codex wrote a missing or empty last message", proc.stdout)
        extra: dict[str, Any] = {"cli_version": _codex_version()}
        if recovered_errors:
            extra["recovered_errors"] = recovered_errors
        return Reply(text, usage, extra=extra)


# API backends
class ChatAPI(Backend):
    """An OpenAI-compatible chat completions endpoint, with call() as the single, recorded retry layer."""
    base_url: ClassVar[str]
    key_env: ClassVar[str]

    def request(self, model: str, system: str, prompt: str, *, json_schema: dict[str, Any] | None,
                reasoning_effort: str | None = None, timeout: int = 600, client: Any = None) -> Reply:
        from openai import APIConnectionError, InternalServerError, OpenAI, RateLimitError  # timeouts included

        if client is None:
            client = OpenAI(base_url=self.base_url, api_key=os.environ[self.key_env], timeout=timeout, max_retries=0)
        try:
            resp = client.chat.completions.create(
                model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                **self.options(reasoning_effort, json_schema))
        except (APIConnectionError, RateLimitError, InternalServerError) as e:
            raise BackendError(f"{self.name} {type(e).__name__}: {e}"[:500], retryable=True) from e
        choice = resp.choices[0]
        text = choice.message.content
        if not text:
            finish = getattr(choice, "finish_reason", None)
            raise BackendError(f"{self.name} returned empty content (finish_reason {finish!r})", resp.model_dump_json(),
                               retryable=finish in ("error", None))
        return self.reply(text, resp.usage.model_dump() if resp.usage else None, resp, model, reasoning_effort)

    @abstractmethod
    def options(self, reasoning_effort: str | None, json_schema: dict[str, Any] | None) -> dict[str, Any]:
        """Provider-specific request arguments for effort and schema enforcement."""

    def reply(self, text: str, usage: dict[str, Any] | None, resp: Any, model: str,
              reasoning_effort: str | None) -> Reply:
        return Reply(text, usage)


def _response_format(json_schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": "rating", "strict": True, "schema": json_schema}}


class OpenRouter(ChatAPI):
    name, base_url, key_env = "openrouter", OPENROUTER_BASE_URL, "OPENROUTER_API_KEY"

    def options(self, reasoning_effort: str | None, json_schema: dict[str, Any] | None) -> dict[str, Any]:
        extra: dict[str, Any] = {"usage": {"include": True}}
        if reasoning_effort:
            extra["reasoning"] = {"effort": reasoning_effort}
        if json_schema is None:
            return {"extra_body": extra}
        extra["provider"] = {"require_parameters": True}  # route only to providers that honor the schema
        return {"extra_body": extra, "response_format": _response_format(json_schema)}

    def reply(self, text: str, usage: dict[str, Any] | None, resp: Any, model: str,
              reasoning_effort: str | None) -> Reply:
        return Reply(text, usage, (usage or {}).get("cost"))


class OpenAIDirect(ChatAPI):
    name, base_url, key_env = "openai", OPENAI_BASE_URL, "OPENAI_API_KEY"

    def options(self, reasoning_effort: str | None, json_schema: dict[str, Any] | None) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if reasoning_effort is not None:
            options["reasoning_effort"] = reasoning_effort
        if json_schema is not None:
            options["response_format"] = _response_format(json_schema)
        return options

    def reply(self, text: str, usage: dict[str, Any] | None, resp: Any, model: str,
              reasoning_effort: str | None) -> Reply:
        return Reply(text, usage, extra={"resolved_model": getattr(resp, "model", model),
                                         "request_id": getattr(resp, "_request_id", None),
                                         "reasoning_effort": reasoning_effort, "endpoint": self.base_url})


# Calling
def call_with_retries(transport: Backend, model: str, system: str, prompt: str, max_retries: int = 2,
                      sleep: Callable[[float], None] = time.sleep, **kwargs: Any) -> CallResult:
    """One transport call with transport retries only.

    Only retryable errors are retried (no answer was produced). A reply that is
    present but fails the caller's checks is returned as is; repairing it is forbidden.
    """
    retried: list[str] = []
    for attempt in range(1, max_retries + 2):
        try:
            result = transport.call(model, system, prompt, **kwargs)
        except BackendError as e:
            if e.retryable and attempt <= max_retries:
                retried.append(str(e)[:200])
                sleep(RETRY_SLEEPS[min(attempt, len(RETRY_SLEEPS)) - 1])
                continue
            if e.retryable or attempt > 1:
                attempts = f"{attempt} attempt{'s' if attempt > 1 else ''}"
                raise BackendError(f"after {attempts}: {e}", e.raw, retryable=e.retryable) from e
            raise
        result.provenance["attempts"] = attempt
        result.provenance["retried_errors"] = retried
        return result
    raise AssertionError("unreachable")
