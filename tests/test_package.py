"""Contract tests for the benchmark package.

The package is the portable artifact ARISEKit emits and a runtime imports.
These tests lock the on-disk round-trip (write_package then load_package) and
the two binders that turn a loaded package back into runnable pieces
(dataset_from_package, scorer_from_manifest), so the artifact stays readable
across the author/runtime seam. Everything here is offline: no client, no
network.
"""

import base64
import hashlib
from pathlib import Path

import pytest

from arisekit import BenchmarkItem, RunResult
from arisekit.agentic import AGENTIC_PASS_CONDITION_SCHEMA_VERSION, PassAtOneScorer
from arisekit.env.fhir import FHIREnvironment, fhir_tools
from arisekit.package import (
    AGENTIC_FHIR_ENVIRONMENT,
    AGENTIC_FHIR_ENV_SCHEMA_VERSION,
    FHIR_TOOL_CATALOG_VERSION,
    IMAGE_ATTACHMENTS_SCHEMA_VERSION,
    BenchmarkManifest,
    BenchmarkPackage,
    agentic_fhir_binding_from_package,
    dataset_from_package,
    load_package,
    multimodal_image_binding_from_package,
    scorer_from_manifest,
    write_package,
)


SAMPLE_PACKAGE = Path(__file__).parent / "data" / "sample_package"

_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _manifest(**overrides: object) -> BenchmarkManifest:
    base: dict[str, object] = {
        "id": "demo-text",
        "name": "Demo text benchmark",
        "version": "0.1.0",
        "modality": "text",
        "scorer": {"kind": "exact-match"},
    }
    base.update(overrides)
    return BenchmarkManifest.from_dict(base)


def test_write_then_load_round_trips(tmp_path: Path):
    manifest = _manifest(provenance={"author": "unit-test"})
    items = [
        BenchmarkItem(id="a", prompt="What is 2+2?", ground_truth="4"),
        BenchmarkItem(
            id="b",
            prompt="Capital of France?",
            ground_truth="Paris",
            metadata={"specialty": "geography"},
        ),
    ]
    rubric = {"scale": [0, 1], "criteria": [{"id": "accuracy", "weight": 1.0}]}

    root = write_package(
        tmp_path / "pkg",
        manifest=manifest,
        items=items,
        rubric=rubric,
    )
    assert root == tmp_path / "pkg"
    assert (root / "benchmark.json").is_file()
    assert (root / "cases.jsonl").is_file()

    pkg = load_package(root)
    assert isinstance(pkg, BenchmarkPackage)
    assert pkg.manifest.id == "demo-text"
    assert pkg.manifest.name == "Demo text benchmark"
    assert pkg.manifest.modality == "text"
    assert pkg.manifest.provenance == {"author": "unit-test"}
    assert [i.id for i in pkg.items] == ["a", "b"]
    assert pkg.items[1].metadata == {"specialty": "geography"}
    assert pkg.items[1].ground_truth == "Paris"
    assert pkg.rubric == rubric
    assert pkg.env is None
    assert pkg.cohort == []
    assert pkg.root == root


def test_write_package_persists_env_cohort_and_readme(tmp_path: Path):
    manifest = _manifest(
        id="agentic-demo",
        modality="agentic-fhir",
        scorer={"kind": "trajectory-judge"},
    )
    env = {"tools": ["fhir_read", "fhir_search"], "cohort": "cohort/"}
    bundles = [
        {"resourceType": "Bundle", "id": "patient-001", "entry": []},
        {"resourceType": "Bundle", "entry": []},
    ]
    root = write_package(
        tmp_path / "agentic",
        manifest=manifest,
        items=[BenchmarkItem(id="t1", prompt="Order the morning labs.")],
        env=env,
        cohort_bundles=bundles,
        readme="# Agentic demo\n",
    )
    assert (root / "env.json").is_file()
    assert (root / "README.md").read_text(encoding="utf-8").startswith("# Agentic demo")
    assert (root / "cohort" / "patient-001.fhir.json").is_file()
    # The second bundle has no id, so it falls back to a positional name.
    assert (root / "cohort" / "bundle-1.fhir.json").is_file()

    pkg = load_package(root)
    assert pkg.env == env
    assert len(pkg.cohort) == 2
    assert all(p.name.endswith(".fhir.json") for p in pkg.cohort)


def test_dataset_from_package_matches_items(tmp_path: Path):
    manifest = _manifest()
    items = [BenchmarkItem(id=f"q{i}", prompt=f"Q{i}") for i in range(4)]
    root = write_package(tmp_path / "pkg", manifest=manifest, items=items)

    ds = dataset_from_package(root, system_prompt="You are a tutor.")
    assert len(ds) == 4
    assert ds[0].id == "q0"
    assert ds.system_prompt == "You are a tutor."
    assert ds.name == "demo-text"


def test_dataset_from_package_accepts_loaded_package(tmp_path: Path):
    manifest = _manifest()
    root = write_package(
        tmp_path / "pkg",
        manifest=manifest,
        items=[BenchmarkItem(id="only", prompt="Q")],
    )
    pkg = load_package(root)
    ds = dataset_from_package(pkg)
    assert ds[0].id == "only"


def _multimodal_package(tmp_path: Path) -> BenchmarkPackage:
    relative = "attachments/case-1.png"
    digest = hashlib.sha256(_ONE_PIXEL_PNG).hexdigest()
    root = write_package(
        tmp_path / "multimodal-package",
        manifest=_manifest(
            id="multimodal-package",
            modality="multimodal",
            scorer={"kind": "exact-match"},
        ),
        items=[
            BenchmarkItem(
                id="case-1",
                prompt="Describe the image.",
                ground_truth="Reference report",
                attachments=[relative],
            )
        ],
        attachments={
            "schema_version": IMAGE_ATTACHMENTS_SCHEMA_VERSION,
            "assets": [
                {
                    "path": relative,
                    "sha256": digest,
                    "size_bytes": len(_ONE_PIXEL_PNG),
                    "media_type": "image/png",
                }
            ],
            "case_bindings": {"case-1": [relative]},
        },
        attachment_assets={relative: _ONE_PIXEL_PNG},
        write_asset_manifest=True,
    )
    return load_package(root, verify_assets=True)


def test_multimodal_package_writes_and_binds_strict_image_assets(tmp_path: Path):
    pkg = _multimodal_package(tmp_path)

    assert pkg.attachments is not None
    assert [path.name for path in pkg.attachment_files] == ["case-1.png"]
    assert pkg.asset_manifest is not None
    inventory = {asset.path for asset in pkg.asset_manifest.assets}
    assert "attachments.json" in inventory
    assert "attachments/case-1.png" in inventory

    binding = multimodal_image_binding_from_package(pkg)
    asset = binding.assets["attachments/case-1.png"]
    assert asset.file_path == pkg.root / "attachments" / "case-1.png"
    assert asset.media_type == "image/png"
    assert binding.case_bindings == {
        "case-1": ("attachments/case-1.png",)
    }


def test_multimodal_binding_rejects_changed_image_bytes(tmp_path: Path):
    pkg = _multimodal_package(tmp_path)
    pkg.attachment_files[0].write_bytes(_ONE_PIXEL_PNG + b"changed")

    with pytest.raises(ValueError, match="size mismatch"):
        multimodal_image_binding_from_package(pkg)


def test_multimodal_binding_rejects_case_binding_drift(tmp_path: Path):
    pkg = _multimodal_package(tmp_path)
    pkg.items[0].attachments = []

    with pytest.raises(ValueError, match="do not match"):
        multimodal_image_binding_from_package(pkg)


def test_write_package_rejects_non_image_attachment_bytes(tmp_path: Path):
    relative = "attachments/not-an-image.png"
    payload = b"not an image"
    digest = hashlib.sha256(payload).hexdigest()

    with pytest.raises(ValueError, match="bytes do not match"):
        write_package(
            tmp_path / "bad-multimodal",
            manifest=_manifest(modality="multimodal"),
            items=[
                BenchmarkItem(
                    id="case-1",
                    prompt="Q",
                    ground_truth="A",
                    attachments=[relative],
                )
            ],
            attachments={
                "schema_version": IMAGE_ATTACHMENTS_SCHEMA_VERSION,
                "assets": [
                    {
                        "path": relative,
                        "sha256": digest,
                        "size_bytes": len(payload),
                        "media_type": "image/png",
                    }
                ],
                "case_bindings": {"case-1": [relative]},
            },
            attachment_assets={relative: payload},
        )


def test_multimodal_package_rejects_more_than_four_images_per_case(
    tmp_path: Path,
):
    paths = [f"attachments/image-{index}.png" for index in range(5)]
    assets = [
        {
            "path": path,
            "sha256": hashlib.sha256(_ONE_PIXEL_PNG).hexdigest(),
            "size_bytes": len(_ONE_PIXEL_PNG),
            "media_type": "image/png",
        }
        for path in paths
    ]

    with pytest.raises(ValueError, match="1-4 image paths"):
        write_package(
            tmp_path / "too-many-images",
            manifest=_manifest(modality="multimodal"),
            items=[
                BenchmarkItem(
                    id="case-1",
                    prompt="Q",
                    ground_truth="A",
                    attachments=paths,
                )
            ],
            attachments={
                "schema_version": IMAGE_ATTACHMENTS_SCHEMA_VERSION,
                "assets": assets,
                "case_bindings": {"case-1": paths},
            },
            attachment_assets={path: _ONE_PIXEL_PNG for path in paths},
        )


def test_multimodal_package_rejects_unsafe_flat_filename(tmp_path: Path):
    relative = "attachments/not safe.png"

    with pytest.raises(ValueError, match="flat lowercase PNG/JPEG"):
        write_package(
            tmp_path / "unsafe-image-name",
            manifest=_manifest(modality="multimodal"),
            items=[
                BenchmarkItem(
                    id="case-1",
                    prompt="Q",
                    ground_truth="A",
                    attachments=[relative],
                )
            ],
            attachments={
                "schema_version": IMAGE_ATTACHMENTS_SCHEMA_VERSION,
                "assets": [
                    {
                        "path": relative,
                        "sha256": hashlib.sha256(_ONE_PIXEL_PNG).hexdigest(),
                        "size_bytes": len(_ONE_PIXEL_PNG),
                        "media_type": "image/png",
                    }
                ],
                "case_bindings": {"case-1": [relative]},
            },
            attachment_assets={relative: _ONE_PIXEL_PNG},
        )


def test_scorer_from_manifest_binds_exact_match():
    scorer = scorer_from_manifest(_manifest(scorer={"kind": "exact-match"}))
    assert scorer is not None
    item = BenchmarkItem(id="x", prompt="Q", ground_truth="Paris")
    responses = [RunResult(id="x", trial=1, response="paris")]
    metrics = scorer.score_item(item, responses)
    assert metrics[0].value == 1.0


def test_scorer_from_manifest_forwards_choice_options():
    scorer = scorer_from_manifest(
        _manifest(scorer={"kind": "choice", "choices": ["A", "B", "C"]})
    )
    assert scorer is not None
    item = BenchmarkItem(id="x", prompt="Q", ground_truth="B")
    metrics = scorer.score_item(item, [RunResult(id="x", trial=1, response="B")])
    assert metrics[0].value == 1.0


def test_scorer_from_manifest_returns_none_only_for_client_bound_kinds():
    assert scorer_from_manifest(_manifest(scorer={"kind": "trajectory-judge"})) is None
    assert scorer_from_manifest(_manifest(scorer={"kind": "rubric-panel"})) is None


def test_scorer_from_manifest_binds_versioned_pass_at_one():
    scorer = scorer_from_manifest(
        _manifest(
            modality="agentic-fhir",
            scorer={
                "kind": "pass-at-one",
                "name": "pass_at_1",
                "condition_schema": AGENTIC_PASS_CONDITION_SCHEMA_VERSION,
            },
        )
    )

    assert isinstance(scorer, PassAtOneScorer)
    assert scorer.condition_schema == AGENTIC_PASS_CONDITION_SCHEMA_VERSION


def test_manifest_validate_accepts_good_manifest():
    _manifest().validate()  # does not raise


def test_manifest_validate_rejects_missing_id():
    with pytest.raises(ValueError):
        _manifest(id="").validate()


def test_manifest_validate_rejects_unknown_modality():
    with pytest.raises(ValueError):
        _manifest(modality="hologram").validate()


def test_load_package_reads_committed_fixture():
    pkg = load_package(SAMPLE_PACKAGE)
    assert pkg.manifest.id == "sample-text-exact"
    assert pkg.manifest.scorer["kind"] == "exact-match"
    assert len(pkg.items) == 2
    assert pkg.items[0].id == "c1"
    assert pkg.rubric is not None
    assert pkg.rubric["criteria"][0]["id"] == "exact_answer"

    scorer = scorer_from_manifest(pkg.manifest)
    assert scorer is not None
    metrics = scorer.score_item(
        pkg.items[0],
        [RunResult(id="c1", trial=1, response="Paris")],
    )
    assert metrics[0].value == 1.0


def test_load_package_rejects_duplicate_manifest_keys(tmp_path: Path):
    root = write_package(
        tmp_path / "pkg",
        manifest=_manifest(),
        items=[BenchmarkItem(id="only", prompt="Q")],
    )
    (root / "benchmark.json").write_text(
        '{"id":"one","id":"two"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON key 'id'"):
        load_package(root)


def test_load_package_rejects_nonfinite_case_values(tmp_path: Path):
    root = write_package(
        tmp_path / "pkg",
        manifest=_manifest(),
        items=[BenchmarkItem(id="only", prompt="Q")],
    )
    (root / "cases.jsonl").write_text(
        '{"id":"only","prompt":"Q","metadata":{"value":NaN},'
        '"ground_truth":null,"attachments":[]}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non-finite JSON number NaN"):
        load_package(root)


def _tool_schema(name: str) -> dict:
    tool = next(
        tool
        for tool in fhir_tools(FHIREnvironment([]))
        if tool.name == name
    )
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
    }


def _agentic_package(tmp_path: Path) -> BenchmarkPackage:
    item_id = "case-1"
    env = {
        "schema_version": AGENTIC_FHIR_ENV_SCHEMA_VERSION,
        "environment": AGENTIC_FHIR_ENVIRONMENT,
        "tool_catalog": FHIR_TOOL_CATALOG_VERSION,
        "allowed_tools": ["get_patient"],
        "max_turns": 3,
        "case_bindings": {item_id: f"cohort/{item_id}.fhir.json"},
        "tools": [_tool_schema("get_patient")],
    }
    root = write_package(
        tmp_path / "agentic-package",
        manifest=_manifest(
            id="agentic-package",
            modality="agentic-fhir",
            scorer={
                "kind": "pass-at-one",
                "name": "pass_at_1",
                "condition_schema": AGENTIC_PASS_CONDITION_SCHEMA_VERSION,
            },
        ),
        items=[
            BenchmarkItem(
                id=item_id,
                prompt="Look up the synthetic patient.",
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
        env=env,
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
                            "name": [{"family": "Hernandez"}],
                        }
                    }
                ],
            }
        ],
        write_asset_manifest=True,
    )
    return load_package(root, verify_assets=True)


def test_agentic_fhir_binding_validates_environment_tools_and_cohort(tmp_path: Path):
    binding = agentic_fhir_binding_from_package(_agentic_package(tmp_path))

    assert binding.allowed_tools == ("get_patient",)
    assert binding.max_turns == 3
    assert binding.bundles["case-1"]["resourceType"] == "Bundle"
    assert binding.tools == (_tool_schema("get_patient"),)


def test_agentic_fhir_binding_rejects_tool_schema_drift(tmp_path: Path):
    pkg = _agentic_package(tmp_path)
    assert pkg.env is not None
    pkg.env["tools"][0]["description"] = "changed"

    with pytest.raises(ValueError, match="tool schemas do not match"):
        agentic_fhir_binding_from_package(pkg)


def test_agentic_fhir_binding_rejects_incomplete_case_bindings(tmp_path: Path):
    pkg = _agentic_package(tmp_path)
    assert pkg.env is not None
    pkg.env["case_bindings"] = {}

    with pytest.raises(ValueError, match="cover every item exactly"):
        agentic_fhir_binding_from_package(pkg)
