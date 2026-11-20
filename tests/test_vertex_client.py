import pytest

from arisekit.client import ModelCall
from arisekit.types import BenchmarkItem
from arisekit.vertex_client import GCloudToken, VertexClient


def client(model="gemini-4-argon"):
    return VertexClient(model, project="configured-project", token=lambda: "fixture-only", thinking_level="HIGH")


def test_explicit_route_and_effective_reasoning_settings_without_credentials_in_body():
    call = ModelCall(item=BenchmarkItem(id="case", prompt="A fictional question"), temperature=0, max_tokens=32768)
    url, body = client().request(call)
    assert "/projects/configured-project/locations/global/publishers/google/models/gemini-4-argon:generateContent" in url
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "HIGH"}
    assert "temperature" not in body["generationConfig"]
    assert "fixture-only" not in str(body)
    _, older = client("gemini-3.1-pro-preview").request(call)
    assert older["generationConfig"]["temperature"] == 0
    assert "gross tariff estimate" in client().configuration()["cost_basis"]


def test_cost_includes_thinking_tokens_and_discounts_cached_input_without_claiming_promotional_credits():
    response = client().parse({"modelVersion": "gemini-4-argon", "responseId": "provider-response",
        "candidates": [{"content": {"parts": [{"text": "hidden", "thought": True}, {"text": "1"}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 100, "cachedContentTokenCount": 20, "candidatesTokenCount": 10,
                          "thoughtsTokenCount": 30, "totalTokenCount": 140}})
    assert response.text == "1" and response.tokens_out == 40
    assert response.cost == pytest.approx(.001124)
    assert response.cost_known and response.finish_reason == "stop"


def test_unknown_usage_and_unexpected_model_are_not_silently_accepted():
    unknown = client().parse({"modelVersion": "gemini-4-argon", "responseId": "missing-usage", "candidates": []})
    assert not unknown.cost_known
    with pytest.raises(ValueError, match="unexpected model"):
        client().parse({"modelVersion": "unrequested-model"})


def test_argon_long_decode_uses_supported_api_and_marks_unfinished_segments():
    url, _ = client().request(ModelCall(item=BenchmarkItem(id="long", prompt="Fictional request"), max_tokens=65536))
    assert "/v1beta1/projects/" in url
    response = client().parse({"modelVersion": "gemini-4-argon", "responseId": "segment",
        "candidates": [{"content": {"parts": [{"text": "partial"}]}, "finishReason": "CONTINUATION"}],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 1, "totalTokenCount": 11}})
    assert response.finish_reason == "length"


def test_structural_contract_is_sent_without_mutating_local_schema():
    schema = {"type": "object", "additionalProperties": False, "properties": {"answer": {"const": "fixed"}}, "required": ["answer"]}
    item = BenchmarkItem(id="structured", prompt="A fictional contract", metadata={"response_schema": schema})
    _, body = client().request(ModelCall(item=item))
    assert body["generationConfig"]["responseJsonSchema"]["properties"]["answer"] == {"enum": ["fixed"]}
    assert schema["additionalProperties"] is False and schema["properties"]["answer"] == {"const": "fixed"}


def test_vertex_quota_account_selection_does_not_change_active_gcloud_configuration(monkeypatch):
    import json
    from datetime import datetime, timedelta, timezone
    import arisekit.vertex_client as vertex
    calls = []
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    monkeypatch.setattr(vertex.subprocess, "check_output", lambda args, **kwargs: calls.append(args) or json.dumps(
        {"credential": {"access_token": "fixture-token", "token_expiry": expiry}}))
    token = GCloudToken("configured-account@example.test")
    assert token() == token() == "fixture-token"
    assert calls == [["gcloud", "config", "config-helper", "--min-expiry=5m",
        "--format=json(credential)", "--account=configured-account@example.test"]]


def test_google_token_cache_uses_actual_remaining_lifetime(monkeypatch):
    import json
    from datetime import datetime, timedelta, timezone
    import arisekit.vertex_client as vertex
    clock, calls = [100.0], []
    monkeypatch.setattr(vertex.time, "monotonic", lambda: clock[0])
    def credentials(*args, **kwargs):
        calls.append(True)
        lifetime = 90 if len(calls) == 1 else 3600
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=lifetime)).isoformat()
        return json.dumps({"credential": {"access_token": f"fixture-{len(calls)}", "token_expiry": expiry}})
    monkeypatch.setattr(vertex.subprocess, "check_output", credentials)
    token = GCloudToken("configured-account@example.test")
    assert token() == "fixture-1"
    clock[0] += 20
    assert token() == "fixture-1"
    clock[0] += 11
    assert token() == "fixture-2" and len(calls) == 2


def test_google_token_without_verified_expiry_is_not_cached(monkeypatch):
    import json
    import arisekit.vertex_client as vertex
    monkeypatch.setattr(vertex.subprocess, "check_output", lambda *a, **k: json.dumps(
        {"credential": {"access_token": "fixture"}}))
    with pytest.raises(ValueError, match="with an expiry"):
        GCloudToken("configured-account@example.test")()


def test_google_token_refreshes_after_sleep_even_when_monotonic_clock_stops(monkeypatch):
    import json
    from datetime import datetime, timezone
    import arisekit.vertex_client as vertex
    wall, calls = [1792790000.0], []
    monkeypatch.setattr(vertex.time, "time", lambda: wall[0])
    monkeypatch.setattr(vertex.time, "monotonic", lambda: 100.0)
    def credentials(*args, **kwargs):
        calls.append(True)
        expiry = datetime.fromtimestamp(wall[0] + 3600, timezone.utc).isoformat()
        return json.dumps({"credential": {"access_token": f"fixture-{len(calls)}", "token_expiry": expiry}})
    monkeypatch.setattr(vertex.subprocess, "check_output", credentials)
    token = GCloudToken("configured-account@example.test")
    assert token() == token() == "fixture-1"
    wall[0] += 3601
    assert token() == "fixture-2" and len(calls) == 2


def test_claude_profile_keeps_mandatory_thinking_and_includes_native_cache_usage():
    opus = client("claude-opus-5-5")
    _, body = opus.request(ModelCall(item=BenchmarkItem(id="case", prompt="A fictional question"), temperature=0))
    assert body["output_config"]["effort"] == "high"
    assert "thinking" not in body and "temperature" not in body
    r = opus.parse({"id": "opus-response", "model": "claude-opus-5-5", "stop_reason": "end_turn",
        "content": [{"type": "thinking", "thinking": "not answer text"}, {"type": "text", "text": "0"}],
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50}})
    assert r.text == "0" and r.tokens_in == 150 and r.cost == pytest.approx(.00081)
