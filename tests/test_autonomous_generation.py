"""Generation keeps attempts and budgets while producing runnable candidates."""

from dataclasses import replace
import json
import shutil

import pytest

from arisekit.generation.autonomous_generation import (
    compile_candidate,
    novel_design_request,
    run_autonomous_generation,
)
import arisekit.generation.autonomous_generation as generation
from arisekit.benchmark import Benchmark
from arisekit.client import ModelResponse
from arisekit.dataset import Dataset
from arisekit.package import PackageVerificationError, load_package
from arisekit.runner import RunnerConfig


class FixtureGenerator:
    model = "fixture/generator"

    def __init__(self, outputs, *, cost=0.02, cost_known=True):
        self.outputs = list(outputs)
        self.calls = 0
        self.cost = cost
        self.cost_known = cost_known

    def __call__(self, call):
        output = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        return ModelResponse(
            text=output if isinstance(output, str) else json.dumps(output),
            cost=self.cost, cost_known=self.cost_known,
            provider_model=self.model,
        )


class FixtureSolver:
    model = "fixture/solver"

    def __call__(self, call):
        return ModelResponse(text="routine", cost=0, provider_model=self.model)


def request(request_id="novel-admin"):
    return novel_design_request(
        request_id=request_id,
        need="Measure routine versus urgent routing in a synthetic scheduling workflow.",
        evidence={"policy": "Synthetic policy: requests explicitly marked routine use routine booking."},
        item_count=1,
    )


def candidate():
    return {
        "name": "Synthetic appointment routing",
        "task": "Assign the booking route stated by the local policy.",
        "population": "Scheduling staff",
        "setting": "Synthetic clinic",
        "response_contract": "Return exactly routine or urgent.",
        "rubric": {"criteria": ["Correctly apply the supplied request priority."]},
        "scorer": {"kind": "exact-match"},
        "items": [{"id": "case-1", "prompt": "A request is marked routine. Return its booking route.",
                   "ground_truth": "routine", "source_ids": ["policy"]}],
    }


def test_novel_multisource_request_survives_canonical_freeze():
    from arisekit.common.jsonio import canonical_json as canonical
    from arisekit.types import BenchmarkItem
    req = novel_design_request(request_id="routing", need="A synthetic routing task",
        evidence={"zeta": "A source", "alpha": "Another source"}, item_count=1)
    saved = BenchmarkItem.from_dict(json.loads(canonical(req.to_dict())))
    value = candidate()
    value["items"][0]["source_ids"] = ["zeta"]
    assert compile_candidate(saved, value).items


def config(**overrides):
    return replace(RunnerConfig(
        max_cost=0.5, max_cost_per_call=0.1, max_calls=5,
        max_retries=1, retry_backoff=0, require_known_cost=True,
    ), **overrides)


def generate(tmp_path, model, *, requests=None, cfg=None, **kwargs):
    return run_autonomous_generation(
        requests or Dataset([request()]), model=model, config=cfg or config(),
        output_dir=tmp_path / "generation", data_classification="synthetic", **kwargs,
    )


def test_incomplete_provider_finish_is_not_compiled_even_if_json_is_valid(tmp_path):
    class IncompleteGenerator(FixtureGenerator):
        def __call__(self, call):
            return replace(super().__call__(call), finish_reason="length")
    model = IncompleteGenerator([candidate()])
    report = generate(tmp_path, model, max_repairs=0)
    assert report["compiled"] == 0 and model.calls == 1
    assert report["outcomes"][0]["status"] == "invalid_candidate"
    assert "natural stop" in report["outcomes"][0]["error"]


def test_new_design_becomes_portable_executable_package_and_resumes(tmp_path):
    model = FixtureGenerator([candidate()])
    report = generate(tmp_path, model)
    assert report["requested"] == report["compiled"] == 1
    path = tmp_path / "generation" / report["outcomes"][0]["package"]
    package = load_package(path, verify_assets=True)
    assert package.manifest.provenance["reference_origin"] == "synthetic"
    assert package.manifest.provenance["design"]["task"] == candidate()["task"]
    assert candidate()["response_contract"] in package.items[0].prompt
    assert package.manifest.scorer["name"] == "synthetic_reference_exact_match"
    assert package.rubric == candidate()["rubric"]
    assert package.manifest.provenance["autonomous_generation"]["evidence"]["policy"]
    benchmark = Benchmark.from_package(path)
    results = benchmark.run(FixtureSolver(), results_dir=tmp_path / "solver", auto_manifest=True)
    assert results.metrics[0].value == 1
    assert generate(tmp_path, model) == report
    assert model.calls == 1


def test_invalid_candidate_is_retained_and_repaired_without_human_edit(tmp_path):
    model = FixtureGenerator([{"bad": "output"}, candidate()])
    report = generate(tmp_path, model)
    assert [row["status"] for row in report["attempts"]] == ["invalid_candidate", "compiled"]
    assert report["calls_total"] == model.calls == 2
    assert report["cost_total"] == pytest.approx(0.04)
    frozen = tmp_path / "generation" / "attempt-1" / "compilation.json"
    assert json.loads(frozen.read_text())[0]["status"] == "invalid_candidate"
    assert generate(tmp_path, model) == report
    assert model.calls == 2


def test_repair_does_not_disclose_ground_truth_or_adapter_metadata(tmp_path):
    item = request()
    item.ground_truth = 'private-reference-sentinel'
    item.metadata['independent_oracle'] = 'private-oracle-sentinel'
    class Capture(FixtureGenerator):
        prompts = []

        def __call__(self, call):
            self.prompts.append(call.item.prompt)
            return super().__call__(call)
    model = Capture([{}, candidate()])
    def adapter(original, payload):
        return compile_candidate(request(original.id), payload)
    report = generate(tmp_path, model, requests=Dataset([item]), compiler=adapter)
    assert report['compiled'] == 1
    assert all('private-reference-sentinel' not in prompt and 'private-oracle-sentinel' not in prompt for prompt in model.prompts)
    repair = json.loads(model.prompts[1])
    assert repair['original_request'] == {'id':item.id, 'prompt':item.prompt}


def test_resume_after_report_interruption_does_not_regenerate_rounds(tmp_path):
    model = FixtureGenerator([{}, candidate()])
    first = generate(tmp_path, model)
    (tmp_path / "generation" / "generation-report.json").unlink()
    resumed = generate(tmp_path, model)
    assert resumed == first
    assert model.calls == 2


def test_budget_is_shared_between_generation_and_repairs(tmp_path):
    model = FixtureGenerator([{}, candidate()], cost=0.08)
    report = generate(tmp_path, model, cfg=config(max_cost=0.12))
    assert report["stop_reason"] == "generation_budget_exhausted"
    assert report["compiled"] == 0
    assert report["calls_total"] == model.calls == 1
    assert report["outcomes"][0]["status"] == "invalid_candidate"


def test_all_assigned_briefs_remain_in_denominator_when_calls_run_out(tmp_path):
    model = FixtureGenerator([candidate()])
    report = generate(
        tmp_path, model, requests=Dataset([request("first"), request("second"), request("third")]),
        cfg=config(max_calls=2), max_repairs=0,
    )
    assert report["requested"] == 3
    assert report["compiled"] == 2
    assert len(report["outcomes"]) == 3
    assert report["calls_total"] == model.calls == 2
    assert report["outcomes"][-1]["status"] == "not_dispatched"


def test_unknown_cost_stops_without_compilation_or_fresh_resume_calls(tmp_path):
    model = FixtureGenerator([candidate()], cost_known=False)
    requests = Dataset([request("first"), request("second")])
    report = generate(tmp_path, model, requests=requests)
    assert report["stop_reason"] == "cost_unknown"
    assert report["compiled"] == 0
    assert report["outcomes"][0]["status"] == "provider_error"
    assert report["outcomes"][1]["status"] == "not_dispatched"
    assert generate(tmp_path, model, requests=requests) == report
    assert model.calls == 1


def test_changed_brief_cannot_reuse_existing_generation_namespace(tmp_path):
    model = FixtureGenerator([candidate()])
    generate(tmp_path, model)
    changed = request()
    changed.prompt += "Changed scope"
    with pytest.raises(ValueError, match="frozen generation inputs differ"):
        generate(tmp_path, model, requests=Dataset([changed]))
    assert model.calls == 1


def test_corrupt_package_fails_before_new_generation(tmp_path):
    model = FixtureGenerator([candidate()])
    generate(tmp_path, model)
    path = tmp_path / "generation" / "packages" / "novel-admin" / "cases.jsonl"
    path.write_text("{}\n")
    with pytest.raises(PackageVerificationError):
        generate(tmp_path, model)
    assert model.calls == 1


def test_valid_package_from_another_generation_cannot_replace_frozen_output(tmp_path):
    model = FixtureGenerator([candidate()])
    generate(tmp_path / "first", model)
    changed = novel_design_request(
        request_id="novel-admin", need="Another scheduling measurement brief.",
        evidence=request().metadata["evidence"], item_count=1,
    )
    generate(tmp_path / "second", model, requests=Dataset([changed]))
    first = tmp_path / "first" / "generation" / "packages" / "novel-admin"
    second = tmp_path / "second" / "generation" / "packages" / "novel-admin"
    shutil.rmtree(first)
    shutil.copytree(second, first)
    with pytest.raises(ValueError, match="completed generation report"):
        generate(tmp_path / "first", model)
    assert model.calls == 2


@pytest.mark.parametrize("output", [
    '{"name":"first","name":"second"}',
    '{"name":NaN}',
    '[]',
])
def test_ambiguous_json_is_retained_as_failure(tmp_path, output):
    model = FixtureGenerator([output])
    report = generate(tmp_path, model, max_repairs=0)
    assert report["compiled"] == 0
    assert report["outcomes"][0]["status"] == "invalid_candidate"


def test_invented_source_reference_is_rejected():
    value = candidate()
    value["items"][0]["source_ids"] = ["invented"]
    with pytest.raises(ValueError, match="supplied evidence"):
        compile_candidate(request(), value)


def test_changed_metadata_cannot_authorize_evidence_absent_from_generator_prompt():
    brief = request()
    brief.metadata["evidence"] = {"unseen": "This was not in the generator prompt."}
    value = candidate()
    value["items"][0]["source_ids"] = ["unseen"]
    with pytest.raises(ValueError, match="request differs from its frozen contract"):
        compile_candidate(brief, value)


@pytest.mark.parametrize("scorer", [
    {"kind": "numeric", "atol": -1},
    {"kind": "exact-match", "case_sensitive": "false"},
    {"kind": "python", "code": "execute me"},
])
def test_invalid_or_executable_scorer_requests_are_rejected(scorer):
    value = candidate()
    value["scorer"] = scorer
    with pytest.raises(ValueError):
        compile_candidate(request(), value)


def test_nonpublic_generation_stops_before_creating_outputs(tmp_path):
    model = FixtureGenerator([candidate()])
    with pytest.raises(ValueError, match="public or synthetic"):
        run_autonomous_generation(
            Dataset([request()]), model=model, config=config(), output_dir=tmp_path / "blocked",
            data_classification="identifiable",
        )
    assert not (tmp_path / "blocked").exists()
    assert model.calls == 0


def test_changed_endpoint_after_interruption_cannot_reset_budget(tmp_path, monkeypatch):
    model = FixtureGenerator([candidate()])
    model.api_base = "https://original.invalid"
    original_write = generation._write_record
    def interrupt_stage(path, payload):
        if path.name == "stage-result.json":
            raise OSError("simulated interruption")
        return original_write(path, payload)
    monkeypatch.setattr(generation, "_write_record", interrupt_stage)
    with pytest.raises(OSError, match="simulated interruption"):
        generate(tmp_path, model)
    assert model.calls == 1
    monkeypatch.setattr(generation, "_write_record", original_write)
    model.api_base = "https://changed.invalid"
    with pytest.raises(ValueError, match="frozen generation inputs differ"):
        generate(tmp_path, model)
    assert model.calls == 1
    model.api_base = "https://original.invalid"
    assert generate(tmp_path, model)["compiled"] == 1
    assert model.calls == 1


def test_stale_stage_cost_cache_cannot_increase_remaining_budget(tmp_path):
    model = FixtureGenerator([{}, candidate()])
    generate(tmp_path, model)
    (tmp_path / "generation" / "generation-report.json").unlink()
    cache_path = tmp_path / "generation" / "attempt-1" / "stage-result.json"
    cache = json.loads(cache_path.read_text())
    cache["summary"]["cost_total"] = 0
    cache_path.write_text(json.dumps(cache))
    with pytest.raises(ValueError, match="integrity receipt mismatch"):
        generate(tmp_path, model)
    assert model.calls == 2


@pytest.mark.parametrize("completed", [False, True])
def test_changed_runner_checkpoint_is_rejected_on_resume(tmp_path, completed):
    model = FixtureGenerator([candidate()])
    generate(tmp_path, model)
    root = tmp_path / "generation"
    if not completed:
        (root / "generation-report.json").unlink()
    stage = root / "attempt-1"
    cache = json.loads((stage / "stage-result.json").read_text())
    ledger = next(path for path in cache["runner_artifacts"] if path.endswith(".calls.jsonl"))
    with (stage / ledger).open("a") as handle:
        handle.write("{}\n")
    with pytest.raises(ValueError, match="checkpoint differs"):
        generate(tmp_path, model)
    assert model.calls == 1


def test_generation_cannot_promote_its_metric_to_clinical_validation():
    value = candidate()
    value["scorer"]["name"] = "clinically_validated_accuracy"
    compiled = compile_candidate(request(), value)
    assert compiled.manifest.scorer["name"] == "synthetic_reference_exact_match"
