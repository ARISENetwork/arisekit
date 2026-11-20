"""The benchmark package: a portable artifact ARISEKit emits and any runtime imports.

A package is a directory on disk:

  <pkg>/benchmark.json      manifest (id, name, version, modality, scorer, ...)
  <pkg>/cases.jsonl         one BenchmarkItem per line
  <pkg>/rubric.json         optional rubric (criteria, weights, scale)
  <pkg>/env.json            optional environment spec (tool set plus cohort ref)
  <pkg>/cohort/*.fhir.json  optional FHIR R4 bundles
  <pkg>/blueprint.json      optional serialized benchmark blueprint
  <pkg>/opportunity.json    optional frozen portfolio opportunity
  <pkg>/stress-spec.json    optional target-specific stress specification
  <pkg>/stress-validation.json optional sealed validation decision record
  <pkg>/stress-bootstrap.json optional bound confidence-interval artifact
  <pkg>/variants.jsonl      optional case-family variants
  <pkg>/rubrics/*.json      optional per-base rubrics
  <pkg>/guidance/*.yaml     optional per-base judge guidance, kept as text
  <pkg>/judge/**            optional frozen judge implementation assets
  <pkg>/review-log.jsonl    optional author/reviewer decision log
  <pkg>/asset-manifest.json optional SHA-256 inventory for strict loading
  <pkg>/README.md           optional human-readable sidecar

Cases reuse the existing BenchmarkItem shape, so authoring and running share one
record type with no new schema. `write_package` and `load_package` are the
round-trip on disk. `dataset_from_package` and `scorer_from_manifest` bind a
loaded package back into the runnable Dataset and BaseScorer types, so a runtime
can pick a package up and evaluate against it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Mapping

from arisekit.agentic import AgenticPassCondition
from arisekit.common.jsonio import strict_json_loads
from arisekit.dataset import Dataset
from arisekit.scorer import BaseScorer, choice, contains, exact_match, numeric
from arisekit.types import BenchmarkItem


# The modalities a manifest may declare. Text is a plain prompt, rubric is a
# rubric-graded free-text case, agentic-fhir is a tool-using FHIR task, and
# multimodal carries image (or other) attachments.
KNOWN_MODALITIES: tuple[str, ...] = ("text", "rubric", "agentic-fhir", "multimodal")

# Scorer kinds that map to a deterministic built-in factory (no client needed).
DETERMINISTIC_SCORER_KINDS: tuple[str, ...] = (
    "exact-match",
    "contains",
    "choice",
    "numeric",
    "pass-at-one",
    "fhir-outcome",
    "sct-concordance",
    "cpc-ranked-differential",
)

# Scorer kinds the caller must bind, since they need a judge client or an
# agentic environment: scorer_from_manifest returns None for these.
BOUND_SCORER_KINDS: tuple[str, ...] = (
    "rubric-panel",
    "trajectory-judge",
)

AGENTIC_FHIR_ENV_SCHEMA_VERSION = "arisekit.agentic-fhir-env.v1"
FHIR_TOOL_CATALOG_VERSION = "arisekit.fhir-tools.v1"
AGENTIC_FHIR_ENVIRONMENT = {
    "kind": "fhir-r4-in-memory",
    "primitive": "arisekit.env.fhir.FHIREnvironment",
    "fhir_version": "R4",
    "isolation": "per-item-trial",
}

IMAGE_ATTACHMENTS_SCHEMA_VERSION = "arisekit.image-attachments.v1"
IMAGE_ATTACHMENT_MEDIA_TYPES: tuple[str, ...] = ("image/jpeg", "image/png")
MAX_IMAGE_ATTACHMENTS_PER_ITEM = 4
MAX_IMAGE_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IMAGE_ATTACHMENT_BYTES = 100 * 1024 * 1024

ASSET_MANIFEST_SCHEMA_VERSION = "1"
ASSET_MANIFEST_ALGORITHM = "sha256"
ASSET_MANIFEST_FILENAME = "asset-manifest.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ATTACHMENT_PATH_RE = re.compile(
    r"^attachments/[A-Za-z0-9][A-Za-z0-9._-]{0,126}\.(?:png|jpe?g)$"
)


class PackageAssetError(ValueError):
    """A package asset is unsafe, malformed, or inconsistent."""


class PackageVerificationError(PackageAssetError):
    """Strict package verification failed."""


@dataclass(frozen=True)
class PackageAsset:
    """One raw-byte asset declared by an asset manifest."""

    path: str
    sha256: str
    size: int

    def __post_init__(self) -> None:
        canonical = _safe_relative_asset_path(self.path)
        if canonical == ASSET_MANIFEST_FILENAME:
            raise PackageAssetError("asset-manifest.json cannot declare itself")
        if not _SHA256_RE.fullmatch(self.sha256):
            raise PackageAssetError(
                f"asset {canonical!r} has an invalid SHA-256 digest"
            )
        if (
            isinstance(self.size, bool)
            or not isinstance(self.size, int)
            or self.size < 0
        ):
            raise PackageAssetError(f"asset {canonical!r} has an invalid byte size")

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PackageAsset":
        path = _safe_relative_asset_path(str(data.get("path", "")))
        digest = str(data.get("sha256", ""))
        size = data.get("size")
        return cls(path=path, sha256=digest, size=size)  # type: ignore[arg-type]


@dataclass(frozen=True)
class PackageAssetManifest:
    """Stable, lexicographically ordered inventory of package file bytes."""

    assets: tuple[PackageAsset, ...]
    schema_version: str = ASSET_MANIFEST_SCHEMA_VERSION
    algorithm: str = ASSET_MANIFEST_ALGORITHM

    def __post_init__(self) -> None:
        if self.schema_version != ASSET_MANIFEST_SCHEMA_VERSION:
            raise PackageAssetError(
                f"unsupported asset manifest schema version {self.schema_version!r}"
            )
        if self.algorithm != ASSET_MANIFEST_ALGORITHM:
            raise PackageAssetError(
                f"unsupported asset manifest algorithm {self.algorithm!r}"
            )
        paths = [asset.path for asset in self.assets]
        if len(paths) != len(set(paths)):
            raise PackageAssetError("asset manifest contains duplicate paths")
        if paths != sorted(paths):
            raise PackageAssetError(
                "asset manifest paths must be lexicographically ordered"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "algorithm": self.algorithm,
            "assets": [asset.to_dict() for asset in self.assets],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PackageAssetManifest":
        raw_assets = data.get("assets")
        if not isinstance(raw_assets, list):
            raise PackageAssetError("asset manifest assets must be a list")
        assets: list[PackageAsset] = []
        for index, raw in enumerate(raw_assets):
            if not isinstance(raw, dict):
                raise PackageAssetError(
                    f"asset manifest entry {index} must be an object"
                )
            assets.append(PackageAsset.from_dict(raw))
        return cls(
            assets=tuple(assets),
            schema_version=str(data.get("schema_version", "")),
            algorithm=str(data.get("algorithm", "")),
        )

    @classmethod
    def build(
        cls,
        root: str | Path,
        *,
        paths: Iterable[str] | None = None,
    ) -> "PackageAssetManifest":
        package_root = Path(root)
        if paths is None:
            asset_paths = sorted(
                path
                for path in _package_file_paths(package_root)
                if path != ASSET_MANIFEST_FILENAME
            )
        else:
            asset_paths = sorted({_safe_relative_asset_path(path) for path in paths})
        assets: list[PackageAsset] = []
        for relative in asset_paths:
            asset_path = _safe_package_file(package_root, relative, required=True)
            payload = asset_path.read_bytes()
            assets.append(
                PackageAsset(
                    path=relative,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    size=len(payload),
                )
            )
        return cls(assets=tuple(assets))

    def verify(self, root: str | Path, *, reject_extra: bool = True) -> None:
        package_root = Path(root)
        declared = {asset.path: asset for asset in self.assets}
        required_core = {"benchmark.json", "cases.jsonl"}
        undeclared_core = sorted(required_core - set(declared))
        if undeclared_core:
            raise PackageVerificationError(
                "asset manifest omits required package files: "
                + ", ".join(undeclared_core)
            )
        actual = set(_package_file_paths(package_root))
        actual.discard(ASSET_MANIFEST_FILENAME)
        declared_paths = set(declared)

        missing = sorted(declared_paths - actual)
        extra = sorted(actual - declared_paths)
        if missing:
            raise PackageVerificationError(
                f"asset manifest declares missing files: {', '.join(missing)}"
            )
        if reject_extra and extra:
            raise PackageVerificationError(
                f"package contains undeclared files: {', '.join(extra)}"
            )

        for relative, asset in declared.items():
            asset_path = _safe_package_file(package_root, relative, required=True)
            payload = asset_path.read_bytes()
            if len(payload) != asset.size:
                raise PackageVerificationError(
                    f"asset size mismatch for {relative}: {len(payload)} != {asset.size}"
                )
            digest = hashlib.sha256(payload).hexdigest()
            if not hmac.compare_digest(digest, asset.sha256):
                raise PackageVerificationError(f"asset hash mismatch for {relative}")


@dataclass
class BenchmarkManifest:
    """The benchmark.json manifest: identity, modality, and how to score.

    `scorer` is a small spec dict whose `kind` selects the scorer and whose
    remaining keys are passed through as options to the built-in factory.
    """

    id: str
    name: str
    version: str = "0.1.0"
    modality: str = "text"
    scorer: dict[str, Any] = field(default_factory=lambda: {"kind": "exact-match"})
    mast_compatible: bool = True
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "modality": self.modality,
            "scorer": self.scorer,
            "mast_compatible": self.mast_compatible,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkManifest":
        scorer = data.get("scorer")
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            version=str(data.get("version", "0.1.0")),
            modality=str(data.get("modality", "text")),
            scorer=(
                dict(scorer)
                if isinstance(scorer, dict) and scorer
                else {"kind": "exact-match"}
            ),
            mast_compatible=bool(data.get("mast_compatible", True)),
            provenance=dict(data.get("provenance", {})),
        )

    def validate(self) -> None:
        """Raise ValueError on a missing id/name/version or an unknown modality.

        This is a contract check, not a certification: it confirms the manifest
        is well-formed enough for a runtime to load, nothing about the quality
        of the benchmark itself.
        """
        missing = [
            key
            for key in ("id", "name", "version")
            if not str(getattr(self, key)).strip()
        ]
        if missing:
            raise ValueError(
                f"benchmark manifest is missing required field(s): {', '.join(missing)}"
            )
        if self.modality not in KNOWN_MODALITIES:
            raise ValueError(
                f"unknown modality {self.modality!r}; expected one of {', '.join(KNOWN_MODALITIES)}"
            )


@dataclass
class BenchmarkPackage:
    """An in-memory view of a benchmark package directory."""

    manifest: BenchmarkManifest
    items: list[BenchmarkItem]
    rubric: dict[str, Any] | None = None
    env: dict[str, Any] | None = None
    cohort: list[Path] = field(default_factory=list)
    attachments: dict[str, Any] | None = None
    attachment_files: list[Path] = field(default_factory=list)
    root: Path = field(default_factory=Path)
    blueprint: dict[str, Any] | None = None
    opportunity: dict[str, Any] | None = None
    stress_spec: dict[str, Any] | None = None
    stress_validation: dict[str, Any] | None = None
    stress_bootstrap: dict[str, Any] | None = None
    variants: list[dict[str, Any]] = field(default_factory=list)
    rubrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    guidance: dict[str, str] = field(default_factory=dict)
    judge_assets: dict[str, bytes] = field(default_factory=dict)
    review_log: list[dict[str, Any]] = field(default_factory=list)
    asset_manifest: PackageAssetManifest | None = None


@dataclass(frozen=True)
class AgenticFHIRBinding:
    """Validated runtime material for one portable agentic/FHIR package."""

    bundles: Mapping[str, dict[str, Any]]
    allowed_tools: tuple[str, ...]
    max_turns: int
    tools: tuple[Mapping[str, Any], ...]

    def build_sut(
        self,
        model: Any,
        *,
        system_prompt: str | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> Any:
        from arisekit.sut import FHIRAgentSUT

        return FHIRAgentSUT(
            model,
            self.bundles,
            allowed_tools=self.allowed_tools,
            system_prompt=system_prompt,
            max_iters=self.max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
        )


@dataclass(frozen=True)
class BoundImageAttachment:
    """One verified image asset bound to its package-local file."""

    path: str
    sha256: str
    size_bytes: int
    media_type: str
    file_path: Path


@dataclass(frozen=True)
class MultimodalImageBinding:
    """Validated image files and ordered case bindings for a package."""

    assets: Mapping[str, BoundImageAttachment]
    case_bindings: Mapping[str, tuple[str, ...]]

    def build_sut(self, model: Any) -> Any:
        from arisekit.sut import MultimodalImageSUT

        return MultimodalImageSUT(
            model,
            assets=self.assets,
            case_bindings=self.case_bindings,
        )


# --- read / write ----------------------------------------------------


def load_package(
    path: str | Path,
    *,
    verify_assets: bool = False,
) -> BenchmarkPackage:
    """Read a benchmark package directory into a BenchmarkPackage.

    benchmark.json and cases.jsonl are the load-bearing files. rubric.json,
    env.json, the cohort/ FHIR bundles, and README.md are optional and are
    simply skipped when absent. Archetype sidecars are also optional. Set
    ``verify_assets=True`` to require an asset manifest and reject missing,
    undeclared, symlinked, or hash-mismatched package files before loading.
    """
    root = Path(path)
    if not root.is_dir():
        raise FileNotFoundError(f"no benchmark.json in package {root}")

    asset_manifest_path = _safe_package_file(
        root, ASSET_MANIFEST_FILENAME, required=False
    )
    asset_manifest = (
        PackageAssetManifest.from_dict(_read_json(asset_manifest_path))
        if asset_manifest_path.is_file()
        else None
    )
    if verify_assets:
        if asset_manifest is None:
            raise PackageVerificationError(
                f"strict verification requires {ASSET_MANIFEST_FILENAME} in {root}"
            )
        asset_manifest.verify(root)

    manifest_path = _safe_package_file(root, "benchmark.json", required=False)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"no benchmark.json in package {root}")
    manifest = BenchmarkManifest.from_dict(_read_json(manifest_path))
    manifest.validate()

    cases_path = _safe_package_file(root, "cases.jsonl", required=False)
    items = [
        BenchmarkItem.from_dict(payload)
        for payload in _read_jsonl_objects(cases_path, required=True)
    ]

    rubric = _read_json_optional(
        _safe_package_file(root, "rubric.json", required=False)
    )
    env = _read_json_optional(_safe_package_file(root, "env.json", required=False))

    cohort_dir = _safe_package_directory(root, "cohort", required=False)
    cohort = (
        _safe_direct_files(root, cohort_dir, suffix=".fhir.json")
        if cohort_dir.is_dir()
        else []
    )

    attachments = _read_json_optional(
        _safe_package_file(root, "attachments.json", required=False)
    )
    attachments_dir = _safe_package_directory(
        root, "attachments", required=False
    )
    attachment_files = (
        _safe_direct_files(root, attachments_dir, suffix=None)
        if attachments_dir.is_dir()
        else []
    )

    blueprint_path = _safe_package_file(root, "blueprint.json", required=False)
    blueprint = _read_json_optional(blueprint_path)
    opportunity = _read_json_optional(
        _safe_package_file(root, "opportunity.json", required=False)
    )
    stress_spec = _read_json_optional(
        _safe_package_file(root, "stress-spec.json", required=False)
    )
    stress_validation = _read_json_optional(
        _safe_package_file(root, "stress-validation.json", required=False)
    )
    stress_bootstrap = _read_json_optional(
        _safe_package_file(root, "stress-bootstrap.json", required=False)
    )
    variants_path = _safe_package_file(root, "variants.jsonl", required=False)
    variants = _read_jsonl_objects(variants_path, required=False)

    rubrics_dir = _safe_package_directory(root, "rubrics", required=False)
    rubrics = (
        {
            file_path.stem: _read_json(file_path)
            for file_path in _safe_direct_files(root, rubrics_dir, suffix=".json")
        }
        if rubrics_dir.is_dir()
        else {}
    )

    guidance_dir = _safe_package_directory(root, "guidance", required=False)
    guidance = (
        {
            file_path.stem: file_path.read_bytes().decode("utf-8")
            for file_path in _safe_direct_files(root, guidance_dir, suffix=".yaml")
        }
        if guidance_dir.is_dir()
        else {}
    )

    judge_dir = _safe_package_directory(root, "judge", required=False)
    judge_assets = (
        {
            file_path.relative_to(judge_dir).as_posix(): file_path.read_bytes()
            for file_path in _safe_tree_files(root, judge_dir)
        }
        if judge_dir.is_dir()
        else {}
    )

    review_log_path = _safe_package_file(root, "review-log.jsonl", required=False)
    review_log = _read_jsonl_objects(review_log_path, required=False)

    return BenchmarkPackage(
        manifest=manifest,
        items=items,
        rubric=rubric,
        env=env,
        cohort=list(cohort),
        attachments=attachments,
        attachment_files=list(attachment_files),
        root=root,
        blueprint=blueprint,
        opportunity=opportunity,
        stress_spec=stress_spec,
        stress_validation=stress_validation,
        stress_bootstrap=stress_bootstrap,
        variants=variants,
        rubrics=rubrics,
        guidance=guidance,
        judge_assets=judge_assets,
        review_log=review_log,
        asset_manifest=asset_manifest,
    )


def write_package(
    path: str | Path,
    *,
    manifest: BenchmarkManifest,
    items: Iterable[BenchmarkItem],
    rubric: dict[str, Any] | None = None,
    env: dict[str, Any] | None = None,
    cohort_bundles: Iterable[dict[str, Any]] | None = None,
    attachment_assets: Mapping[str, bytes] | None = None,
    attachments: dict[str, Any] | None = None,
    readme: str | None = None,
    blueprint: dict[str, Any] | None = None,
    opportunity: dict[str, Any] | None = None,
    stress_spec: dict[str, Any] | None = None,
    stress_validation: dict[str, Any] | None = None,
    stress_bootstrap: dict[str, Any] | None = None,
    variants: Iterable[dict[str, Any]] | None = None,
    rubrics: Mapping[str, dict[str, Any]] | None = None,
    guidance: Mapping[str, str] | None = None,
    judge_assets: Mapping[str, str | bytes] | None = None,
    review_log: Iterable[dict[str, Any]] | None = None,
    write_asset_manifest: bool = False,
) -> Path:
    """Atomically create a new benchmark package directory."""
    destination = Path(path).expanduser()
    if destination.is_symlink():
        raise PackageAssetError(
            f"package output root cannot be a symlink: {destination}"
        )
    if destination.exists():
        if not destination.is_dir():
            raise PackageAssetError(
                f"package output root is not a directory: {destination}"
            )
        stale = sorted(path.name for path in destination.iterdir())
        if stale:
            raise PackageAssetError(
                "cannot write a package over stale package files: " + ", ".join(stale)
            )
        raise PackageAssetError(f"package output root already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.staging-",
            dir=destination.parent,
        )
    )
    try:
        _write_package_contents(
            stage,
            manifest=manifest,
            items=items,
            rubric=rubric,
            env=env,
            cohort_bundles=cohort_bundles,
            attachment_assets=attachment_assets,
            attachments=attachments,
            readme=readme,
            blueprint=blueprint,
            opportunity=opportunity,
            stress_spec=stress_spec,
            stress_validation=stress_validation,
            stress_bootstrap=stress_bootstrap,
            variants=variants,
            rubrics=rubrics,
            guidance=guidance,
            judge_assets=judge_assets,
            review_log=review_log,
            write_asset_manifest=write_asset_manifest,
        )
        os.rename(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return destination


def _write_package_contents(
    path: str | Path,
    *,
    manifest: BenchmarkManifest,
    items: Iterable[BenchmarkItem],
    rubric: dict[str, Any] | None = None,
    env: dict[str, Any] | None = None,
    cohort_bundles: Iterable[dict[str, Any]] | None = None,
    attachment_assets: Mapping[str, bytes] | None = None,
    attachments: dict[str, Any] | None = None,
    readme: str | None = None,
    blueprint: dict[str, Any] | None = None,
    opportunity: dict[str, Any] | None = None,
    stress_spec: dict[str, Any] | None = None,
    stress_validation: dict[str, Any] | None = None,
    stress_bootstrap: dict[str, Any] | None = None,
    variants: Iterable[dict[str, Any]] | None = None,
    rubrics: Mapping[str, dict[str, Any]] | None = None,
    guidance: Mapping[str, str] | None = None,
    judge_assets: Mapping[str, str | bytes] | None = None,
    review_log: Iterable[dict[str, Any]] | None = None,
    write_asset_manifest: bool = False,
) -> Path:
    """Write a benchmark package directory and return its root path.

    Creates the directory (and a cohort/ subdir when bundles are supplied),
    writes benchmark.json pretty-printed and cases.jsonl one item per line via
    `item.to_dict()`, plus any optional rubric/env/README/cohort files given.
    Each cohort bundle is written to cohort/<id>.fhir.json using the bundle's
    own `id` (falling back to a positional name). Archetype assets are written
    only when supplied. ``write_asset_manifest=True`` writes a deterministic
    SHA-256 inventory and refuses to bless stale files already in the target.
    """
    root = Path(path)
    if not isinstance(manifest, BenchmarkManifest):
        raise TypeError("manifest must be a BenchmarkManifest")
    manifest.validate()
    if root.is_symlink():
        raise PackageAssetError(f"package output root cannot be a symlink: {root}")
    root.mkdir(parents=True, exist_ok=True)

    for label, payload in (
        ("blueprint", blueprint),
        ("opportunity", opportunity),
        ("stress_spec", stress_spec),
        ("stress_validation", stress_validation),
        ("stress_bootstrap", stress_bootstrap),
    ):
        if payload is not None and not isinstance(payload, dict):
            raise TypeError(f"{label} must be a serialized dictionary")
    variant_records = _materialize_object_records(variants, "variants")
    review_records = _materialize_object_records(review_log, "review_log")
    rubric_payloads = _normalize_named_json_assets(rubrics, "rubrics")
    guidance_payloads = _normalize_guidance_assets(guidance)
    judge_payloads = _normalize_judge_assets(judge_assets)
    image_payloads = _normalize_image_attachment_assets(attachment_assets)
    image_manifest = _normalize_image_attachments_manifest(attachments)
    if bool(image_payloads) != (image_manifest is not None):
        raise PackageAssetError(
            "attachment_assets and attachments metadata must be supplied together"
        )
    if image_manifest is not None:
        _validate_attachment_payloads(image_manifest, image_payloads)
    written: set[str] = set()

    benchmark_path = _safe_output_file(root, "benchmark.json")
    _write_json(benchmark_path, manifest.to_dict())
    written.add("benchmark.json")

    cases_path = _safe_output_file(root, "cases.jsonl")
    with cases_path.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
    written.add("cases.jsonl")

    if rubric is not None:
        _write_json(_safe_output_file(root, "rubric.json"), rubric)
        written.add("rubric.json")
    if env is not None:
        _write_json(_safe_output_file(root, "env.json"), env)
        written.add("env.json")

    if cohort_bundles is not None:
        _safe_output_directory(root, "cohort")
        for idx, bundle in enumerate(cohort_bundles):
            bundle_id = _bundle_id(bundle, idx)
            relative = f"cohort/{_safe_asset_stem(bundle_id)}.fhir.json"
            _write_json(_safe_output_file(root, relative), bundle)
            written.add(relative)

    if image_manifest is not None:
        _write_json_canonical(
            _safe_output_file(root, "attachments.json"), image_manifest
        )
        written.add("attachments.json")
        for relative, payload in image_payloads.items():
            _safe_output_file(root, relative).write_bytes(payload)
            written.add(relative)

    if readme is not None:
        _safe_output_file(root, "README.md").write_text(readme, encoding="utf-8")
        written.add("README.md")

    if blueprint is not None:
        _write_json_canonical(_safe_output_file(root, "blueprint.json"), blueprint)
        written.add("blueprint.json")
    for relative, payload in (
        ("opportunity.json", opportunity),
        ("stress-spec.json", stress_spec),
        ("stress-validation.json", stress_validation),
        ("stress-bootstrap.json", stress_bootstrap),
    ):
        if payload is not None:
            _write_json_canonical(_safe_output_file(root, relative), payload)
            written.add(relative)

    if variant_records is not None:
        _write_jsonl_canonical(
            _safe_output_file(root, "variants.jsonl"), variant_records
        )
        written.add("variants.jsonl")

    for base_id, rubric_payload in rubric_payloads.items():
        relative = f"rubrics/{base_id}.json"
        _write_json_canonical(_safe_output_file(root, relative), rubric_payload)
        written.add(relative)

    for base_id, text in guidance_payloads.items():
        relative = f"guidance/{base_id}.yaml"
        _safe_output_file(root, relative).write_bytes(text.encode("utf-8"))
        written.add(relative)

    for judge_path, judge_content in judge_payloads.items():
        relative = f"judge/{judge_path}"
        _safe_output_file(root, relative).write_bytes(judge_content)
        written.add(relative)

    if review_records is not None:
        _write_jsonl_canonical(
            _safe_output_file(root, "review-log.jsonl"), review_records
        )
        written.add("review-log.jsonl")

    if write_asset_manifest:
        actual = set(_package_file_paths(root))
        actual.discard(ASSET_MANIFEST_FILENAME)
        stale = sorted(actual - written)
        if stale:
            raise PackageAssetError(
                "cannot write a strict asset manifest with stale package files: "
                + ", ".join(stale)
            )
        asset_manifest = PackageAssetManifest.build(root, paths=written)
        _write_json_canonical(
            _safe_output_file(root, ASSET_MANIFEST_FILENAME),
            asset_manifest.to_dict(),
        )

    return root


# --- binding back to runnable types ----------------------------------


def dataset_from_package(
    pkg_or_path: BenchmarkPackage | str | Path,
    *,
    system_prompt: str | None = None,
) -> Dataset:
    """Build a runnable Dataset from a package (or a package directory path).

    The dataset name is the manifest id, so downstream score CSVs and results
    directories line up with the package identity.
    """
    pkg = (
        pkg_or_path
        if isinstance(pkg_or_path, BenchmarkPackage)
        else load_package(pkg_or_path)
    )
    return Dataset.from_items(
        pkg.items,
        system_prompt=system_prompt,
        name=pkg.manifest.id,
    )


def scorer_from_manifest(manifest: BenchmarkManifest) -> BaseScorer | None:
    """Map a manifest's deterministic scorer kind to a built-in scorer.

    Text scorer kinds resolve to their arisekit.scorer factories, with the
    manifest's remaining scorer options forwarded as keyword arguments.
    rubric-panel and trajectory-judge return None because they need a judge
    client. The versioned pass-at-one scorer is deterministic over a recorded
    trajectory and therefore binds without a judge provider.
    """
    spec = dict(manifest.scorer or {})
    kind = spec.pop("kind", None)
    if kind == "rubric-judge":
        from arisekit.judges.rubric import RubricJudge
        return RubricJudge(**spec)
    if kind == "exact-match":
        return exact_match(**spec)
    if kind == "contains":
        return contains(**spec)
    if kind == "choice":
        return choice(**spec)
    if kind == "numeric":
        return numeric(**spec)
    if kind == "image-answer":
        from arisekit.images.imaging import ImageAnswerScorer
        if spec:
            raise ValueError("image-answer has no configurable scoring options")
        return ImageAnswerScorer()
    if kind in {"sct-concordance", "cpc-ranked-differential"}:
        from arisekit.generation.specialty_adapters import specialty_scorer_from_spec

        return specialty_scorer_from_spec({"kind": kind, **spec})
    if kind == "fhir-outcome":
        from arisekit.fhir.fhir_workflow import FHIROutcomeScorer
        return FHIROutcomeScorer(**spec)
    if kind == "pass-at-one":
        from arisekit.agentic import PassAtOneScorer

        allowed = {"name", "condition_schema"}
        unknown = sorted(set(spec) - allowed)
        if unknown:
            raise ValueError(
                "pass-at-one scorer has unsupported option(s): "
                + ", ".join(unknown)
            )
        return PassAtOneScorer(**spec)
    return None


def multimodal_image_binding_from_package(
    pkg: BenchmarkPackage,
) -> MultimodalImageBinding:
    """Validate and bind a portable image-attachment package.

    The package keeps canonical relative paths in ``cases.jsonl``. The binding
    resolves those paths only for model dispatch, which keeps run manifests
    portable while preventing the process working directory from influencing
    which bytes reach a model.
    """

    if not isinstance(pkg, BenchmarkPackage):
        raise TypeError("pkg must be a BenchmarkPackage")
    if pkg.manifest.modality != "multimodal":
        raise ValueError("multimodal image binding requires modality 'multimodal'")
    if pkg.attachments is None:
        raise ValueError("multimodal package is missing attachments.json")
    if pkg.env is not None or pkg.cohort:
        raise ValueError(
            "the image-attachment package binding cannot include an agentic environment or cohort"
        )

    normalized = _normalize_image_attachments_manifest(pkg.attachments)
    assert normalized is not None
    raw_assets = normalized["assets"]
    raw_bindings = normalized["case_bindings"]

    files_by_relative = {
        path.relative_to(pkg.root).as_posix(): path
        for path in pkg.attachment_files
    }
    declared_paths = [asset["path"] for asset in raw_assets]
    if set(declared_paths) != set(files_by_relative):
        raise ValueError(
            "attachments.json must declare every image file exactly; "
            f"missing={sorted(set(declared_paths) - set(files_by_relative))}, "
            f"extra={sorted(set(files_by_relative) - set(declared_paths))}"
        )

    assets: dict[str, BoundImageAttachment] = {}
    for asset in raw_assets:
        relative = asset["path"]
        file_path = files_by_relative[relative]
        payload = file_path.read_bytes()
        _validate_image_attachment_bytes(
            relative,
            payload,
            sha256=asset["sha256"],
            size_bytes=asset["size_bytes"],
            media_type=asset["media_type"],
        )
        assets[relative] = BoundImageAttachment(
            path=relative,
            sha256=asset["sha256"],
            size_bytes=asset["size_bytes"],
            media_type=asset["media_type"],
            file_path=file_path,
        )

    item_ids = [item.id for item in pkg.items]
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("multimodal package contains duplicate item ids")
    if set(raw_bindings) != set(item_ids):
        raise ValueError(
            "attachment case_bindings must cover every item exactly; "
            f"missing={sorted(set(item_ids) - set(raw_bindings))}, "
            f"extra={sorted(set(raw_bindings) - set(item_ids))}"
        )

    items_by_id = {item.id: item for item in pkg.items}
    bindings: dict[str, tuple[str, ...]] = {}
    referenced: set[str] = set()
    for item_id in item_ids:
        raw_paths = raw_bindings[item_id]
        if not isinstance(raw_paths, list):
            raise ValueError(
                f"attachment case_bindings.{item_id} must be a list"
            )
        paths: list[str] = []
        for index, raw_path in enumerate(raw_paths):
            if not isinstance(raw_path, str):
                raise ValueError(
                    f"attachment case_bindings.{item_id}[{index}] must be a string"
                )
            relative = _image_attachment_path(raw_path)
            if relative not in assets:
                raise ValueError(
                    f"item {item_id!r} names undeclared image asset {relative!r}"
                )
            paths.append(relative)
        if not paths:
            raise ValueError(
                f"multimodal item {item_id!r} must bind at least one image"
            )
        if len(paths) != len(set(paths)):
            raise ValueError(
                f"multimodal item {item_id!r} contains duplicate image bindings"
            )
        if items_by_id[item_id].attachments != paths:
            raise ValueError(
                f"item {item_id!r} attachments do not match attachments.json case_bindings"
            )
        bindings[item_id] = tuple(paths)
        referenced.update(paths)

    unbound = sorted(set(assets) - referenced)
    if unbound:
        raise ValueError(
            "attachments.json contains unbound image assets: " + ", ".join(unbound)
        )
    return MultimodalImageBinding(assets=assets, case_bindings=bindings)


def agentic_fhir_binding_from_package(
    pkg: BenchmarkPackage,
) -> AgenticFHIRBinding:
    """Validate and bind an ``agentic-fhir`` package to trusted primitives."""

    if not isinstance(pkg, BenchmarkPackage):
        raise TypeError("pkg must be a BenchmarkPackage")
    if pkg.manifest.modality != "agentic-fhir":
        raise ValueError("agentic FHIR binding requires modality 'agentic-fhir'")
    if pkg.env is None:
        raise ValueError("agentic-fhir package is missing env.json")

    if pkg.env.get("schema_version") == "arisekit.fhir-docker-env.v1":
        from arisekit.fhir.fhir_workflow import binding_from_package
        return binding_from_package(pkg)

    expected_fields = {
        "schema_version",
        "environment",
        "tool_catalog",
        "allowed_tools",
        "max_turns",
        "case_bindings",
        "tools",
    }
    if set(pkg.env) != expected_fields:
        raise ValueError(
            "agentic env fields differ; "
            f"missing={sorted(expected_fields - set(pkg.env))}, "
            f"extra={sorted(set(pkg.env) - expected_fields)}"
        )
    if pkg.env["schema_version"] != AGENTIC_FHIR_ENV_SCHEMA_VERSION:
        raise ValueError(
            "unsupported agentic FHIR environment schema "
            f"{pkg.env['schema_version']!r}"
        )
    if pkg.env["environment"] != AGENTIC_FHIR_ENVIRONMENT:
        raise ValueError(
            "agentic environment must bind the ARISEKit in-memory FHIR R4 "
            "primitive with per-item-trial isolation"
        )
    if pkg.env["tool_catalog"] != FHIR_TOOL_CATALOG_VERSION:
        raise ValueError(
            f"unsupported FHIR tool catalog {pkg.env['tool_catalog']!r}"
        )

    raw_allowed = pkg.env["allowed_tools"]
    if not isinstance(raw_allowed, list):
        raise ValueError("agentic env allowed_tools must be a list")
    allowed: list[str] = []
    for index, value in enumerate(raw_allowed):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"agentic env allowed_tools[{index}] must be a non-empty string"
            )
        allowed.append(value)
    if not allowed or len(allowed) != len(set(allowed)):
        raise ValueError("agentic env allowed_tools must be non-empty and unique")

    max_turns = pkg.env["max_turns"]
    if (
        isinstance(max_turns, bool)
        or not isinstance(max_turns, int)
        or max_turns < 1
    ):
        raise ValueError("agentic env max_turns must be a positive integer")

    catalog = _fhir_tool_schema_map()
    unknown_tools = sorted(set(allowed) - set(catalog))
    if unknown_tools:
        raise ValueError(
            "agentic env names unknown FHIR tool(s): " + ", ".join(unknown_tools)
        )
    expected_tools = [catalog[name] for name in allowed]
    if pkg.env["tools"] != expected_tools:
        raise ValueError(
            "agentic env tool schemas do not match the selected canonical catalog"
        )

    raw_bindings = pkg.env["case_bindings"]
    if not isinstance(raw_bindings, dict):
        raise ValueError("agentic env case_bindings must be an object")
    item_ids = [item.id for item in pkg.items]
    if set(raw_bindings) != set(item_ids):
        raise ValueError(
            "agentic env case_bindings must cover every item exactly; "
            f"missing={sorted(set(item_ids) - set(raw_bindings))}, "
            f"extra={sorted(set(raw_bindings) - set(item_ids))}"
        )

    cohort_by_relative = {
        path.relative_to(pkg.root).as_posix(): path for path in pkg.cohort
    }
    bindings: dict[str, str] = {}
    for item_id in item_ids:
        raw_path = raw_bindings[item_id]
        if not isinstance(raw_path, str):
            raise ValueError(f"case binding for {item_id!r} must be a string")
        relative = _safe_relative_asset_path(raw_path)
        parts = PurePosixPath(relative).parts
        if (
            len(parts) != 2
            or parts[0] != "cohort"
            or not parts[1].endswith(".fhir.json")
        ):
            raise ValueError(
                f"case binding for {item_id!r} must name a direct cohort/*.fhir.json asset"
            )
        if relative not in cohort_by_relative:
            raise ValueError(
                f"case binding for {item_id!r} names missing cohort asset {relative!r}"
            )
        bindings[item_id] = relative
    if len(set(bindings.values())) != len(bindings):
        raise ValueError("agentic env case bindings must use one cohort asset per item")
    if set(bindings.values()) != set(cohort_by_relative):
        raise ValueError("agentic env contains an unbound cohort asset")

    bundles: dict[str, dict[str, Any]] = {}
    items_by_id = {item.id: item for item in pkg.items}
    for item_id, relative in bindings.items():
        bundle = _read_json(cohort_by_relative[relative])
        _validate_fhir_bundle(bundle, item_id=item_id, path=relative)
        condition = AgenticPassCondition.from_dict(
            items_by_id[item_id].ground_truth
        )
        for call in condition.required_tool_calls:
            if call.name not in allowed:
                raise ValueError(
                    f"item {item_id!r} requires disallowed tool {call.name!r}"
                )
            _validate_tool_arguments(
                call.name,
                call.arguments,
                catalog[call.name]["parameters"],
                item_id=item_id,
            )
        bundles[item_id] = bundle

    return AgenticFHIRBinding(
        bundles=bundles,
        allowed_tools=tuple(allowed),
        max_turns=max_turns,
        tools=tuple(expected_tools),
    )


def _fhir_tool_schema_map() -> dict[str, dict[str, Any]]:
    from arisekit.env.fhir import FHIREnvironment, fhir_tools

    return {
        tool.name: {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        for tool in fhir_tools(FHIREnvironment([]))
    }


def _validate_fhir_bundle(
    bundle: dict[str, Any],
    *,
    item_id: str,
    path: str,
) -> None:
    if bundle.get("resourceType") != "Bundle":
        raise ValueError(f"{path} must contain a FHIR Bundle")
    if bundle.get("id") != item_id:
        raise ValueError(f"{path} Bundle.id must match item id {item_id!r}")
    if not isinstance(bundle.get("type"), str) or not bundle["type"].strip():
        raise ValueError(f"{path} Bundle.type must be non-empty")
    entries = bundle.get("entry", [])
    if not isinstance(entries, list):
        raise ValueError(f"{path} Bundle.entry must be a list")
    for index, entry in enumerate(entries):
        resource = entry.get("resource") if isinstance(entry, dict) else None
        if not isinstance(resource, dict):
            raise ValueError(f"{path} Bundle.entry[{index}] is missing a resource")
        resource_type = resource.get("resourceType")
        if not isinstance(resource_type, str) or not resource_type.strip():
            raise ValueError(
                f"{path} Bundle.entry[{index}].resource needs resourceType"
            )


def _validate_tool_arguments(
    name: str,
    arguments: Mapping[str, Any],
    parameters: Mapping[str, Any],
    *,
    item_id: str,
) -> None:
    properties = parameters.get("properties")
    required = parameters.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise ValueError(f"canonical schema for tool {name!r} is invalid")
    missing = sorted(set(required) - set(arguments))
    unknown = sorted(set(arguments) - set(properties))
    if missing or unknown:
        raise ValueError(
            f"item {item_id!r} call {name!r} arguments differ; "
            f"missing={missing}, unknown={unknown}"
        )
    for key, value in arguments.items():
        schema = properties[key]
        if schema.get("type") == "string" and not isinstance(value, str):
            raise ValueError(
                f"item {item_id!r} call {name!r} argument {key!r} must be a string"
            )
        choices = schema.get("enum")
        if isinstance(choices, list) and value not in choices:
            raise ValueError(
                f"item {item_id!r} call {name!r} argument {key!r} "
                f"must be one of {choices!r}"
            )


# --- internal helpers ------------------------------------------------


def _bundle_id(bundle: dict[str, Any], idx: int) -> str:
    """Filesystem-safe name for a FHIR bundle, from its id or its position."""
    raw = bundle.get("id") or f"bundle-{idx}"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(raw)).strip("-")
    return slug or f"bundle-{idx}"


def _read_json(path: Path) -> dict[str, Any]:
    payload = strict_json_loads(path.read_text(encoding="utf-8"), str(path))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _read_json_optional(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return _read_json(path)


def _write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def _write_json_canonical(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")


def _write_jsonl_canonical(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )


def _read_jsonl_objects(path: Path, *, required: bool) -> list[dict[str, Any]]:
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"required package asset not found: {path}")
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                payload = strict_json_loads(line, f"{path}:{line_no}")
            except json.JSONDecodeError as exc:
                raise ValueError(str(exc)) from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_no} must contain a JSON object")
            records.append(payload)
    return records


def _materialize_object_records(
    records: Iterable[dict[str, Any]] | None,
    label: str,
) -> list[dict[str, Any]] | None:
    if records is None:
        return None
    materialized = list(records)
    for index, record in enumerate(materialized):
        if not isinstance(record, dict):
            raise TypeError(f"{label} record {index} must be a dictionary")
    return materialized


def _normalize_named_json_assets(
    assets: Mapping[str, dict[str, Any]] | None,
    label: str,
) -> dict[str, dict[str, Any]]:
    if assets is None:
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_name, payload in assets.items():
        name = _safe_asset_stem(raw_name)
        if name in normalized:
            raise PackageAssetError(f"duplicate {label} asset name: {name}")
        if not isinstance(payload, dict):
            raise TypeError(f"{label} asset {name!r} must be a dictionary")
        normalized[name] = payload
    return dict(sorted(normalized.items()))


def _normalize_guidance_assets(
    assets: Mapping[str, str] | None,
) -> dict[str, str]:
    if assets is None:
        return {}
    normalized: dict[str, str] = {}
    for raw_name, text in assets.items():
        name = _safe_asset_stem(raw_name)
        if name in normalized:
            raise PackageAssetError(f"duplicate guidance asset name: {name}")
        if not isinstance(text, str):
            raise TypeError(f"guidance asset {name!r} must be raw text")
        normalized[name] = text
    return dict(sorted(normalized.items()))


def _normalize_judge_assets(
    assets: Mapping[str, str | bytes] | None,
) -> dict[str, bytes]:
    if assets is None:
        return {}
    normalized: dict[str, bytes] = {}
    for raw_path, content in assets.items():
        path = _safe_relative_asset_path(str(raw_path))
        if path in normalized:
            raise PackageAssetError(f"duplicate judge asset path: {path}")
        if isinstance(content, str):
            normalized[path] = content.encode("utf-8")
        elif isinstance(content, bytes):
            normalized[path] = content
        else:
            raise TypeError(f"judge asset {path!r} must be text or bytes")
    return dict(sorted(normalized.items()))


def _normalize_image_attachment_assets(
    assets: Mapping[str, bytes] | None,
) -> dict[str, bytes]:
    if assets is None:
        return {}
    normalized: dict[str, bytes] = {}
    for raw_path, payload in assets.items():
        path = _image_attachment_path(str(raw_path))
        if path in normalized:
            raise PackageAssetError(f"duplicate image attachment path: {path}")
        if not isinstance(payload, bytes):
            raise TypeError(f"image attachment {path!r} must be raw bytes")
        normalized[path] = payload
    return dict(sorted(normalized.items()))


def _normalize_image_attachments_manifest(
    value: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("attachments metadata must be a dictionary")
    expected = {"schema_version", "assets", "case_bindings"}
    if set(value) != expected:
        raise PackageAssetError(
            "attachments.json fields differ; "
            f"missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )
    if value["schema_version"] != IMAGE_ATTACHMENTS_SCHEMA_VERSION:
        raise PackageAssetError(
            "unsupported image attachment schema "
            f"{value['schema_version']!r}"
        )

    raw_assets = value["assets"]
    if not isinstance(raw_assets, list) or not raw_assets:
        raise PackageAssetError("attachments.json assets must be a non-empty list")
    assets: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    seen_folded_paths: set[str] = set()
    asset_fields = {"path", "sha256", "size_bytes", "media_type"}
    for index, raw_asset in enumerate(raw_assets):
        if not isinstance(raw_asset, dict) or set(raw_asset) != asset_fields:
            raise PackageAssetError(
                f"attachments.json assets[{index}] must contain exactly "
                "path, sha256, size_bytes, and media_type"
            )
        path = _image_attachment_path(raw_asset["path"])
        if path in seen_paths:
            raise PackageAssetError(
                f"attachments.json contains duplicate asset path {path!r}"
            )
        seen_paths.add(path)
        folded_path = path.casefold()
        if folded_path in seen_folded_paths:
            raise PackageAssetError(
                "attachments.json contains case-insensitive duplicate asset paths"
            )
        seen_folded_paths.add(folded_path)
        digest = raw_asset["sha256"]
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise PackageAssetError(
                f"attachments.json asset {path!r} has an invalid SHA-256 digest"
            )
        size = raw_asset["size_bytes"]
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 1
            or size > MAX_IMAGE_ATTACHMENT_BYTES
        ):
            raise PackageAssetError(
                f"attachments.json asset {path!r} size_bytes must be between "
                f"1 and {MAX_IMAGE_ATTACHMENT_BYTES}"
            )
        media_type = raw_asset["media_type"]
        if media_type not in IMAGE_ATTACHMENT_MEDIA_TYPES:
            raise PackageAssetError(
                f"attachments.json asset {path!r} media_type must be image/jpeg or image/png"
            )
        _validate_image_suffix(path, media_type)
        assets.append(
            {
                "path": path,
                "sha256": digest,
                "size_bytes": size,
                "media_type": media_type,
            }
        )
    paths = [asset["path"] for asset in assets]
    if paths != sorted(paths):
        raise PackageAssetError(
            "attachments.json assets must be sorted by path"
        )
    if sum(asset["size_bytes"] for asset in assets) > MAX_TOTAL_IMAGE_ATTACHMENT_BYTES:
        raise PackageAssetError(
            "attachments.json exceeds the 100 MiB aggregate image limit"
        )

    raw_bindings = value["case_bindings"]
    if not isinstance(raw_bindings, dict) or not raw_bindings:
        raise PackageAssetError(
            "attachments.json case_bindings must be a non-empty object"
        )
    bindings: dict[str, list[str]] = {}
    for raw_item_id, raw_paths in raw_bindings.items():
        if not isinstance(raw_item_id, str) or not raw_item_id.strip():
            raise PackageAssetError(
                "attachments.json case binding ids must be non-empty strings"
            )
        if not isinstance(raw_paths, list):
            raise PackageAssetError(
                f"attachments.json case_bindings.{raw_item_id} must be a list"
            )
        if not raw_paths or len(raw_paths) > MAX_IMAGE_ATTACHMENTS_PER_ITEM:
            raise PackageAssetError(
                f"attachments.json case_bindings.{raw_item_id} must contain "
                f"1-{MAX_IMAGE_ATTACHMENTS_PER_ITEM} image paths"
            )
        paths_for_item: list[str] = []
        for index, raw_path in enumerate(raw_paths):
            if not isinstance(raw_path, str):
                raise PackageAssetError(
                    f"attachments.json case_bindings.{raw_item_id}[{index}] must be a string"
                )
            paths_for_item.append(_image_attachment_path(raw_path))
        if len(paths_for_item) != len(set(paths_for_item)):
            raise PackageAssetError(
                f"attachments.json case_bindings.{raw_item_id} contains duplicate paths"
            )
        bindings[raw_item_id] = paths_for_item
    return {
        "schema_version": IMAGE_ATTACHMENTS_SCHEMA_VERSION,
        "assets": assets,
        "case_bindings": {key: bindings[key] for key in sorted(bindings)},
    }


def _validate_attachment_payloads(
    manifest: Mapping[str, Any],
    payloads: Mapping[str, bytes],
) -> None:
    assets = manifest["assets"]
    declared = {asset["path"]: asset for asset in assets}
    if set(declared) != set(payloads):
        raise PackageAssetError(
            "attachment payloads must exactly match attachments.json assets; "
            f"missing={sorted(set(declared) - set(payloads))}, "
            f"extra={sorted(set(payloads) - set(declared))}"
        )
    for path, asset in declared.items():
        _validate_image_attachment_bytes(
            path,
            payloads[path],
            sha256=asset["sha256"],
            size_bytes=asset["size_bytes"],
            media_type=asset["media_type"],
        )


def _image_attachment_path(raw: Any) -> str:
    if not isinstance(raw, str):
        raise PackageAssetError("image attachment path must be a string")
    path = _safe_relative_asset_path(raw)
    if not _IMAGE_ATTACHMENT_PATH_RE.fullmatch(path):
        raise PackageAssetError(
            "image attachment paths must be flat lowercase PNG/JPEG "
            "attachments/<filename> references"
        )
    return path


def _validate_image_suffix(path: str, media_type: str) -> None:
    suffix = PurePosixPath(path).suffix.lower()
    expected = {"image/png": {".png"}, "image/jpeg": {".jpg", ".jpeg"}}
    if suffix not in expected[media_type]:
        raise PackageAssetError(
            f"image attachment {path!r} extension does not match {media_type!r}"
        )


def _validate_image_attachment_bytes(
    path: str,
    payload: bytes,
    *,
    sha256: str,
    size_bytes: int,
    media_type: str,
) -> None:
    if len(payload) != size_bytes:
        raise PackageVerificationError(
            f"image attachment size mismatch for {path}: {len(payload)} != {size_bytes}"
        )
    digest = hashlib.sha256(payload).hexdigest()
    if not hmac.compare_digest(digest, sha256):
        raise PackageVerificationError(
            f"image attachment hash mismatch for {path}"
        )
    if media_type == "image/png":
        valid = payload.startswith(b"\x89PNG\r\n\x1a\n")
    elif media_type == "image/jpeg":
        valid = payload.startswith(b"\xff\xd8\xff") and payload.endswith(
            b"\xff\xd9"
        )
    else:  # The manifest parser rejects this before byte validation.
        valid = False
    if not valid:
        raise PackageVerificationError(
            f"image attachment {path} bytes do not match declared media type {media_type}"
        )


def _safe_asset_stem(raw: Any) -> str:
    name = str(raw)
    if (
        not name
        or name in {".", ".."}
        or any(character in name for character in ("/", "\\", ":", "\x00"))
    ):
        raise PackageAssetError(f"unsafe package asset name: {name!r}")
    return name


def _safe_relative_asset_path(raw: str) -> str:
    if not raw or "\\" in raw or ":" in raw or "\x00" in raw:
        raise PackageAssetError(f"unsafe package asset path: {raw!r}")
    pure = PurePosixPath(raw)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise PackageAssetError(f"unsafe package asset path: {raw!r}")
    normalized = pure.as_posix()
    if normalized != raw:
        raise PackageAssetError(f"package asset path is not canonical: {raw!r}")
    return normalized


def _safe_package_file(root: Path, relative: str, *, required: bool) -> Path:
    path = _package_path(root, relative)
    _reject_symlink_chain(root, path)
    if path.exists() and not path.is_file():
        raise PackageAssetError(f"package asset is not a regular file: {relative}")
    if required and not path.is_file():
        raise FileNotFoundError(f"required package asset not found: {path}")
    return path


def _safe_package_directory(root: Path, relative: str, *, required: bool) -> Path:
    path = _package_path(root, relative)
    _reject_symlink_chain(root, path)
    if path.exists() and not path.is_dir():
        raise PackageAssetError(f"package asset is not a directory: {relative}")
    if required and not path.is_dir():
        raise FileNotFoundError(f"required package directory not found: {path}")
    return path


def _safe_output_file(root: Path, relative: str) -> Path:
    path = _package_path(root, relative)
    parent_relative = PurePosixPath(_safe_relative_asset_path(relative)).parent
    if parent_relative.as_posix() != ".":
        _safe_output_directory(root, parent_relative.as_posix())
    _reject_symlink_chain(root, path)
    if path.exists() and not path.is_file():
        raise PackageAssetError(f"package output is not a regular file: {relative}")
    return path


def _safe_output_directory(root: Path, relative: str) -> Path:
    path = _package_path(root, relative)
    current = root
    for part in PurePosixPath(_safe_relative_asset_path(relative)).parts:
        current = current / part
        if current.is_symlink():
            raise PackageAssetError(f"package output directory is a symlink: {current}")
        if current.exists() and not current.is_dir():
            raise PackageAssetError(
                f"package output parent is not a directory: {current}"
            )
        current.mkdir(exist_ok=True)
    _assert_within_root(root, path)
    return path


def _package_path(root: Path, relative: str) -> Path:
    canonical = _safe_relative_asset_path(relative)
    path = root.joinpath(*PurePosixPath(canonical).parts)
    _assert_within_root(root, path)
    return path


def _assert_within_root(root: Path, path: Path) -> None:
    resolved_root = root.resolve()
    resolved_path = path.resolve(strict=False)
    if not resolved_path.is_relative_to(resolved_root):
        raise PackageAssetError(f"package asset escapes root: {path}")


def _reject_symlink_chain(root: Path, path: Path) -> None:
    if root.is_symlink():
        raise PackageAssetError(f"package root cannot be a symlink: {root}")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PackageAssetError(f"package asset escapes root: {path}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise PackageAssetError(f"package asset uses a symlink: {current}")


def _safe_direct_files(
    root: Path,
    directory: Path,
    *,
    suffix: str | None,
) -> list[Path]:
    files: list[Path] = []
    for entry in directory.iterdir():
        _reject_symlink_chain(root, entry)
        if entry.is_file() and (suffix is None or entry.name.endswith(suffix)):
            files.append(entry)
    return sorted(files, key=lambda path: path.name)


def _safe_tree_files(root: Path, directory: Path) -> list[Path]:
    files: list[Path] = []
    for current, dirnames, filenames in os.walk(directory, followlinks=False):
        current_path = Path(current)
        for dirname in dirnames:
            candidate = current_path / dirname
            if candidate.is_symlink():
                raise PackageAssetError(f"package asset uses a symlink: {candidate}")
        for filename in filenames:
            candidate = current_path / filename
            _reject_symlink_chain(root, candidate)
            if not candidate.is_file():
                raise PackageAssetError(
                    f"package asset is not a regular file: {candidate}"
                )
            files.append(candidate)
    return sorted(files, key=lambda path: path.relative_to(directory).as_posix())


def _package_file_paths(root: Path) -> list[str]:
    if root.is_symlink():
        raise PackageAssetError(f"package root cannot be a symlink: {root}")
    if not root.is_dir():
        raise FileNotFoundError(f"package directory not found: {root}")
    paths: list[str] = []
    for file_path in _safe_tree_files(root, root):
        relative = file_path.relative_to(root).as_posix()
        paths.append(_safe_relative_asset_path(relative))
    return sorted(paths)


__all__ = [
    "ASSET_MANIFEST_ALGORITHM",
    "ASSET_MANIFEST_FILENAME",
    "ASSET_MANIFEST_SCHEMA_VERSION",
    "AGENTIC_FHIR_ENV_SCHEMA_VERSION",
    "AGENTIC_FHIR_ENVIRONMENT",
    "BOUND_SCORER_KINDS",
    "DETERMINISTIC_SCORER_KINDS",
    "FHIR_TOOL_CATALOG_VERSION",
    "IMAGE_ATTACHMENTS_SCHEMA_VERSION",
    "IMAGE_ATTACHMENT_MEDIA_TYPES",
    "KNOWN_MODALITIES",
    "AgenticFHIRBinding",
    "BoundImageAttachment",
    "BenchmarkManifest",
    "BenchmarkPackage",
    "MultimodalImageBinding",
    "PackageAsset",
    "PackageAssetError",
    "PackageAssetManifest",
    "PackageVerificationError",
    "dataset_from_package",
    "agentic_fhir_binding_from_package",
    "multimodal_image_binding_from_package",
    "load_package",
    "scorer_from_manifest",
    "write_package",
]
