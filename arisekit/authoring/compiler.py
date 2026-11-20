"""Compile per-benchmark scores into the unified MAST leaderboard CSV.

Walks legacy and manifest-namespaced score directories, concatenates rows,
and emits `results/compiled.csv` in the shape used by the MAST leaderboard:

    benchmark,model,category,metric,n,value,ci

A composite score is computed as the arithmetic mean of each model's
overall scores across benchmarks. This matches the MAST methodology.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path


HEADER = ["benchmark", "model", "category", "metric", "n", "value", "ci"]


def compile_results(
    results_dir: str | Path = "results",
    *,
    manifest_digests: Iterable[str] | None = None,
) -> Path:
    """Compile one unambiguous score file per benchmark/model pair.

    Without a selection, both legacy ``<benchmark>/<model>.csv`` files and
    manifested ``<benchmark>/<digest>/<model>.csv`` files are discovered.
    Multiple files for the same benchmark/model are rejected instead of
    silently mixing incompatible runs. ``manifest_digests`` can explicitly
    select one or more manifested runs.
    """
    base = Path(results_dir)
    scores_root = base / "scores"
    out = base / "compiled.csv"
    base.mkdir(parents=True, exist_ok=True)

    selected = set(manifest_digests or [])
    files_by_identity: dict[tuple[str, str], list[Path]] = defaultdict(list)
    rows_by_file: dict[Path, list[list[str]]] = {}
    rows: list[list[str]] = []
    if scores_root.exists():
        for csv_path in sorted(scores_root.rglob("*.csv")):
            relative = csv_path.relative_to(scores_root)
            is_manifested = len(relative.parts) >= 3
            digest = relative.parts[-2] if is_manifested else None
            if selected and digest not in selected:
                continue
            file_rows: list[list[str]] = []
            identities: set[tuple[str, str]] = set()
            with csv_path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    rendered = [
                        row.get("benchmark", ""),
                        row.get("model", ""),
                        row.get("category", ""),
                        row.get("metric", ""),
                        row.get("n", ""),
                        row.get("value", ""),
                        row.get("ci", ""),
                    ]
                    file_rows.append(rendered)
                    identities.add((rendered[0], rendered[1]))
            if not file_rows:
                continue
            if len(identities) != 1:
                raise ValueError(
                    f"score file must contain one benchmark/model identity: {csv_path}"
                )
            identity = next(iter(identities))
            files_by_identity[identity].append(csv_path)
            rows_by_file[csv_path] = file_rows

    ambiguous = {
        identity: paths
        for identity, paths in files_by_identity.items()
        if len(paths) > 1
    }
    if ambiguous:
        details = "; ".join(
            f"{benchmark}/{model}: "
            + ", ".join(str(path.relative_to(scores_root)) for path in paths)
            for (benchmark, model), paths in sorted(ambiguous.items())
        )
        raise ValueError(
            "multiple score runs found for the same benchmark/model; "
            "select manifest digest(s) explicitly: "
            f"{details}"
        )

    for identity in sorted(files_by_identity):
        csv_path = files_by_identity[identity][0]
        rows.extend(rows_by_file[csv_path])

    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return out


def composite_scores(
    results_dir: str | Path = "results",
    *,
    category: str = "overall",
) -> dict[str, float]:
    """Mean of each model's overall scores across benchmarks.

    Reads compiled.csv. If it doesn't exist, compile first.
    """
    base = Path(results_dir)
    compiled = base / "compiled.csv"
    if not compiled.exists():
        compile_results(base)

    by_model: dict[str, list[float]] = defaultdict(list)
    with compiled.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row.get("category") != category:
                continue
            try:
                value = float(row["value"])
            except (TypeError, ValueError, KeyError):
                continue
            by_model[row["model"]].append(value)

    return {m: sum(vs) / len(vs) for m, vs in by_model.items() if vs}
