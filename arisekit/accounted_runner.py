"""Runner execution with a shared journal at the model-dispatch boundary."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
import threading
import time
from typing import Any

from arisekit.dispatch import (
    DispatchLedger,
    DispatchStopped,
    active_dispatch,
    request_signature,
)
from arisekit.sut import SUTCheckpoint
from arisekit.durability import checkpoint_barrier
from arisekit.types import RunResult

log = logging.getLogger("arisekit.runner")


def run_accounted(
    dataset: Any,
    sut: Any,
    cfg: Any,
    out_path: Any,
    manifest_digest: Any,
    on_progress: Any,
) -> Any:
    from arisekit.runner import RunSummary, load_completed, load_turn_checkpoints

    existing = load_completed(out_path, manifest_digest=manifest_digest)
    turns_path = (
        out_path.with_suffix(".turns.jsonl") if sut.supports_turn_checkpoints else None
    )
    checkpoints = (
        load_turn_checkpoints(turns_path, manifest_digest=manifest_digest)
        if turns_path
        else {}
    )
    if sut.supports_turn_checkpoints and not getattr(
        sut, "supports_dispatch_accounting", False
    ):
        raise ValueError(
            "this SUT does not expose model dispatches for budget accounting"
        )
    if (
        sut.supports_turn_checkpoints
        and cfg.max_cost is not None
        and cfg.max_cost_per_call is None
        and sut.name != "stub/reference"
    ):
        raise ValueError(
            "agentic max_cost requires a reviewed max_cost_per_call reservation bound"
        )
    seeds = {}
    for key in set(existing) | set(checkpoints):
        metadata = existing[key].metadata if key in existing else {}
        checkpoint = checkpoints.get(key)
        seeds[key] = {
            "cost": max(
                metadata.get("cost", 0) or 0, checkpoint.cost if checkpoint else 0
            ),
            "provider_calls": max(
                metadata.get(
                    "provider_calls",
                    metadata.get(
                        "attempts",
                        1 if key in existing and existing[key].error is None else 0,
                    ),
                ),
                checkpoint.provider_calls if checkpoint else 0,
            ),
            "cost_unknown": metadata.get("cost_unknown") is True,
            "cost_bound_exceeded": metadata.get("cost_bound_exceeded") is True,
        }
    ledger = DispatchLedger(out_path.with_suffix(".calls.jsonl"), cfg, seeds,
        reserved_failure_types=frozenset(cfg.reserved_failure_types))
    lock = threading.Lock()
    files = {}
    barrier = checkpoint_barrier.get()

    def persist(path: Any, result: RunResult) -> None:
        encoded = json.dumps(result.to_dict(), ensure_ascii=False, allow_nan=False)
        with lock:
            handle = files.get(path)
            if handle is None:
                handle = files[path] = path.open("a", encoding="utf-8")
            handle.write(encoded + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            if barrier is not None:
                barrier()

    skipped = 0
    tasks = []
    for item in dataset:
        for trial in range(1, cfg.trials + 1):
            prev = existing.get((item.id, trial))
            if prev and (
                prev.error is None
                or prev.metadata.get("cost_unknown")
                or prev.metadata.get("cost_bound_exceeded")
            ):
                skipped += 1
            else:
                tasks.append((item, trial))

    def run_one(task: Any) -> RunResult:
        item, trial = task
        key = (item.id, trial)
        checkpoint = checkpoints.get(key)
        started = time.perf_counter()
        records = []
        produced = None
        error = None
        reason = None
        provider_error = None

        def save_turn(value: SUTCheckpoint) -> None:
            nonlocal checkpoint
            metadata = {
                "checkpoint_kind": "trajectory",
                "checkpoint_sequence": value.sequence,
                "checkpoint_complete": value.complete,
                "tokens_in": value.tokens_in,
                "tokens_out": value.tokens_out,
                "cost": value.cost,
                "provider_calls": value.provider_calls,
            }
            if manifest_digest:
                metadata["run_manifest_digest"] = manifest_digest
            persist(turns_path, RunResult(item.id, trial, value.response, metadata))
            checkpoint = value

        for attempt in range(1, cfg.max_retries + 1):
            before = time.perf_counter()
            terminal_resume = checkpoint is not None and checkpoint.complete
            token = active_dispatch.set(
                lambda signature, fn: ledger.invoke(key, signature, fn, agent=True)
            )
            try:

                def respond() -> Any:
                    return sut.respond_checkpointed(
                        item,
                        trial=trial,
                        resume_from=checkpoint,
                        on_checkpoint=save_turn,
                        system_prompt=dataset.system_prompt,
                        temperature=cfg.temperature,
                        max_tokens=cfg.max_tokens,
                    )

                if sut.supports_turn_checkpoints:
                    produced = respond()
                else:
                    signature = request_signature(
                        {
                            "item": item.to_dict(),
                            "system_prompt": dataset.system_prompt,
                            "temperature": cfg.temperature,
                            "max_tokens": cfg.max_tokens,
                        }
                    )
                    produced = ledger.invoke(key, signature, respond, agent=False)
                records.append(
                    {
                        "attempt": attempt,
                        "outcome": (
                            "resumed-complete" if terminal_resume else "succeeded"
                        ),
                        "latency_seconds": time.perf_counter() - before,
                    }
                )
                error = None
                break
            except DispatchStopped as exc:
                reason = exc.reason
                error = str(exc)
                provider_error = exc.__cause__
                if reason not in {"budget_exhausted", "call_budget_exhausted"}:
                    records.append(
                        {
                            "attempt": attempt,
                            "outcome": reason.replace("_", "-"),
                            "latency_seconds": time.perf_counter() - before,
                        }
                    )
                break
            except Exception as exc:
                error = str(exc)
                provider_error = exc
                records.append(
                    {
                        "attempt": attempt,
                        "outcome": "failed",
                        "latency_seconds": time.perf_counter() - before,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                if attempt < cfg.max_retries:
                    time.sleep(cfg.retry_backoff**attempt)
            finally:
                active_dispatch.reset(token)
        with ledger.lock:
            usage = ledger.usage(key)
        metadata = {
            "attempts": len(records),
            "attempt_records": records,
            "latency_seconds": time.perf_counter() - started,
            "cost": usage["cost"],
            "provider_calls": usage["provider_calls"],
            "cost_known": usage["cost_known"],
            "model": sut.name,
        }
        if checkpoint:
            metadata.update(
                tokens_in=checkpoint.tokens_in, tokens_out=checkpoint.tokens_out
            )
        if reason:
            metadata[reason] = True
            metadata["stop_reason"] = reason
            if reason == "cost_unknown":
                metadata["cost_known"] = False
                if usage["cost_reservation_consumed"]:
                    metadata["cost_reservation_consumed"] = True
            if reason == "cost_bound_exceeded":
                metadata["max_cost_per_call"] = cfg.max_cost_per_call
        if provider_error:
            metadata["provider_error_type"] = type(provider_error).__name__
        if manifest_digest:
            metadata["run_manifest_digest"] = manifest_digest
        if produced is not None:
            metadata.update(
                tokens_in=produced.tokens_in,
                tokens_out=produced.tokens_out,
                finish_reason=produced.finish_reason,
            )
            if produced.provider_model is not None:
                metadata["provider_model"] = produced.provider_model
            if produced.response_id is not None:
                metadata["provider_response_id"] = produced.response_id
        result = RunResult(
            item.id,
            trial,
            (
                produced.response
                if produced
                else checkpoint.response if checkpoint else None
            ),
            metadata,
            error or ("unknown error" if produced is None else None),
        )
        persist(out_path, result)
        if on_progress:
            try:
                on_progress(result)
            except Exception:
                log.exception("on_progress callback raised; continuing")
        return result

    try:
        if cfg.threads <= 1:
            results = [run_one(t) for t in tasks]
        else:
            with ThreadPoolExecutor(max_workers=cfg.threads) as pool:
                results = list(pool.map(run_one, tasks))
        merged = {(r.id, r.trial): r for r in results}
        for key, previous in existing.items():
            if key not in merged and (
                previous.error is None
                or previous.metadata.get("cost_unknown")
                or previous.metadata.get("cost_bound_exceeded")
            ):
                merged[key] = previous
        rows = list(merged.values())
        usage = ledger.usage()
        flags = {
            name: any(r.metadata.get(name) is True for r in rows)
            for name in (
                "budget_exhausted",
                "call_budget_exhausted",
                "cost_unknown",
                "cost_bound_exceeded",
            )
        }
        errors = sum(r.error is not None for r in rows)
        summary = RunSummary(
            completed=len(rows) - errors,
            errored=errors,
            skipped=skipped,
            cost_total=usage["cost"],
            output_path=out_path,
            manifest_digest=manifest_digest,
            calls_total=usage["provider_calls"],
            stop_reason=next(
                (
                    name
                    for name in (
                        "cost_unknown",
                        "cost_bound_exceeded",
                        "budget_exhausted",
                        "call_budget_exhausted",
                    )
                    if flags[name]
                ),
                None,
            ),
            **flags,
        )
        return rows, summary
    finally:
        for handle in files.values():
            handle.close()
        ledger.close()
