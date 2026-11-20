"""System Under Test: one uniform interface the runner drives.

A SystemUnderTest turns "the thing being evaluated" into a single
`respond(item)` call, whether that thing is a bare text model, a
tool-using agent over an environment, or an external endpoint. The runner
stays ignorant of which: it gets back a normalized `SUTResponse` (a text
or Trajectory response plus usage) and keeps its resume, retry,
parallelism, and cost tracking unchanged.

This is the Phase 4 seam that lets ARISEKit evaluate not just a bare
model but an actual agentic product (system prompt + tools + model), which
is exactly what the arisekitai workshop exports as a Skill bundle.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable

from arisekit.agentic import (
    AgentClient,
    AgenticPassCondition,
    run_agent,
    trajectory_passes_condition,
)
from arisekit.client import REFERENCE_STUB_MODEL, ModelCall, ModelClient, resolve_client
from arisekit.common.jsonio import json_copy as _json_detach
from arisekit.types import BenchmarkItem, Tool, Trajectory


@dataclass
class SUTResponse:
    """Normalized output of one SUT turn: the response plus usage.

    `response` is a plain string for text models and a `Trajectory` for
    agentic ones; the runner persists it verbatim and the scorers pick the
    shape they need.
    """

    response: Any
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    cost_known: bool = True
    finish_reason: str | None = None
    provider_model: str | None = None
    response_id: str | None = None


@dataclass
class SUTCheckpoint:
    """Cumulative progress for one item/trial SUT response."""

    response: Any
    sequence: int
    complete: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    provider_calls: int = 0


SUTCheckpointCallback = Callable[[SUTCheckpoint], None]


class SystemUnderTest:
    """Base class: a named producer of one response per item."""

    name: str = "sut"
    supports_turn_checkpoints: bool = False

    def respond(
        self,
        item: BenchmarkItem,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> SUTResponse:
        raise NotImplementedError

    def respond_checkpointed(
        self,
        item: BenchmarkItem,
        *,
        trial: int,
        resume_from: SUTCheckpoint | None = None,
        on_checkpoint: SUTCheckpointCallback | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> SUTResponse:
        """Run with optional incremental checkpoints.

        The default keeps existing custom SUT subclasses source-compatible:
        they only need to implement ``respond``. Stateful SUTs override this
        method and set ``supports_turn_checkpoints``.
        """
        return self.respond(
            item,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # --- factories ---------------------------------------------------

    @staticmethod
    def resolve(spec: "str | ModelClient | SystemUnderTest") -> "SystemUnderTest":
        """Accept a SUT, a model id, or a bare ModelClient callable."""
        if isinstance(spec, SystemUnderTest):
            return spec
        name = spec if isinstance(spec, str) else getattr(spec, "model", "custom-client")
        return ModelSUT(resolve_client(spec), name=name)

    @staticmethod
    def from_model(model: "str | ModelClient") -> "ModelSUT":
        """Wrap a text model (id string or ModelClient) as a SUT."""
        name = model if isinstance(model, str) else getattr(model, "model", "custom-client")
        return ModelSUT(resolve_client(model), name=name)

    @staticmethod
    def from_agent(
        model: "str | AgentClient",
        tools: list[Tool],
        *,
        system_prompt: str | None = None,
        max_iters: int = 8,
        name: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> "AgentSUT":
        """Wrap a tool-using agent (a model id or an AgentClient) as a SUT.

        A string builds a litellm-backed agent client; any other callable is
        assumed to already satisfy the AgentClient protocol (handy for tests
        and custom gateways). `system_prompt` is the agent's instructions.
        """
        if isinstance(model, str):
            from arisekit.runtime.agent_clients import LiteLLMAgentClient

            agent_client: AgentClient = LiteLLMAgentClient(
                model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            resolved_name = name or model
        else:
            agent_client = model
            resolved_name = name or getattr(model, "model", "agent")
        return AgentSUT(
            agent_client,
            tools,
            system_prompt=system_prompt,
            max_iters=max_iters,
            name=resolved_name,
        )

    @staticmethod
    def from_endpoint(
        url: str,
        model: str,
        *,
        api_key_env: str | None = None,
        name: str | None = None,
    ) -> "ModelSUT":
        """Wrap an external OpenAI-compatible endpoint as a text SUT."""
        from arisekit.client import LiteLLMClient

        api_key = os.environ.get(api_key_env) if api_key_env else None
        client = LiteLLMClient(model, api_base=url, api_key=api_key)
        return ModelSUT(client, name=name or model)


class ModelSUT(SystemUnderTest):
    """A text model under test: one call, text back."""

    def __init__(self, client: ModelClient, *, name: str = "model"):
        self.client = client
        self.name = name

    def respond(
        self,
        item: BenchmarkItem,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> SUTResponse:
        call = ModelCall(
            item=item,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        resp = self.client(call)
        return SUTResponse(
            response=resp.text,
            tokens_in=resp.tokens_in,
            tokens_out=resp.tokens_out,
            cost=resp.cost,
            cost_known=resp.cost_known,
            finish_reason=resp.finish_reason,
            provider_model=resp.provider_model,
            response_id=resp.response_id,
        )


class MultimodalImageSUT(ModelSUT):
    """A model SUT with strict package-relative image bindings.

    Dataset records retain portable ``attachments/<filename>`` references.
    This wrapper verifies the bound bytes at dispatch and gives the model
    client absolute local paths without mutating the packaged item.
    """

    def __init__(
        self,
        model: str | ModelClient,
        *,
        assets: Mapping[str, Any],
        case_bindings: Mapping[str, Sequence[str]],
    ):
        name = (
            model
            if isinstance(model, str)
            else getattr(model, "model", "custom-client")
        )
        super().__init__(resolve_client(model), name=name)
        self.assets = dict(assets)
        self.case_bindings = {
            item_id: tuple(paths) for item_id, paths in case_bindings.items()
        }

    def prepare_item(self, item: BenchmarkItem) -> BenchmarkItem:
        """Verify package-bound images and return a detached runtime item."""
        references = self.case_bindings.get(item.id)
        if references is None:
            raise ValueError(f"no image attachments are bound to item {item.id!r}")
        if tuple(item.attachments) != references:
            raise ValueError(
                f"item {item.id!r} attachments differ from its package binding"
            )

        resolved: list[str] = []
        from arisekit.client import _encode_image

        for reference in references:
            asset = self.assets.get(reference)
            if asset is None:
                raise ValueError(
                    f"item {item.id!r} names missing bound image {reference!r}"
                )
            path = asset.file_path
            if path.is_symlink() or not path.is_file():
                raise ValueError(
                    f"bound image attachment is missing or unsafe: {reference}"
                )
            payload = path.read_bytes()
            if len(payload) != asset.size_bytes:
                raise ValueError(
                    f"bound image attachment size changed: {reference}"
                )
            digest = hashlib.sha256(payload).hexdigest()
            if not hmac.compare_digest(digest, asset.sha256):
                raise ValueError(
                    f"bound image attachment hash changed: {reference}"
                )
            encoded = _encode_image(str(path))
            if encoded is None or not encoded.startswith(
                f"data:{asset.media_type};base64,"
            ):
                raise ValueError(
                    "bound image attachment could not be encoded as "
                    f"{asset.media_type}: {reference}"
                )
            resolved.append(str(path))

        return BenchmarkItem(
            id=item.id,
            prompt=item.prompt,
            metadata=item.metadata,
            ground_truth=item.ground_truth,
            attachments=resolved,
        )

    def respond(
        self,
        item: BenchmarkItem,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> SUTResponse:
        return super().respond(
            self.prepare_item(item),
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )


class AgentSUT(SystemUnderTest):
    """A tool-using agent under test: run_agent, a Trajectory back."""

    supports_turn_checkpoints = True
    supports_dispatch_accounting = True

    def __init__(
        self,
        agent_client: AgentClient,
        tools: list[Tool],
        *,
        system_prompt: str | None = None,
        max_iters: int = 8,
        name: str = "agent",
    ):
        self.agent_client = agent_client
        self.tools = list(tools)
        self.system_prompt = system_prompt
        self.max_iters = max_iters
        self.name = name

    def respond(
        self,
        item: BenchmarkItem,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> SUTResponse:
        return self.respond_checkpointed(
            item,
            trial=1,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def respond_checkpointed(
        self,
        item: BenchmarkItem,
        *,
        trial: int,
        resume_from: SUTCheckpoint | None = None,
        on_checkpoint: SUTCheckpointCallback | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> SUTResponse:
        # The agent's own instructions win; fall back to the dataset prompt.
        # Inference settings are bound to string-backed agent clients at
        # construction because AgentClient receives messages and tools only.
        del trial, temperature, max_tokens
        sp = self.system_prompt or system_prompt
        initial: Trajectory | None = None
        if resume_from is not None:
            initial = _checkpoint_trajectory(resume_from)
            if resume_from.complete:
                return _trajectory_response(initial)

        def checkpoint(trajectory: Trajectory, complete: bool) -> None:
            if on_checkpoint is None:
                return
            on_checkpoint(
                SUTCheckpoint(
                    response=trajectory,
                    sequence=sum(
                        turn.role == "assistant" for turn in trajectory.turns
                    ),
                    complete=complete,
                    tokens_in=trajectory.total_tokens_in,
                    tokens_out=trajectory.total_tokens_out,
                    cost=trajectory.total_cost,
                    provider_calls=sum(
                        turn.role == "assistant" for turn in trajectory.turns
                    ),
                )
            )

        traj = run_agent(
            self.agent_client,
            item,
            self.tools,
            system_prompt=sp,
            max_iters=self.max_iters,
            initial_trajectory=initial,
            on_checkpoint=checkpoint,
        )
        return _trajectory_response(traj)


class FHIRAgentSUT(SystemUnderTest):
    """A package-bound agent with one fresh FHIR environment per item/trial."""

    supports_turn_checkpoints = True
    supports_dispatch_accounting = True

    def __init__(
        self,
        model: str | AgentClient,
        bundles: Mapping[str, dict[str, Any]],
        *,
        allowed_tools: Sequence[str],
        system_prompt: str | None = None,
        max_iters: int = 8,
        name: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        if not bundles:
            raise ValueError("FHIR agent bundles must not be empty")
        if isinstance(max_iters, bool) or not isinstance(max_iters, int) or max_iters < 1:
            raise ValueError("max_iters must be a positive integer")
        names = tuple(allowed_tools)
        if not names or len(names) != len(set(names)):
            raise ValueError("allowed_tools must be non-empty and unique")

        from arisekit.runtime.agent_clients import (
            LiteLLMAgentClient,
            ReferenceStubAgentClient,
        )

        if isinstance(model, str):
            if model == REFERENCE_STUB_MODEL:
                client: AgentClient = ReferenceStubAgentClient()
            else:
                client = LiteLLMAgentClient(
                    model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            resolved_name = name or model
            self.model_route = model
        else:
            client = model
            resolved_name = name or getattr(model, "model", "fhir-agent")
            self.model_route = getattr(model, "model", resolved_name)

        self.agent_client = client
        self.bundles = {
            item_id: _json_detach(bundle) for item_id, bundle in bundles.items()
        }
        self.allowed_tools = names
        self.system_prompt = system_prompt
        self.max_iters = max_iters
        self.name = resolved_name
        self.tools = _selected_fhir_tools(names)

    def respond(
        self,
        item: BenchmarkItem,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> SUTResponse:
        return self.respond_checkpointed(
            item,
            trial=1,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def respond_checkpointed(
        self,
        item: BenchmarkItem,
        *,
        trial: int,
        resume_from: SUTCheckpoint | None = None,
        on_checkpoint: SUTCheckpointCallback | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> SUTResponse:
        del trial, temperature, max_tokens
        bundle = self.bundles.get(item.id)
        if bundle is None:
            raise ValueError(f"no FHIR bundle is bound to item {item.id!r}")
        condition = AgenticPassCondition.from_dict(item.ground_truth)
        initial: Trajectory | None = None
        if resume_from is not None:
            initial = _checkpoint_trajectory(resume_from)
            if resume_from.complete:
                self._validate_reference_trajectory(initial, condition)
                return _trajectory_response(initial)

        from arisekit.runtime.agent_clients import ReferenceStubAgentClient
        from arisekit.env.fhir import FHIREnvironment, fhir_tools

        environment = FHIREnvironment([_json_detach(bundle)])
        if initial is not None:
            environment.restore_overlay(_recorded_fhir_writes(initial))
        catalog = {tool.name: tool for tool in fhir_tools(environment)}
        tools = [catalog[name] for name in self.allowed_tools]

        def checkpoint(trajectory: Trajectory, complete: bool) -> None:
            if on_checkpoint is None:
                return
            on_checkpoint(
                SUTCheckpoint(
                    response=trajectory,
                    sequence=sum(
                        turn.role == "assistant" for turn in trajectory.turns
                    ),
                    complete=complete,
                    tokens_in=trajectory.total_tokens_in,
                    tokens_out=trajectory.total_tokens_out,
                    cost=trajectory.total_cost,
                    provider_calls=sum(
                        turn.role == "assistant" for turn in trajectory.turns
                    ),
                )
            )

        client = self.agent_client
        if isinstance(client, ReferenceStubAgentClient):
            client = client.for_condition(condition)
        trajectory = run_agent(
            client,
            item,
            tools,
            system_prompt=self.system_prompt or system_prompt,
            max_iters=self.max_iters,
            initial_trajectory=initial,
            on_checkpoint=checkpoint,
        )
        self._validate_reference_trajectory(trajectory, condition)
        return _trajectory_response(trajectory)

    def _validate_reference_trajectory(
        self,
        trajectory: Trajectory,
        condition: AgenticPassCondition,
    ) -> None:
        from arisekit.runtime.agent_clients import ReferenceStubAgentClient

        if isinstance(self.agent_client, ReferenceStubAgentClient) and not (
            trajectory_passes_condition(trajectory, condition)
        ):
            raise ValueError(
                "stub/reference could not satisfy the package pass condition"
            )


def _checkpoint_trajectory(checkpoint: SUTCheckpoint) -> Trajectory:
    value = checkpoint.response
    if isinstance(value, Trajectory):
        return Trajectory.from_dict(value.to_dict())
    if isinstance(value, dict) and value.get("kind") == "trajectory":
        return Trajectory.from_dict(value)
    raise TypeError("agent checkpoint response must be a Trajectory")


def _trajectory_response(trajectory: Trajectory) -> SUTResponse:
    return SUTResponse(
        response=trajectory,
        tokens_in=trajectory.total_tokens_in,
        tokens_out=trajectory.total_tokens_out,
        cost=trajectory.total_cost,
        finish_reason="stop",
    )


def _selected_fhir_tools(names: Sequence[str]) -> list[Tool]:
    from arisekit.env.fhir import FHIREnvironment, fhir_tools

    catalog = {tool.name: tool for tool in fhir_tools(FHIREnvironment([]))}
    unknown = sorted(set(names) - set(catalog))
    if unknown:
        raise ValueError("unknown FHIR tool(s): " + ", ".join(unknown))
    return [catalog[name] for name in names]


def _recorded_fhir_writes(trajectory: Trajectory) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    for turn in trajectory.turns:
        if turn.role != "tool_result" or not isinstance(turn.content, dict):
            continue
        if turn.content.get("name") != "create_task":
            continue
        result = turn.content.get("result")
        if (
            isinstance(result, dict)
            and result.get("resourceType")
            and result.get("id")
            and "error" not in result
        ):
            resources.append(_json_detach(result))
    return resources


__all__ = [
    "SUTResponse",
    "SUTCheckpoint",
    "SUTCheckpointCallback",
    "SystemUnderTest",
    "ModelSUT",
    "MultimodalImageSUT",
    "AgentSUT",
    "FHIRAgentSUT",
]
