"""Deterministic, offline cost previews for one benchmark/model route.

A preview prepares the same messages that a benchmark run would dispatch, but
never calls ``respond`` or a model client. The resulting receipt contains only
counts, digests, pricing metadata, and policy decisions; prompts, references,
attachments, and item identifiers are deliberately excluded.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping, Protocol

from arisekit.runtime.agent_clients import _to_provider_messages, _tool_schemas
from arisekit.agentic import PassAtOneScorer, _seed_messages
from arisekit.client import REFERENCE_STUB_MODEL, ModelCall, _build_messages
from arisekit.common.hashing import canonical_sha256 as _sha256_json
from arisekit.common.jsonio import canonical_json as _canonical_json
from arisekit.common.records import CanonicalRecord
from arisekit.common.validate import positive_int as _positive_int
from arisekit.scorer import (
    ChoiceScorer,
    ContainsScorer,
    ExactMatchScorer,
    NumericScorer,
    RegexScorer,
    _ComposedScorer,
)
from arisekit.sut import (
    AgentSUT,
    FHIRAgentSUT,
    ModelSUT,
    MultimodalImageSUT,
    SystemUnderTest,
)


SCHEMA_VERSION = "arisekit.cost-preview.v1"
CLAIM_BOUNDARY = (
    "This receipt is a deterministic planning estimate, not a provider quote "
    "or a reservation. It makes no model or scorer calls. Runtime budget and "
    "known-cost enforcement remain authoritative."
)
_MONEY_QUANTUM = Decimal("0.000000000001")
_SUPPORTED_PREVIEW_SUT_TYPES = (
    ModelSUT,
    MultimodalImageSUT,
    AgentSUT,
    FHIRAgentSUT,
)


class TokenEstimator(Protocol):
    """Local token estimator injected by callers that need pinned behavior."""

    def __call__(
        self,
        model_route: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> int:
        ...


class PricingResolver(Protocol):
    """Resolve a route against a local pricing registry."""

    def __call__(self, model_route: str) -> "PricingSnapshot":
        ...


@dataclass(frozen=True)
class PricingSnapshot:
    """Frozen per-million-token rates used by a preview receipt."""

    model_route: str
    input_usd_per_million_tokens: Decimal | None
    output_usd_per_million_tokens: Decimal | None
    max_output_tokens: int | None
    source: str
    source_version: str
    provider: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model_route, str) or not self.model_route.strip():
            raise ValueError("pricing model_route must be a non-empty string")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("pricing source must be a non-empty string")
        if not isinstance(self.source_version, str) or not self.source_version.strip():
            raise ValueError("pricing source_version must be a non-empty string")
        for field_name in (
            "input_usd_per_million_tokens",
            "output_usd_per_million_tokens",
        ):
            raw = getattr(self, field_name)
            if raw is None:
                continue
            value = _decimal(raw, field_name, allow_zero=True)
            object.__setattr__(self, field_name, value)
        if (self.input_usd_per_million_tokens is None) != (
            self.output_usd_per_million_tokens is None
        ):
            raise ValueError("pricing must provide both input and output rates")
        if self.max_output_tokens is not None and (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens < 1
        ):
            raise ValueError("pricing max_output_tokens must be positive or null")
        if self.provider is not None and (
            not isinstance(self.provider, str) or not self.provider.strip()
        ):
            raise ValueError("pricing provider must be a non-empty string or null")

    @classmethod
    def explicit(
        cls,
        model_route: str,
        *,
        input_usd_per_million_tokens: Decimal | str | int | float,
        output_usd_per_million_tokens: Decimal | str | int | float,
        max_output_tokens: int | None = None,
        provider: str | None = None,
    ) -> "PricingSnapshot":
        """Create the only supported manual override: both token rates."""
        return cls(
            model_route=model_route,
            input_usd_per_million_tokens=_decimal(
                input_usd_per_million_tokens,
                "input_usd_per_million_tokens",
                allow_zero=True,
            ),
            output_usd_per_million_tokens=_decimal(
                output_usd_per_million_tokens,
                "output_usd_per_million_tokens",
                allow_zero=True,
            ),
            max_output_tokens=max_output_tokens,
            source="explicit",
            source_version="arisekit.cost-preview.v1",
            provider=provider,
        )

    @classmethod
    def unavailable(
        cls,
        model_route: str,
        *,
        source: str = "unavailable",
        source_version: str = "unavailable",
        max_output_tokens: int | None = None,
        provider: str | None = None,
    ) -> "PricingSnapshot":
        return cls(
            model_route=model_route,
            input_usd_per_million_tokens=None,
            output_usd_per_million_tokens=None,
            max_output_tokens=max_output_tokens,
            source=source,
            source_version=source_version,
            provider=provider,
        )

    @property
    def known(self) -> bool:
        return self.input_usd_per_million_tokens is not None

    @property
    def cost_free(self) -> bool:
        return self.known and (
            self.input_usd_per_million_tokens == 0
            and self.output_usd_per_million_tokens == 0
        )

    def to_dict(self) -> dict[str, Any]:
        body = {
            "status": "known" if self.known else "unknown",
            "model_route": self.model_route,
            "provider": self.provider,
            "source": self.source,
            "source_version": self.source_version,
            "input_usd_per_million_tokens": _money_or_none(
                self.input_usd_per_million_tokens
            ),
            "output_usd_per_million_tokens": _money_or_none(
                self.output_usd_per_million_tokens
            ),
            "max_output_tokens": self.max_output_tokens,
        }
        body["entry_sha256"] = _sha256_json(body)
        return body


@dataclass(frozen=True)
class CostPreview(CanonicalRecord):
    """Immutable canonical receipt for a cost preview."""

    _canonical_body: str

    @classmethod
    def from_body(cls, body: Mapping[str, Any]) -> "CostPreview":
        detached = json.loads(_canonical_json(dict(body)))
        if detached.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported cost-preview schema {detached.get('schema_version')!r}")
        if "preview_digest" in detached:
            raise ValueError("cost-preview body must not contain preview_digest")
        return cls(_canonical_json(detached))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CostPreview":
        detached = json.loads(_canonical_json(dict(data)))
        digest = detached.pop("preview_digest", None)
        preview = cls.from_body(detached)
        if not isinstance(digest, str) or digest != preview.digest:
            raise ValueError("cost-preview digest does not match its canonical body")
        return preview

    @property
    def digest(self) -> str:
        return hashlib.sha256(self._canonical_body.encode("utf-8")).hexdigest()

    @property
    def ready_for_paid_run(self) -> bool:
        return bool(json.loads(self._canonical_body)["ready_for_paid_run"])

    @property
    def blocker_codes(self) -> tuple[str, ...]:
        return tuple(
            blocker["code"]
            for blocker in json.loads(self._canonical_body)["blockers"]
        )

    def to_dict(self) -> dict[str, Any]:
        body = json.loads(self._canonical_body)
        body["preview_digest"] = self.digest
        return body

    def write(self, path: str | Path) -> Path:
        """Atomically replace ``path`` with this canonical receipt."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise ValueError(f"refusing to replace symlink cost preview: {target}")
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(self.canonical_json())
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return target


def default_token_estimator(
    model_route: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> int:
    """Estimate prompt tokens from local LiteLLM metadata without inference."""
    import litellm  # type: ignore

    kwargs: dict[str, Any] = {"model": model_route, "messages": messages}
    if tools:
        kwargs["tools"] = tools
    value = litellm.token_counter(**kwargs)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("token estimator returned an invalid count")
    return value


def default_pricing_resolver(model_route: str) -> PricingSnapshot:
    """Freeze the installed LiteLLM registry entry for ``model_route``."""
    if model_route == REFERENCE_STUB_MODEL:
        return _reference_stub_pricing()

    import litellm  # type: ignore

    try:
        source_version = importlib.metadata.version("litellm")
    except importlib.metadata.PackageNotFoundError:
        source_version = "unknown"
    info = litellm.get_model_info(model=model_route)
    if not isinstance(info, Mapping):
        return PricingSnapshot.unavailable(
            model_route,
            source="litellm-model-registry",
            source_version=source_version,
        )
    max_output = _optional_positive_int(
        info.get("max_output_tokens") or info.get("max_tokens")
    )
    provider = _optional_string(info.get("litellm_provider"))
    raw_input = info.get("input_cost_per_token")
    raw_output = info.get("output_cost_per_token")
    registry_key = info.get("key")
    registry_info = (
        litellm.model_cost.get(registry_key, {})
        if isinstance(registry_key, str)
        else litellm.model_cost.get(model_route, {})
    )
    if (
        raw_input is None
        or raw_output is None
        or _unsupported_registry_pricing(info, model_route)
        or (
            isinstance(registry_info, Mapping)
            and _unsupported_registry_pricing(registry_info, model_route)
        )
    ):
        return PricingSnapshot.unavailable(
            model_route,
            source="litellm-model-registry",
            source_version=source_version,
            max_output_tokens=max_output,
            provider=provider,
        )
    try:
        input_per_token = _decimal(raw_input, "input_cost_per_token", allow_zero=True)
        output_per_token = _decimal(raw_output, "output_cost_per_token", allow_zero=True)
    except ValueError:
        return PricingSnapshot.unavailable(
            model_route,
            source="litellm-model-registry",
            source_version=source_version,
            max_output_tokens=max_output,
            provider=provider,
        )
    million = Decimal(1_000_000)
    return PricingSnapshot(
        model_route=model_route,
        input_usd_per_million_tokens=input_per_token * million,
        output_usd_per_million_tokens=output_per_token * million,
        max_output_tokens=max_output,
        source="litellm-model-registry",
        source_version=source_version,
        provider=provider,
    )


def preview_benchmark_cost(
    benchmark: Any,
    *,
    model: str,
    trials: int | None = None,
    limit: int | None = None,
    max_tokens: int | None = None,
    pricing: PricingSnapshot | None = None,
    token_estimator: TokenEstimator | None = None,
    pricing_resolver: PricingResolver | None = None,
) -> CostPreview:
    """Build a no-call cost receipt for one benchmark and model route."""
    if not isinstance(model, str) or not model.strip():
        raise ValueError("cost preview requires a non-empty string model route")
    allowed_routes = getattr(benchmark, "allowed_model_routes", None)
    if allowed_routes is not None and model not in allowed_routes:
        allowed = ", ".join(allowed_routes)
        raise ValueError(
            f"model route {model!r} is not in this benchmark's reviewed "
            f"allowlist: {allowed}"
        )

    cfg = benchmark.runner_config
    effective_trials = cfg.trials if trials is None else trials
    _positive_int(effective_trials, "trials")
    _positive_int(cfg.max_retries, "max_retries")
    if limit is not None:
        _positive_int(limit, "limit")
    if cfg.max_calls is not None:
        _positive_int(cfg.max_calls, "max_calls")
    effective_max_tokens = cfg.max_tokens if max_tokens is None else max_tokens
    if effective_max_tokens is not None:
        _positive_int(effective_max_tokens, "max_tokens")

    runtime_dataset = benchmark.dataset
    runtime_scorer = benchmark.scorer
    if getattr(benchmark, "provider_disclosure_requirement", None) is not None:
        runtime_dataset, runtime_scorer = benchmark._validated_gated_runtime()
    selected = runtime_dataset.limit(limit) if limit is not None else runtime_dataset
    items = list(selected)

    blockers: list[dict[str, str]] = []
    if not items:
        _block(blockers, "empty-selection", "The selected benchmark has no items.")

    scorer_profile = _scorer_profile(runtime_scorer)
    if scorer_profile != "deterministic-local":
        _block(
            blockers,
            "scorer-cost-profile-unknown",
            "Cost preview supports only deterministic local scorers.",
        )

    if model == REFERENCE_STUB_MODEL:
        snapshot = _reference_stub_pricing()
    elif pricing is not None:
        if pricing.model_route != model:
            raise ValueError(
                "explicit pricing model_route must match the preview model route"
            )
        if not pricing.known:
            raise ValueError("explicit pricing must provide both input and output rates")
        snapshot = pricing
    else:
        resolver = pricing_resolver or default_pricing_resolver
        try:
            snapshot = resolver(model)
        except Exception:  # noqa: BLE001
            snapshot = PricingSnapshot.unavailable(model)
        if not isinstance(snapshot, PricingSnapshot):
            raise TypeError("pricing_resolver must return PricingSnapshot")
        if snapshot.model_route != model:
            raise ValueError(
                "pricing_resolver returned a snapshot for a different model route"
            )
    if not snapshot.known:
        _block(
            blockers,
            "pricing-unavailable",
            "Both input and output token prices are required.",
        )

    sut: SystemUnderTest | None
    try:
        sut = _resolve_preview_sut(benchmark, model, effective_max_tokens)
    except Exception:  # noqa: BLE001
        sut = None
        _block(
            blockers,
            "system-under-test-preview-unavailable",
            "The benchmark system-under-test binding could not be prepared locally.",
        )

    sut_profile_known = sut is not None and type(sut) in _SUPPORTED_PREVIEW_SUT_TYPES
    if sut is not None and not sut_profile_known:
        _block(
            blockers,
            "system-under-test-cost-profile-unknown",
            "Cost preview supports only the built-in text, image, Agent, and "
            "Agentic/FHIR system-under-test bindings.",
        )

    modality = _modality(sut)
    agentic = type(sut) in (AgentSUT, FHIRAgentSUT)
    max_turns = sut.max_iters if agentic else None
    nominal_calls = len(items) * effective_trials if sut_profile_known else None
    unbounded_calls = (
        nominal_calls * cfg.max_retries if nominal_calls is not None else None
    )
    if agentic and max_turns is not None and unbounded_calls is not None:
        unbounded_calls *= max_turns
    maximum_calls = (
        None
        if unbounded_calls is None
        else (
            unbounded_calls
            if cfg.max_calls is None
            else min(unbounded_calls, cfg.max_calls)
        )
    )
    if (
        cfg.max_calls is not None
        and nominal_calls is not None
        and cfg.max_calls < nominal_calls
    ):
        _block(
            blockers,
            "call-budget-below-nominal",
            "The configured call limit cannot cover one call per selected trial.",
        )

    output_limit = effective_max_tokens or snapshot.max_output_tokens
    if output_limit is None and model != REFERENCE_STUB_MODEL:
        _block(
            blockers,
            "max-output-tokens-unavailable",
            "A configured or registry max-output token limit is required.",
        )

    estimator = token_estimator or default_token_estimator
    estimator_identity = (
        {
            "name": "litellm.token_counter",
            "version": _package_version("litellm"),
            "used": model != REFERENCE_STUB_MODEL,
        }
        if token_estimator is None
        else {
            "name": "caller-supplied",
            "version": "caller-supplied",
            "used": model != REFERENCE_STUB_MODEL,
        }
    )
    per_cell_inputs: list[int] | None = []
    planned_call_bindings: list[dict[str, str]] | None = []
    estimation_failed = False
    if not sut_profile_known:
        per_cell_inputs = None
        planned_call_bindings = None
    else:
        for item in items:
            try:
                messages, tool_schemas = _preview_call(
                    sut, item, runtime_dataset.system_prompt
                )
            except Exception:  # noqa: BLE001
                per_cell_inputs = None
                planned_call_bindings = None
                _block(
                    blockers,
                    "call-input-preparation-unavailable",
                    "Planned call inputs could not be prepared and verified locally.",
                )
                break
            planned_call_bindings.append(
                {
                    "messages_sha256": _sha256_json(messages),
                    "tool_schemas_sha256": _sha256_json(tool_schemas or []),
                }
            )
            if model == REFERENCE_STUB_MODEL or estimation_failed:
                continue
            try:
                estimated = estimator(model, messages, tool_schemas)
                if (
                    isinstance(estimated, bool)
                    or not isinstance(estimated, int)
                    or estimated < 0
                ):
                    raise ValueError("token estimator returned an invalid count")
                per_cell_inputs.extend([estimated] * effective_trials)
            except Exception:  # noqa: BLE001
                estimation_failed = True
                per_cell_inputs = None
                _block(
                    blockers,
                    "token-estimate-unavailable",
                    "Input tokens could not be estimated locally for every selected item.",
                )
        if planned_call_bindings is not None and model == REFERENCE_STUB_MODEL:
            assert nominal_calls is not None
            per_cell_inputs = [0 for _ in range(nominal_calls)]

    nominal_input_tokens = (
        sum(per_cell_inputs) if per_cell_inputs is not None else None
    )
    nominal_output_tokens = (
        nominal_calls * output_limit
        if nominal_calls is not None and output_limit is not None
        else None
    )
    retry_input_tokens: int | None = None
    retry_output_tokens: int | None = None
    if per_cell_inputs is not None and output_limit is not None and not agentic:
        expanded_inputs = sorted(
            per_cell_inputs * cfg.max_retries,
            reverse=True,
        )[:maximum_calls]
        retry_input_tokens = sum(expanded_inputs)
        retry_output_tokens = len(expanded_inputs) * output_limit

    if agentic and not snapshot.cost_free:
        _block(
            blockers,
            "agentic-future-turn-cost-unbounded",
            "Only first-turn input can be estimated before agent tool results exist.",
        )
        if cfg.max_cost_per_call is None:
            _block(
                blockers,
                "agentic-per-turn-reservation-not-configured",
                "Set max_cost_per_call to reserve a reviewed bound before each agent turn.",
            )

    full_cost_known = (
        snapshot.known
        and output_limit is not None
        and per_cell_inputs is not None
        and scorer_profile == "deterministic-local"
        and (not agentic or snapshot.cost_free)
    )
    nominal_cost = None
    retry_cost = None
    first_turn_cost = None
    if snapshot.known and output_limit is not None and per_cell_inputs is not None:
        first_turn_cost = _token_cost(
            nominal_input_tokens or 0,
            nominal_output_tokens or 0,
            snapshot,
        )
    if full_cost_known:
        nominal_cost = first_turn_cost
        if agentic:
            retry_cost = Decimal(0)
        elif retry_input_tokens is not None and retry_output_tokens is not None:
            retry_cost = _token_cost(
                retry_input_tokens,
                retry_output_tokens,
                snapshot,
            )

    max_cost = _optional_positive_decimal(cfg.max_cost, "max_cost")
    max_cost_per_call = _optional_positive_decimal(
        cfg.max_cost_per_call, "max_cost_per_call"
    )
    budget_status = "not-configured"
    if max_cost is not None:
        if retry_cost is None:
            budget_status = "unknown"
        elif retry_cost <= max_cost:
            budget_status = "within"
        else:
            budget_status = "exceeds"
            _block(
                blockers,
                "configured-budget-exceeded",
                "The retry upper-bound estimate exceeds the configured run budget.",
            )

    per_call_status = "not-configured"
    highest_call_cost = None
    if max_cost_per_call is not None:
        if snapshot.cost_free and per_cell_inputs is not None:
            highest_call_cost = Decimal(0)
            per_call_status = "within"
        elif (
            snapshot.known
            and output_limit is not None
            and per_cell_inputs is not None
            and not agentic
        ):
            highest_call_cost = _token_cost(
                max(per_cell_inputs, default=0), output_limit, snapshot
            )
            if highest_call_cost <= max_cost_per_call:
                per_call_status = "within"
            else:
                per_call_status = "exceeds"
                _block(
                    blockers,
                    "configured-per-call-budget-exceeded",
                    "A planned call exceeds the configured per-call cost bound.",
                )
        else:
            per_call_status = "unknown"

    benchmark_payload = [item.to_dict() for item in runtime_dataset]
    selected_payload = [item.to_dict() for item in items]
    sut_prompt = getattr(sut, "system_prompt", None) if sut is not None else None
    effective_system_prompt = sut_prompt or runtime_dataset.system_prompt
    scorer_name = f"{type(runtime_scorer).__module__}.{type(runtime_scorer).__qualname__}"
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "benchmark": {
            "name": benchmark.name,
            "content_sha256": _sha256_json(benchmark_payload),
            "selection_sha256": _sha256_json(selected_payload),
            "system_prompt_sha256": _sha256_json(effective_system_prompt or ""),
            "planned_calls_sha256": (
                _sha256_json(planned_call_bindings)
                if planned_call_bindings is not None
                else None
            ),
            "package_asset_manifest_sha256": getattr(
                benchmark, "_package_asset_manifest_sha256", None
            ),
        },
        "run": {
            "model_route": model,
            "modality": modality,
            "item_count": len(items),
            "trials": effective_trials,
            "max_attempts_per_item": cfg.max_retries,
            "agent_max_turns": max_turns,
            "configured_max_calls": cfg.max_calls,
            "nominal_calls": nominal_calls,
            "maximum_call_exposure": maximum_calls,
            "provider_authorization_required": (
                getattr(benchmark, "provider_disclosure_requirement", None)
                is not None
            ),
        },
        "scorer": {
            "qualified_name": scorer_name,
            "cost_profile": scorer_profile,
        },
        "pricing": snapshot.to_dict(),
        "tokens": {
            "estimator": estimator_identity,
            "scope": "first-turn" if agentic else "complete-call",
            "nominal_input": nominal_input_tokens,
            "nominal_output_upper_bound": nominal_output_tokens,
            "retry_input_upper_bound": retry_input_tokens,
            "retry_output_upper_bound": retry_output_tokens,
        },
        "cost": {
            "currency": "USD",
            "first_turn_upper_bound_usd": _money_or_none(first_turn_cost),
            "nominal_upper_bound_usd": _money_or_none(nominal_cost),
            "retry_upper_bound_usd": _money_or_none(retry_cost),
        },
        "budget": {
            "status": budget_status,
            "configured_max_cost_usd": _money_or_none(max_cost),
            "per_call_status": per_call_status,
            "configured_max_cost_per_call_usd": _money_or_none(max_cost_per_call),
            "highest_planned_call_usd": _money_or_none(highest_call_cost),
        },
        "ready_for_paid_run": not blockers,
        "no_model_calls_made": True,
        "blockers": blockers,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    return CostPreview.from_body(body)


def _resolve_preview_sut(
    benchmark: Any,
    model: str,
    max_tokens: int | None,
) -> SystemUnderTest:
    factory = getattr(benchmark, "_sut_factory", None)
    if factory is not None:
        return factory(
            model,
            temperature=benchmark.runner_config.temperature,
            max_tokens=max_tokens,
        )
    tools = getattr(benchmark, "tools", None)
    if tools is not None:
        return SystemUnderTest.from_agent(
            model,
            tools,
            max_iters=benchmark.max_turns,
            temperature=benchmark.runner_config.temperature,
            max_tokens=max_tokens,
        )
    return SystemUnderTest.resolve(model)


def _preview_call(
    sut: SystemUnderTest,
    item: Any,
    dataset_system_prompt: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    if type(sut) is MultimodalImageSUT:
        runtime_item = sut.prepare_item(item)
        messages = _build_messages(
            ModelCall(item=runtime_item, system_prompt=dataset_system_prompt)
        )
        return messages, None
    if type(sut) in (AgentSUT, FHIRAgentSUT):
        system_prompt = sut.system_prompt or dataset_system_prompt
        messages = _to_provider_messages(_seed_messages(item, system_prompt))
        return messages, _tool_schemas(sut.tools)
    if type(sut) is ModelSUT:
        messages = _build_messages(
            ModelCall(item=item, system_prompt=dataset_system_prompt)
        )
        return messages, None
    raise TypeError("unsupported system-under-test cost profile")


def _modality(sut: SystemUnderTest | None) -> str:
    if type(sut) is FHIRAgentSUT:
        return "agentic-fhir"
    if type(sut) is AgentSUT:
        return "agentic"
    if type(sut) is MultimodalImageSUT:
        return "multimodal-image"
    if type(sut) is ModelSUT:
        return "text"
    return "unknown"


def _scorer_profile(scorer: Any) -> str:
    deterministic = (
        ExactMatchScorer,
        ContainsScorer,
        RegexScorer,
        ChoiceScorer,
        NumericScorer,
    )
    if type(scorer) in deterministic:
        return "deterministic-local"
    if type(scorer) is PassAtOneScorer and scorer._check is None:
        return "deterministic-local"
    if type(scorer) is _ComposedScorer and all(
        _scorer_profile(child) == "deterministic-local"
        for child in scorer._scorers
    ):
        return "deterministic-local"
    return "unknown-or-model-backed"


def _reference_stub_pricing() -> PricingSnapshot:
    return PricingSnapshot(
        model_route=REFERENCE_STUB_MODEL,
        input_usd_per_million_tokens=Decimal(0),
        output_usd_per_million_tokens=Decimal(0),
        max_output_tokens=1,
        source="arisekit-reference-stub",
        source_version=SCHEMA_VERSION,
        provider="local",
    )


def _token_cost(
    input_tokens: int,
    output_tokens: int,
    pricing: PricingSnapshot,
) -> Decimal:
    if not pricing.known:
        raise ValueError("token cost requires known pricing")
    million = Decimal(1_000_000)
    return (
        Decimal(input_tokens) * pricing.input_usd_per_million_tokens
        + Decimal(output_tokens) * pricing.output_usd_per_million_tokens
    ) / million


def _block(blockers: list[dict[str, str]], code: str, message: str) -> None:
    if any(blocker["code"] == code for blocker in blockers):
        return
    blockers.append({"code": code, "message": message})


def _decimal(value: Any, label: str, *, allow_zero: bool) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite non-negative decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a finite non-negative decimal") from exc
    if not result.is_finite() or result < 0 or (not allow_zero and result == 0):
        raise ValueError(f"{label} must be a finite non-negative decimal")
    return result


def _optional_positive_decimal(value: Any, label: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, label, allow_zero=False)


def _optional_positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _unsupported_registry_pricing(
    info: Mapping[str, Any], model_route: str
) -> bool:
    """Reject registry entries whose full bill is not two token rates."""
    mode = info.get("mode")
    if mode not in (None, "chat"):
        return True
    if info.get("tiered_pricing"):
        return True
    for key in ("input_cost_per_request", "output_cost_per_request"):
        value = info.get(key)
        if value not in (None, 0, 0.0, "0"):
            return True
    for key, value in info.items():
        if value is None:
            continue
        if "cost" in key and "_above_" in key:
            return True
        if key.startswith("regional_") and key.endswith("_multiplier"):
            try:
                if Decimal(str(value)) != 1:
                    return True
            except InvalidOperation:
                return True
    route_parts = {
        part
        for part in model_route.lower().replace(":", "/").replace("-", "/").split("/")
        if part
    }
    tier_fields = {
        "batch": ("input_cost_per_token_batches", "output_cost_per_token_batches"),
        "batches": ("input_cost_per_token_batches", "output_cost_per_token_batches"),
        "priority": ("input_cost_per_token_priority", "output_cost_per_token_priority"),
        "flex": ("input_cost_per_token_flex", "output_cost_per_token_flex"),
    }
    return any(
        tier in route_parts and any(info.get(field) is not None for field in fields)
        for tier, fields in tier_fields.items()
    )


def _package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _money_or_none(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP), "f")


__all__ = [
    "SCHEMA_VERSION",
    "CLAIM_BOUNDARY",
    "CostPreview",
    "PricingSnapshot",
    "TokenEstimator",
    "PricingResolver",
    "default_token_estimator",
    "default_pricing_resolver",
    "preview_benchmark_cost",
]
