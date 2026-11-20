"""NOHARMKit's model routes: backend names and aliases, default models, and route validation over the shared
transports in arisekit.common.llm."""
from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, TypedDict

# BackendError and CallResult are re-exported for the stages, which use them through this module.
from arisekit.common.llm import (Backend, BackendError, CallProvenance as BaseCallProvenance, CallResult, ClaudeCLI,
                                 CodexCLI, OpenAIDirect, OpenRouter, call_with_retries)

BACKENDS = ("claude", "subscription", "openrouter", "codex", "openai")
DEFAULT_MODELS = {"subscription": "opus", "codex": "gpt-6-astra", "openrouter": "openai/gpt-6-astra",
                  "openai": "gpt-6.1-sol"}
JUDGE_DEFAULT_MODELS = {**DEFAULT_MODELS, "codex": "gpt-6.1-sol", "openrouter": "openai/gpt-6.1-sol"}
JUDGE_DEFAULT_EFFORT = "high"
REASONING_EFFORT_BACKENDS = {"openrouter", "codex", "openai"}  # the Claude CLI takes no effort setting
API_BACKENDS = {"openrouter", "openai"}  # billed per call with a key
SUBSCRIPTION_BACKENDS = {"subscription", "codex"}  # account login, no key


class CallProvenance(BaseCallProvenance, total=False):
    """Call provenance as stored in rubric status files, judgment receipts, and response records."""
    # Added by skillrun.call_json.
    skill: str
    json_schema_sha256: str
    output_normalization: str
    # Added by the judge stage.
    judge_model: str
    request_timeout_s: int


# Routes
def canonical_backend(backend: str) -> str:
    """Resolve public aliases while preserving stored subscription provenance."""
    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}; expected one of {BACKENDS}")
    return "subscription" if backend == "claude" else backend


def default_workers(backend: str) -> int:
    """Concurrent paid calls: API routes take many, subscription logins share one account's rate limit."""
    return 24 if canonical_backend(backend) in API_BACKENDS else 8


def run_paid(jobs: list, call: Callable[[Any], Any], write: Callable[[Any, Any], None], workers: int) -> None:
    """Run paid calls concurrently and write each result as it arrives, so a crash never loses a paid result.
    A call that raises lets the others finish and be written first, then its error is raised."""
    errors: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(call, job): job for job in jobs}
        for future in as_completed(futures):
            try:
                outcome = future.result()
            except Exception as error:
                errors.append(error)
                continue
            write(futures[future], outcome)
    if errors:
        raise errors[0]


class Route(TypedDict, total=False):
    """A resolved model route: committee members, panel moderators, and stage routes on disk."""
    backend: str
    model: str
    reasoning_effort: str


BACKEND_HELP = ("claude: Claude subscription; codex: Codex subscription; openrouter: API; "
                "openai: direct OpenAI API; subscription: legacy Claude alias")


def resolve_route(backend: str, model: str | None = None,
                  reasoning_effort: str | None = None) -> tuple[str, str, dict[str, Any]]:
    """Validate a user-chosen backend, model, and effort before any stage runs; fills the default model."""
    backend = canonical_backend(backend)
    model = DEFAULT_MODELS[backend] if model is None else model
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be a nonempty identifier")
    if backend in SUBSCRIPTION_BACKENDS and "/" in model:
        raise ValueError(f"{backend}: use a subscription CLI model ID, not an API provider/model route")
    claude_model = model in {"opus", "sonnet", "haiku"} or model.startswith("claude-")
    if backend == "codex" and claude_model:
        raise ValueError("codex: a Claude model cannot be used with the Codex subscription")
    if backend == "subscription" and model.startswith(("gpt-", "o1", "o3", "o4")):
        raise ValueError("claude: an OpenAI model cannot be used with the Claude subscription")
    if backend == "openrouter" and "/" not in model:
        raise ValueError("openrouter: use a provider/model API route")
    if backend == "openai" and ("/" in model or claude_model):
        raise ValueError("openai: use a direct OpenAI model ID, without a provider prefix")
    if reasoning_effort is not None and backend == "subscription":
        raise ValueError("--reasoning-effort applies to codex, openrouter, or openai, not Claude subscription")
    return backend, model, {"reasoning_effort": reasoning_effort} if reasoning_effort is not None else {}


def route(backend: str, model: str | None = None, reasoning_effort: str | None = None) -> Route:
    """resolve_route as a stored route record."""
    backend, model, kwargs = resolve_route(backend, model, reasoning_effort)
    return {"backend": backend, "model": model, **kwargs}


# Calling
TRANSPORTS: dict[str, Backend] = {"subscription": ClaudeCLI(), "openrouter": OpenRouter(), "codex": CodexCLI(),
                                  "openai": OpenAIDirect()}


def call(backend: str, model: str, system: str, prompt: str, max_retries: int = 2,
         sleep: Callable[[float], None] = time.sleep, **kwargs: Any) -> CallResult:
    """One call on a NOHARMKit backend name or alias, with transport retries only (see call_with_retries)."""
    return call_with_retries(TRANSPORTS[canonical_backend(backend)], model, system, prompt, max_retries, sleep, **kwargs)
