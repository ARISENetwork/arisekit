"""Deterministic scoring revisions over retained solver checkpoints.

This module never resolves or invokes a system under test. It binds an exact
raw checkpoint to the benchmark items that supplied its prompts and ground
truth, then runs an explicitly replay-safe scorer over detached copies.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from arisekit.common.files import atomic_directory
from arisekit.common.hashing import canonical_sha256 as _sha256_json
from arisekit.common.jsonio import canonical_json as _canonical_json, strict_json_loads
from arisekit.run_manifest import RunManifest, sha256_digest
from arisekit.scorer import BaseScorer, ScorerIdentity, identify_scorer
from arisekit.analysis.stats import ScoreDiff, aggregate, diff as diff_scores, top_changes
from arisekit.types import BenchmarkItem, Metric, RunResult


CAPTURED_RESPONSES_SCHEMA_VERSION = "arisekit.captured-responses.v1"
ITEM_SCORE_SCHEMA_VERSION = "arisekit.item-score.v1"
SCORING_REVISION_SCHEMA_VERSION = "arisekit.scoring-revision.v1"
SCORE_DIFF_SCHEMA_VERSION = "arisekit.score-diff.v1"


class RescoreError(ValueError):
    """A retained checkpoint cannot be safely or deterministically scored."""


@dataclass(frozen=True)
class CapturedResponses:
    """Strict, benchmark-bound view of one append-only raw checkpoint."""

    benchmark: str
    model: str
    checkpoint_path: Path
    checkpoint_sha256: str
    checkpoint_size: int
    run_manifest_path: Path
    run_manifest_sha256: str | None
    run_manifest_size: int | None
    dataset_sha256: str
    prompt_sha256: str
    selected_item_ids: tuple[str, ...]
    expected_trials: int
    items: tuple[BenchmarkItem, ...]
    responses: tuple[RunResult, ...]
    missing_item_ids: tuple[str, ...]
    missing_trials: tuple[tuple[str, int], ...]
    run_manifest: RunManifest | None
    system_prompt: str | None
    schema_version: str = CAPTURED_RESPONSES_SCHEMA_VERSION

    @property
    def run_manifest_digest(self) -> str | None:
        return self.run_manifest.digest if self.run_manifest is not None else None


@dataclass(frozen=True)
class ScoringRevision:
    """One immutable scorer result over exact retained response bytes."""

    benchmark: str
    model: str
    checkpoint_sha256: str
    dataset_sha256: str
    prompt_sha256: str
    run_manifest_digest: str | None
    run_manifest_sha256: str | None
    scorer_identity: ScorerIdentity
    bootstrap: int
    seed: int
    expected_trials: int
    selected_item_ids: tuple[str, ...]
    captured_item_ids: tuple[str, ...]
    missing_item_ids: tuple[str, ...]
    missing_trials: tuple[tuple[str, int], ...]
    per_item: tuple[tuple[str, tuple[Metric, ...]], ...]
    metrics: tuple[Metric, ...]
    revision_digest: str
    diff: ScoreDiff | None = None
    root: Path | None = None
    receipt_path: Path | None = None
    item_scores_path: Path | None = None
    scores_path: Path | None = None
    diff_path: Path | None = None
    report_path: Path | None = None
    schema_version: str = SCORING_REVISION_SCHEMA_VERSION


def load_responses(
    checkpoint: str | Path,
    *,
    benchmark: Any,
    model: str | None = None,
    expected_trials: int | None = None,
) -> CapturedResponses:
    """Load one exact checkpoint and bind it to a benchmark dataset.

    Duplicate ``(item_id, trial)`` rows retain the append-only runner's
    latest-row-wins retry semantics. Malformed rows are rejected rather than
    skipped because this loader produces scoring evidence, not best-effort
    resume state.
    """

    supplied_path = Path(checkpoint).expanduser()
    if supplied_path.is_symlink():
        raise RescoreError("response checkpoint must not be a symlink")
    path = supplied_path.resolve()
    if path.name.endswith(".turns.jsonl"):
        raise RescoreError("turn journals cannot be used as final response checkpoints")
    _regular_file(path, "response checkpoint")
    raw_bytes = path.read_bytes()
    if not raw_bytes:
        raise RescoreError("response checkpoint is empty")
    if not raw_bytes.endswith(b"\n"):
        raise RescoreError("response checkpoint must be newline-terminated")
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RescoreError("response checkpoint must be UTF-8") from exc

    benchmark_name, items, system_prompt, configured_trials = _benchmark_snapshot(
        benchmark
    )
    item_by_id = {item.id: item for item in items}
    dataset_sha256 = sha256_digest([item.to_dict() for item in items])
    prompt_sha256 = sha256_digest(system_prompt or "")

    manifest_path = path.parent / "run-manifest.json"
    manifest: RunManifest | None = None
    manifest_sha256: str | None = None
    manifest_size: int | None = None
    if _entry_exists(manifest_path):
        _regular_file(manifest_path, "run manifest")
        try:
            manifest_bytes = manifest_path.read_bytes()
            manifest_payload = _load_json(manifest_bytes.decode("utf-8"))
            manifest = RunManifest.from_dict(manifest_payload)
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            raise RescoreError(f"invalid run manifest sidecar: {exc}") from exc
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        manifest_size = len(manifest_bytes)
        if manifest.benchmark_arm != benchmark_name:
            raise RescoreError(
                "run manifest benchmark does not match the selected benchmark"
            )
        if manifest.benchmark_content_hash != dataset_sha256:
            raise RescoreError(
                "run manifest dataset hash does not match the selected benchmark"
            )
        if manifest.prompt_hash != prompt_sha256:
            raise RescoreError(
                "run manifest prompt hash does not match the selected benchmark"
            )
        raw_selection = manifest.selection.get("item_ids")
        if (
            isinstance(raw_selection, (str, bytes))
            or not isinstance(raw_selection, Sequence)
            or not raw_selection
            or any(not isinstance(value, str) or not value for value in raw_selection)
        ):
            raise RescoreError(
                "run manifest selection must contain non-empty item_ids"
            )
        selected_ids = tuple(raw_selection)
        if len(set(selected_ids)) != len(selected_ids):
            raise RescoreError("run manifest selection contains duplicate item ids")
        unknown_selection = sorted(set(selected_ids) - set(item_by_id))
        if unknown_selection:
            raise RescoreError(
                "run manifest selection contains unknown item ids: "
                + ", ".join(unknown_selection)
            )
        raw_limit = manifest.selection.get("limit")
        if raw_limit is not None and (
            isinstance(raw_limit, bool)
            or not isinstance(raw_limit, int)
            or raw_limit < 1
        ):
            raise RescoreError("run manifest selection limit is invalid")
        expected_selection = tuple(
            item.id
            for item in (
                items[:raw_limit] if raw_limit is not None else items
            )
        )
        if selected_ids != expected_selection:
            raise RescoreError(
                "run manifest selected item ids do not match its dataset limit"
            )
        trials = manifest.trials
        resolved_model = manifest.model
        if model is not None and model != resolved_model:
            raise RescoreError(
                f"requested model {model!r} does not match run manifest model "
                f"{resolved_model!r}"
            )
        if expected_trials is not None and expected_trials != trials:
            raise RescoreError(
                "expected_trials does not match the run manifest trial count"
            )
    else:
        selected_ids = tuple(item.id for item in items)
        trials = expected_trials if expected_trials is not None else configured_trials
        resolved_model = model or ""

    if isinstance(trials, bool) or not isinstance(trials, int) or trials < 1:
        raise RescoreError("expected trial count must be a positive integer")

    latest: dict[tuple[str, int], RunResult] = {}
    observed_models: set[str] = set()
    manifest_digest = manifest.digest if manifest is not None else None
    for line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
        if not raw_line:
            raise RescoreError(f"response checkpoint line {line_number} is empty")
        try:
            payload = _load_json(raw_line)
        except ValueError as exc:
            raise RescoreError(
                f"invalid response checkpoint line {line_number}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise RescoreError(
                f"response checkpoint line {line_number} must be a JSON object"
            )
        expected_fields = {"id", "trial", "response", "metadata", "error"}
        if set(payload) != expected_fields:
            raise RescoreError(
                f"response checkpoint line {line_number} fields differ from RunResult"
            )
        if not isinstance(payload["id"], str) or not payload["id"]:
            raise RescoreError(f"checkpoint line {line_number} has an invalid item id")
        if (
            isinstance(payload["trial"], bool)
            or not isinstance(payload["trial"], int)
            or payload["trial"] < 1
        ):
            raise RescoreError(
                f"checkpoint line {line_number} has an invalid trial number"
            )
        if not isinstance(payload["metadata"], dict):
            raise RescoreError(
                f"checkpoint line {line_number} metadata must be an object"
            )
        if payload["error"] is not None and not isinstance(payload["error"], str):
            raise RescoreError(
                f"checkpoint line {line_number} error must be text or null"
            )
        try:
            result = RunResult.from_dict(payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise RescoreError(
                f"invalid RunResult on checkpoint line {line_number}: {exc}"
            ) from exc
        if result.id not in selected_ids:
            raise RescoreError(
                f"checkpoint line {line_number} contains unselected item {result.id!r}"
            )
        if result.trial > trials:
            raise RescoreError(
                f"checkpoint line {line_number} exceeds the expected trial count"
            )
        row_digest = result.metadata.get("run_manifest_digest")
        if manifest_digest is not None and row_digest != manifest_digest:
            raise RescoreError(
                f"checkpoint line {line_number} is not bound to the adjacent run manifest"
            )
        if manifest_digest is None and row_digest is not None:
            raise RescoreError(
                "checkpoint declares a run manifest digest but its sidecar is missing"
            )
        row_model = result.metadata.get("model")
        if row_model is not None:
            if not isinstance(row_model, str) or not row_model:
                raise RescoreError(
                    f"checkpoint line {line_number} has an invalid model identity"
                )
            observed_models.add(row_model)
        latest[(result.id, result.trial)] = result

    if not latest:
        raise RescoreError("response checkpoint contains no RunResult rows")
    if len(observed_models) > 1:
        raise RescoreError("response checkpoint contains multiple model identities")
    if manifest is not None and observed_models and observed_models != {manifest.model}:
        raise RescoreError(
            "response checkpoint model identity does not match its run manifest"
        )
    if manifest is None:
        if resolved_model and observed_models and observed_models != {resolved_model}:
            raise RescoreError(
                "response checkpoint model identity does not match requested model"
            )
        if not resolved_model:
            resolved_model = next(iter(observed_models), path.stem)

    missing_trials = tuple(
        (item_id, trial)
        for item_id in selected_ids
        for trial in range(1, trials + 1)
        if (item_id, trial) not in latest
    )
    missing_items = tuple(
        item_id
        for item_id in selected_ids
        if not any((item_id, trial) in latest for trial in range(1, trials + 1))
    )
    selected_items = tuple(_clone_item(item_by_id[item_id]) for item_id in selected_ids)
    ordered_responses = tuple(
        _clone_result(latest[(item_id, trial)])
        for item_id in selected_ids
        for trial in range(1, trials + 1)
        if (item_id, trial) in latest
    )
    return CapturedResponses(
        benchmark=benchmark_name,
        model=resolved_model,
        checkpoint_path=path,
        checkpoint_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        checkpoint_size=len(raw_bytes),
        run_manifest_path=manifest_path.resolve(),
        run_manifest_sha256=manifest_sha256,
        run_manifest_size=manifest_size,
        dataset_sha256=dataset_sha256,
        prompt_sha256=prompt_sha256,
        selected_item_ids=selected_ids,
        expected_trials=trials,
        items=selected_items,
        responses=ordered_responses,
        missing_item_ids=missing_items,
        missing_trials=missing_trials,
        run_manifest=manifest,
        system_prompt=system_prompt,
    )


def rescore(
    captured: CapturedResponses,
    *,
    scorer: BaseScorer,
    results_dir: str | Path | None = None,
    baseline: ScoringRevision | str | Path | None = None,
    primary_metric: str | tuple[str, str] | None = None,
    bootstrap: int = 0,
    seed: int = 0,
) -> ScoringRevision:
    """Apply a deterministic scorer without invoking the solver."""

    if not isinstance(captured, CapturedResponses):
        raise TypeError("captured must be CapturedResponses from load_responses()")
    if isinstance(bootstrap, bool) or not isinstance(bootstrap, int) or bootstrap < 0:
        raise RescoreError("bootstrap must be a non-negative integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise RescoreError("seed must be an integer")
    scorer.configure(system_prompt=captured.system_prompt)
    scorer_identity = identify_scorer(scorer)

    by_item: dict[str, list[RunResult]] = defaultdict(list)
    for result in captured.responses:
        by_item[result.id].append(_clone_result(result))
    per_item: list[tuple[str, tuple[Metric, ...]]] = []
    for item in captured.items:
        responses = sorted(by_item.get(item.id, []), key=lambda value: value.trial)
        if not responses:
            continue
        try:
            raw_metrics = scorer.score_item(_clone_item(item), responses)
        except KeyError as exc:
            missing = exc.args[0] if exc.args else "unknown"
            raise RescoreError(
                f"scorer failed on item {item.id!r}: missing key {missing!r}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise RescoreError(
                f"scorer failed on item {item.id!r}: {type(exc).__name__}: {exc}"
            ) from exc
        metrics = _validated_metrics(item.id, raw_metrics)
        per_item.append((item.id, metrics))

    aggregate_metrics = tuple(
        sorted(
            aggregate(
                ([metric for metric in metrics] for _, metrics in per_item),
                bootstrap=bootstrap,
                seed=seed,
            ),
            key=lambda value: (value.category, value.name),
        )
    )
    baseline_revision = _resolve_baseline(baseline)
    if baseline_revision is not None:
        if baseline_revision.checkpoint_sha256 != captured.checkpoint_sha256:
            raise RescoreError("baseline revision uses different response checkpoint bytes")
        if (
            baseline_revision.benchmark != captured.benchmark
            or baseline_revision.model != captured.model
        ):
            raise RescoreError("baseline revision benchmark/model identity differs")
        if (
            baseline_revision.dataset_sha256 != captured.dataset_sha256
            or baseline_revision.prompt_sha256 != captured.prompt_sha256
            or baseline_revision.run_manifest_digest != captured.run_manifest_digest
            or baseline_revision.run_manifest_sha256 != captured.run_manifest_sha256
            or baseline_revision.selected_item_ids != captured.selected_item_ids
            or baseline_revision.expected_trials != captured.expected_trials
        ):
            raise RescoreError("baseline revision input bindings differ")

    score_diff = (
        diff_scores(
            baseline_revision.per_item,
            per_item,
            primary_metric=primary_metric,
        )
        if baseline_revision is not None
        else None
    )
    identity_payload = {
        "schema_version": SCORING_REVISION_SCHEMA_VERSION,
        "benchmark": captured.benchmark,
        "model": captured.model,
        "checkpoint_sha256": captured.checkpoint_sha256,
        "dataset_sha256": captured.dataset_sha256,
        "prompt_sha256": captured.prompt_sha256,
        "run_manifest_digest": captured.run_manifest_digest,
        "run_manifest_sha256": captured.run_manifest_sha256,
        "selected_item_ids": list(captured.selected_item_ids),
        "expected_trials": captured.expected_trials,
        "scorer_sha256": scorer_identity.digest,
        "bootstrap": bootstrap,
        "seed": seed,
    }
    revision_digest = _sha256_json(identity_payload)
    captured_ids = tuple(item_id for item_id, _ in per_item)
    revision = ScoringRevision(
        benchmark=captured.benchmark,
        model=captured.model,
        checkpoint_sha256=captured.checkpoint_sha256,
        dataset_sha256=captured.dataset_sha256,
        prompt_sha256=captured.prompt_sha256,
        run_manifest_digest=captured.run_manifest_digest,
        run_manifest_sha256=captured.run_manifest_sha256,
        scorer_identity=scorer_identity,
        bootstrap=bootstrap,
        seed=seed,
        expected_trials=captured.expected_trials,
        selected_item_ids=captured.selected_item_ids,
        captured_item_ids=captured_ids,
        missing_item_ids=captured.missing_item_ids,
        missing_trials=captured.missing_trials,
        per_item=tuple(per_item),
        metrics=aggregate_metrics,
        revision_digest=revision_digest,
        diff=score_diff,
    )

    _verify_captured_sources(captured)
    if results_dir is None:
        return revision
    return _write_revision(
        revision,
        checkpoint_path=captured.checkpoint_path,
        checkpoint_size=captured.checkpoint_size,
        results_dir=Path(results_dir),
        baseline=baseline_revision,
    )


def load_scoring_revision(path: str | Path) -> ScoringRevision:
    """Load and verify a previously written scoring revision."""

    supplied_path = Path(path).expanduser()
    if supplied_path.is_symlink():
        raise RescoreError("scoring revision receipt must not be a symlink")
    receipt_path = supplied_path.resolve()
    _regular_file(receipt_path, "scoring revision receipt")
    try:
        payload = _load_json(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise RescoreError(f"invalid scoring revision: {exc}") from exc
    if not isinstance(payload, dict):
        raise RescoreError("scoring revision must be a JSON object")
    if payload.get("schema_version") != SCORING_REVISION_SCHEMA_VERSION:
        raise RescoreError("unsupported scoring revision schema")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        raise RescoreError("scoring revision artifacts must be an object")
    if set(artifacts) != {"item_scores", "scores"}:
        raise RescoreError("scoring revision artifact inventory differs")
    artifact_paths: dict[str, Path] = {}
    for key, spec in artifacts.items():
        if not isinstance(spec, dict) or set(spec) != {"path", "sha256", "size"}:
            raise RescoreError(f"scoring revision artifact {key!r} is invalid")
        relative = spec["path"]
        if not isinstance(relative, str):
            raise RescoreError(f"scoring revision artifact {key!r} path is invalid")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or len(pure.parts) != 1 or "\\" in relative:
            raise RescoreError(f"scoring revision artifact {key!r} path is unsafe")
        artifact_path = receipt_path.parent / relative
        _regular_file(artifact_path, f"scoring revision artifact {key}")
        raw = artifact_path.read_bytes()
        if (
            isinstance(spec["size"], bool)
            or not isinstance(spec["size"], int)
            or spec["size"] < 0
            or not isinstance(spec["sha256"], str)
            or len(spec["sha256"]) != 64
        ):
            raise RescoreError(f"scoring revision artifact {key!r} identity is invalid")
        if (
            len(raw) != spec["size"]
            or hashlib.sha256(raw).hexdigest() != spec["sha256"]
        ):
            raise RescoreError(f"scoring revision artifact {key!r} changed")
        artifact_paths[key] = artifact_path

    try:
        scorer_payload = payload["scorer"]
        scorer_identity = ScorerIdentity(
            qualified_name=scorer_payload["qualified_name"],
            source_sha256=scorer_payload["source_sha256"],
            configuration=scorer_payload["configuration"],
            schema_version=scorer_payload["schema_version"],
        )
        if scorer_identity.digest != payload["scorer_sha256"]:
            raise RescoreError("scoring revision scorer identity changed")
        per_item = _load_item_scores(artifact_paths["item_scores"])
        metrics = tuple(_metric_from_dict(value) for value in payload["metrics"])
        coverage = payload["coverage"]
        identity_payload = {
            "schema_version": SCORING_REVISION_SCHEMA_VERSION,
            "benchmark": payload["benchmark"],
            "model": payload["model"],
            "checkpoint_sha256": payload["source"]["sha256"],
            "dataset_sha256": payload["dataset_sha256"],
            "prompt_sha256": payload["prompt_sha256"],
            "run_manifest_digest": payload["run_manifest_digest"],
            "run_manifest_sha256": payload["run_manifest_sha256"],
            "selected_item_ids": coverage["selected_item_ids"],
            "expected_trials": coverage["expected_trials"],
            "scorer_sha256": payload["scorer_sha256"],
            "bootstrap": payload["aggregation"]["bootstrap"],
            "seed": payload["aggregation"]["seed"],
        }
        if _sha256_json(identity_payload) != payload["revision_digest"]:
            raise RescoreError("scoring revision identity digest changed")
        missing_trials = tuple(
            (value["item_id"], value["trial"])
            for value in coverage["missing_trials"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, RescoreError):
            raise
        raise RescoreError(f"invalid scoring revision fields: {exc}") from exc
    return ScoringRevision(
        benchmark=payload["benchmark"],
        model=payload["model"],
        checkpoint_sha256=payload["source"]["sha256"],
        dataset_sha256=payload["dataset_sha256"],
        prompt_sha256=payload["prompt_sha256"],
        run_manifest_digest=payload["run_manifest_digest"],
        run_manifest_sha256=payload["run_manifest_sha256"],
        scorer_identity=scorer_identity,
        bootstrap=payload["aggregation"]["bootstrap"],
        seed=payload["aggregation"]["seed"],
        expected_trials=coverage["expected_trials"],
        selected_item_ids=tuple(coverage["selected_item_ids"]),
        captured_item_ids=tuple(coverage["captured_item_ids"]),
        missing_item_ids=tuple(coverage["missing_item_ids"]),
        missing_trials=missing_trials,
        per_item=per_item,
        metrics=metrics,
        revision_digest=payload["revision_digest"],
        root=receipt_path.parent,
        receipt_path=receipt_path,
        item_scores_path=artifact_paths["item_scores"],
        scores_path=artifact_paths["scores"],
        diff_path=artifact_paths.get("diff"),
        report_path=artifact_paths.get("report"),
    )


def _write_revision(
    revision: ScoringRevision,
    *,
    checkpoint_path: Path,
    checkpoint_size: int,
    results_dir: Path,
    baseline: ScoringRevision | None,
) -> ScoringRevision:
    results_root = results_dir.expanduser().resolve()
    parent = (
        results_root
        / "scoring"
        / _slug(revision.benchmark)
        / revision.checkpoint_sha256
    )
    destination = parent / revision.revision_digest
    parent.mkdir(parents=True, exist_ok=True)

    item_bytes = _item_score_bytes(revision.per_item)
    scores_bytes = _scores_csv_bytes(revision)
    files: dict[str, bytes] = {
        "item-scores.jsonl": item_bytes,
        "scores.csv": scores_bytes,
    }
    artifact_keys = {
        "item-scores.jsonl": "item_scores",
        "scores.csv": "scores",
    }
    artifacts = {
        artifact_keys[name]: {
            "path": name,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        }
        for name, content in sorted(files.items())
    }
    source_path = _display_path(checkpoint_path, results_root)
    receipt = {
        "schema_version": SCORING_REVISION_SCHEMA_VERSION,
        "revision_digest": revision.revision_digest,
        "benchmark": revision.benchmark,
        "model": revision.model,
        "source": {
            "path": source_path,
            "sha256": revision.checkpoint_sha256,
            "size": checkpoint_size,
        },
        "run_manifest_digest": revision.run_manifest_digest,
        "run_manifest_sha256": revision.run_manifest_sha256,
        "dataset_sha256": revision.dataset_sha256,
        "prompt_sha256": revision.prompt_sha256,
        "scorer": revision.scorer_identity.to_dict(),
        "scorer_sha256": revision.scorer_identity.digest,
        "aggregation": {"bootstrap": revision.bootstrap, "seed": revision.seed},
        "coverage": {
            "expected_trials": revision.expected_trials,
            "selected_item_ids": list(revision.selected_item_ids),
            "captured_item_ids": list(revision.captured_item_ids),
            "missing_item_ids": list(revision.missing_item_ids),
            "missing_trials": [
                {"item_id": item_id, "trial": trial}
                for item_id, trial in revision.missing_trials
            ],
        },
        "metrics": [metric.to_dict() for metric in revision.metrics],
        "solver_calls": 0,
        "artifacts": artifacts,
        "claim_boundary": (
            "This revision re-scores one retained benchmark run. It does not "
            "make a broader clinical-performance claim."
        ),
    }
    files["scoring-revision.json"] = _pretty_json_bytes(receipt)
    _atomic_directory(destination, files)
    diff_path: Path | None = None
    report_path: Path | None = None
    if revision.diff is not None and baseline is not None:
        primary = f"{revision.diff.primary_category}/{revision.diff.primary_metric}"
        comparison_digest = _sha256_json(
            {
                "schema_version": SCORE_DIFF_SCHEMA_VERSION,
                "baseline_revision": baseline.revision_digest,
                "candidate_revision": revision.revision_digest,
                "primary_metric": primary,
            }
        )
        comparison = destination / "comparisons" / comparison_digest
        comparison_payload = {
            "schema_version": SCORE_DIFF_SCHEMA_VERSION,
            "comparison_digest": comparison_digest,
            "baseline_revision": baseline.revision_digest,
            "candidate_revision": revision.revision_digest,
            **revision.diff.to_dict(),
        }
        _atomic_directory(
            comparison,
            {
                "diff.json": _pretty_json_bytes(comparison_payload),
                "diff.md": _diff_markdown(revision.diff).encode("utf-8"),
            },
        )
        diff_path = comparison / "diff.json"
        report_path = comparison / "diff.md"
    return ScoringRevision(
        **{
            **revision.__dict__,
            "root": destination,
            "receipt_path": destination / "scoring-revision.json",
            "item_scores_path": destination / "item-scores.jsonl",
            "scores_path": destination / "scores.csv",
            "diff_path": diff_path,
            "report_path": report_path,
        }
    )


def _benchmark_snapshot(
    benchmark: Any,
) -> tuple[str, tuple[BenchmarkItem, ...], str | None, int]:
    name = getattr(benchmark, "name", None)
    dataset = getattr(benchmark, "dataset", None)
    if not isinstance(name, str) or not name:
        raise RescoreError("benchmark must have a non-empty name")
    if dataset is None:
        raise RescoreError("benchmark must provide a dataset")
    raw_items = list(dataset)
    if not raw_items:
        raise RescoreError("benchmark dataset is empty")
    if any(not isinstance(item, BenchmarkItem) for item in raw_items):
        raise RescoreError("benchmark dataset must contain BenchmarkItem objects")
    ids = [item.id for item in raw_items]
    if any(not value for value in ids) or len(set(ids)) != len(ids):
        raise RescoreError("benchmark dataset item ids must be non-empty and unique")
    prompt = getattr(dataset, "system_prompt", None)
    if prompt is not None and not isinstance(prompt, str):
        raise RescoreError("benchmark dataset system prompt must be text or null")
    runner_config = getattr(benchmark, "runner_config", None)
    trials = getattr(runner_config, "trials", 1)
    return name, tuple(_clone_item(item) for item in raw_items), prompt, trials


def _validated_metrics(item_id: str, values: Any) -> tuple[Metric, ...]:
    if not isinstance(values, list):
        raise RescoreError(f"scorer for item {item_id!r} must return a list of Metric")
    seen: set[tuple[str, str]] = set()
    out: list[Metric] = []
    for value in values:
        if not isinstance(value, Metric):
            raise RescoreError(
                f"scorer for item {item_id!r} returned a non-Metric value"
            )
        if not isinstance(value.name, str) or not value.name:
            raise RescoreError(f"scorer for item {item_id!r} returned an invalid metric name")
        if not isinstance(value.category, str) or not value.category:
            raise RescoreError(
                f"scorer for item {item_id!r} returned an invalid metric category"
            )
        if isinstance(value.value, bool) or not isinstance(value.value, (int, float)):
            raise RescoreError(f"scorer for item {item_id!r} returned a non-numeric metric")
        if not math.isfinite(float(value.value)):
            raise RescoreError(f"scorer for item {item_id!r} returned a non-finite metric")
        if value.n is not None and (
            isinstance(value.n, bool) or not isinstance(value.n, int) or value.n < 0
        ):
            raise RescoreError(f"scorer for item {item_id!r} returned an invalid metric n")
        if value.ci is not None and (
            isinstance(value.ci, bool)
            or not isinstance(value.ci, (int, float))
            or not math.isfinite(float(value.ci))
            or value.ci < 0
        ):
            raise RescoreError(f"scorer for item {item_id!r} returned an invalid metric CI")
        key = (value.category, value.name)
        if key in seen:
            raise RescoreError(
                f"scorer for item {item_id!r} returned duplicate metric {key!r}"
            )
        seen.add(key)
        out.append(
            Metric(
                name=value.name,
                value=float(value.value),
                category=value.category,
                n=value.n,
                ci=float(value.ci) if value.ci is not None else None,
            )
        )
    return tuple(sorted(out, key=lambda metric: (metric.category, metric.name)))


def _item_score_bytes(
    per_item: Sequence[tuple[str, Sequence[Metric]]],
) -> bytes:
    lines = []
    for item_id, metrics in per_item:
        row = {
            "schema_version": ITEM_SCORE_SCHEMA_VERSION,
            "item_id": item_id,
            "metrics": [metric.to_dict() for metric in metrics],
        }
        lines.append(_canonical_json(row))
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _scores_csv_bytes(revision: ScoringRevision) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["benchmark", "model", "category", "metric", "n", "value", "ci"])
    for metric in revision.metrics:
        writer.writerow(
            [
                revision.benchmark,
                revision.model,
                metric.category,
                metric.name,
                metric.n if metric.n is not None else "",
                f"{metric.value:.6f}",
                f"{metric.ci:.6f}" if metric.ci is not None else "",
            ]
        )
    return stream.getvalue().encode("utf-8")


def _load_item_scores(path: Path) -> tuple[tuple[str, tuple[Metric, ...]], ...]:
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise RescoreError("item score artifact must be newline-terminated")
    rows: list[tuple[str, tuple[Metric, ...]]] = []
    seen: set[str] = set()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RescoreError("item score artifact must be UTF-8") from exc
    for line_number, line in enumerate(text.splitlines(), start=1):
        try:
            payload = _load_json(line)
            if (
                not isinstance(payload, dict)
                or payload.get("schema_version") != ITEM_SCORE_SCHEMA_VERSION
            ):
                raise ValueError("unsupported item score row")
            item_id = payload["item_id"]
            if not isinstance(item_id, str) or not item_id or item_id in seen:
                raise ValueError("item score ids must be non-empty and unique")
            metrics = tuple(_metric_from_dict(value) for value in payload["metrics"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RescoreError(f"invalid item score line {line_number}: {exc}") from exc
        seen.add(item_id)
        rows.append((item_id, metrics))
    return tuple(rows)


def _metric_from_dict(value: Any) -> Metric:
    if not isinstance(value, dict) or set(value) != {"name", "value", "category", "n", "ci"}:
        raise ValueError("metric fields differ")
    metric = Metric(**value)
    return _validated_metrics("artifact", [metric])[0]


def _resolve_baseline(
    baseline: ScoringRevision | str | Path | None,
) -> ScoringRevision | None:
    if baseline is None:
        return None
    if isinstance(baseline, ScoringRevision):
        return baseline
    return load_scoring_revision(baseline)


def _diff_markdown(value: ScoreDiff) -> str:
    lines = [
        "# Scoring revision diff",
        "",
        f"Primary metric: `{value.primary_category}/{value.primary_metric}`",
        "",
        f"- Improved: {value.improved}",
        f"- Regressed: {value.regressed}",
        f"- Unchanged: {value.unchanged}",
        f"- Added: {value.added}",
        f"- Removed: {value.removed}",
        "",
        "## Largest changes",
        "",
        "| Item | Category | Metric | Before | After | Delta |",
        "| --- | --- | --- | ---: | ---: | ---: |",
    ]
    for change in top_changes(value, limit=10):
        lines.append(
            f"| {change.item_id} | {change.category} | {change.metric} | "
            f"{change.before:.6f} | {change.after:.6f} | {change.delta:+.6f} |"
        )
    lines.append("")
    return "\n".join(lines)


def _atomic_directory(destination: Path, files: Mapping[str, bytes]) -> None:
    atomic_directory(destination, files, _verify_existing_directory)


def _verify_existing_directory(destination: Path, files: Mapping[str, bytes]) -> None:
    if not destination.is_dir() or destination.is_symlink():
        raise RescoreError("scoring revision destination is not a safe directory")
    entries = list(destination.iterdir())
    comparisons = destination / "comparisons"
    if comparisons in entries and (
        comparisons.is_symlink() or not comparisons.is_dir()
    ):
        raise RescoreError("scoring revision comparisons entry is unsafe")
    actual = {path.name for path in entries if path.name != "comparisons"}
    if actual != set(files):
        raise RescoreError("existing scoring revision has a different file inventory")
    for name, content in files.items():
        path = destination / name
        _regular_file(path, f"existing scoring revision {name}")
        if path.read_bytes() != content:
            raise RescoreError("existing scoring revision bytes do not match its identity")


def _clone_item(value: BenchmarkItem) -> BenchmarkItem:
    return BenchmarkItem.from_dict(json.loads(_canonical_json(value.to_dict())))


def _clone_result(value: RunResult) -> RunResult:
    return RunResult.from_dict(json.loads(_canonical_json(value.to_dict())))


def _verify_captured_sources(captured: CapturedResponses) -> None:
    """Close the load-to-write window for both retained source files."""

    _regular_file(captured.checkpoint_path, "response checkpoint")
    checkpoint_bytes = captured.checkpoint_path.read_bytes()
    if (
        len(checkpoint_bytes) != captured.checkpoint_size
        or hashlib.sha256(checkpoint_bytes).hexdigest()
        != captured.checkpoint_sha256
    ):
        raise RescoreError("response checkpoint changed while it was being scored")

    manifest_exists = _entry_exists(captured.run_manifest_path)
    if captured.run_manifest_sha256 is None:
        if manifest_exists:
            raise RescoreError("run manifest sidecar appeared while responses were scored")
        return
    if not manifest_exists:
        raise RescoreError("run manifest sidecar disappeared while responses were scored")
    _regular_file(captured.run_manifest_path, "run manifest")
    manifest_bytes = captured.run_manifest_path.read_bytes()
    if (
        len(manifest_bytes) != captured.run_manifest_size
        or hashlib.sha256(manifest_bytes).hexdigest()
        != captured.run_manifest_sha256
    ):
        raise RescoreError("run manifest sidecar changed while responses were scored")


def _regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise RescoreError(f"{label} must be a regular, non-symlink file: {path}")


def _entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _load_json(text: str) -> Any:
    return strict_json_loads(text, "record")


def _pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _slug(value: str) -> str:
    return value.replace("/", "__").replace(":", "_")


__all__ = [
    "CAPTURED_RESPONSES_SCHEMA_VERSION",
    "ITEM_SCORE_SCHEMA_VERSION",
    "SCORE_DIFF_SCHEMA_VERSION",
    "SCORING_REVISION_SCHEMA_VERSION",
    "CapturedResponses",
    "RescoreError",
    "ScoringRevision",
    "load_responses",
    "load_scoring_revision",
    "rescore",
]
