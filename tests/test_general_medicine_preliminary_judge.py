"""Offline contract tests for preliminary general-medicine AI judging."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from arisekit.client import ModelCall, ModelResponse
from benchmarks.general_medicine_adaptive import build
from benchmarks.general_medicine_adaptive.preliminary_judge import (
    CRITERIA,
    build_pipeline_controls,
    load_source_results,
    run_preliminary_judge,
)
from benchmarks.general_medicine_adaptive.scorer import AdaptiveConsultScorer


def _judgment(score: int, *, passed: bool) -> str:
    return json.dumps(
        {
            **{name: score for name in CRITERIA},
            "preliminary_pass": passed,
            "rationale": "The structured trajectory matches the supplied draft."
            if passed
            else "The trajectory contradicts the draft disposition and actions.",
            "flagged_issues": []
            if passed
            else ["Disposition and action mismatch"],
        }
    )


class SequenceJudgeClient:
    model = "offline-preliminary-judge"

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls = 0

    def __call__(self, call: ModelCall) -> ModelResponse:
        text = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return ModelResponse(
            text=text,
            tokens_in=100,
            tokens_out=50,
            cost=0.001,
            cost_known=True,
            provider_model=self.model,
            response_id=f"judge-response-{self.calls}",
        )


def test_controls_separate_under_deterministic_contract() -> None:
    benchmark = build()
    controls = build_pipeline_controls(benchmark)
    scorer = AdaptiveConsultScorer()
    item = benchmark.dataset[0]

    good = {
        metric.name: metric.value
        for metric in scorer.score_item(item, [controls[0]])
    }
    bad = {
        metric.name: metric.value
        for metric in scorer.score_item(item, [controls[1]])
    }

    assert good["structured_contract_completion"] == 1.0
    assert bad["structured_contract_completion"] == 0.0


def test_preliminary_judge_persists_manifested_outputs_and_resumes(
    tmp_path: Path,
) -> None:
    benchmark = build()
    controls = build_pipeline_controls(benchmark)
    client = SequenceJudgeClient(
        [_judgment(5, passed=True), _judgment(1, passed=False)]
    )

    first = run_preliminary_judge(
        benchmark,
        controls,
        judge_model=client.model,
        results_dir=tmp_path,
        max_cost=0.10,
        max_calls=2,
        max_cost_per_call=0.02,
        client=client,
    )

    assert first.expected == 2
    assert first.parsed == 2
    assert first.preliminary_passed == 1
    assert first.control_discrimination is True
    assert first.summary.calls_total == 2
    assert first.summary.cost_total == 0.002
    assert first.summary.output_path.is_file()
    assert (first.summary.output_path.parent / "run-manifest.json").is_file()
    assert first.judge_inputs_path.is_file()
    assert first.judgments_path.is_file()
    assert first.scores_path.is_file()
    with first.scores_path.open("r", encoding="utf-8", newline="") as handle:
        metrics = {row["metric"]: row for row in csv.DictReader(handle)}
    assert metrics["ai_judge_parse_success_rate"]["value"] == "1.000000"
    assert metrics["ai_judge_declared_pass_rate"]["value"] == "0.500000"
    assert metrics["hybrid_preliminary_pass_rate"]["value"] == "0.500000"

    second = run_preliminary_judge(
        benchmark,
        controls,
        judge_model=client.model,
        results_dir=tmp_path,
        max_cost=0.10,
        max_calls=2,
        max_cost_per_call=0.02,
        client=client,
    )

    assert client.calls == 2
    assert second.summary.skipped == 2
    assert second.manifest_digest == first.manifest_digest


def test_invalid_judge_json_is_counted_as_parse_failure(tmp_path: Path) -> None:
    benchmark = build()
    controls = build_pipeline_controls(benchmark)
    client = SequenceJudgeClient(["not json", _judgment(1, passed=False)])

    report = run_preliminary_judge(
        benchmark,
        controls,
        judge_model=client.model,
        results_dir=tmp_path,
        max_cost=0.10,
        max_calls=2,
        max_cost_per_call=0.02,
        client=client,
    )

    assert report.parsed == 1
    parse_metric = next(
        metric
        for metric in report.metrics
        if metric.name == "ai_judge_parse_success_rate"
    )
    assert parse_metric.value == 0.5


def test_ai_false_positive_cannot_override_deterministic_failure(
    tmp_path: Path,
) -> None:
    benchmark = build()
    controls = build_pipeline_controls(benchmark)
    client = SequenceJudgeClient(
        [_judgment(5, passed=True), _judgment(5, passed=True)]
    )

    report = run_preliminary_judge(
        benchmark,
        controls,
        judge_model=client.model,
        results_dir=tmp_path,
        max_cost=0.10,
        max_calls=2,
        max_cost_per_call=0.02,
        client=client,
    )

    by_name = {metric.name: metric.value for metric in report.metrics}
    assert by_name["ai_judge_declared_pass_rate"] == 1.0
    assert by_name["hybrid_preliminary_pass_rate"] == 0.5
    assert report.preliminary_passed == 1


def test_load_source_results_keeps_latest_successful_trajectories(
    tmp_path: Path,
) -> None:
    controls = build_pipeline_controls(build())
    path = tmp_path / "source.jsonl"
    path.write_text(
        "".join(json.dumps(result.to_dict()) + "\n" for result in controls),
        encoding="utf-8",
    )

    loaded = load_source_results(path)

    assert [(result.id, result.trial) for result in loaded] == [
        (controls[0].id, controls[0].trial),
        (controls[1].id, controls[1].trial),
    ]
