"""Synthetic transport controls for the explicitly audited native scorer."""
import copy
import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from arisekit.env.docker_fhir import digest
from arisekit.fhir.fhir_native import (audit, freeze, verify, native_tools, NativeTransport,
    evaluate_native, FAMILIES, SCORER_FILE, native_state_digest)
from arisekit.types import Trajectory, Turn


@pytest.fixture
def source():
    value = os.environ.get("ARISEKIT_NATIVE_SOURCE")
    if not value:
        pytest.skip("Set ARISEKIT_NATIVE_SOURCE to an authorized native checkout")
    return Path(value)


def test_native_release_has_all_ten_families_and_refuses_drift(source, tmp_path):
    binding = freeze(source, tmp_path / "binding.json")
    assert binding["cases"] == 300 and len(binding["families"]) == len(FAMILIES) == 10
    verify(source, binding)
    binding["files"]["src/tool/finish.py"] = "0" * 64
    with pytest.raises(ValueError, match="drifted"):
        verify(source, binding)


def test_native_original_tool_schemas_and_calculator_boundary(source):
    tools = native_tools(source, NativeTransport("http://127.0.0.1:1/fhir"))
    assert len(tools) == 11 and tools[-1].name == "finish"
    calculator = next(tool for tool in tools if tool.name == "calculator")
    assert calculator.fn(expression="sum([1, 2, 3])") == 6
    assert calculator.fn(expression="(datetime.date(2023, 11, 13) - datetime.date(2023, 11, 12)).days") == 1
    assert calculator.fn(expression="Decimal('1.2') * 3") == 3.6
    with pytest.raises(ValueError, match="private attributes"):
        calculator.fn(expression="(1).__class__.__base__.__subclasses__()")
    for expression in ('"{0.__loader__}".format(datetime)', "datetime.sys.modules", "2 ** 100000000", "[1] * 100000000000"):
        with pytest.raises(ValueError):
            calculator.fn(expression=expression)


def test_native_toolsets_keep_independent_transports(source, monkeypatch):
    import requests
    observed = []
    def request(session, method, url, **kwargs):
        observed.append(url)
        value = {"resourceType": "Bundle", "entry": []}
        return SimpleNamespace(content=json.dumps(value).encode(), json=lambda: value,
            status_code=200, raise_for_status=lambda: None)
    monkeypatch.setattr(requests.Session, "request", request)
    first = native_tools(source, NativeTransport("http://127.0.0.1:1/fhir"))
    second = native_tools(source, NativeTransport("http://127.0.0.1:2/fhir"))
    for tools in (first, second):
        next(tool for tool in tools if tool.name == "patient_search").fn(identifier="synthetic", family=None, given=None, birthdate=None)
    assert observed == ["http://127.0.0.1:1/fhir/Patient", "http://127.0.0.1:2/fhir/Patient"]


@pytest.mark.parametrize("category", range(1, 11))
def test_native_ten_family_positive_and_null_controls(source, monkeypatch, category):
    base = "http://127.0.0.1:1/fhir"
    stamp = "2023-11-13T10:15:00+00:00"
    patient = {"reference": "Patient/synthetic-p"}
    def request(session, method, url, **kwargs):
        assert method == "GET" and kwargs["headers"]["Cache-Control"] == "no-cache"
        if "/Patient?" in url:
            resources = [{"resourceType": "Patient", "birthDate": "1980-01-01"}]
        else:
            values = [1.6] if "code=MG" in url else [3.0] if "code=K" in url else [100, 200] if "code=GLU" in url else [6.6]
            resources = [{"resourceType": "Observation", "effectiveDateTime": stamp,
                "valueQuantity": {"value": value}} for value in values]
            if len(resources) == 2:
                resources[0]["effectiveDateTime"] = "2023-11-13T09:15:00+00:00"
        value = {"resourceType": "Bundle", "entry": [{"resource": resource} for resource in resources]}
        return SimpleNamespace(text=json.dumps(value), content=json.dumps(value).encode(), json=lambda: value, headers={"Content-Type": "application/fhir+json"},
            status_code=200, raise_for_status=lambda: None)
    import requests
    monkeypatch.setattr(requests.Session, "request", request)
    task = {"id": f"task{category}_synthetic", "eval_MRN": "synthetic-p", "sol": ["synthetic-p"]}
    medication = {"resourceType": "MedicationRequest", "medicationCodeableConcept": {"coding": [{"system": "http://hl7.org/fhir/sid/ndc", "code": "0338-1715-40"}]},
        "authoredOn": stamp, "status": "active", "intent": "order", "subject": patient,
        "dosageInstruction": [{"route": "IV", "doseAndRate": [{"doseQuantity": {"value": 1, "unit": "g"}, "rateQuantity": {"value": 1, "unit": "h"}}]}]}
    service = {"resourceType": "ServiceRequest", "code": {"coding": [{"system": "http://snomed.info/sct", "code": "306181000000106"}]},
        "authoredOn": stamp, "status": "active", "intent": "order", "priority": "stat", "subject": patient,
        "note": {"text": next(node.value for node in ast.walk(ast.parse((source / SCORER_FILE).read_text()))
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("Situation:"))}}
    observation = {"resourceType": "Observation", "category": [{"coding": [{"system": "http://hl7.org/fhir/observation-category", "code": "vital-signs", "display": "Vital Signs"}]}],
        "code": {"text": "BP"}, "effectiveDateTime": stamp, "status": "final", "valueString": "118/77 mmHg", "subject": patient}
    posts = []
    if category == 3:
        posts = [("Observation", observation)]
    elif category == 5:
        posts = [("MedicationRequest", medication)]
    elif category == 8:
        posts = [("ServiceRequest", service)]
    elif category == 9:
        medication = copy.deepcopy(medication)
        medication["medicationCodeableConcept"]["coding"][0]["code"] = "40032-917-01"
        medication["dosageInstruction"] = [{"route": "oral", "doseAndRate": [{"doseQuantity": {"value": 50, "unit": "mEq"}}]}]
        service = copy.deepcopy(service)
        service["code"] = {"coding": [{"system": "http://loinc.org", "code": "2823-3"}]}
        service["occurrenceDateTime"] = "2023-11-14T08:00:00+00:00"
        posts = [("MedicationRequest", medication), ("ServiceRequest", service)]
    history = []
    for resource_type, payload in posts:
        history.extend([{"role": "agent", "content": f"POST {base}/{resource_type}\n" + json.dumps(payload)},
                        {"role": "agent", "content": "POST request accepted"}])
    history.append({"role": "agent", "content": "finish([-1])"})
    answers = {1: ["synthetic-p"], 2: [43], 3: [-1], 4: [1.6], 5: [-1], 6: [150], 7: [200], 8: [-1], 9: [-1], 10: [6.6, stamp]}
    def trajectory(answer, accepted):
        state = {"complete": True, "writes": [], "history": accepted}
        state["state_sha256"] = native_state_digest(state)
        return Trajectory(final_response=answer, turns=[Turn("native_environment", state)])
    assert evaluate_native(source, task, trajectory(answers[category], history), base)
    # The historical HbA1c scorer explicitly accepts [] for a recent result.
    assert evaluate_native(source, task, trajectory([], []), base) is (category == 10)


def test_native_docker_write_recovers_in_fresh_baseline(source, tmp_path):
    if os.environ.get("ARISEKIT_TEST_NATIVE_DOCKER") != "1":
        pytest.skip("Set ARISEKIT_TEST_NATIVE_DOCKER=1 for two real native containers")
    from arisekit.fhir.fhir_native import NativeMedAgentSUT
    from arisekit.agentic import AgentTurnOutput
    from arisekit.types import BenchmarkItem
    binding = freeze(source, tmp_path / "binding.json")
    sut = NativeMedAgentSUT(source, binding, "openai/gpt-4.1")
    task = sut.tasks["task3_1"]
    payload = {"resourceType": "Observation", "category": [{"coding": [{"system": "http://hl7.org/fhir/observation-category", "code": "vital-signs", "display": "Vital Signs"}]}],
        "code": {"text": "BP"}, "effectiveDateTime": "2023-11-13T10:15:00+00:00", "status": "final",
        "valueString": "118/77 mmHg", "subject": {"reference": "Patient/" + task["eval_MRN"]}}
    dispatched = []
    def control(messages, tools):
        completed = sum(message["role"] == "tool" for message in messages)
        action = {"name": "fhir_vitals_create", "arguments": payload} if completed == 0 else {"name": "finish", "arguments": {"value": [-1]}}
        dispatched.append(action["name"])
        return AgentTurnOutput(tool_calls=[{"id": f"control-{completed}", **action}])
    sut.client = control
    item = BenchmarkItem(task["id"], task["instruction"] + "\n" + task["context"], None)
    saved = None
    class Interrupted(BaseException):
        pass
    def checkpoint(value):
        nonlocal saved
        saved = value
        if any(turn.role == "tool_result" for turn in value.response.turns):
            from datetime import datetime
            age_task = sut.tasks["task2_1"]
            state = next(turn.content for turn in value.response.turns if turn.role == "native_environment")
            transport = NativeTransport(state["base_url"])
            chart = transport.get(state["base_url"] + "/Patient", params={"identifier": age_task["eval_MRN"]}, headers=None).json()
            dob = datetime.strptime(chart["entry"][0]["resource"]["birthDate"], "%Y-%m-%d")
            today = datetime(2023, 11, 13)
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            age_state = {"complete": True, "writes": [], "history": []}
            age_state["state_sha256"] = native_state_digest(age_state)
            assert evaluate_native(source, age_task, Trajectory(final_response=[age], turns=[Turn("native_environment", age_state)]), state["base_url"])
            raise Interrupted()
    with pytest.raises(Interrupted):
        sut.respond_checkpointed(item, trial=1, on_checkpoint=checkpoint)
    first = next(turn.content for turn in saved.response.turns if turn.role == "native_environment")
    response = sut.respond_checkpointed(item, trial=1, resume_from=saved).response
    state = next(turn.content for turn in response.turns if turn.role == "native_environment")
    verdict = next(turn.content for turn in response.turns if turn.role == "native_verdict")
    assert verdict["passed"] and len(state["writes"]) == 1
    assert state["base_url"] != first["base_url"]
    assert dispatched == ["fhir_vitals_create", "finish"] and response.total_cost == 0


def test_native_route_wire_shape_preserves_logical_scoring_payload(monkeypatch):
    import requests
    submitted = []
    def request(session, method, url, **kwargs):
        submitted.append(kwargs["json"])
        assert kwargs["json"]["dosageInstruction"][0]["route"] == {"text": "IV"}
        value = {**kwargs["json"], "id": "created"}
        return SimpleNamespace(content=json.dumps(value).encode(), json=lambda: value,
            status_code=201, raise_for_status=lambda: None)
    monkeypatch.setattr(requests.Session, "request", request)
    transport = NativeTransport("http://127.0.0.1:1/fhir")
    transport.post(transport.base + "/MedicationRequest", json={"resourceType": "MedicationRequest", "dosageInstruction": [{"route": "IV"}]})
    logical = json.loads(transport.history[0]["content"].split("\n", 1)[1])
    assert logical["dosageInstruction"][0]["route"] == "IV"
    assert transport.writes[0]["dosageInstruction"][0]["route"] == {"text": "IV"}
    assert transport.wire_requests[0]["submitted_fhir_payload"] == submitted[0]
