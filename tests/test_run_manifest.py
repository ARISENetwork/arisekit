"""Run manifests make checkpoint reuse explicit and content-addressed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arisekit.benchmark import Benchmark
from arisekit.client import (
    REFERENCE_STUB_MODEL,
    ModelCall,
    ModelResponse,
    ReferenceStubClient,
    resolve_client,
)
from arisekit.dataset import Dataset
from arisekit.run_manifest import (
    RunManifest,
    build_automatic_run_manifest,
    sha256_digest,
)
from arisekit.runner import RunnerConfig, run
from arisekit.scorer import exact_match
from arisekit.types import BenchmarkItem, Tool


class CountingClient:
    model = "solver"

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, call: ModelCall) -> ModelResponse:
        self.calls += 1
        return ModelResponse(text=f"answer:{call.item.id}")


class AlternateCodeIdentity:
    pass


def _manifest(**overrides: object) -> RunManifest:
    values: dict[str, object] = {
        "benchmark_arm": "original",
        "benchmark_content_hash": sha256_digest("cases-v1"),
        "prompt_hash": sha256_digest("prompt-v1"),
        "rubric_hash": sha256_digest("rubric-v1"),
        "guidance_hash": sha256_digest("guidance-v1"),
        "judge_hash": sha256_digest("judge-v1"),
        "code_hash": sha256_digest("code-v1"),
        "model": "solver",
        "provider": "fake",
        "model_config": {"temperature": None, "max_tokens": None, "nested": {"b": 2, "a": 1}},
        "trials": 1,
        "seeds": (17,),
        "selection": {"k": 1, "ids": ["a", "b"]},
        "source_revision": "abc123",
    }
    values.update(overrides)
    return RunManifest(**values)  # type: ignore[arg-type]


def _dataset() -> Dataset:
    return Dataset.from_items(
        [{"id": "a", "prompt": "qa"}, {"id": "b", "prompt": "qb"}],
        name="fixture",
    )


def test_manifest_is_canonical_round_trippable_and_deeply_frozen() -> None:
    config = {"nested": {"b": 2, "a": 1}, "temperature": None, "max_tokens": None}
    manifest = _manifest(model_config=config)
    digest = manifest.digest

    config["temperature"] = 1
    config["nested"]["a"] = 99

    assert manifest.digest == digest
    assert manifest.to_dict()["model_config"]["temperature"] is None
    assert RunManifest.from_dict(manifest.to_dict()).digest == digest

    reordered = _manifest(
        model_config={"temperature": None, "max_tokens": None, "nested": {"a": 1, "b": 2}},
        selection={"ids": ["a", "b"], "k": 1},
    )
    assert reordered.canonical_json() == manifest.canonical_json()
    assert reordered.digest == digest


def test_manifest_rejects_ambiguous_or_non_json_identity() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        _manifest(prompt_hash="not-a-digest")
    with pytest.raises(ValueError, match="one seed per trial"):
        _manifest(trials=2, seeds=(17,))
    with pytest.raises(ValueError, match="non-JSON"):
        _manifest(model_config={"bad": object()})


def test_manifested_run_is_namespaced_and_resumes(tmp_path: Path) -> None:
    client = CountingClient()
    manifest = _manifest()
    cfg = RunnerConfig(results_dir=tmp_path)

    results, first = run(
        _dataset(),
        model=client,
        benchmark_name="noharm",
        config=cfg,
        manifest=manifest,
    )

    assert first.manifest_digest == manifest.digest
    assert first.output_path.parent.name == manifest.digest
    assert first.output_path.parent.joinpath("run-manifest.json").exists()
    assert all(r.metadata["run_manifest_digest"] == manifest.digest for r in results)
    assert client.calls == 2

    _, second = run(
        _dataset(),
        model=client,
        benchmark_name="noharm",
        config=cfg,
        manifest=manifest,
    )
    assert second.skipped == 2
    assert client.calls == 2


def test_interrupted_manifested_benchmark_resumes_with_lineage_and_run_results(
    tmp_path: Path,
) -> None:
    class InterruptingClient(CountingClient):
        def __call__(self, call: ModelCall) -> ModelResponse:
            self.calls += 1
            if call.item.id == "b":
                raise KeyboardInterrupt("deliberate benchmark interruption")
            return ModelResponse(text=f"answer:{call.item.id}")

    benchmark = Benchmark(
        name="noharm",
        dataset=_dataset(),
        scorer=exact_match(),
        runner_config=RunnerConfig(results_dir=tmp_path, threads=1),
    )
    manifest = _manifest()
    interrupted = InterruptingClient()
    with pytest.raises(KeyboardInterrupt, match="deliberate benchmark interruption"):
        benchmark.run(interrupted, manifest=manifest, results_dir=tmp_path)

    checkpoint = (
        tmp_path
        / "raw"
        / "noharm"
        / manifest.digest
        / "solver.jsonl"
    )
    rows = [json.loads(line) for line in checkpoint.read_text(encoding="utf-8").splitlines()]
    assert [row["id"] for row in rows] == ["a"]
    assert rows[0]["metadata"]["run_manifest_digest"] == manifest.digest

    resumed_client = CountingClient()
    results = benchmark.run(
        resumed_client,
        manifest=manifest,
        results_dir=tmp_path,
    )
    assert resumed_client.calls == 1
    assert results.summary.skipped == 1
    assert results.summary.manifest_digest == manifest.digest
    assert results.report_path is not None and results.report_path.is_file()
    assert results.bundle_path is not None and results.bundle_path.is_file()

def test_changed_manifest_cannot_reuse_previous_responses(tmp_path: Path) -> None:
    client = CountingClient()
    cfg = RunnerConfig(results_dir=tmp_path)
    first_manifest = _manifest()
    second_manifest = _manifest(prompt_hash=sha256_digest("prompt-v2"))

    _, first = run(
        _dataset(), model=client, benchmark_name="noharm", config=cfg, manifest=first_manifest,
    )
    _, second = run(
        _dataset(), model=client, benchmark_name="noharm", config=cfg, manifest=second_manifest,
    )

    assert first.output_path != second.output_path
    assert second.skipped == 0
    assert client.calls == 4


def test_manifest_rejects_runner_identity_mismatch(tmp_path: Path) -> None:
    client = CountingClient()
    with pytest.raises(ValueError, match="resolved model"):
        run(
            _dataset(),
            model=client,
            benchmark_name="noharm",
            config=RunnerConfig(results_dir=tmp_path),
            manifest=_manifest(model="different"),
        )

    with pytest.raises(ValueError, match="runner trials"):
        run(
            _dataset(),
            model=client,
            benchmark_name="noharm",
            config=RunnerConfig(results_dir=tmp_path, trials=2),
            manifest=_manifest(),
        )

    with pytest.raises(ValueError, match="model_config.temperature"):
        run(
            _dataset(),
            model=client,
            benchmark_name="noharm",
            config=RunnerConfig(results_dir=tmp_path, temperature=0.5),
            manifest=_manifest(),
        )
    with pytest.raises(ValueError, match="model_config.temperature"):
        run(
            _dataset(),
            model=client,
            benchmark_name="noharm",
            config=RunnerConfig(results_dir=tmp_path),
            manifest=_manifest(model_config={"temperature": 0, "max_tokens": None}),
        )
    assert client.calls == 0


def test_manifested_run_rejects_copied_checkpoint_rows(tmp_path: Path) -> None:
    client = CountingClient()
    cfg = RunnerConfig(results_dir=tmp_path)
    original = _manifest()
    changed = _manifest(prompt_hash=sha256_digest("changed"))

    results, _ = run(
        _dataset(), model=client, benchmark_name="noharm", config=cfg, manifest=original,
    )
    copied_path = (
        tmp_path / "raw" / "noharm" / changed.digest / "solver.jsonl"
    )
    copied_path.parent.mkdir(parents=True)
    copied_path.write_text(
        "\n".join(json.dumps(result.to_dict()) for result in results) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="contains manifest digest"):
        run(
            _dataset(), model=client, benchmark_name="noharm", config=cfg, manifest=changed,
        )


def test_benchmark_run_passes_manifest_to_runner(tmp_path: Path) -> None:
    benchmark = Benchmark(
        name="noharm",
        dataset=_dataset(),
        scorer=exact_match(),
        runner_config=RunnerConfig(results_dir=tmp_path),
    )

    results = benchmark.run(CountingClient(), manifest=_manifest())

    assert results.summary.manifest_digest == _manifest().digest
    assert results.summary.output_path.parent.name == _manifest().digest
    assert (
        tmp_path
        / "scores"
        / "noharm"
        / _manifest().digest
        / "solver.csv"
    ).is_file()


def test_benchmark_auto_manifest_namespaces_and_resumes(tmp_path: Path) -> None:
    client = CountingClient()
    benchmark = Benchmark(
        name="auto",
        dataset=_dataset(),
        scorer=exact_match(),
        runner_config=RunnerConfig(results_dir=tmp_path),
    )

    first = benchmark.run(client, auto_manifest=True, limit=1)
    second = benchmark.run(client, auto_manifest=True, limit=1)
    changed_config = benchmark.run(
        client,
        auto_manifest=True,
        limit=1,
        bootstrap=10,
    )
    seeded = benchmark.run(
        client,
        auto_manifest=True,
        limit=1,
        bootstrap=10,
        bootstrap_seed=7,
    )
    seeded_again = benchmark.run(
        client,
        auto_manifest=True,
        limit=1,
        bootstrap=10,
        bootstrap_seed=7,
    )

    assert first.summary.manifest_digest is not None
    assert first.summary.manifest_digest == second.summary.manifest_digest
    assert first.summary.output_path.parent.name == first.summary.manifest_digest
    assert first.summary.output_path.parent.joinpath("run-manifest.json").is_file()
    assert second.summary.skipped == 1
    assert changed_config.summary.manifest_digest != first.summary.manifest_digest
    assert changed_config.summary.skipped == 0
    assert seeded.summary.manifest_digest != changed_config.summary.manifest_digest
    assert seeded_again.summary.manifest_digest == seeded.summary.manifest_digest
    assert seeded_again.summary.skipped == 1
    manifest = json.loads(
        seeded.summary.output_path.parent.joinpath("run-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["model_config"]["bootstrap_seed"] == 7
    assert client.calls == 3


def test_reference_stub_is_keyless_and_manifested_as_stub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def provider_call_is_forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("stub/reference must not dispatch a provider call")

    monkeypatch.setattr(
        "arisekit.client.LiteLLMClient.__call__",
        provider_call_is_forbidden,
    )
    client = resolve_client(REFERENCE_STUB_MODEL)
    assert isinstance(client, ReferenceStubClient)
    direct = client(
        ModelCall(
            item=BenchmarkItem(
                id="direct",
                prompt="Contract test only.",
                ground_truth="reference-answer",
            )
        )
    )
    assert direct.text == "reference-answer"
    assert direct.cost == 0.0
    assert direct.cost_known is True
    assert direct.provider_model == REFERENCE_STUB_MODEL

    benchmark = Benchmark(
        name="stub-contract",
        dataset=Dataset.from_items(
            [
                {
                    "id": "a",
                    "prompt": "Return the reference answer.",
                    "ground_truth": "answer-a",
                },
                {
                    "id": "b",
                    "prompt": "Return the reference answer.",
                    "ground_truth": "answer-b",
                },
            ]
        ),
        scorer=exact_match(),
        runner_config=RunnerConfig(
            results_dir=tmp_path,
            require_known_cost=True,
        ),
    )

    results = benchmark.run(REFERENCE_STUB_MODEL, auto_manifest=True)

    assert [row.response for row in results.raw] == ["answer-a", "answer-b"]
    assert results.summary.completed == 2
    assert results.summary.errored == 0
    assert results.summary.cost_total == 0.0
    assert all(row.metadata["cost_known"] is True for row in results.raw)
    assert results.metrics[0].value == 1.0
    manifest = json.loads(
        (results.summary.output_path.parent / "run-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["model"] == REFERENCE_STUB_MODEL
    assert manifest["provider"] == "stub"
    assert manifest["model_config"]["route"] == REFERENCE_STUB_MODEL


def test_explicit_manifest_takes_precedence_over_auto_manifest(tmp_path: Path) -> None:
    benchmark = Benchmark(
        name="noharm",
        dataset=_dataset(),
        scorer=exact_match(),
        runner_config=RunnerConfig(results_dir=tmp_path),
    )
    explicit = _manifest()

    results = benchmark.run(
        CountingClient(),
        manifest=explicit,
        auto_manifest=True,
    )

    assert results.summary.manifest_digest == explicit.digest


def test_automatic_manifest_binds_every_load_bearing_component() -> None:
    items = list(_dataset())
    tool = Tool(
        name="lookup",
        description="Look up one value.",
        parameters={"type": "object", "properties": {}},
        fn=lambda: None,
    )

    def automatic(**overrides: object) -> RunManifest:
        values: dict[str, object] = {
            "benchmark_name": "auto",
            "items": items,
            "selected_item_ids": ["a"],
            "system_prompt": "system-v1",
            "tools": [tool],
            "code_objects": [CountingClient],
            "model": "solver",
            "model_route": "provider/solver-v1",
            "provider": "litellm",
            "trials": 1,
            "limit": 1,
            "model_config": {"temperature": 0.0, "max_tokens": 100},
        }
        values.update(overrides)
        return build_automatic_run_manifest(**values)  # type: ignore[arg-type]

    base = automatic()
    variants = [
        automatic(
            items=Dataset.from_items(
                [{"id": "a", "prompt": "changed"}, {"id": "b", "prompt": "qb"}]
            )
        ),
        automatic(system_prompt="system-v2"),
        automatic(
            tools=[
                Tool(
                    name="lookup",
                    description="Changed schema description.",
                    parameters=tool.parameters,
                    fn=tool.fn,
                )
            ]
        ),
        automatic(code_objects=[AlternateCodeIdentity]),
        automatic(model_route="provider/solver-v2"),
        automatic(trials=2),
        automatic(selected_item_ids=["a", "b"], limit=2),
        automatic(model_config={"temperature": 0.5, "max_tokens": 100}),
    ]

    assert all(variant.digest != base.digest for variant in variants)
    assert "tool_schema_hash" in base.to_dict()["model_config"]
    assert str(Path(__file__).resolve()) not in base.canonical_json()

    with pytest.raises(ValueError, match="cannot read source"):
        automatic(code_objects=[len])
