"""Multi-arm, multi-model benchmark campaign orchestration.

A campaign is the Cartesian product of benchmark arms and systems under test.
Every cell gets its own results directory, then delegates execution to
``Benchmark.run``. This preserves the runner's append-only checkpoint and
resume behavior without allowing two arms with the same benchmark name (or
two systems with the same runtime name) to share a checkpoint.

Campaigns are intentionally sequential at the cell level. ``Benchmark.run``
already owns item-level parallelism, and scorers are not required to be safe
for concurrent use across cells.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from arisekit.benchmark import Benchmark, Results
from arisekit.client import ModelClient
from arisekit.common.jsonio import freeze_json as _freeze_json
from arisekit.sut import SystemUnderTest


ModelSpec = str | ModelClient | SystemUnderTest


@dataclass(frozen=True)
class CampaignArm:
    """One benchmark arm in an experiment."""

    id: str
    benchmark: Benchmark = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_id("arm", self.id)


@dataclass(frozen=True)
class CampaignModel:
    """One explicitly labelled system under test.

    ``id`` is the stable experiment label. It is deliberately separate from
    the runtime SUT name, which may be shared by custom clients.
    """

    id: str
    system: ModelSpec = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_id("model", self.id)


@dataclass(frozen=True)
class CampaignCell:
    """The immutable execution plan for one arm-model pair."""

    id: str
    campaign_id: str
    arm: CampaignArm = field(repr=False, compare=False)
    model: CampaignModel = field(repr=False, compare=False)
    system: SystemUnderTest = field(repr=False, compare=False)
    trials: int
    selection: Mapping[str, Any] = field(repr=False, compare=False)
    results_dir: Path

    @property
    def arm_id(self) -> str:
        return self.arm.id

    @property
    def model_id(self) -> str:
        return self.model.id


# The manifest object remains structurally typed here so campaign orchestration
# does not import a particular manifest schema. A factory constructs the
# versioned RunManifest for each cell from its resolved SUT, arm, trial count,
# and selection. Benchmark.run owns its complete schema validation and storage.
RunManifestFactory = Callable[[CampaignCell], object]
CellResultValidator = Callable[[CampaignCell, Results], None]


@dataclass(frozen=True)
class CampaignSpec:
    """A complete, reproducible arm-by-model execution specification."""

    id: str
    arms: Sequence[CampaignArm]
    models: Sequence[CampaignModel]
    trials: int = 1
    threads: int = 1
    limit: int | None = None
    bootstrap: int = 0
    max_cost: float | None = None
    max_calls: int | None = None
    execution_order: str = "arm-major"
    order_seed: int | None = None
    stop_on_failure: bool = False
    results_dir: Path = field(default_factory=lambda: Path("results"))
    selection: Mapping[str, Any] = field(default_factory=dict)
    run_manifest_factory: RunManifestFactory | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    cell_result_validator: CellResultValidator | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _validate_id("campaign", self.id)
        arms = tuple(self.arms)
        models = tuple(self.models)
        if not arms:
            raise ValueError("campaign requires at least one arm")
        if not models:
            raise ValueError("campaign requires at least one model")
        _require_unique("arm", [arm.id for arm in arms])
        _require_unique("model", [model.id for model in models])
        if self.trials < 1:
            raise ValueError("trials must be at least 1")
        if self.threads < 1:
            raise ValueError("threads must be at least 1")
        if self.limit is not None and self.limit < 1:
            raise ValueError("limit must be at least 1 when provided")
        if self.bootstrap < 0:
            raise ValueError("bootstrap cannot be negative")
        if self.max_cost is not None and (
            isinstance(self.max_cost, bool)
            or not isinstance(self.max_cost, (int, float))
            or not math.isfinite(self.max_cost)
            or self.max_cost <= 0
        ):
            raise ValueError("max_cost must be a finite positive number or null")
        if self.max_calls is not None and (
            isinstance(self.max_calls, bool)
            or not isinstance(self.max_calls, int)
            or self.max_calls < 1
        ):
            raise ValueError("max_calls must be a positive integer or null")
        if self.execution_order not in {"arm-major", "model-interleaved"}:
            raise ValueError("execution_order must be arm-major or model-interleaved")
        if self.order_seed is not None and (
            isinstance(self.order_seed, bool) or not isinstance(self.order_seed, int)
        ):
            raise ValueError("order_seed must be an integer or null")
        if self.execution_order == "model-interleaved" and self.order_seed is None:
            raise ValueError("model-interleaved execution requires order_seed")
        if not isinstance(self.stop_on_failure, bool):
            raise ValueError("stop_on_failure must be boolean")
        if (
            self.cell_result_validator is not None
            and not callable(self.cell_result_validator)
        ):
            raise ValueError("cell_result_validator must be callable or null")

        selection = dict(self.selection)
        if self.limit is not None:
            selected_limit = selection.get("limit", self.limit)
            if selected_limit != self.limit:
                raise ValueError("selection['limit'] must match limit")
            selection["limit"] = self.limit

        object.__setattr__(self, "arms", arms)
        object.__setattr__(self, "models", models)
        object.__setattr__(self, "results_dir", Path(self.results_dir))
        object.__setattr__(self, "selection", _freeze_json(selection, "selection"))

    @property
    def cell_count(self) -> int:
        return len(self.arms) * len(self.models)

    def cells(self) -> tuple[CampaignCell, ...]:
        """Return cells in the declared, deterministic execution order."""
        campaign_dir = self.results_dir / "campaigns" / _path_id("campaign", self.id)
        cells: list[CampaignCell] = []
        coordinates: list[tuple[CampaignArm, CampaignModel]] = []
        if self.execution_order == "arm-major":
            coordinates = [
                (arm, model) for arm in self.arms for model in self.models
            ]
        else:
            rng = random.Random(self.order_seed)
            models = list(self.models)
            rng.shuffle(models)
            first_arms = list(self.arms)
            rng.shuffle(first_arms)
            for index, model in enumerate(models):
                arms = first_arms if index % 2 == 0 else list(reversed(first_arms))
                coordinates.extend((arm, model) for arm in arms)

        for arm, model in coordinates:
            cell_id = campaign_cell_id(self.id, arm.id, model.id)
            cells.append(
                CampaignCell(
                    id=cell_id,
                    campaign_id=self.id,
                    arm=arm,
                    model=model,
                    system=SystemUnderTest.resolve(model.system),
                    trials=self.trials,
                    selection=self.selection,
                    results_dir=campaign_dir / "cells" / cell_id,
                )
            )
        return tuple(cells)


class CellStatus(str, Enum):
    """Outcome of one campaign cell."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class CampaignCellResult:
    """Execution outcome for one campaign cell."""

    cell: CampaignCell
    status: CellStatus
    results: Results | None = field(default=None, repr=False, compare=False)
    error: str | None = None
    manifest_digest: str | None = None

    @property
    def arm_id(self) -> str:
        return self.cell.arm_id

    @property
    def model_id(self) -> str:
        return self.cell.model_id


@dataclass(frozen=True)
class CampaignResult:
    """The complete arm-by-model matrix, including failed cells."""

    spec: CampaignSpec = field(repr=False, compare=False)
    matrix: Mapping[str, Mapping[str, CampaignCellResult]]

    def cell(self, arm_id: str, model_id: str) -> CampaignCellResult:
        return self.matrix[arm_id][model_id]

    @property
    def cells(self) -> tuple[CampaignCellResult, ...]:
        return tuple(
            self.matrix[arm.id][model.id]
            for arm in self.spec.arms
            for model in self.spec.models
        )

    @property
    def succeeded(self) -> int:
        return sum(cell.status is CellStatus.SUCCEEDED for cell in self.cells)

    @property
    def partial(self) -> int:
        return sum(cell.status is CellStatus.PARTIAL for cell in self.cells)

    @property
    def failed(self) -> int:
        return sum(cell.status is CellStatus.FAILED for cell in self.cells)

    @property
    def complete(self) -> bool:
        return len(self.cells) == self.spec.cell_count

    @property
    def cost(self) -> float:
        return sum(
            cell.results.cost
            for cell in self.cells
            if cell.results is not None
        )

    @property
    def calls_total(self) -> int:
        return sum(
            cell.results.summary.calls_total
            for cell in self.cells
            if cell.results is not None
        )


CellCompleteCallback = Callable[[CampaignCellResult], None]


def run_campaign(
    spec: CampaignSpec,
    *,
    on_cell_complete: CellCompleteCallback | None = None,
) -> CampaignResult:
    """Execute every campaign cell while isolating cell-level failures.

    The same ``CampaignSpec`` always resolves each coordinate to the same
    results directory. Calling this function again therefore delegates resume
    to the existing benchmark runner. Exceptions from one cell are captured in
    that cell's result and do not prevent the rest of the matrix from running.
    A configured result validator runs synchronously after its cell returns and
    before the next cell begins. Validator failures retain the paid cell result
    but mark the cell failed, so ``stop_on_failure`` opens the circuit.
    ``KeyboardInterrupt`` and other non-``Exception`` control-flow signals are
    intentionally not swallowed.
    """
    matrix: dict[str, dict[str, CampaignCellResult]] = {
        arm.id: {} for arm in spec.arms
    }
    campaign_cost = 0.0
    campaign_calls = 0
    circuit_reason: str | None = None

    for cell in spec.cells():
        manifest: object | None = None
        manifest_digest: str | None = None
        results: Results | None = None
        try:
            if spec.max_cost is not None and campaign_cost >= spec.max_cost:
                raise RuntimeError("campaign cost budget exhausted before cell")
            if spec.max_calls is not None and campaign_calls >= spec.max_calls:
                raise RuntimeError("campaign model-call budget exhausted before cell")
            if spec.run_manifest_factory is not None:
                manifest = spec.run_manifest_factory(cell)
                _validate_manifest_identity(manifest, cell)
                manifest_digest = _manifest_digest(manifest)
            if circuit_reason is not None:
                raise RuntimeError(circuit_reason)

            run_kwargs: dict[str, Any] = {
                "trials": spec.trials,
                "threads": spec.threads,
                "limit": spec.limit,
                "results_dir": cell.results_dir,
                "bootstrap": spec.bootstrap,
            }
            if manifest is not None:
                run_kwargs["manifest"] = manifest
            if spec.max_cost is not None:
                run_kwargs["max_cost"] = spec.max_cost - campaign_cost
            if spec.max_calls is not None:
                run_kwargs["max_calls"] = spec.max_calls - campaign_calls

            results = cell.arm.benchmark.run(cell.system, **run_kwargs)
            campaign_cost += results.cost
            campaign_calls += results.summary.calls_total
            status = _status_for(results)
            if spec.cell_result_validator is not None:
                spec.cell_result_validator(cell, results)
            outcome = CampaignCellResult(
                cell=cell,
                status=status,
                results=results,
                manifest_digest=manifest_digest,
            )
        except Exception as exc:  # noqa: BLE001 - isolation is the contract
            outcome = CampaignCellResult(
                cell=cell,
                status=CellStatus.FAILED,
                results=results,
                error=f"{type(exc).__name__}: {exc}",
                manifest_digest=manifest_digest,
            )

        matrix[cell.arm_id][cell.model_id] = outcome
        if spec.stop_on_failure and outcome.status is not CellStatus.SUCCEEDED:
            circuit_reason = (
                f"campaign circuit breaker opened after {cell.arm_id}/{cell.model_id} "
                f"finished with {outcome.status.value}"
            )
        if on_cell_complete is not None:
            try:
                on_cell_complete(outcome)
            except Exception:  # noqa: BLE001 - reporting cannot abort a campaign
                pass

    frozen_matrix = MappingProxyType(
        {
            arm_id: MappingProxyType(dict(model_results))
            for arm_id, model_results in matrix.items()
        }
    )
    return CampaignResult(spec=spec, matrix=frozen_matrix)


def campaign_cell_id(campaign_id: str, arm_id: str, model_id: str) -> str:
    """Return a deterministic, collision-resistant human-readable cell ID."""
    payload = _canonical_json([campaign_id, arm_id, model_id])
    digest = hashlib.sha256(payload).hexdigest()[:12]
    return f"{_slug(arm_id)}--{_slug(model_id)}--{digest}"


def _status_for(results: Results) -> CellStatus:
    completed = results.summary.completed
    errored = results.summary.errored
    if errored == 0:
        return CellStatus.SUCCEEDED
    if completed > 0:
        return CellStatus.PARTIAL
    return CellStatus.FAILED


def _manifest_digest(manifest: object) -> str | None:
    digest = getattr(manifest, "digest", None)
    return str(digest) if digest is not None else None


def _validate_manifest_identity(manifest: object, cell: CampaignCell) -> None:
    """Reject a factory result bound to a different campaign coordinate."""
    if manifest is None:
        raise TypeError("run manifest factory returned None")
    expected = {
        "benchmark_arm": cell.arm_id,
        "model": cell.system.name,
        "trials": cell.trials,
        "selection": cell.selection,
    }
    missing = object()
    for field_name, expected_value in expected.items():
        actual = getattr(manifest, field_name, missing)
        if actual is missing:
            raise TypeError(
                f"run manifest factory result has no {field_name!r} field"
            )
        if actual != expected_value:
            raise ValueError(
                f"run manifest {field_name} {actual!r} does not match "
                f"campaign cell {expected_value!r}"
            )


def _validate_id(kind: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{kind} id must be a non-empty string")


def _require_unique(kind: str, values: list[str]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        joined = ", ".join(sorted(duplicates))
        raise ValueError(f"duplicate {kind} ids: {joined}")


def _path_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(_canonical_json([kind, value])).hexdigest()[:12]
    return f"{_slug(value)}--{digest}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug[:64] or "cell"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


__all__ = [
    "CampaignArm",
    "CampaignCell",
    "CampaignCellResult",
    "CampaignModel",
    "CampaignResult",
    "CampaignSpec",
    "CellResultValidator",
    "CellStatus",
    "RunManifestFactory",
    "campaign_cell_id",
    "run_campaign",
]
