from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from arisekit.run_inspection import (
    SCHEMA_VERSION,
    load_and_verify_run_inspection,
    write_run_inspection,
)
from arisekit.types import Metric


def test_every_run_gets_a_machine_bundle_and_run_results_markdown(tmp_path: Path) -> None:
    raw = tmp_path / "raw" / "demo.jsonl"
    scores = tmp_path / "scores" / "demo.csv"
    raw.parent.mkdir(parents=True)
    scores.parent.mkdir(parents=True)
    raw.write_text('{"id":"case-1"}\n', encoding="utf-8")
    scores.write_text("benchmark,model\ndemo,model\n", encoding="utf-8")
    results = SimpleNamespace(
        benchmark="demo",
        model="provider/model",
        metrics=[Metric(name="accuracy", value=0.75, category="overall", n=4, ci=0.1)],
        summary=SimpleNamespace(
            output_path=raw,
            manifest_digest="a" * 64,
            completed=4,
            errored=0,
            skipped=1,
            cost_total=0.25,
            budget_exhausted=False,
            cost_unknown=False,
            cost_bound_exceeded=False,
            calls_total=4,
            call_budget_exhausted=False,
        ),
    )

    receipt = write_run_inspection(results, scores_path=scores, results_root=tmp_path)
    bundle = json.loads(receipt.bundle_path.read_text(encoding="utf-8"))

    assert bundle["schema_version"] == SCHEMA_VERSION
    assert bundle["raw_checkpoint"]["path"] == "raw/demo.jsonl"
    assert bundle["scores"]["path"] == "scores/demo.csv"
    assert "# Run results" in receipt.report_path.read_text(encoding="utf-8")
    verified = load_and_verify_run_inspection(
        receipt.bundle_path,
        results_root=tmp_path,
    )
    assert verified["benchmark"] == "demo"

    scores.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="size changed|digest changed"):
        load_and_verify_run_inspection(receipt.bundle_path, results_root=tmp_path)
