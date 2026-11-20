"""Durable per-dispatch accounting and replay of uncheckpointed responses."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import threading
from typing import Any, Callable
import uuid

from arisekit.common.hashing import canonical_sha256
from arisekit.durability import checkpoint_barrier

active_dispatch: ContextVar[Callable[..., Any] | None] = ContextVar(
    "arisekit_dispatch", default=None
)


class ProviderRequestNotSent(RuntimeError):
    """A trusted adapter confirms rejection before any provider request."""


class DispatchStopped(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(
            {
                "budget_exhausted": "cost budget exhausted before model call",
                "call_budget_exhausted": "model-call budget exhausted before model call",
                "call_retry_exhausted": "bounded transport retry limit reached",
                "user_stopped": "generation stopped by user",
                "cost_unknown": "provider cost is unknown; dispatch stopped",
                "cost_bound_exceeded": "provider cost exceeded reserved per-call bound",
            }[reason]
        )


class DispatchLedger:
    def __init__(
        self, path: Path, config: Any, seeds: dict[tuple[str, int], dict[str, Any]],
        *, reserved_failure_types: frozenset[str] = frozenset()
    ):
        self.path = path
        self.checkpoint_barrier = checkpoint_barrier.get()
        self.config = config
        self.lock = threading.RLock()
        self.stop_requested = False
        self.events: dict[str, dict[str, Any]] = {}
        self.seeds = seeds
        self.run_id = uuid.uuid4().hex
        self.strict = config.require_known_cost or config.max_cost_per_call is not None
        self.bound = Decimal(str(config.max_cost_per_call or 0))
        self.max_cost = (
            Decimal(str(config.max_cost)) if config.max_cost is not None else None
        )
        self.reserved_failure_types = frozenset(reserved_failure_types)
        if self.reserved_failure_types and (not self.bound.is_finite() or self.bound <= 0
                or self.max_cost is None or not self.max_cost.is_finite() or self.max_cost <= 0):
            raise ValueError("reserved failure recovery requires finite total and per-call cost limits")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open("a+", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.handle.seek(0)
            journal_text = self.handle.read()
            if journal_text and not journal_text.endswith("\n"):
                raise ValueError("dispatch journal has an incomplete terminal line")
            rows = journal_text.splitlines()
            seeded = False
            for raw in rows:
                if not raw.strip():
                    continue
                row = json.loads(raw)
                if row.get("schema_version") != "arisekit.dispatch.v1":
                    raise ValueError("unsupported dispatch journal schema")
                if row["state"] == "seed":
                    if seeded or self.events:
                        raise ValueError(
                            "dispatch journal seed must appear exactly once at the start"
                        )
                    seeded = True
                    for item in row["items"]:
                        _validate_usage(item["cost"], item["provider_calls"])
                    self.seeds = {(x["item"], x["trial"]): x for x in row["items"]}
                else:
                    if row["state"] not in {"reserved", "settled", "failed"}:
                        raise ValueError("invalid dispatch state")
                    if not seeded:
                        raise ValueError("dispatch journal has no opening seed")
                    _validate_usage(row["accounted_cost"], 1)
                    previous = self.events.get(row["call_id"])
                    if row["state"] == "reserved":
                        if previous is not None:
                            raise ValueError("duplicate dispatch reservation")
                    elif (
                        previous is None
                        or previous["state"] != "reserved"
                        or any(
                            previous[key] != row[key]
                            for key in ("item", "trial", "signature", "run_id")
                        )
                    ):
                        raise ValueError(
                            "dispatch settlement does not match its reservation"
                        )
                    self.events[row["call_id"]] = row
            if rows and not seeded:
                raise ValueError("dispatch journal has no opening seed")
            if not rows:
                for item in seeds.values():
                    _validate_usage(item["cost"], item["provider_calls"])
                self._append(
                    {
                        "state": "seed",
                        "items": [
                            {**value, "item": key[0], "trial": key[1]}
                            for key, value in seeds.items()
                        ],
                    }
                )
            self._stats = {}
            self._responses = {}
            for key, seed in self.seeds.items():
                self._adjust(
                    key,
                    [
                        Decimal(str(seed.get("cost", 0))),
                        seed.get("provider_calls", 0),
                        int(bool(seed.get("cost_unknown"))),
                        int(bool(seed.get("cost_bound_exceeded"))),
                        0,
                        0,
                        0,
                    ],
                    1,
                )
            for row in self.events.values():
                self._index(row, 1)
        except BaseException:
            self.handle.close()
            raise

    def close(self) -> None:
        self.handle.close()

    def _append(self, row: dict[str, Any]) -> None:
        row = {"schema_version": "arisekit.dispatch.v1", **row}
        encoded = json.dumps(row, ensure_ascii=False, allow_nan=False)
        self.handle.write(encoded + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())
        if self.checkpoint_barrier is not None:
            self.checkpoint_barrier()
        if "call_id" in row:
            old = self.events.get(row["call_id"])
            if hasattr(self, "_stats"):
                if old is not None:
                    self._index(old, -1)
                self._index(row, 1)
            self.events[row["call_id"]] = row

    def _adjust(self, key: tuple[str, int], values: list[Any], direction: int) -> None:
        for target in (None, key):
            total = self._stats.setdefault(target, [Decimal(0), 0, 0, 0, 0, 0, 0])
            for i, value in enumerate(values):
                total[i] += direction * value

    def _index(self, row: dict[str, Any], direction: int) -> None:
        pending = row["state"] == "reserved" and row["run_id"] != self.run_id
        unknown = bool(
            row.get("cost_unknown")
            or pending
            or (self.strict and row.get("cost_unverified"))
        )
        values = [
            Decimal(str(row["accounted_cost"])),
            0 if row.get("request_sent") is False else 1,
            int(unknown),
            int(bool(row.get("cost_bound_exceeded"))),
            int(bool(row.get("cost_unverified"))),
            int(bool(row.get("cost_unknown") and row["accounted_cost"] > 0)),
            int(pending),
        ]
        self._adjust((row["item"], row["trial"]), values, direction)
        if direction == 1 and row["state"] == "settled" and "output" in row:
            self._responses[(row["item"], row["trial"], row["signature"])] = row

    def usage(self, key: tuple[str, int] | None = None) -> dict[str, Any]:
        stats = self._stats.get(key, [Decimal(0), 0, 0, 0, 0, 0, 0])
        return {
            "cost": float(stats[0]),
            "provider_calls": stats[1],
            "cost_unknown": stats[2] > 0,
            "cost_known": stats[2] == 0 and stats[4] == 0,
            "cost_bound_exceeded": stats[3] > 0,
            "cost_reservation_consumed": stats[5] > 0,
            "pending_interruption": stats[6] > 0,
        }

    def request_stop(self) -> None:
        with self.lock:
            self.stop_requested = True

    def invoke(
        self,
        key: tuple[str, int],
        signature: str,
        function: Callable[[], Any],
        *,
        agent: bool,
        max_attempts: int | None = None,
    ) -> Any:
        with self.lock:
            if self.stop_requested:
                raise DispatchStopped("user_stopped")
            row = self._responses.get((*key, signature))
            if row is not None:
                if row.get("cost_bound_exceeded"):
                    raise DispatchStopped("cost_bound_exceeded")
                if row.get("cost_unknown") and (self.strict or agent):
                    raise DispatchStopped("cost_unknown")
                return self._decode(row["output"], agent)
            usage = self.usage()
            if usage["cost_unknown"] and (
                self.strict or agent or usage["pending_interruption"]
            ) and not self._covered_failures(agent):
                raise DispatchStopped("cost_unknown")
            if usage["cost_bound_exceeded"]:
                raise DispatchStopped("cost_bound_exceeded")
            if max_attempts is not None and self.usage(key)["provider_calls"] >= max_attempts:
                raise DispatchStopped("call_retry_exhausted")
            if (
                self.config.max_calls is not None
                and usage["provider_calls"] >= self.config.max_calls
            ):
                raise DispatchStopped("call_budget_exhausted")
            cost = Decimal(str(usage["cost"]))
            if self.max_cost is not None and (
                (self.bound and cost + self.bound > self.max_cost)
                or (not self.bound and cost >= self.max_cost)
            ):
                raise DispatchStopped("budget_exhausted")
            row = {
                "call_id": uuid.uuid4().hex,
                "run_id": self.run_id,
                "item": key[0],
                "trial": key[1],
                "signature": signature,
                "state": "reserved",
                "accounted_cost": float(self.bound),
            }
            self._append(row)
        try:
            output = function()
        except BaseException as exc:
            not_sent = isinstance(exc, ProviderRequestNotSent)
            with self.lock:
                self._append(
                    {
                        **row,
                        "state": "failed",
                        "accounted_cost": 0.0 if not_sent else row["accounted_cost"],
                        **({"request_sent": False} if not_sent else {}),
                        "cost_unknown": bool(
                            not not_sent and (self.strict or not isinstance(exc, Exception))
                        ),
                        "cost_unverified": not not_sent,
                        "error_type": type(exc).__name__,
                    }
                )
            if not_sent or not isinstance(exc, Exception):
                raise
            if self.strict:
                raise DispatchStopped("cost_unknown") from exc
            raise
        cost = output.cost
        known = (
            output.cost_known is True
            and not isinstance(cost, bool)
            and isinstance(cost, (int, float))
            and math.isfinite(cost)
            and cost >= 0
        )
        violation = known and self.bound > 0 and Decimal(str(cost)) > self.bound
        # Keep the normalized response, never the provider SDK's raw envelope.
        if agent:
            encoded = asdict(output)
        else:
            from arisekit.types import RunResult

            encoded = {k: v for k, v in vars(output).items() if k != "response"}
            encoded["response"] = RunResult("", 1, output.response).to_dict()[
                "response"
            ]
        if not known:
            encoded["cost"] = float(self.bound)
            encoded["cost_known"] = False
        with self.lock:
            self._append(
                {
                    **row,
                    "state": "settled",
                    "accounted_cost": cost if known else float(self.bound),
                    "cost_unknown": not known,
                    "cost_bound_exceeded": bool(violation),
                    "output": encoded,
                }
            )
        if violation:
            raise DispatchStopped("cost_bound_exceeded")
        if not known and (self.strict or agent):
            raise DispatchStopped("cost_unknown")
        return output

    def _covered_failures(self, agent: bool) -> bool:
        if agent or not self.reserved_failure_types or any(seed.get("cost_unknown") for seed in self.seeds.values()):
            return False
        for row in self.events.values():
            uncertain = (row.get("cost_unknown") or row.get("cost_unverified")
                         or (row["state"] == "reserved" and row["run_id"] != self.run_id))
            if uncertain and not (row["state"] == "failed"
                    and row.get("error_type") in self.reserved_failure_types
                    and Decimal(str(row["accounted_cost"])) >= self.bound):
                return False
        return True

    @staticmethod
    def _decode(data: dict[str, Any], agent: bool) -> Any:
        data = json.loads(json.dumps(data))
        if agent:
            from arisekit.agentic import AgentTurnOutput

            return AgentTurnOutput(**data)
        from arisekit.sut import SUTResponse
        from arisekit.types import RunResult

        return SUTResponse(
            **{
                **data,
                "response": RunResult.from_dict(
                    {"id": "", "trial": 1, "response": data["response"]}
                ).response,
            }
        )


def request_signature(value: Any) -> str:
    return canonical_sha256(value, ensure_ascii=True)


def dispatch_agent(client: Any, messages: Any, tools: Any) -> Any:
    invoke = active_dispatch.get()
    if invoke is None:
        return client(messages, tools)
    signature = request_signature(
        {
            "messages": messages,
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                }
                for t in tools
            ],
        }
    )
    return invoke(signature, lambda: client(messages, tools))


def _validate_usage(cost: Any, calls: Any) -> None:
    if (
        isinstance(cost, bool)
        or not isinstance(cost, (int, float))
        or not math.isfinite(cost)
        or cost < 0
        or type(calls) is not int
        or calls < 0
    ):
        raise ValueError("dispatch journal contains invalid usage")
