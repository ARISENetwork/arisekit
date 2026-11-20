from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from arisekit.runnable import (
    FILENAME,
    authorize_run_request,
    build_manifest_for_directory,
    load_manifest,
    record_smoke_test,
    verify_assets,
    write_manifest,
)


def _fixture(root: Path, *, origin: str = "builder"):
    (root / "package").mkdir(parents=True)
    (root / "build.py").write_text("def build():\n    return None\n", encoding="utf-8")
    (root / "package" / "cases.jsonl").write_text(
        json.dumps({"id": "case-1", "prompt": "Q"}) + "\n",
        encoding="utf-8",
    )
    manifest = build_manifest_for_directory(
        root,
        benchmark_id="fixture",
        benchmark_version="1.2.3",
        origin=origin,
        entry_point="build.py:build",
        dataset_path="package/cases.jsonl",
        scorer={"kind": "exact-match"},
        source_revision="git:abc123",
        smoke_model="provider/model",
        smoke_limit=2,
        smoke_trials=1,
        build_spec_sha256="a" * 64 if origin == "builder" else None,
        environment={"python": ">=3.10", "arisekit": "test"},
    )
    write_manifest(root / FILENAME, manifest)
    return manifest


def test_builder_manifest_gates_normal_runs_until_smoke_passes(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path / "benchmark")

    with pytest.raises(ValueError, match="exact planned smoke test"):
        authorize_run_request(
            manifest,
            model="provider/model",
            limit=None,
            trials=1,
        )
    assert authorize_run_request(
        manifest,
        model="provider/model",
        limit=2,
        trials=1,
    ) == "smoke"

    result_root = tmp_path / "results"
    bundle = result_root / "run-results.json"
    bundle.parent.mkdir()
    bundle.write_text('{"status":"complete"}\n', encoding="utf-8")
    updated = record_smoke_test(
        tmp_path / "benchmark" / FILENAME,
        root=result_root,
        result_bundle_path=bundle,
        run_manifest_digest="b" * 64,
        completed=2,
        errored=0,
    )

    assert updated.readiness == "ready"
    assert updated.smoke_test.status == "passed"
    assert updated.smoke_test.result_bundle_sha256 == hashlib.sha256(
        bundle.read_bytes()
    ).hexdigest()
    assert authorize_run_request(
        updated,
        model="another/model",
        limit=None,
        trials=4,
    ) == "run"
    assert load_manifest(tmp_path / "benchmark" / FILENAME) == updated
    evidence = result_root / updated.smoke_test.result_bundle_path
    assert evidence != bundle
    original = evidence.read_bytes()
    bundle.write_text('{"status":"resumed"}\n', encoding="utf-8")
    assert evidence.read_bytes() == original
    assert hashlib.sha256(original).hexdigest() == updated.smoke_test.result_bundle_sha256


def test_manifest_verifies_runtime_bytes_and_supports_roster_adapter(tmp_path: Path) -> None:
    root = tmp_path / "roster"
    manifest = _fixture(root, origin="curated-roster")
    verify_assets(root, manifest)

    (root / "build.py").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="(?:size|digest) changed"):
        verify_assets(root, manifest)


def test_failed_smoke_blocks_dispatch(tmp_path: Path) -> None:
    root = tmp_path / "benchmark"
    _fixture(root)
    result_root = tmp_path / "results"
    bundle = result_root / "run-results.json"
    bundle.parent.mkdir()
    bundle.write_text("{}\n", encoding="utf-8")
    updated = record_smoke_test(
        root / FILENAME,
        root=result_root,
        result_bundle_path=bundle,
        run_manifest_digest=None,
        completed=1,
        errored=1,
    )
    assert updated.readiness == "blocked"
    with pytest.raises(ValueError, match="failed smoke test"):
        authorize_run_request(updated, model="provider/model", limit=2, trials=1)


def test_curated_roster_adapter_reaches_ready_run_results_through_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arisekit import cli
    from arisekit.client import ModelResponse

    benchmarks_dir = tmp_path / "benchmarks"
    root = benchmarks_dir / "roster-fixture"
    root.mkdir(parents=True)
    (root / "dataset.jsonl").write_text(
        json.dumps(
            {
                "id": "case-1",
                "prompt": "answer",
                "ground_truth": "answer",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "build.py").write_text(
        "from pathlib import Path\n"
        "from arisekit import Benchmark, Dataset, exact_match\n\n"
        "def build():\n"
        "    root = Path(__file__).parent\n"
        "    return Benchmark(\n"
        "        name='roster-fixture',\n"
        "        dataset=Dataset.from_jsonl(root / 'dataset.jsonl'),\n"
        "        scorer=exact_match(),\n"
        "    )\n",
        encoding="utf-8",
    )
    manifest = build_manifest_for_directory(
        root,
        benchmark_id="roster-fixture",
        benchmark_version="1.0.0",
        origin="curated-roster",
        entry_point="build.py:build",
        dataset_path="dataset.jsonl",
        scorer={"kind": "exact-match"},
        source_revision="git:roster-fixture",
        smoke_model="provider/model",
        smoke_limit=1,
        smoke_trials=1,
        environment={"python": ">=3.10", "arisekit": "test"},
    )
    write_manifest(root / FILENAME, manifest)

    class EchoClient:
        model = "provider/model"

        def __call__(self, call):
            return ModelResponse(text=str(call.item.prompt), cost=0.0)

    monkeypatch.setattr("arisekit.sut.resolve_client", lambda spec: EchoClient())
    results_dir = tmp_path / "results"
    common = [
        "--benchmarks-dir",
        str(benchmarks_dir),
        "--results-dir",
        str(results_dir),
        "eval",
        "roster-fixture",
        "--model",
        "provider/model",
    ]
    assert cli.main([*common, "--limit", "1", "--trials", "1"]) == 0
    assert load_manifest(root / FILENAME).readiness == "ready"
    assert cli.main(common) == 0

    reports = list(results_dir.glob("run-results/**/run-results.md"))
    assert len(reports) == 2
    assert "roster-fixture" in reports[-1].read_text(encoding="utf-8")
