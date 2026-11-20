"""Canonical bridge between benchmark construction and execution.

``benchmark-build-spec.json`` records authoring decisions.  A
``runnable-benchmark.json`` records the materialized bytes that a runner can
actually load.  Builder-produced benchmarks start in ``awaiting_smoke_test``
and become ``ready`` only after the exact planned smoke run completes without
terminal errors.

This is a structural and execution-readiness contract.  It does not certify
clinical quality, privacy, data rights, or MAST admission.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from arisekit.common.files import atomic_write
from arisekit.common.jsonio import strict_canonical_json as _canonical_json
from arisekit.common.records import StrictCanonicalPropertyRecord
from arisekit.common.validate import exact_fields, positive_int as _positive_int, sha256_hex as _sha256, text


SCHEMA_VERSION = "arisekit.runnable-benchmark.v1"
FILENAME = "runnable-benchmark.json"
READINESS_STATES = frozenset(("awaiting_smoke_test", "ready", "blocked"))
SMOKE_TEST_STATES = frozenset(("not_run", "passed", "failed"))
ORIGINS = frozenset(("builder", "curated-roster"))
CLAIM_BOUNDARY = (
    "Execution readiness only; this does not establish clinical quality, "
    "privacy clearance, data authorization, or MAST admission."
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class RunnableAsset:
    """One immutable file required to load the benchmark."""

    path: str
    sha256: str
    size: int

    def __post_init__(self) -> None:
        _relative_path(self.path, "asset.path")
        _sha256(self.sha256, "asset.sha256")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise ValueError("asset.size must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunnableAsset":
        _fields(data, {"path", "sha256", "size"}, "asset")
        return cls(path=data["path"], sha256=data["sha256"], size=data["size"])


@dataclass(frozen=True)
class SmokeTestRecord:
    """Planned smoke configuration and its bound result, if one exists."""

    model: str
    limit: int
    trials: int
    status: str = "not_run"
    result_bundle_path: str | None = None
    result_bundle_sha256: str | None = None
    run_manifest_digest: str | None = None
    completed: int = 0
    errored: int = 0

    def __post_init__(self) -> None:
        _text(self.model, "smoke_test.model")
        _positive_int(self.limit, "smoke_test.limit")
        _positive_int(self.trials, "smoke_test.trials")
        if self.status not in SMOKE_TEST_STATES:
            raise ValueError(
                "smoke_test.status must be one of " + ", ".join(sorted(SMOKE_TEST_STATES))
            )
        for name in ("completed", "errored"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"smoke_test.{name} must be a non-negative integer")
        if self.result_bundle_path is not None:
            _relative_path(self.result_bundle_path, "smoke_test.result_bundle_path")
        if self.result_bundle_sha256 is not None:
            _sha256(self.result_bundle_sha256, "smoke_test.result_bundle_sha256")
        if self.run_manifest_digest is not None:
            _sha256(self.run_manifest_digest, "smoke_test.run_manifest_digest")

        result_fields = (
            self.result_bundle_path,
            self.result_bundle_sha256,
            self.run_manifest_digest,
        )
        if self.status == "not_run":
            if any(value is not None for value in result_fields) or self.completed or self.errored:
                raise ValueError("an unrun smoke test cannot contain result evidence")
        else:
            if self.result_bundle_path is None or self.result_bundle_sha256 is None:
                raise ValueError("a completed smoke test requires a result bundle path and digest")
            if self.status == "passed" and (self.completed < 1 or self.errored != 0):
                raise ValueError("a passed smoke test requires completed > 0 and errored == 0")
            if self.status == "failed" and self.errored < 1:
                raise ValueError("a failed smoke test requires at least one terminal error")

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "limit": self.limit,
            "trials": self.trials,
            "status": self.status,
            "result_bundle_path": self.result_bundle_path,
            "result_bundle_sha256": self.result_bundle_sha256,
            "run_manifest_digest": self.run_manifest_digest,
            "completed": self.completed,
            "errored": self.errored,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SmokeTestRecord":
        fields = {
            "model",
            "limit",
            "trials",
            "status",
            "result_bundle_path",
            "result_bundle_sha256",
            "run_manifest_digest",
            "completed",
            "errored",
        }
        _fields(data, fields, "smoke_test")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True)
class RunnableBenchmarkManifest(StrictCanonicalPropertyRecord):
    """Materialized benchmark identity accepted by run configuration."""

    benchmark_id: str
    benchmark_version: str
    origin: str
    entry_point: str
    entry_point_sha256: str
    dataset_sha256: str
    scorer_sha256: str
    required_assets: tuple[RunnableAsset, ...]
    environment: Mapping[str, str]
    source_revision: str
    smoke_test: SmokeTestRecord
    readiness: str
    build_spec_sha256: str | None = None
    schema_version: str = SCHEMA_VERSION
    claim_boundary: str = CLAIM_BOUNDARY

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION!r}")
        if not _ID_RE.fullmatch(self.benchmark_id):
            raise ValueError("benchmark_id contains unsupported characters")
        _text(self.benchmark_version, "benchmark_version")
        if self.origin not in ORIGINS:
            raise ValueError("origin must be 'builder' or 'curated-roster'")
        if ":" not in self.entry_point:
            raise ValueError("entry_point must use '<relative path>:<callable>' form")
        entry_path, callable_name = self.entry_point.rsplit(":", 1)
        _relative_path(entry_path, "entry_point path")
        _text(callable_name, "entry_point callable")
        for name in ("entry_point_sha256", "dataset_sha256", "scorer_sha256"):
            _sha256(getattr(self, name), name)
        if self.build_spec_sha256 is not None:
            _sha256(self.build_spec_sha256, "build_spec_sha256")
        _text(self.source_revision, "source_revision")
        if self.readiness not in READINESS_STATES:
            raise ValueError("readiness must be awaiting_smoke_test, ready, or blocked")
        expected_readiness = {
            "not_run": "awaiting_smoke_test",
            "passed": "ready",
            "failed": "blocked",
        }[self.smoke_test.status]
        if self.readiness != expected_readiness:
            raise ValueError(
                f"readiness {self.readiness!r} does not match smoke-test status "
                f"{self.smoke_test.status!r}"
            )
        if self.claim_boundary != CLAIM_BOUNDARY:
            raise ValueError("claim_boundary must use the canonical execution boundary")

        assets = tuple(self.required_assets)
        if not assets:
            raise ValueError("required_assets must not be empty")
        paths = [asset.path for asset in assets]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("required_assets must be unique and sorted by path")
        object.__setattr__(self, "required_assets", assets)

        normalized_environment: dict[str, str] = {}
        for key, value in self.environment.items():
            normalized_environment[_text(key, "environment key")] = _text(
                value, f"environment.{key}"
            )
        if not normalized_environment:
            raise ValueError("environment must not be empty")
        object.__setattr__(
            self,
            "environment",
            MappingProxyType(dict(sorted(normalized_environment.items()))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "benchmark_id": self.benchmark_id,
            "benchmark_version": self.benchmark_version,
            "origin": self.origin,
            "entry_point": self.entry_point,
            "entry_point_sha256": self.entry_point_sha256,
            "dataset_sha256": self.dataset_sha256,
            "scorer_sha256": self.scorer_sha256,
            "required_assets": [asset.to_dict() for asset in self.required_assets],
            "environment": dict(self.environment),
            "source_revision": self.source_revision,
            "build_spec_sha256": self.build_spec_sha256,
            "smoke_test": self.smoke_test.to_dict(),
            "readiness": self.readiness,
            "claim_boundary": self.claim_boundary,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunnableBenchmarkManifest":
        fields = {
            "schema_version",
            "benchmark_id",
            "benchmark_version",
            "origin",
            "entry_point",
            "entry_point_sha256",
            "dataset_sha256",
            "scorer_sha256",
            "required_assets",
            "environment",
            "source_revision",
            "build_spec_sha256",
            "smoke_test",
            "readiness",
            "claim_boundary",
        }
        _fields(data, fields, "runnable benchmark manifest")
        raw_assets = data["required_assets"]
        if not isinstance(raw_assets, list):
            raise ValueError("required_assets must be a list")
        environment = data["environment"]
        if not isinstance(environment, Mapping):
            raise ValueError("environment must be an object")
        smoke = data["smoke_test"]
        if not isinstance(smoke, Mapping):
            raise ValueError("smoke_test must be an object")
        return cls(
            schema_version=data["schema_version"],
            benchmark_id=data["benchmark_id"],
            benchmark_version=data["benchmark_version"],
            origin=data["origin"],
            entry_point=data["entry_point"],
            entry_point_sha256=data["entry_point_sha256"],
            dataset_sha256=data["dataset_sha256"],
            scorer_sha256=data["scorer_sha256"],
            required_assets=tuple(
                RunnableAsset.from_dict(asset) if isinstance(asset, Mapping) else _bad_asset()
                for asset in raw_assets
            ),
            environment=environment,
            source_revision=data["source_revision"],
            build_spec_sha256=data["build_spec_sha256"],
            smoke_test=SmokeTestRecord.from_dict(smoke),
            readiness=data["readiness"],
            claim_boundary=data["claim_boundary"],
        )


def build_manifest_for_directory(
    root: str | Path,
    *,
    benchmark_id: str,
    benchmark_version: str,
    origin: str,
    entry_point: str,
    dataset_path: str,
    scorer: Mapping[str, Any],
    source_revision: str,
    smoke_model: str,
    smoke_limit: int,
    smoke_trials: int,
    build_spec_sha256: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> RunnableBenchmarkManifest:
    """Create an unrun manifest from already materialized benchmark bytes.

    This function is also the curated-roster adapter: use
    ``origin='curated-roster'`` and point it at the roster entry's factory and
    dataset bytes.
    """

    directory = Path(root)
    entry_path_text, _ = entry_point.rsplit(":", 1)
    entry_path = _safe_file(directory, entry_path_text)
    dataset_file = _safe_file(directory, dataset_path)
    assets = _inventory(directory, exclude={FILENAME})
    return RunnableBenchmarkManifest(
        benchmark_id=benchmark_id,
        benchmark_version=benchmark_version,
        origin=origin,
        entry_point=entry_point,
        entry_point_sha256=_file_sha256(entry_path),
        dataset_sha256=_file_sha256(dataset_file),
        scorer_sha256=hashlib.sha256(_canonical_json(scorer).encode("utf-8")).hexdigest(),
        required_assets=assets,
        environment=environment or default_environment(),
        source_revision=source_revision,
        build_spec_sha256=build_spec_sha256,
        smoke_test=SmokeTestRecord(
            model=smoke_model,
            limit=smoke_limit,
            trials=smoke_trials,
        ),
        readiness="awaiting_smoke_test",
    )


def load_manifest(path: str | Path) -> RunnableBenchmarkManifest:
    """Load and strictly validate ``runnable-benchmark.json``."""

    manifest_path = Path(path)
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load runnable benchmark manifest: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("runnable benchmark manifest must be a JSON object")
    return RunnableBenchmarkManifest.from_dict(raw)


def write_manifest(
    path: str | Path,
    manifest: RunnableBenchmarkManifest,
) -> Path:
    """Atomically write a canonical runnable manifest."""

    destination = Path(path)
    payload = (manifest.canonical_json + "\n").encode("utf-8")
    _atomic_write(destination, payload)
    return destination


def _atomic_write(destination: Path, payload: bytes) -> None:
    atomic_write(destination, payload, make_parents=True)


def verify_assets(root: str | Path, manifest: RunnableBenchmarkManifest) -> None:
    """Fail if any required runtime byte differs from the manifest."""

    directory = Path(root)
    for asset in manifest.required_assets:
        path = _safe_file(directory, asset.path)
        payload = path.read_bytes()
        if len(payload) != asset.size:
            raise ValueError(f"runnable asset size changed: {asset.path}")
        if hashlib.sha256(payload).hexdigest() != asset.sha256:
            raise ValueError(f"runnable asset digest changed: {asset.path}")


def authorize_run_request(
    manifest: RunnableBenchmarkManifest,
    *,
    model: str,
    limit: int | None,
    trials: int,
) -> str:
    """Return ``'smoke'`` or ``'run'`` when the requested dispatch is allowed."""

    if manifest.readiness == "ready":
        return "run"
    if manifest.readiness == "blocked":
        raise ValueError("runnable benchmark is blocked by a failed smoke test")
    planned = manifest.smoke_test
    if model != planned.model or limit != planned.limit or trials != planned.trials:
        raise ValueError(
            "builder benchmark is awaiting its exact planned smoke test: "
            f"model={planned.model!r}, limit={planned.limit}, trials={planned.trials}"
        )
    return "smoke"


def record_smoke_test(
    manifest_path: str | Path,
    *,
    root: str | Path,
    result_bundle_path: str | Path,
    run_manifest_digest: str | None,
    completed: int,
    errored: int,
) -> RunnableBenchmarkManifest:
    """Bind smoke evidence and advance readiness without overwriting history bytes."""

    path = Path(manifest_path)
    manifest = load_manifest(path)
    bundle = Path(result_bundle_path).resolve()
    root_path = Path(root).resolve()
    try:
        bundle.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("smoke result bundle must be inside the declared result root") from exc
    status = "passed" if completed > 0 and errored == 0 else "failed"
    record = SmokeTestRecord(
        model=manifest.smoke_test.model,
        limit=manifest.smoke_test.limit,
        trials=manifest.smoke_test.trials,
        status=status,
        result_bundle_path=bundle.relative_to(root_path).as_posix(),
        result_bundle_sha256=_file_sha256(bundle),
        run_manifest_digest=run_manifest_digest,
        completed=completed,
        errored=errored,
    )
    # The normal run summary changes on resume; readiness must bind retained
    # evidence rather than that mutable latest-run view.
    payload = bundle.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    evidence = (root_path / "smoke-evidence" / f"{digest}.json").resolve()
    relative = evidence.relative_to(root_path).as_posix()
    if evidence.exists():
        if evidence.read_bytes() != payload:
            raise ValueError("retained smoke evidence bytes changed")
    else:
        _atomic_write(evidence, payload)
    record = replace(record, result_bundle_path=relative, result_bundle_sha256=digest)
    updated = replace(
        manifest,
        smoke_test=record,
        readiness="ready" if status == "passed" else "blocked",
    )
    write_manifest(path, updated)
    return updated


def default_environment() -> Mapping[str, str]:
    try:
        version = importlib.metadata.version("arisekit")
    except importlib.metadata.PackageNotFoundError:
        version = "source-tree"
    return {"python": ">=3.11", "arisekit": version}


def _inventory(root: Path, *, exclude: set[str]) -> tuple[RunnableAsset, ...]:
    assets: list[RunnableAsset] = []
    files = [value for value in root.rglob("*") if value.is_file()]
    for path in sorted(files, key=lambda value: value.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if relative in exclude or "__pycache__" in path.parts:
            continue
        payload = path.read_bytes()
        assets.append(
            RunnableAsset(
                path=relative,
                sha256=hashlib.sha256(payload).hexdigest(),
                size=len(payload),
            )
        )
    return tuple(assets)


def _safe_file(root: Path, relative: str) -> Path:
    _relative_path(relative, "runtime asset path")
    root_resolved = root.resolve()
    path = root_resolved / relative
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"runtime asset is missing or unsafe: {relative}")
    try:
        path.resolve().relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"runtime asset escapes benchmark root: {relative}") from exc
    return path


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fields(data: Any, expected: set[str], label: str) -> None:
    exact_fields(data, expected, label, kind=None)


def _relative_path(value: Any, name: str) -> str:
    text = _text(value, name)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or "\\" in text:
        raise ValueError(f"{name} must be a safe relative POSIX path")
    if str(path) in {"", "."}:
        raise ValueError(f"{name} must not be empty")
    return text


def _text(value: Any, name: str) -> str:
    return text(value, name, no_nul=True)


def _bad_asset() -> RunnableAsset:
    raise ValueError("every required_assets entry must be an object")


__all__ = [
    "CLAIM_BOUNDARY",
    "FILENAME",
    "SCHEMA_VERSION",
    "RunnableAsset",
    "RunnableBenchmarkManifest",
    "SmokeTestRecord",
    "authorize_run_request",
    "build_manifest_for_directory",
    "default_environment",
    "load_manifest",
    "record_smoke_test",
    "verify_assets",
    "write_manifest",
]
