from dataclasses import replace
import json

import pytest
from arisekit import Benchmark, BenchmarkItem, Dataset
from arisekit.client import ModelResponse
from arisekit.judges.rubric import RubricJudge, validate_rubric
from arisekit.providers import development_profile
from arisekit.runner import RunnerConfig
from arisekit.types import RunResult


def rubric():
    return {
        "schema_version": "arisekit.rubric-judge.v1",
        "criteria": [
            {
                "id": "accuracy",
                "description": "Matches the expected answer",
                "weight": 1,
                "anchors": {"0": "Incorrect", "1": "Correct"},
            }
        ],
        "judges": [
            development_profile().to_dict(),
            replace(development_profile(), name="second-judge").to_dict(),
        ],
        "examples": [
            {
                "case": "2 + 2",
                "response": "4",
                "judgments": {
                    "accuracy": {"score": 1, "rationale": "Matches the reference"}
                },
            }
        ],
        "budget": {"max_calls": 10, "max_cost": 0.1, "max_cost_per_call": 0.01},
    }


def test_rubric_accounts_judges_and_reuses_recorded_calls(tmp_path):
    calls = []

    def judge(score):
        def call(request):
            calls.append(request)
            return ModelResponse(
                json.dumps(
                    {"accuracy": {"score": score, "rationale": "Example rationale"}}
                ),
                cost=0.005,
            )

        return call

    scorer = RubricJudge(
        rubric=rubric(),
        clients={"development-openrouter": judge(1), "second-judge": judge(0)},
    )
    bench = Benchmark(
        name="rubric",
        dataset=Dataset.from_items([BenchmarkItem("a", "2 + 2", ground_truth="4")]),
        scorer=scorer,
        runner_config=RunnerConfig(results_dir=tmp_path),
    )

    class Solver:
        model = "solver"

        def __call__(self, call):
            return ModelResponse("4", cost=0.001)

    results = bench.run(Solver())
    assert len(calls) == 2
    assert results.judge_summary["calls_total"] == 2
    assert results.judge_summary["cost_usd"] == 0.01
    assert results.cost == 0.001
    assert results.judge_summary["disagreements"][0]["range"] == 1
    assert next(m.value for m in results.metrics if m.name == "overall") == 0.5
    repeated = bench.run(Solver())
    assert len(calls) == 2 and repeated.judge_summary["calls_total"] == 2


def test_malformed_rating_keeps_cost_without_fabricating_zero(tmp_path):
    scorer = RubricJudge(
        rubric=rubric(),
        clients={
            p["name"]: lambda c: ModelResponse(
                '{"accuracy":{"score":99,"rationale":"bad"}}', cost=0.005
            )
            for p in rubric()["judges"]
        },
    )
    scorer.begin_run(tmp_path)
    assert (
        scorer.score_item(BenchmarkItem("a", "q"), [RunResult("a", 1, "answer")]) == []
    )
    report = scorer.end_run()
    assert report["status"] == "incomplete" and report["cost_usd"] == 0.01


def test_reference_smoke_does_not_call_paid_judges(tmp_path):
    def never(call):
        raise AssertionError("paid judge during structural smoke")

    scorer = RubricJudge(
        rubric=rubric(), clients={p["name"]: never for p in rubric()["judges"]}
    )
    bench = Benchmark(
        name="smoke",
        dataset=Dataset.from_items([BenchmarkItem("a", "q", ground_truth="a")]),
        scorer=scorer,
        runner_config=RunnerConfig(results_dir=tmp_path),
    )
    result = bench.run("stub/reference")
    assert result.metrics == [] and result.judge_summary["calls_total"] == 0
    assert result.judge_summary["status"] == "skipped-structural-smoke"


def test_rubric_validation_and_scaffold_binding():
    from arisekit.scaffold import ScorerSpec

    spec = ScorerSpec.from_dict(
        {
            "kind": "rubric-judge",
            "primitive": "arisekit.judges.rubric.RubricJudge",
            "options": {"rubric": rubric()},
        }
    )
    assert spec.auto_bindable
    invalid = rubric()
    invalid["examples"][0]["judgments"]["accuracy"]["score"] = True
    with pytest.raises(ValueError, match="finite"):
        validate_rubric(invalid)


def test_standard_scaffold_materializes_and_loads_rubric(tmp_path):
    from test_scaffold import _fixture
    from arisekit.scaffold import (
        BenchmarkScaffoldSpec,
        scaffold_benchmark,
        load_scaffolded_benchmark,
    )

    path, payload = _fixture(
        tmp_path / "authoring",
        scorer={
            "kind": "rubric-judge",
            "primitive": "arisekit.judges.rubric.RubricJudge",
            "options": {"rubric": rubric()},
        },
    )
    payload["readiness"]["library_gaps"] = []
    spec = BenchmarkScaffoldSpec.from_dict(payload, base_dir=path.parent)
    receipt = scaffold_benchmark(spec, output_root=tmp_path / "benchmarks")
    bench = load_scaffolded_benchmark(receipt.root)
    assert isinstance(bench.scorer, RubricJudge)


@pytest.mark.parametrize("modality", ["agentic-fhir", "multimodal"])
def test_rubric_adapter_scaffolds_richer_modalities_and_smokes_without_judges(
    tmp_path, modality
):
    from arisekit.scaffold import (
        BenchmarkScaffoldSpec,
        scaffold_benchmark,
        load_scaffolded_benchmark,
    )

    if modality == "agentic-fhir":
        from test_agentic_fhir_scaffold import _fixture

        path, payload = _fixture(tmp_path / "authoring")
    else:
        from test_multimodal_scaffold import _fixture

        _, path = _fixture(tmp_path)
        payload = json.loads(path.read_text())
    payload["scorer"] = {
        "kind": "rubric-judge",
        "primitive": "arisekit.judges.rubric.RubricJudge",
        "options": {"rubric": rubric()},
    }
    payload["readiness"]["library_gaps"] = []
    spec = BenchmarkScaffoldSpec.from_dict(payload, base_dir=path.parent)
    receipt = scaffold_benchmark(spec, output_root=tmp_path / "benchmarks")
    bench = load_scaffolded_benchmark(receipt.root)
    result = bench.run("stub/reference", results_dir=tmp_path / "results")
    assert result.summary.errored == 0
    assert result.judge_summary["status"] == "skipped-structural-smoke"
