"""Vertical contract tests for build-spec v3 multimodal attachments."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from arisekit import cli
from arisekit.client import REFERENCE_STUB_MODEL
from arisekit.package import PackageAssetManifest, load_package
from arisekit.runnable import load_manifest as load_runnable_manifest
from arisekit.scaffold import (
    MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION,
    BenchmarkScaffoldSpec,
    ScaffoldError,
    ScaffoldSpecError,
    check_benchmark,
    scaffold_benchmark,
)


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    repository = Path(__file__).resolve().parents[1]
    source = repository / "examples" / "multimodal-golden-path"
    fixture = tmp_path / "fixture"
    shutil.copytree(source, fixture)
    return fixture, fixture / "authoring" / "benchmark-build-spec.json"


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_v3_plan_materializes_portable_image_package(tmp_path: Path) -> None:
    fixture, spec_path = _fixture(tmp_path)
    raw_spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec = BenchmarkScaffoldSpec.from_json(spec_path)

    assert spec.schema_version == MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION
    assert spec.to_dict() == raw_spec
    receipt = scaffold_benchmark(spec, output_root=tmp_path / "benchmarks")
    package = load_package(receipt.package_path, verify_assets=True)

    source_image = fixture / "authoring" / "attachments" / "synthetic-frontal.png"
    packaged_image = receipt.package_path / "attachments" / "synthetic-frontal.png"
    assert packaged_image.read_bytes() == source_image.read_bytes()
    assert package.items[0].attachments == [
        "attachments/synthetic-frontal.png"
    ]
    attachment_contract = json.loads(
        (receipt.package_path / "attachments.json").read_text(encoding="utf-8")
    )
    assert attachment_contract["schema_version"] == "arisekit.image-attachments.v1"
    assert attachment_contract["case_bindings"] == {
        "synthetic-frontal": ["attachments/synthetic-frontal.png"]
    }
    assert check_benchmark(
        receipt.root,
        verify_linked_provenance=True,
    ).compatible


def test_v3_cli_smoke_reaches_ready_without_bespoke_code(tmp_path: Path) -> None:
    fixture, spec_path = _fixture(tmp_path)
    assert not list(fixture.rglob("*.py"))
    benchmarks = tmp_path / "benchmarks"
    results = tmp_path / "results"
    common = ["--benchmarks-dir", str(benchmarks), "--results-dir", str(results)]

    assert cli.main([*common, "new-benchmark", "--spec", str(spec_path)]) == 0
    assert cli.main(
        [
            *common,
            "check-benchmark",
            "multimodal-golden-path",
            "--verify-linked-provenance",
        ]
    ) == 0
    assert cli.main(
        [
            *common,
            "eval",
            "multimodal-golden-path",
            "--model",
            REFERENCE_STUB_MODEL,
            "--limit",
            "1",
            "--trials",
            "1",
        ]
    ) == 0

    root = benchmarks / "multimodal-golden-path"
    runnable = load_runnable_manifest(root / "runnable-benchmark.json")
    assert runnable.readiness == "ready"
    assert runnable.smoke_test.status == "passed"
    assert (root / "package" / "attachments" / "synthetic-frontal.png").is_file()


@pytest.mark.parametrize(
    ("path", "media_type"),
    [
        ("../image.png", "image/png"),
        ("attachments/nested/image.png", "image/png"),
        ("attachments/image.svg", "image/svg+xml"),
        ("https://example.test/image.png", "image/png"),
    ],
)
def test_v3_rejects_unsafe_or_unsupported_asset_paths(
    tmp_path: Path,
    path: str,
    media_type: str,
) -> None:
    _, spec_path = _fixture(tmp_path)
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    payload["multimodal"]["assets"][0]["path"] = path
    payload["multimodal"]["assets"][0]["media_type"] = media_type
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldSpecError, match="flat PNG or JPEG"):
        BenchmarkScaffoldSpec.from_json(spec_path)


def test_v3_rejects_changed_image_before_materialization(tmp_path: Path) -> None:
    fixture, spec_path = _fixture(tmp_path)
    spec = BenchmarkScaffoldSpec.from_json(spec_path)
    image = fixture / "authoring" / "attachments" / "synthetic-frontal.png"
    image.write_bytes(image.read_bytes() + b"tampered")

    with pytest.raises(ScaffoldError, match="SHA-256 mismatch"):
        scaffold_benchmark(spec, output_root=tmp_path / "benchmarks")


def test_v3_ready_contract_rejects_non_structural_scorer(tmp_path: Path) -> None:
    _, spec_path = _fixture(tmp_path)
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    payload["scorer"] = {
        "kind": "contains",
        "primitive": "arisekit.scorer.contains",
        "options": {"case_sensitive": False, "name": "contains"},
    }
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldSpecError, match="requires exact-match"):
        BenchmarkScaffoldSpec.from_json(spec_path)


def test_v3_tampered_packaged_image_fails_strict_check(tmp_path: Path) -> None:
    _, spec_path = _fixture(tmp_path)
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    image = receipt.package_path / "attachments" / "synthetic-frontal.png"
    image.write_bytes(image.read_bytes() + b"tampered")

    report = check_benchmark(receipt.root)
    assert not report.compatible
    assert any(
        "asset" in issue.message.lower() or "attachment" in issue.message.lower()
        for issue in report.issues
    )


def test_v3_rejects_inventory_hash_that_does_not_match_bytes(tmp_path: Path) -> None:
    _, spec_path = _fixture(tmp_path)
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    payload["multimodal"]["assets"][0]["sha256"] = hashlib.sha256(
        b"different"
    ).hexdigest()
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldError, match="SHA-256 mismatch"):
        scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")


def test_v3_attachment_contract_is_covered_by_package_manifest(tmp_path: Path) -> None:
    _, spec_path = _fixture(tmp_path)
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    manifest = PackageAssetManifest.build(receipt.package_path)
    paths = {asset.path for asset in manifest.assets}

    assert "attachments.json" in paths
    assert "attachments/synthetic-frontal.png" in paths
