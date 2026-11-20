"""Pluggable, resumable execution of blinded NOHARM judge inputs."""

from __future__ import annotations

import hashlib
import inspect
import math
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from arisekit.common.files import existing_file as _existing_file
from arisekit.common.hashing import strict_canonical_sha256 as _sha256_json
from arisekit.common.jsonio import strict_canonical_json as _canonical_json, strict_json_object
from arisekit.common.validate import number, positive_int as _positive_int, sha256_hex as _sha256
from arisekit.judge_handoff import (
    JUDGED_RESULT_SCHEMA,
    JUDGE_INPUT_SCHEMA,
    normalize_judge_panel,
    validate_noharm_metrics,
)
from arisekit.evaluation.noharm_judge_contract import is_canonical_noharm_panel


JUDGE_EXECUTION_SCHEMA = "arisekit.noharm-parity-judge-execution.v1"
_INPUT_KEYS = {
    "schema_version",
    "opaque_id",
    "binding_digest",
    "response_sha256",
    "case",
    "response",
}
_RESULT_KEYS = {
    "schema_version",
    "opaque_id",
    "binding_digest",
    "response_sha256",
    "judge",
    "judge_execution_digest",
    "judge_provenance",
    "metrics",
}
_PROVENANCE_KEYS = {
    "provider",
    "model",
    "provider_model",
    "settings_sha256",
    "judge_runtime_hash",
    "provider_response_ids",
    "cost_usd",
}


@dataclass(frozen=True)
class BlindedJudgeCall:
    """The complete information an adapter may receive for one judgment."""

    judge_id: str
    judge_config: Mapping[str, Any]
    opaque_id: str
    binding_digest: str
    response_sha256: str
    case: Mapping[str, Any]
    response: Any
    max_cost_usd_remaining: float


@dataclass(frozen=True)
class BlindedJudgeResponse:
    """One adapter result with provider-returned execution provenance."""

    metrics: Mapping[str, float]
    provider: str
    model: str
    provider_model: str
    provider_response_ids: Sequence[str]
    cost_usd: float


class BlindedJudgeAdapter(Protocol):
    def __call__(self, call: BlindedJudgeCall) -> BlindedJudgeResponse:
        """Judge one opaque response without access to reidentification data."""


@dataclass(frozen=True)
class JudgeExecutionSummary:
    output_path: Path
    manifest_path: Path
    manifest_digest: str
    expected: int
    completed: int
    skipped: int
    calls_made: int
    cost_usd: float
    complete: bool
    budget_exhausted: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": "blinded-judge-execution",
            "output_path": str(self.output_path),
            "manifest_path": str(self.manifest_path),
            "manifest_digest": self.manifest_digest,
            "expected": self.expected,
            "completed": self.completed,
            "skipped": self.skipped,
            "calls_made": self.calls_made,
            "cost_usd": self.cost_usd,
            "complete": self.complete,
            "budget_exhausted": self.budget_exhausted,
        }


def execute_blinded_judges(
    judge_input_path: str | Path,
    *,
    judge_panel: Sequence[Mapping[str, Any]],
    judge_runtime_hash: str,
    adapters: Mapping[str, BlindedJudgeAdapter],
    adapter_ids: Mapping[str, str],
    output_path: str | Path,
    max_cost_usd: float,
    max_calls: int,
) -> JudgeExecutionSummary:
    """Run the frozen panel over opaque rows with checkpoint/resume semantics."""
    input_path = _existing_file(judge_input_path, "judge input")
    output = Path(output_path).expanduser().resolve()
    if output == input_path:
        raise ValueError("judge output cannot overwrite judge input")
    if output.is_symlink():
        raise ValueError("judge output must not be a symlink")
    runtime_hash = _sha256(judge_runtime_hash, "judge runtime hash")
    budget = _positive_number(max_cost_usd, "max_cost_usd")
    call_cap = _positive_int(max_calls, "max_calls")
    panel = normalize_judge_panel(judge_panel)
    if is_canonical_noharm_panel(panel):
        raise ValueError(
            "the canonical NOHARM composite must use the cohort-pooled "
            "canonical batch executor"
        )
    panel_by_id = {record["id"]: record for record in panel}
    expected_ids = set(panel_by_id)
    if set(adapters) != expected_ids or set(adapter_ids) != expected_ids:
        raise ValueError("adapters and adapter_ids must exactly match the judge panel")
    normalized_adapter_ids = {
        judge: _required_string(adapter_ids[judge], f"adapter id for {judge}")
        for judge in panel_by_id
    }
    adapter_records = {
        judge: {
            "adapter_id": normalized_adapter_ids[judge],
            "code_sha256": _adapter_code_hash(adapters[judge]),
        }
        for judge in panel_by_id
    }

    input_bytes = input_path.read_bytes()
    input_rows = _load_judge_inputs(input_bytes, input_path)
    execution_manifest = {
        "schema_version": JUDGE_EXECUTION_SCHEMA,
        "judge_input_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "judge_panel": list(panel),
        "judge_runtime_hash": runtime_hash,
        "adapters": adapter_records,
        "max_cost_usd": budget,
        "max_calls": call_cap,
    }
    manifest_bytes = (_canonical_json(execution_manifest) + "\n").encode("utf-8")
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = output.with_name(output.name + ".execution.json")
    if manifest_path in {input_path, output}:
        raise ValueError("judge execution manifest path collides with an artifact")
    _write_new_or_identical(manifest_path, manifest_bytes)

    expected_pairs = [
        (row["opaque_id"], panel_record["id"])
        for row in input_rows
        for panel_record in panel
    ]
    input_by_id = {row["opaque_id"]: row for row in input_rows}
    existing = _load_existing_results(
        output,
        input_by_id=input_by_id,
        panel_by_id=panel_by_id,
        judge_runtime_hash=runtime_hash,
        execution_digest=manifest_digest,
    )
    unexpected = set(existing) - set(expected_pairs)
    if unexpected:
        raise ValueError(
            f"judge checkpoint contains unexpected identities: {unexpected}"
        )
    spent = sum(float(row["judge_provenance"]["cost_usd"]) for row in existing.values())
    calls_before = len(existing)
    if spent > budget:
        raise ValueError("existing judge checkpoint already exceeds its cost ceiling")
    if calls_before > call_cap:
        raise ValueError("existing judge checkpoint already exceeds its call ceiling")

    output.parent.mkdir(parents=True, exist_ok=True)
    handle = output.open("a", encoding="utf-8")
    calls_made = 0
    budget_exhausted = False
    try:
        for opaque_id, judge_id in expected_pairs:
            if (opaque_id, judge_id) in existing:
                continue
            if calls_before + calls_made >= call_cap or spent >= budget:
                budget_exhausted = True
                break
            row = input_by_id[opaque_id]
            panel_record = panel_by_id[judge_id]
            remaining = budget - spent
            call = BlindedJudgeCall(
                judge_id=judge_id,
                judge_config=panel_record,
                opaque_id=opaque_id,
                binding_digest=row["binding_digest"],
                response_sha256=row["response_sha256"],
                case=row["case"],
                response=row["response"],
                max_cost_usd_remaining=remaining,
            )
            produced = adapters[judge_id](call)
            calls_made += 1
            result = _result_row(
                call,
                produced,
                expected=panel_record,
                judge_runtime_hash=runtime_hash,
                execution_digest=manifest_digest,
            )
            cost = float(result["judge_provenance"]["cost_usd"])
            if cost > remaining:
                raise ValueError(
                    f"judge {judge_id!r} exceeded the remaining cost ceiling"
                )
            spent += cost
            handle.write(_canonical_json(result) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            existing[(opaque_id, judge_id)] = result
    finally:
        handle.close()

    complete = set(existing) == set(expected_pairs)
    if not complete and (calls_before + calls_made >= call_cap or spent >= budget):
        budget_exhausted = True
    return JudgeExecutionSummary(
        output_path=output,
        manifest_path=manifest_path,
        manifest_digest=manifest_digest,
        expected=len(expected_pairs),
        completed=len(existing),
        skipped=calls_before,
        calls_made=calls_made,
        cost_usd=spent,
        complete=complete,
        budget_exhausted=budget_exhausted,
    )


def _result_row(
    call: BlindedJudgeCall,
    response: Any,
    *,
    expected: Mapping[str, Any],
    judge_runtime_hash: str,
    execution_digest: str,
) -> dict[str, Any]:
    if not isinstance(response, BlindedJudgeResponse):
        raise ValueError("judge adapter must return BlindedJudgeResponse")
    validate_noharm_metrics(response.metrics, context=f"judge {call.judge_id}")
    for name, actual, expected_value in (
        ("provider", response.provider, expected["provider"]),
        ("model", response.model, expected["model"]),
        (
            "provider_model",
            response.provider_model,
            expected["expected_provider_model"],
        ),
    ):
        normalized = _required_string(actual, f"judge response {name}")
        if normalized != expected_value:
            raise ValueError(
                f"judge {call.judge_id!r} returned unexpected {name} {normalized!r}"
            )
    response_ids = tuple(
        _required_string(value, "judge provider response id")
        for value in response.provider_response_ids
    )
    if not response_ids or len(set(response_ids)) != len(response_ids):
        raise ValueError("judge provider response ids must be non-empty and unique")
    cost = response.cost_usd
    if (
        isinstance(cost, bool)
        or not isinstance(cost, (int, float))
        or not math.isfinite(cost)
        or cost < 0
    ):
        raise ValueError("judge response cost_usd must be finite and non-negative")
    return {
        "schema_version": JUDGED_RESULT_SCHEMA,
        "opaque_id": call.opaque_id,
        "binding_digest": call.binding_digest,
        "response_sha256": call.response_sha256,
        "judge": call.judge_id,
        "judge_execution_digest": execution_digest,
        "judge_provenance": {
            "provider": response.provider,
            "model": response.model,
            "provider_model": response.provider_model,
            "settings_sha256": _sha256_json(expected["settings"]),
            "judge_runtime_hash": judge_runtime_hash,
            "provider_response_ids": list(response_ids),
            "cost_usd": float(cost),
        },
        "metrics": dict(response.metrics),
    }


def _load_judge_inputs(content: bytes, path: Path) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    identities: set[str] = set()
    for line_number, raw in enumerate(content.splitlines(), start=1):
        if not raw.strip():
            continue
        row = _json_object(raw, f"{path}:{line_number}")
        _exact_keys(row, _INPUT_KEYS, f"{path}:{line_number}")
        if row["schema_version"] != JUDGE_INPUT_SCHEMA:
            raise ValueError(f"{path}:{line_number} has an unsupported input schema")
        opaque_id = _required_string(
            row["opaque_id"], f"{path}:{line_number} opaque_id"
        )
        if opaque_id in identities:
            raise ValueError(f"{path}:{line_number} duplicates opaque_id {opaque_id}")
        identities.add(opaque_id)
        _sha256(row["binding_digest"], f"{path}:{line_number} binding_digest")
        response_hash = _sha256(
            row["response_sha256"],
            f"{path}:{line_number} response_sha256",
        )
        if _sha256_json(row["response"]) != response_hash:
            raise ValueError(
                f"{path}:{line_number} response hash does not match response"
            )
        if not isinstance(row["case"], Mapping):
            raise ValueError(f"{path}:{line_number} case must be an object")
        rows.append(row)
    if not rows:
        raise ValueError(f"{path} contains no judge inputs")
    return tuple(rows)


def _load_existing_results(
    path: Path,
    *,
    input_by_id: Mapping[str, Mapping[str, Any]],
    panel_by_id: Mapping[str, Mapping[str, Any]],
    judge_runtime_hash: str,
    execution_digest: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise ValueError("judge output checkpoint must be a regular file")
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for line_number, raw in enumerate(path.read_bytes().splitlines(), start=1):
        if not raw.strip():
            continue
        row = _json_object(raw, f"{path}:{line_number}")
        _exact_keys(row, _RESULT_KEYS, f"{path}:{line_number}")
        if row["schema_version"] != JUDGED_RESULT_SCHEMA:
            raise ValueError(f"{path}:{line_number} has an unsupported result schema")
        opaque_id = _required_string(
            row["opaque_id"], f"{path}:{line_number} opaque_id"
        )
        judge_id = _required_string(row["judge"], f"{path}:{line_number} judge")
        if row["judge_execution_digest"] != execution_digest:
            raise ValueError(f"{path}:{line_number} changed judge execution digest")
        source = input_by_id.get(opaque_id)
        panel = panel_by_id.get(judge_id)
        if source is None or panel is None:
            raise ValueError(f"{path}:{line_number} is outside the frozen execution")
        if (
            row["binding_digest"] != source["binding_digest"]
            or row["response_sha256"] != source["response_sha256"]
        ):
            raise ValueError(f"{path}:{line_number} changed an opaque input binding")
        provenance = row["judge_provenance"]
        _exact_keys(provenance, _PROVENANCE_KEYS, f"{path}:{line_number} provenance")
        expected_provenance = {
            "provider": panel["provider"],
            "model": panel["model"],
            "provider_model": panel["expected_provider_model"],
            "settings_sha256": _sha256_json(panel["settings"]),
            "judge_runtime_hash": judge_runtime_hash,
        }
        for name, expected in expected_provenance.items():
            if provenance.get(name) != expected:
                raise ValueError(f"{path}:{line_number} changed judge provenance")
        response_ids = provenance["provider_response_ids"]
        if (
            not isinstance(response_ids, list)
            or not response_ids
            or not all(
                isinstance(value, str) and value.strip() for value in response_ids
            )
        ):
            raise ValueError(f"{path}:{line_number} has invalid provider response ids")
        cost = provenance["cost_usd"]
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(cost)
            or cost < 0
        ):
            raise ValueError(f"{path}:{line_number} has invalid cost")
        validate_noharm_metrics(row["metrics"], context=f"{path}:{line_number}")
        identity = (opaque_id, judge_id)
        if identity in rows:
            raise ValueError(f"{path}:{line_number} duplicates {identity}")
        rows[identity] = row
    return rows


def _adapter_code_hash(adapter: Callable[..., Any]) -> str:
    target: Any = adapter if inspect.isfunction(adapter) else type(adapter)
    source_path = inspect.getsourcefile(target)
    if source_path is not None and Path(source_path).is_file():
        source_hash = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
        identity = {
            "module": getattr(target, "__module__", ""),
            "qualname": getattr(target, "__qualname__", type(adapter).__qualname__),
            "source_sha256": source_hash,
        }
        return _sha256_json(identity)
    code = getattr(adapter, "__code__", None)
    if code is not None:
        identity = {
            "module": getattr(adapter, "__module__", ""),
            "qualname": getattr(adapter, "__qualname__", ""),
            "bytecode_sha256": hashlib.sha256(code.co_code).hexdigest(),
            "constants": repr(code.co_consts),
        }
        return _sha256_json(identity)
    declared = getattr(adapter, "code_sha256", None)
    return _sha256(declared, "adapter code_sha256")


def _write_new_or_identical(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != content:
            raise ValueError(f"judge execution manifest conflicts at {path}")
        return
    try:
        with path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != content:
            raise ValueError(f"judge execution manifest conflicts at {path}")


def _json_object(content: bytes, source: str) -> dict[str, Any]:
    return strict_json_object(content, source, allow_bytes=True, allow_duplicate_keys=True)


def _exact_keys(value: Any, expected: set[str], context: str) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{context} fields do not match the strict schema")


def _required_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _positive_number(value: Any, name: str) -> float:
    return number(value, name, exclusive_minimum=0)


__all__ = [
    "JUDGE_EXECUTION_SCHEMA",
    "BlindedJudgeAdapter",
    "BlindedJudgeCall",
    "BlindedJudgeResponse",
    "JudgeExecutionSummary",
    "execute_blinded_judges",
]
