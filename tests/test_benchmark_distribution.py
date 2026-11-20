"""Offline release round trips, relocated runtimes, and hostile archive rejection."""

import hashlib
import importlib.util
import json
import shutil
import stat
import zipfile
import warnings
from pathlib import Path

import pytest

from arisekit import (
    Benchmark, BenchmarkItem, BenchmarkManifest, DistributionError,
    export_benchmark, import_benchmark, verify_dependencies,
    verify_distribution, write_package,
)
from arisekit import cli, __version__
from arisekit.package import PackageAssetError, load_package
from arisekit.scaffold import scaffold_benchmark, load_scaffolded_benchmark


@pytest.fixture
def package(tmp_path):
    return write_package(
        tmp_path / "source", manifest=BenchmarkManifest(id="example", name="Example", version="1.2.3"),
        items=[BenchmarkItem(id="one", prompt="Return yes", ground_truth="yes")],
        rubric={"criteria": []}, readme="Author's original description\n",
        judge_assets={"binding.py": "raise RuntimeError('must not execute')\n"},
    )


def archive_for(package, tmp_path, **kwargs):
    return export_benchmark(package, tmp_path / "release.zip", description="A synthetic response benchmark.", **kwargs)


def rewrite_archive(archive, edit):
    with zipfile.ZipFile(archive) as z:
        contents = {name: z.read(name) for name in z.namelist()}
    edit(contents)
    with zipfile.ZipFile(archive, "w") as z:
        for name, content in contents.items():
            z.writestr(name, content)


def test_round_trip_preserves_assets_and_runs_offline(package, tmp_path):
    before = {p.relative_to(package): p.read_bytes() for p in package.rglob("*") if p.is_file()}
    archive = archive_for(package, tmp_path)
    second = export_benchmark(package, tmp_path / "second.zip", description="A synthetic response benchmark.")
    assert archive.read_bytes() == second.read_bytes()
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    shutil.rmtree(package)
    receipt = import_benchmark(archive, tmp_path / "release", expected_sha256=digest)
    assert receipt.benchmark_version == "1.2.3"
    assert receipt.dependencies == (f"arisekit=={__version__}",)
    for relative, payload in before.items():
        assert (receipt.benchmark_path / relative).read_bytes() == payload
    assert load_package(receipt.benchmark_path, verify_assets=True).items[0].id == "one"
    assert verify_distribution(receipt.root) == receipt
    bench = Benchmark.from_package(receipt.benchmark_path)
    results = bench.run(model="stub/reference", results_dir=tmp_path / "results")
    assert results.summary.completed == 1
    assert "git submodule add" in (receipt.root / "MAST_CONTRIBUTION.md").read_text()
    assert "A synthetic response benchmark." in (receipt.root / "BENCHMARK.md").read_text()


def test_generated_package_adapter_works(package, tmp_path):
    receipt = import_benchmark(archive_for(package, tmp_path), tmp_path / "release")
    repository = tmp_path / "example"
    repository.mkdir()
    shutil.copytree(receipt.benchmark_path, repository / "data")
    handoff = (receipt.root / "MAST_CONTRIBUTION.md").read_text()
    adapter = handoff.split("```python\n", 1)[1].split("```", 1)[0]
    (repository / "build.py").write_text(adapter)
    spec = importlib.util.spec_from_file_location("contribution_fixture", repository / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert isinstance(module.build(), Benchmark)


@pytest.mark.parametrize("example", ["p0-golden-path", "agentic-fhir-golden-path", "multimodal-golden-path"])
def test_scaffolds_relocate_with_reviewed_runtime_controls(tmp_path, example):
    repository = Path(__file__).resolve().parents[1]
    authoring = tmp_path / "authoring"
    shutil.copytree(repository / "examples" / example / "authoring", authoring)
    scaffold = scaffold_benchmark(authoring / "benchmark-build-spec.json", output_root=tmp_path / "benchmarks")
    original = (scaffold.root / "runnable-benchmark.json").read_bytes()
    (scaffold.root / "unrelated-secret.txt").write_text("must not travel")
    with pytest.raises(ValueError, match="root entries differ"):
        export_benchmark(scaffold.root, tmp_path / "release.zip")
    (scaffold.root / "unrelated-secret.txt").unlink()
    archive = export_benchmark(scaffold.root, tmp_path / "release.zip")
    shutil.rmtree(authoring)
    shutil.rmtree(scaffold.root)
    receipt = import_benchmark(archive, tmp_path / "release")
    assert receipt.kind == "scaffold"
    assert (receipt.benchmark_path / "runnable-benchmark.json").read_bytes() == original
    assert not (receipt.benchmark_path / "unrelated-secret.txt").exists()
    bench = load_scaffolded_benchmark(receipt.benchmark_path)
    assert bench.allowed_model_routes
    working = tmp_path / "work" / receipt.benchmark_id
    working.parent.mkdir()
    shutil.copytree(receipt.benchmark_path, working)
    plan = json.loads(original)["smoke_test"]
    assert cli.main([
        "--benchmarks-dir", str(working.parent), "--results-dir", str(tmp_path / "results"),
        "eval", receipt.benchmark_id, "--model", plan["model"],
        "--limit", str(plan["limit"]), "--trials", str(plan["trials"]),
    ]) == 0
    assert verify_distribution(receipt.root) == receipt


def test_cli_round_trip_and_errors(package, tmp_path, capsys):
    archive = tmp_path / "cli.zip"
    destination = tmp_path / "release"
    assert cli.main(["export-benchmark", str(package), "--output", str(archive), "--description", "CLI fixture"]) == 0
    assert cli.main(["import-benchmark", str(archive), "--destination", str(destination)]) == 0
    assert cli.main(["verify-benchmark", str(destination)]) == 0
    assert cli.main(["describe-benchmark", str(destination)]) == 0
    assert "CLI fixture" in capsys.readouterr().out
    assert cli.main(["import-benchmark", str(archive), "--destination", str(destination)]) == 2
    assert "already exists" in capsys.readouterr().err


@pytest.mark.parametrize("mutation", ["extra", "missing", "tampered", "schema", "identity", "duplicate-json"])
def test_corrupt_archives_leave_no_destination(package, tmp_path, mutation):
    archive = archive_for(package, tmp_path)
    def edit(contents):
        if mutation == "extra":
            contents["surprise.txt"] = b"extra"
        elif mutation == "missing":
            del contents["benchmark/cases.jsonl"]
        elif mutation == "tampered":
            contents["benchmark/cases.jsonl"] = b"changed"
        elif mutation == "duplicate-json":
            contents["distribution.json"] = b'{"schema_version": "a", "schema_version": "b"}'
        else:
            manifest = json.loads(contents["distribution.json"])
            manifest["schema_version" if mutation == "schema" else "benchmark_version"] = "999"
            contents["distribution.json"] = json.dumps(manifest).encode()
    rewrite_archive(archive, edit)
    destination = tmp_path / "release"
    with pytest.raises((DistributionError, PackageAssetError)):
        import_benchmark(archive, destination)
    assert not destination.exists()


@pytest.mark.parametrize("name", ["../escaped", "/absolute", "C:/absolute", "benchmark/../escaped", "benchmark\\evil", "./dot"])
def test_unsafe_paths_are_rejected(package, tmp_path, name):
    archive = archive_for(package, tmp_path)
    with zipfile.ZipFile(archive, "a") as z:
        z.writestr(name, "unsafe")
    with pytest.raises((DistributionError, PackageAssetError)):
        import_benchmark(archive, tmp_path / "release")
    assert not (tmp_path / "escaped").exists()
    assert not (tmp_path / "release").exists()


@pytest.mark.parametrize("mode", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFDIR])
def test_special_archive_entries_rejected(package, tmp_path, mode):
    archive = archive_for(package, tmp_path)
    with zipfile.ZipFile(archive, "a") as z:
        info = zipfile.ZipInfo("link")
        info.external_attr = (mode | 0o777) << 16
        z.writestr(info, "../outside")
    with pytest.raises(DistributionError, match="regular file"):
        import_benchmark(archive, tmp_path / "release")


@pytest.mark.parametrize("name", ["BENCHMARK.md", "benchmark/CASES.JSONL", "BENCHMARK.md/file"])
def test_duplicate_alias_and_parent_collisions(package, tmp_path, name):
    archive = archive_for(package, tmp_path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(archive, "a") as z:
            z.writestr(name, "collision")
    with pytest.raises(DistributionError, match="duplicate|collision"):
        import_benchmark(archive, tmp_path / "release")


def test_symlink_and_modified_sources_are_not_blessed(package, tmp_path):
    (package / "link").symlink_to(package / "cases.jsonl")
    with pytest.raises(PackageAssetError):
        archive_for(package, tmp_path)
    (package / "link").unlink()
    from arisekit.package import PackageAssetManifest
    (package / "asset-manifest.json").write_text(json.dumps(PackageAssetManifest.build(package).to_dict()))
    (package / "cases.jsonl").write_text("tampered")
    with pytest.raises(PackageAssetError):
        archive_for(package, tmp_path)
    assert not (tmp_path / "release.zip").exists()


def test_dependency_failure_is_offline_and_rolls_back(package, tmp_path):
    archive = archive_for(package, tmp_path, dependencies=["arisekit-test-nonexistent-package==1.0"])
    with pytest.raises(DistributionError, match="missing dependency"):
        import_benchmark(archive, tmp_path / "release")
    assert not (tmp_path / "release").exists()


@pytest.mark.parametrize("dependencies,python_requires,message", [
    (["arisekit==9999"], ">=3.10", "does not satisfy"),
    (["arisekit>=0"], ">=9999", "Python"),
    (["arisekit>=0", "anything @ https://example.com/a.whl"], ">=3", "URLs"),
    (["arisekit>=0", "anything[extra]>=1"], ">=3", "extras"),
    (["arisekit>=0", "ARISEKit>=0"], ">=3", "duplicate"),
    (["arisekit>=0; python_version<'1'"], ">=3", "unconditional"),
    (["arisekit>=0"], "not-a-specifier", "invalid"),
])
def test_dependency_validation(dependencies, python_requires, message):
    with pytest.raises(DistributionError, match=message):
        verify_dependencies(dependencies, python_requires)


def test_inactive_dependency_marker_is_skipped():
    verify_dependencies(["arisekit>=0", "does-not-exist==1; python_version<'1'"], ">=3.10")


def test_digest_limits_and_existing_outputs(package, tmp_path, monkeypatch):
    archive = archive_for(package, tmp_path)
    with pytest.raises(DistributionError, match="SHA-256"):
        import_benchmark(archive, tmp_path / "release", expected_sha256="0" * 64)
    with pytest.raises(DistributionError, match="already exists"):
        archive_for(package, tmp_path)
    import arisekit.runtime.distribution as distribution
    monkeypatch.setattr(distribution, "MAX_DISTRIBUTION_FILES", 1)
    with pytest.raises(DistributionError, match="file count"):
        import_benchmark(archive, tmp_path / "release")
    assert not (tmp_path / "release").exists()


def test_explicit_description_required_for_legacy_package(package, tmp_path):
    with pytest.raises(DistributionError, match="description"):
        export_benchmark(package, tmp_path / "release.zip")
    assert not (tmp_path / "release.zip").exists()


def test_export_rejects_case_aliases(package, tmp_path, monkeypatch):
    import arisekit.runtime.distribution as distribution
    inventory = distribution._package_file_paths
    # Model a case-sensitive source inventory on case-insensitive test hosts.
    monkeypatch.setattr(
        distribution, "_package_file_paths",
        lambda root: inventory(root) + (["CASES.JSONL"] if root == package else []),
    )
    with pytest.raises(DistributionError, match="duplicate"):
        archive_for(package, tmp_path)
    assert not (tmp_path / "release.zip").exists()


def test_installed_dependency_version_mismatch(monkeypatch):
    import arisekit.runtime.distribution as distribution
    monkeypatch.setattr(distribution.importlib.metadata, "version", lambda name: "1.0")
    with pytest.raises(DistributionError, match="helper 1.0 does not satisfy >=2"):
        verify_dependencies(["arisekit>=0", "helper>=2"], ">=3.10")


def test_custom_scorer_handoff_names_missing_binding(package, tmp_path):
    manifest_path = package / "benchmark.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["scorer"] = {"kind": "custom-review-panel"}
    manifest_path.write_text(json.dumps(manifest))
    receipt = import_benchmark(archive_for(package, tmp_path), tmp_path / "release")
    handoff = (receipt.root / "MAST_CONTRIBUTION.md").read_text()
    assert "explicit runtime binding" in handoff
    assert "```python" not in handoff
