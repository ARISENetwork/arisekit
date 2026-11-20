"""Versioned, secret-free provider profiles for planning and evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

SCHEMA_VERSION = "arisekit.provider-profile.v1"
_PARAMETERS = {
    "temperature",
    "max_tokens",
    "max_completion_tokens",
    "reasoning_effort",
    "seed",
    "response_format",
}


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    provider: str
    model: str
    parameters: Mapping[str, Any] = field(default_factory=lambda: {"max_tokens": 512})
    supported_parameters: tuple[str, ...] = (
        "max_tokens",
        "temperature",
        "tools",
        "tool_choice",
    )
    api_key_env: str | None = None
    api_base_env: str | None = None
    api_version_env: str | None = None
    token_env: str | None = None
    timeout: float = 45.0
    development_only: bool = False
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported provider profile schema")
        if self.provider not in {"azure", "openrouter", "stub"}:
            raise ValueError("profile provider must be azure, openrouter, or stub")
        for value in (self.name, self.model):
            if (
                not isinstance(value, str)
                or not value
                or any(c.isspace() for c in value)
            ):
                raise ValueError("profile name and model must be nonempty identifiers")
        if not self.model.startswith(self.provider + "/"):
            raise ValueError("profile model must use its provider prefix")
        if self.provider == "stub" and self.model != "stub/reference":
            raise ValueError("unsupported stub model")
        for name in (
            self.api_key_env,
            self.api_base_env,
            self.api_version_env,
            self.token_env,
        ):
            if name is not None and (
                not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
            ):
                raise ValueError(
                    "credentials and endpoints must use environment variable names"
                )
        if self.provider == "azure" and (
            not self.api_base_env
            or not self.api_version_env
            or not (self.api_key_env or self.token_env)
        ):
            raise ValueError(
                "Azure profiles require endpoint, API version, and credential environment references"
            )
        if self.provider == "openrouter" and (
            not self.api_key_env
            or self.token_env
            or self.api_version_env
            or self.api_base_env
        ):
            raise ValueError(
                "OpenRouter profiles require their own API key and fixed OpenRouter endpoint"
            )
        if (
            isinstance(self.timeout, bool)
            or not isinstance(self.timeout, (int, float))
            or not math.isfinite(self.timeout)
            or self.timeout <= 0
        ):
            raise ValueError("profile timeout must be finite and positive")
        if not isinstance(self.development_only, bool):
            raise ValueError("development_only must be boolean")
        if not isinstance(self.supported_parameters, (list, tuple)) or any(
            not isinstance(p, str) for p in self.supported_parameters
        ):
            raise ValueError("supported_parameters must be a list of parameter names")
        if len(set(self.supported_parameters)) != len(self.supported_parameters):
            raise ValueError("supported_parameters contains duplicates")
        object.__setattr__(
            self, "supported_parameters", tuple(self.supported_parameters)
        )
        params = json.loads(json.dumps(dict(self.parameters), allow_nan=False))
        self.validate_parameters(params)
        if not any(p in params for p in ("max_tokens", "max_completion_tokens")):
            raise ValueError("profiles require an explicit output token limit")
        object.__setattr__(self, "parameters", params)

    def validate_parameters(self, parameters: Mapping[str, Any]) -> None:
        unknown = set(parameters) - _PARAMETERS
        unsupported = set(parameters) - set(self.supported_parameters)
        if unknown or unsupported:
            raise ValueError(
                "unsupported profile parameters: "
                + ", ".join(sorted(unknown | unsupported))
            )
        if "max_tokens" in parameters and "max_completion_tokens" in parameters:
            raise ValueError("choose one output token parameter")
        for key in ("max_tokens", "max_completion_tokens"):
            if key in parameters and (
                type(parameters[key]) is not int or parameters[key] <= 0
            ):
                raise ValueError(key + " must be a positive integer")
        if "temperature" in parameters:
            t = parameters["temperature"]
            if (
                isinstance(t, bool)
                or not isinstance(t, (float, int))
                or not math.isfinite(t)
                or not 0 <= t <= 2
            ):
                raise ValueError("temperature must be between 0 and 2")
        if "reasoning_effort" in parameters and parameters["reasoning_effort"] not in {
            "none",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
        }:
            raise ValueError("unsupported reasoning effort")
        if "seed" in parameters and type(parameters["seed"]) is not int:
            raise ValueError("seed must be an integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            k: (
                list(v) if isinstance(v, tuple) else dict(v) if k == "parameters" else v
            )
            for k, v in vars(self).items()
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProviderProfile":
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("provider profile must declare " + SCHEMA_VERSION)
        if set(data) - set(cls.__dataclass_fields__):
            raise ValueError("unknown provider profile fields")
        return cls(**data)

    def client(self) -> "ProfileClient":
        return ProfileClient(self)

    def request_options(
        self, environ: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        env = os.environ if environ is None else environ
        result: dict[str, Any] = {
            "timeout": self.timeout,
            "extra": {"num_retries": 0, "drop_params": False},
        }
        if self.provider == "stub":
            return result

        def required(name: str | None) -> str:
            value = env.get(name or "", "").strip()
            if not value:
                raise ValueError("missing environment variable " + str(name))
            return value

        if self.provider == "azure":
            base = required(self.api_base_env)
            parsed = urlsplit(base)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "Azure endpoint must be an HTTPS URL without credentials or query parameters"
                )
            result["api_base"] = base
            result["extra"]["api_version"] = required(self.api_version_env)
            if self.token_env and env.get(self.token_env, "").strip():
                result["extra"]["azure_ad_token"] = required(self.token_env)
            else:
                result["api_key"] = required(self.api_key_env)
        else:
            result["api_base"] = "https://openrouter.ai/api/v1"
            result["api_key"] = required(self.api_key_env)
            result["extra"]["extra_body"] = {
                "provider": {"require_parameters": True, "allow_fallbacks": False}
            }
        return result


class ProfileClient:
    """One frozen profile usable through either model-client protocol."""

    def __init__(self, profile: ProviderProfile):
        self.profile = ProviderProfile.from_dict(profile.to_dict())
        self.model = profile.model
        self.api_base = (
            os.environ.get(profile.api_base_env or "")
            if profile.provider == "azure"
            else (
                "https://openrouter.ai/api/v1"
                if profile.provider == "openrouter"
                else None
            )
        )
        self.extra = {"profile_sha256": profile.digest}
        if profile.api_version_env:
            self.extra["api_version"] = os.environ.get(profile.api_version_env)

    def __call__(self, call: Any, tools: Any = None) -> Any:
        if self.profile.digest != self.extra["profile_sha256"]:
            raise ValueError("provider profile changed after the client was bound")
        from arisekit.client import LiteLLMClient, ModelCall, ReferenceStubClient
        from arisekit.runtime.agent_clients import LiteLLMAgentClient

        if self.profile.provider == "stub":
            if not isinstance(call, ModelCall):
                raise ValueError("use the FHIR reference stub for tool trajectories")
            return ReferenceStubClient()(call)
        params = dict(self.profile.parameters)
        if isinstance(call, ModelCall):
            if call.extra:
                raise ValueError(
                    "profile clients do not accept unpinned call extra parameters"
                )
            if call.temperature is not None:
                params["temperature"] = call.temperature
            if call.max_tokens is not None:
                key = (
                    "max_completion_tokens"
                    if "max_completion_tokens" in params
                    else "max_tokens"
                )
                params[key] = call.max_tokens
        elif tools and not {"tools", "tool_choice"}.issubset(
            self.profile.supported_parameters
        ):
            raise ValueError("profile does not declare tool support")
        self.profile.validate_parameters(params)
        options = self.profile.request_options()
        if options.get("api_base") != self.api_base or options["extra"].get(
            "api_version"
        ) != self.extra.get("api_version"):
            raise ValueError(
                "provider endpoint or API version changed after the client was bound"
            )
        options["temperature"] = params.pop("temperature", None)
        options["max_tokens"] = params.pop("max_tokens", None)
        options["extra"].update(params)
        if isinstance(call, ModelCall):
            from dataclasses import replace

            return LiteLLMClient(self.model, **options)(
                replace(call, temperature=None, max_tokens=None)
            )
        return LiteLLMAgentClient(self.model, **options)(call, tools)


def load_profile(path: str | Path) -> ProviderProfile:
    return ProviderProfile.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def development_profile() -> ProviderProfile:
    return ProviderProfile(
        name="development-openrouter",
        provider="openrouter",
        model="openrouter/openai/gpt-4o-mini",
        api_key_env="OPENROUTER_API_KEY",
        parameters={"temperature": 0, "max_tokens": 256},
        development_only=True,
    )


def check_connection(
    profile: ProviderProfile,
    *,
    live: bool = False,
    check_tools: bool = True,
    client: Any = None,
) -> dict[str, Any]:
    """Live checks send at most two synthetic requests and never execute a tool."""
    from dataclasses import replace
    from arisekit.client import ModelCall
    from arisekit.types import BenchmarkItem, Tool

    report: dict[str, Any] = {
        "schema_version": "arisekit.connection-check.v1",
        "profile_sha256": profile.digest,
        "profile": profile.name,
        "model": profile.model,
        "live": live,
        "ready": False,
        "checks": {},
        "calls": 0,
        "cost_usd": 0.0,
        "cost_known": True,
    }
    checks = report["checks"]
    try:
        profile.request_options()
    except ValueError as exc:
        checks["configuration"] = {"status": "failed", "detail": str(exc)}
        return report
    checks["configuration"] = {"status": "passed"}
    for name in ("authentication", "deployment", "parameters", "tools"):
        checks[name] = {"status": "not-verified"}
    if not live:
        return report
    params = dict(profile.parameters)
    key = "max_completion_tokens" if "max_completion_tokens" in params else "max_tokens"
    params[key] = min(params[key], 128)
    probe = client or replace(profile, parameters=params).client()
    for stage in ("parameters", "tools") if check_tools else ("parameters",):
        if stage == "tools" and not {"tools", "tool_choice"}.issubset(
            profile.supported_parameters
        ):
            checks[stage] = {"status": "unsupported"}
            break
        try:
            report["calls"] += 1
            if stage == "parameters":
                output = probe(
                    ModelCall(
                        BenchmarkItem(
                            id="connection-check",
                            prompt="Reply with OK. This is a synthetic connection test.",
                        )
                    )
                )
            else:
                tool = Tool(
                    name="connection_check",
                    description="Confirm the synthetic connection test.",
                    parameters={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                    fn=lambda: "OK",
                )
                output = probe(
                    [
                        {
                            "role": "user",
                            "content": "Call connection_check with no arguments. Do not answer in text.",
                        }
                    ],
                    [tool],
                )
            valid_cost = (
                output.cost_known is True
                and isinstance(output.cost, (int, float))
                and math.isfinite(output.cost)
                and output.cost >= 0
            )
            report["cost_known"] = report["cost_known"] and valid_cost
            if valid_cost:
                report["cost_usd"] += output.cost
            checks["authentication"] = checks["deployment"] = {"status": "passed"}
            if stage == "tools" and not any(
                c.get("name") == "connection_check" and c.get("arguments") == {}
                for c in output.tool_calls
            ):
                checks[stage] = {
                    "status": "failed",
                    "detail": "No matching tool call returned; tool capability remains unverified.",
                }
            else:
                checks[stage] = {"status": "passed"}
        except Exception as exc:
            report["cost_known"] = False
            status = getattr(exc, "status_code", None)
            category = (
                "authentication"
                if status in {401, 403}
                else "deployment" if status == 404 else stage
            )
            checks[category] = {
                "status": "failed",
                "error_type": type(exc).__name__,
                "http_status": status if isinstance(status, int) else None,
            }
            break
    required = (
        ("authentication", "deployment", "parameters", "tools")
        if check_tools
        else ("authentication", "deployment", "parameters")
    )
    report["ready"] = all(checks[name]["status"] == "passed" for name in required)
    return report
