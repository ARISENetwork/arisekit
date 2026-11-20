"""Applied model card assembly (ASSURE).

Turns a completed run into a CHAI-style applied model card: a
structured, human-readable dossier a committee or regulator can read.

This is an evidence-assembly artifact, never a certification. A run can
only fill the measured parts of a card (the benchmark metrics, the
evaluation cost, the item count). Every prose field a run cannot compute
is stamped with the ``REQUIRES_HUMAN_INPUT`` sentinel and surfaced under
``human_input_required`` so a human owner knows exactly what is missing
before the card is used for any decision.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from arisekit.benchmark import Results


# Sentinel stamped into any field a run cannot compute. A human owner
# must replace every occurrence before the card informs a decision.
REQUIRES_HUMAN_INPUT = "REQUIRES HUMAN INPUT"


# Fixed disclaimer. Makes the framing unambiguous: this is evidence a
# human interprets, not a pass/fail clearance.
DISCLAIMER = (
    "This model card is an evidence-assembly artifact, not a certification "
    "or a clearance. The measured metrics summarize benchmark performance "
    "under the stated evaluation conditions only and do not establish "
    "safety, efficacy, or fitness for any clinical use. Fields marked "
    "'" + REQUIRES_HUMAN_INPUT + "' must be completed, and every result "
    "must be interpreted, by a qualified human owner before any deployment "
    "decision."
)


@dataclass
class ModelCard:
    """A CHAI-style applied model card.

    Sections are nested dicts so the card serializes cleanly to JSON and
    reads section-by-section as Markdown. ``key_metrics`` carries the
    measured evaluation results; ``human_input_required`` lists the dotted
    keys of every field still stamped ``REQUIRES_HUMAN_INPUT``.
    """

    basic_info: dict[str, Any] = field(default_factory=dict)
    uses_and_directions: dict[str, Any] = field(default_factory=dict)
    warnings: dict[str, Any] = field(default_factory=dict)
    trust_ingredients: dict[str, Any] = field(default_factory=dict)
    key_metrics: list[dict[str, Any]] = field(default_factory=list)
    other_information: dict[str, Any] = field(default_factory=dict)
    human_input_required: list[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER

    # --- constructors ------------------------------------------------

    @classmethod
    def from_results(
        cls,
        results: "Results",
        *,
        intended_use: str | None = None,
        warnings: str | None = None,
        date: str | None = None,
    ) -> "ModelCard":
        """Build a single-benchmark card from a completed run.

        ``results`` is duck-typed: only ``.metrics`` (a list of Metric),
        ``.model``, ``.benchmark``, and (optionally) ``.cost`` are read.
        Prose fields the caller supplies (``intended_use``, ``warnings``)
        are filled in; everything else a run cannot compute is left as the
        ``REQUIRES_HUMAN_INPUT`` sentinel and collected into
        ``human_input_required``.
        """
        metrics = list(getattr(results, "metrics", None) or [])
        model = str(getattr(results, "model", REQUIRES_HUMAN_INPUT))
        benchmark = str(getattr(results, "benchmark", REQUIRES_HUMAN_INPUT))
        cost = getattr(results, "cost", None)

        key_metrics = [_metric_to_row(m) for m in metrics]
        benchmarks = [benchmark]
        n_items = _infer_n_items(key_metrics)

        card = cls(
            basic_info={
                "model": model,
                "benchmarks": benchmarks,
                "date": date or _today(),
            },
            uses_and_directions=_uses_and_directions(intended_use),
            warnings=_warnings_section(warnings),
            trust_ingredients=_trust_ingredients(benchmarks, key_metrics),
            key_metrics=key_metrics,
            other_information={
                "evaluation_cost_usd": (
                    round(float(cost), 6)
                    if isinstance(cost, (int, float)) and not isinstance(cost, bool)
                    else REQUIRES_HUMAN_INPUT
                ),
                "n_items": n_items if n_items is not None else REQUIRES_HUMAN_INPUT,
            },
        )
        card.human_input_required = card._collect_human_input_keys()
        return card

    @classmethod
    def from_compiled_csv(
        cls,
        path: str | Path,
        *,
        model: str,
        date: str | None = None,
    ) -> "ModelCard":
        """Build a multi-benchmark card from a compiled MAST CSV.

        Reads the ``benchmark,model,category,metric,n,value,ci`` schema,
        keeps only rows for ``model``, and folds every benchmark's metrics
        into one card. Each ``key_metrics`` entry additionally carries its
        ``benchmark``. Cost is not present in the CSV, so it is stamped
        ``REQUIRES_HUMAN_INPUT``.
        """
        path = Path(path)
        key_metrics: list[dict[str, Any]] = []
        benchmarks: list[str] = []
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if row.get("model") != model:
                    continue
                bench = row.get("benchmark", "") or ""
                if bench and bench not in benchmarks:
                    benchmarks.append(bench)
                key_metrics.append(
                    {
                        "benchmark": bench,
                        "category": row.get("category", "") or "overall",
                        "metric": row.get("metric", "") or "",
                        "value": _to_float(row.get("value")),
                        "ci": _to_float(row.get("ci")),
                        "n": _to_int(row.get("n")),
                    }
                )

        benchmarks = sorted(benchmarks)
        n_items = _infer_n_items(key_metrics)

        card = cls(
            basic_info={
                "model": model,
                "benchmarks": benchmarks or [REQUIRES_HUMAN_INPUT],
                "date": date or _today(),
            },
            uses_and_directions=_uses_and_directions(None),
            warnings=_warnings_section(None),
            trust_ingredients=_trust_ingredients(benchmarks, key_metrics),
            key_metrics=key_metrics,
            other_information={
                "evaluation_cost_usd": REQUIRES_HUMAN_INPUT,
                "n_items": n_items if n_items is not None else REQUIRES_HUMAN_INPUT,
            },
        )
        card.human_input_required = card._collect_human_input_keys()
        return card

    # --- serialization ----------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return the whole card as a JSON-serializable dict."""
        return {
            "basic_info": self.basic_info,
            "uses_and_directions": self.uses_and_directions,
            "warnings": self.warnings,
            "trust_ingredients": self.trust_ingredients,
            "key_metrics": self.key_metrics,
            "other_information": self.other_information,
            "human_input_required": self.human_input_required,
            "disclaimer": self.disclaimer,
        }

    def to_json(self, path: str | Path | None = None) -> str:
        """Return the card as JSON text; also write it to ``path`` if given."""
        text = json.dumps(self.to_dict(), indent=2)
        if path is not None:
            out = Path(path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        return text

    def to_markdown(self, path: str | Path | None = None) -> str:
        """Render a readable card; write it to ``path`` if given.

        Includes a dedicated 'Requires human input' section listing every
        outstanding field and the fixed disclaimer at the foot.
        """
        lines: list[str] = []
        model = self.basic_info.get("model", REQUIRES_HUMAN_INPUT)
        lines.append(f"# Applied model card: {model}")
        lines.append("")
        lines.append("_Evidence-assembly artifact. Not a certification or clearance._")
        lines.append("")

        lines.append("## Basic information")
        lines.extend(_dict_bullets(self.basic_info))
        lines.append("")

        lines.append("## Uses and directions")
        lines.extend(_dict_bullets(self.uses_and_directions))
        lines.append("")

        lines.append("## Warnings")
        lines.extend(_dict_bullets(self.warnings))
        lines.append("")

        lines.append("## Key metrics")
        lines.extend(_metrics_table(self.key_metrics))
        lines.append("")

        lines.append("## Trust ingredients")
        for key, value in self.trust_ingredients.items():
            if key == "evaluation" and isinstance(value, dict):
                benches = ", ".join(str(b) for b in value.get("benchmarks", [])) or "-"
                n_metrics = len(value.get("metrics", []) or [])
                lines.append(
                    f"- Evaluation: {n_metrics} metric(s) measured across {benches} "
                    "(see Key metrics)."
                )
            else:
                lines.append(f"- {_prettify(key)}: {value}")
        lines.append("")

        lines.append("## Other information")
        lines.extend(_dict_bullets(self.other_information))
        lines.append("")

        lines.append("## Requires human input")
        if self.human_input_required:
            lines.append(
                "The following fields could not be computed from the run and "
                "must be completed by a human owner:"
            )
            for key in self.human_input_required:
                lines.append(f"- {key}")
        else:
            lines.append("None outstanding; all fields were provided or computed.")
        lines.append("")

        lines.append("## Disclaimer")
        lines.append(self.disclaimer)
        lines.append("")

        text = "\n".join(lines)
        if path is not None:
            out = Path(path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        return text

    # --- internals ---------------------------------------------------

    def _collect_human_input_keys(self) -> list[str]:
        """Return sorted dotted keys of every field still stamped as a sentinel."""
        found: list[str] = []
        sections = {
            "basic_info": self.basic_info,
            "uses_and_directions": self.uses_and_directions,
            "warnings": self.warnings,
            "trust_ingredients": self.trust_ingredients,
            "other_information": self.other_information,
        }
        for name, section in sections.items():
            _find_sentinel(section, name, found)
        return sorted(found)


# --- section builders ------------------------------------------------


def _uses_and_directions(intended_use: str | None) -> dict[str, Any]:
    return {
        "intended_use_and_workflow": intended_use or REQUIRES_HUMAN_INPUT,
        "intended_users": REQUIRES_HUMAN_INPUT,
        "targeted_patient_population": REQUIRES_HUMAN_INPUT,
    }


def _warnings_section(warnings: str | None) -> dict[str, Any]:
    return {
        "known_risks_and_limitations": warnings or REQUIRES_HUMAN_INPUT,
        "human_oversight": REQUIRES_HUMAN_INPUT,
    }


def _trust_ingredients(
    benchmarks: list[str],
    key_metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "evaluation": {
            "benchmarks": benchmarks,
            "metrics": key_metrics,
            "measured": bool(key_metrics),
        },
        "development_data": REQUIRES_HUMAN_INPUT,
        "fairness_and_subgroup_analysis": REQUIRES_HUMAN_INPUT,
        "external_validation": REQUIRES_HUMAN_INPUT,
    }


# --- helpers ---------------------------------------------------------


def _today() -> str:
    return _date.today().isoformat()


def _metric_to_row(m: Any) -> dict[str, Any]:
    """Normalize a Metric (duck-typed) into a JSON-serializable row."""
    ci = getattr(m, "ci", None)
    n = getattr(m, "n", None)
    return {
        "category": getattr(m, "category", "overall"),
        "metric": getattr(m, "name", ""),
        "value": float(getattr(m, "value", 0.0)),
        "ci": float(ci) if ci is not None else None,
        "n": int(n) if n is not None else None,
    }


def _infer_n_items(key_metrics: list[dict[str, Any]]) -> int | None:
    """Largest per-metric item count; the most honest single n for the card."""
    ns = [row.get("n") for row in key_metrics if isinstance(row.get("n"), int)]
    return max(ns) if ns else None


def _find_sentinel(obj: Any, prefix: str, found: list[str]) -> None:
    """Recurse into dicts collecting dotted keys whose value is the sentinel."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            _find_sentinel(value, f"{prefix}.{key}", found)
    elif isinstance(obj, str) and obj == REQUIRES_HUMAN_INPUT:
        found.append(prefix)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _prettify(key: str) -> str:
    return key.replace("_", " ").capitalize()


def _dict_bullets(section: dict[str, Any]) -> list[str]:
    if not section:
        return ["- (none)"]
    bullets: list[str] = []
    for key, value in section.items():
        if isinstance(value, list):
            rendered = ", ".join(str(v) for v in value) if value else "-"
        else:
            rendered = str(value)
        bullets.append(f"- {_prettify(key)}: {rendered}")
    return bullets


def _fmt_num(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def _metrics_table(key_metrics: list[dict[str, Any]]) -> list[str]:
    if not key_metrics:
        return ["No metrics were recorded for this run."]

    has_benchmark = any("benchmark" in row for row in key_metrics)
    header = ["Benchmark"] if has_benchmark else []
    header += ["Category", "Metric", "Value", "95% CI", "n"]
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")

    small_ns: list[int] = []
    for row in key_metrics:
        cells: list[str] = []
        if has_benchmark:
            cells.append(str(row.get("benchmark", "")))
        cells.append(str(row.get("category", "")))
        cells.append(str(row.get("metric", "")))
        cells.append(_fmt_num(row.get("value")))
        ci = row.get("ci")
        cells.append(f"+/-{_fmt_num(ci)}" if ci is not None else "-")
        n = row.get("n")
        cells.append(str(n) if isinstance(n, int) else "-")
        if isinstance(n, int):
            small_ns.append(n)
        lines.append("| " + " | ".join(cells) + " |")

    if small_ns and min(small_ns) < 30:
        lines.append("")
        lines.append(
            f"> Small-n honesty: some metrics rest on few items (min n = {min(small_ns)}). "
            "Treat point estimates as provisional and read the confidence intervals."
        )
    return lines
