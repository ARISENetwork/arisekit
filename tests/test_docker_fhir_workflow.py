"""Portable FHIR outcome checks and opt-in real Docker recovery verification."""
import copy
import json
import os
from pathlib import Path

import pytest

from arisekit.agentic import AgentTurnOutput
from arisekit.env.docker_fhir import DockerFHIRServer, HTTPFHIREnvironment, digest
from arisekit.fhir.fhir_workflow import (compile_candidate, generation_request, binding_from_package,
    score_trajectory, FHIROutcomeScorer, state_predicates, DockerFHIRAgentSUT, validate_brief)
from arisekit.package import write_package, load_package
from arisekit.sut import SUTCheckpoint
from arisekit.types import RunResult, Trajectory, Turn

ROOT = Path(__file__).parents[1]


@pytest.fixture
def compiled():
    brief = json.loads((ROOT / "examples/docker-fhir/brief.json").read_text())
    candidate = json.loads((ROOT / "examples/docker-fhir/reference-candidate.json").read_text())
    return compile_candidate(generation_request(brief), candidate)


def bind(tmp_path, candidate):
    path = tmp_path / "package"
    write_package(path, manifest=candidate.manifest, items=candidate.items, env=candidate.env,
                  cohort_bundles=candidate.cohort_bundles, write_asset_manifest=True)
    return path, binding_from_package(load_package(path, verify_assets=True))


def test_package_roundtrip_and_drift(tmp_path, compiled):
    path, binding = bind(tmp_path, compiled)
    from arisekit.benchmark import Benchmark
    assert Benchmark.from_package(path).scorer.configuration() == {"kind": "fhir-outcome"}
    assert binding.max_turns == 8
    benchmark = Benchmark.from_package(path)
    assert benchmark.runner_config.max_calls == 32
    with pytest.raises(ValueError, match="frozen FHIR brief"):
        benchmark.run("stub/reference", max_calls=33)
    package = load_package(path, verify_assets=True)
    package.env["environment"]["image"] = "hapiproject/hapi:latest"
    with pytest.raises(ValueError, match="drift"):
        binding_from_package(package)


def test_request_freeze_and_privacy(compiled):
    brief = compiled.manifest.provenance["fhir_brief"]
    invalid = copy.deepcopy(brief)
    invalid["data_classification"] = "identifiable"
    with pytest.raises(ValueError, match="public or synthetic"):
        validate_brief(invalid)
    request = generation_request(brief)
    request.prompt += "tampered"
    with pytest.raises(ValueError, match="frozen brief"):
        compile_candidate(request, compiled.manifest.provenance["candidate_payload"])
    for item in compiled.items:
        assert "reference_actions" not in item.prompt


def test_outcome_controls_and_equivalent_plan(compiled):
    item = compiled.items[1]
    initial = [e["resource"] for e in compiled.cohort_bundles[1]["entry"]]
    created = copy.deepcopy(item.ground_truth["reference_actions"][0]["arguments"]["resource"])
    created["id"] = "any-alternative-id"
    terminal = initial + [created]
    def trajectory(resources, answer="done"):
        state = {"seed_sha256": item.ground_truth["seed_sha256"], "initial": initial,
                 "terminal": resources, "initial_sha256": digest(initial), "terminal_sha256": digest(resources), "complete": True}
        return Trajectory(final_response=answer, turns=[Turn("tool_result", {"result": {"id": "alternative-plan"}}), Turn("environment", state)])
    assert score_trajectory(item, trajectory(terminal))["passed"]
    assert not score_trajectory(item, trajectory(initial))["passed"]
    [metric] = FHIROutcomeScorer().score_item(item, [RunResult(item.id, 0, trajectory(terminal)),
                                                     RunResult(item.id, 1, None, error="FHIR attempt time limit reached")])
    assert (metric.value, metric.n) == (0.5, 2)
    [metric] = FHIROutcomeScorer().score_item(item, [RunResult(item.id, 0, None, error="provider error")])
    assert (metric.value, metric.n) == (0.0, 1)
    wrong = copy.deepcopy(terminal)
    wrong[-1]["status"] = "completed"
    assert not score_trajectory(item, trajectory(wrong))["passed"]
    wrong = copy.deepcopy(terminal)
    wrong[-1]["for"]["reference"] = "Patient/other"
    assert not score_trajectory(item, trajectory(wrong))["passed"]
    duplicate = copy.deepcopy(created); duplicate["id"] = "duplicate-write"
    assert not score_trajectory(item, trajectory(terminal + [duplicate]))["passed"]
    altered = copy.deepcopy(terminal); next(r for r in altered if r["resourceType"] == "Observation")["valueQuantity"]["value"] = 99
    assert not score_trajectory(item, trajectory(altered))["passed"]
    recovered = trajectory(terminal)
    recovered.turns.insert(0, Turn("tool_result", {"result": {"error": "invalid search parameter"}}))
    assert score_trajectory(item, recovered)["passed"]
    recovered.turns[-1].content["policy_violations"] = 1
    assert not score_trajectory(item, recovered)["passed"]
    bad = trajectory(terminal)
    bad.turns[-1].content["terminal_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="checksum"):
        score_trajectory(item, bad)


def test_invalid_authoring_and_seed(compiled):
    brief = compiled.manifest.provenance["fhir_brief"]
    candidate = copy.deepcopy(compiled.manifest.provenance["candidate_payload"])
    candidate["cases"][1]["predicates"] = [{"phase": "terminal", "resource_type": "Task", "where": {}, "path": ".", "operator": "exists", "expected": True}]
    with pytest.raises(ValueError, match="already satisfied"):
        compile_candidate(generation_request(brief), candidate)
    invalid = copy.deepcopy(brief)
    invalid["seed_bundle"]["entry"][1]["resource"]["subject"]["reference"] = "Patient/other"
    with pytest.raises(PermissionError):
        generation_request(invalid)
    invalid = copy.deepcopy(brief)
    invalid["limits"]["max_turns"] = 1.5
    with pytest.raises(ValueError, match="integers"):
        validate_brief(invalid)


def test_chart_provenance_is_not_an_evidence_source(compiled):
    brief = compiled.manifest.provenance["fhir_brief"]
    candidate = copy.deepcopy(compiled.manifest.provenance["candidate_payload"])
    candidate["cases"][0]["source_ids"].append("seed_bundle")
    with pytest.raises(ValueError, match='allowed source_ids: \\["operational-rule"\\]'):
        compile_candidate(generation_request(brief), candidate)
    candidate["cases"][0]["source_ids"] = [list(brief["evidence"])[0]]
    assert compile_candidate(generation_request(brief), candidate).items


def test_reference_response_is_derived_without_changing_the_answer(compiled):
    brief = compiled.manifest.provenance["fhir_brief"]
    candidate = copy.deepcopy(compiled.manifest.provenance["candidate_payload"])
    for row in candidate["cases"]:
        row.pop("reference_answer")
    result = compile_candidate(generation_request(brief), candidate)
    assert result.manifest.provenance["derived_reference_answer_case_ids"] == [row["id"] for row in candidate["cases"]]
    for item in result.items:
        answer = item.ground_truth["answer_json"]
        if answer is not None:
            assert json.loads(item.ground_truth["reference_answer"]) == answer
        else:
            assert item.ground_truth["reference_answer"] == "Done"
    candidate["cases"][0]["reference_answer"] = "-1234"
    with pytest.raises(ValueError, match="differs from answer_json"):
        compile_candidate(generation_request(brief), candidate)


def test_missing_candidate_fields_are_actionable_for_structural_repair(compiled):
    brief = compiled.manifest.provenance["fhir_brief"]
    candidate = copy.deepcopy(compiled.manifest.provenance["candidate_payload"])
    candidate["cases"][0].pop("reference_actions")
    candidate["cases"][0]["unrecognized"] = True
    with pytest.raises(ValueError, match=r'cases\[0\].*missing: \["reference_actions"\].*unexpected: \["unrecognized"\]'):
        compile_candidate(generation_request(brief), candidate)


def test_json_numeric_value_is_distinct_from_boolean_and_wrong_answers(compiled):
    item = copy.deepcopy(compiled.items[0])
    item.ground_truth["answer_json"] = {"values": [123.0, False]}
    initial = [entry["resource"] for entry in compiled.cohort_bundles[0]["entry"]]
    state = {"seed_sha256": item.ground_truth["seed_sha256"], "initial": initial,
             "terminal": initial, "initial_sha256": digest(initial), "terminal_sha256": digest(initial), "complete": True}
    def score(answer):
        return score_trajectory(item, Trajectory(final_response=answer,
            turns=[Turn("tool_result", {"result": {"ok": True}}), Turn("environment", state)]))["passed"]
    assert score('{"values":[123,false]}')
    assert not score('{"values":[123,0]}')
    assert not score('{"values":[124,false]}')
    assert not score('{"values":[NaN,false]}')
    assert not score('{"values":[123,false],"extra":1}')


def test_next_page_can_use_exact_base_path_without_crossing_server_boundary():
    import io
    server = DockerFHIRServer()
    server.base_url = "http://127.0.0.1:12345/fhir"
    calls = []
    class Opener:
        def open(self, request, **kwargs):
            calls.append(request.full_url)
            return io.BytesIO(b'{"resourceType":"Bundle"}')
    server.opener = Opener()
    assert server.request("GET", server.base_url + "?_getpages=opaque")["resourceType"] == "Bundle"
    assert len(calls) == 1
    for url in ("http://127.0.0.1:12346/fhir?_getpages=x", "https://127.0.0.1:12345/fhir",
                "http://127.0.0.1:12345/fhir-other", "http://127.0.0.1:12345/admin"):
        with pytest.raises(ValueError, match="same server"):
            server.request("GET", url)
    assert len(calls) == 1


DOCKER = pytest.mark.skipif(os.environ.get("ARISEKIT_TEST_DOCKER") != "1", reason="set ARISEKIT_TEST_DOCKER=1 to start real pinned HAPI containers")


@DOCKER
@pytest.mark.slow
def test_real_docker_search_follows_same_origin_base_path_page():
    resources = [{"resourceType": "Patient", "id": "page-patient"}] + [
        {"resourceType": "Observation", "id": identifier, "status": "final", "code": {"text": "Page test"},
         "subject": {"reference": "Patient/page-patient"}, "valueQuantity": {"value": 1}}
        for identifier in ("page-a", "page-b")]
    seed = {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": resource} for resource in resources]}
    with DockerFHIRServer() as server:
        env = HTTPFHIREnvironment(server, seed, {"Patient": ["read", "search"], "Observation": ["read", "search"]})
        env.seed()
        assert {r["id"] for r in server.resources("Observation", {"_count": "1"})} == {"page-a", "page-b"}


@DOCKER
@pytest.mark.slow
def test_real_docker_crud_search_policy_and_isolation(compiled):
    bundle = compiled.cohort_bundles[1]
    policy = compiled.env["resources"]
    with DockerFHIRServer() as server:
        env = HTTPFHIREnvironment(server, bundle, policy)
        env.seed()
        initial = env.snapshot()
        assert server.metadata["fhirVersion"] == "4.0.1"
        assert env.search("Observation", {"patient": "p1", "code": "2823-3"})[0]["valueQuantity"]["value"] == 4.2
        assert env.search("Observation", {"date": "gt2026-10-21"}) == []
        assert env.search("Observation", {"patient": "p1", "_count": 1})[0]["id"] == "lab1"
        task = env.create(compiled.items[1].ground_truth["reference_actions"][0]["arguments"]["resource"])
        assert any(r["id"] == task["id"] for r in env.snapshot())
        task["status"] = "completed"
        assert env.update(task)["status"] == "completed"
        assert env.read("Task", task["id"])["status"] == "completed"
        env.delete("Task", task["id"])
        assert env.read("Task", task["id"]) is None
        with pytest.raises(PermissionError):
            env.delete("Patient", "p1")
        with pytest.raises(ValueError):
            env.search("Observation", {"typo": "ignored-filter"})
        wrong = copy.deepcopy(task)
        wrong.pop("id")
        wrong["for"]["reference"] = "Patient/other"
        with pytest.raises(PermissionError):
            env.create(wrong)
        assert env.snapshot() == initial
    with DockerFHIRServer() as server:
        env = HTTPFHIREnvironment(server, bundle, policy)
        env.seed()
        assert env.snapshot() == initial


@DOCKER
@pytest.mark.slow
def test_real_docker_interrupted_write_resume_and_null(compiled, tmp_path):
    _, binding = bind(tmp_path, compiled)
    item = compiled.items[1]
    class Interrupt(BaseException):
        pass
    checkpoints = []
    sut = DockerFHIRAgentSUT("stub/reference", binding)
    def save(checkpoint):
        checkpoints.append(SUTCheckpoint(**{**checkpoint.__dict__, "response": Trajectory.from_dict(checkpoint.response.to_dict())}))
        if any(t.role == "tool_result" for t in checkpoint.response.turns):
            raise Interrupt()
    with pytest.raises(Interrupt):
        sut.respond_checkpointed(item, trial=1, on_checkpoint=save)
    assert len(checkpoints) == 2
    resumed = sut.respond_checkpointed(item, trial=1, resume_from=checkpoints[-1])
    assert score_trajectory(item, resumed.response)["passed"]
    terminal = [t.content for t in resumed.response.turns if t.role == "environment"][-1]["terminal"]
    assert sum(r["resourceType"] == "Task" for r in terminal) == 2
    assert sum(t.role == "tool_result" for t in resumed.response.turns) == 1
    # Intent-only checkpoint must replay exactly one write into a new server.
    replay = sut.respond_checkpointed(item, trial=1, resume_from=checkpoints[0])
    assert score_trajectory(item, replay.response)["passed"]
    assert [t.content for t in replay.response.turns if t.role == "environment"][-1]["terminal"] == terminal
    class NullClient:
        model = "software/null"
        def __call__(self, messages, tools):
            return AgentTurnOutput(text="Done")
    null = DockerFHIRAgentSUT(NullClient(), binding).respond(item)
    assert not score_trajectory(item, null.response)["passed"]
