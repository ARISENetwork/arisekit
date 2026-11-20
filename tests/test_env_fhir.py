"""FHIR environment: read/search, copy-on-write isolation, tool surface."""

from arisekit.env.fhir import FHIREnvironment, fhir_tools


def _bundle() -> dict:
    """A tiny R4 Bundle: one patient with one condition and two labs."""
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "p1",
                    "name": [{"family": "Hernandez", "given": ["Maria"]}],
                    "gender": "female",
                    "birthDate": "1958-03-12",
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "o-hba1c",
                    "status": "final",
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": "4548-4"}],
                        "text": "Hemoglobin A1c",
                    },
                    "subject": {"reference": "Patient/p1"},
                    "effectiveDateTime": "2026-04-10",
                    "valueQuantity": {"value": 9.2, "unit": "%"},
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "o-bp",
                    "status": "final",
                    "code": {"text": "Blood pressure"},
                    "subject": {"reference": "Patient/p1"},
                    "effectiveDateTime": "2025-01-05",
                    "valueString": "152/94 mmHg",
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "c-t2dm",
                    "clinicalStatus": {"coding": [{"code": "active"}]},
                    "code": {"text": "Type 2 diabetes"},
                    "subject": {"reference": "Patient/p1"},
                }
            },
        ],
    }


def test_read_returns_seed_resource():
    env = FHIREnvironment([_bundle()])
    patient = env.read("Patient", "p1")
    assert patient is not None
    assert patient["name"][0]["family"] == "Hernandez"
    assert env.read("Patient", "missing") is None


def test_search_by_patient_reference():
    env = FHIREnvironment([_bundle()])
    obs = env.search("Observation", patient="p1")
    assert {o["id"] for o in obs} == {"o-hba1c", "o-bp"}
    # A bare id and the Patient/<id> form both resolve.
    assert len(env.search("Observation", patient="Patient/p1")) == 2
    assert env.search("Observation", patient="p-nobody") == []


def test_search_by_code_and_status_and_clinical_status():
    env = FHIREnvironment([_bundle()])
    by_code = env.search("Observation", patient="p1", code="4548-4")
    assert [o["id"] for o in by_code] == ["o-hba1c"]

    active = env.search("Condition", patient="p1", clinical_status="active")
    assert [c["id"] for c in active] == ["c-t2dm"]
    assert env.search("Condition", patient="p1", clinical_status="resolved") == []


def test_search_by_date_range():
    env = FHIREnvironment([_bundle()])
    recent = env.search("Observation", patient="p1", start="2026-01-01")
    assert [o["id"] for o in recent] == ["o-hba1c"]
    windowed = env.search("Observation", patient="p1", start="2025-01-01", end="2025-12-31")
    assert [o["id"] for o in windowed] == ["o-bp"]


def test_none_params_are_ignored():
    env = FHIREnvironment([_bundle()])
    # Optional filters left as None should not exclude anything.
    obs = env.search("Observation", patient="p1", code=None, start=None, end=None)
    assert len(obs) == 2


def test_create_writes_to_overlay_and_reset_clears_it():
    env = FHIREnvironment([_bundle()])
    created = env.create(
        {
            "resourceType": "Task",
            "description": "Outreach for late refill",
            "for": {"reference": "Patient/p1"},
        }
    )
    # An id was assigned and the task is readable from the overlay.
    assert created["id"]
    assert env.read("Task", created["id"]) is not None
    assert len(env.search("Task", patient="p1")) == 1

    env.reset()
    # Overlay writes vanish, but the seed chart is untouched.
    assert env.read("Task", created["id"]) is None
    assert env.search("Task", patient="p1") == []
    assert env.read("Patient", "p1") is not None


def test_update_supersedes_seed_in_search():
    env = FHIREnvironment([_bundle()])
    env.update(
        {
            "resourceType": "Condition",
            "id": "c-t2dm",
            "clinicalStatus": {"coding": [{"code": "resolved"}]},
            "code": {"text": "Type 2 diabetes"},
            "subject": {"reference": "Patient/p1"},
        }
    )
    assert env.search("Condition", patient="p1", clinical_status="active") == []
    assert len(env.search("Condition", patient="p1", clinical_status="resolved")) == 1
    env.reset()
    assert len(env.search("Condition", patient="p1", clinical_status="active")) == 1


def test_fhir_tools_query_the_env():
    env = FHIREnvironment([_bundle()])
    tools = {t.name: t for t in fhir_tools(env)}
    assert set(tools) == {
        "get_patient",
        "search_observations",
        "search_conditions",
        "search_medication_requests",
        "list_allergies",
        "search_encounters",
        "search_tasks",
        "create_task",
    }
    # Every tool carries a json-schema parameters object.
    for tool in tools.values():
        assert tool.parameters["type"] == "object"

    patient = tools["get_patient"].fn(patient_id="p1")
    assert patient["name"][0]["family"] == "Hernandez"

    obs = tools["search_observations"].fn(patient_id="p1", code="4548-4")
    assert [o["id"] for o in obs] == ["o-hba1c"]

    task = tools["create_task"].fn(for_patient_id="p1", description="Follow up")
    assert task["resourceType"] == "Task"
    assert env.read("Task", task["id"]) is not None


def test_from_cohort_dir_loads_bundles(tmp_path):
    import json

    cohort = tmp_path / "cohort"
    cohort.mkdir()
    (cohort / "a.fhir.json").write_text(json.dumps(_bundle()))
    env = FHIREnvironment.from_cohort_dir(tmp_path)
    assert env.read("Patient", "p1") is not None
    assert len(env.search("Observation", patient="p1")) == 2


def test_restore_overlay_preserves_shared_allocation_position_and_prior_writes():
    uninterrupted = FHIREnvironment([_bundle()])
    first = uninterrupted.create({"resourceType": "Task", "description": "First"})
    observation = uninterrupted.create({"resourceType": "Observation", "valueString": "Recorded"})
    resumed = FHIREnvironment([_bundle()])
    resumed.restore_overlay(uninterrupted.overlay_snapshot())

    for environment in (uninterrupted, resumed):
        created = environment.create({"resourceType": "Task", "description": "Second"})
        assert created["id"] == "task-3"
        assert environment.read("Task", first["id"])["description"] == "First"
        assert environment.read("Observation", observation["id"])["valueString"] == "Recorded"
    assert resumed.overlay_snapshot() == uninterrupted.overlay_snapshot()


def test_allocator_skips_seed_ids_and_reserves_explicit_overlay_ids_on_resume():
    bundle = _bundle()
    bundle["entry"].extend([
        {"resource": {"resourceType": "Task", "id": "task-1", "description": "Seed one"}},
        {"resource": {"resourceType": "Task", "id": "task-6", "description": "Seed six"}},
    ])
    uninterrupted = FHIREnvironment([bundle])
    assert uninterrupted.create({"resourceType": "Task"})["id"] == "task-2"
    uninterrupted.create({"resourceType": "Task", "id": "task-4", "description": "Explicit"})
    uninterrupted.update({"resourceType": "Observation", "id": "observation-5", "valueString": "Updated"})
    resumed = FHIREnvironment([bundle])
    resumed.restore_overlay(uninterrupted.overlay_snapshot())

    for environment in (uninterrupted, resumed):
        assert environment.create({"resourceType": "Task"})["id"] == "task-7"
        assert environment.read("Task", "task-1")["description"] == "Seed one"
        assert environment.read("Task", "task-6")["description"] == "Seed six"
        assert environment.read("Task", "task-4")["description"] == "Explicit"
    assert resumed.overlay_snapshot() == uninterrupted.overlay_snapshot()


def test_reset_and_replacement_restore_reset_allocation_position():
    environment = FHIREnvironment([_bundle()])
    assert environment.create({"resourceType": "Task"})["id"] == "task-1"
    snapshot = environment.overlay_snapshot()
    environment.create({"resourceType": "Task"})
    environment.restore_overlay(snapshot)
    assert environment.create({"resourceType": "Task"})["id"] == "task-2"

    environment.reset()
    assert environment.overlay_snapshot() == []
    assert environment.create({"resourceType": "Task"})["id"] == "task-1"
    environment.restore_overlay([])
    assert environment.create({"resourceType": "Task"})["id"] == "task-1"
