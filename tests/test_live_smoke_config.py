import pytest

from live_smoke_config import client_options, live_enabled


@pytest.mark.parametrize("value", [None, "", "0", "false", "yes", "true"])
def test_live_inference_requires_exact_opt_in(value):
    assert not live_enabled({} if value is None else {"ARISEKIT_LIVE": value})
    assert live_enabled({"ARISEKIT_LIVE": "1"})


def test_azure_key_options_support_reasoning_without_temperature_or_legacy_limit():
    settings = client_options("azure/gpt-5-mini", {
        "AZURE_API_BASE": "https://example.openai.azure.com",
        "AZURE_API_VERSION": "2024-12-01-preview",
        "AZURE_API_KEY": "test-only-key",
        "ARISEKIT_LIVE_REASONING_EFFORT": "low",
        "ARISEKIT_LIVE_MAX_TOKENS": "512",
    })
    assert settings["temperature"] is None
    assert settings["max_tokens"] is None
    assert settings["api_key"] == "test-only-key"
    assert settings["extra"] == {
        "num_retries": 0, "reasoning_effort": "low", "max_completion_tokens": 512,
        "api_version": "2024-12-01-preview",
    }


def test_azure_entra_token_does_not_require_or_forward_an_api_key():
    settings = client_options("azure/deployment", {
        "AZURE_API_BASE": "https://example.openai.azure.com",
        "AZURE_API_VERSION": "2024-12-01-preview",
        "AZURE_AD_TOKEN": "test-only-token", "AZURE_API_KEY": "unused-key",
    })
    assert "api_key" not in settings
    assert settings["extra"]["azure_ad_token"] == "test-only-token"


def test_azure_does_not_use_an_unrelated_provider_key():
    with pytest.raises(ValueError, match="Azure live tests require"):
        client_options("azure/gpt-5-mini", {"OPENROUTER_API_KEY": "test-only-key"})


@pytest.mark.parametrize("limit", ["0", "-1", "2049", "1.5"])
def test_live_token_budget_rejects_invalid_or_excessive_limits(limit):
    with pytest.raises(ValueError):
        client_options("gpt-4o-mini", {"ARISEKIT_LIVE_MAX_TOKENS": limit})


def test_non_azure_route_does_not_receive_azure_endpoint_or_credentials():
    settings = client_options("openrouter/example", {
        "AZURE_API_BASE": "https://example.openai.azure.com", "AZURE_API_KEY": "unused-key",
    })
    assert "api_key" not in settings and "api_base" not in settings
    assert settings["max_tokens"] == 1024
