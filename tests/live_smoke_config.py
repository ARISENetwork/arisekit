"""Explicit, bounded provider settings for the opt-in live test suite."""

from collections.abc import Mapping
from typing import Any


def live_enabled(environ: Mapping[str, str]) -> bool:
    return environ.get("ARISEKIT_LIVE") == "1"


def client_options(model: str, environ: Mapping[str, str]) -> dict[str, Any]:
    limit = int(environ.get("ARISEKIT_LIVE_MAX_TOKENS", "1024"))
    if not 1 <= limit <= 2048:
        raise ValueError("ARISEKIT_LIVE_MAX_TOKENS must be between 1 and 2048")
    extra: dict[str, Any] = {"num_retries": 0}
    options: dict[str, Any] = {
        "temperature": None, "max_tokens": limit, "timeout": 45, "extra": extra,
    }
    effort = environ.get("ARISEKIT_LIVE_REASONING_EFFORT")
    if effort:
        if effort not in {"none", "minimal", "low", "medium", "high"}:
            raise ValueError("unsupported ARISEKIT_LIVE_REASONING_EFFORT")
        options["max_tokens"] = None
        extra.update(reasoning_effort=effort, max_completion_tokens=limit)
    if model.startswith("azure/"):
        base = environ.get("AZURE_API_BASE")
        version = environ.get("AZURE_API_VERSION")
        key = environ.get("AZURE_API_KEY")
        token = environ.get("AZURE_AD_TOKEN")
        if not base or not version or not (key or token):
            raise ValueError(
                "Azure live tests require AZURE_API_BASE, AZURE_API_VERSION, "
                "and AZURE_API_KEY or AZURE_AD_TOKEN"
            )
        options["api_base"] = base
        extra["api_version"] = version
        if token:
            extra["azure_ad_token"] = token
        else:
            options["api_key"] = key
    return options
