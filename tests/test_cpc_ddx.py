from copy import deepcopy
import json

import pytest

from arisekit.benchmark import Benchmark
from arisekit.client import ModelResponse
from arisekit.generation.cpc_ddx import compile_candidate, evaluate, generation_request, judgment_metrics, original_cpc, ranked_diagnoses
from arisekit.common.frozen_records import read_record
from arisekit.runner import RunnerConfig
from arisekit.scorer import DeferredScorer


@pytest.mark.parametrize("value,expected", [
    ({"present": "yes", "matching_diagnosis": "A synonym", "rank": "1"}, [1., 1., 1.]),
    ({"present": "YES", "rank": None}, [0., 0., 1.]),
    ({"present": "yes", "rank": "not a number"}, [0., 0., 1.]),
    ({"present": "no", "rank": 1}, [0., 0., 0.]),
    ({"present": "yes", "rank": 0}, [0., 1., 1.]),
])
def test_native_judgment_arithmetic_preserves_original_rank_behavior(value, expected):
    from arisekit.generation.cpc_ddx import native_judgment_metrics
    assert list(native_judgment_metrics(value).values()) == expected


def test_native_policy_reports_label_format_separately_and_keeps_strict_default():
    from arisekit.generation.cpc_ddx import JudgmentScorer
    from arisekit.types import BenchmarkItem, RunResult
    item = BenchmarkItem(id="one", prompt="Fictional", metadata={"differential_size": 1, "diagnoses": ["Full provided label"]})
    response = RunResult(id="one", trial=1, response=json.dumps({"present": "yes", "matching_diagnosis": "An alternative label", "rank": 1}))
    native = {r.name: r.value for r in JudgmentScorer("mast-native").score_item(item, [response])}
    strict = {r.name: r.value for r in JudgmentScorer().score_item(item, [response])}
    assert native["top1"] == 1 and native["strict_judgment_format_violation_rate"] == 1
    assert strict["invalid_judgment_rate"] == 1
    assert JudgmentScorer("mast-native").configuration()["judge_response_policy"] == "mast-native"
    assert "judge_response_policy" not in JudgmentScorer().configuration()


def baseline(count=11):
    return [{"id": f"original-{i}", "age_years": 40, "scenario": f"HELD OUT original presentation {i}", "final_diagnosis": "Source diagnosis",
        "source": "Fictional source", "source_id": str(i), "source_item_sha256": "a" * 64,
        "source_reference_sha256": "b" * 64} for i in range(count)]


def candidate():
    return {"schema_version": "arisekit.cpc-ddx.v4", "name": "candidate", "reference_origin": "synthetic",
        "cases": [{"id": f"new-{i}", "age_years": 40, "presentation": f"An independent fictional diagnostic problem {i}",
            "final_diagnosis": "Synthetic diagnosis", "reference_explanation": "Hidden explanation of the evidence",
            "synthetic_confirmation": "Hidden synthetic test and confirming result after presentation",
            "source_ids": ["guideline"]} for i in range(2)]}


@pytest.mark.parametrize("label", [
    "NSTEMI with multivessel coronary artery disease requiring coronary angiography within 72 hours",
    "Pulmonary embolism requiring anticoagulation",
])
def test_new_diagnostic_references_exclude_management_recommendations(label):
    request = generation_request(specialty="cardiology", need_statement="A diagnostic reasoning task",
        evidence={"guideline": "Synthetic evidence"}, case_count=2)
    value = candidate()
    value["cases"][0]["final_diagnosis"] = label
    with pytest.raises(ValueError, match="condition only"):
        compile_candidate(request, value)
    value["cases"][0]["final_diagnosis"] = "Non-ST-elevation myocardial infarction"
    assert len(compile_candidate(request, value).items) == 2


def test_multiple_sources_survive_canonical_frozen_request_roundtrip():
    from arisekit.common.jsonio import canonical_json as canonical
    from arisekit.types import BenchmarkItem
    evidence = {"zeta": "Evidence Z", "alpha": "Evidence A"}
    request = generation_request(specialty="cardiology", need_statement="A diagnostic reasoning task",
        evidence=evidence, case_count=2)
    saved = BenchmarkItem.from_dict(json.loads(canonical(request.to_dict())))
    value = candidate()
    for row in value["cases"]:
        row["source_ids"] = ["zeta", "alpha"]
    assert len(compile_candidate(saved, value).items) == 2
    assert request.to_dict() == saved.to_dict()
    assert list(evidence) == ["zeta", "alpha"]


def test_authoring_examples_survive_persistence_without_entering_solver_prompts():
    from arisekit.common.jsonio import canonical_json as canonical
    from arisekit.types import BenchmarkItem
    examples = [{"source_case_id": "source-1", "presentation": "PRIVATE EXAMPLE presentation",
        "published_diagnosis": "PRIVATE EXAMPLE diagnosis"}]
    request = generation_request(specialty="cardiology", need_statement="Diagnostic reasoning",
        evidence={"zeta": "Z", "alpha": "A"}, case_count=2, authoring_examples=examples)
    saved = BenchmarkItem.from_dict(json.loads(canonical(request.to_dict())))
    value = candidate()
    for row in value["cases"]:
        row["source_ids"] = ["authoring_example_1"]
    compiled = compile_candidate(saved, value)
    assert "PRIVATE EXAMPLE" in saved.prompt
    assert all("PRIVATE EXAMPLE" not in json.dumps(item.to_dict()) for item in compiled.items)
    assert compiled.manifest.provenance["criteria"]["authoring_examples"] == examples
    assert "private provenance" in compiled.readme
    with pytest.raises(ValueError, match="distinct source"):
        generation_request(specialty="cardiology", need_statement="Diagnostic reasoning",
            evidence={"a": "A"}, case_count=2, authoring_examples=examples * 2)


class Client:
    def __init__(self, model):
        self.model, self.calls = model, []

    def __call__(self, call):
        self.calls.append(call)
        schema = call.item.metadata.get("response_schema", {})
        fields = schema.get("properties", {})
        if self.model == "generator":
            assert "HELD OUT" not in call.item.prompt and "HELD OUT" not in call.system_prompt
            assert "Source diagnosis" not in call.item.prompt and "Source diagnosis" not in call.system_prompt
            value = candidate()
        elif "classifications" in fields:
            rows = json.loads(call.item.prompt)["original_cases"]
            assert all(row["published_final_diagnosis"] == "Source diagnosis" for row in rows)
            value = {"classifications": [{"case_id": row["case_id"], "tested_task": "Fictional diagnosis", "in_scope": True} for row in rows],
                "rationale": "These cases test the requested diagnostic field."}
        elif "coverage" in fields:
            rows = json.loads(call.item.prompt)["cases"]
            value = {"findings": [], "summary": "Fictional review", "coverage": [
                {"case_id": row["case_id"], **{key: "fictional" for key in
                    ("clinical_topic", "age_band", "care_setting", "decision_type", "new_evidence_type")}} for row in rows],
                "criteria_checks": [{"case_id": row["case_id"], "meets_user_criteria": True,
                    "tested_task": "Fictional task", "rationale": "Fictional criteria fixture"} for row in rows]}
        elif "present" in fields:
            value = {"present": "yes", "matching_diagnosis": "A matched label", "rank": 2}
        else:
            assert "Source diagnosis" not in call.item.prompt and "Synthetic diagnosis" not in call.item.prompt
            assert "Hidden explanation" not in call.item.prompt
            assert "Hidden synthetic test" not in call.item.prompt
            value = {"most_likely_diagnosis": "Alternative", "differential_diagnosis": [
                {"rank": 2, "diagnosis": "A matched label"}, {"rank": "1", "diagnosis": "Alternative"}]}
        return ModelResponse(text=json.dumps(value), cost=.001)


def test_bad_judge_is_reported_as_missing_instead_of_a_low_model_score(tmp_path):
    class BrokenJudge(Client):
        def __call__(self, call):
            return ModelResponse(text='{"present":"yes","matching_diagnosis":"Disease","rank":99}', cost=.001)
    result = evaluate(original_cpc(baseline(2), 2), solver=Client("solver"), judge=BrokenJudge("judge"),
        config=RunnerConfig(results_dir=tmp_path, max_calls=5, max_cost=1, max_cost_per_call=.1, max_retries=1))
    assert result["mean"] is None and result["metrics"]["top5"] is None
    assert result["missing_judgments"] == 2 and result["invalid_judgments"] == 2
    assert result["calls_total"] == 4 and result["cost_total"] == .004


@pytest.mark.parametrize("policy", ["strict", "mast-native"])
def test_portable_cpc_export_records_the_policy_needed_to_reproduce_scores(tmp_path, policy):
    from arisekit.package import write_package
    request = generation_request(specialty="Fictional medicine", need_statement="Fictional diagnostic criteria",
        evidence={"guideline": "Fictional evidence"}, case_count=2)
    legacy = compile_candidate(request, candidate())
    compiled = compile_candidate(request, candidate(), judgment_response_policy=policy)
    assert [item.to_dict() for item in compiled.items] == [item.to_dict() for item in legacy.items]
    assert "judge_response_policy" not in legacy.manifest.provenance["scoring_contract"]
    package = write_package(tmp_path / "package", manifest=compiled.manifest,
        items=compiled.items, readme=compiled.readme, write_asset_manifest=True)
    manifest = json.loads((package / "benchmark.json").read_text())
    recorded_policy = manifest["provenance"]["scoring_contract"].get("judge_response_policy", "strict")
    assert recorded_policy == policy
    assert f'judgment_response_policy="{policy}"' in (package / "README.md").read_text()

    class NativeJudge(Client):
        def __call__(self, call):
            self.calls.append(call)
            return ModelResponse(text=json.dumps({"present": "yes", "matching_diagnosis": "Alternative", "rank": "1"}), cost=.001)

    solver, judge = Client("solver"), NativeJudge("judge")
    config = RunnerConfig(results_dir=tmp_path / "evaluation", max_calls=4, max_cost=1,
        max_cost_per_call=.1, max_retries=1)
    result = evaluate(package, solver=solver, judge=judge, config=config,
        judgment_response_policy=recorded_policy)
    assert result["mean"] == (1.0 if policy == "mast-native" else None)
    assert result["calls_total"] == 4
    replay = evaluate(package, solver=solver, judge=judge, config=config,
        judgment_response_policy=recorded_policy)
    assert replay["metrics"] == result["metrics"]
    assert len(solver.calls) == len(judge.calls) == 2


@pytest.mark.parametrize("kind", ["truncated", "invalid", "not-sent"])
def test_incomplete_solvers_do_not_become_zero_accuracy(tmp_path, kind):
    from arisekit.dispatch import ProviderRequestNotSent
    class IncompleteSolver(Client):
        def __call__(self, call):
            if kind == "not-sent":
                raise ProviderRequestNotSent("Fictional preflight rejection")
            if kind == "invalid":
                return ModelResponse(text="{}", cost=.001)
            return ModelResponse(text=json.dumps({"differential_diagnosis": [{"rank": 1, "diagnosis": "Fictional"}]}),
                cost=.001, finish_reason="length")
    judge = Client("judge")
    result = evaluate(original_cpc(baseline(2), 2), solver=IncompleteSolver("solver"), judge=judge,
        config=RunnerConfig(results_dir=tmp_path, max_calls=5, max_cost=1, max_cost_per_call=.1, max_retries=1))
    assert result["expected"] == result["observed"] == 2
    assert result["mean"] is None and all(v is None for v in result["metrics"].values())
    assert result["judged"] == result["valid_solver_outputs"] == 0 and judge.calls == []
    assert result[{"truncated": "truncated_solver_outputs", "invalid": "invalid", "not-sent": "errors"}[kind]] == 2


def test_native_evaluation_preserves_rank_scores_and_separate_format_counts(tmp_path):
    class AlternativeLabelJudge(Client):
        def __call__(self, call):
            return ModelResponse(text='{"present":"yes","matching_diagnosis":"Alternative wording","rank":1}', cost=.001)
    result = evaluate(original_cpc(baseline(2), 2), solver=Client("solver"), judge=AlternativeLabelJudge("judge"),
        config=RunnerConfig(results_dir=tmp_path, max_calls=5, max_cost=1, max_cost_per_call=.1, max_retries=1),
        judgment_response_policy="mast-native")
    assert result["mean"] == 1 and result["missing_judgments"] == 0
    assert result["strict_judgment_format_violations"] == 2
    assert result["calls_total"] == 4 and result["cost_total"] == .004


def test_native_differential_order_and_top_k_boundaries():
    assert ranked_diagnoses(json.dumps({"differential_diagnosis": [{"rank": "5", "diagnosis": "B"}, {"rank": 1, "diagnosis": "A"}]})) == ["A", "B"]
    for rank in range(1, 11):
        assert judgment_metrics(json.dumps({"present": "yes", "matching_diagnosis": "Disease", "rank": rank}), 10) == {
            f"top{k}": float(rank <= k) for k in (1, 5, 10)}
    assert judgment_metrics('{"present":"no","matching_diagnosis":"","rank":null}', 10) == {"top1": 0, "top5": 0, "top10": 0}
    for rank in (0, 11, True, "1", None):
        with pytest.raises(ValueError):
            judgment_metrics(json.dumps({"present": "yes", "matching_diagnosis": "Disease", "rank": rank}), 10)
    with pytest.raises(ValueError, match="disagree"):
        judgment_metrics('{"present":"yes","matching_diagnosis":"Disease","rank":1}', 1, diagnoses=["Different disease"])


def test_frozen_criteria_and_synthetic_reference_provenance_cannot_be_overridden():
    request = generation_request(specialty="Fictional medicine", need_statement="Fictional diagnostic criteria",
        evidence={"guideline": "Fictional evidence"}, case_count=2)
    compiled = compile_candidate(request, candidate())
    assert compiled.manifest.scorer == {"kind": "deferred"}
    assert compiled.manifest.provenance["scoring_contract"]["metrics"] == ["top1", "top5", "top10"]
    assert all(item.metadata["synthetic_confirmation"].startswith("Hidden synthetic test") for item in compiled.items)
    changed = deepcopy(request)
    changed.metadata["need_statement"] += " changed"
    with pytest.raises(ValueError, match="frozen criteria"):
        compile_candidate(changed, candidate())
    wrong = candidate()
    wrong["reference_origin"] = "expert"
    with pytest.raises(ValueError, match="synthetic reference"):
        compile_candidate(request, wrong)


def test_all_judge_calls_are_reused_on_local_resume(tmp_path):
    solver, judge = Client("solver"), Client("judge")
    cfg = RunnerConfig(results_dir=tmp_path, max_calls=8, max_cost=1, max_cost_per_call=.1, max_retries=1)
    first = evaluate(original_cpc(baseline(2), 2), solver=solver, judge=judge, config=cfg)
    second = evaluate(original_cpc(baseline(2), 2), solver=solver, judge=judge, config=cfg)
    assert second == first
    assert len(solver.calls) == len(judge.calls) == 2


def test_reasoning_model_output_limits_are_explicit_for_both_cpc_stages(tmp_path):
    solver, judge = Client("solver"), Client("judge")
    evaluate(original_cpc(baseline(2), 2), solver=solver, judge=judge,
        config=RunnerConfig(results_dir=tmp_path, max_calls=8, max_cost=1, max_cost_per_call=.1, max_retries=1),
        solver_max_tokens=32768, judge_max_tokens=16384)
    assert {call.max_tokens for call in solver.calls} == {32768}
    assert {call.max_tokens for call in judge.calls} == {16384}


def test_optional_case_identity_contract_reaches_actual_vertex_schema():
    from arisekit.client import ModelCall
    from arisekit.vertex_client import VertexClient
    identities = ['planned-b', 'planned-a']
    request = generation_request(specialty='cardiology', need_statement='Diagnostic reasoning',
        evidence={'guideline': 'Synthetic evidence'}, case_count=2, case_ids=identities)
    identities[0] = 'caller-change'
    call = ModelCall(item=request, system_prompt='', temperature=0, max_tokens=4096)
    _, body = VertexClient('gemini-3.1-pro-preview', project='offline-fixture', token=lambda: 'unused').request(call)
    schema = body['generationConfig']['responseJsonSchema']['properties']['cases']['items']['properties']
    assert schema['id'] == {'type': 'string', 'enum': ['planned-b', 'planned-a']}
    assert schema['presentation'] == {'type': 'string'}
    assert request.metadata['case_ids'] == ['planned-b', 'planned-a']


@pytest.mark.parametrize('identities', [[], ['one'], ['one', 'one'], ['one', ''],
    ['one', '  '], ['one', None], ['one', []], 'ab'])
def test_case_identity_assignment_must_cover_every_slot_before_generation(identities):
    with pytest.raises(ValueError, match='case_ids'):
        generation_request(specialty='cardiology', need_statement='Diagnostic reasoning',
            evidence={'guideline': 'Synthetic evidence'}, case_count=2, case_ids=identities)


@pytest.mark.parametrize('identities', [['Wait', 'Wait2'], ['new-0', 'new-0'],
    ['new-0', 'extra'], ['new-0', None], ['new-0', []]])
def test_compile_rejects_unbound_case_identity_before_packaging(identities):
    request = generation_request(specialty='cardiology', need_statement='Diagnostic reasoning',
        evidence={'guideline': 'Synthetic evidence'}, case_count=2, case_ids=['new-0', 'new-1'])
    value = candidate()
    for row, identity in zip(value['cases'], identities):
        row['id'] = identity
    with pytest.raises(ValueError, match='exact assigned case identity'):
        compile_candidate(request, value)


def test_assigned_case_identity_survives_frozen_roundtrip_without_relabeling():
    from arisekit.common.jsonio import canonical_json as canonical
    from arisekit.types import BenchmarkItem
    request = generation_request(specialty='cardiology', need_statement='Diagnostic reasoning',
        evidence={'guideline': 'Synthetic evidence'}, case_count=2, case_ids=['new-0', 'new-1'])
    saved = BenchmarkItem.from_dict(json.loads(canonical(request.to_dict())))
    value = candidate()
    value['cases'].reverse()
    compiled = compile_candidate(saved, value)
    assert [item.id for item in compiled.items] == ['new-1', 'new-0']
    assert compiled.manifest.provenance['criteria']['case_ids'] == ['new-0', 'new-1']
    changed = deepcopy(saved)
    changed.metadata['case_ids'] = ['different', 'new-1']
    with pytest.raises(ValueError, match='frozen criteria'):
        compile_candidate(changed, value)


def test_unassigned_cpc_request_preserves_frozen_request_bytes():
    import hashlib
    request = generation_request(specialty='cardiology', need_statement='Diagnostic reasoning',
        evidence={'guideline': 'Synthetic evidence'}, case_count=2)
    encoded = json.dumps(request.to_dict(), sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == 'ef7b9977dfb4c84306147098da01d839f468a7e38c98da97b1292943327a1d49'
    assert 'case_ids' not in request.metadata
    assert len(compile_candidate(request, candidate()).items) == 2


def test_assigned_case_identity_uses_existing_bounded_structural_repair(tmp_path):
    from arisekit.generation.autonomous_generation import run_autonomous_generation
    from arisekit.dataset import Dataset
    from test_autonomous_generation import FixtureGenerator
    request = generation_request(specialty='cardiology', need_statement='Diagnostic reasoning',
        evidence={'guideline': 'Synthetic evidence'}, case_count=2, case_ids=['new-0', 'new-1'])
    invalid = candidate()
    invalid['cases'][0]['id'] = 'Wait'
    model = FixtureGenerator([invalid, candidate()])
    kwargs = dict(model=model, config=RunnerConfig(max_cost=.5, max_cost_per_call=.1,
        max_calls=2, max_retries=1, retry_backoff=0, require_known_cost=True),
        output_dir=tmp_path/'generation', data_classification='synthetic', max_repairs=1,
        compiler=compile_candidate)
    report = run_autonomous_generation(Dataset([request]), **kwargs)
    assert report['requested'] == report['compiled'] == 1
    assert model.calls == 2
    package = tmp_path/'generation'/report['outcomes'][0]['package']
    assert [item.id for item in Benchmark.from_package(package, scorer=DeferredScorer()).dataset] == ['new-0', 'new-1']
    assert run_autonomous_generation(Dataset([request]), **kwargs) == report
    assert model.calls == 2
