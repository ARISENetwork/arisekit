from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from arisekit.client import LiteLLMClient, ModelCall, _build_messages
from arisekit.types import BenchmarkItem


def test_litellm_client_forwards_constructor_extra(monkeypatch):
    captured = {}

    def completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok"),
                    finish_reason="stop",
                )
        ],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
        model="provider/model-2026-07-01",
        id="response-123",
    )

    fake_litellm = SimpleNamespace(
        completion=completion,
        completion_cost=lambda **_: 0.01,
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    client = LiteLLMClient(
        "provider/model",
        extra={"extra_body": {"reasoning": {"effort": "low"}}},
    )
    response = client(ModelCall(BenchmarkItem(id="case", prompt="question")))

    assert captured["extra_body"] == {"reasoning": {"effort": "low"}}
    assert response.text == "ok"
    assert response.tokens_in == 3
    assert response.tokens_out == 2
    assert response.cost == 0.01
    assert response.provider_model == "provider/model-2026-07-01"
    assert response.response_id == "response-123"


def test_litellm_client_prefers_gateway_reported_cost(monkeypatch):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="ok"),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
        _hidden_params={"response_cost": 0.02},
    )
    fake_litellm = SimpleNamespace(
        completion=lambda **_: response,
        completion_cost=lambda **_: 0.0,
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    client = LiteLLMClient("provider/model")

    result = client(ModelCall(BenchmarkItem(id="case", prompt="question")))
    assert result.cost == 0.02


def test_litellm_client_marks_unavailable_pricing_as_unknown(monkeypatch):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="ok"),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
    )
    fake_litellm = SimpleNamespace(
        completion=lambda **_: response,
        completion_cost=lambda **_: None,
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    result = LiteLLMClient("provider/model")(
        ModelCall(BenchmarkItem(id="case", prompt="question"))
    )

    assert result.cost == 0.0
    assert result.cost_known is False


@pytest.mark.parametrize(
    "extra",
    [
        {"model": "different/model"},
        {"messages": [{"role": "user", "content": "replacement"}]},
        {"temperature": 1.0},
        {"fallbacks": ["different/model"]},
    ],
)
def test_litellm_extra_cannot_override_request_identity(extra):
    with pytest.raises(ValueError, match="reserved request fields"):
        LiteLLMClient("provider/model", extra=extra)


def test_build_messages_does_not_mutate_message_list_prompt(tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    prompt = [{"role": "user", "content": "Describe this image."}]
    item = BenchmarkItem(
        id="case",
        prompt=prompt,
        attachments=[str(image)],
    )

    first = _build_messages(ModelCall(item))
    second = _build_messages(ModelCall(item))

    assert prompt == [{"role": "user", "content": "Describe this image."}]
    assert len(first[0]["content"]) == 2
    assert len(second[0]["content"]) == 2


def test_build_messages_rejects_missing_image_instead_of_silently_dropping_it(
    tmp_path,
):
    item = BenchmarkItem(
        id="case",
        prompt="Describe this image.",
        attachments=[str(tmp_path / "missing.png")],
    )

    with pytest.raises(ValueError, match="missing or has an unsupported"):
        _build_messages(ModelCall(item))
