"""Load and fingerprint the canonical public NOHARM bundle without modifying it.

This adapter deliberately models the released NOHARM contract instead of
pretending that its staged action-matching judge is a generic rubric panel.
The public release remains the authority for judge execution; this module
provides structural validation, deterministic item selection, provenance
hashes, and offline aggregate replay for compatibility checks.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import importlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ForwardRef, Iterable, Mapping, Sequence

if TYPE_CHECKING:
    from arisekit.authoring.content_inventory import ReferenceSelectionInventory
    from arisekit.dataset import Dataset
    from arisekit.types import BenchmarkItem
else:
    BenchmarkItem = ForwardRef("_resolve_annotation_type('arisekit.types', 'BenchmarkItem')")
    Dataset = ForwardRef("_resolve_annotation_type('arisekit.dataset', 'Dataset')")
    ReferenceSelectionInventory = ForwardRef(
        "_resolve_annotation_type("
        "'arisekit.authoring.content_inventory', 'ReferenceSelectionInventory')"
    )


def _resolve_annotation_type(module_name: str, type_name: str) -> Any:
    return getattr(importlib.import_module(module_name), type_name)


PUBLIC_BASE_CASES = 30
VARIANTS_PER_BASE = 11
PERTURBATIONS_PER_BASE = 10
PUBLIC_ROWS = PUBLIC_BASE_CASES * VARIANTS_PER_BASE
DEFAULT_K = 5

JUDGE_VERSION = "v2"
DEFAULT_MATCH_JUDGE = "gemini/gemini-3-flash-preview"
DEFAULT_REVIEW_JUDGE = "gemini/gemini-3.5-flash"

_BASE_ID_RE = re.compile(r"^[A-Za-z]+\d{3}$")
_REQUIRED_JUDGE_PROMPTS = (
    "extract_match.md",
    "global_match_review.md",
    "severity.md",
    "triage.md",
)
_REQUIRED_JUDGE_SCHEMAS = (
    "judged.schema.json",
    "match.schema.json",
    "review.schema.json",
    "severity.schema.json",
    "strategies.schema.json",
    "triage.schema.json",
)
_CANONICAL_METRIC_ORDER = (
    "F1_raw",
    "F1_binary",
    "F1_weighted",
    "Precision_raw",
    "Precision_binary",
    "Precision_weighted",
    "Recall_raw",
    "Recall_binary",
    "Recall_weighted",
    "Accuracy",
    "Accuracy_binary",
    "Severe_rate",
    "Moderate_rate",
    "Mild_rate",
    "Triage",
)
_RUNTIME_DEPENDENCY_FILENAMES = {
    "Pipfile.lock",
    "poetry.lock",
    "pyproject.toml",
    "uv.lock",
}


class NoHarmBundleError(ValueError):
    """The supplied directory is not the canonical 30-case public bundle."""


@dataclass(frozen=True)
class NoHarmAssetHashes:
    """Hashes needed to freeze a public data and judge snapshot."""

    content_sha256: str
    data_sha256: str
    judge_sha256: str
    runtime_dependency_lock_sha256: str
    bundle_sha256: str
    assets: Mapping[str, str]


@dataclass(frozen=True)
class NoHarmSelection:
    """Deterministic identity of one baseline-plus-perturbations slice."""

    k: int
    base_ids: tuple[str, ...]
    item_ids: tuple[str, ...]
    policy: str = "baseline-plus-first-perturbations"

    def to_dict(self) -> dict[str, Any]:
        return {
            "k": self.k,
            "policy": self.policy,
            "base_ids": list(self.base_ids),
            "item_ids": list(self.item_ids),
        }


@dataclass(frozen=True)
class AggregateMetric:
    """One row in the canonical NOHARM aggregate score shape."""

    category: str
    metric: str
    trials: int
    mean: float
    ci: float | None = None
    ci_lo: float | None = None
    ci_hi: float | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.category, self.metric)


@dataclass(frozen=True)
class MetricDelta:
    """A point-estimate difference between replayed and cached metrics."""

    category: str
    metric: str
    observed: float
    reference: float
    observed_trials: int
    reference_trials: int
    delta: float
    within_tolerance: bool


@dataclass(frozen=True)
class AggregateComparison:
    """Complete comparison, including metrics missing from either side."""

    deltas: tuple[MetricDelta, ...]
    missing_observed: tuple[tuple[str, str], ...]
    missing_reference: tuple[tuple[str, str], ...]

    @property
    def matches(self) -> bool:
        return (
            not self.missing_observed
            and not self.missing_reference
            and all(delta.within_tolerance for delta in self.deltas)
        )


class NoHarmReferenceBundle:
    """Validated, read-only view of the released 30-case NOHARM subset."""

    def __init__(self, root: str | Path, *, prompt_name: str = "default"):
        self.root = Path(root).expanduser().resolve()
        self.prompt_name = prompt_name
        self._raw_items: tuple[dict[str, Any], ...] = ()
        self._by_id: dict[str, dict[str, Any]] = {}
        self._base_ids: tuple[str, ...] = ()
        self._prompt_template = ""
        self._rubrics: dict[str, dict[str, Any]] = {}
        self._perturbations: dict[str, dict[str, Any]] = {}
        self._hashes: NoHarmAssetHashes | None = None
        self._load_and_validate()

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
        """All 330 rows in canonical file order, with the released full prompt."""
        return tuple(self._to_benchmark_item(row) for row in self._raw_items)

    @property
    def base_cases(self) -> tuple[BenchmarkItem, ...]:
        return tuple(
            self._to_benchmark_item(self._by_id[base]) for base in self._base_ids
        )

    def selection(
        self,
        k: int = DEFAULT_K,
        *,
        base_ids: Iterable[str] | None = None,
        base_limit: int | None = None,
    ) -> NoHarmSelection:
        """Describe an exact, reproducible subset in canonical bundle order."""
        if (
            isinstance(k, bool)
            or not isinstance(k, int)
            or not 1 <= k <= VARIANTS_PER_BASE
        ):
            raise ValueError(f"k must be an integer from 1 to {VARIANTS_PER_BASE}")
        selected_bases = _select_base_ids(
            self._base_ids,
            base_ids=base_ids,
            base_limit=base_limit,
        )
        item_ids: list[str] = []
        for base_id in selected_bases:
            item_ids.append(base_id)
            for perturb_id in range(k - 1):
                item_ids.append(f"{base_id}-{perturb_id}")
        return NoHarmSelection(
            k=k,
            base_ids=selected_bases,
            item_ids=tuple(item_ids),
        )

    def select(
        self,
        k: int = DEFAULT_K,
        *,
        base_ids: Iterable[str] | None = None,
        base_limit: int | None = None,
    ) -> tuple[BenchmarkItem, ...]:
        """Apply the released runner rule, optionally to an explicit base subset."""
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
        """Return an ARISEKit Dataset that preserves the canonical prompt shape."""
        from arisekit.dataset import Dataset

        return Dataset.from_items(
            self.select(k, base_ids=base_ids, base_limit=base_limit),
            name="donoharm",
        )

    def build_reference_selection_inventory(
        self,
        selection: NoHarmSelection,
        *,
        source_manifest_sha256: str,
        source_revision: str,
        selection_protocol_sha256: str,
        selection_commit_sha256: str,
    ) -> ReferenceSelectionInventory:
        """Bind a frozen selection to the released raw presentation content.

        Item hashes are derived directly from the ``prompt`` field in the
        released ``dataset/items.jsonl`` row. The response-instruction template
        added by :meth:`select` is deliberately excluded from the canonical
        presentation hash.
        """
        from arisekit.authoring.content_inventory import (
            ContentFamilyBinding,
            ContentItemBinding,
            ReferenceSelectionInventory,
            canonical_family_content_sha256,
            canonical_item_content_sha256,
        )

        if not isinstance(selection, NoHarmSelection):
            raise ValueError("selection must be a NoHarmSelection")
        if selection.policy != "baseline-plus-first-perturbations":
            raise ValueError("NOHARM selection policy is not canonical")
        try:
            canonical_selection = self.selection(
                selection.k,
                base_ids=selection.base_ids,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("NOHARM selection is invalid") from exc
        if selection != canonical_selection:
            raise ValueError(
                "NOHARM selection must exactly match its canonical family topology"
            )

        families: list[ContentFamilyBinding] = []
        for base_id in canonical_selection.base_ids:
            family_item_ids = (base_id,) + tuple(
                f"{base_id}-{perturb_id}"
                for perturb_id in range(canonical_selection.k - 1)
            )
            items = tuple(
                ContentItemBinding(
                    item_id=item_id,
                    content_sha256=canonical_item_content_sha256(
                        str(self._by_id[item_id]["prompt"])
                    ),
                )
                for item_id in family_item_ids
            )
            families.append(
                ContentFamilyBinding(
                    family_id=base_id,
                    family_content_sha256=canonical_family_content_sha256(
                        [item.content_sha256 for item in items]
                    ),
                    baseline_item_id=base_id,
                    items=items,
                )
            )

        return ReferenceSelectionInventory(
            bundle_sha256=self.hashes.bundle_sha256,
            source_manifest_sha256=source_manifest_sha256,
            source_revision=source_revision,
            selection_protocol_sha256=selection_protocol_sha256,
            selection_commit_sha256=selection_commit_sha256,
            families=tuple(families),
        )

    def rubric_for(self, item_id: str) -> dict[str, Any]:
        """Resolve a variant to its base rubric and return a defensive copy."""
        row = self._by_id.get(str(item_id))
        if row is None:
            raise KeyError(f"unknown NOHARM item id: {item_id}")
        base_id = str(row["metadata"]["base_id"])
        return copy.deepcopy(self._rubrics[base_id])

    @property
    def hashes(self) -> NoHarmAssetHashes:
        if self._hashes is None:
            self._hashes = self._compute_hashes()
        return self._hashes

    def _to_benchmark_item(self, row: Mapping[str, Any]) -> BenchmarkItem:
        from arisekit.types import BenchmarkItem

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
            raise FileNotFoundError(f"NOHARM bundle directory not found: {self.root}")

        prompt_path = self.root / "prompts" / f"{self.prompt_name}.md"
        if prompt_path.parent.resolve() != (self.root / "prompts").resolve():
            raise NoHarmBundleError(f"invalid prompt name: {self.prompt_name!r}")
        self._prompt_template = _required_text(prompt_path).strip()

        self._raw_items = tuple(_read_jsonl(self.root / "dataset" / "items.jsonl"))
        if len(self._raw_items) != PUBLIC_ROWS:
            raise NoHarmBundleError(
                f"public NOHARM must contain {PUBLIC_ROWS} rows; found {len(self._raw_items)}"
            )

        self._validate_items()
        self._validate_rubrics()
        self._validate_perturbations()
        self._validate_guidance()
        self._validate_judge_assets()

    def _validate_items(self) -> None:
        by_id: dict[str, dict[str, Any]] = {}
        families: dict[str, list[str]] = defaultdict(list)
        base_ids: list[str] = []

        for index, row in enumerate(self._raw_items, start=1):
            if not isinstance(row, dict):
                raise NoHarmBundleError(f"items.jsonl row {index} must be an object")
            item_id = row.get("id")
            prompt = row.get("prompt")
            metadata = row.get("metadata")
            if not isinstance(item_id, str) or not item_id:
                raise NoHarmBundleError(f"items.jsonl row {index} has no string id")
            if item_id in by_id:
                raise NoHarmBundleError(f"duplicate NOHARM item id: {item_id}")
            if not isinstance(prompt, str) or not prompt.strip():
                raise NoHarmBundleError(f"NOHARM item {item_id} has an empty prompt")
            if not isinstance(metadata, dict):
                raise NoHarmBundleError(f"NOHARM item {item_id} has invalid metadata")
            if metadata.get("open") is not True:
                raise NoHarmBundleError(
                    f"NOHARM item {item_id} is not marked open; closed content is rejected"
                )

            base_id, perturb_id = _parse_item_id(item_id)
            if not _BASE_ID_RE.fullmatch(base_id):
                raise NoHarmBundleError(f"invalid NOHARM base id: {base_id}")
            if metadata.get("base_id") != base_id:
                raise NoHarmBundleError(f"NOHARM item {item_id} has mismatched base_id")
            if metadata.get("perturb_id") != perturb_id:
                raise NoHarmBundleError(
                    f"NOHARM item {item_id} has mismatched perturb_id"
                )
            if perturb_id is None:
                if metadata.get("category") != "baseline":
                    raise NoHarmBundleError(
                        f"base item {item_id} must have category 'baseline'"
                    )
                base_ids.append(base_id)
            elif not 0 <= perturb_id < PERTURBATIONS_PER_BASE:
                raise NoHarmBundleError(
                    f"NOHARM item {item_id} has invalid perturbation suffix"
                )

            by_id[item_id] = row
            families[base_id].append(item_id)

        if len(base_ids) != PUBLIC_BASE_CASES:
            raise NoHarmBundleError(
                f"public NOHARM must contain {PUBLIC_BASE_CASES} base cases; found {len(base_ids)}"
            )
        if len(set(base_ids)) != len(base_ids):
            raise NoHarmBundleError("NOHARM base case ids are not unique")

        expected_order: list[str] = []
        for base_id in base_ids:
            expected_family = [base_id] + [
                f"{base_id}-{index}" for index in range(PERTURBATIONS_PER_BASE)
            ]
            if families[base_id] != expected_family:
                raise NoHarmBundleError(
                    f"NOHARM family {base_id} must be baseline followed by perturbations 0-9"
                )
            expected_order.extend(expected_family)
        if list(by_id) != expected_order:
            raise NoHarmBundleError(
                "NOHARM item families must be contiguous in canonical order"
            )

        self._by_id = by_id
        self._base_ids = tuple(base_ids)

    def _validate_rubrics(self) -> None:
        rubric_dir = self.root / "dataset" / "rubrics"
        actual = {path.stem for path in rubric_dir.glob("*.json")}
        expected = set(self._base_ids)
        _require_exact_names("rubric", actual, expected)

        for base_id in self._base_ids:
            rubric = _read_json(rubric_dir / f"{base_id}.json")
            if rubric.get("id") != base_id or rubric.get("open") is not True:
                raise NoHarmBundleError(
                    f"rubric {base_id} has invalid identity or visibility"
                )
            case = rubric.get("case")
            if (
                not isinstance(case, dict)
                or case.get("presentation") != self._by_id[base_id]["prompt"]
            ):
                raise NoHarmBundleError(
                    f"rubric {base_id} does not match its base presentation"
                )
            options = rubric.get("options")
            if not isinstance(options, list) or not options:
                raise NoHarmBundleError(f"rubric {base_id} has no options")
            option_ids: set[int] = set()
            inaction_count = 0
            for option in options:
                if not isinstance(option, dict):
                    raise NoHarmBundleError(
                        f"rubric {base_id} contains a non-object option"
                    )
                option_id = option.get("id")
                score = option.get("score")
                if isinstance(option_id, bool) or not isinstance(option_id, int):
                    raise NoHarmBundleError(
                        f"rubric {base_id} has a non-integer option id"
                    )
                if option_id in option_ids:
                    raise NoHarmBundleError(
                        f"rubric {base_id} has duplicate option id {option_id}"
                    )
                if (
                    isinstance(score, bool)
                    or not isinstance(score, int)
                    or not 1 <= score <= 9
                ):
                    raise NoHarmBundleError(
                        f"rubric {base_id} option {option_id} has a score outside 1-9"
                    )
                if (
                    not isinstance(option.get("text"), str)
                    or not option["text"].strip()
                ):
                    raise NoHarmBundleError(
                        f"rubric {base_id} option {option_id} has no text"
                    )
                if (
                    not isinstance(option.get("category"), str)
                    or not option["category"].strip()
                ):
                    raise NoHarmBundleError(
                        f"rubric {base_id} option {option_id} has no category"
                    )
                option_ids.add(option_id)
                inaction_count += int(option.get("isHarmOfInaction") is True)
            if inaction_count != 1:
                raise NoHarmBundleError(
                    f"rubric {base_id} must contain exactly one harm-of-inaction option"
                )
            self._rubrics[base_id] = rubric

    def _validate_perturbations(self) -> None:
        perturbation_dir = self.root / "dataset" / "perturbations"
        actual = {path.stem for path in perturbation_dir.glob("*.json")}
        expected = set(self._by_id)
        _require_exact_names("perturbation", actual, expected)

        for item_id, row in self._by_id.items():
            perturbation = _read_json(perturbation_dir / f"{item_id}.json")
            metadata = row["metadata"]
            checks = {
                "id": item_id,
                "base_id": metadata["base_id"],
                "perturb_id": metadata["perturb_id"],
                "candidate_id": metadata.get("candidate_id"),
                "category": metadata.get("category"),
                "presentation": row["prompt"],
                "n_perturbs": PERTURBATIONS_PER_BASE,
            }
            for field, expected_value in checks.items():
                if perturbation.get(field) != expected_value:
                    raise NoHarmBundleError(
                        f"perturbation {item_id} has mismatched {field}: "
                        f"{perturbation.get(field)!r} != {expected_value!r}"
                    )
            self._perturbations[item_id] = perturbation

    def _validate_guidance(self) -> None:
        guidance_dir = self.root / "guidance"
        actual = {path.stem for path in guidance_dir.glob("*.yaml")}
        _require_exact_names("guidance", actual, set(self._base_ids))
        for base_id in self._base_ids:
            _required_text(guidance_dir / f"{base_id}.yaml")

    def _validate_judge_assets(self) -> None:
        for filename in _REQUIRED_JUDGE_PROMPTS:
            _required_text(self.root / "judge" / "prompts" / filename)
        for filename in _REQUIRED_JUDGE_SCHEMAS:
            schema = _read_json(self.root / "judge" / "schemas" / filename)
            if not isinstance(schema, dict):
                raise NoHarmBundleError(f"judge schema {filename} must be an object")

        config_text = _required_text(self.root / "judge" / "config.py")
        data_text = _required_text(self.root / "DATA.md")
        for pin in (DEFAULT_MATCH_JUDGE, DEFAULT_REVIEW_JUDGE):
            if pin not in config_text or pin not in data_text:
                raise NoHarmBundleError(f"canonical judge pin {pin!r} is missing")
        if f"JUDGE_VERSION: {JUDGE_VERSION}" not in data_text:
            raise NoHarmBundleError(
                f"canonical judge version {JUDGE_VERSION!r} is missing"
            )

    def _compute_hashes(self) -> NoHarmAssetHashes:
        asset_paths = self._asset_paths()
        assets = {
            path.relative_to(self.root).as_posix(): _sha256_bytes(path.read_bytes())
            for path in asset_paths
        }
        data_assets = {
            name: digest
            for name, digest in assets.items()
            if name.startswith(("dataset/", "guidance/", "prompts/"))
        }
        judge_assets = {
            name: digest
            for name, digest in assets.items()
            if name.startswith("judge/") or is_judge_dependency_manifest(name)
        }
        runtime_dependency_lock = dependency_lock_sha256(assets)
        logical_content = {
            "items": self._raw_items,
            "rubrics": self._rubrics,
            "perturbations": self._perturbations,
            "guidance": {
                base_id: _normalized_text(self.root / "guidance" / f"{base_id}.yaml")
                for base_id in self._base_ids
            },
            "prompt": _normalized_text(
                self.root / "prompts" / f"{self.prompt_name}.md"
            ),
        }
        return NoHarmAssetHashes(
            content_sha256=_sha256_json(logical_content),
            data_sha256=_sha256_json(data_assets),
            judge_sha256=_sha256_json(judge_assets),
            runtime_dependency_lock_sha256=runtime_dependency_lock,
            bundle_sha256=_sha256_json(assets),
            assets=MappingProxyType(assets),
        )

    def _asset_paths(self) -> tuple[Path, ...]:
        patterns = (
            "DATA.md",
            "LICENSE",
            "README.md",
            "config/benchmark.yaml",
            "data_loader.py",
            "run.py",
            "score.py",
            "dataset/items.jsonl",
            "dataset/rubrics/*.json",
            "dataset/perturbations/*.json",
            "guidance/*.yaml",
            "prompts/*.md",
            "judge/**/*.py",
            "judge/prompts/*.md",
            "judge/schemas/*.json",
            "requirements*.txt",
            "judge/pyproject.toml",
            "judge/requirements*.txt",
            "judge/uv.lock",
            "judge/poetry.lock",
            "judge/Pipfile.lock",
        )
        paths: set[Path] = set()
        for pattern in patterns:
            paths.update(path for path in self.root.glob(pattern) if path.is_file())
        return tuple(
            sorted(paths, key=lambda path: path.relative_to(self.root).as_posix())
        )


def is_judge_dependency_manifest(path: str) -> bool:
    """Return whether an asset contributes to the declared judge dependency lock."""
    if not isinstance(path, str) or not path:
        return False
    pure = PurePosixPath(path)
    name = pure.name
    if (
        len(pure.parts) == 1
        and name.startswith("requirements")
        and name.endswith(".txt")
    ):
        return True
    if pure.parts[:1] != ("judge",):
        return False
    return name in _RUNTIME_DEPENDENCY_FILENAMES or (
        name.startswith("requirements") and name.endswith(".txt")
    )


def dependency_lock_sha256(assets: Mapping[str, str]) -> str:
    """Hash the exact public dependency-manifest inventory, without copying bytes."""
    if not isinstance(assets, MappingABC):
        raise ValueError("dependency lock assets must be a mapping")
    selected: dict[str, str] = {}
    for name, digest in assets.items():
        if not isinstance(name, str) or not isinstance(digest, str):
            raise ValueError("dependency lock assets must map string paths to digests")
        if is_judge_dependency_manifest(name):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(
                    f"dependency manifest {name!r} must have a lowercase SHA-256 digest"
                )
            selected[name] = digest
    return _sha256_json(dict(sorted(selected.items())))


def load_aggregate_csv(path: str | Path) -> tuple[AggregateMetric, ...]:
    """Load a cached canonical score CSV without importing the judge runtime."""
    source = Path(path)
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"category", "metric", "trials", "mean"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(f"{source} is not a canonical NOHARM aggregate CSV")
        rows: list[AggregateMetric] = []
        for line_number, row in enumerate(reader, start=2):
            try:
                rows.append(
                    AggregateMetric(
                        category=str(row["category"]),
                        metric=str(row["metric"]),
                        trials=int(row["trials"]),
                        mean=float(row["mean"]),
                        ci=_optional_float(row.get("ci")),
                        ci_lo=_optional_float(row.get("ci_lo")),
                        ci_hi=_optional_float(row.get("ci_hi")),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{source}:{line_number} has invalid aggregate values"
                ) from exc
    return tuple(rows)


def replay_judged_aggregates(
    path: str | Path,
    *,
    judge_names: Iterable[str] | None = None,
    metrics_key: str = "metrics",
) -> tuple[AggregateMetric, ...]:
    """Replay canonical point estimates from cached judged JSONL.

    Values first collapse variants and configured judges within a base case,
    then average equally across base cases. Confidence intervals remain the
    authority of the released NumPy bootstrap and are intentionally omitted.
    """
    allowed_judges = set(judge_names) if judge_names is not None else None
    case_values: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for line_number, record in enumerate(_read_jsonl(Path(path)), start=1):
        if not isinstance(record, dict):
            raise ValueError(f"{path}:{line_number} judged record must be an object")
        if allowed_judges is not None and record.get("judge") not in allowed_judges:
            continue
        item_id = record.get("id")
        metrics = record.get(metrics_key)
        if not isinstance(item_id, str) or not isinstance(metrics, dict):
            continue
        base_id, _ = _parse_item_id(item_id)
        for metric, value in metrics.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            numeric = float(value)
            if math.isfinite(numeric):
                case_values[base_id][str(metric)].append(numeric)

    if not case_values:
        raise ValueError(f"no judged NOHARM metrics found in {path}")

    metric_names = set().union(
        *(set(metrics_by_case) for metrics_by_case in case_values.values())
    )
    order = {name: index for index, name in enumerate(_CANONICAL_METRIC_ORDER)}
    sorted_names = sorted(
        metric_names, key=lambda name: (order.get(name, len(order)), name)
    )
    rows: list[AggregateMetric] = []
    for metric in sorted_names:
        per_case = [
            sum(values) / len(values)
            for metrics_by_case in case_values.values()
            if (values := metrics_by_case.get(metric))
        ]
        if per_case:
            rows.append(
                AggregateMetric(
                    category="Overall",
                    metric=metric,
                    trials=len(per_case),
                    mean=round(sum(per_case) / len(per_case), 4),
                )
            )
    return tuple(rows)


def compare_aggregate_metrics(
    observed: Sequence[AggregateMetric],
    reference: Sequence[AggregateMetric],
    *,
    absolute_tolerance: float = 5e-5,
) -> AggregateComparison:
    """Compare aggregate point estimates and report missing metric rows."""
    if absolute_tolerance < 0:
        raise ValueError("absolute_tolerance must be non-negative")
    observed_by_key = _unique_metrics(observed, "observed")
    reference_by_key = _unique_metrics(reference, "reference")
    observed_keys = set(observed_by_key)
    reference_keys = set(reference_by_key)

    deltas: list[MetricDelta] = []
    for key in sorted(observed_keys & reference_keys):
        left = observed_by_key[key].mean
        right = reference_by_key[key].mean
        delta = left - right
        deltas.append(
            MetricDelta(
                category=key[0],
                metric=key[1],
                observed=left,
                reference=right,
                observed_trials=observed_by_key[key].trials,
                reference_trials=reference_by_key[key].trials,
                delta=delta,
                within_tolerance=(
                    observed_by_key[key].trials == reference_by_key[key].trials
                    and abs(delta) <= absolute_tolerance
                ),
            )
        )
    return AggregateComparison(
        deltas=tuple(deltas),
        missing_observed=tuple(sorted(reference_keys - observed_keys)),
        missing_reference=tuple(sorted(observed_keys - reference_keys)),
    )


def _parse_item_id(item_id: str) -> tuple[str, int | None]:
    if "-" not in item_id:
        return item_id, None
    base_id, suffix = item_id.rsplit("-", 1)
    if not suffix.isdigit():
        raise NoHarmBundleError(f"invalid NOHARM item id: {item_id}")
    return base_id, int(suffix)


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
    if any(not isinstance(base_id, str) or not base_id for base_id in requested):
        raise ValueError("base_ids must contain non-empty strings")
    if len(requested) != len(set(requested)):
        raise ValueError("base_ids must not contain duplicates")
    unknown = sorted(set(requested) - set(canonical_base_ids))
    if unknown:
        raise ValueError(f"unknown NOHARM base ids: {', '.join(unknown)}")
    requested_set = set(requested)
    return tuple(base_id for base_id in canonical_base_ids if base_id in requested_set)


def _read_jsonl(path: Path) -> list[Any]:
    if not path.is_file():
        raise FileNotFoundError(f"required NOHARM asset not found: {path}")
    records: list[Any] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                raise NoHarmBundleError(
                    f"{path}:{line_number} is not valid JSON"
                ) from exc
    return records


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"required NOHARM asset not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NoHarmBundleError(f"{path} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise NoHarmBundleError(f"{path} must contain a JSON object")
    return payload


def _required_text(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"required NOHARM asset not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise NoHarmBundleError(f"required NOHARM asset is empty: {path}")
    return text


def _require_exact_names(kind: str, actual: set[str], expected: set[str]) -> None:
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing {missing[:5]}")
        if extra:
            details.append(f"unexpected {extra[:5]}")
        raise NoHarmBundleError(
            f"{kind} assets do not match public cases: {'; '.join(details)}"
        )


def _normalized_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _unique_metrics(
    rows: Sequence[AggregateMetric], label: str
) -> dict[tuple[str, str], AggregateMetric]:
    indexed: dict[tuple[str, str], AggregateMetric] = {}
    for row in rows:
        if row.key in indexed:
            raise ValueError(f"duplicate {label} aggregate metric: {row.key}")
        indexed[row.key] = row
    return indexed


__all__ = [
    "AggregateComparison",
    "AggregateMetric",
    "DEFAULT_K",
    "DEFAULT_MATCH_JUDGE",
    "DEFAULT_REVIEW_JUDGE",
    "JUDGE_VERSION",
    "MetricDelta",
    "NoHarmAssetHashes",
    "NoHarmBundleError",
    "NoHarmReferenceBundle",
    "NoHarmSelection",
    "PUBLIC_BASE_CASES",
    "PUBLIC_ROWS",
    "VARIANTS_PER_BASE",
    "compare_aggregate_metrics",
    "load_aggregate_csv",
    "replay_judged_aggregates",
]
