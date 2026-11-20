"""End-to-end: dataset + scorer + mock client -> CSV with the right shape."""

import base64
import csv
import hashlib
from pathlib import Path

import pytest

from arisekit import Benchmark, BenchmarkItem, Dataset, Tool, exact_match
from arisekit.agentic import AGENTIC_PASS_CONDITION_SCHEMA_VERSION
from arisekit.client import REFERENCE_STUB_MODEL, ModelCall, ModelResponse
from arisekit.env.fhir import FHIREnvironment, fhir_tools
from arisekit.package import (
    AGENTIC_FHIR_ENVIRONMENT,
    AGENTIC_FHIR_ENV_SCHEMA_VERSION,
    FHIR_TOOL_CATALOG_VERSION,
    IMAGE_ATTACHMENTS_SCHEMA_VERSION,
    BenchmarkManifest,
    write_package,
)
from arisekit.runner import RunnerConfig
from arisekit.sut import SUTResponse, SystemUnderTest
from arisekit.types import Trajectory


class CannedClient:
    model = "canned"

    def __init__(self, answers: dict[str, str]):
        self.answers = answers

    def __call__(self, call: ModelCall) -> ModelResponse:
        return ModelResponse(text=self.answers.get(call.item.id, ""), cost=0.0)


def test_benchmark_run_writes_scores_csv(tmp_path: Path):
    items = [
        BenchmarkItem(id="a", prompt="Capital of France?", ground_truth="paris"),
        BenchmarkItem(id="b", prompt="2+2?", ground_truth="4"),
        BenchmarkItem(id="c", prompt="Capital of Italy?", ground_truth="rome"),
    ]
    bench = Benchmark(
        name="canned-mcq",
        dataset=Dataset.from_items(items),
        scorer=exact_match(),
        runner_config=RunnerConfig(results_dir=tmp_path),
    )

    client = CannedClient({"a": "Paris", "b": "4", "c": "Florence"})
    results = bench.run(model=client)

    assert results.benchmark == "canned-mcq"
    assert results.model == "canned"
    assert results.summary.completed == 3
    # 2/3 correct.
    assert len(results.metrics) == 1
    assert abs(results.metrics[0].value - 2 / 3) < 1e-6

    # Scores CSV is written under results/scores/<bench>/<model>.csv.
    scores_csv = tmp_path / "scores" / "canned-mcq" / "canned.csv"
    assert scores_csv.exists()
    with scores_csv.open() as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["benchmark"] == "canned-mcq"
    assert rows[0]["metric"] == "accuracy"
    assert rows[0]["category"] == "overall"


def test_benchmark_run_respects_limit(tmp_path: Path):
    items = [BenchmarkItem(id=f"i{i}", prompt=f"Q{i}", ground_truth=f"Q{i}") for i in range(5)]
    bench = Benchmark(
        name="lim",
        dataset=Dataset.from_items(items),
        scorer=exact_match(),
        runner_config=RunnerConfig(results_dir=tmp_path),
    )
    client = CannedClient({f"i{i}": f"Q{i}" for i in range(5)})
    results = bench.run(model=client, limit=2)
    assert results.summary.completed == 2


def test_benchmark_with_tools_resolves_model_id_as_agent_sut(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    class FakeAgentSUT(SystemUnderTest):
        name = "fake-agent-model"

        def respond(self, item, **kwargs):
            return SUTResponse(
                response=Trajectory(
                    final_response="done",
                    total_tokens_in=1,
                    total_tokens_out=1,
                )
            )

    def fake_from_agent(
        model,
        tools,
        *,
        system_prompt=None,
        max_iters=8,
        name=None,
        temperature=None,
        max_tokens=None,
    ):
        captured.update(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            max_iters=max_iters,
            name=name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return FakeAgentSUT()

    monkeypatch.setattr(
        SystemUnderTest,
        "from_agent",
        staticmethod(fake_from_agent),
    )
    tool = Tool(
        name="lookup",
        description="Look up a value.",
        parameters={"type": "object", "properties": {}},
        fn=lambda: {"ok": True},
    )
    benchmark = Benchmark(
        name="agentic",
        dataset=Dataset.from_items(
            [BenchmarkItem(id="a", prompt="Do the task.", ground_truth="done")]
        ),
        scorer=exact_match(),
        runner_config=RunnerConfig(
            results_dir=tmp_path,
            temperature=0.25,
            max_tokens=321,
        ),
        tools=[tool],
        max_turns=5,
    )

    results = benchmark.run("provider/model")

    assert captured == {
        "model": "provider/model",
        "tools": [tool],
        "system_prompt": None,
        "max_iters": 5,
        "name": None,
        "temperature": 0.25,
        "max_tokens": 321,
    }
    assert results.model == "fake-agent-model"
    assert results.metrics[0].value == 1.0


def test_benchmark_with_tools_leaves_provided_sut_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class ProvidedSUT(SystemUnderTest):
        name = "provided"

        def respond(self, item, **kwargs):
            return SUTResponse(response="answer")

    def unexpected(*args, **kwargs):
        raise AssertionError("provided SUT must not be rebuilt as an agent")

    monkeypatch.setattr(SystemUnderTest, "from_agent", staticmethod(unexpected))
    benchmark = Benchmark(
        name="provided-sut",
        dataset=Dataset.from_items(
            [BenchmarkItem(id="a", prompt="Q", ground_truth="answer")]
        ),
        scorer=exact_match(),
        runner_config=RunnerConfig(results_dir=tmp_path),
        tools=[],
    )

    results = benchmark.run(ProvidedSUT())

    assert results.model == "provided"
    assert results.metrics[0].value == 1.0


def _write_agentic_package(root: Path, *, family: str = "Hernandez") -> Path:
    tool = next(
        tool
        for tool in fhir_tools(FHIREnvironment([]))
        if tool.name == "get_patient"
    )
    prompt = "Use the allowed FHIR tools before answering."
    item_id = "case-1"
    return write_package(
        root,
        manifest=BenchmarkManifest(
            id="agentic-fixture",
            name="Agentic fixture",
            version="0.1.0",
            modality="agentic-fhir",
            scorer={
                "kind": "pass-at-one",
                "name": "pass_at_1",
                "condition_schema": AGENTIC_PASS_CONDITION_SCHEMA_VERSION,
            },
            provenance={
                "build_spec": {
                    "schema_version": "arisekit.benchmark-build-spec.v2"
                },
                "source": {
                    "system_prompt": {
                        "text": prompt,
                        "sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    }
                },
                "data_governance": {
                    "classification": "synthetic",
                    "release_posture": "public",
                },
            },
        ),
        items=[
            BenchmarkItem(
                id=item_id,
                prompt="Look up patient p1.",
                ground_truth={
                    "schema_version": AGENTIC_PASS_CONDITION_SCHEMA_VERSION,
                    "required_tool_calls": [
                        {
                            "name": "get_patient",
                            "arguments": {"patient_id": "p1"},
                        }
                    ],
                    "final_response_contains": ["Hernandez"],
                },
            )
        ],
        env={
            "schema_version": AGENTIC_FHIR_ENV_SCHEMA_VERSION,
            "environment": AGENTIC_FHIR_ENVIRONMENT,
            "tool_catalog": FHIR_TOOL_CATALOG_VERSION,
            "allowed_tools": ["get_patient"],
            "max_turns": 3,
            "case_bindings": {item_id: f"cohort/{item_id}.fhir.json"},
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            ],
        },
        cohort_bundles=[
            {
                "resourceType": "Bundle",
                "id": item_id,
                "type": "collection",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Patient",
                            "id": "p1",
                            "name": [{"family": family}],
                        }
                    }
                ],
            }
        ],
        write_asset_manifest=True,
    )


def test_agentic_package_auto_binds_stub_runtime_and_scorer(tmp_path: Path):
    package_path = _write_agentic_package(tmp_path / "package")
    benchmark = Benchmark.from_package(package_path)

    results = benchmark.run(
        REFERENCE_STUB_MODEL,
        results_dir=tmp_path / "results",
        auto_manifest=True,
    )

    assert results.summary.completed == 1
    assert results.summary.errored == 0
    assert isinstance(results.raw[0].response, Trajectory)
    assert results.metrics[0].name == "pass_at_1"
    assert results.metrics[0].value == 1.0
    manifest = (
        results.summary.output_path.parent / "run-manifest.json"
    ).read_text(encoding="utf-8")
    assert '"provider": "stub"' in manifest
    assert '"package_asset_manifest_sha256"' in manifest


def test_agentic_package_cohort_bytes_change_run_identity(tmp_path: Path):
    first = Benchmark.from_package(
        _write_agentic_package(tmp_path / "package-a", family="Hernandez")
    ).run(
        REFERENCE_STUB_MODEL,
        results_dir=tmp_path / "results",
        auto_manifest=True,
    )
    second = Benchmark.from_package(
        _write_agentic_package(tmp_path / "package-b", family="Changed")
    ).run(
        REFERENCE_STUB_MODEL,
        results_dir=tmp_path / "results",
        auto_manifest=True,
    )

    assert first.summary.manifest_digest != second.summary.manifest_digest
    assert second.summary.skipped == 0


def _write_multimodal_package(root: Path) -> Path:
    payload = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    relative = "attachments/case-1.png"
    return write_package(
        root,
        manifest=BenchmarkManifest(
            id="multimodal-fixture",
            name="Multimodal fixture",
            modality="multimodal",
            scorer={"kind": "exact-match"},
        ),
        items=[
            BenchmarkItem(
                id="case-1",
                prompt="Write a short report.",
                ground_truth="Reference report",
                attachments=[relative],
            )
        ],
        attachments={
            "schema_version": IMAGE_ATTACHMENTS_SCHEMA_VERSION,
            "assets": [
                {
                    "path": relative,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                    "media_type": "image/png",
                }
            ],
            "case_bindings": {"case-1": [relative]},
        },
        attachment_assets={relative: payload},
        write_asset_manifest=True,
    )


def test_multimodal_package_rebases_images_only_for_model_dispatch(tmp_path: Path):
    package_path = _write_multimodal_package(tmp_path / "package")
    captured: list[str] = []

    class ImageClient:
        model = "image-client"

        def __call__(self, call: ModelCall) -> ModelResponse:
            captured.extend(call.item.attachments)
            assert all(Path(path).is_absolute() for path in call.item.attachments)
            assert all(Path(path).is_file() for path in call.item.attachments)
            return ModelResponse(text="Reference report")

    benchmark = Benchmark.from_package(package_path)
    assert benchmark.dataset[0].attachments == ["attachments/case-1.png"]

    results = benchmark.run(ImageClient(), results_dir=tmp_path / "results")

    assert results.summary.completed == 1
    assert results.metrics[0].value == 1.0
    assert captured == [str(package_path / "attachments" / "case-1.png")]
    assert benchmark.dataset[0].attachments == ["attachments/case-1.png"]


def test_multimodal_reference_stub_reads_and_encodes_bound_image(tmp_path: Path):
    package_path = _write_multimodal_package(tmp_path / "package")
    benchmark = Benchmark.from_package(package_path)
    image_path = package_path / "attachments" / "case-1.png"
    image_path.write_bytes(image_path.read_bytes() + b"changed")

    results = benchmark.run(
        REFERENCE_STUB_MODEL,
        results_dir=tmp_path / "results",
    )

    assert results.summary.completed == 0
    assert results.summary.errored == 1
    assert "size changed" in (results.raw[0].error or "")


def test_errored_run_result_contributes_zero_to_score(tmp_path: Path):
    class PartlyFailingClient:
        model = "partly-failing"

        def __call__(self, call: ModelCall) -> ModelResponse:
            if call.item.id == "bad":
                raise RuntimeError("model failure")
            return ModelResponse(text="correct")

    benchmark = Benchmark(
        name="failure-scoring",
        dataset=Dataset.from_items(
            [
                BenchmarkItem(id="good", prompt="Q", ground_truth="correct"),
                BenchmarkItem(id="bad", prompt="Q", ground_truth="correct"),
            ]
        ),
        scorer=exact_match(),
        runner_config=RunnerConfig(
            results_dir=tmp_path,
            max_retries=1,
            retry_backoff=0.0,
        ),
    )

    results = benchmark.run(PartlyFailingClient())

    assert results.summary.completed == 1
    assert results.summary.errored == 1
    assert {item_id for item_id, _ in results.per_item} == {"good", "bad"}
    assert results.metrics[0].n == 2
    assert results.metrics[0].value == 0.5


@pytest.mark.parametrize("max_turns", [0, -1, True, 1.5])
def test_benchmark_rejects_invalid_max_turns(max_turns):
    with pytest.raises(ValueError, match="max_turns"):
        Benchmark(
            name="invalid-turns",
            dataset=Dataset.from_items([]),
            scorer=exact_match(),
            max_turns=max_turns,
        )
