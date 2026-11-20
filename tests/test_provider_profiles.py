import json
from dataclasses import replace
from types import SimpleNamespace
import sys

import pytest
from arisekit.client import ModelCall, ModelResponse
from arisekit.providers import ProviderProfile, check_connection, development_profile
from arisekit.types import BenchmarkItem


def azure():
    return ProviderProfile(
        name="azure-evaluation",
        provider="azure",
        model="azure/my-deployment",
        api_key_env="AZURE_API_KEY",
        token_env="AZURE_AD_TOKEN",
        api_base_env="AZURE_API_BASE",
        api_version_env="AZURE_API_VERSION",
        parameters={"max_completion_tokens": 512, "reasoning_effort": "low"},
        supported_parameters=(
            "max_completion_tokens",
            "reasoning_effort",
            "tools",
            "tool_choice",
        ),
    )


def test_azure_profile_uses_explicit_token_dialect_and_entra(monkeypatch):
    env = {
        "AZURE_API_BASE": "https://example.openai.azure.com",
        "AZURE_API_VERSION": "2024-12-01-preview",
        "AZURE_AD_TOKEN": "test-token",
        "OPENROUTER_API_KEY": "wrong-provider",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    captured = []

    def completion(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok"), finish_reason="stop"
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            _hidden_params={"response_cost": 0.001},
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))
    result = azure().client()(ModelCall(BenchmarkItem("a", "question"), max_tokens=64))
    kwargs = captured[0]
    assert kwargs["azure_ad_token"] == "test-token"
    assert (
        "api_key" not in kwargs
        and "temperature" not in kwargs
        and "max_tokens" not in kwargs
    )
    assert kwargs["max_completion_tokens"] == 64 and kwargs["num_retries"] == 0
    assert result.cost == 0.001
    assert "test-token" not in json.dumps(azure().to_dict())


def test_profile_never_falls_back_to_another_provider_credential():
    with pytest.raises(ValueError, match="AZURE_API_BASE"):
        azure().request_options({"OPENROUTER_API_KEY": "other"})
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        development_profile().request_options({"OPENAI_API_KEY": "other"})


def test_parameter_dialect_is_checked_before_dispatch():
    with pytest.raises(ValueError, match="unsupported profile parameters"):
        azure().client()(ModelCall(BenchmarkItem("a", "question"), temperature=0.0))
    with pytest.raises(ValueError, match="choose one"):
        replace(
            development_profile(),
            parameters={"max_tokens": 10, "max_completion_tokens": 10},
            supported_parameters=("max_tokens", "max_completion_tokens"),
        )


def test_config_check_never_claims_live_verification(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    report = check_connection(development_profile())
    assert report["calls"] == 0 and report["ready"] is False
    assert report["checks"]["authentication"]["status"] == "not-verified"


def test_live_check_observes_tool_call_and_accounts_both_probes(monkeypatch):
    from arisekit.agentic import AgentTurnOutput

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def probe(call, tools=None):
        return (
            AgentTurnOutput(
                tool_calls=[{"name": "connection_check", "arguments": {}}], cost=0.001
            )
            if tools
            else ModelResponse("OK", cost=0.001)
        )

    report = check_connection(development_profile(), live=True, client=probe)
    assert report["ready"] and report["calls"] == 2 and report["cost_usd"] == 0.002


def test_failed_check_redacts_provider_exception(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")

    class Unauthorized(Exception):
        status_code = 401

    def fail(*args):
        raise Unauthorized("Authorization: Bearer test-secret")

    report = check_connection(development_profile(), live=True, client=fail)
    assert not report["ready"] and report["calls"] == 1
    assert report["checks"]["authentication"]["status"] == "failed"
    assert "test-secret" not in json.dumps(report)


def test_profile_mutation_cannot_change_a_bound_client():
    profile = development_profile()
    client = profile.client()
    client.profile.parameters["max_tokens"] = 2000
    with pytest.raises(ValueError, match="changed after"):
        client(ModelCall(BenchmarkItem("a", "q")))
