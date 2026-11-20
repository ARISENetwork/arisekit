"""Paired generation must preserve the original and isolate both transformations."""

from __future__ import annotations

import hashlib
import json

import pytest

from arisekit.client import ModelCall, ModelResponse
from arisekit.generation.international_adaptation import (
    AdaptationEvidence,
    InternationalAdaptationPlan,
    compile_international_candidate,
    write_international_baseline,
)
from arisekit.runner import RunnerConfig, run
from arisekit.types import BenchmarkItem, RunResult


def _source() -> BenchmarkItem:
    return BenchmarkItem(
        id="booking-1", prompt="Which desk books a routine visit?",
        ground_truth="front desk", metadata={"family_id": "booking", "nested": {"kept": True}},
    )


def _rubric() -> dict:
    return {"criterion": "Identify the front desk.", "acceptable_answer": "front desk"}


def _plan(source=None, rubric=None, **overrides) -> InternationalAdaptationPlan:
    values = dict(
        source=source or _source(), rubric=rubric or _rubric(),
        source_benchmark_id="synthetic-admin", source_benchmark_version="1.0.0",
        source_language="en", source_setting="Source clinic",
        target_language="sv", target_setting="Target clinic",
        evidence=(AdaptationEvidence(
            source_id="local-booking", text="At Target clinic, central booking books routine visits.",
            setting="Target clinic", locator="fixture://local-booking",
        ),),
        scorer_spec={"kind": "exact-match", "primitive": "arisekit.scorer.exact_match",
                     "options": {}},
    )
    values.update(overrides)
    return InternationalAdaptationPlan(**values)


def _payload(cell: str) -> dict:
    texts = {
        "language-only": ("Vilken disk bokar ett rutinbesök?", "receptionen", "Ange receptionen."),
        "system-only": ("Which service books a routine visit?", "central booking", "Identify central booking."),
        "combined": ("Vilken tjänst bokar ett rutinbesök?", "central bokning", "Ange central bokning."),
    }
    prompt, reference, criterion = texts[cell]
    kinds = {"language-only": ["language"], "system-only": ["system"],
             "combined": ["language", "system"]}[cell]
    return {
        "prompt": prompt, "reference": reference,
        "rubric": {"criterion": criterion, "acceptable_answer": reference},
        "changes": [{"field": field, "change_kinds": kinds,
                     "rationale": "Translate the wording and/or apply the supplied booking rule.",
                     "evidence_ids": ["source-item"] if cell == "language-only" else ["local-booking"]}
                    for field in ("prompt", "reference", "rubric")],
    }


def _response(request, payload=None, **overrides):
    values = {"id": request.id, "trial": 0,
              "response": json.dumps(payload if payload is not None else _payload(
                  request.metadata["international_adaptation"]["cell"])),
              "metadata": {"provider_model": "fixture-generator"}}
    values.update(overrides)
    return RunResult(**values)


def test_three_cells_are_independently_rooted_in_the_frozen_source():
    source, rubric = _source(), _rubric()
    original = source.to_dict()
    original_json = json.dumps(original, sort_keys=True, ensure_ascii=False, allow_nan=False,
                               separators=(",", ":"))
    plan = _plan(source, rubric)
    source.prompt = "Mutation after the freeze"
    source.metadata["nested"]["kept"] = False
    rubric["criterion"] = "Mutation after the freeze"

    requests = plan.generation_dataset()
    assert len(requests) == 3
    assert len({request.id for request in requests}) == 3
    assert plan.source_item_sha256 == hashlib.sha256(original_json.encode()).hexdigest()
    observed = {}
    for request in requests:
        packet = json.loads(request.prompt)
        observed[packet["cell"]] = (packet["output_language"], packet["output_setting"])
        assert packet["source_item"] == json.loads(original_json)
        assert packet["source_rubric"] == _rubric()
        assert packet["allowed_evidence_ids"] == ["source-item", "local-booking"]
    assert observed == {"language-only": ("sv", "Source clinic"),
                        "system-only": ("en", "Target clinic"),
                        "combined": ("sv", "Target clinic")}

    compiled = plan.compile_response(requests[0], _response(requests[0]))
    compiled.prompt = "Contamination from an earlier generated cell"
    compiled.metadata["international_adaptation"]["rubric"]["criterion"] = "Changed"
    assert [request.to_dict() for request in plan.generation_dataset()] == [
        request.to_dict() for request in requests]


def test_baseline_preserves_content_and_does_not_share_mutable_objects():
    source = _source()
    plan = _plan(source)
    baseline = plan.baseline()
    assert baseline.prompt == source.prompt
    assert baseline.ground_truth == source.ground_truth
    assert baseline.attachments == source.attachments
    assert baseline.metadata["family_id"] == source.metadata["family_id"]
    record = baseline.metadata["international_adaptation"]
    assert record["cell"] == "baseline"
    assert record["language"] == "en"
    assert record["setting"] == "Source clinic"
    assert record["generation_status"] == "source-baseline"
    assert record["changes"] == []
    assert record["rubric"] == _rubric()
    baseline.metadata["nested"]["kept"] = False
    record["rubric"]["criterion"] = "Changed"
    assert plan.baseline().metadata["nested"]["kept"] is True
    assert plan.baseline().metadata["international_adaptation"]["rubric"] == _rubric()
    with pytest.raises(ValueError, match="only generated adaptation cells"):
        plan.compile_response(baseline, _response(baseline, _payload("combined")))


@pytest.mark.parametrize("index", [0, 1, 2])
def test_compile_preserves_lineage_and_distinguishes_candidate_from_approval(index):
    plan = _plan()
    request = plan.generation_dataset()[index]
    response = _response(request)
    compiled = plan.compile_response(request, response)
    record = compiled.metadata["international_adaptation"]
    assert record["source_item_id"] == "booking-1"
    assert record["source_item_sha256"] == plan.source_item_sha256
    assert record["source_benchmark_version"] == "1.0.0"
    assert record["plan_sha256"] == plan.plan_sha256
    assert record["request_id"] == request.id
    assert record["generation_trial"] == 0
    assert record["generation_metadata"]["provider_model"] == "fixture-generator"
    assert record["generation_status"] == "autonomous-candidate"
    assert record["clinical_validity"] == "not-established"
    assert record["human_edits"] is False
    assert record["source_scorer_spec"]["kind"] == "exact-match"
    assert compiled.ground_truth == json.loads(response.response)["reference"]
    assert compiled.metadata["family_id"] == "booking"
    assert "trial-0" in compiled.id


@pytest.mark.parametrize("change", [
    {"evidence_ids": ["invented-guideline"]},
    {"evidence_ids": ["source-item"]},
    {"change_kinds": ["language"]},
    {"field": "metadata"},
])
def test_system_changes_reject_invented_sources_nonlocal_evidence_and_wrong_fields(change):
    plan = _plan()
    request = plan.generation_dataset()[1]
    payload = _payload("system-only")
    payload["changes"][0].update(change)
    with pytest.raises(ValueError):
        plan.compile_response(request, _response(request, payload))


@pytest.mark.parametrize("mutation", ["omission", "duplicate", "unchanged", "wrong-kind", "approval"])
def test_changed_field_coverage_and_cell_boundaries_are_enforced(mutation):
    plan = _plan()
    request = plan.generation_dataset()[0]
    payload = _payload("language-only")
    if mutation == "omission":
        payload["changes"].pop()
    elif mutation == "duplicate":
        payload["changes"].append(payload["changes"][0])
    elif mutation == "unchanged":
        payload["reference"] = _source().ground_truth
    elif mutation == "wrong-kind":
        payload["changes"][0]["change_kinds"] = ["system"]
    else:
        payload["clinically_approved"] = True
    with pytest.raises(ValueError):
        plan.compile_response(request, _response(request, payload))


def test_unchanged_generation_is_a_failure_not_an_adapted_baseline():
    plan = _plan()
    request = plan.generation_dataset()[0]
    payload = {"prompt": _source().prompt, "reference": _source().ground_truth,
               "rubric": _rubric(), "changes": []}
    with pytest.raises(ValueError, match="no adaptation"):
        plan.compile_response(request, _response(request, payload))


def test_combined_cell_requires_both_transformations():
    plan = _plan()
    request = plan.generation_dataset()[2]
    payload = _payload("combined")
    for change in payload["changes"]:
        change["change_kinds"] = ["language"]
    with pytest.raises(ValueError, match="every requested transformation"):
        plan.compile_response(request, _response(request, payload))


def test_compiler_rejects_foreign_or_changed_request_and_errored_response():
    plan = _plan()
    request = plan.generation_dataset()[0]
    with pytest.raises(ValueError, match="response ID"):
        plan.compile_response(request, _response(request, id="another-request"))
    with pytest.raises(ValueError, match="errored"):
        plan.compile_response(request, _response(request, error="interrupted"))
    with pytest.raises(ValueError, match="exact frozen plan"):
        _plan(target_setting="Another clinic").compile_response(request, _response(request))
    response = _response(request)
    request.prompt += "Use the preceding cell instead."
    with pytest.raises(ValueError, match="exact frozen plan"):
        plan.compile_response(request, response)


def test_changed_evidence_or_rubric_gets_a_new_request_identity():
    original = _plan()
    revised = _plan(evidence=(AdaptationEvidence("local-booking", "Revised local rule.",
                                               "Target clinic"),))
    revised_rubric = _plan(rubric={"criterion": "An amended criterion."})
    assert len({plan.generation_dataset()[0].id for plan in
                (original, revised, revised_rubric)}) == 3


def test_duplicate_json_keys_and_nonfinite_values_are_rejected():
    plan = _plan()
    request = plan.generation_dataset()[0]
    with pytest.raises(ValueError, match="duplicate JSON key"):
        plan.compile_response(request, _response(request, response='{"prompt":"a","prompt":"b"}'))
    payload = _payload("language-only")
    payload["rubric"]["weight"] = float("nan")
    with pytest.raises(ValueError, match="not canonical JSON"):
        plan.compile_response(request, _response(request, payload))


def test_existing_runner_generates_three_cells_and_resumes_without_calls(tmp_path):
    class FixtureClient:
        model = "offline-adaptation-fixture"

        def __init__(self):
            self.calls = 0

        def __call__(self, call: ModelCall) -> ModelResponse:
            self.calls += 1
            packet = json.loads(call.item.prompt)
            assert packet["source_item"] == _source().to_dict()
            assert "Do not use another generated cell" in call.system_prompt
            return ModelResponse(text=json.dumps(_payload(packet["cell"])), cost=0.0)

    plan = _plan()
    dataset = plan.generation_dataset()
    client = FixtureClient()
    config = RunnerConfig(results_dir=tmp_path, max_calls=3, max_retries=1)
    responses, summary = run(dataset, model=client, benchmark_name=dataset.name, config=config)
    assert summary.completed == 3
    assert summary.errored == 0
    assert client.calls == 3
    by_id = {request.id: request for request in dataset}
    candidates = [plan.compile_response(by_id[response.id], response) for response in responses]
    assert {item.metadata["international_adaptation"]["cell"] for item in candidates} == {
        "language-only", "system-only", "combined"}
    _, resumed = run(dataset, model=client, benchmark_name=dataset.name, config=config)
    assert resumed.skipped == 3
    assert client.calls == 3


@pytest.mark.parametrize("source_id", ["booking-1", "urn:example:admin/case-1"])
def test_controller_exports_three_scorable_candidates_and_separate_unchanged_baseline(tmp_path, source_id):
    from arisekit.generation.autonomous_generation import run_autonomous_generation
    from arisekit.package import load_package, scorer_from_manifest

    class FixtureClient:
        model = "offline-international-controller"

        def __init__(self):
            self.calls = 0

        def __call__(self, call: ModelCall) -> ModelResponse:
            self.calls += 1
            packet = json.loads(call.item.prompt)
            assert packet["source_item"] == source.to_dict()
            return ModelResponse(text=json.dumps(_payload(packet["cell"])), cost=0.01,
                                 provider_model=self.model)

    source = _source()
    source.id = source_id
    plan = _plan(source=source)
    dataset = plan.generation_dataset()
    recovered = InternationalAdaptationPlan.from_request(dataset[0])
    assert recovered.source_item_sha256 == plan.source_item_sha256
    baseline_path = write_international_baseline(dataset[0], tmp_path / "source-baseline")
    baseline = load_package(baseline_path, verify_assets=True)
    assert baseline.items[0].prompt == _source().prompt
    assert baseline.items[0].ground_truth == _source().ground_truth
    assert baseline.rubric == _rubric()
    assert baseline.manifest.provenance["international_adaptation"]["generation_status"] == "source-baseline"
    client = FixtureClient()
    config = RunnerConfig(max_calls=3, max_cost=0.3, max_cost_per_call=0.05,
                          require_known_cost=True, max_retries=1)
    output = tmp_path / "generated"
    report = run_autonomous_generation(
        dataset, model=client, config=config, output_dir=output,
        data_classification="synthetic", max_repairs=0, compiler=compile_international_candidate,
    )
    assert report["compiled"] == 3, report
    assert report["calls_total"] == 3
    assert client.calls == 3
    for outcome in report["outcomes"]:
        package = load_package(output / outcome["package"], verify_assets=True)
        assert package.manifest.scorer == {"kind": "exact-match"}
        item = package.items[0]
        assert package.rubric == item.metadata["international_adaptation"]["rubric"]
        scorer = scorer_from_manifest(package.manifest)
        assert scorer.score_item(item, [RunResult(id=item.id, trial=0, response=item.ground_truth)])[0].value == 1.0
        assert scorer.score_item(item, [RunResult(id=item.id, trial=0, response="wrong desk")])[0].value == 0.0
        assert package.manifest.provenance["source_packet"]["source_item"] == source.to_dict()
    resumed = run_autonomous_generation(
        dataset, model=client, config=config, output_dir=output,
        data_classification="synthetic", max_repairs=0, compiler=compile_international_candidate,
    )
    assert resumed["compiled"] == 3
    assert client.calls == 3


@pytest.mark.parametrize("spec", [None, {"kind": "semantic-clinical-review",
                                       "primitive": "external.clinical_review", "options": {}}])
def test_portable_compiler_names_missing_or_semantic_scorer_gap(spec):
    request = _plan(scorer_spec=spec).generation_dataset()[0]
    with pytest.raises(ValueError, match="international scorer gap"):
        compile_international_candidate(request, _payload("language-only"))


def test_portable_compiler_preserves_fixed_choices_and_rejects_unbound_translation():
    spec = {"kind": "choice", "primitive": "arisekit.scorer.choice",
            "options": {"choices": ["front desk", "central booking"]}}
    plan = _plan(scorer_spec=spec)
    system_request = plan.generation_dataset()[1]
    candidate = compile_international_candidate(system_request, _payload("system-only"))
    assert candidate.manifest.scorer == {"kind": "choice", "choices": spec["options"]["choices"]}
    with pytest.raises(ValueError, match="outside the unchanged source choices"):
        compile_international_candidate(plan.generation_dataset()[0], _payload("language-only"))


def test_request_reconstruction_rejects_modified_frozen_source():
    request = _plan().generation_dataset()[0]
    packet = json.loads(request.prompt)
    packet["source_item"]["ground_truth"] = "a different reference"
    request.prompt = json.dumps(packet)
    with pytest.raises(ValueError, match="exact frozen plan"):
        compile_international_candidate(request, _payload("language-only"))


def test_portable_compiler_rejects_ambiguous_normalized_source_choices():
    spec = {"kind": "choice", "primitive": "arisekit.scorer.choice",
            "options": {"choices": ["front desk", "FRONT DESK", "central booking"]}}
    request = _plan(scorer_spec=spec).generation_dataset()[1]
    with pytest.raises(ValueError, match="source choices collapse"):
        compile_international_candidate(request, _payload("system-only"))
