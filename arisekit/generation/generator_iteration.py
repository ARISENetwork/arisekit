"""Resumable development of generators, with separate measurement diagnostics.

Adapters own generation, evaluation and existing dispatch accounting. The outer
loop retains stage results and permits only declared strategy text to change.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from arisekit.generation.autonomous_generation import _run_lock, _write_same
from arisekit.generation.generator_metrics import profile_diagnostics


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _callback_identity(callback):
    path = inspect.getsourcefile(callback)
    if path is None:
        raise ValueError("Generator-loop callbacks require inspectable source")
    return {"name": callback.__module__ + "." + callback.__qualname__,
            "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def _stage(path, inputs, callback):
    identity = _digest(inputs)
    if path.is_symlink():
        raise ValueError("Generator stages cannot be symlinks")
    if path.exists():
        saved = json.loads(path.read_text())
        if saved["input_sha256"] != identity or saved["output_sha256"] != _digest(saved["output"]):
            raise ValueError("Retained generator stage differs from its frozen inputs or output")
        return saved["output"]
    path.parent.mkdir(parents=True, exist_ok=True)
    result = callback(json.loads(json.dumps(inputs, allow_nan=False)))
    if not isinstance(result, dict):
        raise ValueError("Generator-loop stages return JSON objects")
    _write_same(path, {"input_sha256": identity, "output_sha256": _digest(result), "output": result})
    return result


def run_generator_loop(
    plan: Mapping[str, Any], *, output_dir: str | Path,
    generate: Callable, evaluate: Callable, diagnose: Callable, improve: Callable,
) -> dict[str, Any]:
    """Run fresh development cycles; adapter clients enforce the shared budget.

    Each callback receives a JSON object containing cycle, specification,
    strategy and stage-specific retained observations. Interrupted callbacks
    must resume their paid work through the existing accounted runner.
    """
    if plan.get("mode") != "development":
        raise ValueError("Generator optimization accepts declared development material only")
    cycles = plan.get("cycles")
    strategy = plan.get("initial_strategy", [])
    if not isinstance(cycles, list) or not cycles or not isinstance(strategy, list) or any(not isinstance(s, str) for s in strategy):
        raise ValueError("Declare nonempty cycles and a list of strategy strings")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    frozen = {"specification": dict(plan), "callbacks": {name: _callback_identity(fn)
        for name, fn in (("generate", generate), ("evaluate", evaluate), ("diagnose", diagnose), ("improve", improve))},
        "controller_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "diagnostics_sha256": hashlib.sha256(Path(inspect.getsourcefile(profile_diagnostics)).read_bytes()).hexdigest()}
    with _run_lock(root):
        _write_same(root / "loop-plan.json", frozen)
        history = []
        for index, specification in enumerate(cycles, 1):
            directory = root / f"cycle-{index}"
            context = {"cycle": index, "specification": specification, "strategy": strategy}
            generated = _stage(directory / "generated.json", context, generate)
            evaluated = _stage(directory / "evaluated.json", {**context, "generated": generated}, evaluate)
            diagnosis = _stage(directory / "diagnosis.json", {**context, "generated": generated, "evaluated": evaluated}, diagnose)
            entry = {"cycle": index, "strategy": strategy, "generated": generated,
                     "evaluated": evaluated, "diagnosis": diagnosis}
            if index < len(cycles):
                revision = _stage(directory / "improvement.json", {**context, "diagnosis": diagnosis}, improve)
                if set(revision) != {"strategy"} or not isinstance(revision["strategy"], list) or any(not isinstance(s, str) for s in revision["strategy"]):
                    raise ValueError("An improvement may return only a list of strategy strings")
                strategy = revision["strategy"]
                entry["improvement"] = revision
            history.append(entry)
        report = {"mode": "development", "loop_plan_sha256": _digest(frozen), "cycles": history,
                  "generator_is_product": True, "evaluation_scope": "declared-development-material"}
        _write_same(root / "loop-report.json", report)
        return report


def kendall_tau_b(left: Sequence[float], right: Sequence[float]) -> float | None:
    """Return descriptive tau-b, preserving undefined tied profiles."""
    if len(left) != len(right):
        raise ValueError("Model profiles must use the same panel")
    if any(not math.isfinite(value) for value in (*left, *right)):
        raise ValueError("Model profiles require finite scores")
    concordant = discordant = left_ties = right_ties = 0
    for i in range(len(left)):
        for j in range(i):
            a, b = left[i] - left[j], right[i] - right[j]
            if a == 0 and b == 0:
                continue
            if a == 0:
                left_ties += 1
            elif b == 0:
                right_ties += 1
            elif a * b > 0:
                concordant += 1
            else:
                discordant += 1
    n = concordant + discordant
    denominator = math.sqrt((n + left_ties) * (n + right_ties))
    return (concordant - discordant) / denominator if denominator else None


def compare_model_profiles(
    records: Sequence[Mapping[str, Any]], *, models: Sequence[str],
    items: Sequence[str], trials: Sequence[int], reference: str, candidate: str,
    operational_failure_score: float = 0,
    rbo_persistence: float | None = None, top_k: int | None = None,
    agreement_tolerance: float | None = None, tdi_probability: float | None = None,
) -> dict[str, Any]:
    """Compare matched scores and report missing measurements separately.

    Records contain source/item/model/trial/score/error. A missing or errored
    outcome is excluded from measurement analysis. Only the explicitly labeled
    operational analysis assigns the declared failure score.
    """
    if not models or not items or not trials or len(set(models)) != len(models) or len(set(items)) != len(items) or len(set(trials)) != len(trials) or reference == candidate:
        raise ValueError("Declare distinct models, items, trials and source labels")
    if not math.isfinite(operational_failure_score):
        raise ValueError("The operational failure score must be finite")
    indexed = {}
    for row in records:
        key = (row["source"], row["item"], row["model"], row["trial"])
        if key in indexed:
            raise ValueError("Duplicate source/item/model/trial observation")
        if row["model"] not in models or row["item"] not in items or row["trial"] not in trials or row["source"] not in {reference, candidate}:
            raise ValueError("Observation lies outside the declared comparison grid")
        if row.get("score") is not None and (type(row["score"]) not in (int, float) or not math.isfinite(row["score"])):
            raise ValueError("Scores must be finite numbers or explicit missing values")
        indexed[key] = row
    units = [(item, trial) for item in items for trial in trials]
    def observed(source, item, model, trial):
        row = indexed.get((source, item, model, trial))
        return row is not None and not row.get("error") and row.get("score") is not None
    complete = [unit for unit in units if all(observed(source, unit[0], model, unit[1])
        for source in (reference, candidate) for model in models)]
    def profile(selected, operational):
        scores = {}
        for source in (reference, candidate):
            scores[source] = [sum(indexed[source, item, model, trial]["score"] if observed(source, item, model, trial)
                else operational_failure_score for item, trial in selected) / len(selected) for model in models] if selected else []
        a, b = scores[reference], scores[candidate]
        deltas = [y - x for x, y in zip(a, b)]
        pairwise = [{"models": [models[i], models[j]], "reference_gap": a[i] - a[j],
                     "candidate_gap": b[i] - b[j], "gap_shift": (b[i] - b[j]) - (a[i] - a[j])}
                    for i in range(len(models)) for j in range(i)] if selected else []
        return {"units": len(selected), "model_scores": scores, "score_shifts": deltas,
            "mean_absolute_score_shift": sum(abs(d) for d in deltas) / len(deltas) if deltas else None,
            "kendall_tau_b": kendall_tau_b(a, b) if a else None, "pairwise_model_gaps": pairwise,
            "operational_failure_score": operational_failure_score if operational else None,
            "additional_diagnostics": profile_diagnostics(a, b, rbo_persistence=rbo_persistence,
                top_k=top_k, agreement_tolerance=agreement_tolerance, tdi_probability=tdi_probability)}
    failures = [{"source": source, "item": item, "model": model, "trial": trial,
                 "error": indexed.get((source, item, model, trial), {}).get("error") or "missing measurement"}
        for source in (reference, candidate) for item, trial in units for model in models if not observed(source, item, model, trial)]
    return {"models": list(models), "assigned_units": len(units),
        "complete_common_units": [{"item": item, "trial": trial} for item, trial in complete],
        "measurement": profile(complete, False), "operational": profile(units, True),
        "unavailable_measurements": failures,
        "interpretation": "Development comparison; tau and calibration are separate, with no equivalence threshold."}
