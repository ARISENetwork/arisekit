"""CLI verb functions for the ASSURE, DECIDE, and MONITOR surfaces.

Each verb takes an ``argparse.Namespace`` and returns an ``int`` exit code
(0 on success). They are deliberately thin: they read scores CSVs, hand the
parsed metrics to the pure library modules (``arisekit.report``,
``arisekit.compare``, ``arisekit.monitor``), and print or persist the
resulting evidence artifact. No verb calls a model or touches the network,
so every one is deterministic and offline-testable.

The orchestrator wires the argparse subparsers separately (in ``cli.py``);
this module only supplies the ``cmd_*`` callables and the CSV helpers they
share. Each verb's docstring lists the exact Namespace attributes it reads.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from types import SimpleNamespace

from arisekit.types import Metric

# MAST scores CSV schema shared by compiled.csv and per-model score CSVs.
CSV_HEADER = ["benchmark", "model", "category", "metric", "n", "value", "ci"]


# --- CSV helpers -----------------------------------------------------


def metrics_from_csv(path: str | Path) -> list[Metric]:
    """Read a MAST scores CSV into a list of :class:`~arisekit.types.Metric`.

    Expects the ``benchmark,model,category,metric,n,value,ci`` schema. Each
    data row becomes one Metric, keyed by its ``metric`` column. Rows whose
    ``value`` is empty or does not parse as a float are skipped rather than
    crashing the read: an all-failed run writes such rows and they carry no
    measurement. A blank ``category`` normalizes to ``"overall"``; blank
    ``ci`` / ``n`` become ``None``.
    """
    metrics: list[Metric] = []
    with Path(path).open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            value = _to_float(row.get("value"))
            if value is None:
                continue
            metrics.append(
                Metric(
                    name=row.get("metric", "") or "",
                    value=value,
                    category=(row.get("category") or "overall"),
                    ci=_to_float(row.get("ci")),
                    n=_to_int(row.get("n")),
                )
            )
    return metrics


def _results_like(path: str | Path) -> SimpleNamespace:
    """Return a Results-like object for the CSV at ``path``.

    Exposes only the fields the report and checklist code duck-types:
    ``metrics`` (from :func:`metrics_from_csv`), ``model`` and ``benchmark``
    (from the first data row, or ``""`` when the CSV has no rows), and a
    zero ``cost`` (a scores CSV records no spend).
    """
    model = ""
    benchmark = ""
    with Path(path).open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            model = row.get("model", "") or ""
            benchmark = row.get("benchmark", "") or ""
            break
    return SimpleNamespace(
        metrics=metrics_from_csv(path),
        model=model,
        benchmark=benchmark,
        cost=0.0,
    )


def _to_float(value: object) -> float | None:
    """Parse a possibly-empty CSV cell into a float, or None when unparseable."""
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int | None:
    """Parse a possibly-empty CSV cell into an int, or None when unparseable."""
    if value is None or value == "":
        return None
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# --- verbs -----------------------------------------------------------


def cmd_report(args: argparse.Namespace) -> int:
    """Assemble an applied model card (plus optional checklist coverage).

    Reads Namespace attributes:

    - ``scores`` (str): path to a per-model scores CSV or a compiled.csv.
    - ``model`` (str | None): model id, required with ``compiled``.
    - ``compiled`` (bool): treat ``scores`` as a multi-benchmark compiled.csv.
    - ``checklist`` (str | None): checklist name (e.g. ``"tripod_llm"``) to
      evaluate and append as a coverage report.
    - ``output`` (str | None): write the Markdown here, else print to stdout.
    """
    from arisekit.report import Checklist, ModelCard

    if args.compiled and args.model:
        card = ModelCard.from_compiled_csv(args.scores, model=args.model)
    else:
        card = ModelCard.from_results(_results_like(args.scores))

    md = card.to_markdown()

    if args.checklist:
        report = Checklist.load(args.checklist).evaluate(_results_like(args.scores))
        md += "\n\n" + report.to_markdown()

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(md)
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Reduce several vendors' scores CSVs into a ranked comparative scorecard.

    Reads Namespace attributes:

    - ``vendor`` (list[str]): ``"name=path.csv"`` entries, one per vendor.
    - ``output`` (str | None): write the scorecard pivot CSV here if given.
    - ``higher_is_better`` (str | None): optional comma list of
      ``"criterion:false"`` direction overrides (unlisted criteria default to
      higher-is-better).
    """
    from arisekit.compare import comparative_scorecard

    results_by_vendor: dict[str, list[Metric]] = {}
    for entry in args.vendor:
        name, sep, path = entry.partition("=")
        if not sep:
            print(f"malformed vendor (expected name=path.csv): {entry!r}")
            return 2
        results_by_vendor[name] = metrics_from_csv(path)

    overrides = _parse_higher_is_better(args.higher_is_better)
    if overrides:
        sc = comparative_scorecard(results_by_vendor, higher_is_better=overrides)
    else:
        sc = comparative_scorecard(results_by_vendor)

    if args.output:
        sc.to_csv(args.output)
        print(f"wrote {args.output}")

    print(sc.to_markdown())
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    """Run one canary reading and compare it against the locked baseline.

    Reads Namespace attributes:

    - ``config`` (str): path to a MonitorConfig JSON.
    - ``benchmark`` (str): benchmark name under ``benchmarks_dir``.
    - ``benchmarks_dir`` (str): directory of per-benchmark folders.
    - ``model`` (str | None): model id override (else the config's model).
    - ``timestamp`` (str | None): injectable ISO timestamp for the reading.
    """
    from arisekit.monitor import MonitorConfig, latest_vs_baseline

    config = MonitorConfig.from_json(args.config)

    # Lazy import so the benchmark loader (and its heavy deps) is only pulled
    # in when a monitor run actually needs it, and so tests can monkeypatch it.
    from arisekit.cli import _load_benchmark

    bench = _load_benchmark(args.benchmark, Path(args.benchmarks_dir))

    run, verdict = latest_vs_baseline(
        config,
        bench,
        model=args.model,
        timestamp=args.timestamp,
    )

    print(f"canary {run.timestamp}: {run.metric}={run.value:.6f}")
    if verdict is not None:
        print(
            f"is_regression={verdict.is_regression} "
            f"recommend_rollback={verdict.recommend_rollback}"
        )
        print(verdict.message)
    else:
        print("no baseline in config; recorded canary only")
    return 0


# --- verb helpers ----------------------------------------------------


def _parse_higher_is_better(spec: str | None) -> dict[str, bool]:
    """Parse a ``"criterion:false,other:true"`` override spec into a dict.

    Returns an empty dict when ``spec`` is None or blank so the caller can
    omit the argument entirely and fall back to the all-higher-is-better
    default. A value of ``false``/``0``/``no`` (case-insensitive) maps to
    ``False``; anything else maps to ``True``. Entries without a ``:`` are
    treated as ``criterion:true``.
    """
    overrides: dict[str, bool] = {}
    if not spec:
        return overrides
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        criterion, sep, raw = chunk.partition(":")
        criterion = criterion.strip()
        if not criterion:
            continue
        flag = True
        if sep and raw.strip().lower() in ("false", "0", "no"):
            flag = False
        overrides[criterion] = flag
    return overrides
