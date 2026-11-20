"""Model-proposed FHIR cases compile to the existing executable package contract."""

from copy import deepcopy
import json

import pytest

from arisekit.agentic import AgenticPassCondition, PassAtOneScorer, trajectory_passes_condition
from arisekit.fhir.autonomous_fhir import (
    AUTONOMOUS_FHIR_CANDIDATE_SCHEMA,
    autonomous_fhir_generation_contract,
    autonomous_fhir_generation_request,
    compile_autonomous_fhir_candidate,
)
from arisekit.generation.autonomous_generation import compile_candidate, run_autonomous_generation
from arisekit.benchmark import Benchmark
from arisekit.client import ModelResponse
from arisekit.dataset import Dataset
from arisekit.env.fhir import FHIREnvironment, fhir_tools
from arisekit.package import agentic_fhir_binding_from_package, load_package, write_package
from arisekit.runner import RunnerConfig
from arisekit.types import RunResult, Trajectory, Turn


def request(**kwargs):
    return autonomous_fhir_generation_request(
        request_id="refill-coordination",
        need="Measure whether an assistant can find the recorded refill status and create an outreach task when requested.",
        evidence={"workflow": "Synthetic workflow: use recorded prescription status and explicitly requested outreach actions."},
        **kwargs,
    )


def candidate(*, write=False):
    result = {
        "schema_version": AUTONOMOUS_FHIR_CANDIDATE_SCHEMA,
        "kind": "agentic-fhir", "reference_origin": "synthetic",
        "name": "Refill chart workflow", "task": "Retrieve recorded prescription status.",
        "cases": [{
            "id": "refill-1", "patient_id": "patient-1", "source_ids": ["workflow"],
            "instruction": "For Patient/patient-1, find the prescription and report its recorded status.",
            "bundle": {
                "resourceType": "Bundle", "id": "refill-1", "type": "collection",
                "entry": [
                    {"resource": {"resourceType": "Patient", "id": "patient-1", "name": [{"family": "Sample"}]}},
                    {"resource": {
                        "resourceType": "MedicationRequest", "id": "rx-1", "status": "active",
                        "intent": "order", "subject": {"reference": "Patient/patient-1"},
                        "medicationCodeableConcept": {"text": "Synthetic medication"},
                    }},
                ],
            },
            "required_tool_calls": [{"name": "search_medication_requests", "arguments": {"patient_id": "patient-1"}}],
            "answer_bindings": [{"label": "Recorded prescription status", "call_index": 0, "path": [0, "status"]}],
        }],
    }
    if write:
        result["task"] = "Retrieve recorded prescription status and create requested outreach task."
        result["cases"][0]["instruction"] += " Create a routine outreach task with description 'Confirm refill availability'. Report the task id."
        result["cases"][0]["required_tool_calls"].append({
            "name": "create_task", "arguments": {"for_patient_id": "patient-1", "description": "Confirm refill availability", "priority": "routine"},
        })
        result["cases"][0]["answer_bindings"].append({"label": "Created task id", "call_index": 1, "path": ["id"]})
    return result


def replay(compiled, *, final=None, skip_call=None):
    item = compiled.items[0]
    condition = AgenticPassCondition.from_dict(item.ground_truth)
    env = FHIREnvironment(deepcopy(compiled.cohort_bundles))
    tools = {tool.name: tool for tool in fhir_tools(env)}
    turns = []
    for index, call in enumerate(condition.required_tool_calls):
        if index == skip_call:
            continue
        call_id = f"call-{index}"
        result = tools[call.name].fn(**call.arguments)
        turns.extend([
            Turn(role="tool_call", content={"id": call_id, **call.to_dict()}),
            Turn(role="tool_result", content={"id": call_id, "name": call.name, "result": result}),
        ])
    return Trajectory(turns=turns, final_response=final if final is not None else " ".join(condition.final_response_contains))


def test_request_exposes_real_tool_schemas_and_json_design_contract():
    item = request(allowed_tools=["search_medication_requests", "create_task"])
    prompt = json.loads(item.prompt)
    assert prompt["need"] == item.metadata["need"]
    assert prompt["evidence"] == item.metadata["evidence"]
    assert item.metadata["candidate_kind"] == "agentic-fhir"
    assert [tool["name"] for tool in prompt["contract"]["tools"]] == item.metadata["allowed_tools"]
    schema = prompt["contract"]["response_schema"]
    assert schema["properties"]["reference_origin"]["const"] == "synthetic"
    assert "answer_bindings" in schema["properties"]["cases"]["items"]["required"]


def test_generation_schema_accepts_executable_reference():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(candidate(write=True), autonomous_fhir_generation_contract()["response_schema"])


def test_reference_answers_are_derived_and_score_real_calls():
    compiled = compile_autonomous_fhir_candidate(request(), candidate(write=True))
    item = compiled.items[0]
    condition = AgenticPassCondition.from_dict(item.ground_truth)
    assert condition.final_response_contains == ('["active","task-1"]',)
    assert "task-1" not in item.prompt
    assert "active" not in item.prompt
    assert '["Recorded prescription status","Created task id"]' in item.prompt
    assert compiled.manifest.scorer["name"] == "synthetic_reference_pass_at_1"
    assert compiled.manifest.provenance["reference_origin"] == "synthetic"
    assert trajectory_passes_condition(replay(compiled), condition)
    assert not trajectory_passes_condition(replay(compiled, final='["completed","task-1"]'), condition)
    assert not trajectory_passes_condition(replay(compiled, skip_call=1), condition)
    assert not trajectory_passes_condition(Trajectory(turns=[], final_response="active task-1"), condition)
    metric = PassAtOneScorer(**{key: value for key, value in compiled.manifest.scorer.items() if key != "kind"}).score_item(
        item, [RunResult(id=item.id, trial=0, response=replay(compiled)),
               RunResult(id=item.id, trial=1, response=None, error="provider failed")],
    )[0]
    assert metric.n == 2
    assert metric.value == 0.5


def test_replay_digest_is_stable_despite_created_task_clock_and_detaches_input():
    payload = candidate(write=True)
    first = compile_autonomous_fhir_candidate(request(), payload)
    second = compile_autonomous_fhir_candidate(request(), payload)
    assert first.manifest.provenance["reference_replays"] == second.manifest.provenance["reference_replays"]
    assert first.manifest.provenance["replay_exclusions"] == ["authoredOn of Task resources created during reference replay"]
    payload["cases"][0]["bundle"]["entry"][1]["resource"]["status"] = "stopped"
    assert first.cohort_bundles[0]["entry"][1]["resource"]["status"] == "active"


def test_complete_answer_vector_prevents_category_substring_false_positive():
    compiled = compile_autonomous_fhir_candidate(request(), candidate())
    condition = AgenticPassCondition.from_dict(compiled.items[0].ground_truth)
    assert trajectory_passes_condition(replay(compiled, final='["active"]'), condition)
    assert not trajectory_passes_condition(replay(compiled, final='["inactive"]'), condition)
    assert not trajectory_passes_condition(replay(compiled, final='["active","invented"]'), condition)
    assert "scalar boundaries are preserved" in compiled.manifest.provenance["scoring_scope"]
    assert "additional response text" in compiled.manifest.provenance["scoring_scope"]
    assert "clinical correctness are not evaluated" in compiled.manifest.provenance["scoring_scope"]


def test_complete_answer_vector_preserves_numeric_type_and_boundary():
    payload = candidate()
    row = payload["cases"][0]
    row["bundle"]["entry"][1]["resource"]["dispenseRequest"] = {"numberOfRepeatsAllowed": 7}
    row["answer_bindings"] = [{"label": "Number of repeats allowed", "call_index": 0,
                               "path": [0, "dispenseRequest", "numberOfRepeatsAllowed"]}]
    compiled = compile_autonomous_fhir_candidate(request(), payload)
    condition = AgenticPassCondition.from_dict(compiled.items[0].ground_truth)
    assert condition.final_response_contains == ("[7]",)
    assert trajectory_passes_condition(replay(compiled, final="[7]"), condition)
    for final in ("[70]", '["7"]', "[7,70]", "7"):
        assert not trajectory_passes_condition(replay(compiled, final=final), condition)


def test_write_only_task_has_executable_condition_without_answer_assertion():
    payload = candidate(write=True)
    payload["cases"][0]["required_tool_calls"] = payload["cases"][0]["required_tool_calls"][1:]
    payload["cases"][0]["answer_bindings"] = []
    compiled = compile_autonomous_fhir_candidate(request(), payload)
    assert compiled.items[0].ground_truth["final_response_contains"] == []
    assert trajectory_passes_condition(replay(compiled), AgenticPassCondition.from_dict(compiled.items[0].ground_truth))


@pytest.mark.parametrize("binding", [
    {"call_index": 0, "path": [8, "status"]},
    {"call_index": 0, "path": [0]},
    {"call_index": 0, "path": [True, "status"]},
    {"call_index": True, "path": [0, "status"]},
    {"call_index": 9, "path": [0, "status"]},
    {"call_index": 0, "path": []},
    {"call_index": 1, "path": ["authoredOn"]},
    {"call_index": 0, "path": [0, "absent"]},
])
def test_invalid_or_volatile_answer_selectors_rejected(binding):
    payload = candidate(write=True)
    payload["cases"][0]["answer_bindings"] = [{"label": "Requested result", **binding}]
    with pytest.raises(ValueError, match="answer binding"):
        compile_autonomous_fhir_candidate(request(), payload)


@pytest.mark.parametrize("change,match", [
    (lambda p: p.update(reference_origin="expert"), "synthetic"),
    (lambda p: p.update(kind="novel-text"), "schema or kind"),
    (lambda p: p.update(expert_approval=True), "exactly"),
    (lambda p: p["cases"][0].update(source_ids=["invented-source"]), "supplied evidence"),
    (lambda p: p["cases"][0].update(answer_bindings=[]), "read-only"),
    (lambda p: p["cases"][0]["bundle"].update(id="different"), "Bundle.id"),
    (lambda p: p["cases"][0]["bundle"]["entry"][1]["resource"].update(id=None), "FHIR id"),
    (lambda p: p["cases"][0]["bundle"]["entry"][1]["resource"].update(subject={"reference": "Patient/missing"}), "case patient"),
    (lambda p: p["cases"][0]["bundle"]["entry"][1]["resource"].update(encounter={"reference": "Encounter/missing"}), "resolve"),
    (lambda p: p["cases"][0]["bundle"]["entry"].append(deepcopy(p["cases"][0]["bundle"]["entry"][0])), "duplicate"),
    (lambda p: p["cases"][0]["required_tool_calls"][0]["arguments"].update(patient_id="another"), "case patient"),
    (lambda p: p["cases"][0]["required_tool_calls"][0]["arguments"].update(code="fake"), "unknown"),
    (lambda p: p["cases"][0]["required_tool_calls"][0]["arguments"].update(status="imaginary"), "must be one of"),
    (lambda p: p["cases"][0]["required_tool_calls"][0].update(name="execute_python"), "disallowed"),
    (lambda p: p["cases"].append(deepcopy(p["cases"][0])), "case count"),
])
def test_malformed_unbound_or_invented_candidates_rejected(change, match):
    payload = candidate()
    change(payload)
    with pytest.raises(ValueError, match=match):
        compile_autonomous_fhir_candidate(request(), payload)


def test_disallowed_tools_turn_limits_and_created_identity_collision_avoidance():
    with pytest.raises(ValueError, match="disallowed"):
        compile_autonomous_fhir_candidate(request(allowed_tools=["get_patient"]), candidate())
    with pytest.raises(ValueError, match="max_turns"):
        compile_autonomous_fhir_candidate(request(max_turns=2), candidate(write=True))
    payload = candidate(write=True)
    payload["cases"][0]["bundle"]["entry"].append({"resource": {
        "resourceType": "Task", "id": "task-1", "status": "ready", "intent": "plan",
        "for": {"reference": "Patient/patient-1"},
    }})
    compiled = compile_autonomous_fhir_candidate(request(), payload)
    assert compiled.items[0].ground_truth["final_response_contains"] == ['["active","task-2"]']
    assert compiled.cohort_bundles[0]["entry"][-1]["resource"]["id"] == "task-1"


@pytest.mark.parametrize("change", [
    lambda item: item.metadata["evidence"].update(workflow="Substituted evidence never supplied to the generator."),
    lambda item: item.metadata.update(allowed_tools=["search_medication_requests"]),
    lambda item: item.metadata.update(max_turns=9),
    lambda item: setattr(item, "prompt", "Different generation prompt"),
    lambda item: item.metadata.update(evidence={"workflow": "Replaced evidence", "invented": "Unsent source"}),
])
def test_request_metadata_cannot_change_without_matching_rendered_prompt(change):
    generation_request = request()
    change(generation_request)
    with pytest.raises(ValueError, match="rendered prompt"):
        compile_autonomous_fhir_candidate(generation_request, candidate())


def test_two_cases_can_reuse_patient_ids_with_isolated_bundles(tmp_path):
    payload = candidate(write=True)
    other = deepcopy(payload["cases"][0])
    other["id"] = other["bundle"]["id"] = "refill-2"
    other["bundle"]["entry"][0]["resource"]["name"][0]["family"] = "Second"
    payload["cases"].append(other)
    compiled = compile_autonomous_fhir_candidate(request(case_count=2), payload)
    path = write_package(tmp_path / "package", manifest=compiled.manifest, items=compiled.items,
                         env=compiled.env, cohort_bundles=compiled.cohort_bundles, write_asset_manifest=True)
    package = load_package(path, verify_assets=True)
    binding = agentic_fhir_binding_from_package(package)
    assert set(binding.bundles) == {"refill-1", "refill-2"}
    benchmark = Benchmark.from_package(path)
    results = benchmark.run("stub/reference", trials=2, threads=2,
                            results_dir=tmp_path / "solver", auto_manifest=True)
    assert results.metrics[0].value == 1
    assert results.metrics[0].n == 2
    assert len(results.raw) == 4
    assert all(metrics[0].n == 2 for _, metrics in results.per_item)
    assert results.summary.cost_total == 0
    for bundle in compiled.cohort_bundles:
        assert not any(entry["resource"]["resourceType"] == "Task" for entry in bundle["entry"])


class FixtureGenerator:
    model = "fixture/fhir-generator"

    def __init__(self):
        self.calls = 0

    def __call__(self, call):
        self.calls += 1
        payload = candidate(write=True)
        if self.calls == 1:
            payload["cases"][0]["answer_bindings"][0]["path"] = [0, "invented"]
        return ModelResponse(text=json.dumps(payload), cost=0, cost_known=True, provider_model=self.model)


def test_shared_controller_repairs_packages_and_resumes_fhir_without_live_calls(tmp_path):
    model = FixtureGenerator()
    kwargs = {
        "model": model, "config": RunnerConfig(max_cost=1, max_cost_per_call=0.1, max_calls=3,
                                                max_retries=1, retry_backoff=0, require_known_cost=True),
        "output_dir": tmp_path / "generation", "data_classification": "synthetic",
    }
    report = run_autonomous_generation(Dataset([request()]), **kwargs)
    assert report["compiled"] == 1
    assert [attempt["status"] for attempt in report["attempts"]] == ["invalid_candidate", "compiled"]
    assert report["calls_total"] == model.calls == 2
    package_path = tmp_path / "generation" / report["outcomes"][0]["package"]
    package = load_package(package_path, verify_assets=True)
    assert package.env is not None and len(package.cohort) == 1
    assert package.manifest.provenance["autonomous_generation"]["attempt"] == 2
    assert compile_candidate(request(), candidate()).manifest.modality == "agentic-fhir"
    results = Benchmark.from_package(package_path).run("stub/reference", results_dir=tmp_path / "solver", auto_manifest=True)
    assert results.metrics[0].value == 1
    assert run_autonomous_generation(Dataset([request()]), **kwargs) == report
    assert model.calls == 2
