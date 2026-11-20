"""Deterministic trajectory scoring for Adaptive Consult-10."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from arisekit import BaseScorer, BenchmarkItem, Metric, RunResult, Trajectory

from .environment import (
    ACTION_CODES,
    CONCERN_CODES,
    DISPOSITIONS,
    QUESTION_TOPICS,
    patient_message_for,
    stage_token,
)


@dataclass(frozen=True)
class ToolEvent:
    turn: int
    name: str
    arguments: dict[str, Any]
    calls_in_turn: int
    succeeded: bool


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _events(trajectory: Trajectory) -> list[ToolEvent]:
    events: list[ToolEvent] = []
    assistant_turn = -1
    for index, turn in enumerate(trajectory.turns):
        if turn.role != "assistant":
            continue
        assistant_turn += 1
        content = turn.content
        if not isinstance(content, dict):
            continue
        calls = content.get("tool_calls", [])
        if not isinstance(calls, list):
            continue
        results: list[dict[str, Any]] = []
        for later in trajectory.turns[index + 1 :]:
            if later.role == "assistant":
                break
            if later.role == "tool_result" and isinstance(later.content, dict):
                results.append(later.content)
        used_results: set[int] = set()
        for call in calls:
            if not isinstance(call, dict):
                events.append(
                    ToolEvent(
                        turn=assistant_turn,
                        name="",
                        arguments={},
                        calls_in_turn=len(calls),
                        succeeded=False,
                    )
                )
                continue
            arguments = call.get("arguments")
            matched_result: dict[str, Any] | None = None
            for result_index, result in enumerate(results):
                if result_index in used_results:
                    continue
                if (
                    result.get("id") == call.get("id")
                    and result.get("name") == call.get("name")
                ):
                    matched_result = result
                    used_results.add(result_index)
                    break
            result_value = (
                matched_result.get("result")
                if matched_result is not None
                else None
            )
            succeeded = matched_result is not None and not (
                isinstance(result_value, dict) and "error" in result_value
            )
            events.append(
                ToolEvent(
                    turn=assistant_turn,
                    name=str(call.get("name", "")),
                    arguments=dict(arguments) if isinstance(arguments, dict) else {},
                    calls_in_turn=len(calls),
                    succeeded=succeeded,
                )
            )
    return events


def _as_trajectory(response: Any) -> Trajectory:
    if isinstance(response, Trajectory):
        return response
    if isinstance(response, dict) and response.get("kind") == "trajectory":
        return Trajectory.from_dict(response)
    return Trajectory()


def _weighted_topic_score(
    required: list[dict[str, Any]],
    disclosed: set[str],
) -> tuple[float, float]:
    total_weight = 0.0
    obtained_weight = 0.0
    critical: list[str] = []
    for entry in required:
        topic = str(entry.get("topic", ""))
        weight = float(entry.get("weight", 1.0))
        total_weight += weight
        if topic in disclosed:
            obtained_weight += weight
        if entry.get("critical") is True:
            critical.append(topic)
    weighted = obtained_weight / total_weight if total_weight else 1.0
    critical_recall = (
        sum(1 for topic in critical if topic in disclosed) / len(critical)
        if critical
        else 1.0
    )
    return weighted, critical_recall


def _valid_string_set(
    value: Any,
    *,
    allowed: tuple[str, ...],
    maximum: int,
) -> tuple[set[str], bool]:
    if not isinstance(value, list):
        return set(), False
    if any(not isinstance(entry, str) for entry in value):
        return set(), False
    values = set(value)
    valid = (
        len(value) == len(values)
        and len(value) <= maximum
        and values <= set(allowed)
    )
    return values, valid


def _assistant_text(turn: Any) -> str:
    if isinstance(turn.content, str):
        return turn.content.strip()
    if isinstance(turn.content, Mapping):
        return str(turn.content.get("text") or "").strip()
    return ""


def _expected_stage_token(item: BenchmarkItem) -> str:
    simulator = item.metadata.get("patient_simulator", {})
    update = (
        simulator.get("scheduled_update", {})
        if isinstance(simulator, Mapping)
        else {}
    )
    return stage_token(item.id, update if isinstance(update, Mapping) else {})


def _scheduled_update_topics(item: BenchmarkItem) -> set[str]:
    simulator = item.metadata.get("patient_simulator", {})
    update = (
        simulator.get("scheduled_update", {})
        if isinstance(simulator, Mapping)
        else {}
    )
    topics = update.get("disclosed_topics", []) if isinstance(update, Mapping) else []
    if not isinstance(topics, list):
        return set()
    return {
        str(topic)
        for topic in topics
        if isinstance(topic, str) and topic in QUESTION_TOPICS
    }


def _trial_scores(item: BenchmarkItem, result: RunResult) -> dict[str, float]:
    metric_names = (
        "structured_contract_completion",
        "essential_information_recall",
        "pre_update_information_recall",
        "post_update_information_recall",
        "critical_topic_recall",
        "duplicate_free_questioning",
        "update_score",
        "protocol_adherence",
        "disposition_exact",
        "undertriage_avoidance",
        "overtriage_avoidance",
        "critical_concern_recall",
        "concern_precision",
        "required_action_recall",
        "action_precision",
        "prohibited_action_avoidance",
        "supported_evidence",
        "canonical_patient_message",
    )
    zero = dict.fromkeys(metric_names, 0.0)
    if result.error is not None:
        return zero

    truth = item.ground_truth if isinstance(item.ground_truth, dict) else {}
    trajectory = _as_trajectory(result.response)
    events = _events(trajectory)
    successful = [event for event in events if event.succeeded]
    pre_asks = [event for event in successful if event.name == "ask_patient"]
    post_asks = [
        event
        for event in successful
        if event.name == "ask_patient_after_update"
    ]
    interims = [
        event for event in successful if event.name == "submit_interim"
    ]
    finishes = [
        event for event in successful if event.name == "finish_consult"
    ]
    interim = interims[-1] if interims else None
    finish = finishes[-1] if finishes else None

    interim_turn = interim.turn if interim is not None else -1
    finish_turn = finish.turn if finish is not None else 10**9
    pre_sequence = [
        str(event.arguments.get("topic", ""))
        for event in pre_asks
        if event.turn < interim_turn
    ]
    post_sequence = [
        str(event.arguments.get("topic", ""))
        for event in post_asks
        if interim_turn < event.turn < finish_turn
    ]
    update_topics = _scheduled_update_topics(item)
    pre_disclosed = {topic for topic in pre_sequence if topic}
    post_disclosed = {topic for topic in post_sequence if topic} | update_topics
    disclosed = pre_disclosed | post_disclosed

    pre_required = list(truth.get("pre_update_topics", []))
    post_required = list(truth.get("post_update_topics", []))
    pre_recall, pre_critical = _weighted_topic_score(pre_required, pre_disclosed)
    post_recall, post_critical = _weighted_topic_score(
        post_required,
        post_disclosed,
    )
    information_recall, critical_recall = _weighted_topic_score(
        pre_required + post_required,
        disclosed,
    )

    disclosed_sequence = pre_sequence + post_sequence
    duplicate_count = sum(
        count - 1 for count in Counter(disclosed_sequence).values() if count > 1
    )
    duplicate_free = (
        max(0.0, 1.0 - duplicate_count / len(disclosed_sequence))
        if disclosed_sequence
        else 0.0
    )

    assistant_turns = [
        turn for turn in trajectory.turns if turn.role == "assistant"
    ]
    single_call_turns = all(event.calls_in_turn == 1 for event in events)
    known_calls_only = all(
        event.name
        in {
            "ask_patient",
            "submit_interim",
            "ask_patient_after_update",
            "finish_consult",
        }
        for event in events
    )
    all_calls_succeeded = all(event.succeeded for event in events)
    correct_case_ids = all(
        str(event.arguments.get("case_id", "")) == item.id for event in events
    )
    ordered = (
        interim is not None
        and finish is not None
        and interim.turn < finish.turn
    )
    correct_phase = (
        ordered
        and all(event.turn < interim.turn for event in pre_asks)
        and all(interim.turn < event.turn < finish.turn for event in post_asks)
    )
    expected_token = _expected_stage_token(item)
    correct_stage_tokens = (
        finish is not None
        and finish.arguments.get("stage_token") == expected_token
        and all(
            event.arguments.get("stage_token") == expected_token
            for event in post_asks
        )
    )
    tool_events_after_finish = (
        [event for event in events if finish is not None and event.turn > finish.turn]
        if finish is not None
        else []
    )
    final_turn = assistant_turns[-1] if assistant_turns else None
    final_turn_has_calls = (
        isinstance(final_turn.content, dict)
        and bool(final_turn.content.get("tool_calls"))
        if final_turn is not None
        else False
    )
    one_call_or_terminal_per_assistant = len(assistant_turns) == len(events) + 1
    no_intermediate_prose = all(
        not _assistant_text(turn) for turn in assistant_turns[:-1]
    )

    final_args = finish.arguments if finish is not None else {}
    actions, actions_valid = _valid_string_set(
        final_args.get("action_codes"),
        allowed=ACTION_CODES,
        maximum=5,
    )
    final_disposition = str(final_args.get("disposition", ""))
    expected_message = patient_message_for(final_disposition, actions)
    canonical_message = (
        finish is not None
        and actions_valid
        and isinstance(trajectory.final_response, str)
        and trajectory.final_response.strip() == expected_message
        and final_turn is not None
        and _assistant_text(final_turn) == expected_message
        and not final_turn_has_calls
    )
    terminal_response = finish is not None and canonical_message
    protocol = (
        single_call_turns
        and known_calls_only
        and all_calls_succeeded
        and correct_case_ids
        and len(interims) == 1
        and len(finishes) == 1
        and ordered
        and correct_phase
        and correct_stage_tokens
        and len(pre_asks) == 2
        and len(post_asks) <= 3
        and len(pre_asks) + len(post_asks) <= 5
        and not tool_events_after_finish
        and one_call_or_terminal_per_assistant
        and no_intermediate_prose
        and terminal_response
    )

    interim_args = interim.arguments if interim is not None else {}
    interim_disposition = str(interim_args.get("disposition", ""))
    target_disposition = str(truth.get("final_disposition", ""))
    accepted_interim = {
        str(value) for value in truth.get("acceptable_interim_dispositions", [])
    }
    disposition_exact = final_disposition == target_disposition
    update_score = interim_disposition in accepted_interim and disposition_exact

    ranks = {value: index for index, value in enumerate(DISPOSITIONS)}
    target_rank = ranks.get(target_disposition)
    final_rank = ranks.get(final_disposition)
    undertriage_avoidance = (
        target_rank is not None and final_rank is not None and final_rank >= target_rank
    )
    overtriage_avoidance = (
        target_rank is not None and final_rank is not None and final_rank <= target_rank
    )

    concerns, concerns_valid = _valid_string_set(
        final_args.get("concern_codes"),
        allowed=CONCERN_CODES,
        maximum=3,
    )
    accepted_concerns = {
        str(value) for value in truth.get("accepted_concern_codes", [])
    }
    concern_recall = bool(concerns & accepted_concerns)
    concern_precision = (
        len(concerns & accepted_concerns) / len(concerns)
        if concerns
        else 0.0
    )
    concern_contract = (
        concerns_valid and concern_recall and concern_precision == 1.0
    )

    required_actions = {
        str(value) for value in truth.get("required_action_codes", [])
    }
    prohibited_actions = {
        str(value) for value in truth.get("prohibited_action_codes", [])
    }
    action_recall = (
        len(actions & required_actions) / len(required_actions)
        if required_actions
        else 1.0
    )
    action_precision = (
        len(actions & required_actions) / len(actions)
        if actions
        else float(not required_actions)
    )
    prohibited_avoidance = not bool(actions & prohibited_actions)
    action_contract = (
        actions_valid
        and action_recall == 1.0
        and action_precision == 1.0
        and prohibited_avoidance
    )

    evidence_topics, evidence_valid = _valid_string_set(
        final_args.get("evidence_topics"),
        allowed=QUESTION_TOPICS,
        maximum=5,
    )
    critical_topics = {
        str(entry.get("topic", ""))
        for entry in pre_required + post_required
        if isinstance(entry, Mapping) and entry.get("critical") is True
    }
    required_evidence = critical_topics & disclosed
    supported_evidence = (
        evidence_valid
        and bool(evidence_topics)
        and evidence_topics <= disclosed
        and required_evidence <= evidence_topics
    )

    complete = (
        protocol
        and disposition_exact
        and concern_contract
        and action_contract
        and critical_recall == 1.0
        and supported_evidence
        and update_score
        and canonical_message
    )
    return {
        "structured_contract_completion": float(complete),
        "essential_information_recall": information_recall,
        "pre_update_information_recall": pre_recall,
        "post_update_information_recall": post_recall,
        "critical_topic_recall": critical_recall,
        "duplicate_free_questioning": duplicate_free,
        "update_score": float(update_score),
        "protocol_adherence": float(protocol),
        "disposition_exact": float(disposition_exact),
        "undertriage_avoidance": float(undertriage_avoidance),
        "overtriage_avoidance": float(overtriage_avoidance),
        "critical_concern_recall": float(concern_recall),
        "concern_precision": concern_precision,
        "required_action_recall": action_recall,
        "action_precision": action_precision,
        "prohibited_action_avoidance": float(prohibited_avoidance),
        "supported_evidence": float(supported_evidence),
        "canonical_patient_message": float(canonical_message),
    }


class AdaptiveConsultScorer(BaseScorer):
    """Score structured consult trajectories without an LLM judge."""

    _categories = {
        "structured_contract_completion": "overall",
        "essential_information_recall": "information_gathering",
        "pre_update_information_recall": "information_gathering",
        "post_update_information_recall": "information_gathering",
        "critical_topic_recall": "information_gathering",
        "duplicate_free_questioning": "information_gathering",
        "update_score": "dialogue",
        "protocol_adherence": "dialogue",
        "canonical_patient_message": "dialogue",
        "disposition_exact": "clinical_decision",
        "undertriage_avoidance": "clinical_decision",
        "overtriage_avoidance": "clinical_decision",
        "critical_concern_recall": "clinical_decision",
        "concern_precision": "clinical_decision",
        "required_action_recall": "clinical_decision",
        "action_precision": "clinical_decision",
        "prohibited_action_avoidance": "clinical_decision",
        "supported_evidence": "clinical_decision",
    }

    def score_item(
        self,
        item: BenchmarkItem,
        responses: list[RunResult],
    ) -> list[Metric]:
        trials = [_trial_scores(item, response) for response in responses]
        metrics = [
            Metric(
                name=name,
                value=_mean([trial[name] for trial in trials]),
                category=category,
                n=len(trials),
            )
            for name, category in self._categories.items()
        ]
        primary = _mean(
            [trial["structured_contract_completion"] for trial in trials]
        )
        update_class = str(item.metadata.get("update_class", "unknown"))
        truth = item.ground_truth if isinstance(item.ground_truth, dict) else {}
        target_disposition = str(truth.get("final_disposition", "unknown"))
        metrics.extend(
            [
                Metric(
                    name="structured_contract_completion",
                    value=primary,
                    category=f"update_class/{update_class}",
                    n=len(trials),
                ),
                Metric(
                    name="structured_contract_completion",
                    value=primary,
                    category=f"target_disposition/{target_disposition}",
                    n=len(trials),
                ),
            ]
        )
        return metrics


__all__ = ["AdaptiveConsultScorer"]
