"""Deterministic scoring and source/response boundaries for specialty candidates."""

import copy
import json

import pytest

from arisekit.client import ModelResponse
from arisekit.benchmark import Benchmark
from arisekit.package import BenchmarkManifest, write_package
from arisekit.scorer import identify_scorer
from arisekit.generation.specialty_adapters import (
    SPECIALTY_CANDIDATE_SCHEMA,
    CPCRankedDifferentialScorer,
    SCTConcordanceScorer,
    build_specialty_benchmark,
    compile_cpc_items,
    compile_sct_items,
    normalize_diagnosis,
    specialty_generation_contract,
    specialty_scorer_from_spec,
)
from arisekit.types import RunResult


def sct_payload():
    return {
        "schema_version": SPECIALTY_CANDIDATE_SCHEMA,
        "kind": "sct",
        "name": "specialty-sct",
        "specialty": "cardiology",
        "reference_origin": "synthetic",
        "items": [{
            "id": "scenario-1",
            "scenario": "An uncertain clinical presentation.",
            "hypothesis": "The proposed diagnosis explains the presentation.",
            "new_evidence": "An additional finding becomes available.",
            "reference_counts": {"-2": 0, "-1": 1, "0": 2, "1": 4, "2": 4},
            "expert_ratings": [],
        }],
    }


def cpc_payload():
    return {
        "schema_version": SPECIALTY_CANDIDATE_SCHEMA,
        "kind": "cpc",
        "name": "specialty-cpc",
        "specialty": "internal-medicine",
        "reference_origin": "synthetic",
        "diagnoses": [
            {"id": "pe", "label": "Pulmonary embolism", "aliases": ["Pulmonary thromboembolism"]},
            {"id": "pneumonia", "label": "Pneumonia", "aliases": []},
        ],
        "cases": [{
            "id": "case-1",
            "presentation": "Initial presentation text.",
            "final_diagnosis_id": "pe",
            "expert_reviews": [],
            "stages": [
                {"id": "initial", "evidence": "First disclosed findings.",
                 "reference_differential": [{"diagnosis_id": "pneumonia", "evidence_ids": ["presentation", "initial"]}]},
                {"id": "imaging", "evidence": "Later imaging findings.",
                 "reference_differential": [{"diagnosis_id": "pe", "evidence_ids": ["imaging"]}]},
            ],
        }],
    }


def results(item, responses):
    return [RunResult(id=item.id, trial=i, response=response) for i, response in enumerate(responses)]


def by_name(metrics):
    return {metric.name: metric for metric in metrics}


def test_sct_modal_ties_partial_credit_and_failures_keep_denominators():
    item = compile_sct_items(sct_payload())[0]
    responses = results(item, ["+1", " 2\n", "0", "-1", "-2", "Answer: 1", "+1"])
    responses[-1].error = "transport failed"
    metrics = by_name(SCTConcordanceScorer().score_item(item, responses))
    assert metrics["synthetic_concordance"].value == pytest.approx((1 + 1 + .5 + .25) / 7)
    assert metrics["invalid_response_rate"].value == pytest.approx(1 / 7)
    assert metrics["execution_error_rate"].value == pytest.approx(1 / 7)
    assert all(metric.n == 7 and metric.category == "cardiology" for metric in metrics.values())
    assert "expert" not in " ".join(metrics)


@pytest.mark.parametrize("response", ["1.0", "1 or 2", "10", "-0", "+0", "True", "{\"rating\":1}", 1, True, None])
def test_sct_rejects_nonordinal_responses(response):
    item = compile_sct_items(sct_payload())[0]
    metrics = by_name(SCTConcordanceScorer().score_item(item, results(item, [response])))
    assert metrics["synthetic_concordance"].value == 0
    assert metrics["invalid_response_rate"].value == 1


@pytest.mark.parametrize("counts", [
    {"-2": 0, "-1": 0, "0": 0, "1": 0, "2": 0},
    {"-2": 0, "-1": 0, "0": 0, "1": -1, "2": 1},
    {"-2": 0, "-1": 0, "0": 0, "1": True, "2": 1},
    {"-2": 0, "-1": 0, "0": 0, "1": .5, "2": 1},
    {"-2": 0, "-1": 0, "0": 0, "1": float("nan"), "2": 1},
    {"-2": 0, "-1": 0, "0": 0, "+1": 1, "2": 1},
])
def test_sct_refuses_malformed_reference_histograms(counts):
    payload = sct_payload()
    payload["items"][0]["reference_counts"] = counts
    with pytest.raises(ValueError):
        compile_sct_items(payload)


def test_expert_sct_requires_explicit_import_and_exact_rater_evidence():
    payload = sct_payload()
    payload["reference_origin"] = "expert"
    row = payload["items"][0]
    row["reference_counts"] = {"-2": 0, "-1": 0, "0": 1, "1": 2, "2": 0}
    row["expert_ratings"] = [
        {"reviewer_id": "r1", "rating": 0, "evidence_ref": "ratings.csv#row-1"},
        {"reviewer_id": "r2", "rating": 1, "evidence_ref": "ratings.csv#row-2"},
        {"reviewer_id": "r3", "rating": 1, "evidence_ref": "ratings.csv#row-3"},
    ]
    with pytest.raises(ValueError, match="allow_expert_references"):
        build_specialty_benchmark(payload)
    benchmark = build_specialty_benchmark(payload, allow_expert_references=True)
    item = benchmark.dataset[0]
    metrics = by_name(benchmark.scorer.score_item(item, results(item, ["0"])))
    assert metrics["expert_concordance"].value == .5
    assert "synthetic_concordance" not in metrics
    row["reference_counts"]["1"] = 3
    with pytest.raises(ValueError, match="do not match"):
        compile_sct_items(payload, allow_expert_references=True)
    row["reference_counts"]["1"] = 2
    row["expert_ratings"][1]["reviewer_id"] = "r1"
    with pytest.raises(ValueError, match="duplicate reviewer"):
        compile_sct_items(payload, allow_expert_references=True)


def test_synthetic_origin_cannot_be_promoted_by_fabricated_expert_fields():
    payload = sct_payload()
    payload["items"][0]["expert_ratings"] = [{"reviewer_id": "r", "rating": 1, "evidence_ref": "x"}]
    with pytest.raises(ValueError, match="cannot carry expert"):
        compile_sct_items(payload)
    payload = cpc_payload()
    payload["cases"][0]["expert_reviews"] = [{"reviewer_id": "r", "diagnosis_id": "pe", "evidence_ref": "x"}]
    with pytest.raises(ValueError, match="cannot carry expert"):
        compile_cpc_items(payload)


def test_cpc_compiler_preserves_stages_without_disclosing_later_evidence_or_references():
    payload = cpc_payload()
    first, second = compile_cpc_items(payload)
    assert first.id == "case-1::initial"
    assert second.id == "case-1::imaging"
    assert "Later imaging findings" not in first.prompt
    assert "First disclosed findings" in second.prompt
    assert "Later imaging findings" in second.prompt
    assert "Pulmonary embolism" not in first.prompt
    assert "Pneumonia" not in first.prompt
    assert second.metadata["previous_item_id"] == first.id
    assert first.metadata["disclosed_evidence_ids"] == ["presentation", "initial"]
    assert second.metadata["disclosed_evidence_ids"] == ["presentation", "initial", "imaging"]
    assert first.metadata["independent_unit"] == "case"
    assert first.metadata["category"] != second.metadata["category"]
    assert second.ground_truth["reference_differential"] == payload["cases"][0]["stages"][1]["reference_differential"]
    payload["diagnoses"][0]["label"] = "Changed after compilation"
    assert second.ground_truth["diagnoses"][0]["label"] == "Pulmonary embolism"


@pytest.mark.parametrize("bad_link", ["imaging", "not-a-stage"])
def test_cpc_refuses_future_or_unknown_evidence_links(bad_link):
    payload = cpc_payload()
    payload["cases"][0]["stages"][0]["reference_differential"][0]["evidence_ids"] = [bad_link]
    with pytest.raises(ValueError, match="unknown or future evidence"):
        compile_cpc_items(payload)


@pytest.mark.parametrize("change", ["stage", "case", "diagnosis", "final", "alias"])
def test_cpc_rejects_ambiguous_ids_and_reference_vocabularies(change):
    payload = cpc_payload()
    if change == "stage":
        payload["cases"][0]["stages"][1]["id"] = "initial"
    elif change == "case":
        payload["cases"].append(copy.deepcopy(payload["cases"][0]))
    elif change == "diagnosis":
        payload["diagnoses"].append(copy.deepcopy(payload["diagnoses"][0]))
    elif change == "final":
        payload["cases"][0]["final_diagnosis_id"] = "missing"
    else:
        payload["diagnoses"][1]["aliases"] = ["  PULMONARY   EMBOLISM "]
    with pytest.raises(ValueError):
        compile_cpc_items(payload)


def test_cpc_rank_and_top_k_use_exact_aliases_and_account_for_unknown_diagnoses():
    item = compile_cpc_items(cpc_payload())[1]
    responses = results(item, [
        '{"diagnoses":["  PULMONARY   THROMBOEMBOLISM "]}',
        '{"diagnoses":["Pneumonia","pulmonary embolism"]}',
        '{"diagnoses":["Other condition","Pneumonia","PE"]}',
        '{"diagnoses":["not pulmonary embolism"]}',
        '{"diagnoses":["Pulmonary embolism"]}',
    ])
    responses[-1].error = "timeout"
    metrics = by_name(CPCRankedDifferentialScorer().score_item(item, responses))
    assert metrics["synthetic_reciprocal_rank"].value == pytest.approx((1 + .5 + 1 / 3) / 5)
    assert metrics["synthetic_ddx_at_1"].value == .2
    assert metrics["synthetic_ddx_at_3"].value == .6
    assert metrics["invalid_response_rate"].value == 0
    assert metrics["execution_error_rate"].value == .2
    assert all(metric.n == 5 and metric.category == "internal-medicine/stage-2" for metric in metrics.values())
    assert normalize_diagnosis("ＰＥ") == "pe"


@pytest.mark.parametrize("response", [
    "Pulmonary embolism", "```json\n{\"diagnoses\":[\"pe\"]}\n```",
    '{"diagnoses":["pe"],"reason":"explanation"}',
    '{"diagnoses":["pe","pulmonary embolism"]}',
    '{"diagnoses":["pe"],"diagnoses":["pe"]}',
    '{"diagnoses":[]}', '{"diagnoses":[1]}', '{"diagnoses":[NaN]}',
    json.dumps({"diagnoses": [f"unknown-{i}" for i in range(11)]}),
])
def test_cpc_invalid_responses_score_zero_without_substring_recovery(response):
    item = compile_cpc_items(cpc_payload())[0]
    metrics = by_name(CPCRankedDifferentialScorer().score_item(item, results(item, [response])))
    assert metrics["synthetic_reciprocal_rank"].value == 0
    assert metrics["synthetic_ddx_at_10"].value == 0
    assert metrics["invalid_response_rate"].value == 1


def test_cpc_expert_origin_requires_diagnosis_bound_review_evidence():
    payload = cpc_payload()
    payload["reference_origin"] = "expert"
    with pytest.raises(ValueError, match="expert_reviews"):
        compile_cpc_items(payload, allow_expert_references=True)
    payload["cases"][0]["expert_reviews"] = [{"reviewer_id": "r1", "diagnosis_id": "pe", "evidence_ref": "review.csv#case-1"}]
    item = compile_cpc_items(payload, allow_expert_references=True)[0]
    metrics = by_name(CPCRankedDifferentialScorer().score_item(item, results(item, ['{"diagnoses":["pe"]}'])))
    assert metrics["expert_ddx_at_1"].value == 1
    payload["cases"][0]["expert_reviews"][0]["diagnosis_id"] = "pneumonia"
    with pytest.raises(ValueError, match="does not support"):
        compile_cpc_items(payload, allow_expert_references=True)


@pytest.mark.parametrize("payload_factory", [sct_payload, cpc_payload])
def test_response_identity_and_reference_tampering_fail_closed(payload_factory):
    benchmark = build_specialty_benchmark(payload_factory())
    item = benchmark.dataset[0]
    with pytest.raises(ValueError, match="item/trial identity"):
        benchmark.scorer.score_item(item, [RunResult(id="other", trial=0, response="1")])
    with pytest.raises(ValueError, match="duplicate response trial"):
        benchmark.scorer.score_item(item, results(item, ["1"]) * 2)
    empty = benchmark.scorer.score_item(item, [])
    assert all(metric.n == 0 and metric.value == 0 for metric in empty)
    item.metadata["reference_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="compiled binding"):
        benchmark.scorer.score_item(item, results(item, ["1"]))


@pytest.mark.parametrize("kind,payload_factory", [("sct", sct_payload), ("cpc", cpc_payload)])
def test_generation_contract_and_local_benchmark_run(kind, payload_factory, tmp_path):
    import jsonschema

    contract = specialty_generation_contract(kind)
    jsonschema.Draft202012Validator.check_schema(contract["response_schema"])
    jsonschema.validate(payload_factory(), contract["response_schema"])
    expert = payload_factory()
    expert["reference_origin"] = "expert"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(expert, contract["response_schema"])
    benchmark = build_specialty_benchmark(payload_factory())
    assert identify_scorer(benchmark.scorer).configuration["kind"].startswith(kind)
    calls = []

    class LocalClient:
        model = f"local-{kind}-fixture"

        def __call__(self, call):
            calls.append(call.item.id)
            return ModelResponse(text="+1" if kind == "sct" else '{"diagnoses":["pe"]}', cost=0)

    first = benchmark.run(LocalClient(), results_dir=tmp_path)
    assert first.summary.completed == len(benchmark.dataset)
    assert all(metric.value == 1 for metric in first.metrics if metric.name.startswith("synthetic_"))
    count = len(calls)
    benchmark.run(LocalClient(), results_dir=tmp_path)
    assert len(calls) == count


def test_unknown_candidate_fields_cannot_introduce_approval_claims():
    payload = sct_payload()
    payload["clinically_validated"] = True
    with pytest.raises(ValueError, match="exactly"):
        build_specialty_benchmark(payload)


@pytest.mark.parametrize("scorer", [SCTConcordanceScorer(), CPCRankedDifferentialScorer(top_k=(1, 2), max_diagnoses=5)])
def test_scorer_spec_roundtrip_and_invariant_tampering(scorer):
    spec = json.loads(json.dumps(scorer.configuration()))
    restored = specialty_scorer_from_spec(spec)
    assert identify_scorer(restored).digest == identify_scorer(scorer).digest
    spec["normalization"] = "substring-match"
    with pytest.raises(ValueError, match="canonical scoring semantics"):
        specialty_scorer_from_spec(spec)


@pytest.mark.parametrize("top_k", [[1, True], [2, 1], [1, 1], [1, 11], "1,3,10"])
def test_scorer_spec_rejects_malformed_rank_cutoffs(top_k):
    spec = dict(CPCRankedDifferentialScorer().configuration())
    spec["top_k"] = top_k
    with pytest.raises(ValueError):
        specialty_scorer_from_spec(spec)


@pytest.mark.parametrize("payload_factory", [sct_payload, cpc_payload])
def test_specialty_package_roundtrip_preserves_scorer_references_and_stages(payload_factory, tmp_path):
    benchmark = build_specialty_benchmark(payload_factory())
    manifest = BenchmarkManifest.from_dict({
        "id": benchmark.name, "name": benchmark.name, "version": "0.1.0", "modality": "text",
        "scorer": dict(benchmark.scorer.configuration()),
    })
    root = write_package(tmp_path / "package", manifest=manifest, items=benchmark.dataset, write_asset_manifest=True)
    loaded = Benchmark.from_package(root)
    assert loaded.scorer.configuration() == benchmark.scorer.configuration()
    assert [item.to_dict() for item in loaded.dataset] == [item.to_dict() for item in benchmark.dataset]
    item = loaded.dataset[0]
    answer = "+1" if payload_factory is sct_payload else '{"diagnoses":["pe"]}'
    metrics = by_name(loaded.scorer.score_item(item, results(item, [answer])))
    assert all(metric.value == 1 for name, metric in metrics.items() if name.startswith("synthetic_"))
