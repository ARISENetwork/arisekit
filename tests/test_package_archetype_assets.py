"""Strict archetype sidecar and asset-integrity package tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arisekit.package import (
    ASSET_MANIFEST_FILENAME,
    BenchmarkManifest,
    PackageAsset,
    PackageAssetError,
    PackageAssetManifest,
    PackageVerificationError,
    load_package,
    write_package,
)
from arisekit.types import BenchmarkItem


def _manifest() -> BenchmarkManifest:
    return BenchmarkManifest(
        id="noharm-style-demo",
        name="NOHARM-style demo",
        version="0.1.0",
        modality="rubric",
        scorer={"kind": "rubric-panel"},
        provenance={"source": "synthetic-test"},
    )


def _write_strict_package(root: Path, **overrides: object) -> Path:
    kwargs: dict[str, object] = {
        "manifest": _manifest(),
        "items": [
            BenchmarkItem(id="Case001", prompt="Base case"),
            BenchmarkItem(
                id="Case001-0",
                prompt="Variant case",
                metadata={"base_id": "Case001", "perturb_id": 0},
            ),
        ],
        "rubric": {"legacy": True},
        "env": {"kind": "none"},
        "cohort_bundles": [
            {"resourceType": "Bundle", "id": "cohort-one", "entry": []}
        ],
        "readme": "# Test package\n",
        "blueprint": {
            "schema_version": "1",
            "archetype": "noharm",
            "construct": {"target": "management safety"},
        },
        "opportunity": {"schema_version": "opportunity-v2", "id": "gap-1"},
        "stress_spec": {"schema_version": "stress-v2", "id": "stress-1"},
        "stress_validation": {
            "schema_version": "stress-validation-v2",
            "verdict": "inconclusive",
        },
        "variants": [
            {
                "id": "Case001-0",
                "base_id": "Case001",
                "perturb_id": 0,
                "invariance": "clinical action set unchanged",
            }
        ],
        "rubrics": {
            "Case001": {
                "id": "Case001",
                "options": [{"id": 1, "score": 9, "text": "Required action"}],
            }
        },
        "guidance": {
            "Case001": "version: 1\r\nrule: preserve-this-newline-form"
        },
        "judge_assets": {
            "prompts/match.md": "Match prompt\n",
            "schemas/match.schema.json": b'{"type":"object"}\n',
            "fixtures/binary.dat": b"\x00\x01\xff",
        },
        "review_log": [
            {
                "event": "clinical-lock",
                "case_id": "Case001",
                "reviewer": "test-reviewer",
            }
        ],
        "write_asset_manifest": True,
    }
    kwargs.update(overrides)
    return write_package(root, **kwargs)  # type: ignore[arg-type]


def test_strict_archetype_package_round_trip(tmp_path: Path):
    root = _write_strict_package(tmp_path / "package")
    package = load_package(root, verify_assets=True)

    assert package.manifest.id == "noharm-style-demo"
    assert [item.id for item in package.items] == ["Case001", "Case001-0"]
    assert package.rubric == {"legacy": True}
    assert package.env == {"kind": "none"}
    assert [path.name for path in package.cohort] == ["cohort-one.fhir.json"]
    assert package.blueprint == {
        "archetype": "noharm",
        "construct": {"target": "management safety"},
        "schema_version": "1",
    }
    assert package.opportunity == {
        "id": "gap-1",
        "schema_version": "opportunity-v2",
    }
    assert package.stress_spec == {
        "id": "stress-1",
        "schema_version": "stress-v2",
    }
    assert package.stress_validation == {
        "schema_version": "stress-validation-v2",
        "verdict": "inconclusive",
    }
    assert package.variants[0]["invariance"] == "clinical action set unchanged"
    assert package.rubrics["Case001"]["options"][0]["score"] == 9
    assert package.guidance["Case001"] == (
        "version: 1\r\nrule: preserve-this-newline-form"
    )
    assert package.judge_assets == {
        "fixtures/binary.dat": b"\x00\x01\xff",
        "prompts/match.md": b"Match prompt\n",
        "schemas/match.schema.json": b'{"type":"object"}\n',
    }
    assert package.review_log == [
        {
            "case_id": "Case001",
            "event": "clinical-lock",
            "reviewer": "test-reviewer",
        }
    ]

    assert isinstance(package.asset_manifest, PackageAssetManifest)
    declared = [asset.path for asset in package.asset_manifest.assets]
    assert declared == sorted(declared)
    assert "benchmark.json" in declared
    assert "cases.jsonl" in declared
    assert "blueprint.json" in declared
    assert "opportunity.json" in declared
    assert "stress-spec.json" in declared
    assert "stress-validation.json" in declared
    assert "variants.jsonl" in declared
    assert "rubrics/Case001.json" in declared
    assert "guidance/Case001.yaml" in declared
    assert "judge/prompts/match.md" in declared
    assert "review-log.jsonl" in declared
    assert ASSET_MANIFEST_FILENAME not in declared


def test_guidance_is_preserved_as_raw_utf8_text(tmp_path: Path):
    text = "first: line\r\nsecond: line\nno-final-newline"
    root = _write_strict_package(
        tmp_path / "package",
        guidance={"Case001": text},
    )

    assert (root / "guidance" / "Case001.yaml").read_bytes() == text.encode("utf-8")
    assert load_package(root, verify_assets=True).guidance["Case001"] == text


def test_new_json_assets_have_stable_hashes_across_mapping_order(tmp_path: Path):
    first = _write_strict_package(
        tmp_path / "first",
        blueprint={"z": 3, "a": {"y": 2, "b": 1}},
        opportunity={"z": 3, "a": {"y": 2, "b": 1}},
        stress_spec={"z": 3, "a": {"y": 2, "b": 1}},
        stress_validation={"z": 3, "a": {"y": 2, "b": 1}},
        rubrics={"Case001": {"z": 3, "a": 1}},
    )
    second = _write_strict_package(
        tmp_path / "second",
        blueprint={"a": {"b": 1, "y": 2}, "z": 3},
        opportunity={"a": {"b": 1, "y": 2}, "z": 3},
        stress_spec={"a": {"b": 1, "y": 2}, "z": 3},
        stress_validation={"a": {"b": 1, "y": 2}, "z": 3},
        rubrics={"Case001": {"a": 1, "z": 3}},
    )

    first_manifest = PackageAssetManifest.from_dict(
        json.loads((first / ASSET_MANIFEST_FILENAME).read_text(encoding="utf-8"))
    )
    second_manifest = PackageAssetManifest.from_dict(
        json.loads((second / ASSET_MANIFEST_FILENAME).read_text(encoding="utf-8"))
    )
    first_hashes = {asset.path: asset.sha256 for asset in first_manifest.assets}
    second_hashes = {asset.path: asset.sha256 for asset in second_manifest.assets}

    assert first_hashes == second_hashes
    assert (first / ASSET_MANIFEST_FILENAME).read_bytes() == (
        second / ASSET_MANIFEST_FILENAME
    ).read_bytes()


def test_strict_load_requires_asset_manifest(tmp_path: Path):
    root = write_package(
        tmp_path / "legacy",
        manifest=_manifest(),
        items=[BenchmarkItem(id="one", prompt="Question")],
    )
    assert load_package(root).asset_manifest is None

    with pytest.raises(PackageVerificationError, match="requires asset-manifest.json"):
        load_package(root, verify_assets=True)


def test_strict_load_rejects_hash_mismatch_but_nonstrict_load_remains_available(
    tmp_path: Path,
):
    root = _write_strict_package(
        tmp_path / "package", guidance={"Case001": "abc"}
    )
    (root / "guidance" / "Case001.yaml").write_bytes(b"abd")

    assert load_package(root).guidance["Case001"] == "abd"
    with pytest.raises(PackageVerificationError, match="hash mismatch"):
        load_package(root, verify_assets=True)


def test_strict_load_rejects_missing_declared_asset(tmp_path: Path):
    root = _write_strict_package(tmp_path / "package")
    (root / "rubrics" / "Case001.json").unlink()

    with pytest.raises(PackageVerificationError, match="declares missing files"):
        load_package(root, verify_assets=True)


def test_strict_load_rejects_undeclared_extra_asset(tmp_path: Path):
    root = _write_strict_package(tmp_path / "package")
    (root / "unexpected.txt").write_text("not declared", encoding="utf-8")

    with pytest.raises(PackageVerificationError, match="undeclared files"):
        load_package(root, verify_assets=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rubrics", {"../escape": {"id": "bad"}}),
        ("guidance", {"../../escape": "bad"}),
        ("judge_assets", {"../escape.py": "bad"}),
        ("judge_assets", {"/tmp/escape.py": "bad"}),
    ],
)
def test_writer_rejects_asset_path_traversal(
    tmp_path: Path,
    field: str,
    value: object,
):
    with pytest.raises(PackageAssetError, match="unsafe package asset"):
        _write_strict_package(tmp_path / "package", **{field: value})

    assert not (tmp_path / "escape").exists()


def test_manifest_rejects_traversal_without_opening_declared_path(tmp_path: Path):
    root = write_package(
        tmp_path / "package",
        manifest=_manifest(),
        items=[BenchmarkItem(id="one", prompt="Question")],
    )
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (root / ASSET_MANIFEST_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": "1",
                "algorithm": "sha256",
                "assets": [
                    {"path": "../secret.txt", "sha256": "0" * 64, "size": 6}
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PackageAssetError, match="unsafe package asset path"):
        load_package(root)


def test_strict_manifest_must_declare_core_package_files(tmp_path: Path):
    root = write_package(
        tmp_path / "package",
        manifest=_manifest(),
        items=[BenchmarkItem(id="one", prompt="Question")],
    )
    manifest = PackageAssetManifest.build(root, paths=["benchmark.json"])
    (root / "cases.jsonl").unlink()
    (root / ASSET_MANIFEST_FILENAME).write_text(
        json.dumps(manifest.to_dict()), encoding="utf-8"
    )

    with pytest.raises(PackageVerificationError, match="omits required package files"):
        load_package(root, verify_assets=True)


def test_strict_load_rejects_symlinked_asset(tmp_path: Path):
    root = _write_strict_package(tmp_path / "package")
    asset = root / "judge" / "prompts" / "match.md"
    outside = tmp_path / "outside.md"
    outside.write_text("outside secret", encoding="utf-8")
    asset.unlink()
    try:
        asset.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(PackageAssetError, match="symlink"):
        load_package(root, verify_assets=True)


def test_writer_refuses_to_manifest_stale_files(tmp_path: Path):
    root = tmp_path / "package"
    root.mkdir()
    (root / "stale-private-note.txt").write_text("do not include", encoding="utf-8")

    with pytest.raises(PackageAssetError, match="stale package files"):
        _write_strict_package(root)
    assert not (root / ASSET_MANIFEST_FILENAME).exists()


def test_asset_manifest_type_rejects_unsorted_duplicate_and_invalid_entries():
    a = PackageAsset(path="a.txt", sha256="0" * 64, size=0)
    b = PackageAsset(path="b.txt", sha256="1" * 64, size=1)

    with pytest.raises(PackageAssetError, match="lexicographically ordered"):
        PackageAssetManifest(assets=(b, a))
    with pytest.raises(PackageAssetError, match="duplicate paths"):
        PackageAssetManifest(assets=(a, a))
    with pytest.raises(PackageAssetError, match="invalid SHA-256"):
        PackageAsset(path="bad.txt", sha256="xyz", size=1)
    with pytest.raises(PackageAssetError, match="cannot declare itself"):
        PackageAsset(path=ASSET_MANIFEST_FILENAME, sha256="0" * 64, size=0)
