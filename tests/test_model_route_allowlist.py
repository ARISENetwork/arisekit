"""Reviewed model-route allowlists remain active at execution time."""

from __future__ import annotations

from pathlib import Path

import pytest

from arisekit import Benchmark, BenchmarkItem, Dataset, exact_match
from arisekit.agentic import AgentTurnOutput
from arisekit.client import ModelCall, ModelResponse
from arisekit.package import BenchmarkManifest, write_package
from arisekit.sut import AgentSUT, ModelSUT


class _Client:
    def __init__(self, model: str):
        self.model = model
        self.calls = 0

    def __call__(self, call: ModelCall) -> ModelResponse:
        self.calls += 1
        return ModelResponse(text=str(call.item.ground_truth))


class _AgentClient:
    def __init__(self, model: str):
        self.model = model
        self.calls = 0

    def __call__(self, messages, tools) -> AgentTurnOutput:
        self.calls += 1
        return AgentTurnOutput(text="yes")


def _benchmark(*, allowed_model_routes: list[str]) -> Benchmark:
    return Benchmark(
        name="route-policy",
        dataset=Dataset.from_items(
            [BenchmarkItem(id="case-1", prompt="Answer.", ground_truth="yes")]
        ),
        scorer=exact_match(),
        allowed_model_routes=allowed_model_routes,
    )


def test_benchmark_runs_an_allowlisted_model_route(tmp_path: Path) -> None:
    client = _Client("provider/allowed")
    results = _benchmark(
        allowed_model_routes=["provider/allowed"],
    ).run(client, results_dir=tmp_path)

    assert results.metrics[0].value == 1.0
    assert client.calls == 1


def test_benchmark_rejects_model_route_before_dispatch(tmp_path: Path) -> None:
    client = _Client("provider/not-reviewed")

    with pytest.raises(ValueError, match="reviewed allowlist"):
        _benchmark(
            allowed_model_routes=["provider/allowed"],
        ).run(client, results_dir=tmp_path)

    assert client.calls == 0
    assert not (tmp_path / "raw").exists()


def test_model_sut_alias_cannot_bypass_route_policy(tmp_path: Path) -> None:
    client = _Client("provider/not-reviewed")
    sut = ModelSUT(client, name="provider/allowed")

    with pytest.raises(ValueError, match="provider/not-reviewed"):
        _benchmark(
            allowed_model_routes=["provider/allowed"],
        ).run(sut, results_dir=tmp_path)

    assert client.calls == 0


def test_agent_sut_alias_cannot_bypass_route_policy(tmp_path: Path) -> None:
    client = _AgentClient("provider/not-reviewed")
    sut = AgentSUT(client, [], name="provider/allowed")

    with pytest.raises(ValueError, match="provider/not-reviewed"):
        _benchmark(
            allowed_model_routes=["provider/allowed"],
        ).run(sut, results_dir=tmp_path)

    assert client.calls == 0


def test_package_provenance_restores_model_route_policy(tmp_path: Path) -> None:
    root = write_package(
        tmp_path / "package",
        manifest=BenchmarkManifest(
            id="route-policy",
            name="Route policy",
            scorer={"kind": "exact-match"},
            provenance={
                "readiness": {
                    "allowed_model_routes": ["provider/allowed"],
                }
            },
        ),
        items=[
            BenchmarkItem(
                id="case-1",
                prompt="Answer.",
                ground_truth="yes",
            )
        ],
    )

    benchmark = Benchmark.from_package(root)

    assert benchmark.allowed_model_routes == ("provider/allowed",)
    with pytest.raises(ValueError, match="provider/not-reviewed"):
        benchmark.run("provider/not-reviewed", results_dir=tmp_path / "results")


def test_package_route_policy_cannot_be_expanded(tmp_path: Path) -> None:
    root = write_package(
        tmp_path / "package",
        manifest=BenchmarkManifest(
            id="route-policy",
            name="Route policy",
            scorer={"kind": "exact-match"},
            provenance={
                "readiness": {
                    "allowed_model_routes": ["provider/allowed"],
                }
            },
        ),
        items=[BenchmarkItem(id="case-1", prompt="Answer.", ground_truth="yes")],
    )

    with pytest.raises(ValueError, match="cannot add an unreviewed"):
        Benchmark.from_package(
            root,
            allowed_model_routes=["provider/not-reviewed"],
        )


@pytest.mark.parametrize(
    "routes",
    [
        [],
        ["provider/model", "provider/model"],
        ["provider/model", ""],
    ],
)
def test_invalid_model_route_policy_is_rejected(routes: list[str]) -> None:
    with pytest.raises(ValueError):
        _benchmark(allowed_model_routes=routes)
