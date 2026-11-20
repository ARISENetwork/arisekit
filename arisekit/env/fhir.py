"""In-memory FHIR R4 environment for agentic ARISEKit benchmarks.

A minimal FHIR sandbox: load a handful of R4 Bundles into an in-memory
store keyed by (resourceType, id), then let an agent read and search the
chart or write new resources back. The logic is translated from the
arisekitai workshop (lib/fhir/store.ts + search.ts): a copy-on-write
overlay isolates each run's mutations from the shared seed, so scoring
many trials never lets one run's writes leak into the next.

This is not a full FHIR server. It covers only the fields we display,
query, or hand to the agent (Patient, Observation, Condition,
MedicationRequest, AllergyIntolerance, Task, and friends). The store
holds plain dicts so everything stays JSON-serializable for the runner.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arisekit.common.jsonio import json_copy as _json_detach
from arisekit.types import Tool


class FHIREnvironment:
    """Copy-on-write in-memory FHIR store.

    Bundles seed an immutable base layer. Every create or update lands in
    a per-run overlay checked ahead of the seed, so `reset()` restores the
    original chart without ever mutating the seed. Reads consult the
    overlay first, then fall back to the seed; searches merge the overlay
    over the seed so a mutated resource supersedes its seed version.
    """

    def __init__(self, bundles: list[dict[str, Any]]):
        self._seed: dict[tuple[str, str], dict[str, Any]] = {}
        self._overlay: dict[tuple[str, str], dict[str, Any]] = {}
        self._id_counter: int = 0
        for bundle in bundles or []:
            self._load_bundle(bundle)

    def _load_bundle(self, bundle: dict[str, Any]) -> None:
        """Index every entry[].resource in one FHIR Bundle into the seed."""
        if not isinstance(bundle, dict):
            return
        for entry in bundle.get("entry", []) or []:
            resource = entry.get("resource") if isinstance(entry, dict) else None
            if not isinstance(resource, dict):
                continue
            rtype = resource.get("resourceType")
            rid = resource.get("id")
            if rtype and rid is not None:
                self._seed[(str(rtype), str(rid))] = resource

    # --- lifecycle ---------------------------------------------------

    def reset(self) -> None:
        """Drop every per-run mutation, restoring the seed chart."""
        self._overlay.clear()
        self._id_counter = 0

    def overlay_snapshot(self) -> list[dict[str, Any]]:
        """Return a detached, deterministic snapshot of per-run writes.

        Agent checkpoints already retain tool results. This explicit state
        surface lets a case-scoped SUT also reconstruct the exact terminal
        FHIR overlay when a run resumes after interruption.
        """
        return [
            _json_detach(resource)
            for _, resource in sorted(self._overlay.items(), key=lambda item: item[0])
        ]

    def restore_overlay(self, resources: list[dict[str, Any]]) -> None:
        """Replace the overlay with previously checkpointed FHIR resources."""
        restored: dict[tuple[str, str], dict[str, Any]] = {}
        for resource in resources:
            if not isinstance(resource, dict):
                raise TypeError("overlay resources must be FHIR JSON objects")
            rtype = resource.get("resourceType")
            rid = resource.get("id")
            if not rtype or not rid:
                raise ValueError(
                    "restored overlay resources require resourceType and id"
                )
            restored[(str(rtype), str(rid))] = _json_detach(resource)
        self._overlay = restored
        self._id_counter = self._overlay_allocation_position()

    def _overlay_allocation_position(self) -> int:
        """Recover the shared allocator from resource IDs retained in snapshots."""
        position = 0
        for rtype, rid in self._overlay:
            prefix = f"{rtype.lower()}-"
            suffix = rid.removeprefix(prefix)
            if (rid.startswith(prefix) and suffix.isascii() and suffix.isdecimal()
                    and not suffix.startswith("0")):
                position = max(position, int(suffix))
        return position

    # --- reads -------------------------------------------------------

    def read(self, resource_type: str, id: str) -> dict[str, Any] | None:
        """Fetch one resource by type and id (overlay wins over seed)."""
        key = (str(resource_type), str(id))
        if key in self._overlay:
            return self._overlay[key]
        return self._seed.get(key)

    def search(self, resource_type: str, **params: Any) -> list[dict[str, Any]]:
        """Return resources of a type matching every supplied parameter.

        Supported params: `patient` (or `subject`), `code`, `status`,
        `clinical-status` (also accepted as `clinical_status`), and a date
        range via `start` and `end`. Empty or None params are ignored, so
        callers can forward optional filters without pre-filtering them.
        """
        return [
            resource
            for resource in self._iter_type(str(resource_type))
            if _matches(resource, params)
        ]

    def _iter_type(self, resource_type: str) -> list[dict[str, Any]]:
        """Merge overlay over seed for one resource type."""
        merged: dict[str, dict[str, Any]] = {}
        for (rtype, rid), resource in self._seed.items():
            if rtype == resource_type:
                merged[rid] = resource
        for (rtype, rid), resource in self._overlay.items():
            if rtype == resource_type:
                merged[rid] = resource
        return list(merged.values())

    # --- writes ------------------------------------------------------

    def create(self, resource: dict[str, Any]) -> dict[str, Any]:
        """Write a new resource to the overlay, assigning an id if absent."""
        stored = dict(resource)
        rtype = stored.get("resourceType")
        if not rtype:
            raise ValueError("resource is missing resourceType")
        rid = stored.get("id")
        if not rid:
            # Explicit IDs in the generated namespace must reserve the same
            # position in uninterrupted runs and resource-only checkpoints.
            self._id_counter = max(self._id_counter, self._overlay_allocation_position())
            while True:
                self._id_counter += 1
                rid = f"{str(rtype).lower()}-{self._id_counter}"
                key = (str(rtype), rid)
                if key not in self._seed and key not in self._overlay:
                    break
            stored["id"] = rid
        self._overlay[(str(rtype), str(rid))] = stored
        return stored

    def update(self, resource: dict[str, Any]) -> dict[str, Any]:
        """Overwrite an existing resource in the overlay (id required)."""
        stored = dict(resource)
        rtype = stored.get("resourceType")
        rid = stored.get("id")
        if not rtype or not rid:
            raise ValueError("update requires both resourceType and id")
        self._overlay[(str(rtype), str(rid))] = stored
        return stored

    # --- loaders -----------------------------------------------------

    @classmethod
    def from_cohort_dir(cls, path: str | Path) -> "FHIREnvironment":
        """Load every cohort/*.fhir.json Bundle under a directory.

        Accepts either a directory that contains a `cohort/` subfolder or a
        directory that already is the cohort folder. Files are read in
        sorted order so the seed is deterministic across runs.
        """
        base = Path(path)
        cohort = base / "cohort" if (base / "cohort").is_dir() else base
        bundles: list[dict[str, Any]] = []
        for bundle_path in sorted(cohort.glob("*.fhir.json")):
            bundles.append(json.loads(bundle_path.read_text()))
        return cls(bundles)


# --- search matching (translated from lib/fhir/search.ts) ------------


def _matches(resource: dict[str, Any], params: dict[str, Any]) -> bool:
    """True when a resource satisfies every non-empty search param."""
    for key, value in params.items():
        if value is None or value == "":
            continue
        if not _matches_param(resource, key, value):
            return False
    return True


def _matches_param(resource: dict[str, Any], key: str, value: Any) -> bool:
    """Dispatch one search param to its field-specific matcher."""
    norm = str(key).replace("_", "-")
    if norm in ("patient", "subject"):
        return _ref_matches(resource, str(value).lower())
    if norm == "code":
        return _code_matches(resource, str(value).lower())
    if norm == "status":
        return str(resource.get("status", "")).lower() == str(value).lower()
    if norm == "clinical-status":
        return _clinical_status_matches(resource, str(value).lower())
    if norm in ("start", "date", "date-from"):
        return _date_gte(resource, str(value))
    if norm in ("end", "date-to"):
        return _date_lte(resource, str(value))
    # Unknown params are ignored rather than excluding everything.
    return True


def _ref_matches(resource: dict[str, Any], value: str) -> bool:
    """Match a patient/subject reference against a bare id or Patient/<id>."""
    targets = {value, f"patient/{value}"}
    candidates: list[str] = []
    for key in ("subject", "patient", "for", "beneficiary"):
        ref = resource.get(key)
        if isinstance(ref, dict) and ref.get("reference"):
            candidates.append(str(ref["reference"]))
    if resource.get("resourceType") == "Appointment":
        for participant in resource.get("participant", []) or []:
            actor = participant.get("actor") if isinstance(participant, dict) else None
            if isinstance(actor, dict) and actor.get("reference"):
                candidates.append(str(actor["reference"]))
    return any(ref.lower() in targets for ref in candidates)


def _code_matches(resource: dict[str, Any], value: str) -> bool:
    """Match on CodeableConcept text, coding code, or coding display."""
    code = resource.get("code")
    if not isinstance(code, dict):
        return False
    text = code.get("text")
    if isinstance(text, str) and value in text.lower():
        return True
    for coding in code.get("coding", []) or []:
        if not isinstance(coding, dict):
            continue
        if str(coding.get("code", "")).lower() == value:
            return True
        display = coding.get("display")
        if isinstance(display, str) and value in display.lower():
            return True
    return False


def _clinical_status_matches(resource: dict[str, Any], value: str) -> bool:
    """Match a Condition's clinicalStatus coding code."""
    clinical_status = resource.get("clinicalStatus")
    if not isinstance(clinical_status, dict):
        return False
    return any(
        str(coding.get("code", "")).lower() == value
        for coding in clinical_status.get("coding", []) or []
        if isinstance(coding, dict)
    )


def _extract_date(resource: dict[str, Any]) -> str | None:
    """Pull the most relevant date/datetime field off a resource."""
    for field in (
        "effectiveDateTime",
        "authoredOn",
        "recordedDate",
        "onsetDateTime",
        "occurrenceDateTime",
        "start",
        "created",
    ):
        value = resource.get(field)
        if isinstance(value, str) and value:
            return value
    period = resource.get("period")
    if isinstance(period, dict) and isinstance(period.get("start"), str):
        return period["start"]
    return None


def _date_gte(resource: dict[str, Any], bound: str) -> bool:
    """True when the resource date is on or after `bound` (inclusive lower)."""
    date = _extract_date(resource)
    if not date:
        return False
    # Compare on the shared prefix so a date-only bound (YYYY-MM-DD) still
    # matches a full ISO datetime on the same day.
    return date[: len(bound)].lower() >= bound.lower()


def _date_lte(resource: dict[str, Any], bound: str) -> bool:
    """True when the resource date is on or before `bound` (inclusive upper)."""
    date = _extract_date(resource)
    if not date:
        return False
    return date[: len(bound)].lower() <= bound.lower()


# --- tool surface (translated from lib/agent/tools.ts) ---------------


def fhir_tools(env: FHIREnvironment) -> list[Tool]:
    """Build a small MVP tool catalog whose fns close over one environment.

    The catalog covers the common MedAgentBench read/search surfaces and a
    constrained care-coordination write. Each tool returns plain dicts or
    lists so outputs stay JSON-serializable when fed back to the agent.
    """

    def get_patient(patient_id: str) -> dict[str, Any] | None:
        return env.read("Patient", patient_id)

    def search_observations(
        patient_id: str,
        code: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        return env.search(
            "Observation", patient=patient_id, code=code, start=start, end=end
        )

    def search_conditions(
        patient_id: str,
        clinical_status: str | None = None,
    ) -> list[dict[str, Any]]:
        return env.search(
            "Condition", patient=patient_id, clinical_status=clinical_status
        )

    def search_medication_requests(
        patient_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        return env.search("MedicationRequest", patient=patient_id, status=status)

    def list_allergies(patient_id: str) -> list[dict[str, Any]]:
        return env.search("AllergyIntolerance", patient=patient_id)

    def search_encounters(
        patient_id: str,
        status: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        return env.search(
            "Encounter", patient=patient_id, status=status, start=start, end=end
        )

    def search_tasks(
        patient_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        return env.search("Task", patient=patient_id, status=status)

    def create_task(
        for_patient_id: str,
        description: str,
        priority: str = "routine",
    ) -> dict[str, Any]:
        task = {
            "resourceType": "Task",
            "status": "ready",
            "intent": "plan",
            "priority": priority,
            "description": description,
            "for": {"reference": f"Patient/{for_patient_id}"},
            "authoredOn": datetime.now(timezone.utc).isoformat(),
        }
        return env.create(task)

    return [
        Tool(
            name="get_patient",
            description=(
                "Fetch full demographics for a single patient by their FHIR "
                "Patient.id."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "patient_id": {"type": "string", "description": "FHIR Patient.id"},
                },
                "required": ["patient_id"],
            },
            fn=get_patient,
        ),
        Tool(
            name="search_observations",
            description=(
                "Retrieve observations (vitals, labs, screenings) for a patient. "
                "Optionally filter by LOINC code or code text, and by a date "
                "range (start/end, ISO dates)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "patient_id": {"type": "string", "description": "FHIR Patient.id"},
                    "code": {
                        "type": "string",
                        "description": "LOINC code or partial text match.",
                    },
                    "start": {"type": "string", "description": "ISO date (YYYY-MM-DD)"},
                    "end": {"type": "string", "description": "ISO date (YYYY-MM-DD)"},
                },
                "required": ["patient_id"],
            },
            fn=search_observations,
        ),
        Tool(
            name="search_conditions",
            description=(
                "Retrieve conditions (diagnoses, problems) for a patient. Filter "
                "by clinical status (active, resolved, inactive)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "patient_id": {"type": "string", "description": "FHIR Patient.id"},
                    "clinical_status": {
                        "type": "string",
                        "enum": ["active", "resolved", "inactive"],
                    },
                },
                "required": ["patient_id"],
            },
            fn=search_conditions,
        ),
        Tool(
            name="search_medication_requests",
            description=(
                "Retrieve medication requests (current and historical "
                "prescriptions) for a patient. Filter by status."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "patient_id": {"type": "string", "description": "FHIR Patient.id"},
                    "status": {
                        "type": "string",
                        "enum": [
                            "active",
                            "on-hold",
                            "cancelled",
                            "completed",
                            "stopped",
                        ],
                    },
                },
                "required": ["patient_id"],
            },
            fn=search_medication_requests,
        ),
        Tool(
            name="list_allergies",
            description="Retrieve known allergies and intolerances for a patient.",
            parameters={
                "type": "object",
                "properties": {
                    "patient_id": {"type": "string", "description": "FHIR Patient.id"},
                },
                "required": ["patient_id"],
            },
            fn=list_allergies,
        ),
        Tool(
            name="search_encounters",
            description=(
                "Retrieve encounters for a patient. Optionally filter by FHIR "
                "Encounter.status and an ISO date range."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "patient_id": {"type": "string", "description": "FHIR Patient.id"},
                    "status": {
                        "type": "string",
                        "enum": [
                            "planned",
                            "arrived",
                            "triaged",
                            "in-progress",
                            "onleave",
                            "finished",
                            "cancelled",
                        ],
                    },
                    "start": {"type": "string", "description": "ISO date (YYYY-MM-DD)"},
                    "end": {"type": "string", "description": "ISO date (YYYY-MM-DD)"},
                },
                "required": ["patient_id"],
            },
            fn=search_encounters,
        ),
        Tool(
            name="search_tasks",
            description=(
                "Retrieve existing care-coordination tasks for a patient. "
                "Optionally filter by Task.status."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "patient_id": {"type": "string", "description": "FHIR Patient.id"},
                    "status": {
                        "type": "string",
                        "enum": [
                            "draft",
                            "requested",
                            "received",
                            "accepted",
                            "ready",
                            "in-progress",
                            "completed",
                            "cancelled",
                        ],
                    },
                },
                "required": ["patient_id"],
            },
            fn=search_tasks,
        ),
        Tool(
            name="create_task",
            description=(
                "Create a work task (outreach for a missed refill, follow-up "
                "call, or care coordination item). Writes to the per-run overlay."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "for_patient_id": {"type": "string", "description": "FHIR Patient.id"},
                    "description": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["routine", "urgent", "asap", "stat"],
                    },
                },
                "required": ["for_patient_id", "description"],
            },
            fn=create_task,
        ),
    ]
