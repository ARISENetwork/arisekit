"""Strict structural validation for Adaptive Consult-10 draft assets."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from arisekit import BenchmarkItem

from .environment import ACTION_CODES, CONCERN_CODES, DISPOSITIONS, QUESTION_TOPICS


UPDATE_CLASSES = ("escalating", "refining", "reassuring")
EXPECTED_CASE_COUNT = 10
EXPECTED_DISPOSITION_COUNTS = {
    "emergency_now": 4,
    "urgent_same_day": 3,
    "routine_appointment": 2,
    "self_care": 1,
}
OPAQUE_CASE_ID = re.compile(r"gm-\d{3}\Z")


@dataclass(frozen=True)
class ValidationIssue:
    item_id: str
    path: str
    message: str

    def __str__(self) -> str:
        location = f"{self.item_id}.{self.path}" if self.path else self.item_id
        return f"{location}: {self.message}"


def validate_items(items: Iterable[BenchmarkItem]) -> list[ValidationIssue]:
    """Return every structural error in the synthetic pilot assets."""
    rows = list(items)
    issues: list[ValidationIssue] = []
    ids = [item.id for item in rows]
    duplicate_ids = {item_id for item_id, count in Counter(ids).items() if count > 1}
    if len(rows) != EXPECTED_CASE_COUNT:
        issues.append(
            ValidationIssue(
                "benchmark",
                "items",
                f"expected {EXPECTED_CASE_COUNT} cases, found {len(rows)}",
            )
        )
    for duplicate_id in sorted(duplicate_ids):
        issues.append(ValidationIssue(duplicate_id, "id", "duplicate case ID"))

    for item in rows:
        issues.extend(_validate_item(item))

    disposition_counts = Counter(
        str(item.ground_truth.get("final_disposition", ""))
        for item in rows
        if isinstance(item.ground_truth, Mapping)
    )
    if dict(disposition_counts) != EXPECTED_DISPOSITION_COUNTS:
        issues.append(
            ValidationIssue(
                "benchmark",
                "case_mix",
                "final disposition counts must be "
                f"{EXPECTED_DISPOSITION_COUNTS}, found {dict(disposition_counts)}",
            )
        )
    return issues


def assert_valid_items(items: Iterable[BenchmarkItem]) -> None:
    """Raise one actionable error if any asset contract is invalid."""
    issues = validate_items(items)
    if issues:
        details = "\n".join(f"- {issue}" for issue in issues)
        raise ValueError(f"invalid general-medicine adaptive assets:\n{details}")


def _validate_item(item: BenchmarkItem) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def add(path: str, message: str) -> None:
        issues.append(ValidationIssue(item.id, path, message))

    if f"[case_id: {item.id}]" not in str(item.prompt):
        add("prompt", "must expose the exact case ID")
    if not OPAQUE_CASE_ID.fullmatch(item.id):
        add("id", "must be opaque and match gm-NNN")
    if item.attachments:
        add("attachments", "must be empty for this text-only pilot")

    metadata = item.metadata
    if metadata.get("status") != "synthetic_draft":
        add("metadata.status", "must be 'synthetic_draft'")
    if metadata.get("synthetic") is not True:
        add("metadata.synthetic", "must be true")
    if metadata.get("clinically_validated") is not False:
        add("metadata.clinically_validated", "must be false")
    if metadata.get("specialty") != "primary-internal-medicine":
        add("metadata.specialty", "must be 'primary-internal-medicine'")

    update_class = metadata.get("update_class")
    if update_class not in UPDATE_CLASSES:
        add("metadata.update_class", f"must be one of {UPDATE_CLASSES}")

    anchors = metadata.get("source_anchors")
    anchor_ids: set[str] = set()
    if not isinstance(anchors, list) or not anchors:
        add("metadata.source_anchors", "must be a non-empty list")
    else:
        for index, anchor in enumerate(anchors):
            path = f"metadata.source_anchors[{index}]"
            if not isinstance(anchor, Mapping):
                add(path, "must be an object")
                continue
            source_id = str(anchor.get("id", ""))
            if not source_id:
                add(f"{path}.id", "must be non-empty")
            elif source_id in anchor_ids:
                add(f"{path}.id", "must be unique within the case")
            anchor_ids.add(source_id)
            url = str(anchor.get("url", ""))
            if not url.startswith("https://"):
                add(f"{path}.url", "must be an HTTPS URL")

    simulator = metadata.get("patient_simulator")
    if not isinstance(simulator, Mapping):
        add("metadata.patient_simulator", "must be an object")
        return issues
    fact_bank = simulator.get("fact_bank")
    if not isinstance(fact_bank, Mapping):
        add("metadata.patient_simulator.fact_bank", "must be an object")
        fact_bank = {}
    update = simulator.get("scheduled_update")
    if not isinstance(update, Mapping):
        add("metadata.patient_simulator.scheduled_update", "must be an object")
        update = {}
    elif update.get("class") != update_class:
        add(
            "metadata.patient_simulator.scheduled_update.class",
            "must match metadata.update_class",
        )
    if not str(update.get("text", "")).strip():
        add("metadata.patient_simulator.scheduled_update.text", "must be non-empty")
    disclosed_topics = _string_list(update.get("disclosed_topics"))
    if not disclosed_topics:
        add(
            "metadata.patient_simulator.scheduled_update.disclosed_topics",
            "must identify at least one patient-visible topic",
        )
    elif (
        len(disclosed_topics) != len(set(disclosed_topics))
        or not set(disclosed_topics) <= set(QUESTION_TOPICS)
    ):
        add(
            "metadata.patient_simulator.scheduled_update.disclosed_topics",
            "must contain unique valid topics",
        )
    for topic in disclosed_topics:
        if topic not in fact_bank:
            add(
                "metadata.patient_simulator.scheduled_update.disclosed_topics",
                f"references topic without a fact-bank entry: {topic}",
            )
    _validate_source_ids(
        item.id,
        "metadata.patient_simulator.scheduled_update.source_ids",
        update.get("source_ids"),
        anchor_ids,
        issues,
    )

    truth = item.ground_truth
    if not isinstance(truth, Mapping):
        add("ground_truth", "must be an object")
        return issues
    if truth.get("schema_version") != "arisekit.general-medicine-dialogue-rubric.v1":
        add("ground_truth.schema_version", "has an unsupported value")
    if truth.get("review_status") != "synthetic_draft_unreviewed":
        add("ground_truth.review_status", "must remain synthetic_draft_unreviewed")
    if truth.get("clinically_validated") is not False:
        add("ground_truth.clinically_validated", "must be false")

    pre = _topic_entries(item.id, "ground_truth.pre_update_topics", truth.get("pre_update_topics"), issues)
    post = _topic_entries(item.id, "ground_truth.post_update_topics", truth.get("post_update_topics"), issues)
    if len(pre) != 2:
        add("ground_truth.pre_update_topics", "must contain exactly two topics")
    if len(post) > 3:
        add("ground_truth.post_update_topics", "must contain at most three topics")
    topics = [entry["topic"] for entry in pre + post]
    if len(topics) != len(set(topics)):
        add("ground_truth", "pre- and post-update topics must be unique")
    for topic in topics:
        if topic not in fact_bank:
            add(
                f"metadata.patient_simulator.fact_bank.{topic}",
                "must define every rubric topic",
            )
    for topic, fact in fact_bank.items():
        if topic not in QUESTION_TOPICS:
            add(
                f"metadata.patient_simulator.fact_bank.{topic}",
                "is not in the global topic vocabulary",
            )
            continue
        if not isinstance(fact, Mapping):
            add(f"metadata.patient_simulator.fact_bank.{topic}", "must be an object")
            continue
        if not str(fact.get("text", "")).strip():
            add(f"metadata.patient_simulator.fact_bank.{topic}.text", "must be non-empty")
        _validate_source_ids(
            item.id,
            f"metadata.patient_simulator.fact_bank.{topic}.source_ids",
            fact.get("source_ids"),
            anchor_ids,
            issues,
        )

    interim = truth.get("acceptable_interim_dispositions")
    interim_values = (
        [str(value) for value in interim]
        if isinstance(interim, list)
        else []
    )
    if not interim_values:
        add("ground_truth.acceptable_interim_dispositions", "must be non-empty")
    elif any(value not in DISPOSITIONS for value in interim_values):
        add(
            "ground_truth.acceptable_interim_dispositions",
            "contains an unknown disposition",
        )
    final_disposition = str(truth.get("final_disposition", ""))
    if final_disposition not in DISPOSITIONS:
        add("ground_truth.final_disposition", "contains an unknown disposition")
    elif interim_values and update_class in UPDATE_CLASSES:
        _validate_update_direction(
            item.id,
            str(update_class),
            interim_values,
            final_disposition,
            issues,
        )

    concerns = _string_list(truth.get("accepted_concern_codes"))
    if not concerns:
        add("ground_truth.accepted_concern_codes", "must be non-empty")
    elif not set(concerns) <= set(CONCERN_CODES):
        add("ground_truth.accepted_concern_codes", "contains an unknown concern code")

    required_actions = _string_list(truth.get("required_action_codes"))
    prohibited_actions = _string_list(truth.get("prohibited_action_codes"))
    if not required_actions:
        add("ground_truth.required_action_codes", "must be non-empty")
    if not set(required_actions) <= set(ACTION_CODES):
        add("ground_truth.required_action_codes", "contains an unknown action code")
    if not set(prohibited_actions) <= set(ACTION_CODES):
        add("ground_truth.prohibited_action_codes", "contains an unknown action code")
    overlap = set(required_actions) & set(prohibited_actions)
    if overlap:
        add(
            "ground_truth",
            f"required and prohibited actions overlap: {sorted(overlap)}",
        )

    _validate_source_ids(
        item.id,
        "ground_truth.source_ids",
        truth.get("source_ids"),
        anchor_ids,
        issues,
    )
    return issues


def _topic_entries(
    item_id: str,
    path: str,
    value: Any,
    issues: list[ValidationIssue],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        issues.append(ValidationIssue(item_id, path, "must be a list"))
        return []
    entries: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        entry_path = f"{path}[{index}]"
        if not isinstance(raw, Mapping):
            issues.append(ValidationIssue(item_id, entry_path, "must be an object"))
            continue
        topic = str(raw.get("topic", ""))
        if topic not in QUESTION_TOPICS:
            issues.append(
                ValidationIssue(item_id, f"{entry_path}.topic", "is not a valid topic")
            )
        weight = raw.get("weight")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or weight <= 0
        ):
            issues.append(
                ValidationIssue(
                    item_id,
                    f"{entry_path}.weight",
                    "must be a positive number",
                )
            )
        if not isinstance(raw.get("critical"), bool):
            issues.append(
                ValidationIssue(
                    item_id,
                    f"{entry_path}.critical",
                    "must be boolean",
                )
            )
        entries.append(dict(raw))
    return entries


def _validate_source_ids(
    item_id: str,
    path: str,
    value: Any,
    anchor_ids: set[str],
    issues: list[ValidationIssue],
) -> None:
    source_ids = _string_list(value)
    if not source_ids:
        issues.append(ValidationIssue(item_id, path, "must be a non-empty list"))
        return
    missing = sorted(set(source_ids) - anchor_ids)
    if missing:
        issues.append(
            ValidationIssue(
                item_id,
                path,
                f"references undeclared source IDs: {missing}",
            )
        )


def _validate_update_direction(
    item_id: str,
    update_class: str,
    interim: list[str],
    final: str,
    issues: list[ValidationIssue],
) -> None:
    ranks = {value: index for index, value in enumerate(DISPOSITIONS)}
    final_rank = ranks[final]
    interim_ranks = [ranks[value] for value in interim if value in ranks]
    if update_class == "escalating" and any(final_rank <= rank for rank in interim_ranks):
        issues.append(
            ValidationIssue(
                item_id,
                "ground_truth.acceptable_interim_dispositions",
                "escalating cases require every interim disposition below the final",
            )
        )
    if update_class == "reassuring" and any(final_rank > rank for rank in interim_ranks):
        issues.append(
            ValidationIssue(
                item_id,
                "ground_truth.acceptable_interim_dispositions",
                "reassuring cases cannot escalate above an acceptable interim disposition",
            )
        )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(entry) for entry in value if isinstance(entry, str) and entry]


__all__ = [
    "EXPECTED_CASE_COUNT",
    "EXPECTED_DISPOSITION_COUNTS",
    "UPDATE_CLASSES",
    "ValidationIssue",
    "assert_valid_items",
    "validate_items",
]
