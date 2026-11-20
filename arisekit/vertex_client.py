"""Direct, explicitly scoped Vertex clients for frozen text evaluations."""

from __future__ import annotations

import json
from datetime import datetime
import subprocess
import threading
import time
import urllib.request

from arisekit.client import ModelCall, ModelResponse

PRICING_SOURCE = "https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing"
MODELS = {"gemini-4-argon": "google", "gemini-3.1-pro-preview": "google", "claude-opus-5-5": "anthropic"}


class GCloudToken:
    """Use an existing account without changing the machine's active project."""

    def __init__(self, account):
        if not isinstance(account, str) or not account.strip():
            raise ValueError("Select the configured Google account explicitly")
        self.account, self.lock = account, threading.Lock()
        self._token, self._expires, self._expires_at = None, 0, 0

    def __call__(self):
        with self.lock:
            if self._token is None or time.monotonic() >= self._expires or time.time() >= self._expires_at:
                raw = subprocess.check_output(["gcloud", "config", "config-helper", "--min-expiry=5m",
                    "--format=json(credential)", "--account=" + self.account], text=True)
                credential = json.loads(raw)["credential"]
                token = credential.get("access_token")
                expiry = credential.get("token_expiry")
                if not isinstance(token, str) or not token.strip() or not isinstance(expiry, str):
                    raise ValueError("The selected Google account did not return a token with an expiry")
                expires_at = datetime.fromisoformat(expiry.replace("Z", "+00:00")).timestamp()
                remaining = expires_at - time.time()
                if remaining <= 60:
                    raise ValueError("The selected Google access token expires too soon for dispatch")
                self._token = token.strip()
                # Some monotonic clocks stop during sleep; tokens expire in UTC.
                self._expires_at = expires_at - 60
                self._expires = time.monotonic() + remaining - 60
            return self._token


def response_schema(call):
    schema = call.item.metadata.get("response_schema")
    if call.item.metadata.get("candidate_kind") in {"sct", "cpc", "cpc-ddx"}:
        request = json.loads(call.item.prompt)
        if "original_request" in request:
            request = json.loads(request["original_request"]["prompt"])
        schema = request["contract"]["response_schema"]
    return schema


def google_schema(value):
    if isinstance(value, list):
        return [google_schema(v) for v in value]
    if not isinstance(value, dict):
        return value
    result = {key: google_schema(v) for key, v in value.items() if key not in {"const", "additionalProperties"}}
    if "const" in value:
        result["enum"] = [value["const"]]
    return result


class VertexClient:
    """Report usage-based tariff estimates separately from a settled invoice.

    Raw envelopes belong in a caller-owned private dispatch receipt. The client
    performs no fallback, retry, prompt logging or checkpoint management.
    """

    def __init__(self, model, *, project, token, location="global", thinking_level="HIGH", timeout=900):
        if model not in MODELS:
            raise ValueError("This frozen tariff profile does not cover the requested Vertex model")
        if not all(isinstance(v, str) and v.strip() and "/" not in v for v in (project, location)):
            raise ValueError("Vertex project and location must be explicit identifiers")
        if thinking_level not in {"LOW", "MEDIUM", "HIGH"}:
            raise ValueError("Choose an explicit reasoning level")
        if location != "global":
            raise ValueError("This profile freezes the verified global route and tariff")
        self.provider_model = model
        self.model = "vertex_ai/" + model
        self.project, self.location, self.token = project, location, token
        self.thinking_level, self.timeout = thinking_level, timeout

    def configuration(self):
        return {"provider": "google-vertex", "model": self.provider_model, "project": self.project,
            "location": self.location, "thinking_level": self.thinking_level,
            "temperature": "call value" if self.provider_model == "gemini-3.1-pro-preview" else "provider default; not set",
            "argon_long_decode": "v1beta1 above 32768 requested output tokens; checkpoint handling belongs to the accounted transport",
            "pricing_source": PRICING_SOURCE, "pricing_snapshot": "2026-10-23",
            "cost_basis": "usage-based gross tariff estimate; no promotional credits assumed; not a settled invoice"}

    def request(self, call: ModelCall):
        if call.item.attachments:
            raise ValueError("The frozen text comparison does not silently discard attachments")
        if call.extra:
            raise ValueError("Freeze Vertex settings through the client configuration, not unverified call extras")
        publisher = MODELS[self.provider_model]
        url = (f"https://aiplatform.googleapis.com/v1/projects/{self.project}/locations/{self.location}/"
               f"publishers/{publisher}/models/{self.provider_model}:")
        if self.provider_model == "gemini-4-argon" and (call.max_tokens or 32768) > 32768:
            url = url.replace("/v1/projects/", "/v1beta1/projects/")
        schema = response_schema(call)
        if publisher == "google":
            config = {"maxOutputTokens": call.max_tokens or 32768,
                      "thinkingConfig": {"thinkingLevel": self.thinking_level}}
            if self.provider_model != "gemini-4-argon" and call.temperature is not None:
                config["temperature"] = call.temperature
            if schema is not None:
                config.update(responseMimeType="application/json", responseJsonSchema=google_schema(schema))
            body = {"contents": [{"role": "user", "parts": [{"text": call.item.prompt}]}], "generationConfig": config}
            if call.system_prompt:
                body["systemInstruction"] = {"parts": [{"text": call.system_prompt}]}
            return url + "generateContent", body
        body = {"anthropic_version": "vertex-2023-10-16", "max_tokens": call.max_tokens or 32768,
                "messages": [{"role": "user", "content": call.item.prompt}],
                "output_config": {"effort": self.thinking_level.lower()}}
        if call.system_prompt:
            body["system"] = call.system_prompt
        if schema is not None:
            body["output_config"]["format"] = {"type": "json_schema", "schema": schema}
        return url + "rawPredict", body

    def parse(self, value):
        if MODELS[self.provider_model] == "google":
            candidates = value.get("candidates", [])
            candidate = candidates[0] if candidates else {}
            parts = candidate.get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            usage = value.get("usageMetadata", {})
            input_tokens = usage.get("promptTokenCount")
            visible, thinking = usage.get("candidatesTokenCount", 0), usage.get("thoughtsTokenCount", 0)
            output_tokens = visible + thinking if type(visible) is int and type(thinking) is int else None
            cached = usage.get("cachedContentTokenCount", 0)
            model, identity = value.get("modelVersion"), value.get("responseId")
            reason = {"STOP": "stop", "MAX_TOKENS": "length", "CONTINUATION": "length"}.get(candidate.get("finishReason"),
                candidate.get("finishReason") or value.get("promptFeedback", {}).get("blockReason"))
            long_context = input_tokens is not None and input_tokens > 200000
            rates = (4, .2, 20) if self.provider_model == "gemini-4-argon" else (4, .4, 18) if long_context else (2, .2, 12)
            known = (type(input_tokens) is int and type(output_tokens) is int and type(cached) is int
                     and 0 <= cached <= input_tokens and output_tokens >= 0 and "totalTokenCount" in usage)
            cost = ((input_tokens - cached) * rates[0] + cached * rates[1] + output_tokens * rates[2]) / 1e6 if known else 0
        else:
            text = "".join(p.get("text", "") for p in value.get("content", []) if p.get("type") == "text")
            usage = value.get("usage", {})
            input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
            cached, created = usage.get("cache_read_input_tokens", 0), usage.get("cache_creation_input_tokens", 0)
            known = all(type(v) is int and v >= 0 for v in (input_tokens, output_tokens, cached, created)) and created == 0
            cost = (input_tokens * 4 + output_tokens * 20 + cached * .2) / 1e6 if known else 0
            input_tokens = (input_tokens or 0) + cached + created
            model, identity = value.get("model"), value.get("id")
            reason = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length"}.get(value.get("stop_reason"), value.get("stop_reason"))
        if not isinstance(model, str) or not model.removeprefix("models/").startswith(self.provider_model):
            raise ValueError("Vertex returned an unexpected model identity; retain the response before any recovery")
        return ModelResponse(text=text, raw=value, tokens_in=input_tokens or 0, tokens_out=output_tokens or 0,
            cost=cost, cost_known=known, finish_reason=reason, provider_model=model, response_id=identity)

    def __call__(self, call):
        url, body = self.request(call)
        request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": "Bearer " + self.token(), "x-goog-user-project": self.project, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return self.parse(json.load(response))
