"""Multi-arm campaign execution stays isolated, complete, and resumable."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import pytest

from arisekit.benchmark import Benchmark
from arisekit.campaign import (
    CampaignArm,
    CampaignModel,
    CampaignSpec,
    CellStatus,
    run_campaign,
)
from arisekit.client import ModelCall, ModelResponse
from arisekit.dataset import Dataset
from arisekit.run_manifest import RunManifest
from arisekit.runner import RunnerConfig
from arisekit.scorer import exact_match
from arisekit.types import BenchmarkItem


class AnswerClient:
    def __init__(self, name: str = "shared-runtime", *, fail_on: str | None = None):
        self.model = name
        self.fail_on = fail_on
        self.calls = 0

    def __call__(self, call: ModelCall) -> ModelResponse:
        self.calls += 1
        if self.fail_on and self.fail_on in str(call.item.prompt):
            raise RuntimeError("deliberate model failure")
        return ModelResponse(text=str(call.item.ground_truth))


def _benchmark(*, prompt: str, answer: str, name: str = "same-benchmark") -> Benchmark:
    item = BenchmarkItem(id="case-1", prompt=prompt, ground_truth=answer)
    return Benchmark(
        name=name,
        dataset=Dataset.from_items([item]),
        scorer=exact_match(),
        runner_config=RunnerConfig(max_retries=1, retry_backoff=0.0),
    )


def _spec(tmp_path: Path, clients: list[AnswerClient]) -> CampaignSpec:
    return CampaignSpec(
        id="noharm-parity/v1",
        arms=[
            CampaignArm(
                "original/arm",
                _benchmark(prompt="original case", answer="original answer"),
            ),
            CampaignArm(
                "generated__arm",
                _benchmark(prompt="generated case", answer="generated answer"),
            ),
        ],
        models=[CampaignModel(f"model-{idx}", client) for idx, client in enumerate(clients)],
        results_dir=tmp_path,
    )


def _manifest_for_cell(cell) -> RunManifest:
    def digest(label: str) -> str:
        return hashlib.sha256(label.encode("utf-8")).hexdigest()

    return RunManifest(
        benchmark_arm=cell.arm_id,
        benchmark_content_hash=digest(f"content:{cell.arm_id}"),
        prompt_hash=digest(f"prompt:{cell.arm_id}"),
        rubric_hash=digest(f"rubric:{cell.arm_id}"),
        code_hash=digest("code"),
        model=cell.system.name,
        provider="test",
        trials=cell.trials,
        selection=cell.selection,
        source_revision="test-revision",
    )


def test_two_arms_by_four_models_is_complete_isolated_and_resumable(tmp_path: Path):
    # All four clients intentionally expose the same runtime name. Both arms
    # also use the same benchmark name and item id. Campaign coordinates, not
    # these runtime labels, must isolate the eight checkpoints.
    clients = [AnswerClient() for _ in range(4)]
    spec = _spec(tmp_path, clients)

    first = run_campaign(spec)

    assert first.complete
    assert first.succeeded == 8
    assert first.partial == 0
    assert first.failed == 0
    assert list(first.matrix) == ["original/arm", "generated__arm"]
    assert all(len(row) == 4 for row in first.matrix.values())
    assert all(client.calls == 2 for client in clients)

    cell_ids = {cell.cell.id for cell in first.cells}
    output_paths = {
        cell.results.summary.output_path
        for cell in first.cells
        if cell.results is not None
    }
    assert len(cell_ids) == 8
    assert len(output_paths) == 8
    assert first.cell("original/arm", "model-0").cell.id != first.cell(
        "generated__arm", "model-0"
    ).cell.id

    # Cell identity is independent of declaration order.
    reordered = CampaignSpec(
        id=spec.id,
        arms=list(reversed(spec.arms)),
        models=list(reversed(spec.models)),
        results_dir=tmp_path,
    )
    reordered_ids = {
        (cell.arm_id, cell.model_id): cell.id for cell in reordered.cells()
    }
    assert reordered_ids == {
        (cell.arm_id, cell.model_id): cell.id for cell in spec.cells()
    }

    calls_after_first = [client.calls for client in clients]
    second = run_campaign(spec)

    assert [client.calls for client in clients] == calls_after_first
    assert all(
        outcome.results is not None and outcome.results.summary.skipped == 1
        for outcome in second.cells
    )


def test_one_failed_cell_does_not_abort_the_matrix(tmp_path: Path):
    good = AnswerClient(name="good")
    fails_only_generated_arm = AnswerClient(name="selective", fail_on="generated")
    spec = _spec(tmp_path, [good, fails_only_generated_arm])

    result = run_campaign(spec)

    assert result.complete
    assert result.succeeded == 3
    assert result.failed == 1
    failed = result.cell("generated__arm", "model-1")
    assert failed.status is CellStatus.FAILED
    assert failed.results is not None
    assert failed.results.summary.completed == 0
    assert failed.results.summary.errored == 1
    assert result.cell("original/arm", "model-1").status is CellStatus.SUCCEEDED
    assert result.cell("generated__arm", "model-0").status is CellStatus.SUCCEEDED


def test_manifest_factory_binds_and_records_one_manifest_per_cell(tmp_path: Path):
    clients = [AnswerClient(name="model-a"), AnswerClient(name="model-b")]
    built: dict[tuple[str, str], RunManifest] = {}

    def manifest_for(cell):
        manifest = _manifest_for_cell(cell)
        built[(cell.arm_id, cell.model_id)] = manifest
        return manifest

    base = _spec(tmp_path, clients)
    spec = CampaignSpec(
        id=base.id,
        arms=base.arms,
        models=base.models,
        trials=2,
        results_dir=tmp_path,
        selection={"variant_policy": "baseline-plus-four"},
        run_manifest_factory=manifest_for,
    )

    result = run_campaign(spec)

    assert result.complete
    assert result.succeeded == 4
    assert len(built) == 4
    for outcome in result.cells:
        manifest = built[(outcome.arm_id, outcome.model_id)]
        assert outcome.manifest_digest == manifest.digest
        assert outcome.results is not None
        assert outcome.results.summary.manifest_digest == manifest.digest
        assert outcome.results.summary.completed == 2


def test_manifest_factory_exception_is_isolated_to_its_cell(tmp_path: Path):
    clients = [AnswerClient(name="model-a"), AnswerClient(name="model-b")]
    base = _spec(tmp_path, clients)

    def manifest_for(cell):
        if cell.arm_id == "generated__arm" and cell.model_id == "model-0":
            raise ValueError("missing generated-arm content hash")
        return _manifest_for_cell(cell)

    spec = CampaignSpec(
        id=base.id,
        arms=base.arms,
        models=base.models,
        results_dir=tmp_path,
        run_manifest_factory=manifest_for,
    )

    result = run_campaign(spec)

    assert result.complete
    assert result.succeeded == 3
    assert result.failed == 1
    failed = result.cell("generated__arm", "model-0")
    assert failed.results is None
    assert failed.error == "ValueError: missing generated-arm content hash"
    assert result.cell("generated__arm", "model-1").status is CellStatus.SUCCEEDED


def test_selection_is_deeply_immutable_and_rejects_non_json_values(tmp_path: Path):
    nested = {"base_ids": ["Case001"], "policy": {"k": 5}}
    spec = CampaignSpec(
        id="immutable-selection",
        arms=[CampaignArm("reference", _benchmark(prompt="q", answer="a"))],
        models=[CampaignModel("model", AnswerClient())],
        results_dir=tmp_path,
        selection=nested,
    )

    nested["base_ids"].append("Case002")
    nested["policy"]["k"] = 11
    assert spec.selection["base_ids"] == ("Case001",)
    assert spec.selection["policy"]["k"] == 5

    with pytest.raises(ValueError, match="non-finite float"):
        CampaignSpec(
            id="bad-selection",
            arms=spec.arms,
            models=spec.models,
            selection={"margin": math.nan},
        )


def test_campaign_budget_stops_before_later_cells(tmp_path: Path):
    class CostlyClient(AnswerClient):
        def __call__(self, call: ModelCall) -> ModelResponse:
            self.calls += 1
            return ModelResponse(text=str(call.item.ground_truth), cost=0.6)

    clients = [CostlyClient(name="costly-a"), CostlyClient(name="costly-b")]
    spec = CampaignSpec(
        id="budgeted-campaign",
        arms=[
            CampaignArm("reference", _benchmark(prompt="q", answer="a")),
            CampaignArm("generated", _benchmark(prompt="q", answer="a")),
        ],
        models=[CampaignModel(f"model-{index}", client) for index, client in enumerate(clients)],
        trials=2,
        results_dir=tmp_path,
        max_cost=0.5,
    )

    result = run_campaign(spec)

    assert result.partial == 1
    assert result.failed == 3
    assert clients[0].calls == 1
    assert clients[1].calls == 0
    assert result.cells[0].results is not None
    assert result.cells[0].results.summary.budget_exhausted is True
    assert all(
        cell.error == "RuntimeError: campaign cost budget exhausted before cell"
        for cell in result.cells[1:]
    )


def test_campaign_model_call_budget_is_shared_across_cells(tmp_path: Path):
    clients = [AnswerClient(name="calls-a"), AnswerClient(name="calls-b")]
    spec = CampaignSpec(
        id="call-budgeted-campaign",
        arms=[
            CampaignArm("reference", _benchmark(prompt="q", answer="a")),
            CampaignArm("generated", _benchmark(prompt="q", answer="a")),
        ],
        models=[CampaignModel(f"model-{index}", client) for index, client in enumerate(clients)],
        trials=2,
        results_dir=tmp_path,
        max_calls=2,
    )

    result = run_campaign(spec)

    assert result.calls_total == 2
    assert sum(client.calls for client in clients) == 2
    assert result.cells[0].status is CellStatus.SUCCEEDED
    assert all(cell.status is CellStatus.FAILED for cell in result.cells[1:])


def test_optional_circuit_breaker_records_remaining_cells_without_calls(tmp_path: Path):
    failing = AnswerClient(name="fails", fail_on="original")
    untouched = AnswerClient(name="untouched")
    base = _spec(tmp_path, [failing, untouched])
    spec = CampaignSpec(
        id=base.id,
        arms=base.arms,
        models=base.models,
        results_dir=tmp_path,
        stop_on_failure=True,
    )

    result = run_campaign(spec)

    assert result.cells[0].status is CellStatus.FAILED
    assert all(cell.status is CellStatus.FAILED for cell in result.cells[1:])
    assert all(
        "circuit breaker opened" in (cell.error or "")
        for cell in result.cells[1:]
    )
    assert untouched.calls == 0


def test_cell_result_validation_failure_opens_circuit_before_later_calls(
    tmp_path: Path,
):
    clients = [AnswerClient(name="first"), AnswerClient(name="untouched")]
    base = _spec(tmp_path, clients)

    def reject_first_identity(cell, _results):
        if cell.arm_id == "original/arm" and cell.model_id == "model-0":
            raise ValueError("provider-returned model identity mismatch")

    spec = CampaignSpec(
        id=base.id,
        arms=base.arms,
        models=base.models,
        results_dir=tmp_path,
        stop_on_failure=True,
        cell_result_validator=reject_first_identity,
    )

    result = run_campaign(spec)

    first = result.cell("original/arm", "model-0")
    assert first.status is CellStatus.FAILED
    assert first.results is not None
    assert first.error == "ValueError: provider-returned model identity mismatch"
    assert all(cell.status is CellStatus.FAILED for cell in result.cells)
    assert all(
        "circuit breaker opened" in (cell.error or "")
        for cell in result.cells[1:]
    )
    assert [client.calls for client in clients] == [1, 0]
    assert result.calls_total == 1


def test_cell_result_validation_success_allows_later_cells(tmp_path: Path):
    clients = [AnswerClient(name="model-a"), AnswerClient(name="model-b")]
    base = _spec(tmp_path, clients)
    validated: list[tuple[str, str]] = []

    def accept_identity(cell, results):
        assert results.raw
        validated.append((cell.arm_id, cell.model_id))

    spec = CampaignSpec(
        id=base.id,
        arms=base.arms,
        models=base.models,
        results_dir=tmp_path,
        stop_on_failure=True,
        cell_result_validator=accept_identity,
    )

    result = run_campaign(spec)

    assert result.succeeded == 4
    assert len(validated) == 4
    assert [client.calls for client in clients] == [2, 2]


def test_model_interleaved_execution_is_seeded_and_arm_balanced(tmp_path: Path):
    base = _spec(tmp_path, [AnswerClient() for _ in range(4)])
    first = CampaignSpec(
        id=base.id,
        arms=base.arms,
        models=base.models,
        results_dir=tmp_path,
        execution_order="model-interleaved",
        order_seed=17,
    )
    second = CampaignSpec(
        id=base.id,
        arms=base.arms,
        models=base.models,
        results_dir=tmp_path,
        execution_order="model-interleaved",
        order_seed=17,
    )

    coordinates = [(cell.arm_id, cell.model_id) for cell in first.cells()]
    assert coordinates == [(cell.arm_id, cell.model_id) for cell in second.cells()]
    for index in range(0, len(coordinates), 2):
        pair = coordinates[index : index + 2]
        assert pair[0][1] == pair[1][1]
        assert {pair[0][0], pair[1][0]} == {"original/arm", "generated__arm"}
    assert coordinates[0][0] != coordinates[2][0]

    with pytest.raises(ValueError, match="requires order_seed"):
        CampaignSpec(
            id="missing-seed",
            arms=base.arms,
            models=base.models,
            execution_order="model-interleaved",
        )
