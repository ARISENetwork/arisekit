"""Agentic run path: a client-agnostic tool-use executor loop.

This is the executor half of the arisekitai planner-executor loop
(lib/agent/runLoop.ts), translated to a synchronous, framework-native
form. `run_agent` drives a tool-using model against a set of
`arisekit.types.Tool` objects and records the whole interaction as a
`Trajectory` the agentic scorers can grade.

The loop deliberately talks to an `AgentClient` protocol rather than the
text-only `arisekit.client.ModelClient`: a tool-using turn returns both
optional text and a list of structured tool calls, which the flat text
client cannot express. Any object (or plain callable) matching the
protocol works, so tests inject a scripted fake and stay fully offline.

Note: a litellm-backed AgentClient adapter (translating litellm's
tool-call blocks into `AgentTurnOutput` and back) is a Phase 4 follow-up.
`run_agent` is written client-agnostic on purpose so that adapter is the
only new surface needed to run real models through this path.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from arisekit.common.jsonio import strict_canonical_json as _canonical_json_text
from arisekit.scorer import BaseScorer
from arisekit.types import BenchmarkItem, Metric, RunResult, Tool, Trajectory, Turn


AGENTIC_PASS_CONDITION_SCHEMA_VERSION = "arisekit.agentic-pass-condition.v1"


@dataclass(frozen=True)
class RequiredToolCall:
    """One exact tool invocation required by an agentic pass condition."""

    name: str
    arguments: dict[str, Any]

    @classmethod
    def from_dict(cls, data: Any, *, index: int) -> "RequiredToolCall":
        label = f"required_tool_calls[{index}]"
        if not isinstance(data, dict) or set(data) != {"name", "arguments"}:
            raise ValueError(f"{label} must contain exactly name and arguments")
        name = data["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{label}.name must be a non-empty string")
        arguments = data["arguments"]
        if not isinstance(arguments, dict):
            raise ValueError(f"{label}.arguments must be an object")
        return cls(name=name, arguments=_canonical_json_object(arguments, label))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "arguments": dict(self.arguments)}


@dataclass(frozen=True)
class AgenticPassCondition:
    """Portable AND-composed success condition for one agent trajectory."""

    required_tool_calls: tuple[RequiredToolCall, ...]
    final_response_contains: tuple[str, ...]
    schema_version: str = AGENTIC_PASS_CONDITION_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, data: Any) -> "AgenticPassCondition":
        expected = {
            "schema_version",
            "required_tool_calls",
            "final_response_contains",
        }
        if not isinstance(data, dict) or set(data) != expected:
            raise ValueError(
                "agentic pass condition must contain exactly schema_version, "
                "required_tool_calls, and final_response_contains"
            )
        if data["schema_version"] != AGENTIC_PASS_CONDITION_SCHEMA_VERSION:
            raise ValueError(
                "unsupported agentic pass-condition schema "
                f"{data['schema_version']!r}"
            )
        raw_calls = data["required_tool_calls"]
        if not isinstance(raw_calls, list):
            raise ValueError("required_tool_calls must be a list")
        calls = tuple(
            RequiredToolCall.from_dict(value, index=index)
            for index, value in enumerate(raw_calls)
        )
        call_keys = [
            (call.name, _canonical_json_text(call.arguments)) for call in calls
        ]
        if len(call_keys) != len(set(call_keys)):
            raise ValueError("required_tool_calls contains duplicate calls")

        raw_fragments = data["final_response_contains"]
        if not isinstance(raw_fragments, list):
            raise ValueError("final_response_contains must be a list")
        fragments: list[str] = []
        for index, value in enumerate(raw_fragments):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"final_response_contains[{index}] must be a non-empty string"
                )
            fragments.append(value)
        if len(fragments) != len({fragment.casefold() for fragment in fragments}):
            raise ValueError("final_response_contains contains duplicates")
        if not calls and not fragments:
            raise ValueError(
                "agentic pass condition must require a tool call or response text"
            )
        return cls(
            required_tool_calls=calls,
            final_response_contains=tuple(fragments),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "required_tool_calls": [call.to_dict() for call in self.required_tool_calls],
            "final_response_contains": list(self.final_response_contains),
        }


@dataclass
class AgentTurnOutput:
    """One turn's worth of model output in the tool-use loop.

    `text` is the assistant's natural-language content (None when the turn
    is pure tool calls). `tool_calls` is a list of {"id", "name",
    "arguments"} dicts; an empty list signals the turn is final.
    """

    text: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    cost_known: bool = True


class AgentCostUnknownError(RuntimeError):
    """Raised before checkpointing when an agent turn has unknown cost."""


class AgentClient(Protocol):
    """A tool-using model: messages plus a tool catalog in, one turn out."""

    def __call__(
        self,
        messages: list[dict[str, Any]],
        tools: list[Tool],
    ) -> AgentTurnOutput:  # pragma: no cover
        ...


AgentCheckpointCallback = Callable[[Trajectory, bool], None]


def run_agent(
    client: AgentClient,
    item: BenchmarkItem,
    tools: list[Tool],
    *,
    system_prompt: str | None = None,
    max_iters: int = 8,
    initial_trajectory: Trajectory | None = None,
    on_checkpoint: AgentCheckpointCallback | None = None,
    terminal_tool: str | None = None,
) -> Trajectory:
    """Drive a tool-using model to an answer, recording the trajectory.

    Each iteration calls the client, records an 'assistant' turn, and:
      - if the turn requested tool calls, executes each against the
        matching Tool.fn(**arguments), records a 'tool_result' turn per
        call, feeds the results back into the message history, and loops;
      - otherwise treats the turn's text as the final answer and stops.

    A tool name with no matching Tool records an error tool_result and the
    loop continues, so one bad call never aborts the run. The loop is
    capped at `max_iters`; on exhaustion the last turn's text becomes the
    final response.
    """
    tool_index = {tool.name: tool for tool in tools}
    trajectory = _copy_trajectory(initial_trajectory)
    messages = _messages_from_trajectory(item, system_prompt, trajectory)
    completed_iters = sum(turn.role == "assistant" for turn in trajectory.turns)
    last_text = _last_assistant_text(trajectory)

    if completed_iters > max_iters:
        raise ValueError(
            f"initial trajectory has {completed_iters} assistant turns; "
            f"max_iters is {max_iters}"
        )

    pending = _pending_tool_calls(trajectory)
    def finish(call, result):
        if terminal_tool is None or call.get("name") != terminal_tool or (isinstance(result, dict) and "error" in result):
            return False
        trajectory.final_response = result
        _emit_checkpoint(on_checkpoint, trajectory, complete=True)
        return True

    if terminal_tool is not None:
        for turn in trajectory.turns:
            if turn.role == "tool_result" and finish(turn.content, turn.content.get("result")):
                return trajectory
    if pending:
        for call in pending:
            result = _execute_tool_call(tool_index, call)
            _append_tool_result(trajectory, messages, call, result)
            if finish(call, result):
                return trajectory
            _emit_checkpoint(on_checkpoint, trajectory, complete=False)

    for _ in range(completed_iters, max_iters):
        from arisekit.dispatch import dispatch_agent
        output = dispatch_agent(client, messages, tools)
        try:
            turn_cost = float(output.cost)
        except (TypeError, ValueError) as exc:
            raise AgentCostUnknownError(
                "agent provider cost is unavailable"
            ) from exc
        if (
            output.cost_known is not True
            or not math.isfinite(turn_cost)
            or turn_cost < 0
        ):
            raise AgentCostUnknownError("agent provider cost is unavailable")
        last_text = output.text
        tool_calls = output.tool_calls or []
        trajectory.total_tokens_in += output.tokens_in or 0
        trajectory.total_tokens_out += output.tokens_out or 0
        trajectory.total_tokens = (
            trajectory.total_tokens_in + trajectory.total_tokens_out
        )
        trajectory.total_cost += turn_cost

        if tool_calls:
            trajectory.turns.append(
                Turn(role="assistant", content={"text": output.text, "tool_calls": tool_calls})
            )
        else:
            trajectory.turns.append(Turn(role="assistant", content=output.text))

        messages.append(
            {"role": "assistant", "content": output.text or "", "tool_calls": tool_calls}
        )

        if not tool_calls:
            trajectory.final_response = output.text
            _emit_checkpoint(on_checkpoint, trajectory, complete=True)
            break

        # Persist the model's tool-call intent before dispatch. On resume, calls
        # that already have a recorded result are skipped and only pending IDs
        # are dispatched.
        _emit_checkpoint(on_checkpoint, trajectory, complete=False)
        for call in tool_calls:
            result = _execute_tool_call(tool_index, call)
            _append_tool_result(trajectory, messages, call, result)
            if finish(call, result):
                return trajectory
            _emit_checkpoint(on_checkpoint, trajectory, complete=False)
    else:
        # Loop hit max_iters without a tool-free turn: best-effort answer.
        trajectory.final_response = last_text
        _emit_checkpoint(on_checkpoint, trajectory, complete=True)

    return trajectory


def _seed_messages(
    item: BenchmarkItem,
    system_prompt: str | None,
) -> list[dict[str, Any]]:
    """Turn (system_prompt, item.prompt) into a mutable message list."""
    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if isinstance(item.prompt, str):
        messages.append({"role": "user", "content": item.prompt})
    else:
        messages.extend(dict(m) for m in item.prompt)
    return messages


def _copy_trajectory(initial: Trajectory | None) -> Trajectory:
    if initial is None:
        return Trajectory()
    return Trajectory.from_dict(initial.to_dict())


def _messages_from_trajectory(
    item: BenchmarkItem,
    system_prompt: str | None,
    trajectory: Trajectory,
) -> list[dict[str, Any]]:
    messages = _seed_messages(item, system_prompt)
    for turn in trajectory.turns:
        if turn.role == "assistant":
            if isinstance(turn.content, dict):
                messages.append(
                    {
                        "role": "assistant",
                        "content": turn.content.get("text") or "",
                        "tool_calls": turn.content.get("tool_calls") or [],
                    }
                )
            else:
                messages.append(
                    {"role": "assistant", "content": turn.content or "", "tool_calls": []}
                )
        elif turn.role == "tool_result" and isinstance(turn.content, dict):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": turn.content.get("id"),
                    "name": turn.content.get("name"),
                    "content": turn.content.get("result"),
                }
            )
    return messages


def _last_assistant_text(trajectory: Trajectory) -> Any:
    for turn in reversed(trajectory.turns):
        if turn.role != "assistant":
            continue
        if isinstance(turn.content, dict):
            return turn.content.get("text")
        return turn.content
    return None


def _pending_tool_calls(trajectory: Trajectory) -> list[dict[str, Any]]:
    """Return calls on the latest assistant turn that have no saved result."""
    assistant_index: int | None = None
    calls: list[dict[str, Any]] = []
    for index in range(len(trajectory.turns) - 1, -1, -1):
        turn = trajectory.turns[index]
        if turn.role != "assistant":
            continue
        assistant_index = index
        if isinstance(turn.content, dict):
            calls = [
                call
                for call in (turn.content.get("tool_calls") or [])
                if isinstance(call, dict)
            ]
        break
    if assistant_index is None or not calls:
        return []
    completed_count = sum(
        turn.role == "tool_result" and isinstance(turn.content, dict)
        for turn in trajectory.turns[assistant_index + 1 :]
    )
    return calls[completed_count:]


def _append_tool_result(
    trajectory: Trajectory,
    messages: list[dict[str, Any]],
    call: dict[str, Any],
    result: Any,
) -> None:
    trajectory.turns.append(
        Turn(
            role="tool_result",
            content={
                "id": call.get("id"),
                "name": call.get("name"),
                "result": result,
            },
        )
    )
    messages.append(
        {
            "role": "tool",
            "tool_call_id": call.get("id"),
            "name": call.get("name"),
            "content": result,
        }
    )


def _emit_checkpoint(
    callback: AgentCheckpointCallback | None,
    trajectory: Trajectory,
    *,
    complete: bool,
) -> None:
    if callback is not None:
        callback(_copy_trajectory(trajectory), complete)


def _execute_tool_call(
    tool_index: dict[str, Tool],
    call: dict[str, Any],
) -> Any:
    """Run one tool call, returning its result or an error payload."""
    name = call.get("name")
    tool = tool_index.get(name) if name is not None else None
    if tool is None:
        return {"error": f"tool not found: {name}"}
    arguments = call.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    try:
        return tool.fn(**arguments)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "tool": name}


# --- scoring ---------------------------------------------------------


def _as_trajectory(response: Any) -> Trajectory:
    """Coerce any RunResult.response shape into a Trajectory.

    Real trajectories pass through; a Trajectory-dict is rehydrated; plain
    text (or anything else) becomes a turn-less Trajectory whose
    final_response is the value, so the default check can still run a
    substring test on it.
    """
    if isinstance(response, Trajectory):
        return response
    if isinstance(response, dict) and response.get("kind") == "trajectory":
        return Trajectory.from_dict(response)
    return Trajectory(turns=[], final_response=response)


def _final_text(traj: Trajectory) -> str:
    """Best-effort string form of a trajectory's final response."""
    value = traj.final_response
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _called_tool_names(traj: Trajectory) -> set[str]:
    """Collect every tool name invoked across a trajectory's turns."""
    names: set[str] = set()
    for turn in traj.turns:
        content = turn.content
        if turn.role == "tool_result" and isinstance(content, dict):
            name = content.get("name")
            if isinstance(name, str):
                names.add(name)
        if turn.role == "assistant" and isinstance(content, dict):
            for call in content.get("tool_calls", []) or []:
                if isinstance(call, dict) and isinstance(call.get("name"), str):
                    names.add(call["name"])
    return names


def _canonical_json_object(value: dict[str, Any], label: str) -> dict[str, Any]:
    """Detach and validate a JSON object, including finite numbers."""

    encoded = _canonical_json_text(value)
    detached = json.loads(encoded)
    if not isinstance(detached, dict):  # pragma: no cover - guarded by caller
        raise ValueError(f"{label} must be an object")
    return detached


def _successful_tool_calls(traj: Trajectory) -> list[tuple[str, str, str]]:
    """Return ``(id, name, canonical arguments)`` for completed tool calls."""

    calls: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    results: dict[str, list[tuple[str | None, Any]]] = {}
    for turn in traj.turns:
        content = turn.content
        if turn.role == "assistant" and isinstance(content, dict):
            for call in content.get("tool_calls", []) or []:
                if not isinstance(call, dict):
                    continue
                call_id = call.get("id")
                name = call.get("name")
                arguments = call.get("arguments")
                if (
                    isinstance(call_id, str)
                    and call_id
                    and isinstance(name, str)
                    and isinstance(arguments, dict)
                ):
                    calls.setdefault(call_id, []).append((name, arguments))
        elif turn.role == "tool_call" and isinstance(content, dict):
            call_id = content.get("id")
            name = content.get("name")
            arguments = content.get("arguments")
            if (
                isinstance(call_id, str)
                and call_id
                and isinstance(name, str)
                and isinstance(arguments, dict)
            ):
                calls.setdefault(call_id, []).append((name, arguments))
        elif turn.role == "tool_result" and isinstance(content, dict):
            call_id = content.get("id")
            if isinstance(call_id, str) and call_id:
                result = content.get("result")
                result_name = content.get("name")
                results.setdefault(call_id, []).append(
                    (
                        result_name if isinstance(result_name, str) else None,
                        result,
                    )
                )

    successful: list[tuple[str, str, str]] = []
    for call_id, declarations in calls.items():
        completions = results.get(call_id, [])
        if len(declarations) != 1 or len(completions) != 1:
            continue
        name, arguments = declarations[0]
        result_name, result = completions[0]
        if result_name is not None and result_name != name:
            continue
        if isinstance(result, dict) and "error" in result:
            continue
        try:
            encoded_arguments = _canonical_json_text(arguments)
        except ValueError:
            continue
        successful.append((call_id, name, encoded_arguments))
    return successful


def trajectory_passes_condition(
    trajectory: Trajectory,
    condition: AgenticPassCondition,
) -> bool:
    """Evaluate every tool and response requirement with AND semantics."""

    available = _successful_tool_calls(trajectory)
    used: set[int] = set()
    for required in condition.required_tool_calls:
        arguments = _canonical_json_text(required.arguments)
        match = next(
            (
                index
                for index, (_, name, actual_arguments) in enumerate(available)
                if index not in used
                and name == required.name
                and actual_arguments == arguments
            ),
            None,
        )
        if match is None:
            return False
        used.add(match)

    response = _final_text(trajectory).casefold()
    return all(fragment.casefold() in response for fragment in condition.final_response_contains)


def _default_check(traj: Trajectory, item: BenchmarkItem) -> bool:
    """Ground-truth aware pass predicate for a single trajectory.

    Interprets `item.ground_truth` three ways:
      - str: the final response must contain it (case-insensitive).
      - list: every substring must appear in the final response.
      - dict {"tool_calls": [names]}: every named tool must have been called.
    Any other ground-truth shape (including None) fails, since there is
    nothing to check the trajectory against.
    """
    gt = item.ground_truth
    if isinstance(gt, dict):
        if gt.get("schema_version") == AGENTIC_PASS_CONDITION_SCHEMA_VERSION:
            return trajectory_passes_condition(
                traj,
                AgenticPassCondition.from_dict(gt),
            )
        required = gt.get("tool_calls", []) or []
        called = _called_tool_names(traj)
        return all(name in called for name in required)
    text = _final_text(traj).lower()
    if isinstance(gt, list):
        return all(str(sub).lower() in text for sub in gt)
    if isinstance(gt, str):
        return gt.lower() in text
    return False


class PassAtOneScorer(BaseScorer):
    """Grade agentic trajectories with a per-trial pass/fail predicate.

    Emits one metric (default name "pass_at_1") whose value is the mean of
    1.0 (pass) / 0.0 (fail) across trials. The default predicate checks the
    trajectory's final response or tool-call set against `item.ground_truth`
    (see `_default_check`); pass a custom `check(trajectory, item) -> bool`
    to grade domain-specific success instead.
    """

    def __init__(
        self,
        *,
        name: str = "pass_at_1",
        condition_schema: str | None = None,
        check: Callable[[Trajectory, BenchmarkItem], bool] | None = None,
    ):
        if condition_schema not in (None, AGENTIC_PASS_CONDITION_SCHEMA_VERSION):
            raise ValueError(
                f"unsupported agentic pass-condition schema {condition_schema!r}"
            )
        if condition_schema is not None and check is not None:
            raise ValueError("condition_schema and a custom check cannot be combined")
        self.name = name
        self.condition_schema = condition_schema
        self._check = check

    @property
    def rescore_safe(self) -> bool:
        """The built-in predicate is replay-safe; arbitrary callbacks are not."""

        return self._check is None

    def configuration(self) -> Mapping[str, Any]:
        if self._check is not None:
            raise NotImplementedError(
                "persistent re-scoring does not support a custom pass@1 callback"
            )
        return {
            "kind": "pass-at-one",
            "name": self.name,
            "condition_schema": self.condition_schema,
        }

    def score_item(self, item: BenchmarkItem, responses: list[RunResult]) -> list[Metric]:
        per_trial: list[float] = []
        for r in responses:
            if r.error is not None:
                per_trial.append(0.0)
                continue
            traj = _as_trajectory(r.response)
            if self.condition_schema is not None:
                condition = AgenticPassCondition.from_dict(item.ground_truth)
                passed = trajectory_passes_condition(traj, condition)
            else:
                check = self._check or _default_check
                passed = check(traj, item)
            per_trial.append(1.0 if passed else 0.0)
        value = sum(per_trial) / len(per_trial) if per_trial else 0.0
        return [Metric(name=self.name, value=value, n=len(per_trial))]


__all__ = [
    "AGENTIC_PASS_CONDITION_SCHEMA_VERSION",
    "AgenticPassCondition",
    "RequiredToolCall",
    "AgentTurnOutput",
    "AgentCostUnknownError",
    "AgentClient",
    "AgentCheckpointCallback",
    "run_agent",
    "PassAtOneScorer",
    "trajectory_passes_condition",
]
