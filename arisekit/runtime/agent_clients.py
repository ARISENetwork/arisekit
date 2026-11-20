"""litellm-backed AgentClient: a real tool-using model as a system under test.

This is the Phase 4 adapter promised in `arisekit.agentic`: it translates
between ARISEKit's internal agentic message and tool shapes and the
OpenAI-style tool-calling format litellm speaks, so `run_agent` can drive
any of litellm's providers. The pure translation helpers
(`_tool_schemas`, `_to_provider_messages`, `_parse_completion`) are unit
tested offline; `__call__` is a thin wrapper over `litellm.completion`
(imported lazily, exactly like `arisekit.client.LiteLLMClient`).
"""

from __future__ import annotations

import json
from typing import Any

from arisekit.agentic import AgenticPassCondition, AgentTurnOutput
from arisekit.client import REFERENCE_STUB_MODEL
from arisekit.common.llm import LiteLLMBase
from arisekit.types import Tool


def _tool_schemas(tools: list[Tool]) -> list[dict[str, Any]]:
    """Render ARISEKit Tools as OpenAI-style function tool schemas."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def _to_provider_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate run_agent's internal message history into provider shape.

    run_agent stores assistant tool calls as {"id","name","arguments"(dict)}
    and tool results as {"role":"tool","tool_call_id","name","content"(any)}.
    The provider wants OpenAI-style assistant.tool_calls with a stringified
    function.arguments, and tool messages whose content is a string.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "assistant":
            tool_calls = m.get("tool_calls") or []
            if tool_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": m.get("content") or None,
                        "tool_calls": [
                            {
                                "id": c.get("id"),
                                "type": "function",
                                "function": {
                                    "name": c.get("name"),
                                    "arguments": json.dumps(c.get("arguments") or {}),
                                },
                            }
                            for c in tool_calls
                        ],
                    }
                )
            else:
                out.append({"role": "assistant", "content": m.get("content") or ""})
        elif role == "tool":
            content = m.get("content")
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id"),
                    "content": content if isinstance(content, str) else json.dumps(content),
                }
            )
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return out


def _parse_completion(response: Any) -> AgentTurnOutput:
    """Turn a litellm/OpenAI completion into one AgentTurnOutput."""
    choice = response.choices[0]
    msg = choice.message
    text = getattr(msg, "content", None)
    raw_calls = getattr(msg, "tool_calls", None) or []
    tool_calls: list[dict[str, Any]] = []
    for tc in raw_calls:
        fn = tc.function
        raw_args = getattr(fn, "arguments", None)
        try:
            args = json.loads(raw_args) if raw_args else {}
        except (json.JSONDecodeError, TypeError):
            args = {}
        tool_calls.append({"id": getattr(tc, "id", None), "name": fn.name, "arguments": args})
    usage = getattr(response, "usage", None)
    tokens_in = getattr(usage, "prompt_tokens", 0) or 0
    tokens_out = getattr(usage, "completion_tokens", 0) or 0
    return AgentTurnOutput(
        text=text,
        tool_calls=tool_calls,
        tokens_in=int(tokens_in),
        tokens_out=int(tokens_out),
    )


class LiteLLMAgentClient(LiteLLMBase):
    """An AgentClient that drives a real tool-using model via litellm."""
    extra_label = "agent client extra"

    def __call__(self, messages: list[dict[str, Any]], tools: list[Tool]) -> AgentTurnOutput:
        provider_messages = _to_provider_messages(messages)
        request = {"tools": _tool_schemas(tools), "tool_choice": "auto"} if tools else {}
        response = self._complete(provider_messages, temperature=self.temperature, max_tokens=self.max_tokens,
                                  request=request)
        out = _parse_completion(response)
        out.cost, out.cost_known = self._cost(response)
        return out


class ReferenceStubAgentClient:
    """Keyless agent client that executes one item's frozen reference calls.

    This is the agentic counterpart to ``ReferenceStubClient``. It exists only
    to prove package, environment, tool-loop, checkpoint, and scorer plumbing.
    It is constructed per item so concurrent smoke trials share no mutable
    cursor state.
    """

    model = REFERENCE_STUB_MODEL

    def __init__(self, condition: AgenticPassCondition | None = None):
        self.condition = condition

    def for_condition(
        self,
        condition: AgenticPassCondition,
    ) -> "ReferenceStubAgentClient":
        return type(self)(condition)

    def __call__(
        self,
        messages: list[dict[str, Any]],
        tools: list[Tool],
    ) -> AgentTurnOutput:
        if self.condition is None:
            raise RuntimeError("reference agent client is missing an item condition")
        answer = " ".join(self.condition.final_response_contains)
        if not answer:
            answer = "Reference tool calls completed."
        if any(message.get("role") == "tool" for message in messages):
            return AgentTurnOutput(text=answer)
        return AgentTurnOutput(
            text=answer,
            tool_calls=[
                {
                    "id": f"reference-call-{index}",
                    "name": call.name,
                    "arguments": dict(call.arguments),
                }
                for index, call in enumerate(
                    self.condition.required_tool_calls,
                    start=1,
                )
            ],
        )


__all__ = ["LiteLLMAgentClient", "ReferenceStubAgentClient"]
