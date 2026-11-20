from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from arisekit.runtime.agent_clients import LiteLLMAgentClient
from arisekit.agentic import AgentTurnOutput, PassAtOneScorer
from arisekit.benchmark import Benchmark
from arisekit.client import ModelCall, ModelResponse, REFERENCE_STUB_MODEL
from arisekit.runtime.cost_preview import (
    CLAIM_BOUNDARY,
    SCHEMA_VERSION,
    CostPreview,
    PricingSnapshot,
    default_pricing_resolver,
    preview_benchmark_cost,
)
from arisekit.dataset import Dataset
from arisekit.package import BoundImageAttachment
from arisekit.runner import RunnerConfig, run as run_dataset
from arisekit.scorer import BaseScorer, ExactMatchScorer, _ComposedScorer
from arisekit.sut import ModelSUT, MultimodalImageSUT, SystemUnderTest
from arisekit.types import BenchmarkItem, Metric, RunResult, Tool


class BombTextClient:
    model = "vendor/model"

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, call: ModelCall) -> ModelResponse:
        self.calls += 1
        raise AssertionError("cost preview dispatched a model call")


def _pricing(
    model: str = "vendor/model",
    *,
    max_output_tokens: int | None = 10,
) -> PricingSnapshot:
    return PricingSnapshot.explicit(
        model,
        input_usd_per_million_tokens="1.00",
        output_usd_per_million_tokens="2.00",
        max_output_tokens=max_output_tokens,
        provider="test-provider",
    )


def _text_benchmark(
    tmp_path: Path,
    *,
    max_tokens: int | None = 10,
    scorer: BaseScorer | None = None,
    allowed_model_routes: tuple[str, ...] | None = None,
) -> tuple[Benchmark, BombTextClient]:
    client = BombTextClient()
    benchmark = Benchmark(
        name="preview-fixture",
        dataset=Dataset.from_items(
            [
                {
                    "id": "private-record-alpha",
                    "prompt": "SECRET CLINICAL PROMPT ALPHA",
                    "ground_truth": "SECRET REFERENCE ALPHA",
                },
                {
                    "id": "private-record-beta",
                    "prompt": "SECRET CLINICAL PROMPT BETA",
                    "ground_truth": "SECRET REFERENCE BETA",
                },
            ],
            system_prompt="SECRET SYSTEM PROMPT",
        ),
        scorer=scorer or ExactMatchScorer(),
        runner_config=RunnerConfig(
            trials=2,
            max_retries=2,
            max_tokens=max_tokens,
            results_dir=tmp_path,
        ),
        allowed_model_routes=allowed_model_routes,
        sut_factory=lambda model, **_: ModelSUT(client, name=model),
    )
    return benchmark, client


def test_text_preview_is_no_call_canonical_and_contains_no_case_data(tmp_path: Path):
    benchmark, client = _text_benchmark(tmp_path)
    estimator_calls: list[tuple[str, object, object]] = []

    def estimate(model, messages, tools):
        estimator_calls.append((model, messages, tools))
        return 100

    first = preview_benchmark_cost(
        benchmark,
        model="vendor/model",
        pricing=_pricing(),
        token_estimator=estimate,
    )
    second = preview_benchmark_cost(
        benchmark,
        model="vendor/model",
        pricing=_pricing(),
        token_estimator=lambda *_: 100,
    )

    assert client.calls == 0
    assert len(estimator_calls) == 2
    assert first.to_dict() == second.to_dict()
    assert first.digest == second.digest
    assert CostPreview.from_dict(first.to_dict()).to_dict() == first.to_dict()
    receipt = first.canonical_json()
    assert '"schema_version":"arisekit.cost-preview.v1"' in receipt
    assert SCHEMA_VERSION == "arisekit.cost-preview.v1"
    assert "timestamp" not in receipt
    for forbidden in (
        "SECRET",
        "private-record-alpha",
        "private-record-beta",
    ):
        assert forbidden not in receipt
    payload = first.to_dict()
    expected_prompt_hash = hashlib.sha256(
        json.dumps(
            "SECRET SYSTEM PROMPT",
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert payload["no_model_calls_made"] is True
    assert payload["benchmark"]["system_prompt_sha256"] == expected_prompt_hash
    assert payload["tokens"]["estimator"] == {
        "name": "caller-supplied",
        "version": "caller-supplied",
        "used": True,
    }
    assert payload["run"]["provider_authorization_required"] is False
    assert payload["tokens"] == {
        "estimator": {
            "name": "caller-supplied",
            "version": "caller-supplied",
            "used": True,
        },
        "scope": "complete-call",
        "nominal_input": 400,
        "nominal_output_upper_bound": 40,
        "retry_input_upper_bound": 800,
        "retry_output_upper_bound": 80,
    }
    assert payload["cost"]["nominal_upper_bound_usd"] == "0.000480000000"
    assert payload["cost"]["retry_upper_bound_usd"] == "0.000960000000"
    assert payload["claim_boundary"] == CLAIM_BOUNDARY
    assert first.ready_for_paid_run is True


def test_preview_atomic_write_round_trips(tmp_path: Path):
    benchmark, _ = _text_benchmark(tmp_path)
    preview = preview_benchmark_cost(
        benchmark,
        model="vendor/model",
        pricing=_pricing(),
        token_estimator=lambda *_: 3,
    )
    target = tmp_path / "nested" / "cost-preview.json"
    assert preview.write(target) == target
    assert CostPreview.from_dict(json.loads(target.read_text())) == preview
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))


def test_unknown_pricing_and_unknown_output_limit_block_without_zero_claim(
    tmp_path: Path,
):
    benchmark, _ = _text_benchmark(tmp_path, max_tokens=None)
    preview = preview_benchmark_cost(
        benchmark,
        model="unlisted/model",
        pricing_resolver=lambda _: PricingSnapshot.unavailable("unlisted/model"),
        token_estimator=lambda *_: 5,
    )
    payload = preview.to_dict()
    assert preview.blocker_codes == (
        "pricing-unavailable",
        "max-output-tokens-unavailable",
    )
    assert payload["pricing"]["input_usd_per_million_tokens"] is None
    assert payload["pricing"]["output_usd_per_million_tokens"] is None
    assert payload["cost"]["first_turn_upper_bound_usd"] is None
    assert payload["cost"]["nominal_upper_bound_usd"] is None
    assert payload["cost"]["retry_upper_bound_usd"] is None
    assert preview.ready_for_paid_run is False


def test_resolver_failure_is_a_deterministic_pricing_blocker(tmp_path: Path):
    benchmark, _ = _text_benchmark(tmp_path)

    def unavailable(_model):
        raise LookupError("registry details must not leak into the receipt")

    preview = preview_benchmark_cost(
        benchmark,
        model="vendor/model",
        pricing_resolver=unavailable,
        token_estimator=lambda *_: 5,
    )
    assert preview.blocker_codes == ("pricing-unavailable",)
    assert "registry details" not in preview.canonical_json()


@pytest.mark.parametrize(
    "extra",
    [
        {"tiered_pricing": [{"range": [0, 1000]}]},
        {"input_cost_per_request": 0.01},
        {"regional_endpoint_uplift_multiplier": 1.1},
        {"input_cost_per_token_above_200k_tokens": 0.00001},
    ],
)
def test_default_pricing_fails_closed_for_unsupported_billing_dimensions(
    monkeypatch, extra
):
    import litellm

    model_info = {
        "mode": "chat",
        "input_cost_per_token": 0.000001,
        "output_cost_per_token": 0.000002,
        "max_output_tokens": 100,
        **extra,
    }
    monkeypatch.setattr(litellm, "get_model_info", lambda **_: model_info)
    snapshot = default_pricing_resolver("vendor/tiered-model")
    assert snapshot.known is False
    assert snapshot.to_dict()["input_usd_per_million_tokens"] is None


def test_explicit_override_requires_both_rates_and_matching_route(tmp_path: Path):
    with pytest.raises(ValueError, match="both input and output"):
        PricingSnapshot(
            model_route="vendor/model",
            input_usd_per_million_tokens="1",
            output_usd_per_million_tokens=None,
            max_output_tokens=10,
            source="explicit",
            source_version=SCHEMA_VERSION,
        )

    benchmark, _ = _text_benchmark(tmp_path)
    with pytest.raises(ValueError, match="must match"):
        preview_benchmark_cost(
            benchmark,
            model="vendor/model",
            pricing=_pricing("other/model"),
            token_estimator=lambda *_: 1,
        )


def test_preview_enforces_benchmark_route_allowlist(tmp_path: Path):
    benchmark, client = _text_benchmark(
        tmp_path, allowed_model_routes=("reviewed/model",)
    )
    with pytest.raises(ValueError, match="reviewed allowlist"):
        preview_benchmark_cost(
            benchmark,
            model="vendor/model",
            pricing=_pricing(),
            token_estimator=lambda *_: 1,
        )
    assert client.calls == 0


class UnknownScorer(BaseScorer):
    def score_item(
        self, item: BenchmarkItem, responses: list[RunResult]
    ) -> list[Metric]:
        raise AssertionError("preview called the scorer")


def test_preview_blocks_unknown_or_model_backed_scorer_without_calling_it(
    tmp_path: Path,
):
    benchmark, client = _text_benchmark(tmp_path, scorer=UnknownScorer())
    preview = preview_benchmark_cost(
        benchmark,
        model="vendor/model",
        pricing=_pricing(),
        token_estimator=lambda *_: 2,
    )
    assert client.calls == 0
    assert preview.blocker_codes == ("scorer-cost-profile-unknown",)
    assert preview.to_dict()["cost"]["nominal_upper_bound_usd"] is None


class PaidPassAtOneSubclass(PassAtOneScorer):
    def score_item(self, item, responses):
        raise AssertionError("preview invoked a model-backed scorer subclass")


def test_preview_does_not_trust_pass_at_one_subclasses(tmp_path: Path) -> None:
    benchmark, _ = _text_benchmark(tmp_path, scorer=PaidPassAtOneSubclass())

    preview = preview_benchmark_cost(
        benchmark,
        model="vendor/model",
        pricing=_pricing(),
        token_estimator=lambda *_: 2,
    )

    assert preview.ready_for_paid_run is False
    assert preview.blocker_codes == ("scorer-cost-profile-unknown",)


class PaidComposedSubclass(_ComposedScorer):
    def score_item(self, item, responses):
        raise AssertionError("preview invoked a model-backed composed subclass")


def test_preview_does_not_trust_composed_scorer_subclasses(tmp_path: Path) -> None:
    benchmark, _ = _text_benchmark(
        tmp_path,
        scorer=PaidComposedSubclass([ExactMatchScorer()]),
    )

    preview = preview_benchmark_cost(
        benchmark,
        model="vendor/model",
        pricing=_pricing(),
        token_estimator=lambda *_: 2,
    )

    assert preview.ready_for_paid_run is False
    assert preview.blocker_codes == ("scorer-cost-profile-unknown",)


class DoubleDispatchSUT(SystemUnderTest):
    name = "double-dispatch"

    def __init__(self) -> None:
        self.calls = 0

    def respond(self, item, **kwargs):
        self.calls += 2
        raise AssertionError("preview invoked a custom SUT")


def test_preview_blocks_unknown_sut_without_assuming_one_provider_call(
    tmp_path: Path,
) -> None:
    sut = DoubleDispatchSUT()
    benchmark, _ = _text_benchmark(tmp_path)
    benchmark._sut_factory = lambda model, **_: sut
    estimator_calls = 0

    def estimator(*_args):
        nonlocal estimator_calls
        estimator_calls += 1
        return 2

    preview = preview_benchmark_cost(
        benchmark,
        model="vendor/model",
        pricing=_pricing(),
        token_estimator=estimator,
    )

    payload = preview.to_dict()
    assert sut.calls == 0
    assert estimator_calls == 0
    assert preview.ready_for_paid_run is False
    assert preview.blocker_codes == ("system-under-test-cost-profile-unknown",)
    assert payload["run"]["modality"] == "unknown"
    assert payload["run"]["nominal_calls"] is None
    assert payload["run"]["maximum_call_exposure"] is None
    assert payload["cost"]["nominal_upper_bound_usd"] is None


def test_multimodal_preview_prepares_bound_image_without_dispatch(
    tmp_path: Path,
):
    image = tmp_path / "case-image.png"
    payload = b"\x89PNG\r\n\x1a\nfixture"
    image.write_bytes(payload)
    relative = "attachments/case-image.png"
    asset = BoundImageAttachment(
        path=relative,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        media_type="image/png",
        file_path=image,
    )
    client = BombTextClient()
    benchmark = Benchmark(
        name="image-preview",
        dataset=Dataset.from_items(
            [
                BenchmarkItem(
                    id="image-case",
                    prompt="PRIVATE IMAGE PROMPT",
                    ground_truth="reference",
                    attachments=[relative],
                )
            ]
        ),
        scorer=ExactMatchScorer(),
        runner_config=RunnerConfig(max_tokens=12, results_dir=tmp_path),
        sut_factory=lambda model, **_: MultimodalImageSUT(
            client,
            assets={relative: asset},
            case_bindings={"image-case": (relative,)},
        ),
    )
    observed_data_urls: list[str] = []

    def estimate(_model, messages, _tools):
        content = messages[-1]["content"]
        observed_data_urls.append(content[-1]["image_url"]["url"])
        return 7

    preview = preview_benchmark_cost(
        benchmark,
        model="vendor/model",
        pricing=_pricing(),
        token_estimator=estimate,
    )
    assert client.calls == 0
    assert observed_data_urls[0].startswith("data:image/png;base64,")
    assert preview.to_dict()["run"]["modality"] == "multimodal-image"
    assert observed_data_urls[0] not in preview.canonical_json()
    assert "PRIVATE IMAGE PROMPT" not in preview.canonical_json()


def test_paid_agentic_preview_exposes_calls_and_blocks_unbounded_turn_cost(
    tmp_path: Path,
):
    tool = Tool(
        name="lookup",
        description="Look up one local fixture value.",
        parameters={
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
        fn=lambda key: {"key": key},
    )
    benchmark = Benchmark(
        name="agent-preview",
        dataset=Dataset.from_items(
            [{"id": "agent-private", "prompt": "PRIVATE AGENT PROMPT", "ground_truth": "done"}]
        ),
        scorer=PassAtOneScorer(),
        runner_config=RunnerConfig(
            max_retries=2,
            max_tokens=20,
            results_dir=tmp_path,
        ),
        tools=[tool],
        max_turns=3,
    )
    observed_tools: list[object] = []

    def estimate(_model, _messages, tools):
        observed_tools.extend(tools or [])
        return 9

    preview = preview_benchmark_cost(
        benchmark,
        model="vendor/model",
        pricing=_pricing(),
        token_estimator=estimate,
    )
    payload = preview.to_dict()
    assert payload["run"]["modality"] == "agentic"
    assert payload["run"]["nominal_calls"] == 1
    assert payload["run"]["maximum_call_exposure"] == 6
    assert observed_tools[0]["function"]["name"] == "lookup"
    assert preview.blocker_codes == (
        "agentic-future-turn-cost-unbounded",
        "agentic-per-turn-reservation-not-configured",
    )
    assert payload["cost"]["first_turn_upper_bound_usd"] == "0.000049000000"
    assert payload["cost"]["nominal_upper_bound_usd"] is None
    assert "PRIVATE AGENT PROMPT" not in preview.canonical_json()


def test_preview_digest_binds_agent_system_prompt_and_planned_messages(
    tmp_path: Path,
) -> None:
    class BombAgent:
        model = "vendor/model"

        def __call__(self, messages, tools):
            raise AssertionError("cost preview dispatched the agent")

    def benchmark(prompt: str) -> Benchmark:
        return Benchmark(
            name="agent-prompt-binding",
            dataset=Dataset.from_items(
                [{"id": "case", "prompt": "Synthetic case", "ground_truth": "done"}],
                system_prompt="dataset fallback",
            ),
            scorer=PassAtOneScorer(),
            runner_config=RunnerConfig(max_tokens=20, results_dir=tmp_path),
            sut_factory=lambda model, **_: SystemUnderTest.from_agent(
                BombAgent(),
                [],
                name=model,
                system_prompt=prompt,
            ),
        )

    first = preview_benchmark_cost(
        benchmark("First agent prompt"),
        model="vendor/model",
        pricing=_pricing(),
        token_estimator=lambda *_: 10,
    )
    second = preview_benchmark_cost(
        benchmark("Second agent prompt"),
        model="vendor/model",
        pricing=_pricing(),
        token_estimator=lambda *_: 10,
    )

    assert first.digest != second.digest
    assert first.to_dict()["benchmark"]["planned_calls_sha256"] != (
        second.to_dict()["benchmark"]["planned_calls_sha256"]
    )
    assert first.to_dict()["benchmark"]["system_prompt_sha256"] == (
        hashlib.sha256(
            json.dumps(
                "First agent prompt",
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )


def test_reference_stub_is_known_zero_without_estimator_or_pricing_lookup(
    tmp_path: Path,
):
    benchmark, client = _text_benchmark(tmp_path, max_tokens=None)

    def bomb(*_args):
        raise AssertionError("stub preview used an estimator or registry")

    preview = preview_benchmark_cost(
        benchmark,
        model=REFERENCE_STUB_MODEL,
        pricing_resolver=bomb,
        token_estimator=bomb,
    )
    payload = preview.to_dict()
    assert client.calls == 0
    assert payload["pricing"]["status"] == "known"
    assert payload["pricing"]["input_usd_per_million_tokens"] == "0.000000000000"
    assert payload["cost"]["retry_upper_bound_usd"] == "0.000000000000"
    assert payload["tokens"]["estimator"]["used"] is False
    assert payload["no_model_calls_made"] is True
    assert preview.blocker_codes == ()


def test_reference_agent_stub_satisfies_explicit_per_call_bound(tmp_path: Path):
    benchmark = Benchmark(
        name="agent-stub-preview",
        dataset=Dataset.from_items(
            [{"id": "case", "prompt": "Use the local tool.", "ground_truth": "done"}]
        ),
        scorer=PassAtOneScorer(),
        runner_config=RunnerConfig(
            max_tokens=20,
            max_cost_per_call=0.01,
            results_dir=tmp_path,
        ),
        tools=[
            Tool(
                name="lookup",
                description="Read a synthetic local value.",
                parameters={"type": "object", "properties": {}},
                fn=lambda: {"value": "synthetic"},
            )
        ],
    )

    preview = preview_benchmark_cost(benchmark, model=REFERENCE_STUB_MODEL)

    assert preview.ready_for_paid_run is True
    assert preview.blocker_codes == ()
    assert preview.to_dict()["budget"]["per_call_status"] == "within"
    assert preview.to_dict()["budget"]["highest_planned_call_usd"] == (
        "0.000000000000"
    )


def test_agentic_preview_caps_exposure_at_enforced_call_limit(tmp_path: Path) -> None:
    benchmark = Benchmark(
        name="agent-call-limit-preview",
        dataset=Dataset.from_items(
            [{"id": "case", "prompt": "Use the tool.", "ground_truth": "done"}]
        ),
        scorer=PassAtOneScorer(),
        runner_config=RunnerConfig(
            max_retries=1,
            max_tokens=20,
            max_calls=1,
            results_dir=tmp_path,
        ),
        tools=[
            Tool(
                name="lookup",
                description="Read a synthetic local value.",
                parameters={"type": "object", "properties": {}},
                fn=lambda: {"value": "synthetic"},
            )
        ],
        max_turns=3,
    )

    preview = preview_benchmark_cost(benchmark, model=REFERENCE_STUB_MODEL)

    assert preview.ready_for_paid_run is True
    assert preview.blocker_codes == ()
    assert preview.to_dict()["run"]["configured_max_calls"] == 1
    assert preview.to_dict()["run"]["maximum_call_exposure"] == 1


class UnknownCostAgent:
    model = "vendor/agent"

    def __call__(self, messages, tools):
        return AgentTurnOutput(text="answer", cost=0.0, cost_known=False)


def test_agent_unknown_cost_is_terminal_and_never_reported_as_known_zero(
    tmp_path: Path,
):
    dataset = Dataset.from_items([{"id": "one", "prompt": "q"}])
    sut = SystemUnderTest.from_agent(UnknownCostAgent(), [], name="vendor-agent")
    results, summary = run_dataset(
        dataset,
        model=sut,
        benchmark_name="unknown-agent-cost",
        config=RunnerConfig(max_retries=3, results_dir=tmp_path),
    )
    assert summary.completed == 0
    assert summary.errored == 1
    assert summary.cost_unknown is True
    assert summary.calls_total == 1
    assert results[0].metadata["cost_unknown"] is True
    assert results[0].metadata["cost_known"] is False
    assert results[0].metadata["attempts"] == 1


def test_litellm_agent_client_marks_unavailable_cost_unknown(monkeypatch):
    import litellm

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="answer", tool_calls=[])
            )
        ],
        usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1, cost=None),
        _hidden_params={},
    )
    monkeypatch.setattr(litellm, "completion", lambda **_: response)
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: None)
    output = LiteLLMAgentClient("vendor/agent")([], [])
    assert output.cost == 0.0
    assert output.cost_known is False
