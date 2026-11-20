"""Structured review cues for moving retained run evidence back into authoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA_VERSION = "arisekit.iteration-review.v1"


def build_iteration_review(run: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize case outcomes without deciding which authoring change is correct."""

    cases = run.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        raise ValueError("Iteration review requires the verified case outcomes")

    notable: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, Mapping):
            raise ValueError("Iteration review case outcomes must be objects")
        outcome = case.get("outcome")
        if outcome not in {"passed", "failed", "scored", "unscored", "error", "missing"}:
            raise ValueError("Iteration review found an unknown case outcome")
        if outcome not in {"error", "missing", "failed"}:
            continue
        metrics = case.get("metrics", [])
        metric_values = []
        if isinstance(metrics, Sequence) and not isinstance(metrics, (str, bytes)):
            for metric in metrics:
                if isinstance(metric, Mapping) and isinstance(metric.get("name"), str):
                    metric_values.append({"name": metric["name"], "value": metric.get("value")})
        notable.append(
            {
                "id": str(case.get("id", "")),
                "trial": int(case.get("trial", 0)),
                "outcome": outcome,
                "error": str(case["error"]) if case.get("error") else None,
                "metrics": metric_values,
            }
        )

    counts = {outcome: 0 for outcome in ("passed", "failed", "scored", "unscored", "error", "missing")}
    for case in cases:
        counts[str(case["outcome"])] += 1

    if counts["error"] or counts["missing"]:
        opening = "Start with incomplete or errored trials before changing the benchmark definition."
    elif counts["failed"]:
        opening = "Start with the failed cases and compare each response with its reference and scoring rule."
    else:
        opening = "The run has no failed, missing, or errored cases. Review coverage before deciding whether a revision is useful."

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(run.get("id", "")),
        "counts": counts,
        "opening": opening,
        "notable_cases": notable,
        "revision_routes": [
            {
                "stage": "data-intake",
                "label": "Revise cases or references",
                "purpose": "Change source-case coverage, case wording, field mapping, or reference answers.",
            },
            {
                "stage": "rubric-design",
                "label": "Revise the rubric",
                "purpose": "Change scoring criteria, anchors, weights, or the scorer binding.",
            },
            {
                "stage": "study-design",
                "label": "Revise the review plan",
                "purpose": "Change expert review, disagreement handling, or the planned analysis.",
            },
        ],
    }


__all__ = ["SCHEMA_VERSION", "build_iteration_review"]
