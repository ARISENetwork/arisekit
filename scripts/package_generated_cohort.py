"""Export complete generated cohorts without original comparison cases or calls."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from arisekit.benchmark import Benchmark
from arisekit.package import BenchmarkManifest, load_package, write_package
from arisekit.scorer import DeferredScorer
from arisekit.generation.specialty_adapters import SCTConcordanceScorer, _sct_reference, _scoring_context
from arisekit.types import BenchmarkItem


def package(rows, output, *, family, expected, study, input_sha256):
    if (family not in {"sct", "cpc"} or type(expected) is not int or expected < 1 or
        len(rows) != expected or len({r["id"] for r in rows}) != expected):
        raise ValueError("Export every unique case from the complete frozen cohort")
    if not re.fullmatch(r"[a-f0-9]{64}", input_sha256):
        raise ValueError("Bind the frozen source bytes with SHA256")
    for row in rows:
        reference = row["ground_truth"]
        origin = reference.get("reference_origin") if family == "sct" else row.get("metadata", {}).get("reference_origin")
        if origin != "synthetic":
            raise ValueError("The generated package cannot relabel source or expert references")
        if family == "sct":
            _sct_reference(reference)
            _scoring_context(BenchmarkItem.from_dict(row), [], reference)
            if row["metadata"].get("native_prompt") is not True:
                raise ValueError("Native SCT packages require the verified native prompt")
        elif not isinstance(reference.get("final_diagnosis"), str) or not reference["final_diagnosis"].strip():
            raise ValueError("Every CPC case needs its frozen synthetic diagnostic reference")
    scorer = SCTConcordanceScorer(response_format="mast-native-rating") if family == "sct" else DeferredScorer()
    spec = scorer.configuration() if family == "sct" else {"kind": "deferred"}
    provenance = {"source_study": study, "frozen_items_file_sha256": input_sha256,
        "reference_origin": "synthetic", "original_comparison_cases_included": False,
        "clinical_item_edits_during_export": 0, "provider_calls_during_export": 0,
        "application_version": (ROOT / "VERSION").read_text().strip()}
    instructions = ("Load with Benchmark.from_package(path). The packaged scorer accepts native Rating: responses. "
        "Concordance excludes execution failures and truncation; their rates and strict format compliance have separate denominators."
        if family == "sct" else
        "Run with arisekit.generation.cpc_ddx.evaluate(path, solver=solver, judge=judge, config=config). "
        "CPC diagnosis matching requires a separately accounted judge and reports top-1, top-5 and top-10 accuracy.")
    path = write_package(output, manifest=BenchmarkManifest(id="generated-" + family + "-" + input_sha256[:12], name="Generated " + family.upper() + " benchmark",
        version=(ROOT / "VERSION").read_text().strip().removeprefix("v"), scorer=spec, provenance=provenance),
        items=[BenchmarkItem.from_dict(r) for r in rows], write_asset_manifest=True,
        readme=f"# Generated {family.upper()} benchmark\n\n{len(rows)} frozen questions with automated AI references. Weight units do not represent expert votes. Original comparison cases are excluded.\n\nRequires ARISEKit 0.10.108 or newer. {instructions}\n\nFor reproduction, use the source study's recorded model and execution profile. Use the solver output allowance frozen in that study. Argon uses its provider-default temperature; Pro receives temperature zero. CPC uses a separately accounted Pro LOW judge with 4096 output tokens.\n\nSource study: {study}. Export made no inference calls and changed no clinical item or reference.\n")
    verified = load_package(path, verify_assets=True)
    loaded = Benchmark.from_package(path, **({"scorer": DeferredScorer()} if family == "cpc" else {}))
    if [r.to_dict() for r in loaded.dataset] != rows or len(verified.items) != expected:
        raise ValueError("The exported package changed frozen items")
    return path


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--items", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--family", choices=["sct", "cpc"], required=True)
    p.add_argument("--expected", type=int, default=100)
    p.add_argument("--study", required=True)
    args = p.parse_args()
    raw = args.items.read_bytes()
    rows = [json.loads(s) for s in raw.decode().splitlines() if s.strip()]
    print(package(rows, args.output, family=args.family, expected=args.expected, study=args.study,
        input_sha256=hashlib.sha256(raw).hexdigest()))
