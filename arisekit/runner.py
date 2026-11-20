"""Inference runner with resume, retry, parallelism, and cost tracking.

The runner is the only place in ARISEKit that touches the model. Everything
else operates on RunResult objects.

Persistence shape:
    results/raw/{benchmark}/{model_slug}.jsonl
    results/raw/{benchmark}/{manifest_digest}/{model_slug}.jsonl  # manifested

The JSONL is append-only. Resume works by reading all completed
(item_id, trial) pairs from the file at startup; tasks that already
succeeded are skipped. Errored rows are retried (since a transient
failure shouldn't lock the run in a bad state forever).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Callable

from arisekit.client import ModelClient
from arisekit.dataset import Dataset
from arisekit.run_manifest import RunManifest
from arisekit.sut import SUTCheckpoint, SystemUnderTest
from arisekit.types import RunResult

log = logging.getLogger("arisekit.runner")


@dataclass
class RunnerConfig:
    trials: int = 1
    threads: int = 1
    max_retries: int = 3
    retry_backoff: float = 1.5  # seconds, exponential base
    results_dir: Path = field(default_factory=lambda: Path("results"))
    temperature: float | None = None
    max_tokens: int | None = None
    max_cost: float | None = None
    # When set, each dispatched call reserves this amount against max_cost.
    # Strict accounting also treats missing cost after dispatch as terminal.
    max_cost_per_call: float | None = None
    require_known_cost: bool = False
    max_calls: int | None = None
    reserved_failure_types: tuple[str, ...] = ()


@dataclass
class RunSummary:
    completed: int
    errored: int
    skipped: int
    cost_total: float
    output_path: Path
    manifest_digest: str | None = None
    budget_exhausted: bool = False
    cost_unknown: bool = False
    cost_bound_exceeded: bool = False
    calls_total: int = 0
    call_budget_exhausted: bool = False
    stop_reason: str | None = None


def model_slug(model: str) -> str:
    """Filesystem-safe slug for the model id."""
    return model.replace("/", "__").replace(":", "_")


def raw_path(
    config: RunnerConfig,
    benchmark_name: str,
    model: str,
    *,
    manifest_digest: str | None = None,
) -> Path:
    root = config.results_dir / "raw" / benchmark_name
    if manifest_digest is not None:
        root = root / manifest_digest
    return root / f"{model_slug(model)}.jsonl"


def turn_path(
    config: RunnerConfig,
    benchmark_name: str,
    model: str,
    *,
    manifest_digest: str | None = None,
) -> Path:
    """Sibling append-only journal for incremental SUT checkpoints."""
    path = raw_path(
        config,
        benchmark_name,
        model,
        manifest_digest=manifest_digest,
    )
    return path.with_suffix(".turns.jsonl")


def load_completed(
    path: Path,
    *,
    manifest_digest: str | None = None,
) -> dict[tuple[str, int], RunResult]:
    """Read existing checkpoint. Errored rows are *not* counted as done.

    Latest line wins for a given (id, trial) — append-only files written
    on retry will overwrite the previous (errored) attempt.
    """
    if not path.exists():
        return {}
    completed: dict[tuple[str, int], RunResult] = {}
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                log.warning("skip malformed checkpoint line in %s", path)
                continue
            result = RunResult.from_dict(payload)
            if manifest_digest is not None:
                found = result.metadata.get("run_manifest_digest")
                if found != manifest_digest:
                    raise ValueError(
                        f"checkpoint {path} contains manifest digest {found!r}; "
                        f"expected {manifest_digest!r}"
                    )
            completed[(result.id, result.trial)] = result
    return completed


def load_turn_checkpoints(
    path: Path,
    *,
    manifest_digest: str | None = None,
) -> dict[tuple[str, int], SUTCheckpoint]:
    """Load the latest trajectory checkpoint for every item/trial."""
    if not path.exists():
        return {}
    latest: dict[tuple[str, int], SUTCheckpoint] = {}
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                log.warning("skip malformed turn checkpoint line in %s", path)
                continue
            result = RunResult.from_dict(payload)
            metadata = result.metadata
            if metadata.get("checkpoint_kind") != "trajectory":
                raise ValueError(f"turn checkpoint {path} contains an unknown checkpoint kind")
            if manifest_digest is not None:
                found = metadata.get("run_manifest_digest")
                if found != manifest_digest:
                    raise ValueError(
                        f"turn checkpoint {path} contains manifest digest {found!r}; "
                        f"expected {manifest_digest!r}"
                    )
            sequence = metadata.get("checkpoint_sequence")
            if (
                isinstance(sequence, bool)
                or not isinstance(sequence, int)
                or sequence < 0
            ):
                raise ValueError(
                    f"turn checkpoint {path} has an invalid checkpoint sequence"
                )
            checkpoint = SUTCheckpoint(
                response=result.response,
                sequence=sequence,
                complete=metadata.get("checkpoint_complete") is True,
                tokens_in=_nonnegative_int(metadata.get("tokens_in")),
                tokens_out=_nonnegative_int(metadata.get("tokens_out")),
                cost=_nonnegative_float(metadata.get("cost")),
                provider_calls=_nonnegative_int(metadata.get("provider_calls")),
            )
            key = (result.id, result.trial)
            previous = latest.get(key)
            if previous is None or checkpoint.sequence >= previous.sequence:
                latest[key] = checkpoint
    return latest


def run(
    dataset: Dataset,
    *,
    model: str | ModelClient | SystemUnderTest,
    benchmark_name: str,
    config: RunnerConfig | None = None,
    on_progress: Callable[[RunResult], None] | None = None,
    manifest: RunManifest | None = None,
) -> tuple[list[RunResult], RunSummary]:
    """Run the dataset against the model. Returns all results + a summary.

    Resume semantics: existing successful results for (id, trial) pairs
    are loaded from disk and reused; only missing-or-errored pairs are
    actually called. Brand-new runs and resumed runs share the same code
    path.
    """
    cfg = config or RunnerConfig()
    if cfg.max_cost is not None and (
        isinstance(cfg.max_cost, bool)
        or not isinstance(cfg.max_cost, (int, float))
        or not math.isfinite(cfg.max_cost)
        or cfg.max_cost <= 0
    ):
        raise ValueError("runner max_cost must be a finite positive number or null")
    if not isinstance(cfg.require_known_cost, bool):
        raise ValueError("runner require_known_cost must be boolean")
    if (not isinstance(cfg.reserved_failure_types, tuple)
        or any(not isinstance(v, str) or not v.isidentifier() for v in cfg.reserved_failure_types)):
        raise ValueError("runner reserved_failure_types must be a tuple of exception type names")
    if cfg.max_cost_per_call is not None and (
        isinstance(cfg.max_cost_per_call, bool)
        or not isinstance(cfg.max_cost_per_call, (int, float))
        or not math.isfinite(cfg.max_cost_per_call)
        or cfg.max_cost_per_call <= 0
    ):
        raise ValueError(
            "runner max_cost_per_call must be a finite positive number or null"
        )
    if cfg.max_calls is not None and (
        isinstance(cfg.max_calls, bool)
        or not isinstance(cfg.max_calls, int)
        or cfg.max_calls < 1
    ):
        raise ValueError("runner max_calls must be a positive integer or null")
    sut = SystemUnderTest.resolve(model)
    model_id = sut.name

    manifest_digest: str | None = None
    if manifest is not None:
        if manifest.model != model_id:
            raise ValueError(
                f"run manifest model {manifest.model!r} does not match resolved model {model_id!r}"
            )
        if manifest.trials != cfg.trials:
            raise ValueError(
                f"run manifest trials {manifest.trials} do not match runner trials {cfg.trials}"
            )
        for name in (
            "temperature",
            "max_tokens",
            "threads",
            "max_retries",
            "retry_backoff",
            "max_cost_per_call",
            "require_known_cost",
            "reserved_failure_types",
        ):
            if name not in manifest.model_config:
                continue
            actual = getattr(cfg, name)
            declared = manifest.model_config.get(name)
            if declared != actual:
                raise ValueError(
                    f"run manifest model_config.{name} "
                    f"{declared!r} does not match runner {name} {actual!r}"
                )
        manifest_digest = manifest.digest

    out_path = raw_path(
        cfg,
        benchmark_name,
        model_id,
        manifest_digest=manifest_digest,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        _ensure_manifest_sidecar(out_path.parent / "run-manifest.json", manifest)

    from arisekit.accounted_runner import run_accounted
    return run_accounted(dataset, sut, cfg, out_path, manifest_digest, on_progress)


def _ensure_manifest_sidecar(path: Path, manifest: RunManifest) -> None:
    """Persist the manifest and reject a conflicting checkpoint namespace."""
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            existing = RunManifest.from_dict(payload)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid run manifest sidecar {path}: {exc}") from exc
        if existing.digest != manifest.digest:
            raise ValueError(
                f"run manifest sidecar {path} has digest {existing.digest}; "
                f"expected {manifest.digest}"
            )
        return

    try:
        with path.open("x", encoding="utf-8") as fh:
            json.dump(manifest.to_dict(), fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    except FileExistsError:
        # A concurrent process created the sidecar after the initial check.
        _ensure_manifest_sidecar(path, manifest)


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _nonnegative_float(value: object) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number) or number < 0:
        return 0.0
    return number
