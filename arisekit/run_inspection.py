"""Universal post-run result bundle and human-readable inspection summary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from arisekit.common.files import atomic_write as _atomic_write


SCHEMA_VERSION = "arisekit.run-results.v1"


@dataclass(frozen=True)
class RunInspectionReceipt:
    bundle_path: Path
    report_path: Path
    bundle_sha256: str


def write_run_inspection(
    results: Any,
    *,
    scores_path: str | Path,
    results_root: str | Path,
) -> RunInspectionReceipt:
    """Write ``run-results.json`` and ``run-results.md`` for every run.

    The JSON bundle points at the existing append-only raw checkpoint and
    scored CSV.  It does not replace either source artifact.
    """

    root = Path(results_root).resolve()
    raw_path = Path(results.summary.output_path).resolve()
    score_path = Path(scores_path).resolve()
    identity = results.summary.manifest_digest or "unmanifested"
    destination = (
        root
        / "run-results"
        / _slug(results.benchmark)
        / identity
        / _slug(results.model)
    )
    destination.mkdir(parents=True, exist_ok=True)
    bundle_path = destination / "run-results.json"
    report_path = destination / "run-results.md"

    metrics = [metric.to_dict() for metric in results.metrics]
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "benchmark": results.benchmark,
        "model": results.model,
        "run_manifest_digest": results.summary.manifest_digest,
        "raw_checkpoint": _artifact(root, raw_path),
        "scores": _artifact(root, score_path),
        "summary": {
            "completed": results.summary.completed,
            "errored": results.summary.errored,
            "skipped": results.summary.skipped,
            "cost_total": results.summary.cost_total,
            "budget_exhausted": results.summary.budget_exhausted,
            "cost_unknown": results.summary.cost_unknown,
            "cost_bound_exceeded": results.summary.cost_bound_exceeded,
            "calls_total": results.summary.calls_total,
            "call_budget_exhausted": results.summary.call_budget_exhausted,
            "stop_reason": getattr(results.summary, "stop_reason", None),
        },
        "metrics": metrics,
        "claim_boundary": (
            "These results describe this benchmark snapshot and run only; they "
            "do not establish clinical performance in general."
        ),
    }
    if getattr(results, "judge_summary", None) is not None:
        bundle["judge_summary"] = results.judge_summary
        for i, path in enumerate(results.judge_artifacts):
            bundle[f"judge_artifact_{i}"] = _artifact(root, Path(path).resolve())
    calls_path = raw_path.with_suffix(".calls.jsonl")
    if calls_path.exists():
        bundle["dispatch_journal"] = _artifact(root, calls_path)
    encoded = (
        json.dumps(
            bundle,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    _atomic_write(bundle_path, encoded)
    _atomic_write(report_path, _render_markdown(bundle).encode("utf-8"))
    return RunInspectionReceipt(
        bundle_path=bundle_path,
        report_path=report_path,
        bundle_sha256=hashlib.sha256(encoded).hexdigest(),
    )


def load_and_verify_run_inspection(
    bundle_path: str | Path,
    *,
    results_root: str | Path,
) -> Mapping[str, Any]:
    """Load a result bundle and verify its referenced artifact bytes."""

    try:
        raw = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load run result bundle: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("run result bundle must be a JSON object")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"run result bundle schema must be {SCHEMA_VERSION!r}")
    root = Path(results_root).resolve()
    for key in ("raw_checkpoint", "scores", *[k for k in raw if k.startswith("judge_artifact_") or k == "dispatch_journal"]):
        artifact = raw.get(key)
        if not isinstance(artifact, Mapping):
            raise ValueError(f"run result bundle {key} must be an object")
        if set(artifact) != {"path", "sha256", "size"}:
            raise ValueError(f"run result bundle {key} fields differ")
        relative = artifact["path"]
        if not isinstance(relative, str):
            raise ValueError(f"run result bundle {key}.path must be text")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
            raise ValueError(f"run result bundle {key}.path is unsafe")
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"run result bundle {key}.path escapes results root") from exc
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"run result artifact is missing or unsafe: {relative}")
        payload = path.read_bytes()
        if artifact["size"] != len(payload):
            raise ValueError(f"run result artifact size changed: {relative}")
        if artifact["sha256"] != hashlib.sha256(payload).hexdigest():
            raise ValueError(f"run result artifact digest changed: {relative}")
    return raw


def _artifact(root: Path, path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"run artifact is missing: {path}")
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"run artifact is outside results root: {path}") from exc
    payload = path.read_bytes()
    return {
        "path": relative,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }


def _render_markdown(bundle: dict[str, Any]) -> str:
    summary = bundle["summary"]
    manifest = bundle["run_manifest_digest"] or "not recorded"
    lines = [
        "# Run results",
        "",
        f"- Benchmark: `{bundle['benchmark']}`",
        f"- Model: `{bundle['model']}`",
        f"- Run manifest: `{manifest}`",
        f"- Completed: {summary['completed']}",
        f"- Terminal errors: {summary['errored']}",
        f"- Resumed/skipped: {summary['skipped']}",
        f"- Recorded cost: {summary['cost_total']:.6f}",
        f"- Raw checkpoint: `{bundle['raw_checkpoint']['path']}`",
        f"- Scores: `{bundle['scores']['path']}`",
        "",
        "## Metrics",
        "",
        "| Category | Metric | N | Value | CI |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for metric in bundle["metrics"]:
        n = "" if metric["n"] is None else str(metric["n"])
        ci = "" if metric["ci"] is None else f"{metric['ci']:.6f}"
        lines.append(
            f"| {metric['category']} | {metric['name']} | {n} | "
            f"{metric['value']:.6f} | {ci} |"
        )
    if bundle.get("judge_summary") is not None:
        judge = bundle["judge_summary"]
        lines.extend(["", "## Judge accounting", "", f"- Status: {judge['status']}", f"- Judge calls: {judge['calls_total']}", f"- Judge cost: {judge['cost_usd']:.6f} USD", f"- Cost known: {judge['cost_known']}", f"- Disagreements: {len(judge['disagreements'])}"])
    lines.extend(["", bundle["claim_boundary"], ""])
    return "\n".join(lines)


def _slug(value: str) -> str:
    return value.replace("/", "__").replace(":", "_")


__all__ = [
    "SCHEMA_VERSION",
    "RunInspectionReceipt",
    "load_and_verify_run_inspection",
    "write_run_inspection",
]
