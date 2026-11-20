"""Model client.

The framework uses any callable that matches the ModelClient Protocol.
The default implementation (`LiteLLMClient`) wraps litellm to give us
100+ providers, multimodal image base64 encoding, and cost tracking.

Users can substitute their own callable for institutional gateways,
locally hosted models, or test mocks. The runner doesn't know or care
which one it has.
"""

from __future__ import annotations

import base64
import copy
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from arisekit.common.llm import LiteLLMBase, validated_extra
from arisekit.types import BenchmarkItem


REFERENCE_STUB_MODEL = "stub/reference"


@dataclass
class ModelCall:
    """Input to the client. Built by the runner per (item, trial)."""

    item: BenchmarkItem
    system_prompt: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    extra: dict[str, Any] | None = None


@dataclass
class ModelResponse:
    """What every client returns."""

    text: str
    raw: Any = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    cost_known: bool = True
    finish_reason: str | None = None
    provider_model: str | None = None
    response_id: str | None = None


class ModelClient(Protocol):
    """Any callable with this shape is a valid model client."""

    def __call__(self, call: ModelCall) -> ModelResponse:  # pragma: no cover
        ...


class ReferenceStubClient:
    """Local, non-clinical contract-test client for ``stub/reference``.

    The client returns each item's reference answer without inference or any
    provider call. It exists only to exercise scaffold, runner, and result
    plumbing; its output is not evidence of model or clinical performance.
    """

    model = REFERENCE_STUB_MODEL

    def __call__(self, call: ModelCall) -> ModelResponse:
        return ModelResponse(
            text=str(call.item.ground_truth),
            cost=0.0,
            cost_known=True,
            finish_reason="stop",
            provider_model=self.model,
        )


# --- default implementation: litellm wrapper ------------------------


class LiteLLMClient(LiteLLMBase):
    """Default model client. Resolves a model string via litellm."""

    def __call__(self, call: ModelCall) -> ModelResponse:
        response = self._complete(
            _build_messages(call),
            temperature=call.temperature if call.temperature is not None else self.temperature,
            max_tokens=call.max_tokens or self.max_tokens,
            extra=validated_extra(call.extra, "call extra") if call.extra else None,
        )
        choice = response.choices[0]
        text = (choice.message.content or "") if hasattr(choice, "message") else ""
        usage = getattr(response, "usage", None)
        cost, cost_known = self._cost(response)
        return ModelResponse(
            text=text,
            raw=response,
            tokens_in=int(getattr(usage, "prompt_tokens", 0) or 0),
            tokens_out=int(getattr(usage, "completion_tokens", 0) or 0),
            cost=cost,
            cost_known=cost_known,
            finish_reason=getattr(choice, "finish_reason", None),
            provider_model=_optional_identifier(getattr(response, "model", None)),
            response_id=_optional_identifier(getattr(response, "id", None)),
        )


def _build_messages(call: ModelCall) -> list[dict[str, Any]]:
    """Turn (system_prompt, item.prompt, attachments) into a chat list.

    - string prompt -> single user message
    - list prompt -> use as-is (caller already supplied the chat shape)
    - attachments -> appended as image_url content blocks to the last user msg
    """
    item = call.item
    messages: list[dict[str, Any]] = []
    if call.system_prompt:
        messages.append({"role": "system", "content": call.system_prompt})

    if isinstance(item.prompt, str):
        messages.append({"role": "user", "content": item.prompt})
    else:
        messages.extend(copy.deepcopy(item.prompt))

    if item.attachments:
        _attach_images(messages, item.attachments)

    return messages


def _attach_images(messages: list[dict[str, Any]], attachments: list[str]) -> None:
    """Append image attachments as image_url content blocks to the last user msg.

    Existing string content gets promoted to a content-block list so we
    can mix text + images. Only image MIME types are attached; other
    file types are ignored (the runner can read them via item metadata).
    """
    if not messages or not attachments:
        return
    target_idx = next(
        (i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"),
        None,
    )
    if target_idx is None:
        return
    target = messages[target_idx]
    content = target.get("content", "")
    if isinstance(content, str):
        blocks: list[dict[str, Any]] = [{"type": "text", "text": content}] if content else []
    else:
        blocks = list(content)

    for att in attachments:
        encoded = _encode_image(att)
        if encoded is None:
            raise ValueError(
                f"image attachment is missing or has an unsupported media type: {att}"
            )
        blocks.append({"type": "image_url", "image_url": {"url": encoded}})

    target["content"] = blocks


def _encode_image(path_or_url: str) -> str | None:
    if path_or_url.startswith(("http://", "https://", "data:")):
        return path_or_url
    path = Path(path_or_url)
    if not path.exists():
        return None
    mime, _ = mimetypes.guess_type(str(path))
    if not mime or not mime.startswith("image/"):
        return None
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


# --- helpers --------------------------------------------------------


def resolve_client(spec: str | ModelClient) -> ModelClient:
    """Accept a callable or resolve a model-id string to its client."""
    if callable(spec) and not isinstance(spec, str):
        return spec  # type: ignore[return-value]
    if spec == REFERENCE_STUB_MODEL:
        return ReferenceStubClient()
    return LiteLLMClient(model=str(spec))


def _optional_identifier(value: Any) -> str | None:
    """Return a provider identifier only when it is safe to persist as text."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
