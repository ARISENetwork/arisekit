"""Single-benchmark multi-model sweep orchestration.

This module deliberately does not compile suites or rank vendors.  It runs one
frozen benchmark against an ordered set of reviewed model routes, delegates
each model cell to :meth:`arisekit.benchmark.Benchmark.run`, and records a
descriptive, hash-bound receipt.
"""

from __future__ import annotations

import csv
import hashlib
import inspect
import io
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from arisekit.benchmark import Benchmark, BenchmarkScoringError, Results
from arisekit.common.files import atomic_directory
from arisekit.common.jsonio import canonical_json as _canonical_json, strict_json_object
from arisekit.common.records import CanonicalPropertyRecord
from arisekit.common.validate import (
    integer as _integer,
    nonnegative_int as _nonnegative_int,
    positive_int as _positive_int,
    sha256_hex as _sha256,
)
from arisekit.egress import ProviderDisclosureAuthorization
from arisekit.run_manifest import RunManifest
from arisekit.runner import model_slug


SWEEP_SPEC_SCHEMA_VERSION = "arisekit.benchmark-sweep.v1"
SWEEP_RESULTS_SCHEMA_VERSION = "arisekit.benchmark-sweep-results.v1"
SWEEP_SCORES_HEADER = (
    "benchmark",
    "model",
    "category",
    "metric",
    "n",
    "value",
    "ci",
)
SWEEP_CLAIM_BOUNDARY = (
    "These results describe this benchmark snapshot and the declared model "
    "routes only. They are not a vendor ranking, a clinical-performance "
    "claim, or a MAST-admission decision."
)


@dataclass(frozen=True)
class SweepModel:
    """One ordered model route in a single-benchmark sweep."""

    model: str
    provider: str
    trials: int

    def __post_init__(self) -> None:
        _single_line_text(self.model, "sweep model")
        _single_line_text(self.provider, "sweep provider")
        _positive_int(self.trials, "sweep trials")

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "trials": self.trials,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, index: int = 0) -> "SweepModel":
        _exact_fields(data, {"model", "provider", "trials"}, f"models[{index}]")
        return cls(
            model=data["model"],
            provider=data["provider"],
            trials=data["trials"],
        )


@dataclass(frozen=True)
class BenchmarkSweepSpec(CanonicalPropertyRecord):
    """Versioned execution contract for one benchmark and many model routes."""

    benchmark: str
    models: Sequence[SweepModel]
    allowed_model_routes: Sequence[str] | None = None
    threads: int = 1
    limit: int | None = None
    bootstrap: int = 0
    bootstrap_seed: int = 0
    max_cost: float | None = None
    max_calls: int | None = None
    cost_preview_digest: str | None = None
    schema_version: str = SWEEP_SPEC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SWEEP_SPEC_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {SWEEP_SPEC_SCHEMA_VERSION!r}"
            )
        _safe_benchmark_id(self.benchmark)
        models = tuple(self.models)
        if not models:
            raise ValueError("benchmark sweep requires at least one model")
        if any(not isinstance(model, SweepModel) for model in models):
            raise TypeError("models must contain SweepModel values")
        routes = tuple(model.model for model in models)
        if len(routes) != len(set(routes)):
            raise ValueError("benchmark sweep model routes must be unique")
        _positive_int(self.threads, "threads")
        if self.limit is not None:
            _positive_int(self.limit, "limit")
        _nonnegative_int(self.bootstrap, "bootstrap")
        _integer(self.bootstrap_seed, "bootstrap_seed")
        _positive_number_or_none(self.max_cost, "max_cost")
        if self.max_calls is not None:
            _positive_int(self.max_calls, "max_calls")
        if self.cost_preview_digest is not None:
            _sha256(self.cost_preview_digest, "cost_preview_digest")

        allowed: tuple[str, ...] | None = None
        if self.allowed_model_routes is not None:
            if isinstance(self.allowed_model_routes, (str, bytes)):
                raise TypeError("allowed_model_routes must be an array of routes")
            allowed = tuple(self.allowed_model_routes)
            if not allowed:
                raise ValueError("allowed_model_routes must not be empty")
            for route in allowed:
                _single_line_text(route, "allowed model route")
            if len(allowed) != len(set(allowed)):
                raise ValueError("allowed_model_routes must be unique")
            outside = sorted(set(routes) - set(allowed))
            if outside:
                raise ValueError(
                    "sweep models are outside allowed_model_routes: "
                    + ", ".join(outside)
                )

        object.__setattr__(self, "models", models)
        object.__setattr__(self, "allowed_model_routes", allowed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "benchmark": self.benchmark,
            "models": [model.to_dict() for model in self.models],
            "allowed_model_routes": (
                list(self.allowed_model_routes)
                if self.allowed_model_routes is not None
                else None
            ),
            "threads": self.threads,
            "limit": self.limit,
            "bootstrap": self.bootstrap,
            "bootstrap_seed": self.bootstrap_seed,
            "max_cost": self.max_cost,
            "max_calls": self.max_calls,
            "cost_preview_digest": self.cost_preview_digest,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkSweepSpec":
        fields = {
            "schema_version",
            "benchmark",
            "models",
            "allowed_model_routes",
            "threads",
            "limit",
            "bootstrap",
            "bootstrap_seed",
            "max_cost",
            "max_calls",
            "cost_preview_digest",
        }
        _exact_fields(data, fields, "benchmark sweep spec")
        raw_models = data["models"]
        if isinstance(raw_models, (str, bytes)) or not isinstance(raw_models, Sequence):
            raise ValueError("models must be an array")
        models: list[SweepModel] = []
        for index, value in enumerate(raw_models):
            if not isinstance(value, Mapping):
                raise ValueError(f"models[{index}] must be an object")
            models.append(SweepModel.from_dict(value, index=index))
        allowed = data["allowed_model_routes"]
        if allowed is not None and (
            isinstance(allowed, (str, bytes)) or not isinstance(allowed, Sequence)
        ):
            raise ValueError("allowed_model_routes must be an array or null")
        return cls(
            schema_version=data["schema_version"],
            benchmark=data["benchmark"],
            models=models,
            allowed_model_routes=allowed,
            threads=data["threads"],
            limit=data["limit"],
            bootstrap=data["bootstrap"],
            bootstrap_seed=data["bootstrap_seed"],
            max_cost=data["max_cost"],
            max_calls=data["max_calls"],
            cost_preview_digest=data["cost_preview_digest"],
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "BenchmarkSweepSpec":
        source = Path(path)
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"sweep spec must be a regular file: {source}")
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"cannot load sweep spec {source}: {exc}") from exc
        return cls.from_dict(strict_json_object(text, f"sweep spec {source}"))


class SweepCellStatus(str, Enum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_RUN = "not-run"


@dataclass(frozen=True)
class SweepArtifact:
    path: str
    sha256: str
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}


@dataclass(frozen=True)
class SweepCellResult:
    """One isolated model cell and its bound run artifacts."""

    model: str
    provider: str
    trials: int
    status: SweepCellStatus
    completed: int = 0
    errored: int = 0
    cost: float = 0.0
    calls_total: int = 0
    cost_unknown: bool = False
    run_manifest_digest: str | None = None
    raw_checkpoint: SweepArtifact | None = None
    run_manifest: SweepArtifact | None = None
    scores: SweepArtifact | None = None
    error: str | None = None
    results: Results | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "trials": self.trials,
            "status": self.status.value,
            "completed": self.completed,
            "errored": self.errored,
            "cost": self.cost,
            "calls_total": self.calls_total,
            "cost_unknown": self.cost_unknown,
            "run_manifest_digest": self.run_manifest_digest,
            "raw_checkpoint": (
                self.raw_checkpoint.to_dict() if self.raw_checkpoint else None
            ),
            "run_manifest": self.run_manifest.to_dict() if self.run_manifest else None,
            "scores": self.scores.to_dict() if self.scores else None,
            "error": self.error,
        }


@dataclass(frozen=True)
class BenchmarkSweepResults:
    """Completed descriptive sweep plus its persisted artifact locations."""

    spec: BenchmarkSweepSpec
    cells: tuple[SweepCellResult, ...]
    execution_digest: str
    spec_path: Path
    receipt_path: Path
    scores_path: Path
    report_path: Path
    artifacts: Mapping[str, SweepArtifact]

    @property
    def succeeded(self) -> int:
        return sum(cell.status is SweepCellStatus.SUCCEEDED for cell in self.cells)

    @property
    def partial(self) -> int:
        return sum(cell.status is SweepCellStatus.PARTIAL for cell in self.cells)

    @property
    def failed(self) -> int:
        return sum(cell.status is SweepCellStatus.FAILED for cell in self.cells)

    @property
    def not_run(self) -> int:
        return sum(cell.status is SweepCellStatus.NOT_RUN for cell in self.cells)

    @property
    def cost(self) -> float:
        return sum(cell.cost for cell in self.cells)

    @property
    def calls_total(self) -> int:
        return sum(cell.calls_total for cell in self.cells)

    @property
    def complete(self) -> bool:
        return self.succeeded == len(self.cells)


def sweep_spec_from_package(
    package: Any,
    *,
    models: Sequence[str] | None = None,
    threads: int | None = None,
    limit: int | None = None,
    bootstrap: int = 0,
    bootstrap_seed: int = 0,
    max_cost: float | None = None,
    max_calls: int | None = None,
    cost_preview_digest: str | None = None,
) -> BenchmarkSweepSpec:
    """Build a sweep spec from a scaffolded package's reviewed first sweep.

    ``models`` may only select and reorder routes already present in the
    package. It cannot expand the package execution allowlist.
    """

    manifest = getattr(package, "manifest", None)
    if manifest is None:
        raise TypeError("package must expose a benchmark manifest")
    provenance = getattr(manifest, "provenance", None)
    if not isinstance(provenance, Mapping):
        raise ValueError("package manifest provenance must be an object")
    raw_sweep = provenance.get("first_sweep")
    if not isinstance(raw_sweep, list) or not raw_sweep:
        raise ValueError("package provenance requires a non-empty first_sweep")
    planned: dict[str, SweepModel] = {}
    planned_order: list[str] = []
    for index, value in enumerate(raw_sweep):
        if not isinstance(value, Mapping):
            raise ValueError(f"first_sweep[{index}] must be an object")
        model = SweepModel.from_dict(value, index=index)
        if model.model in planned:
            raise ValueError("package first_sweep contains duplicate model routes")
        planned[model.model] = model
        planned_order.append(model.model)

    readiness = provenance.get("readiness")
    if not isinstance(readiness, Mapping):
        raise ValueError("package provenance readiness must be an object")
    raw_allowed = readiness.get("allowed_model_routes")
    if not isinstance(raw_allowed, list) or not raw_allowed:
        raise ValueError("package readiness.allowed_model_routes must be non-empty")
    allowed = tuple(raw_allowed)
    for route in allowed:
        _single_line_text(route, "package allowed model route")
    if len(allowed) != len(set(allowed)):
        raise ValueError("package allowed_model_routes contains duplicates")
    if set(planned) != set(allowed):
        raise ValueError(
            "package first_sweep must exactly cover allowed_model_routes"
        )

    if models is None:
        selected_routes = planned_order
    else:
        if isinstance(models, (str, bytes)):
            raise TypeError("models must be an array of model routes")
        selected_routes = list(models)
        if not selected_routes:
            raise ValueError("selected models must not be empty")
        for route in selected_routes:
            _single_line_text(route, "selected model route")
        if len(selected_routes) != len(set(selected_routes)):
            raise ValueError("selected model routes must be unique")
        outside = sorted(set(selected_routes) - set(planned))
        if outside:
            raise ValueError(
                "selected models are outside the reviewed first_sweep: "
                + ", ".join(outside)
            )

    runner = provenance.get("runner")
    if threads is None:
        if not isinstance(runner, Mapping):
            raise ValueError("package provenance runner must be an object")
        threads = runner.get("threads")
        _positive_int(threads, "package runner.threads")

    return BenchmarkSweepSpec(
        benchmark=getattr(manifest, "id", None),
        models=tuple(planned[route] for route in selected_routes),
        allowed_model_routes=allowed,
        threads=threads,
        limit=limit,
        bootstrap=bootstrap,
        bootstrap_seed=bootstrap_seed,
        max_cost=max_cost,
        max_calls=max_calls,
        cost_preview_digest=cost_preview_digest,
    )


def run_benchmark_sweep(
    benchmark: Benchmark,
    spec: BenchmarkSweepSpec,
    *,
    results_dir: str | Path = "results",
    provider_authorizations: Mapping[
        str, ProviderDisclosureAuthorization
    ] | None = None,
) -> BenchmarkSweepResults:
    """Run one benchmark across the exact ordered model routes in ``spec``.

    Model cells are sequential. Each cell delegates item concurrency, retry,
    checkpointing, and resume to ``Benchmark.run``. Failures are isolated to a
    cell unless spend can no longer be accounted conservatively.
    """

    if not isinstance(benchmark, Benchmark):
        raise TypeError("benchmark must be an arisekit.Benchmark")
    if not isinstance(spec, BenchmarkSweepSpec):
        raise TypeError("spec must be a BenchmarkSweepSpec")
    if benchmark.name != spec.benchmark:
        raise ValueError(
            f"sweep benchmark {spec.benchmark!r} does not match {benchmark.name!r}"
        )

    _validate_route_subset(benchmark, spec)
    authorizations = _validate_provider_authorizations(
        benchmark,
        spec,
        provider_authorizations,
    )
    root = Path(results_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    cells: list[SweepCellResult] = []
    accounted_cost = 0.0
    accounted_calls = 0
    stop_reason: str | None = None

    for planned in spec.models:
        if stop_reason is not None:
            cells.append(
                SweepCellResult(
                    model=planned.model,
                    provider=planned.provider,
                    trials=planned.trials,
                    status=SweepCellStatus.NOT_RUN,
                    error=stop_reason,
                )
            )
            continue

        remaining_cost = (
            None if spec.max_cost is None else spec.max_cost - accounted_cost
        )
        remaining_calls = (
            None if spec.max_calls is None else spec.max_calls - accounted_calls
        )
        if remaining_cost is not None and remaining_cost <= 0:
            stop_reason = "sweep cost budget exhausted before model cell"
            cells.append(
                SweepCellResult(
                    model=planned.model,
                    provider=planned.provider,
                    trials=planned.trials,
                    status=SweepCellStatus.NOT_RUN,
                    error=stop_reason,
                )
            )
            continue
        if remaining_calls is not None and remaining_calls <= 0:
            stop_reason = "sweep model-call budget exhausted before model cell"
            cells.append(
                SweepCellResult(
                    model=planned.model,
                    provider=planned.provider,
                    trials=planned.trials,
                    status=SweepCellStatus.NOT_RUN,
                    error=stop_reason,
                )
            )
            continue

        result: Results | None = None
        try:
            run_options: dict[str, Any] = {
                "trials": planned.trials,
                "threads": spec.threads,
                "limit": spec.limit,
                "results_dir": root,
                "auto_manifest": True,
                "bootstrap": spec.bootstrap,
                "max_cost": _cell_cost_budget(benchmark, remaining_cost),
                "max_calls": _cell_call_budget(benchmark, remaining_calls),
                "provider_authorization": authorizations.get(planned.model),
            }
            if _supports_keyword(benchmark.run, "bootstrap_seed"):
                run_options["bootstrap_seed"] = spec.bootstrap_seed
            result = benchmark.run(planned.model, **run_options)
            cell = _completed_cell(root, planned, result)
            accounted_cost += cell.cost
            accounted_calls += cell.calls_total
            if cell.cost_unknown and _unknown_cost_blocks_sweep(
                benchmark, spec, result.summary, result.raw
            ):
                stop_reason = (
                    "remaining model cells were not run because provider cost "
                    "could not be accounted"
                )
            elif spec.max_cost is not None and (
                accounted_cost >= spec.max_cost
                or result.summary.budget_exhausted
                or result.summary.cost_bound_exceeded
            ):
                stop_reason = "remaining model cells were not run after cost exhaustion"
            elif spec.max_calls is not None and (
                accounted_calls >= spec.max_calls
                or result.summary.call_budget_exhausted
            ):
                stop_reason = (
                    "remaining model cells were not run after model-call exhaustion"
                )
        except BenchmarkScoringError as exc:
            cell = _scoring_failed_cell(root, planned, exc)
            accounted_cost += cell.cost
            accounted_calls += cell.calls_total
            if cell.cost_unknown and _unknown_cost_blocks_sweep(
                benchmark, spec, exc.summary, exc.raw
            ):
                stop_reason = (
                    "remaining model cells were not run because provider cost "
                    "could not be accounted"
                )
            elif spec.max_cost is not None and (
                accounted_cost >= spec.max_cost
                or exc.summary.budget_exhausted
                or exc.summary.cost_bound_exceeded
            ):
                stop_reason = "remaining model cells were not run after cost exhaustion"
            elif spec.max_calls is not None and (
                accounted_calls >= spec.max_calls
                or exc.summary.call_budget_exhausted
            ):
                stop_reason = (
                    "remaining model cells were not run after model-call exhaustion"
                )
        except Exception as exc:  # noqa: BLE001 - cell isolation is the contract
            cell = SweepCellResult(
                model=planned.model,
                provider=planned.provider,
                trials=planned.trials,
                status=SweepCellStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
                results=result,
            )
            if spec.max_cost is not None or spec.max_calls is not None:
                stop_reason = (
                    "remaining model cells were not run because a failed cell "
                    "did not return complete spend accounting"
                )
        cells.append(cell)

    return _write_sweep_artifacts(root, spec, tuple(cells))


def _unknown_cost_blocks_sweep(benchmark, spec, summary, responses) -> bool:
    # Unbudgeted provider errors keep cell isolation; strict budgets and
    # returned responses with unknown charges still stop later paid work.
    return (
        spec.max_cost is not None
        or benchmark.runner_config.max_cost is not None
        or benchmark.runner_config.require_known_cost
        or benchmark.runner_config.max_cost_per_call is not None
        or summary.cost_unknown
        or any(row.error is None and row.metadata.get("cost_known") is False for row in responses)
    )


def _validate_route_subset(benchmark: Benchmark, spec: BenchmarkSweepSpec) -> None:
    selected = {model.model for model in spec.models}
    benchmark_routes = benchmark.allowed_model_routes
    if benchmark_routes is not None:
        outside = sorted(selected - set(benchmark_routes))
        if outside:
            raise ValueError(
                "sweep models are outside the benchmark's reviewed allowlist: "
                + ", ".join(outside)
            )
        if spec.allowed_model_routes is not None:
            expanded = sorted(set(spec.allowed_model_routes) - set(benchmark_routes))
            if expanded:
                raise ValueError(
                    "sweep allowed_model_routes expand the benchmark allowlist: "
                    + ", ".join(expanded)
                )


def _validate_provider_authorizations(
    benchmark: Benchmark,
    spec: BenchmarkSweepSpec,
    values: Mapping[str, ProviderDisclosureAuthorization] | None,
) -> Mapping[str, ProviderDisclosureAuthorization]:
    authorizations = dict(values or {})
    selected = {model.model for model in spec.models}
    extras = sorted(set(authorizations) - selected)
    if extras:
        raise ValueError(
            "provider authorizations include unselected model routes: "
            + ", ".join(extras)
        )
    requirement = benchmark.provider_disclosure_requirement
    if requirement is None:
        if authorizations:
            raise ValueError(
                "provider authorizations were supplied for a public benchmark"
            )
        return MappingProxyType({})

    for planned in spec.models:
        expected_provider = requirement.provider_for_route(planned.model)
        if planned.provider != expected_provider:
            raise ValueError(
                f"sweep provider {planned.provider!r} for {planned.model!r} does "
                f"not match the package provider {expected_provider!r}"
            )
        requirement.validate_authorization(
            model_route=planned.model,
            authorization=authorizations.get(planned.model),
        )
    return MappingProxyType(authorizations)


def _cell_cost_budget(benchmark: Benchmark, remaining: float | None) -> float | None:
    configured = benchmark.runner_config.max_cost
    if remaining is None:
        return configured
    return remaining if configured is None else min(remaining, configured)


def _cell_call_budget(benchmark: Benchmark, remaining: int | None) -> int | None:
    configured = benchmark.runner_config.max_calls
    if remaining is None:
        return configured
    return remaining if configured is None else min(remaining, configured)


def _completed_cell(
    root: Path,
    planned: SweepModel,
    result: Results,
) -> SweepCellResult:
    digest = result.summary.manifest_digest
    if digest is None:
        raise ValueError("sweep model cell did not produce a run manifest")
    raw_path = Path(result.summary.output_path).resolve()
    manifest_path = raw_path.parent / "run-manifest.json"
    manifest_artifact = _manifest_artifact(root, manifest_path, digest)
    score_path = (
        root
        / "scores"
        / result.benchmark
        / digest
        / f"{model_slug(result.model)}.csv"
    )
    cost_unknown = result.summary.cost_unknown or any(
        response.metadata.get("cost_known") is False for response in result.raw
    )
    if result.summary.errored == 0:
        status = SweepCellStatus.SUCCEEDED
    elif result.summary.completed > 0:
        status = SweepCellStatus.PARTIAL
    else:
        status = SweepCellStatus.FAILED
    return SweepCellResult(
        model=planned.model,
        provider=planned.provider,
        trials=planned.trials,
        status=status,
        completed=result.summary.completed,
        errored=result.summary.errored,
        cost=result.cost,
        calls_total=result.summary.calls_total,
        cost_unknown=cost_unknown,
        run_manifest_digest=digest,
        raw_checkpoint=_artifact(root, raw_path),
        run_manifest=manifest_artifact,
        scores=_artifact(root, score_path),
        results=result,
    )


def _scoring_failed_cell(
    root: Path,
    planned: SweepModel,
    error: BenchmarkScoringError,
) -> SweepCellResult:
    digest = error.summary.manifest_digest
    if digest is None:
        raise ValueError("failed scoring cell did not produce a run manifest")
    raw_path = Path(error.summary.output_path).resolve()
    manifest_path = raw_path.parent / "run-manifest.json"
    cost_unknown = error.summary.cost_unknown or any(
        response.metadata.get("cost_known") is False
        or response.metadata.get("cost_unknown") is True
        for response in error.raw
    )
    return SweepCellResult(
        model=planned.model,
        provider=planned.provider,
        trials=planned.trials,
        status=SweepCellStatus.FAILED,
        completed=error.summary.completed,
        errored=error.summary.errored,
        cost=error.summary.cost_total,
        calls_total=error.summary.calls_total,
        cost_unknown=cost_unknown,
        run_manifest_digest=digest,
        raw_checkpoint=_artifact(root, raw_path),
        run_manifest=_manifest_artifact(root, manifest_path, digest),
        error=f"{type(error).__name__}: {error}",
    )


def _manifest_artifact(root: Path, path: Path, expected_digest: str) -> SweepArtifact:
    artifact = _artifact(root, path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest = RunManifest.from_dict(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid run manifest artifact {path}: {exc}") from exc
    if manifest.digest != expected_digest:
        raise ValueError(
            f"run manifest artifact digest {manifest.digest} does not match "
            f"cell digest {expected_digest}"
        )
    return artifact


def _write_sweep_artifacts(
    root: Path,
    spec: BenchmarkSweepSpec,
    cells: tuple[SweepCellResult, ...],
) -> BenchmarkSweepResults:
    core = {
        "schema_version": SWEEP_RESULTS_SCHEMA_VERSION,
        "sweep_spec_sha256": spec.digest,
        "cells": [cell.to_dict() for cell in cells],
    }
    execution_digest = hashlib.sha256(
        _canonical_json(core).encode("utf-8")
    ).hexdigest()
    destination = (
        root
        / "sweeps"
        / _path_slug(spec.benchmark)
        / spec.digest
        / execution_digest
    )
    spec_path = destination / "sweep-spec.json"
    scores_path = destination / "sweep-scores.csv"
    report_path = destination / "sweep-results.md"
    receipt_path = destination / "sweep-results.json"

    spec_bytes = (spec.canonical_json + "\n").encode("utf-8")
    score_bytes = _render_scores(cells)
    report_bytes = _render_report(spec, cells, execution_digest).encode("utf-8")
    generated = {
        "sweep_spec": _artifact_for_bytes(root, spec_path, spec_bytes),
        "sweep_scores": _artifact_for_bytes(root, scores_path, score_bytes),
        "sweep_report": _artifact_for_bytes(root, report_path, report_bytes),
    }
    receipt = {
        **core,
        "execution_digest": execution_digest,
        "benchmark": spec.benchmark,
        "complete": all(
            cell.status is SweepCellStatus.SUCCEEDED for cell in cells
        ),
        "summary": {
            "succeeded": sum(
                cell.status is SweepCellStatus.SUCCEEDED for cell in cells
            ),
            "partial": sum(
                cell.status is SweepCellStatus.PARTIAL for cell in cells
            ),
            "failed": sum(
                cell.status is SweepCellStatus.FAILED for cell in cells
            ),
            "not_run": sum(
                cell.status is SweepCellStatus.NOT_RUN for cell in cells
            ),
            "cost_total": sum(cell.cost for cell in cells),
            "calls_total": sum(cell.calls_total for cell in cells),
            "cost_unknown": any(cell.cost_unknown for cell in cells),
        },
        "artifacts": {name: value.to_dict() for name, value in generated.items()},
        "claim_boundary": SWEEP_CLAIM_BOUNDARY,
    }
    receipt_bytes = (_canonical_json(receipt) + "\n").encode("utf-8")
    _atomic_directory(
        destination,
        {
            spec_path.name: spec_bytes,
            scores_path.name: score_bytes,
            report_path.name: report_bytes,
            receipt_path.name: receipt_bytes,
        },
    )
    return BenchmarkSweepResults(
        spec=spec,
        cells=cells,
        execution_digest=execution_digest,
        spec_path=spec_path,
        receipt_path=receipt_path,
        scores_path=scores_path,
        report_path=report_path,
        artifacts=MappingProxyType(generated),
    )


def _render_scores(cells: tuple[SweepCellResult, ...]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(SWEEP_SCORES_HEADER)
    for cell in cells:
        if cell.results is None:
            continue
        for metric in cell.results.metrics:
            writer.writerow(
                [
                    cell.results.benchmark,
                    cell.results.model,
                    metric.category,
                    metric.name,
                    metric.n if metric.n is not None else "",
                    f"{metric.value:.6f}",
                    f"{metric.ci:.6f}" if metric.ci is not None else "",
                ]
            )
    return buffer.getvalue().encode("utf-8")


def _render_report(
    spec: BenchmarkSweepSpec,
    cells: tuple[SweepCellResult, ...],
    execution_digest: str,
) -> str:
    lines = [
        "# Benchmark sweep results",
        "",
        f"- Benchmark: `{spec.benchmark}`",
        f"- Sweep specification: `{spec.digest}`",
        f"- Execution: `{execution_digest}`",
        f"- Recorded cost: {sum(cell.cost for cell in cells):.6f}",
        f"- Recorded model calls: {sum(cell.calls_total for cell in cells)}",
        "",
        "| Model route | Provider | Trials | Status | Completed | Errors | Cost |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: |",
    ]
    for cell in cells:
        lines.append(
            f"| {_markdown(cell.model)} | {_markdown(cell.provider)} | "
            f"{cell.trials} | {cell.status.value} | {cell.completed} | "
            f"{cell.errored} | {cell.cost:.6f} |"
        )
    lines.extend(
        [
            "",
            "## Metrics",
            "",
            "| Model | Category | Metric | N | Value | CI |",
            "| --- | --- | --- | ---: | ---: | ---: |",
        ]
    )
    for cell in cells:
        if cell.results is None:
            continue
        for metric in cell.results.metrics:
            n = "" if metric.n is None else str(metric.n)
            ci = "" if metric.ci is None else f"{metric.ci:.6f}"
            lines.append(
                f"| {_markdown(cell.results.model)} | {_markdown(metric.category)} | "
                f"{_markdown(metric.name)} | {n} | {metric.value:.6f} | {ci} |"
            )
    lines.extend(["", SWEEP_CLAIM_BOUNDARY, ""])
    return "\n".join(lines)


def _artifact(root: Path, path: Path) -> SweepArtifact:
    candidate = path.resolve()
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"sweep artifact is outside results root: {path}") from exc
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise ValueError(f"sweep artifact path is unsafe: {relative}")
    if path.is_symlink() or not candidate.is_file():
        raise ValueError(f"sweep artifact is missing or unsafe: {relative}")
    payload = candidate.read_bytes()
    return SweepArtifact(
        path=relative,
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
    )


def _artifact_for_bytes(root: Path, path: Path, payload: bytes) -> SweepArtifact:
    try:
        relative = path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"sweep artifact is outside results root: {path}") from exc
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise ValueError(f"sweep artifact path is unsafe: {relative}")
    return SweepArtifact(
        path=relative,
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
    )


def _atomic_directory(destination: Path, files: Mapping[str, bytes]) -> None:
    """Publish a complete immutable sweep directory in one rename."""
    atomic_directory(destination, files, _verify_existing_directory, symlink_counts_as_existing=True)


def _verify_existing_directory(
    destination: Path,
    files: Mapping[str, bytes],
) -> None:
    if destination.is_symlink() or not destination.is_dir():
        raise ValueError("sweep destination is not a safe directory")
    entries = {path.name: path for path in destination.iterdir()}
    if set(entries) != set(files):
        raise ValueError("existing sweep directory has a different file inventory")
    for name, expected in files.items():
        path = entries[name]
        if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
            raise ValueError(
                "existing sweep directory bytes do not match its content identity"
            )


def _exact_fields(
    data: Mapping[str, Any], expected: set[str], label: str
) -> None:
    missing = expected - set(data)
    unknown = set(data) - expected
    if missing or unknown:
        raise ValueError(
            f"invalid {label} fields; missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )


def _safe_benchmark_id(value: Any) -> str:
    text = _single_line_text(value, "benchmark")
    if text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError("benchmark must be a path-safe identifier")
    return text


def _single_line_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    if any(character in value for character in ("\r", "\n", "\x00")):
        raise ValueError(f"{label} must be single-line text")
    return value


def _supports_keyword(callable_value: Any, keyword: str) -> bool:
    parameters = inspect.signature(callable_value).parameters.values()
    return any(
        parameter.name == keyword
        or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )


def _positive_number_or_none(value: Any, label: str) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{label} must be a finite positive number or null")


def _path_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return slug[:80] or "benchmark"


def _markdown(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


__all__ = [
    "BenchmarkSweepResults",
    "BenchmarkSweepSpec",
    "SWEEP_CLAIM_BOUNDARY",
    "SWEEP_RESULTS_SCHEMA_VERSION",
    "SWEEP_SCORES_HEADER",
    "SWEEP_SPEC_SCHEMA_VERSION",
    "SweepArtifact",
    "SweepCellResult",
    "SweepCellStatus",
    "SweepModel",
    "run_benchmark_sweep",
    "sweep_spec_from_package",
]
