"""Offline tests for the litellm AgentClient adapter's pure translators.

The network __call__ is not exercised; the message/tool/response
translation helpers are, using fabricated litellm-shaped objects.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from arisekit.runtime.agent_clients import _parse_completion, _to_provider_messages, _tool_schemas
from arisekit.agentic import AgentTurnOutput
from arisekit.types import Tool


def _tool() -> Tool:
    return Tool(
        name="get_x",
        description="get x",
        parameters={"type": "object", "properties": {"a": {"type": "integer"}}},
        fn=lambda **k: {},
    )


def test_tool_schemas_render_openai_function_shape():
    schemas = _tool_schemas([_tool()])
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "get_x"
    assert schemas[0]["function"]["parameters"]["properties"] == {"a": {"type": "integer"}}


def test_to_provider_messages_translates_tool_calls_and_results():
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "name": "get_x", "arguments": {"a": 1}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "get_x", "content": {"ok": True}},
        {"role": "assistant", "content": "final", "tool_calls": []},
    ]
    out = _to_provider_messages(msgs)
    call = out[2]
    assert call["tool_calls"][0]["type"] == "function"
    assert call["tool_calls"][0]["function"]["name"] == "get_x"
    assert json.loads(call["tool_calls"][0]["function"]["arguments"]) == {"a": 1}
    tool_msg = out[3]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1"
    assert isinstance(tool_msg["content"], str) and "ok" in tool_msg["content"]
    assert out[4] == {"role": "assistant", "content": "final"}


def test_parse_completion_extracts_text_tool_calls_and_usage():
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content=None,
            tool_calls=[SimpleNamespace(id="c1", function=SimpleNamespace(name="get_x", arguments='{"a": 2}'))],
        ))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )
    out = _parse_completion(resp)
    assert isinstance(out, AgentTurnOutput)
    assert out.text is None
    assert out.tool_calls == [{"id": "c1", "name": "get_x", "arguments": {"a": 2}}]
    assert out.tokens_in == 10 and out.tokens_out == 5


def test_parse_completion_handles_plain_text_and_bad_json_args():
    plain = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello", tool_calls=None))],
        usage=None,
    )
    out = _parse_completion(plain)
    assert out.text == "hello" and out.tool_calls == [] and out.tokens_in == 0

    bad = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content=None,
            tool_calls=[SimpleNamespace(id="c", function=SimpleNamespace(name="f", arguments="not json"))],
        ))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )
    assert _parse_completion(bad).tool_calls[0]["arguments"] == {}
