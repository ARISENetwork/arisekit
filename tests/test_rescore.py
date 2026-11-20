"""CUJ 05: deterministic scorer iteration over retained responses."""

from __future__ import annotations

import json
import hashlib
from collections.abc import Mapping
from pathlib import Path

import pytest

from arisekit.agentic import PassAtOneScorer
from arisekit.benchmark import Benchmark
from arisekit.client import ModelCall, ModelResponse
from arisekit.dataset import Dataset
from arisekit.runtime.rescore import (
    RescoreError,
    load_responses,
    load_scoring_revision,
    rescore,
)
from arisekit.runner import RunnerConfig
from arisekit.scorer import BaseScorer, exact_match, identify_scorer
from arisekit.analysis.stats import diff, top_changes
from arisekit.types import BenchmarkItem, Metric, RunResult


class CountingClient:
    model = "offline/solver"

    def __init__(self, answers: Mapping[str, str]) -> None:
        self.answers = dict(answers)
        self.calls = 0

    def __call__(self, call: ModelCall) -> ModelResponse:
        self.calls += 1
        return ModelResponse(text=self.answers[call.item.id], cost=0.0)


class PerItemAnswerScorer(BaseScorer):
    rescore_safe = True

    def __init__(self, answers: Mapping[str, str]) -> None:
        self.answers = dict(answers)

    def configuration(self) -> Mapping[str, object]:
        return {"answers": dict(sorted(self.answers.items()))}

    def score_item(
        self,
        item: BenchmarkItem,
        responses: list[RunResult],
    ) -> list[Metric]:
        expected = self.answers[item.id]
        values = [
            float(result.error is None and result.response == expected)
            for result in responses
        ]
        return [Metric("accuracy", sum(values) / len(values), n=len(values))]


class MissingKeyScorer(BaseScorer):
    rescore_safe = True

    def configuration(self) -> Mapping[str, object]:
        return {"required_key": "contraindications"}

    def score_item(
        self,
        item: BenchmarkItem,
        responses: list[RunResult],
    ) -> list[Metric]:
        del responses
        return [Metric("present", float(bool(item.ground_truth["contraindications"])))]


class UnidentifiedScorer(BaseScorer):
    def score_item(
        self,
        item: BenchmarkItem,
        responses: list[RunResult],
    ) -> list[Metric]:
        del item, responses
        return [Metric("paid", 1.0)]


class PromptAwareScorer(BaseScorer):
    rescore_safe = True

    def __init__(self) -> None:
        self.prompt: str | None = None

    def configure(self, *, system_prompt: str | None = None) -> None:
        self.prompt = system_prompt

    def configuration(self) -> Mapping[str, object]:
        return {
            "system_prompt_sha256": hashlib.sha256(
                (self.prompt or "").encode("utf-8")
            ).hexdigest()
        }

    def score_item(
        self,
        item: BenchmarkItem,
        responses: list[RunResult],
    ) -> list[Metric]:
        del item, responses
        return [Metric("configured", float(self.prompt == "Be concise."))]


def _benchmark(tmp_path: Path, *, prompt: str = "Be concise.") -> Benchmark:
    return Benchmark(
        name="rescore-fixture",
        dataset=Dataset.from_items(
            [
                BenchmarkItem(id="a", prompt="A?", ground_truth={"answer": "old-a"}),
                BenchmarkItem(id="b", prompt="B?", ground_truth={"answer": "old-b"}),
                BenchmarkItem(id="c", prompt="C?", ground_truth={"answer": "same"}),
            ],
            system_prompt=prompt,
        ),
        scorer=exact_match(),
        runner_config=RunnerConfig(results_dir=tmp_path, trials=1),
    )


def _run(tmp_path: Path) -> tuple[Benchmark, CountingClient, Path]:
    benchmark = _benchmark(tmp_path)
    client = CountingClient({"a": "new-a", "b": "old-b", "c": "same"})
    results = benchmark.run(client, auto_manifest=True, results_dir=tmp_path)
    return benchmark, client, results.summary.output_path


def test_rescore_reuses_exact_checkpoint_without_solver_calls_and_is_byte_stable(
    tmp_path: Path,
) -> None:
    benchmark, client, checkpoint = _run(tmp_path)
    original = checkpoint.read_bytes()
    captured = load_responses(checkpoint, benchmark=benchmark)

    first = rescore(
        captured,
        scorer=PerItemAnswerScorer({"a": "new-a", "b": "new-b", "c": "same"}),
        results_dir=tmp_path,
    )
    assert client.calls == 3
    assert checkpoint.read_bytes() == original
    assert first.root is not None
    first_bytes = {
        path.name: path.read_bytes() for path in sorted(first.root.iterdir())
    }

    second = rescore(
        captured,
        scorer=PerItemAnswerScorer({"a": "new-a", "b": "new-b", "c": "same"}),
        results_dir=tmp_path,
    )
    assert second.root == first.root
    assert {
        path.name: path.read_bytes() for path in sorted(second.root.iterdir())
    } == first_bytes
    assert client.calls == 3
    assert first.scores_path is not None
    assert first.scores_path.read_text(encoding="utf-8").splitlines()[0] == (
        "benchmark,model,category,metric,n,value,ci"
    )
    assert json.loads(first.receipt_path.read_text(encoding="utf-8"))["solver_calls"] == 0


def test_latest_retry_row_wins_and_partial_coverage_is_reported(tmp_path: Path) -> None:
    benchmark, _, checkpoint = _run(tmp_path)
    rows = [
        json.loads(line)
        for line in checkpoint.read_text(encoding="utf-8").splitlines()
    ]
    # Keep two selected items, then append a retry for the first key.
    retry = dict(rows[0])
    retry["response"] = "latest-a"
    checkpoint.write_text(
        "\n".join(json.dumps(row) for row in [rows[0], rows[1], retry]) + "\n",
        encoding="utf-8",
    )

    captured = load_responses(checkpoint, benchmark=benchmark)

    assert [(value.id, value.response) for value in captured.responses] == [
        ("a", "latest-a"),
        ("b", "old-b"),
    ]
    assert captured.missing_item_ids == ("c",)
    assert captured.missing_trials == (("c", 1),)
    revision = rescore(
        captured,
        scorer=PerItemAnswerScorer({"a": "latest-a", "b": "old-b", "c": "same"}),
    )
    assert revision.captured_item_ids == ("a", "b")
    assert revision.metrics[0].n == 2


@pytest.mark.parametrize(
    ("changed_prompt", "changed_ground_truth", "message"),
    [
        ("Changed prompt", False, "prompt hash"),
        (None, True, "dataset hash"),
    ],
)
def test_loader_rejects_benchmark_tampering(
    tmp_path: Path,
    changed_prompt: str | None,
    changed_ground_truth: bool,
    message: str,
) -> None:
    _, _, checkpoint = _run(tmp_path)
    altered = _benchmark(tmp_path, prompt=changed_prompt or "Be concise.")
    if changed_ground_truth:
        altered.dataset[0].ground_truth = {"answer": "tampered"}

    with pytest.raises(RescoreError, match=message):
        load_responses(checkpoint, benchmark=altered)


def test_loader_rejects_manifest_or_checkpoint_tampering(tmp_path: Path) -> None:
    benchmark, _, checkpoint = _run(tmp_path)
    row = json.loads(checkpoint.read_text(encoding="utf-8").splitlines()[0])
    row["metadata"]["run_manifest_digest"] = "f" * 64
    checkpoint.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(RescoreError, match="adjacent run manifest"):
        load_responses(checkpoint, benchmark=benchmark)


def test_rescore_rejects_manifest_change_after_checkpoint_binding(tmp_path: Path) -> None:
    benchmark, _, checkpoint = _run(tmp_path)
    captured = load_responses(checkpoint, benchmark=benchmark)
    manifest_path = checkpoint.parent / "run-manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(RescoreError, match="manifest sidecar changed"):
        rescore(captured, scorer=exact_match())


def test_legacy_trial_coverage_is_part_of_revision_identity(tmp_path: Path) -> None:
    benchmark = _benchmark(tmp_path)
    checkpoint = tmp_path / "legacy.jsonl"
    checkpoint.write_text(
        json.dumps(
            RunResult(
                id="a",
                trial=1,
                response="new-a",
                metadata={"model": "offline/solver"},
            ).to_dict()
        )
        + "\n",
        encoding="utf-8",
    )
    scorer = PerItemAnswerScorer({"a": "new-a", "b": "old-b", "c": "same"})

    one_trial = rescore(
        load_responses(
            checkpoint,
            benchmark=benchmark,
            expected_trials=1,
        ),
        scorer=scorer,
        results_dir=tmp_path,
    )
    two_trials = rescore(
        load_responses(
            checkpoint,
            benchmark=benchmark,
            expected_trials=2,
        ),
        scorer=PerItemAnswerScorer(scorer.answers),
        results_dir=tmp_path,
    )

    assert one_trial.revision_digest != two_trials.revision_digest
    assert one_trial.expected_trials == 1
    assert two_trials.expected_trials == 2
    assert len(one_trial.missing_trials) == 2
    assert len(two_trials.missing_trials) == 5


def test_diff_rejects_legacy_baseline_with_different_dataset_binding(
    tmp_path: Path,
) -> None:
    benchmark = _benchmark(tmp_path)
    checkpoint = tmp_path / "legacy.jsonl"
    checkpoint.write_text(
        json.dumps(
            RunResult(
                id="a",
                trial=1,
                response="new-a",
                metadata={"model": "offline/solver"},
            ).to_dict()
        )
        + "\n",
        encoding="utf-8",
    )
    baseline = rescore(
        load_responses(checkpoint, benchmark=benchmark, expected_trials=1),
        scorer=PerItemAnswerScorer({"a": "new-a", "b": "old-b", "c": "same"}),
    )
    changed = _benchmark(tmp_path)
    changed.dataset[0].ground_truth = {"answer": "changed"}
    captured = load_responses(checkpoint, benchmark=changed, expected_trials=1)

    with pytest.raises(RescoreError, match="input bindings differ"):
        rescore(
            captured,
            scorer=PerItemAnswerScorer(
                {"a": "new-a", "b": "old-b", "c": "same"}
            ),
            baseline=baseline,
        )


def test_scorer_error_names_first_item_and_missing_key(tmp_path: Path) -> None:
    benchmark, _, checkpoint = _run(tmp_path)
    captured = load_responses(checkpoint, benchmark=benchmark)

    with pytest.raises(RescoreError, match=r"item 'a'.*missing key 'contraindications'"):
        rescore(captured, scorer=MissingKeyScorer())


def test_non_opted_in_or_paid_scorer_is_blocked_before_persistence(tmp_path: Path) -> None:
    benchmark, _, checkpoint = _run(tmp_path)
    captured = load_responses(checkpoint, benchmark=benchmark)

    with pytest.raises(ValueError, match="paid judge scorers"):
        rescore(captured, scorer=UnidentifiedScorer(), results_dir=tmp_path)


def test_builtin_pass_at_one_has_identity_but_custom_callback_fails_closed() -> None:
    identity = identify_scorer(PassAtOneScorer(condition_schema=None))

    assert identity.configuration == {
        "kind": "pass-at-one",
        "name": "pass_at_1",
        "condition_schema": None,
    }
    with pytest.raises(ValueError, match="deterministic scorer"):
        identify_scorer(PassAtOneScorer(check=lambda _trajectory, _item: True))


def test_scorer_identity_captures_post_configuration_state(tmp_path: Path) -> None:
    benchmark, _, checkpoint = _run(tmp_path)

    revision = rescore(
        load_responses(checkpoint, benchmark=benchmark),
        scorer=PromptAwareScorer(),
        results_dir=tmp_path,
    )

    assert revision.metrics[0].value == 1.0
    expected = hashlib.sha256(b"Be concise.").hexdigest()
    assert revision.scorer_identity.configuration == {
        "system_prompt_sha256": expected
    }
    receipt = json.loads(revision.receipt_path.read_text(encoding="utf-8"))
    assert receipt["scorer"]["configuration"] == {
        "system_prompt_sha256": expected
    }


def test_diff_and_top_changes_report_improvement_regression_and_ties(
    tmp_path: Path,
) -> None:
    benchmark, client, checkpoint = _run(tmp_path)
    captured = load_responses(checkpoint, benchmark=benchmark)
    baseline = rescore(
        captured,
        scorer=PerItemAnswerScorer({"a": "old-a", "b": "old-b", "c": "same"}),
        results_dir=tmp_path,
    )
    candidate = rescore(
        captured,
        scorer=PerItemAnswerScorer({"a": "new-a", "b": "new-b", "c": "same"}),
        baseline=baseline.receipt_path,
        results_dir=tmp_path,
    )

    assert candidate.diff is not None
    assert (candidate.diff.improved, candidate.diff.regressed, candidate.diff.unchanged) == (
        1,
        1,
        1,
    )
    assert [value.item_id for value in top_changes(candidate.diff, limit=2)] == [
        "a",
        "b",
    ]
    assert candidate.diff_path is not None and candidate.diff_path.is_file()
    assert candidate.report_path is not None and candidate.report_path.is_file()
    assert client.calls == 3

    direct = diff(baseline.per_item, candidate.per_item)
    assert direct.to_dict()["summary"]["improved"] == 1


def test_written_revision_detects_item_score_tampering(tmp_path: Path) -> None:
    benchmark, _, checkpoint = _run(tmp_path)
    revision = rescore(
        load_responses(checkpoint, benchmark=benchmark),
        scorer=PerItemAnswerScorer({"a": "new-a", "b": "old-b", "c": "same"}),
        results_dir=tmp_path,
    )
    assert revision.item_scores_path is not None
    revision.item_scores_path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(RescoreError, match="item_scores.*changed"):
        load_scoring_revision(revision.receipt_path)


def test_candidate_revision_and_multiple_baseline_comparisons_coexist(
    tmp_path: Path,
) -> None:
    benchmark, _, checkpoint = _run(tmp_path)
    captured = load_responses(checkpoint, benchmark=benchmark)
    old_a = rescore(
        captured,
        scorer=PerItemAnswerScorer({"a": "old-a", "b": "old-b", "c": "same"}),
        results_dir=tmp_path,
    )
    old_b = rescore(
        captured,
        scorer=PerItemAnswerScorer({"a": "new-a", "b": "new-b", "c": "wrong"}),
        results_dir=tmp_path,
    )
    candidate_scorer = PerItemAnswerScorer(
        {"a": "new-a", "b": "old-b", "c": "same"}
    )
    without_diff = rescore(captured, scorer=candidate_scorer, results_dir=tmp_path)
    against_a = rescore(
        captured,
        scorer=PerItemAnswerScorer(candidate_scorer.answers),
        baseline=old_a,
        results_dir=tmp_path,
    )
    against_b = rescore(
        captured,
        scorer=PerItemAnswerScorer(candidate_scorer.answers),
        baseline=old_b,
        results_dir=tmp_path,
    )

    assert without_diff.root == against_a.root == against_b.root
    assert against_a.diff_path != against_b.diff_path
    assert against_a.diff_path is not None and against_a.diff_path.is_file()
    assert against_b.diff_path is not None and against_b.diff_path.is_file()
    comparisons = without_diff.root / "comparisons"
    assert len([path for path in comparisons.iterdir() if path.is_dir()]) == 2


def test_multimetric_diff_requires_explicit_primary_metric() -> None:
    old = [("a", [Metric("one", 0.0), Metric("two", 1.0)])]
    new = [("a", [Metric("one", 1.0), Metric("two", 0.0)])]

    with pytest.raises(ValueError, match="primary_metric is required"):
        diff(old, new)
    selected = diff(old, new, primary_metric="overall/one")
    assert selected.improved == 1
