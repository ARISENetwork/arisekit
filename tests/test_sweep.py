from __future__ import annotations

import csv
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import arisekit.sut as sut_module
from arisekit.benchmark import Benchmark
from arisekit.client import ModelCall, ModelResponse
from arisekit.dataset import Dataset
from arisekit.runner import RunnerConfig
from arisekit.scorer import BaseScorer, exact_match
from arisekit.analysis.sweep import (
    SWEEP_RESULTS_SCHEMA_VERSION,
    SWEEP_SCORES_HEADER,
    SWEEP_SPEC_SCHEMA_VERSION,
    BenchmarkSweepSpec,
    SweepCellStatus,
    SweepModel,
    run_benchmark_sweep,
    sweep_spec_from_package,
)
from arisekit.types import BenchmarkItem, Metric, RunResult


class CountingClient:
    def __init__(
        self,
        model: str,
        *,
        cost: float = 0.0,
        cost_known: bool = True,
        fail: bool = False,
    ):
        self.model = model
        self.cost = cost
        self.cost_known = cost_known
        self.fail = fail
        self.calls = 0

    def __call__(self, call: ModelCall) -> ModelResponse:
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self.model} unavailable")
        return ModelResponse(
            text=str(call.item.ground_truth),
            cost=self.cost,
            cost_known=self.cost_known,
            provider_model=self.model,
        )


class FailOnceScorer(BaseScorer):
    def __init__(self) -> None:
        self.calls = 0

    def score_item(
        self,
        item: BenchmarkItem,
        responses: list[RunResult],
    ) -> list[Metric]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("synthetic scorer failure")
        passed = all(response.response == item.ground_truth for response in responses)
        return [Metric("accuracy", float(passed), n=len(responses))]


def _benchmark(
    *,
    items: int = 2,
    allowed: tuple[str, ...] | None = None,
    max_cost_per_call: float | None = None,
    require_known_cost: bool = False,
) -> Benchmark:
    dataset = Dataset.from_items(
        [
            BenchmarkItem(
                id=f"case-{index}",
                prompt=f"Question {index}",
                ground_truth=f"answer-{index}",
            )
            for index in range(1, items + 1)
        ],
        name="sweep-fixture",
    )
    return Benchmark(
        name="sweep-fixture",
        dataset=dataset,
        scorer=exact_match(case_sensitive=True),
        runner_config=RunnerConfig(
            max_retries=1,
            retry_backoff=0.0,
            max_cost_per_call=max_cost_per_call,
            require_known_cost=require_known_cost,
        ),
        allowed_model_routes=allowed,
    )


def _clients(monkeypatch: pytest.MonkeyPatch, **options) -> dict[str, CountingClient]:
    values = {
        route: CountingClient(route, **config)
        for route, config in options.items()
    }

    def resolve(route):
        return values[str(route)]

    monkeypatch.setattr(sut_module, "resolve_client", resolve)
    return values


def _spec(*models: tuple[str, str, int], **options) -> BenchmarkSweepSpec:
    return BenchmarkSweepSpec(
        benchmark="sweep-fixture",
        models=tuple(
            SweepModel(model=model, provider=provider, trials=trials)
            for model, provider, trials in models
        ),
        **options,
    )


def _assert_artifact(root: Path, artifact: dict[str, object]) -> Path:
    path = root / str(artifact["path"])
    payload = path.read_bytes()
    assert artifact["size"] == len(payload)
    assert artifact["sha256"] == hashlib.sha256(payload).hexdigest()
    return path


def test_two_model_sweep_is_manifested_resumable_and_hash_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = _clients(
        monkeypatch,
        **{
            "provider/model-a": {},
            "provider/model-b": {},
        },
    )
    bench = _benchmark(allowed=("provider/model-a", "provider/model-b"))
    spec = _spec(
        ("provider/model-a", "provider", 1),
        ("provider/model-b", "provider", 2),
        allowed_model_routes=("provider/model-a", "provider/model-b"),
        threads=2,
        cost_preview_digest="a" * 64,
    )

    first = run_benchmark_sweep(bench, spec, results_dir=tmp_path)

    assert [cell.model for cell in first.cells] == [
        "provider/model-a",
        "provider/model-b",
    ]
    assert [cell.trials for cell in first.cells] == [1, 2]
    assert all(cell.status is SweepCellStatus.SUCCEEDED for cell in first.cells)
    assert [clients[route].calls for route in clients] == [2, 4]
    assert first.complete
    assert first.cost == 0.0
    assert first.receipt_path.parts[-4:-1] == (
        "sweep-fixture",
        spec.digest,
        first.execution_digest,
    )

    spec_payload = json.loads(first.spec_path.read_text(encoding="utf-8"))
    receipt_payload = json.loads(first.receipt_path.read_text(encoding="utf-8"))
    assert spec_payload["schema_version"] == SWEEP_SPEC_SCHEMA_VERSION
    assert BenchmarkSweepSpec.from_json(first.spec_path) == spec
    assert spec_payload["bootstrap"] == 0
    assert spec_payload["bootstrap_seed"] == 0
    assert receipt_payload["schema_version"] == SWEEP_RESULTS_SCHEMA_VERSION
    assert receipt_payload["sweep_spec_sha256"] == spec.digest
    assert receipt_payload["complete"] is True
    assert receipt_payload["claim_boundary"].startswith(
        "These results describe this benchmark snapshot"
    )
    for cell in receipt_payload["cells"]:
        assert len(cell["run_manifest_digest"]) == 64
        for field in ("raw_checkpoint", "run_manifest", "scores"):
            _assert_artifact(tmp_path, cell[field])
    for artifact in receipt_payload["artifacts"].values():
        _assert_artifact(tmp_path, artifact)

    with first.scores_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert tuple(rows[0]) == SWEEP_SCORES_HEADER
    assert [row[1] for row in rows[1:]] == [
        "provider/model-a",
        "provider/model-b",
    ]
    assert "rank" not in rows[0]
    assert "composite" not in rows[0]

    receipt_before = first.receipt_path.read_bytes()
    second = run_benchmark_sweep(bench, spec, results_dir=tmp_path)

    assert [clients[route].calls for route in clients] == [2, 4]
    assert second.execution_digest == first.execution_digest
    assert second.receipt_path.read_bytes() == receipt_before


def test_adding_and_removing_selected_models_reuses_existing_cells(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = _clients(
        monkeypatch,
        **{
            "provider/model-a": {},
            "provider/model-b": {},
            "provider/model-c": {},
        },
    )
    routes = tuple(clients)
    bench = _benchmark(allowed=routes)

    run_benchmark_sweep(
        bench,
        _spec(
            ("provider/model-a", "provider", 1),
            ("provider/model-b", "provider", 1),
            allowed_model_routes=routes,
        ),
        results_dir=tmp_path,
    )
    assert [client.calls for client in clients.values()] == [2, 2, 0]

    expanded = run_benchmark_sweep(
        bench,
        _spec(
            ("provider/model-a", "provider", 1),
            ("provider/model-b", "provider", 1),
            ("provider/model-c", "provider", 1),
            allowed_model_routes=routes,
        ),
        results_dir=tmp_path,
    )
    assert [client.calls for client in clients.values()] == [2, 2, 2]

    reduced = run_benchmark_sweep(
        bench,
        _spec(
            ("provider/model-b", "provider", 1),
            allowed_model_routes=routes,
        ),
        results_dir=tmp_path,
    )
    assert [client.calls for client in clients.values()] == [2, 2, 2]
    assert expanded.cells[0].run_manifest_digest == next(
        cell.run_manifest_digest
        for cell in run_benchmark_sweep(
            bench,
            _spec(
                ("provider/model-a", "provider", 1),
                allowed_model_routes=routes,
            ),
            results_dir=tmp_path,
        ).cells
    )
    assert reduced.cells[0].model == "provider/model-b"


def test_one_failed_model_does_not_stop_later_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = _clients(
        monkeypatch,
        **{
            "provider/failing": {"fail": True},
            "provider/healthy": {},
        },
    )
    bench = _benchmark()
    result = run_benchmark_sweep(
        bench,
        _spec(
            ("provider/failing", "provider", 1),
            ("provider/healthy", "provider", 1),
        ),
        results_dir=tmp_path,
    )

    assert result.cells[0].status is SweepCellStatus.FAILED
    assert result.cells[0].errored == 2
    assert result.cells[1].status is SweepCellStatus.SUCCEEDED
    assert clients["provider/failing"].calls == 2
    assert clients["provider/healthy"].calls == 2
    assert result.failed == 1
    assert not result.complete


def test_framework_exception_is_isolated_to_one_model_cell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = _clients(monkeypatch, **{"provider/healthy": {}})
    bench = _benchmark()
    original_run = bench.run

    def run(model, **options):
        if model == "provider/broken":
            raise RuntimeError("scorer binding failed")
        if "bootstrap_seed" not in inspect.signature(original_run).parameters:
            options.pop("bootstrap_seed", None)
        return original_run(model, **options)

    monkeypatch.setattr(bench, "run", run)
    result = run_benchmark_sweep(
        bench,
        _spec(
            ("provider/broken", "provider", 1),
            ("provider/healthy", "provider", 1),
        ),
        results_dir=tmp_path,
    )

    assert result.cells[0].status is SweepCellStatus.FAILED
    assert result.cells[0].error == "RuntimeError: scorer binding failed"
    assert result.cells[0].raw_checkpoint is None
    assert result.cells[1].status is SweepCellStatus.SUCCEEDED
    assert clients["provider/healthy"].calls == 2


def test_scorer_failure_retains_raw_provenance_and_actual_accounting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = _clients(
        monkeypatch,
        **{
            "provider/first": {"cost": 0.25},
            "provider/second": {"cost": 0.0},
        },
    )
    benchmark = _benchmark(items=1)
    benchmark.scorer = FailOnceScorer()

    result = run_benchmark_sweep(
        benchmark,
        _spec(
            ("provider/first", "provider", 1),
            ("provider/second", "provider", 1),
        ),
        results_dir=tmp_path,
    )

    failed, succeeded = result.cells
    assert failed.status is SweepCellStatus.FAILED
    assert failed.completed == 1
    assert failed.calls_total == 1
    assert failed.cost == pytest.approx(0.25)
    assert failed.raw_checkpoint is not None
    assert failed.run_manifest is not None
    assert failed.scores is None
    assert (tmp_path / failed.raw_checkpoint.path).is_file()
    assert succeeded.status is SweepCellStatus.SUCCEEDED
    assert [client.calls for client in clients.values()] == [1, 1]


def test_route_allowlist_rejection_happens_before_any_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = _clients(
        monkeypatch,
        **{
            "provider/allowed": {},
            "provider/rejected": {},
        },
    )
    bench = _benchmark(allowed=("provider/allowed",))
    spec = _spec(
        ("provider/allowed", "provider", 1),
        ("provider/rejected", "provider", 1),
    )

    with pytest.raises(ValueError, match="outside the benchmark's reviewed allowlist"):
        run_benchmark_sweep(bench, spec, results_dir=tmp_path)

    assert all(client.calls == 0 for client in clients.values())


def test_global_call_budget_stops_before_unstarted_model_cells(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = _clients(
        monkeypatch,
        **{
            "provider/model-a": {},
            "provider/model-b": {},
            "provider/model-c": {},
        },
    )
    result = run_benchmark_sweep(
        _benchmark(items=1),
        _spec(
            ("provider/model-a", "provider", 1),
            ("provider/model-b", "provider", 1),
            ("provider/model-c", "provider", 1),
            max_calls=2,
        ),
        results_dir=tmp_path,
    )

    assert [cell.status for cell in result.cells] == [
        SweepCellStatus.SUCCEEDED,
        SweepCellStatus.SUCCEEDED,
        SweepCellStatus.NOT_RUN,
    ]
    assert [client.calls for client in clients.values()] == [1, 1, 0]
    assert result.calls_total == 2


def test_global_cost_budget_and_unknown_cost_stop_conservatively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = _clients(
        monkeypatch,
        **{
            "provider/model-a": {"cost": 0.6},
            "provider/model-b": {"cost": 0.6},
            "provider/model-c": {"cost": 0.6},
        },
    )
    cost_result = run_benchmark_sweep(
        _benchmark(items=1, max_cost_per_call=0.6, require_known_cost=True),
        _spec(
            ("provider/model-a", "provider", 1),
            ("provider/model-b", "provider", 1),
            ("provider/model-c", "provider", 1),
            max_cost=0.7,
        ),
        results_dir=tmp_path / "cost",
    )

    assert [cell.status for cell in cost_result.cells] == [
        SweepCellStatus.SUCCEEDED,
        SweepCellStatus.FAILED,
        SweepCellStatus.NOT_RUN,
    ]
    assert [client.calls for client in clients.values()] == [1, 0, 0]
    assert cost_result.cost == pytest.approx(0.6)

    unknown_clients = _clients(
        monkeypatch,
        **{
            "provider/unknown": {"cost_known": False},
            "provider/unstarted": {},
        },
    )
    unknown_result = run_benchmark_sweep(
        _benchmark(items=1),
        _spec(
            ("provider/unknown", "provider", 1),
            ("provider/unstarted", "provider", 1),
        ),
        results_dir=tmp_path / "unknown",
    )

    assert unknown_result.cells[0].cost_unknown is True
    assert unknown_result.cells[1].status is SweepCellStatus.NOT_RUN
    assert [client.calls for client in unknown_clients.values()] == [1, 0]


def test_package_plan_supports_only_reviewed_subsets_and_preserves_order() -> None:
    package = SimpleNamespace(
        manifest=SimpleNamespace(
            id="sweep-fixture",
            provenance={
                "first_sweep": [
                    {"model": "provider/a", "provider": "one", "trials": 1},
                    {"model": "provider/b", "provider": "two", "trials": 3},
                ],
                "readiness": {
                    "allowed_model_routes": ["provider/a", "provider/b"]
                },
                "runner": {"threads": 4},
            },
        )
    )

    spec = sweep_spec_from_package(
        package,
        models=("provider/b", "provider/a"),
        bootstrap=250,
        bootstrap_seed=-17,
        cost_preview_digest="b" * 64,
    )

    assert [model.model for model in spec.models] == ["provider/b", "provider/a"]
    assert [model.trials for model in spec.models] == [3, 1]
    assert spec.threads == 4
    assert spec.bootstrap == 250
    assert spec.bootstrap_seed == -17
    assert BenchmarkSweepSpec.from_dict(spec.to_dict()) == spec

    with pytest.raises(ValueError, match="outside the reviewed first_sweep"):
        sweep_spec_from_package(package, models=("provider/c",))


def test_benchmark_run_many_builds_versioned_spec_and_delegates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import arisekit.analysis.sweep as sweep_module

    benchmark = _benchmark(allowed=("provider/a", "provider/b"))
    captured: dict[str, object] = {}
    expected = object()

    def fake_run(bound_benchmark, spec, **kwargs):
        captured["benchmark"] = bound_benchmark
        captured["spec"] = spec
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(sweep_module, "run_benchmark_sweep", fake_run)

    actual = benchmark.run_many(
        ("provider/b", "provider/a"),
        providers={"provider/a": "one", "provider/b": "two"},
        trials={"provider/a": 1, "provider/b": 3},
        threads=4,
        bootstrap=50,
        bootstrap_seed=-9,
        results_dir=tmp_path,
    )

    assert actual is expected
    assert captured["benchmark"] is benchmark
    spec = captured["spec"]
    assert isinstance(spec, BenchmarkSweepSpec)
    assert [model.model for model in spec.models] == ["provider/b", "provider/a"]
    assert [model.provider for model in spec.models] == ["two", "one"]
    assert [model.trials for model in spec.models] == [3, 1]
    assert spec.bootstrap == 50
    assert spec.bootstrap_seed == -9
    assert captured["results_dir"] == tmp_path
