"""Versioned, offline benchmark distribution and MAST contribution handoff."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from arisekit.common.jsonio import strict_json_object
from arisekit.package import (
    ASSET_MANIFEST_FILENAME,
    PackageAsset,
    PackageAssetManifest,
    _package_file_paths,
    _safe_package_file,
    _safe_relative_asset_path,
    load_package,
)

DISTRIBUTION_SCHEMA_VERSION = "arisekit.benchmark-distribution.v1"
DISTRIBUTION_FILENAME = "distribution.json"
MAX_DISTRIBUTION_BYTES = 512 * 1024 * 1024
MAX_DISTRIBUTION_FILES = 10000
_RESERVED = {DISTRIBUTION_FILENAME, "BENCHMARK.md", "MAST_CONTRIBUTION.md"}


class DistributionError(ValueError):
    """A distribution is incompatible, incomplete, or unsafe to import."""


@dataclass(frozen=True)
class DistributionReceipt:
    root: Path
    benchmark_id: str
    benchmark_version: str
    description: str
    kind: str
    dependencies: tuple[str, ...]
    python_requires: str
    manifest_sha256: str

    @property
    def benchmark_path(self) -> Path:
        return self.root / "benchmark"

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "benchmark_path": str(self.benchmark_path),
            "benchmark_id": self.benchmark_id,
            "benchmark_version": self.benchmark_version,
            "description": self.description,
            "kind": self.kind,
            "dependencies": list(self.dependencies),
            "python_requires": self.python_requires,
            "manifest_sha256": self.manifest_sha256,
        }


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def _read_object(path: Path) -> dict[str, Any]:
    return strict_json_object(path.read_bytes(), path.name, allow_bytes=True, error=DistributionError)


def _requirements(values: Iterable[str]) -> tuple[Requirement, ...]:
    if isinstance(values, (str, bytes)):
        raise DistributionError("dependencies must be a list of requirement strings")
    requirements = []
    names = set()
    for value in values:
        if not isinstance(value, str):
            raise DistributionError("dependencies must contain strings")
        try:
            requirement = Requirement(value)
        except InvalidRequirement as exc:
            raise DistributionError(f"invalid dependency: {value!r}") from exc
        if requirement.url or requirement.extras:
            raise DistributionError("dependencies must use package versions, without URLs or extras")
        name = canonicalize_name(requirement.name)
        if name in names:
            raise DistributionError(f"duplicate dependency: {name}")
        names.add(name)
        requirements.append(requirement)
    runtime = [r for r in requirements if canonicalize_name(r.name) == "arisekit"]
    if len(runtime) != 1 or runtime[0].marker or not str(runtime[0].specifier):
        raise DistributionError("dependencies require an unconditional, versioned arisekit requirement")
    return tuple(requirements)


def verify_dependencies(dependencies: Iterable[str], python_requires: str) -> None:
    """Check installed versions; never install packages or import their code."""
    requirements = _requirements(dependencies)
    try:
        if not isinstance(python_requires, str) or not python_requires.strip():
            raise InvalidSpecifier("empty Python requirement")
        python_spec = SpecifierSet(python_requires)
    except InvalidSpecifier as exc:
        raise DistributionError("invalid python_requires specifier") from exc
    failures = []
    if not python_spec.contains(platform.python_version()):
        failures.append(f"Python {platform.python_version()} does not satisfy {python_requires}")
    for requirement in requirements:
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            if canonicalize_name(requirement.name) == "arisekit":
                from arisekit import __version__
                installed = __version__
            else:
                installed = importlib.metadata.version(requirement.name)
            if not requirement.specifier.contains(installed, prereleases=True):
                failures.append(f"{requirement.name} {installed} does not satisfy {requirement.specifier}")
        except importlib.metadata.PackageNotFoundError:
            failures.append(f"missing dependency: {requirement}")
    if failures:
        raise DistributionError("dependency verification failed: " + "; ".join(failures))


def _identity(data: dict[str, Any]) -> None:
    if not isinstance(data["benchmark_id"], str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", data["benchmark_id"]
    ):
        raise DistributionError("benchmark id must be a portable slug")
    for name in ("benchmark_name", "benchmark_version", "description"):
        if not isinstance(data[name], str) or not data[name].strip():
            raise DistributionError(f"{name} must be a non-empty string")
    try:
        Version(data["benchmark_version"])
    except InvalidVersion as exc:
        raise DistributionError("benchmark_version must be a PEP 440 version") from exc


def _portable_paths(paths: Iterable[str]) -> None:
    names = set()
    folded = set()
    for raw in paths:
        path = _safe_relative_asset_path(raw)
        if path in names or path.casefold() in folded:
            raise DistributionError(f"duplicate archive path: {path}")
        names.add(path)
        folded.add(path.casefold())
    for path in names:
        if any(
            parent.as_posix().casefold() in folded
            for parent in Path(path).parents if parent.as_posix() != "."
        ):
            raise DistributionError(f"archive file/directory collision: {path}")


def _verify_payload(root: Path, kind: str):
    if not isinstance(kind, str) or kind not in {"package", "scaffold"}:
        raise DistributionError(f"unsupported distribution kind: {kind!r}")
    package_path = root / "package" if kind == "scaffold" else root
    package = load_package(package_path, verify_assets=True)
    if package.manifest.modality != "multimodal" and any(item.attachments for item in package.items):
        raise DistributionError("attachments require the portable multimodal image binding")
    if kind == "scaffold":
        from arisekit.scaffold import load_scaffolded_benchmark
        load_scaffolded_benchmark(root)
    else:
        # Frozen authoring controls require the complete runnable scaffold.
        if "build_spec" in package.manifest.provenance:
            raise DistributionError("export the scaffold root, not its package/ directory")
        from arisekit.package import agentic_fhir_binding_from_package, multimodal_image_binding_from_package
        if package.manifest.modality == "agentic-fhir":
            agentic_fhir_binding_from_package(package)
        if package.manifest.modality == "multimodal":
            multimodal_image_binding_from_package(package)
    return package


def verify_distribution(path: str | Path, *, check_dependencies: bool = True) -> DistributionReceipt:
    """Verify an extracted distribution, including every declared byte."""
    root = Path(path).expanduser()
    files = _package_file_paths(root)
    _portable_paths(files)
    if len(files) > MAX_DISTRIBUTION_FILES:
        raise DistributionError("distribution contains too many files")
    data = _read_object(_safe_package_file(root, DISTRIBUTION_FILENAME, required=True))
    expected = {
        "schema_version", "benchmark_id", "benchmark_name", "benchmark_version",
        "description", "kind", "dependencies", "python_requires", "assets",
    }
    if set(data) != expected or data.get("schema_version") != DISTRIBUTION_SCHEMA_VERSION:
        raise DistributionError("unsupported distribution schema or fields")
    _identity(data)
    if not isinstance(data["dependencies"], list):
        raise DistributionError("dependencies must be a list")
    _requirements(data["dependencies"])
    if not isinstance(data["python_requires"], str) or not data["python_requires"].strip():
        raise DistributionError("python_requires must be a non-empty specifier")
    try:
        SpecifierSet(data["python_requires"])
    except InvalidSpecifier as exc:
        raise DistributionError("invalid python_requires specifier") from exc
    if not isinstance(data["assets"], list) or any(not isinstance(a, dict) for a in data["assets"]):
        raise DistributionError("assets must be a list of objects")
    if any(set(a) != {"path", "sha256", "size"} for a in data["assets"]):
        raise DistributionError("distribution asset fields are invalid")
    assets = tuple(PackageAsset.from_dict(a) for a in data["assets"])
    paths = [a.path for a in assets]
    if paths != sorted(set(paths)) or set(paths) != set(files) - {DISTRIBUTION_FILENAME}:
        raise DistributionError("distribution inventory has missing, duplicate, or undeclared files")
    if not {"BENCHMARK.md", "MAST_CONTRIBUTION.md"}.issubset(paths):
        raise DistributionError("distribution is missing description or contribution handoff")
    if any(p not in _RESERVED and not p.startswith("benchmark/") for p in paths):
        raise DistributionError("distribution contains files outside benchmark/")
    if sum(a.size for a in assets) > MAX_DISTRIBUTION_BYTES:
        raise DistributionError("distribution exceeds size limit")
    for asset in assets:
        payload = _safe_package_file(root, asset.path, required=True).read_bytes()
        if len(payload) != asset.size or hashlib.sha256(payload).hexdigest() != asset.sha256:
            raise DistributionError(f"distribution asset mismatch: {asset.path}")
    if check_dependencies:
        verify_dependencies(data["dependencies"], data["python_requires"])
    try:
        package = _verify_payload(root / "benchmark", data["kind"])
    except (TypeError, AttributeError, KeyError) as exc:
        raise DistributionError(f"invalid benchmark payload: {exc}") from exc
    if (package.manifest.id, package.manifest.name, package.manifest.version) != (
        data["benchmark_id"], data["benchmark_name"], data["benchmark_version"]
    ):
        raise DistributionError("distribution identity differs from benchmark manifest")
    return DistributionReceipt(
        root, data["benchmark_id"], data["benchmark_version"], data["description"],
        data["kind"], tuple(data["dependencies"]), data["python_requires"],
        hashlib.sha256((root / DISTRIBUTION_FILENAME).read_bytes()).hexdigest(),
    )


def _description(data: dict[str, Any], package) -> str:
    manifest = package.manifest
    return (
        f"# {manifest.name}\n\n{data['description']}\n\n"
        f"- Benchmark: `{manifest.id}`\n- Version: `{manifest.version}`\n"
        f"- Modality: `{manifest.modality}`\n- Cases: {len(package.items)}\n"
        f"- Scorer: `{manifest.scorer.get('kind', 'unspecified')}`\n"
        f"- Python: `{data['python_requires']}`\n"
        + "- Dependencies: " + ", ".join(f"`{r}`" for r in data["dependencies"]) + "\n\n"
        "Provenance and any author-declared data governance remain in benchmark.json. "
        "External provenance links are not copied or verified as runtime assets.\n\n"
        "Checks establish package integrity and declared dependency compatibility. "
        "They do not establish clinical validity, data rights, privacy clearance, or MAST admission.\n"
    )


def _handoff(data: dict[str, Any], package) -> str:
    slug = data["benchmark_id"]
    package_path = "package/benchmark.json" if data["kind"] == "scaffold" else "data/benchmark.json"
    from arisekit.package import scorer_from_manifest

    binding = scorer_from_manifest(package.manifest) is None
    return (
        f"# MAST contribution handoff: {package.manifest.name}\n\n"
        f"Proposed benchmark: `{slug}`, version `{data['benchmark_version']}`.\n\n"
        "1. Verify this release with `arisekit verify-benchmark <release-directory>`. "
        "Review BENCHMARK.md and the declared dependencies before installing them.\n"
        f"2. Create a standalone benchmark repository named `{slug}`. "
        + ("Copy the contents of `benchmark/` to its root. " if data["kind"] == "scaffold"
           else "Copy `benchmark/` to its `data/` directory. ") +
        "Use a working copy for smoke runs; release inventories are immutable. "
        "Retain this handoff, BENCHMARK.md, and distribution.json as release evidence outside that working copy.\n"
        f"3. Review `{package_path}` and all packaged data, licenses, provenance, "
        "scoring rules, and release permissions. Record missing information; "
        "the generator does not infer a license or permission to publish.\n"
        "4. In the benchmark repository, provide a `build()` returning an "
        "`arisekit.Benchmark`. "
        + ("The scaffold already includes `build.py`; keep its verified factory unchanged.\n"
           if data["kind"] == "scaffold" else
           "Use the package adapter below; keep the dataset and scorer in the package.\n")
        + ("   This scorer needs an explicit runtime binding. Supply the reviewed scorer "
           "to `Benchmark.from_package(..., scorer=...)` and document its dependencies.\n" if binding else "")
        + "5. Run the documented smoke configuration, retain the manifested results and MAST-shaped "
        "scores CSV, and describe limitations. For a scaffold, inspect "
        "`runnable-benchmark.json` for its exact planned smoke and readiness state.\n"
        f"   From the parent directory: `arisekit --benchmarks-dir . eval {slug} "
        "--model <reviewed-model> --limit <planned-limit> --trials <planned-trials>`.\n"
        "6. Commit the reviewed benchmark repository and select an immutable commit. "
        "In your local MAST checkout, prepare the submodule and pin that commit:\n\n"
        "```sh\n"
        f"git submodule add <benchmark-repository-url> benchmarks/{slug}\n"
        f"git -C benchmarks/{slug} checkout <benchmark-commit>\n"
        f"git add .gitmodules benchmarks/{slug}\n"
        "```\n\n"
        "Follow the receiving MAST repository's current contribution instructions to register "
        "the benchmark in its suite and prepare a pull request. Include benchmark version, "
        "pinned commit, description, dependency requirements, data/license provenance, "
        "smoke evidence, score columns and directions, and known limitations. "
        "This handoff does not publish a repository or open a pull request.\n"
        + ("\nPackage adapter (`build.py` at the benchmark repository root):\n\n"
           "```python\nfrom pathlib import Path\nfrom arisekit import Benchmark\n\n"
           "def build():\n    return Benchmark.from_package(Path(__file__).resolve().parent / \"data\")\n```\n"
           if data["kind"] == "package" and not binding else "")
    )


def export_benchmark(
    source: str | Path,
    output: str | Path,
    *,
    description: str | None = None,
    dependencies: Iterable[str] = (),
    python_requires: str = ">=3.10",
) -> Path:
    """Create a deterministic ZIP release without changing the source package.

    Existing inventories must verify. Legacy packages receive an inventory in
    the staged copy. Only declared scaffold assets and package files are copied.
    """
    from arisekit import __version__

    source = Path(source).expanduser()
    output = Path(output).expanduser()
    if output.exists() or output.is_symlink():
        raise DistributionError(f"output already exists: {output}")
    if output.resolve().is_relative_to(source.resolve()):
        raise DistributionError("export output must be outside the source directory")
    if source.is_symlink() or not source.is_dir():
        raise DistributionError("source must be a regular package or scaffold directory")
    kind = "scaffold" if (source / "package").exists() else "package"
    package_root = source / "package" if kind == "scaffold" else source
    package = load_package(package_root, verify_assets=(package_root / ASSET_MANIFEST_FILENAME).exists())
    if kind == "scaffold":
        from arisekit.runnable import load_manifest, verify_assets
        from arisekit.scaffold import load_scaffolded_benchmark
        load_scaffolded_benchmark(source)
        runnable = load_manifest(source / "runnable-benchmark.json")
        verify_assets(source, runnable)
        files = {a.path for a in runnable.required_assets} | {"runnable-benchmark.json"}
        files.update("package/" + p for p in _package_file_paths(package_root))
    else:
        files = set(_package_file_paths(source))
    _portable_paths(files)
    if description is None:
        record = package.manifest.provenance.get("benchmark")
        description = record.get("description") if isinstance(record, dict) else None
    if isinstance(dependencies, (str, bytes)):
        raise DistributionError("dependencies must be a list of requirement strings")
    dependency_values = list(dependencies)
    if not any(canonicalize_name(Requirement(r).name) == "arisekit" for r in dependency_values):
        dependency_values.append(f"arisekit=={__version__}")
    data = {
        "schema_version": DISTRIBUTION_SCHEMA_VERSION,
        "benchmark_id": package.manifest.id,
        "benchmark_name": package.manifest.name,
        "benchmark_version": package.manifest.version,
        "description": description,
        "kind": kind,
        "dependencies": sorted(str(r) for r in _requirements(dependency_values)),
        "python_requires": python_requires,
    }
    _identity(data)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".arisekit-export-", dir=output.parent) as temporary:
        stage = Path(temporary) / "release"
        payload_root = stage / "benchmark"
        payload_root.mkdir(parents=True)
        for relative in sorted(files):
            original = _safe_package_file(source, relative, required=True)
            target = payload_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original.read_bytes())
        staged_package = payload_root / "package" if kind == "scaffold" else payload_root
        if not (staged_package / ASSET_MANIFEST_FILENAME).exists():
            inventory = PackageAssetManifest.build(staged_package)
            (staged_package / ASSET_MANIFEST_FILENAME).write_bytes(_json_bytes(inventory.to_dict()))
        package = _verify_payload(payload_root, kind)
        (stage / "BENCHMARK.md").write_text(_description(data, package), encoding="utf-8")
        (stage / "MAST_CONTRIBUTION.md").write_text(_handoff(data, package), encoding="utf-8")
        data["assets"] = [
            {"path": p, "size": (stage / p).stat().st_size,
             "sha256": hashlib.sha256((stage / p).read_bytes()).hexdigest()}
            for p in _package_file_paths(stage)
        ]
        (stage / DISTRIBUTION_FILENAME).write_bytes(_json_bytes(data))
        verify_distribution(stage, check_dependencies=False)
        archive_path = Path(temporary) / "release.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative in _package_file_paths(stage):
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, (stage / relative).read_bytes())
        if archive_path.stat().st_size > MAX_DISTRIBUTION_BYTES:
            raise DistributionError("archive exceeds size limit")
        # A hard link publishes atomically and cannot replace a concurrent writer.
        os.link(archive_path, output)
    return output


def import_benchmark(
    archive: str | Path,
    destination: str | Path,
    *,
    expected_sha256: str | None = None,
) -> DistributionReceipt:
    """Verify and import a ZIP into a new directory; never overwrite or execute."""
    archive_path = Path(archive).expanduser()
    destination = Path(destination).expanduser()
    if destination.exists() or destination.is_symlink():
        raise DistributionError(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".arisekit-import-", dir=destination.parent) as temporary:
        # Snapshot the archive so optional out-of-band digest verification binds extraction.
        snapshot = Path(temporary) / "release.zip"
        if archive_path.stat().st_size > MAX_DISTRIBUTION_BYTES:
            raise DistributionError("archive exceeds size limit")
        shutil.copyfile(archive_path, snapshot)
        if snapshot.stat().st_size > MAX_DISTRIBUTION_BYTES:
            raise DistributionError("archive exceeds size limit")
        if expected_sha256 is not None:
            if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
                raise DistributionError("expected_sha256 must be a lowercase SHA-256 digest")
            if hashlib.sha256(snapshot.read_bytes()).hexdigest() != expected_sha256:
                raise DistributionError("archive SHA-256 does not match expected_sha256")
        stage = Path(temporary) / "release"
        stage.mkdir()
        try:
            with zipfile.ZipFile(snapshot) as bundle:
                entries = bundle.infolist()
                if len(entries) > MAX_DISTRIBUTION_FILES or sum(e.file_size for e in entries) > MAX_DISTRIBUTION_BYTES:
                    raise DistributionError("archive exceeds file count or uncompressed size limit")
                _portable_paths(entry.filename for entry in entries)
                for entry in entries:
                    if entry.orig_filename != entry.filename:
                        raise DistributionError("archive entry contains a truncated filename")
                    mode = entry.external_attr >> 16
                    if entry.is_dir() or stat.S_IFMT(mode) not in {0, stat.S_IFREG} or entry.flag_bits & 1:
                        raise DistributionError(
                            f"archive entry must be an unencrypted regular file: {entry.filename}"
                        )
                for entry in entries:
                    target = stage / entry.filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(entry) as source, target.open("xb") as sink:
                        shutil.copyfileobj(source, sink)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise DistributionError(f"invalid benchmark archive: {exc}") from exc
        receipt = verify_distribution(stage)
        # mkdir reserves the destination without clobbering existing directories.
        destination.mkdir()
        try:
            for child in stage.iterdir():
                os.rename(child, destination / child.name)
        except BaseException:
            shutil.rmtree(destination)
            raise
    return replace(receipt, root=destination)


__all__ = [
    "DISTRIBUTION_SCHEMA_VERSION", "DistributionError", "DistributionReceipt",
    "export_benchmark", "import_benchmark", "verify_dependencies", "verify_distribution",
]
