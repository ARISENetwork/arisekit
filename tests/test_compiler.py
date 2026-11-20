"""Score compiler behavior for legacy and manifest-namespaced runs."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from arisekit.authoring.compiler import compile_results


def _write_score(path: Path, *, benchmark: str, model: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["benchmark", "model", "category", "metric", "n", "value", "ci"]
        )
        writer.writerow(
            [benchmark, model, "overall", "primary", "10", value, ""]
        )


def _compiled_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_compile_discovers_manifest_namespaced_scores(tmp_path: Path) -> None:
    _write_score(
        tmp_path / "scores" / "bench-a" / "digest-a" / "model-a.csv",
        benchmark="bench-a",
        model="model-a",
        value="0.75",
    )
    _write_score(
        tmp_path / "scores" / "bench-b" / "digest-b" / "model-a.csv",
        benchmark="bench-b",
        model="model-a",
        value="0.50",
    )

    rows = _compiled_rows(compile_results(tmp_path))

    assert [(row["benchmark"], row["value"]) for row in rows] == [
        ("bench-a", "0.75"),
        ("bench-b", "0.50"),
    ]


def test_compile_rejects_ambiguous_runs_for_same_identity(tmp_path: Path) -> None:
    for digest, value in (("digest-old", "0.25"), ("digest-new", "0.75")):
        _write_score(
            tmp_path / "scores" / "bench" / digest / "model.csv",
            benchmark="bench",
            model="model",
            value=value,
        )

    with pytest.raises(ValueError, match="multiple score runs"):
        compile_results(tmp_path)


def test_compile_can_select_manifest_digests_explicitly(tmp_path: Path) -> None:
    for digest, value in (("digest-old", "0.25"), ("digest-new", "0.75")):
        _write_score(
            tmp_path / "scores" / "bench" / digest / "model.csv",
            benchmark="bench",
            model="model",
            value=value,
        )

    rows = _compiled_rows(
        compile_results(tmp_path, manifest_digests=["digest-new"])
    )

    assert len(rows) == 1
    assert rows[0]["value"] == "0.75"
