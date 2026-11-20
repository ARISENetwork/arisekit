"""Core data types for ARISEKit.

The shapes here are the contract between the four moving parts of a
benchmark: items go in, responses come out, scorers turn responses
into metrics. Stick to JSON-serializable values inside the dataclasses
so the runner can checkpoint everything as JSONL with no extra hooks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# A prompt is either a single string or a chat-style message list. The
# message-list form is what NOHARM, MedAgentBench, and ReXrank use.
Prompt = str | list[dict[str, Any]]


@dataclass
class BenchmarkItem:
    """A single evaluation item. The universal input type."""

    id: str
    prompt: Prompt
    metadata: dict[str, Any] = field(default_factory=dict)
    ground_truth: Any = None
    attachments: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "metadata": self.metadata,
            "ground_truth": self.ground_truth,
            "attachments": self.attachments,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkItem":
        return cls(
            id=str(data["id"]),
            prompt=data["prompt"],
            metadata=dict(data.get("metadata", {})),
            ground_truth=data.get("ground_truth"),
            attachments=list(data.get("attachments", [])),
        )


@dataclass
class RunResult:
    """One model response. Persisted per (item_id, trial)."""

    id: str
    trial: int
    response: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trial": self.trial,
            "response": _serialize_response(self.response),
            "metadata": self.metadata,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunResult":
        return cls(
            id=str(data["id"]),
            trial=int(data["trial"]),
            response=_deserialize_response(data.get("response")),
            metadata=dict(data.get("metadata", {})),
            error=data.get("error"),
        )


@dataclass
class Metric:
    """A single scalar metric. Multiple per item, aggregated across items."""

    name: str
    value: float
    category: str = "overall"
    n: int | None = None
    ci: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "category": self.category,
            "n": self.n,
            "ci": self.ci,
        }


# --- Agentic types (used by MedAgentBench-style benchmarks) ----------


@dataclass
class Tool:
    """A callable the agent can invoke. JSON-schema parameters, sync fn."""

    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., Any]


@dataclass
class Turn:
    """One step in an agentic trajectory.

    Roles: 'assistant' (model text or tool-call intent), 'tool_call'
    (the dispatched call), 'tool_result' (the value returned).
    """

    role: str
    content: Any

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content}


@dataclass
class Trajectory:
    """A sequence of turns plus the final response.

    Scorers for agentic benchmarks read `final_response` for the answer
    and `turns` to grade tool-use behavior.
    """

    turns: list[Turn] = field(default_factory=list)
    final_response: Any = None
    total_tokens: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "trajectory",
            "turns": [t.to_dict() for t in self.turns],
            "final_response": self.final_response,
            "total_tokens": self.total_tokens,
            "total_tokens_in": self.total_tokens_in,
            "total_tokens_out": self.total_tokens_out,
            "total_cost": self.total_cost,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Trajectory":
        return cls(
            turns=[Turn(role=t["role"], content=t["content"]) for t in data.get("turns", [])],
            final_response=data.get("final_response"),
            total_tokens=int(data.get("total_tokens", 0)),
            total_tokens_in=int(data.get("total_tokens_in", 0)),
            total_tokens_out=int(data.get("total_tokens_out", 0)),
            total_cost=float(data.get("total_cost", 0.0)),
        )


# --- internal helpers ------------------------------------------------


def _serialize_response(response: Any) -> Any:
    if isinstance(response, Trajectory):
        return response.to_dict()
    return response


def _deserialize_response(response: Any) -> Any:
    if isinstance(response, dict) and response.get("kind") == "trajectory":
        return Trajectory.from_dict(response)
    return response
