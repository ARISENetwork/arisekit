"""Export reviewed ARISEKit blueprints as deterministic NOHARM-compatible bundles.

The generated-bundle contract is intentionally separate from
``NoHarmReferenceBundle``. The latter continues to validate only the released
30-base/330-row public snapshot. This module validates ARISEKit-authored
bundles of any positive family count while retaining NOHARM's exact
baseline-plus-ten-perturbations topology.

Workflow completion is evidence that the declared review steps occurred. It is
not clinical approval and does not certify source rights, privacy, or MAST
admission.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, cast

from arisekit.authoring.blueprint import BenchmarkBlueprint, CaseFamily, OptionGuidance
from arisekit.dataset import Dataset
from arisekit.types import BenchmarkItem

from .adapter import (
    DEFAULT_K,
    PERTURBATIONS_PER_BASE,
    VARIANTS_PER_BASE,
    NoHarmAssetHashes,
    NoHarmSelection,
    dependency_lock_sha256,
)


BUNDLE_SCHEMA_VERSION = "arisekit.noharm-compatible-bundle.v2"
GENERATION_LINEAGE_SCHEMA_VERSION = "arisekit.generation-lineage.v1"
PINS_SCHEMA_VERSION = "arisekit.noharm-judge-pins.v1"
SELECTION_POLICY = "baseline-plus-first-perturbations"
WORKFLOW_ASSURANCE = (
    "Workflow-state evidence only; no clinical, rights, privacy, or benchmark "
    "admission certification."
)

_BASE_ID_RE = re.compile(r"^[A-Za-z]+\d{3}$")
_PROMPT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_ACCESS_CLASSIFICATIONS = ("private", "public", "restricted")


class NoHarmExportError(ValueError):
    """A blueprint or pinned asset cannot form a compatible bundle."""


class NoHarmCompatibleBundleError(ValueError):
    """A generated NOHARM-compatible bundle is malformed or has been altered."""


@dataclass(frozen=True)
class GenerationLineage:
    """Cryptographically bound provenance for the model generation run."""

    provider: str
    requested_model: str
    returned_model: str
    family: str
    response_ids: tuple[str, ...]
    generation_manifest_sha256: str
    generation_code_sha256: str
    generation_input_sha256: str
    generated_at: str

    def __post_init__(self) -> None:
        for label, value in (
            ("generation provider", self.provider),
            ("requested generation model", self.requested_model),
            ("returned generation model", self.returned_model),
            ("generation model family", self.family),
        ):
            _require_text(value, label)
        if isinstance(self.response_ids, (str, bytes)):
            raise NoHarmExportError("generation response_ids must be a sequence")
        response_ids = tuple(self.response_ids)
        if not response_ids:
            raise NoHarmExportError(
                "generation response_ids must contain at least one identifier"
            )
        for response_id in response_ids:
            _require_text(response_id, "generation response id")
        if len(set(response_ids)) != len(response_ids):
            raise NoHarmExportError("generation response_ids must be distinct")
        object.__setattr__(self, "response_ids", response_ids)
        for label, value in (
            ("generation manifest SHA-256", self.generation_manifest_sha256),
            ("generation code SHA-256", self.generation_code_sha256),
            ("generation input SHA-256", self.generation_input_sha256),
        ):
            _require_hash(value, label)
        _require_timestamp(self.generated_at, "generation timestamp")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": GENERATION_LINEAGE_SCHEMA_VERSION,
            "provider": self.provider,
            "requested_model": self.requested_model,
            "returned_model": self.returned_model,
            "family": self.family,
            "response_ids": list(self.response_ids),
            "generation_manifest_sha256": self.generation_manifest_sha256,
            "generation_code_sha256": self.generation_code_sha256,
            "generation_input_sha256": self.generation_input_sha256,
            "generated_at": self.generated_at,
        }

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())

    @property
    def manifest_identity(self) -> dict[str, Any]:
        return {
            **self.to_dict(),
            "digest": self.digest,
            "path": "provenance/generation-lineage.json",
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GenerationLineage":
        expected_keys = {
            "schema_version",
            "provider",
            "requested_model",
            "returned_model",
            "family",
            "response_ids",
            "generation_manifest_sha256",
            "generation_code_sha256",
            "generation_input_sha256",
            "generated_at",
        }
        if not isinstance(data, Mapping) or set(data) != expected_keys:
            raise NoHarmExportError(
                "generation lineage fields do not match its schema"
            )
        if data.get("schema_version") != GENERATION_LINEAGE_SCHEMA_VERSION:
            raise NoHarmExportError("unsupported generation lineage schema")
        response_ids = data.get("response_ids")
        if not isinstance(response_ids, list):
            raise NoHarmExportError("generation response_ids must be a list")
        return cls(
            provider=data.get("provider"),
            requested_model=data.get("requested_model"),
            returned_model=data.get("returned_model"),
            family=data.get("family"),
            response_ids=tuple(response_ids),
            generation_manifest_sha256=data.get("generation_manifest_sha256"),
            generation_code_sha256=data.get("generation_code_sha256"),
            generation_input_sha256=data.get("generation_input_sha256"),
            generated_at=data.get("generated_at"),
        )


@dataclass(frozen=True)
class PinnedNoHarmAssets:
    """Response and judge bytes whose exact hashes are part of the export."""

    response_prompt: str | bytes
    response_prompt_sha256: str
    judge_assets: Mapping[str, str | bytes]
    source_revision: str
    runtime_dependency_lock_sha256: str
    generation_lineage: GenerationLineage
    prompt_name: str = "default"

    def __post_init__(self) -> None:
        prompt_bytes = _asset_bytes(self.response_prompt, "response prompt")
        try:
            prompt_text = prompt_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NoHarmExportError("response prompt must be valid UTF-8") from exc
        if not prompt_text.strip():
            raise NoHarmExportError("response prompt must be non-empty")
        _require_hash(self.response_prompt_sha256, "response prompt SHA-256")
        actual = _sha256(prompt_bytes)
        if not hmac.compare_digest(actual, self.response_prompt_sha256):
            raise NoHarmExportError(
                "response prompt bytes do not match response_prompt_sha256"
            )
        if (
            not isinstance(self.prompt_name, str)
            or _PROMPT_NAME_RE.fullmatch(self.prompt_name) is None
            or self.prompt_name in (".", "..")
        ):
            raise NoHarmExportError("prompt_name must be a safe filename stem")
        if not isinstance(self.source_revision, str) or not self.source_revision.strip():
            raise NoHarmExportError("source_revision must be a non-empty string")
        _require_hash(
            self.runtime_dependency_lock_sha256,
            "runtime dependency lock SHA-256",
        )
        if not isinstance(self.generation_lineage, GenerationLineage):
            raise NoHarmExportError(
                "generation_lineage must be a GenerationLineage record"
            )
        if not isinstance(self.judge_assets, Mapping) or not self.judge_assets:
            raise NoHarmExportError("judge_assets must contain pinned judge files")

        normalized: dict[str, bytes] = {}
        for supplied_path, supplied_payload in self.judge_assets.items():
            relative = _safe_relative_path(supplied_path, label="judge asset")
            if relative == "pins.json":
                raise NoHarmExportError("judge/pins.json is generated by the exporter")
            if relative in normalized:
                raise NoHarmExportError(f"duplicate judge asset path: {relative}")
            payload = _asset_bytes(supplied_payload, f"judge asset {relative}")
            if not payload:
                raise NoHarmExportError(f"judge asset {relative} must not be empty")
            normalized[relative] = payload
        object.__setattr__(
            self,
            "judge_assets",
            MappingProxyType(dict(sorted(normalized.items()))),
        )
        object.__setattr__(self, "response_prompt", prompt_bytes)

    @property
    def response_prompt_bytes(self) -> bytes:
        value = self.response_prompt
        assert isinstance(value, bytes)
        return value

    @property
    def judge_asset_bytes(self) -> Mapping[str, bytes]:
        """Return the normalized bytes stored after construction."""
        return cast(Mapping[str, bytes], self.judge_assets)


class NoHarmCompatibleBundle:
    """Validated, read-only view of an ARISEKit-generated NOHARM bundle."""

    def __init__(self, root: str | Path):
        supplied = Path(root).expanduser()
        if supplied.is_symlink():
            raise NoHarmCompatibleBundleError("bundle root must not be a symlink")
        self.root = supplied.resolve()
        self.prompt_name = "default"
        self._manifest: dict[str, Any] = {}
        self._blueprint: BenchmarkBlueprint | None = None
        self._generation_lineage: GenerationLineage | None = None
        self._raw_items: tuple[dict[str, Any], ...] = ()
        self._by_id: dict[str, dict[str, Any]] = {}
        self._base_ids: tuple[str, ...] = ()
        self._prompt_template = ""
        self._rubrics: dict[str, dict[str, Any]] = {}
        self._perturbations: dict[str, dict[str, Any]] = {}
        self._hashes: NoHarmAssetHashes | None = None
        self._load_and_validate()

    @property
    def manifest(self) -> dict[str, Any]:
        return copy.deepcopy(self._manifest)

    @property
    def blueprint(self) -> BenchmarkBlueprint:
        if self._blueprint is None:
            raise RuntimeError("bundle blueprint was not loaded")
        return self._blueprint

    @property
    def generation_lineage(self) -> GenerationLineage:
        if self._generation_lineage is None:
            raise RuntimeError("bundle generation lineage was not loaded")
        return self._generation_lineage

    @property
    def prompt_template(self) -> str:
        return self._prompt_template

    @property
    def base_ids(self) -> tuple[str, ...]:
        return self._base_ids

    @property
    def row_count(self) -> int:
        return len(self._raw_items)

    @property
    def base_case_count(self) -> int:
        return len(self._base_ids)

    @property
    def items(self) -> tuple[BenchmarkItem, ...]:
        return tuple(self._to_benchmark_item(row) for row in self._raw_items)

    @property
    def base_cases(self) -> tuple[BenchmarkItem, ...]:
        return tuple(
            self._to_benchmark_item(self._by_id[base_id])
            for base_id in self._base_ids
        )

    def selection(
        self,
        k: int = DEFAULT_K,
        *,
        base_ids: Iterable[str] | None = None,
        base_limit: int | None = None,
    ) -> NoHarmSelection:
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= VARIANTS_PER_BASE:
            raise ValueError(f"k must be an integer from 1 to {VARIANTS_PER_BASE}")
        selected_bases = _select_base_ids(
            self._base_ids,
            base_ids=base_ids,
            base_limit=base_limit,
        )
        item_ids = tuple(
            item_id
            for base_id in selected_bases
            for item_id in (
                base_id,
                *(f"{base_id}-{index}" for index in range(k - 1)),
            )
        )
        return NoHarmSelection(
            k=k,
            base_ids=selected_bases,
            item_ids=item_ids,
        )

    def select(
        self,
        k: int = DEFAULT_K,
        *,
        base_ids: Iterable[str] | None = None,
        base_limit: int | None = None,
    ) -> tuple[BenchmarkItem, ...]:
        selection = self.selection(k, base_ids=base_ids, base_limit=base_limit)
        return tuple(
            self._to_benchmark_item(self._by_id[item_id])
            for item_id in selection.item_ids
        )

    def dataset(
        self,
        k: int = DEFAULT_K,
        *,
        base_ids: Iterable[str] | None = None,
        base_limit: int | None = None,
    ) -> Dataset:
        return Dataset.from_items(
            self.select(k, base_ids=base_ids, base_limit=base_limit),
            name="donoharm",
        )

    def rubric_for(self, item_id: str) -> dict[str, Any]:
        row = self._by_id.get(str(item_id))
        if row is None:
            raise KeyError(f"unknown NOHARM item id: {item_id}")
        return copy.deepcopy(self._rubrics[str(row["metadata"]["base_id"])])

    @property
    def hashes(self) -> NoHarmAssetHashes:
        if self._hashes is None:
            asset_hashes = {
                record["path"]: record["sha256"]
                for record in self._manifest["assets"]
            }
            data_assets = {
                name: digest
                for name, digest in asset_hashes.items()
                if name.startswith(("dataset/", "guidance/", "prompts/"))
            }
            judge_assets = {
                name: digest
                for name, digest in asset_hashes.items()
                if name.startswith("judge/")
            }
            content = {
                "items": self._raw_items,
                "rubrics": self._rubrics,
                "perturbations": self._perturbations,
                "guidance": {
                    base_id: _read_json(
                        self.root / "guidance" / f"{base_id}.yaml",
                        error_type=NoHarmCompatibleBundleError,
                    )
                    for base_id in self._base_ids
                },
                "prompt": self._prompt_template,
            }
            self._hashes = NoHarmAssetHashes(
                content_sha256=_sha256_json(content),
                data_sha256=_sha256_json(data_assets),
                judge_sha256=_sha256_json(judge_assets),
                runtime_dependency_lock_sha256=(
                    self._manifest["judge_contract"].get(
                        "runtime_dependency_lock_sha256"
                    )
                    or dependency_lock_sha256(asset_hashes)
                ),
                bundle_sha256=_sha256_json(asset_hashes),
                assets=MappingProxyType(asset_hashes),
            )
        return self._hashes

    def _to_benchmark_item(self, row: Mapping[str, Any]) -> BenchmarkItem:
        case_prompt = str(row["prompt"])
        prompt = (
            f"{self._prompt_template}\n\n{case_prompt}"
            if self._prompt_template
            else case_prompt
        )
        return BenchmarkItem(
            id=str(row["id"]),
            prompt=prompt,
            metadata=copy.deepcopy(row["metadata"]),
            ground_truth=copy.deepcopy(row.get("ground_truth")),
        )

    def _load_and_validate(self) -> None:
        if not self.root.is_dir():
            raise FileNotFoundError(
                f"NOHARM-compatible bundle directory not found: {self.root}"
            )
        _reject_symlinks(self.root)
        manifest_path = self.root / "bundle-manifest.json"
        self._manifest = _read_json(
            manifest_path,
            error_type=NoHarmCompatibleBundleError,
        )
        _verify_manifest_inventory(self.root, self._manifest)
        expected_manifest_keys = {
            "access",
            "assets",
            "assurance",
            "blueprint",
            "bundle_kind",
            "generation_lineage",
            "judge_contract",
            "response_prompt",
            "schema_version",
            "selection",
            "source_revision",
            "topology",
        }
        if set(self._manifest) != expected_manifest_keys:
            raise NoHarmCompatibleBundleError(
                "bundle manifest fields do not match the generated contract"
            )
        if self._manifest.get("schema_version") != BUNDLE_SCHEMA_VERSION:
            raise NoHarmCompatibleBundleError("unsupported compatible bundle schema")
        if self._manifest.get("bundle_kind") != "generated-noharm-compatible":
            raise NoHarmCompatibleBundleError("bundle_kind is not generated NOHARM")
        if self._manifest.get("assurance") != WORKFLOW_ASSURANCE:
            raise NoHarmCompatibleBundleError(
                "bundle workflow assurance statement is missing or altered"
            )
        lineage_payload = _read_json(
            self.root / "provenance" / "generation-lineage.json",
            error_type=NoHarmCompatibleBundleError,
        )
        try:
            lineage = GenerationLineage.from_dict(lineage_payload)
        except (TypeError, ValueError) as exc:
            raise NoHarmCompatibleBundleError(
                f"generation lineage is invalid: {exc}"
            ) from exc
        if self._manifest.get("generation_lineage") != lineage.manifest_identity:
            raise NoHarmCompatibleBundleError(
                "bundle manifest generation lineage does not match provenance"
            )
        self._generation_lineage = lineage

        blueprint_payload = _read_json(
            self.root / "provenance" / "blueprint.json",
            error_type=NoHarmCompatibleBundleError,
        )
        try:
            blueprint = BenchmarkBlueprint.from_dict(blueprint_payload)
            families = _validated_families(
                blueprint,
                expected_base_cases=None,
                error_type=NoHarmCompatibleBundleError,
            )
        except NoHarmCompatibleBundleError:
            raise
        except (TypeError, ValueError) as exc:
            raise NoHarmCompatibleBundleError(
                f"provenance blueprint is invalid: {exc}"
            ) from exc
        self._blueprint = blueprint
        self._base_ids = tuple(family.id for family in families)

        topology = self._manifest.get("topology")
        expected_topology = _topology(self._base_ids)
        if topology != expected_topology:
            raise NoHarmCompatibleBundleError(
                "bundle manifest topology does not match provenance blueprint"
            )
        identity = self._manifest.get("blueprint")
        expected_identity = {
            "digest": blueprint.digest,
            "id": blueprint.id,
            "schema_version": blueprint.schema_version,
            "version": blueprint.version,
        }
        if identity != expected_identity:
            raise NoHarmCompatibleBundleError(
                "bundle manifest blueprint identity does not match provenance"
            )
        expected_judge_identity = {
            "digest": blueprint.judge_contract.digest,
            "id": blueprint.judge_contract.id,
            "version": blueprint.judge_contract.version,
        }
        if blueprint.judge_contract.runtime_dependency_lock_sha256 is not None:
            expected_judge_identity["runtime_dependency_lock_sha256"] = (
                blueprint.judge_contract.runtime_dependency_lock_sha256
            )
        if self._manifest.get("judge_contract") != expected_judge_identity:
            raise NoHarmCompatibleBundleError(
                "bundle manifest judge identity does not match provenance"
            )

        prompt = self._manifest.get("response_prompt")
        if not isinstance(prompt, dict):
            raise NoHarmCompatibleBundleError("response_prompt manifest entry is invalid")
        prompt_name = prompt.get("name")
        if (
            not isinstance(prompt_name, str)
            or _PROMPT_NAME_RE.fullmatch(prompt_name) is None
        ):
            raise NoHarmCompatibleBundleError("manifest prompt name is unsafe")
        self.prompt_name = prompt_name
        prompt_path = f"prompts/{prompt_name}.md"
        if prompt.get("path") != prompt_path:
            raise NoHarmCompatibleBundleError("response prompt path is not canonical")
        prompt_bytes = _required_bytes(
            self.root / prompt_path,
            error_type=NoHarmCompatibleBundleError,
        )
        if _sha256(prompt_bytes) != prompt.get("sha256"):
            raise NoHarmCompatibleBundleError("response prompt hash does not match")
        try:
            self._prompt_template = prompt_bytes.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise NoHarmCompatibleBundleError(
                "response prompt must be valid UTF-8"
            ) from exc
        if not self._prompt_template:
            raise NoHarmCompatibleBundleError("response prompt must not be empty")
        _validate_response_contract(
            blueprint,
            prompt_bytes,
            error_type=NoHarmCompatibleBundleError,
        )

        source_revision = self._manifest.get("source_revision")
        if not isinstance(source_revision, str) or not source_revision.strip():
            raise NoHarmCompatibleBundleError("source_revision is missing")
        access = self._manifest.get("access")
        if not isinstance(access, dict):
            raise NoHarmCompatibleBundleError("bundle access declaration is missing")
        access_classification = access.get("classification")
        if access_classification not in _ACCESS_CLASSIFICATIONS:
            raise NoHarmCompatibleBundleError(
                "bundle access classification is invalid"
            )
        if access != _access_record(blueprint, access_classification):
            raise NoHarmCompatibleBundleError(
                "bundle access declaration does not match blueprint source rights"
            )
        judge_paths = _verify_judge_pins(
            self.root,
            blueprint,
            source_revision=source_revision,
            prompt_name=prompt_name,
            prompt_sha256=str(prompt.get("sha256", "")),
        )

        expected_non_judge = _rendered_non_judge_assets(
            blueprint,
            families,
            generation_lineage=lineage,
            prompt_name=prompt_name,
            response_prompt=prompt_bytes,
            source_revision=source_revision,
            access_classification=access_classification,
        )
        actual_paths = {
            record["path"]
            for record in self._manifest["assets"]
            if not record["path"].startswith("judge/")
        }
        if actual_paths != set(expected_non_judge):
            raise NoHarmCompatibleBundleError(
                "generated bundle contains unexpected or missing non-judge assets"
            )
        for relative, expected_bytes in expected_non_judge.items():
            actual_bytes = _required_bytes(
                self.root / relative,
                error_type=NoHarmCompatibleBundleError,
            )
            if actual_bytes != expected_bytes:
                raise NoHarmCompatibleBundleError(
                    f"generated asset does not match provenance blueprint: {relative}"
                )
        expected_judge_paths = {f"judge/{path}" for path in judge_paths} | {
            "judge/pins.json"
        }
        actual_judge_paths = {
            record["path"]
            for record in self._manifest["assets"]
            if record["path"].startswith("judge/")
        }
        if actual_judge_paths != expected_judge_paths:
            raise NoHarmCompatibleBundleError(
                "judge pins do not correspond exactly to judge assets"
            )

        self._raw_items = tuple(
            _read_jsonl(
                self.root / "dataset" / "items.jsonl",
                error_type=NoHarmCompatibleBundleError,
            )
        )
        self._by_id = {str(row["id"]): row for row in self._raw_items}
        self._rubrics = {
            family.id: _read_json(
                self.root / "dataset" / "rubrics" / f"{family.id}.json",
                error_type=NoHarmCompatibleBundleError,
            )
            for family in families
        }
        self._perturbations = {
            item_id: _read_json(
                self.root / "dataset" / "perturbations" / f"{item_id}.json",
                error_type=NoHarmCompatibleBundleError,
            )
            for item_id in self._by_id
        }

        default_selection = self.selection(DEFAULT_K).to_dict()
        selection_contract = self._manifest.get("selection")
        if selection_contract != {
            "default": default_selection,
            "policy": SELECTION_POLICY,
            "supports": ["base_ids", "base_limit", "k"],
        }:
            raise NoHarmCompatibleBundleError(
                "manifest selection identity does not match bundle topology"
            )


def export_noharm_bundle(
    blueprint: BenchmarkBlueprint,
    output_path: str | Path,
    *,
    assets: PinnedNoHarmAssets,
    access_classification: str,
    expected_base_cases: int | None = None,
) -> NoHarmCompatibleBundle:
    """Write one immutable generated bundle and return its validated view.

    An existing byte-identical bundle is accepted for idempotency. Any stale or
    different existing target is left untouched and rejected.
    """

    if not isinstance(blueprint, BenchmarkBlueprint):
        raise TypeError("blueprint must be a BenchmarkBlueprint")
    if not isinstance(assets, PinnedNoHarmAssets):
        raise TypeError("assets must be PinnedNoHarmAssets")
    if access_classification not in _ACCESS_CLASSIFICATIONS:
        raise NoHarmExportError(
            "access_classification must be public, restricted, or private"
        )
    _validate_export_authorization(blueprint, access_classification)
    _validate_response_contract(
        blueprint,
        assets.response_prompt_bytes,
        error_type=NoHarmExportError,
    )
    families = _validated_families(
        blueprint,
        expected_base_cases=expected_base_cases,
        error_type=NoHarmExportError,
    )
    judge_assets = assets.judge_asset_bytes
    runtime_dependency_lock = (
        blueprint.judge_contract.runtime_dependency_lock_sha256
    )
    if runtime_dependency_lock is None:
        raise NoHarmExportError(
            "judge contract requires runtime_dependency_lock_sha256 for export"
        )
    if not hmac.compare_digest(
        runtime_dependency_lock,
        assets.runtime_dependency_lock_sha256,
    ):
        raise NoHarmExportError(
            "pinned runtime dependency lock does not match the judge contract"
        )
    _validate_judge_contract_assets(
        blueprint,
        judge_assets,
        error_type=NoHarmExportError,
    )

    supplied_output = Path(output_path).expanduser()
    if supplied_output.is_symlink():
        raise NoHarmExportError("output path must not be a symlink")
    output = supplied_output.absolute()
    if not output.name or output.name in (".", ".."):
        raise NoHarmExportError("output path must name a bundle directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.parent.is_symlink():
        raise NoHarmExportError("output parent must not be a symlink")

    stage = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent)
    )
    try:
        non_judge_assets = _rendered_non_judge_assets(
            blueprint,
            families,
            generation_lineage=assets.generation_lineage,
            prompt_name=assets.prompt_name,
            response_prompt=assets.response_prompt_bytes,
            source_revision=assets.source_revision,
            access_classification=access_classification,
        )
        for relative, payload in non_judge_assets.items():
            _write_bytes(stage, relative, payload)
        for relative, payload in judge_assets.items():
            _write_bytes(stage, f"judge/{relative}", payload)

        judge_hashes = {
            relative: _sha256(payload)
            for relative, payload in judge_assets.items()
        }
        pins = {
            "schema_version": PINS_SCHEMA_VERSION,
            "source_revision": assets.source_revision,
            "response_prompt": {
                "name": assets.prompt_name,
                "sha256": assets.response_prompt_sha256,
            },
            "judge_contract": {
                "digest": blueprint.judge_contract.digest,
                "id": blueprint.judge_contract.id,
                "version": blueprint.judge_contract.version,
                "runtime_dependency_lock_sha256": (
                    assets.runtime_dependency_lock_sha256
                ),
            },
            "assets": judge_hashes,
        }
        _write_bytes(stage, "judge/pins.json", _json_bytes(pins))

        inventory = _build_inventory(stage)
        base_ids = tuple(family.id for family in families)
        manifest = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "bundle_kind": "generated-noharm-compatible",
            "assurance": WORKFLOW_ASSURANCE,
            "blueprint": {
                "digest": blueprint.digest,
                "id": blueprint.id,
                "schema_version": blueprint.schema_version,
                "version": blueprint.version,
            },
            "source_revision": assets.source_revision,
            "access": _access_record(blueprint, access_classification),
            "generation_lineage": assets.generation_lineage.manifest_identity,
            "response_prompt": {
                "name": assets.prompt_name,
                "path": f"prompts/{assets.prompt_name}.md",
                "sha256": assets.response_prompt_sha256,
            },
            "judge_contract": {
                "digest": blueprint.judge_contract.digest,
                "id": blueprint.judge_contract.id,
                "version": blueprint.judge_contract.version,
                "runtime_dependency_lock_sha256": (
                    assets.runtime_dependency_lock_sha256
                ),
            },
            "topology": _topology(base_ids),
            "selection": {
                "default": _selection_for(base_ids, DEFAULT_K).to_dict(),
                "policy": SELECTION_POLICY,
                "supports": ["base_ids", "base_limit", "k"],
            },
            "assets": inventory,
        }
        manifest_bytes = _json_bytes(manifest)
        _write_bytes(stage, "bundle-manifest.json", manifest_bytes)

        NoHarmCompatibleBundle(stage)
        if output.exists():
            if not output.is_dir() or output.is_symlink():
                raise FileExistsError(
                    f"NOHARM export target exists and is not a safe directory: {output}"
                )
            try:
                existing = NoHarmCompatibleBundle(output)
            except (FileNotFoundError, NoHarmCompatibleBundleError) as exc:
                raise FileExistsError(
                    f"NOHARM export target exists but is stale or invalid: {output}"
                ) from exc
            existing_bytes = (output / "bundle-manifest.json").read_bytes()
            if existing_bytes != manifest_bytes:
                raise FileExistsError(
                    f"NOHARM export target contains different content: {output}"
                )
            return existing

        os.rename(stage, output)
        return NoHarmCompatibleBundle(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _validated_families(
    blueprint: BenchmarkBlueprint,
    *,
    expected_base_cases: int | None,
    error_type: type[ValueError],
) -> tuple[CaseFamily, ...]:
    if blueprint.review_stage != "workflow_complete":
        raise error_type("blueprint must be workflow_complete before export")
    families = tuple(sorted(blueprint.case_families, key=lambda family: family.id))
    if expected_base_cases is not None:
        if (
            isinstance(expected_base_cases, bool)
            or not isinstance(expected_base_cases, int)
            or expected_base_cases < 1
        ):
            raise error_type("expected_base_cases must be a positive integer or null")
        if len(families) != expected_base_cases:
            raise error_type(
                f"expected {expected_base_cases} base cases; found {len(families)}"
            )
    for family in families:
        if _BASE_ID_RE.fullmatch(family.id) is None:
            raise error_type(
                f"case family {family.id!r} is not a canonical NOHARM base id"
            )
        if family.review.stage != "workflow_complete":
            raise error_type(f"case family {family.id!r} is not workflow_complete")
        if len(family.variants) != PERTURBATIONS_PER_BASE:
            raise error_type(
                f"case family {family.id!r} requires exactly "
                f"{PERTURBATIONS_PER_BASE} variants"
            )
        expected_variants = {
            f"{family.id}-{index}" for index in range(PERTURBATIONS_PER_BASE)
        }
        actual_variants = {variant.id for variant in family.variants}
        if actual_variants != expected_variants:
            raise error_type(
                f"case family {family.id!r} variants must be named "
                f"{family.id}-0 through {family.id}-9"
            )
        if any(
            not variant.is_attested or variant.presentation.status != "clinician_locked"
            for variant in family.variants
        ):
            raise error_type(
                f"case family {family.id!r} has an unreviewed perturbation"
            )
        if any(variant.category.casefold() == "baseline" for variant in family.variants):
            raise error_type(
                f"case family {family.id!r} perturbations cannot use baseline category"
            )
        if family.guidance is None or not family.guidance.is_locked:
            raise error_type(
                f"case family {family.id!r} requires clinician-locked guidance"
            )

        numeric_ids: dict[str, int] = {}
        for option in family.rubric_options:
            if not option.id.isdecimal():
                raise error_type(
                    f"case family {family.id!r} rubric option ids must be positive integers"
                )
            numeric = int(option.id)
            if numeric < 1 or str(numeric) != option.id:
                raise error_type(
                    f"case family {family.id!r} rubric option id "
                    f"{option.id!r} is not canonical"
                )
            numeric_ids[option.id] = numeric
        if len(numeric_ids) != len(family.rubric_options):
            raise error_type(f"case family {family.id!r} has duplicate numeric option ids")
        if sum(option.harm_of_inaction for option in family.rubric_options) != 1:
            raise error_type(
                f"case family {family.id!r} requires exactly one harm-of-inaction option"
            )

        membership: dict[str, list[str]] = {}
        for group in family.rubric_groups:
            for option_id in group.option_ids:
                membership.setdefault(option_id, []).append(group.id)
        duplicate_memberships = sorted(
            option_id
            for option_id, group_ids in membership.items()
            if len(group_ids) > 1
        )
        if duplicate_memberships:
            raise error_type(
                f"case family {family.id!r} options belong to multiple rubric groups: "
                + ", ".join(duplicate_memberships)
            )
        groups_by_id = {group.id: group for group in family.rubric_groups}
        groups_by_name = {group.name: group for group in family.rubric_groups}
        for option in family.rubric_options:
            member_group = (
                groups_by_id[membership[option.id][0]]
                if option.id in membership
                else None
            )
            if option.abstraction_type == "alternative":
                linked = groups_by_id.get(option.abstraction or "") or groups_by_name.get(
                    option.abstraction or ""
                )
                if linked is None or option.id not in linked.option_ids:
                    raise error_type(
                        f"case family {family.id!r} option {option.id!r} has "
                        "inconsistent alternative-group linkage"
                    )
            elif member_group is not None:
                raise error_type(
                    f"case family {family.id!r} option {option.id!r} belongs to "
                    "a group but is not marked as an alternative"
                )

        guidance_ids = {
            rule.option_id for rule in family.guidance.option_rules
        }
        unknown_guidance = sorted(guidance_ids - set(numeric_ids))
        if unknown_guidance:
            raise error_type(
                f"case family {family.id!r} guidance references unknown options: "
                + ", ".join(unknown_guidance)
            )
    return families


def _validate_export_authorization(
    blueprint: BenchmarkBlueprint,
    access_classification: str,
) -> None:
    scope_rank = {"private": 0, "restricted": 1, "public": 2}
    for source in blueprint.sources:
        if source.rights_basis == "unknown":
            raise NoHarmExportError(
                f"source {source.id!r} has unknown rights and cannot be exported"
            )
        if (
            source.release_scope is None
            or source.release_authorization_hash is None
            or source.release_authorized_by is None
            or source.release_authorized_at is None
        ):
            raise NoHarmExportError(
                f"source {source.id!r} requires an explicit data-owner release authorization"
            )
        if scope_rank[source.release_scope] < scope_rank[access_classification]:
            raise NoHarmExportError(
                f"source {source.id!r} is authorized for {source.release_scope} access, "
                f"not {access_classification}"
            )


def _validate_response_contract(
    blueprint: BenchmarkBlueprint,
    response_prompt: bytes,
    *,
    error_type: type[ValueError],
) -> None:
    contract = blueprint.response_contract
    if contract.instruction_delivery != "user_message_preamble":
        raise error_type(
            "NOHARM-compatible export requires user_message_preamble instruction delivery"
        )
    if contract.system_prompt is not None:
        raise error_type(
            "NOHARM-compatible export cannot encode a separate system prompt"
        )
    try:
        rendered = response_prompt.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise error_type("response prompt must be valid UTF-8") from exc
    if rendered != contract.instructions.strip():
        raise error_type(
            "pinned response prompt does not match the blueprint response contract"
        )


def _rendered_non_judge_assets(
    blueprint: BenchmarkBlueprint,
    families: tuple[CaseFamily, ...],
    *,
    generation_lineage: GenerationLineage,
    prompt_name: str,
    response_prompt: bytes,
    source_revision: str,
    access_classification: str,
) -> dict[str, bytes]:
    rendered: dict[str, bytes] = {}
    item_rows: list[dict[str, Any]] = []
    source_rights = {
        source.id: source.rights_basis for source in blueprint.sources
    }
    for family in families:
        family_rows, perturbations = _render_family_items(
            family,
            access_classification=access_classification,
            source_rights=source_rights,
        )
        item_rows.extend(family_rows)
        rendered[f"dataset/rubrics/{family.id}.json"] = _json_bytes(
            _render_rubric(
                family,
                open_access=access_classification == "public",
            )
        )
        rendered[f"guidance/{family.id}.yaml"] = _json_bytes(
            _render_guidance(family)
        )
        for item_id, perturbation in perturbations.items():
            rendered[f"dataset/perturbations/{item_id}.json"] = _json_bytes(
                perturbation
            )
    rendered["dataset/items.jsonl"] = b"".join(
        _canonical_json(row).encode("utf-8") + b"\n" for row in item_rows
    )
    rendered[f"prompts/{prompt_name}.md"] = response_prompt
    rendered["provenance/blueprint.json"] = _json_bytes(blueprint.to_dict())
    rendered["provenance/generation-lineage.json"] = _json_bytes(
        generation_lineage.to_dict()
    )
    rendered["provenance/sources.json"] = _json_bytes(
        {"sources": [source.to_dict() for source in blueprint.sources]}
    )
    rendered["provenance/review.json"] = _json_bytes(
        {
            "assurance": WORKFLOW_ASSURANCE,
            "blueprint": {
                "review_events": [
                    event.to_dict() for event in blueprint.review_events
                ],
                "review_stage": blueprint.review_stage,
            },
            "case_families": [
                {
                    "id": family.id,
                    "review": family.review.to_dict(),
                    "workflow_revision": family.workflow_revision,
                }
                for family in families
            ],
        }
    )
    rendered["config/benchmark.yaml"] = _json_bytes(
        {
            "benchmark": {
                "id": blueprint.id,
                "name": blueprint.name,
                "prompt": prompt_name,
                "source_revision": source_revision,
                "access_classification": access_classification,
                "version": blueprint.version,
            }
        }
    )
    rendered["DATA.md"] = (
        "# Generated NOHARM-compatible data\n\n"
        f"Blueprint: `{blueprint.id}` version `{blueprint.version}`\n\n"
        f"Source revision: `{source_revision}`\n\n"
        f"Access classification: `{access_classification}`\n\n"
        f"{WORKFLOW_ASSURANCE}\n"
    ).encode("utf-8")
    rendered["README.md"] = (
        f"# {blueprint.name}\n\n"
        "This immutable bundle was rendered from an ARISEKit benchmark blueprint "
        "using the NOHARM-compatible baseline-plus-ten-perturbations shape.\n\n"
        f"{WORKFLOW_ASSURANCE}\n"
    ).encode("utf-8")
    return dict(sorted(rendered.items()))


def _render_family_items(
    family: CaseFamily,
    *,
    access_classification: str,
    source_rights: Mapping[str, str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    perturbations: dict[str, dict[str, Any]] = {}
    family_rights = {
        source_id: source_rights[source_id]
        for source_id in sorted(family.source_ids())
    }
    baseline = {
        "id": family.id,
        "prompt": family.base_case.presentation.value,
        "metadata": {
            "base_id": family.id,
            "specialty": family.base_case.specialty,
            "candidate_id": None,
            "category": "baseline",
            "perturb_id": None,
            "access_classification": access_classification,
            "source_rights": family_rights,
        },
    }
    rows.append(baseline)
    perturbations[family.id] = {
        "id": family.id,
        "base_id": family.id,
        "perturb_id": None,
        "n_perturbs": PERTURBATIONS_PER_BASE,
        "candidate_id": None,
        "specialty": family.base_case.specialty,
        "category": "baseline",
        "description": None,
        "presentation": family.base_case.presentation.value,
    }
    variants = {variant.id: variant for variant in family.variants}
    for index in range(PERTURBATIONS_PER_BASE):
        item_id = f"{family.id}-{index}"
        variant = variants[item_id]
        rows.append(
            {
                "id": item_id,
                "prompt": variant.presentation.value,
                "metadata": {
                    "base_id": family.id,
                    "specialty": family.base_case.specialty,
                    "candidate_id": index + 1,
                    "category": variant.category,
                    "perturb_id": index,
                    "access_classification": access_classification,
                    "source_rights": family_rights,
                },
            }
        )
        perturbations[item_id] = {
            "id": item_id,
            "base_id": family.id,
            "perturb_id": index,
            "n_perturbs": PERTURBATIONS_PER_BASE,
            "candidate_id": index + 1,
            "specialty": family.base_case.specialty,
            "category": variant.category,
            "description": variant.description,
            "presentation": variant.presentation.value,
        }
    return rows, perturbations


def _render_rubric(
    family: CaseFamily,
    *,
    open_access: bool,
) -> dict[str, Any]:
    groups_by_id = {group.id: group for group in family.rubric_groups}
    groups_by_name = {group.name: group for group in family.rubric_groups}
    options: list[dict[str, Any]] = []
    for option in sorted(family.rubric_options, key=lambda item: int(item.id)):
        payload: dict[str, Any] = {
            "id": int(option.id),
            "text": option.action.value,
            "category": option.category,
            "score": option.score,
            "bestInGroup": option.best_in_group,
            "isHarmOfInaction": option.harm_of_inaction,
        }
        if option.depends_on:
            payload["dependsOn"] = [int(item) for item in option.depends_on]
        if option.abstraction is not None:
            abstraction = option.abstraction
            if option.abstraction_type == "alternative":
                group = groups_by_id.get(abstraction) or groups_by_name.get(abstraction)
                assert group is not None
                abstraction = group.name
            payload["abstraction"] = abstraction
            payload["abstractionType"] = option.abstraction_type
        options.append(payload)
    consults = []
    for rule in sorted(
        family.specialist_consults,
        key=lambda item: int(item.option_id),
    ):
        consult: dict[str, Any] = {
            "type": rule.consult_type,
            "urgency": rule.urgency,
            "harm": {
                "type": rule.harm_type,
                "severity": rule.harm_severity,
            },
            "optionId": int(rule.option_id),
        }
        if rule.specialty is not None:
            consult["specialty"] = rule.specialty
        consults.append(consult)
    return {
        "id": family.id,
        "open": open_access,
        "case": {
            "presentation": family.base_case.presentation.value,
            "recommendations": family.base_case.reference_recommendations.value,
        },
        "options": options,
        "abstractionGroups": [
            {
                "name": group.name,
                "pickCount": group.pick_count,
                "pickType": group.pick_rule,
            }
            for group in sorted(family.rubric_groups, key=lambda item: item.id)
        ],
        "specialistConsult": {"consults": consults},
    }


def _render_guidance(family: CaseFamily) -> dict[str, Any]:
    guidance = family.guidance
    assert guidance is not None
    return {
        "case_id": family.id,
        "version": guidance.version,
        "clinical_revision": family.clinical_revision,
        "spirit": guidance.spirit.value,
        "watchouts": [item.value for item in guidance.watchouts],
        "options": {
            rule.option_id: _render_option_guidance(rule)
            for rule in sorted(
                guidance.option_rules,
                key=lambda item: int(item.option_id),
            )
        },
    }


def _render_option_guidance(rule: OptionGuidance) -> dict[str, Any]:
    rendered = {
        "matching": rule.matching.value,
        "disqualifiers": [item.value for item in rule.disqualifiers],
    }
    if rule.aliases:
        rendered["aliases"] = [item.value for item in rule.aliases]
    if rule.gates:
        rendered["gates"] = [item.value for item in rule.gates]
    return rendered


def _validate_judge_contract_assets(
    blueprint: BenchmarkBlueprint,
    judge_assets: Mapping[str, bytes],
    *,
    error_type: type[ValueError],
) -> dict[str, str]:
    contract = blueprint.judge_contract
    if not contract.prompt_hashes:
        raise error_type("judge contract requires at least one pinned prompt")
    if not contract.schema_hashes:
        raise error_type("judge contract requires at least one pinned schema")
    resolved: dict[str, str] = {}
    for kind, named_hashes, directory in (
        ("prompt", contract.prompt_hashes, "prompts"),
        ("schema", contract.schema_hashes, "schemas"),
    ):
        for named in named_hashes:
            path = _resolve_contract_asset(
                named.name,
                judge_assets,
                directory=directory,
                error_type=error_type,
            )
            actual = _sha256(judge_assets[path])
            if not hmac.compare_digest(actual, named.digest):
                raise error_type(
                    f"judge {kind} hash mismatch for {named.name!r}"
                )
            resolved[named.name] = path
            if kind == "prompt":
                try:
                    text = judge_assets[path].decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise error_type(
                        f"judge prompt {path!r} must be valid UTF-8"
                    ) from exc
                if not text.strip():
                    raise error_type(f"judge prompt {path!r} must not be empty")
            else:
                try:
                    schema = json.loads(judge_assets[path].decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise error_type(
                        f"judge schema {path!r} must be a JSON object"
                    ) from exc
                if not isinstance(schema, dict):
                    raise error_type(
                        f"judge schema {path!r} must be a JSON object"
                    )
    return resolved


def _resolve_contract_asset(
    name: str,
    judge_assets: Mapping[str, bytes],
    *,
    directory: str,
    error_type: type[ValueError],
) -> str:
    supplied = name[6:] if name.startswith("judge/") else name
    try:
        canonical = _safe_relative_path(supplied, label="judge contract asset")
    except NoHarmExportError as exc:
        raise error_type(str(exc)) from exc
    candidates: list[str] = []
    if canonical in judge_assets and canonical.startswith(f"{directory}/"):
        candidates.append(canonical)
    if "/" not in canonical:
        prefixed = f"{directory}/{canonical}"
        if prefixed in judge_assets:
            candidates.append(prefixed)
    if not candidates:
        candidates = [
            path
            for path in judge_assets
            if path.startswith(f"{directory}/")
            and PurePosixPath(path).name == PurePosixPath(canonical).name
        ]
    if not candidates and "/" not in canonical:
        candidates = [
            path
            for path in judge_assets
            if path.startswith(f"{directory}/")
            and _logical_asset_name(PurePosixPath(path).name, directory)
            == canonical
        ]
    candidates = sorted(set(candidates))
    if len(candidates) != 1:
        detail = "missing" if not candidates else "ambiguous"
        raise error_type(
            f"judge contract asset {name!r} is {detail} under {directory}/"
        )
    return candidates[0]


def _logical_asset_name(filename: str, directory: str) -> str:
    if directory == "prompts" and filename.endswith(".md"):
        return filename[: -len(".md")]
    if directory == "schemas" and filename.endswith(".schema.json"):
        return filename[: -len(".schema.json")]
    return filename


def _verify_judge_pins(
    root: Path,
    blueprint: BenchmarkBlueprint,
    *,
    source_revision: str,
    prompt_name: str,
    prompt_sha256: str,
) -> tuple[str, ...]:
    pins = _read_json(
        root / "judge" / "pins.json",
        error_type=NoHarmCompatibleBundleError,
    )
    judge_assets = pins.get("assets")
    if not isinstance(judge_assets, dict) or not judge_assets:
        raise NoHarmCompatibleBundleError("judge pins contain no assets")
    if list(judge_assets) != sorted(judge_assets):
        raise NoHarmCompatibleBundleError("judge pin paths must be sorted")
    payloads: dict[str, bytes] = {}
    for relative, digest in judge_assets.items():
        try:
            canonical = _safe_relative_path(relative, label="judge pin")
        except NoHarmExportError as exc:
            raise NoHarmCompatibleBundleError(str(exc)) from exc
        if canonical == "pins.json":
            raise NoHarmCompatibleBundleError("judge pins cannot pin themselves")
        _require_hash(digest, f"judge pin {canonical}", error_type=NoHarmCompatibleBundleError)
        payload = _required_bytes(
            root / "judge" / canonical,
            error_type=NoHarmCompatibleBundleError,
        )
        if not hmac.compare_digest(_sha256(payload), digest):
            raise NoHarmCompatibleBundleError(
                f"judge asset hash does not match pin: {canonical}"
            )
        payloads[canonical] = payload
    expected = {
        "schema_version": PINS_SCHEMA_VERSION,
        "source_revision": source_revision,
        "response_prompt": {
            "name": prompt_name,
            "sha256": prompt_sha256,
        },
        "judge_contract": {
            "digest": blueprint.judge_contract.digest,
            "id": blueprint.judge_contract.id,
            "version": blueprint.judge_contract.version,
        },
        "assets": {
            relative: _sha256(payload)
            for relative, payload in payloads.items()
        },
    }
    if blueprint.judge_contract.runtime_dependency_lock_sha256 is not None:
        expected["judge_contract"]["runtime_dependency_lock_sha256"] = (
            blueprint.judge_contract.runtime_dependency_lock_sha256
        )
    if pins != expected:
        raise NoHarmCompatibleBundleError(
            "judge pins do not match the pinned blueprint contract"
        )
    _validate_judge_contract_assets(
        blueprint,
        payloads,
        error_type=NoHarmCompatibleBundleError,
    )
    return tuple(payloads)


def _verify_manifest_inventory(root: Path, manifest: Mapping[str, Any]) -> None:
    records = manifest.get("assets")
    if not isinstance(records, list):
        raise NoHarmCompatibleBundleError("bundle manifest assets must be a list")
    paths: list[str] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != {"path", "sha256", "size"}:
            raise NoHarmCompatibleBundleError(
                f"bundle manifest asset {index} is invalid"
            )
        try:
            path = _safe_relative_path(record["path"], label="manifest asset")
        except NoHarmExportError as exc:
            raise NoHarmCompatibleBundleError(str(exc)) from exc
        if path == "bundle-manifest.json":
            raise NoHarmCompatibleBundleError("bundle manifest cannot inventory itself")
        _require_hash(
            record["sha256"],
            f"manifest asset {path}",
            error_type=NoHarmCompatibleBundleError,
        )
        size = record["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise NoHarmCompatibleBundleError(
                f"manifest asset {path} has invalid size"
            )
        payload = _required_bytes(
            root / path,
            error_type=NoHarmCompatibleBundleError,
        )
        if len(payload) != size or not hmac.compare_digest(
            _sha256(payload), record["sha256"]
        ):
            raise NoHarmCompatibleBundleError(
                f"manifest asset bytes do not match inventory: {path}"
            )
        paths.append(path)
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise NoHarmCompatibleBundleError(
            "bundle manifest asset paths must be unique and sorted"
        )
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.relative_to(root).as_posix() != "bundle-manifest.json"
    }
    if actual != set(paths):
        raise NoHarmCompatibleBundleError(
            "bundle files do not correspond exactly to manifest inventory"
        )
    expected_directories = {
        parent.as_posix()
        for relative in paths
        for parent in PurePosixPath(relative).parents
        if parent.as_posix() != "."
    }
    actual_directories = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_dir()
    }
    if actual_directories != expected_directories:
        raise NoHarmCompatibleBundleError(
            "bundle directories do not match the canonical asset shape"
        )


def _build_inventory(root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        relative = path.relative_to(root).as_posix()
        if relative == "bundle-manifest.json":
            continue
        payload = path.read_bytes()
        records.append(
            {"path": relative, "sha256": _sha256(payload), "size": len(payload)}
        )
    return records


def _topology(base_ids: tuple[str, ...]) -> dict[str, Any]:
    return {
        "base_cases": len(base_ids),
        "base_ids": list(base_ids),
        "perturbations_per_base": PERTURBATIONS_PER_BASE,
        "rows": len(base_ids) * VARIANTS_PER_BASE,
        "variants_per_base_including_baseline": VARIANTS_PER_BASE,
    }


def _access_record(
    blueprint: BenchmarkBlueprint,
    classification: str,
) -> dict[str, Any]:
    return {
        "classification": classification,
        "sources": [
            {
                "id": source.id,
                "license_or_terms": source.license_or_terms,
                "rights_basis": source.rights_basis,
                "rights_note": source.rights_note,
                "release_scope": source.release_scope,
                "release_authorization_hash": source.release_authorization_hash,
                "release_authorized_by": source.release_authorized_by,
                "release_authorized_at": source.release_authorized_at,
            }
            for source in sorted(blueprint.sources, key=lambda item: item.id)
        ],
    }


def _selection_for(base_ids: tuple[str, ...], k: int) -> NoHarmSelection:
    item_ids = tuple(
        item_id
        for base_id in base_ids
        for item_id in (
            base_id,
            *(f"{base_id}-{index}" for index in range(k - 1)),
        )
    )
    return NoHarmSelection(k=k, base_ids=base_ids, item_ids=item_ids)


def _select_base_ids(
    canonical_base_ids: tuple[str, ...],
    *,
    base_ids: Iterable[str] | None,
    base_limit: int | None,
) -> tuple[str, ...]:
    if base_ids is not None and base_limit is not None:
        raise ValueError("base_ids and base_limit are mutually exclusive")
    if base_limit is not None:
        if (
            isinstance(base_limit, bool)
            or not isinstance(base_limit, int)
            or not 1 <= base_limit <= len(canonical_base_ids)
        ):
            raise ValueError(
                f"base_limit must be an integer from 1 to {len(canonical_base_ids)}"
            )
        return canonical_base_ids[:base_limit]
    if base_ids is None:
        return canonical_base_ids
    if isinstance(base_ids, (str, bytes)):
        raise ValueError("base_ids must be an iterable of base case ids")
    requested = tuple(base_ids)
    if not requested:
        raise ValueError("base_ids must contain at least one base case id")
    if any(not isinstance(item, str) or not item for item in requested):
        raise ValueError("base_ids must contain non-empty strings")
    if len(requested) != len(set(requested)):
        raise ValueError("base_ids must not contain duplicates")
    unknown = sorted(set(requested) - set(canonical_base_ids))
    if unknown:
        raise ValueError(f"unknown NOHARM base ids: {', '.join(unknown)}")
    selected = set(requested)
    return tuple(item for item in canonical_base_ids if item in selected)


def _safe_relative_path(path: Any, *, label: str) -> str:
    if not isinstance(path, str) or not path or "\\" in path:
        raise NoHarmExportError(f"{label} path must be a non-empty POSIX path")
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise NoHarmExportError(f"{label} path is unsafe: {path!r}")
    canonical = pure.as_posix()
    if canonical != path:
        raise NoHarmExportError(f"{label} path is not canonical: {path!r}")
    return canonical


def _asset_bytes(value: Any, label: str) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, bytes):
        return value
    raise NoHarmExportError(f"{label} must be str or bytes")


def _write_bytes(root: Path, relative: str, payload: bytes) -> None:
    canonical = _safe_relative_path(relative, label="output asset")
    path = root / canonical
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _read_json(
    path: Path,
    *,
    error_type: type[ValueError],
) -> dict[str, Any]:
    payload = _required_bytes(path, error_type=error_type)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise error_type(f"{path} must contain valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise error_type(f"{path} must contain a JSON object")
    return value


def _read_jsonl(
    path: Path,
    *,
    error_type: type[ValueError],
) -> list[dict[str, Any]]:
    payload = _required_bytes(path, error_type=error_type)
    rows: list[dict[str, Any]] = []
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise error_type(f"{path} must be valid UTF-8") from exc
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise error_type(f"{path}:{line_number} is invalid JSON") from exc
        if not isinstance(row, dict):
            raise error_type(f"{path}:{line_number} must contain an object")
        rows.append(row)
    return rows


def _required_bytes(path: Path, *, error_type: type[ValueError]) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise error_type(f"required generated bundle asset is missing: {path}")
    return path.read_bytes()


def _reject_symlinks(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise NoHarmCompatibleBundleError(
                f"generated bundle must not contain symlinks: {path}"
            )


def _require_hash(
    value: Any,
    label: str,
    *,
    error_type: type[ValueError] = NoHarmExportError,
) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise error_type(f"{label} must be a lowercase SHA-256 digest")


def _require_text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise NoHarmExportError(f"{label} must be a non-empty string")


def _require_timestamp(value: Any, label: str) -> None:
    _require_text(value, label)
    if _RFC3339_RE.fullmatch(value) is None:
        raise NoHarmExportError(
            f"{label} must be an RFC 3339 timestamp with a timezone"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NoHarmExportError(
            f"{label} must be a valid RFC 3339 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NoHarmExportError(f"{label} must include a timezone")


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise NoHarmExportError(f"value is not canonical JSON: {exc}") from exc


def _json_bytes(value: Any) -> bytes:
    return (_canonical_json(value) + "\n").encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256(_canonical_json(value).encode("utf-8"))


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "GENERATION_LINEAGE_SCHEMA_VERSION",
    "GenerationLineage",
    "NoHarmCompatibleBundle",
    "NoHarmCompatibleBundleError",
    "NoHarmExportError",
    "PinnedNoHarmAssets",
    "export_noharm_bundle",
]
