"""Needs-derived requests retain clinical scope and actual scoring contracts."""

from copy import deepcopy
import hashlib
import json

import pytest

from arisekit.benchmark import Benchmark
from arisekit.generation.benchmark_emulation import (
    compile_emulation_candidate, emulation_generation_request, emulation_profile,
)
from arisekit.generation.autonomous_generation import run_autonomous_generation
from arisekit.client import ModelResponse
from arisekit.dataset import Dataset
from arisekit.package import load_package
from arisekit.runner import RunnerConfig
from arisekit.types import RunResult
from test_specialty_adapters import sct_payload, cpc_payload
from test_autonomous_fhir import candidate as fhir_payload


NEED = """# Need statement

## Problem
Measure reasoning about a fictional pregnancy-related assessment.

## Population
Women's health, outpatient care.

## Outcomes
Appropriate diagnostic reasoning under uncertainty.

## Exclusions
Do not include inpatient or emergency scenarios.
"""


def request(family="SCT", **kwargs):
    return emulation_generation_request(
        request_id="womens-health", family=family, specialty="women's health",
        need_statement=NEED, evidence={"workflow": "A fictional evidence rule."},
        case_count=1, **kwargs,
    )


def payload(family):
    value = {"sct": sct_payload, "cpc": cpc_payload, "medagentbench": fhir_payload}[family]()
    if family in {"sct", "cpc"}:
        value["specialty"] = "women's health"
        for row in value["items" if family == "sct" else "cases"]:
            row["source_ids"] = ["workflow"]
    return value


def test_generated_sct_rejects_observed_arithmetic_error_without_changing_legacy_loader():
    from arisekit.generation.specialty_adapters import compile_sct_items
    value = payload("sct")
    row = value["items"][0]
    row.update(scenario="A 59-year-old woman has pneumonia.",
        hypothesis="Consider admission.",
        new_evidence="CRB65 score of 1 (age 59, RR 28, BP 110/70, no confusion).")
    with pytest.raises(ValueError, match="sum to 0, not 1"):
        compile_emulation_candidate(request(), value)
    historical = deepcopy(value)
    historical["items"][0].pop("source_ids")
    assert compile_sct_items(historical)
    row["new_evidence"] = row["new_evidence"].replace("score of 1", "score of 0")
    compiled = compile_emulation_candidate(request(), value)
    assert compiled.items[0].metadata["numeric_consistency_audit"]["status"] == "consistent"


@pytest.mark.parametrize("family", ["SCT", "CPC-Bench", "MedAgentBench"])
def test_full_need_reaches_generation_and_survives_compilation(family):
    item = request(family)
    prompt = json.loads(item.prompt)
    assert prompt["emulation"]["need_statement"] == NEED
    assert "outpatient care" in item.prompt
    assert "Do not include inpatient" in item.prompt
    compiled = compile_emulation_candidate(item, payload(emulation_profile(family)["family"]))
    context = compiled.manifest.provenance["emulation"]
    assert context["need_statement"] == NEED
    assert context["need_statement_sha256"] == hashlib.sha256(NEED.encode()).hexdigest()
    assert context["case_count"] == 1
    assert compiled.items
    assert all(item.metadata["source_ids"] == ["workflow"] for item in compiled.items)


@pytest.mark.parametrize("mutate", [
    lambda item: item.metadata["emulation"].update(need_statement=NEED + "Changed scope"),
    lambda item: item.metadata["emulation"].update(case_count=2),
    lambda item: item.metadata["evidence"].update(invented="Unseen source"),
    lambda item: item.metadata["emulation"]["profile"].update(scoring="Different judge"),
])
def test_changed_needs_or_scoring_cannot_bypass_the_frozen_prompt(mutate):
    item = request()
    mutate(item)
    with pytest.raises(ValueError, match="frozen needs-analysis contract"):
        compile_emulation_candidate(item, payload("sct"))


@pytest.mark.parametrize("family", ["SCT", "CPC"])
def test_independent_case_count_is_enforced(family):
    candidate = payload(emulation_profile(family)["family"])
    field = "items" if family == "SCT" else "cases"
    candidate[field].append(deepcopy(candidate[field][0]))
    with pytest.raises(ValueError, match="independent case count"):
        compile_emulation_candidate(request(family), candidate)


def test_sct_emulation_does_not_claim_generated_expert_ratings():
    candidate = payload("sct")
    candidate["reference_origin"] = "expert"
    with pytest.raises(ValueError, match="expert"):
        compile_emulation_candidate(request(), candidate)


def test_reference_update_explanation_is_hidden_and_bound_to_a_histogram_mode():
    candidate = payload("sct")
    candidate["items"][0]["reference_assessment"] = {
        "explanation": "A fictional new finding increases support relative to the baseline.", "modal_rating": 1}
    compiled = compile_emulation_candidate(request(), candidate)
    item = compiled.items[0]
    assert item.metadata["reference_assessment"]["modal_rating"] == 1
    assert "fictional new finding" not in item.prompt
    candidate["items"][0]["reference_assessment"]["modal_rating"] = -2
    with pytest.raises(ValueError, match="contradict the stated modal update"):
        compile_emulation_candidate(request(), candidate)


@pytest.mark.parametrize("family", ["ReXrank", "CPC-Bench management", "Unrecognized benchmark"])
def test_missing_family_adapters_fail_before_generation(family):
    with pytest.raises(ValueError, match="adapter|compiler|requires"):
        request(family)


def test_needs_request_generates_scores_and_resumes_without_new_calls(tmp_path):
    class Model:
        model = "fixture/emulation"
        calls = 0

        def __call__(self, call):
            self.calls += 1
            assert NEED in json.loads(call.item.prompt)["emulation"]["need_statement"]
            return ModelResponse(text=json.dumps(payload("sct")), cost=.01, provider_model=self.model)

    model = Model()
    cfg = RunnerConfig(max_cost=.2, max_cost_per_call=.1, max_calls=2, max_retries=1)
    kwargs = dict(model=model, config=cfg, output_dir=tmp_path / "generation",
                  data_classification="synthetic")
    report = run_autonomous_generation(Dataset([request()]), **kwargs)
    assert report["compiled"] == 1
    package_path = tmp_path / "generation" / report["outcomes"][0]["package"]
    package = load_package(package_path, verify_assets=True)
    assert package.manifest.provenance["emulation"]["need_statement"] == NEED
    benchmark = Benchmark.from_package(package_path)
    scores = benchmark.scorer.score_item(package.items[0], [RunResult(id=package.items[0].id, trial=1, response="1")])
    assert scores[0].name == "synthetic_concordance"
    assert scores[0].value == 1
    assert run_autonomous_generation(Dataset([request()]), **kwargs) == report
    assert model.calls == 1
    changed = emulation_generation_request(
        request_id="womens-health", family="SCT", specialty="women's health",
        need_statement=NEED + "Different setting.", evidence={"workflow": "A fictional evidence rule."}, case_count=1,
    )
    with pytest.raises(ValueError, match="frozen generation inputs differ"):
        run_autonomous_generation(Dataset([changed]), **kwargs)
    assert model.calls == 1


@pytest.mark.parametrize("refs", [None, [], ["invented"], ["workflow", "workflow"]])
def test_case_source_lineage_cannot_be_missing_or_fabricated(refs):
    candidate = payload("sct")
    candidate["items"][0]["source_ids"] = refs
    with pytest.raises(ValueError, match="supplied source_ids"):
        compile_emulation_candidate(request(), candidate)
