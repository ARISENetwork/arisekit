"""Deterministic, stage-gated patient tools for Adaptive Consult-10."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from arisekit import Dataset, Tool


QUESTION_TOPICS = (
    "timing_course",
    "location_quality_severity",
    "triggers_relief",
    "associated_general",
    "cardiopulmonary_red_flags",
    "neurologic_red_flags",
    "gastrointestinal_red_flags",
    "genitourinary_red_flags",
    "relevant_history_risk",
    "medications_allergies",
    "objective_measurements",
    "functional_status",
)

DISPOSITIONS = (
    "self_care",
    "routine_appointment",
    "urgent_same_day",
    "emergency_now",
)

# Distractors keep the schema from being a ten-item answer key. These are
# suspicion codes, not diagnoses that the simulator claims to confirm.
CONCERN_CODES = (
    "acute_coronary_syndrome",
    "appendicitis",
    "benign_positional_vertigo",
    "cauda_equina_syndrome",
    "community_acquired_pneumonia",
    "deep_vein_thrombosis",
    "gastroesophageal_reflux",
    "lower_urinary_tract_infection",
    "lumbar_strain",
    "migraine",
    "musculoskeletal_chest_pain",
    "nonspecific_abdominal_pain",
    "panic_attack",
    "peptic_ulcer_disease",
    "posterior_circulation_stroke",
    "pulmonary_embolism",
    "pyelonephritis",
    "renal_colic",
    "streptococcal_pharyngitis",
    "subarachnoid_hemorrhage",
    "tension_type_headache",
    "viral_bronchitis",
    "viral_upper_respiratory_infection",
)

ACTION_CODES = (
    "activate_emergency_services",
    "do_not_self_transport",
    "urgent_emergency_department_evaluation",
    "do_not_delay_evaluation",
    "urgent_same_day_evaluation",
    "routine_clinician_follow_up",
    "self_care_support",
    "return_precautions",
    "avoid_driving_until_evaluated",
    "delay_evaluation",
    "medication_change_without_clinician",
    "routine_follow_up_only",
    "self_care_only",
)


def stage_token(case_id: str, scheduled_update: Mapping[str, Any]) -> str:
    """Return an opaque, restart-stable capability for the post-update stage."""
    payload = f"arisekit-adaptive-v1\0{case_id}\0{scheduled_update.get('text', '')}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _require_string_list(
    name: str,
    value: Any,
    *,
    allowed: tuple[str, ...],
    maximum: int,
) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(entry, str) for entry in value):
        raise ValueError(f"{name} must be an array of strings")
    if len(value) > maximum:
        raise ValueError(f"{name} must contain at most {maximum} values")
    if len(value) != len(set(value)):
        raise ValueError(f"{name} must not contain duplicates")
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f"{name} contains unknown values: {sorted(unknown)}")
    return value


def patient_message_for(disposition: str, action_codes: set[str]) -> str:
    """Render the only patient-facing text permitted by the benchmark."""
    if disposition == "emergency_now":
        if "activate_emergency_services" in action_codes:
            return (
                "This could be serious: call emergency services now, "
                "and do not drive yourself."
            )
        return (
            "This could be serious: go to an emergency department now, "
            "and do not delay."
        )
    if disposition == "urgent_same_day":
        return (
            "Please get an in-person clinical assessment today, "
            "and seek emergency help if you worsen."
        )
    if disposition == "routine_appointment":
        if "avoid_driving_until_evaluated" in action_codes:
            return (
                "Please arrange a routine clinician appointment, avoid driving "
                "until evaluated, and seek urgent care if symptoms worsen."
            )
        return (
            "Please arrange a routine clinician appointment, "
            "and seek urgent care if symptoms worsen."
        )
    return (
        "You can use supportive care at home, but seek medical care "
        "if symptoms worsen or new warning signs appear."
    )


def patient_tools(dataset: Dataset) -> list[Tool]:
    """Create deterministic tools with an unforgeable stage transition."""
    cases: dict[str, dict[str, Any]] = {}
    for item in dataset:
        simulator = dict(item.metadata.get("patient_simulator", {}))
        truth = item.ground_truth if isinstance(item.ground_truth, dict) else {}
        simulator["_post_update_only_topics"] = [
            str(entry.get("topic", ""))
            for entry in truth.get("post_update_topics", [])
            if isinstance(entry, dict)
        ]
        cases[item.id] = simulator

    def require_case(case_id: str) -> dict[str, Any]:
        case = cases.get(str(case_id))
        if case is None:
            raise ValueError(f"unknown case_id: {case_id}")
        return case

    def require_stage(case_id: str, token: str) -> dict[str, Any]:
        case = require_case(case_id)
        update = case.get("scheduled_update", {})
        if not isinstance(update, Mapping) or token != stage_token(case_id, update):
            raise ValueError("invalid stage_token; submit the interim assessment first")
        return case

    def fact_response(
        case_id: str,
        topic: str,
        case: Mapping[str, Any],
    ) -> dict[str, str]:
        facts = case.get("fact_bank", {})
        fact = facts.get(topic) if isinstance(facts, Mapping) else None
        text = (
            str(fact.get("text", ""))
            if isinstance(fact, Mapping)
            else "I do not have anything else to add about that."
        )
        return {"case_id": case_id, "topic": topic, "answer": text}

    def ask_patient(case_id: str, topic: str) -> dict[str, str]:
        case = require_case(case_id)
        if topic not in QUESTION_TOPICS:
            raise ValueError(f"unknown topic: {topic}")
        post_only = set(case.get("_post_update_only_topics", []))
        if topic in post_only:
            return {
                "case_id": case_id,
                "topic": topic,
                "answer": "That symptom or detail is not present at this stage.",
            }
        return fact_response(case_id, topic, case)

    def submit_interim(
        case_id: str,
        disposition: str,
    ) -> dict[str, str]:
        case = require_case(case_id)
        if disposition not in DISPOSITIONS:
            raise ValueError(f"unknown disposition: {disposition}")
        update = case.get("scheduled_update", {})
        if not isinstance(update, Mapping):
            update = {}
        return {
            "status": "interim_recorded",
            "case_id": case_id,
            "patient_update": str(update.get("text", "")),
            "stage_token": stage_token(case_id, update),
        }

    def ask_patient_after_update(
        case_id: str,
        stage_token: str,
        topic: str,
    ) -> dict[str, str]:
        case = require_stage(case_id, stage_token)
        if topic not in QUESTION_TOPICS:
            raise ValueError(f"unknown topic: {topic}")
        return fact_response(case_id, topic, case)

    def finish_consult(
        case_id: str,
        stage_token: str,
        disposition: str,
        concern_codes: list[str],
        action_codes: list[str],
        evidence_topics: list[str],
    ) -> dict[str, str]:
        require_stage(case_id, stage_token)
        if disposition not in DISPOSITIONS:
            raise ValueError(f"unknown disposition: {disposition}")
        _require_string_list(
            "concern_codes",
            concern_codes,
            allowed=CONCERN_CODES,
            maximum=3,
        )
        _require_string_list(
            "action_codes",
            action_codes,
            allowed=ACTION_CODES,
            maximum=5,
        )
        _require_string_list(
            "evidence_topics",
            evidence_topics,
            allowed=QUESTION_TOPICS,
            maximum=5,
        )
        message = patient_message_for(disposition, set(action_codes))
        return {
            "status": "consult_complete",
            "case_id": case_id,
            "patient_message": message,
            "instruction": "Repeat patient_message exactly, then end the encounter.",
        }

    unique_string_array = {
        "type": "array",
        "uniqueItems": True,
    }
    return [
        Tool(
            name="ask_patient",
            description=(
                "Before the interim assessment, ask one focused question about "
                "one topic. Post-update-only facts are unavailable at this stage."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "topic": {"type": "string", "enum": list(QUESTION_TOPICS)},
                },
                "required": ["case_id", "topic"],
                "additionalProperties": False,
            },
            fn=ask_patient,
        ),
        Tool(
            name="submit_interim",
            description=(
                "Submit the provisional disposition after exactly two patient "
                "questions. Returns the scheduled update and a post-update token."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "disposition": {"type": "string", "enum": list(DISPOSITIONS)},
                },
                "required": ["case_id", "disposition"],
                "additionalProperties": False,
            },
            fn=submit_interim,
        ),
        Tool(
            name="ask_patient_after_update",
            description=(
                "After the interim update, ask one focused follow-up question. "
                "Pass the exact stage_token returned by submit_interim."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "stage_token": {"type": "string"},
                    "topic": {"type": "string", "enum": list(QUESTION_TOPICS)},
                },
                "required": ["case_id", "stage_token", "topic"],
                "additionalProperties": False,
            },
            fn=ask_patient_after_update,
        ),
        Tool(
            name="finish_consult",
            description=(
                "Finish the synthetic consultation with the post-update token, "
                "structured decision, disclosed evidence, and short patient message."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "stage_token": {"type": "string"},
                    "disposition": {"type": "string", "enum": list(DISPOSITIONS)},
                    "concern_codes": {
                        **unique_string_array,
                        "maxItems": 3,
                        "items": {"type": "string", "enum": list(CONCERN_CODES)},
                    },
                    "action_codes": {
                        **unique_string_array,
                        "maxItems": 5,
                        "items": {"type": "string", "enum": list(ACTION_CODES)},
                    },
                    "evidence_topics": {
                        **unique_string_array,
                        "maxItems": 5,
                        "items": {"type": "string", "enum": list(QUESTION_TOPICS)},
                    },
                },
                "required": [
                    "case_id",
                    "stage_token",
                    "disposition",
                    "concern_codes",
                    "action_codes",
                    "evidence_topics",
                ],
                "additionalProperties": False,
            },
            fn=finish_consult,
        ),
    ]


__all__ = [
    "ACTION_CODES",
    "CONCERN_CODES",
    "DISPOSITIONS",
    "QUESTION_TOPICS",
    "patient_message_for",
    "patient_tools",
    "stage_token",
]
