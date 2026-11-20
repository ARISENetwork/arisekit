"""Offline contract tests for the synthetic Adaptive Consult-10 pilot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from arisekit.agentic import AgentTurnOutput
from arisekit.cli import _load_benchmark
from arisekit.sut import SystemUnderTest
from arisekit.types import BenchmarkItem, RunResult, Trajectory, Turn
from benchmarks.general_medicine_adaptive import build
from benchmarks.general_medicine_adaptive.environment import (
    ACTION_CODES,
    CONCERN_CODES,
    patient_message_for,
    stage_token,
)
from benchmarks.general_medicine_adaptive.scorer import AdaptiveConsultScorer
from benchmarks.general_medicine_adaptive.validation import validate_items


REPO_ROOT = Path(__file__).resolve().parent.parent


def _assistant_call(name: str, arguments: dict[str, Any], turn_id: int) -> list[Turn]:
    call = {"id": f"call-{turn_id}", "name": name, "arguments": arguments}
    return [
        Turn(
            role="assistant",
            content={"text": None, "tool_calls": [call]},
        ),
        Turn(
            role="tool_result",
            content={"id": call["id"], "name": name, "result": {"ok": True}},
        ),
    ]


def _perfect_trajectory(item: BenchmarkItem) -> Trajectory:
    truth = item.ground_truth
    assert isinstance(truth, dict)
    update = item.metadata["patient_simulator"]["scheduled_update"]
    token = stage_token(item.id, update)
    turns: list[Turn] = []
    turn_id = 0
    disclosed: list[str] = []
    for entry in truth["pre_update_topics"]:
        topic = entry["topic"]
        disclosed.append(topic)
        turns.extend(
            _assistant_call(
                "ask_patient",
                {"case_id": item.id, "topic": topic},
                turn_id,
            )
        )
        turn_id += 1
    turns.extend(
        _assistant_call(
            "submit_interim",
            {
                "case_id": item.id,
                "disposition": truth["acceptable_interim_dispositions"][0],
            },
            turn_id,
        )
    )
    turn_id += 1
    for entry in truth["post_update_topics"]:
        topic = entry["topic"]
        disclosed.append(topic)
        turns.extend(
            _assistant_call(
                "ask_patient_after_update",
                {"case_id": item.id, "stage_token": token, "topic": topic},
                turn_id,
            )
        )
        turn_id += 1
    turns.extend(
        _assistant_call(
            "finish_consult",
            {
                "case_id": item.id,
                "stage_token": token,
                "disposition": truth["final_disposition"],
                "concern_codes": [truth["accepted_concern_codes"][0]],
                "action_codes": truth["required_action_codes"],
                "evidence_topics": disclosed,
            },
            turn_id,
        )
    )
    message = patient_message_for(
        truth["final_disposition"],
        set(truth["required_action_codes"]),
    )
    turns.append(Turn(role="assistant", content=message))
    return Trajectory(turns=turns, final_response=message)


def test_benchmark_loads_ten_synthetic_draft_cases():
    benchmark = build()

    assert benchmark.name == "general-medicine-adaptive"
    assert len(benchmark.dataset) == 10
    assert benchmark.tools is not None
    assert {tool.name for tool in benchmark.tools} == {
        "ask_patient",
        "ask_patient_after_update",
        "submit_interim",
        "finish_consult",
    }
    assert all(
        item.metadata["status"] == "synthetic_draft"
        and item.metadata["specialty"] == "primary-internal-medicine"
        and item.attachments == []
        for item in benchmark.dataset
    )


def test_all_synthetic_assets_pass_strict_validation():
    assert validate_items(build().dataset) == []


def test_asset_validation_reports_topic_source_and_action_contract_breaks():
    benchmark = build()
    rows = [BenchmarkItem.from_dict(item.to_dict()) for item in benchmark.dataset]
    broken = rows[0]
    broken.ground_truth["pre_update_topics"][0]["topic"] = "not_a_topic"
    broken.ground_truth["required_action_codes"].append("self_care_only")
    broken.metadata["patient_simulator"]["scheduled_update"]["source_ids"] = [
        "missing-source"
    ]

    issues = validate_items(rows)
    rendered = "\n".join(str(issue) for issue in issues)

    assert "is not a valid topic" in rendered
    assert "required and prohibited actions overlap" in rendered
    assert "references undeclared source IDs" in rendered


def test_cli_discovers_package_init_build():
    benchmark = _load_benchmark(
        "general_medicine_adaptive",
        REPO_ROOT / "benchmarks",
    )
    assert benchmark.name == "general-medicine-adaptive"
    assert len(benchmark.dataset) == 10


def test_patient_tools_disclose_only_requested_fact_and_scheduled_update():
    benchmark = build()
    item = benchmark.dataset[0]
    tools = {tool.name: tool for tool in benchmark.tools or []}
    topic = item.ground_truth["pre_update_topics"][0]["topic"]

    answer = tools["ask_patient"].fn(
        case_id=item.id,
        topic=topic,
    )
    assert answer["topic"] == topic
    assert answer["answer"] == item.metadata["patient_simulator"]["fact_bank"][topic]["text"]
    assert "ground_truth" not in answer
    assert "source_ids" not in answer

    update = tools["submit_interim"].fn(
        case_id=item.id,
        disposition="routine_appointment",
    )
    assert update["patient_update"] == (
        item.metadata["patient_simulator"]["scheduled_update"]["text"]
    )
    assert "final_disposition" not in update
    assert "source_ids" not in update
    assert "update_class" not in update
    assert update["stage_token"]

    post_topic = item.ground_truth["post_update_topics"][0]["topic"]
    premature = tools["ask_patient"].fn(case_id=item.id, topic=post_topic)
    assert premature["answer"] == "That symptom or detail is not present at this stage."
    after = tools["ask_patient_after_update"].fn(
        case_id=item.id,
        stage_token=update["stage_token"],
        topic=post_topic,
    )
    assert after["answer"] == (
        item.metadata["patient_simulator"]["fact_bank"][post_topic]["text"]
    )


def test_scorer_gives_every_perfect_structured_trajectory_full_credit():
    items = build().dataset
    for item in items:
        result = RunResult(
            id=item.id,
            trial=1,
            response=_perfect_trajectory(item),
        )

        metrics = AdaptiveConsultScorer().score_item(item, [result])

        assert metrics
        assert all(metric.value == 1.0 for metric in metrics), item.id


def test_primary_metric_is_honest_and_stratified():
    item = build().dataset[0]
    result = RunResult(
        id=item.id,
        trial=1,
        response=_perfect_trajectory(item),
    )

    metrics = AdaptiveConsultScorer().score_item(item, [result])

    assert {metric.name for metric in metrics if metric.category == "overall"} == {
        "structured_contract_completion"
    }
    assert {
        metric.category
        for metric in metrics
        if metric.name == "structured_contract_completion"
    } == {
        "overall",
        f"update_class/{item.metadata['update_class']}",
        f"target_disposition/{item.ground_truth['final_disposition']}",
    }


def test_failed_patient_tool_result_cannot_claim_information_credit():
    item = build().dataset[0]
    trajectory = _perfect_trajectory(item)
    first_result = next(
        turn for turn in trajectory.turns if turn.role == "tool_result"
    )
    first_result.content["result"] = {"error": "simulated tool failure"}
    result = RunResult(id=item.id, trial=1, response=trajectory)

    by_name = {
        metric.name: metric.value
        for metric in AdaptiveConsultScorer().score_item(item, [result])
        if metric.category in {"overall", "information_gathering", "dialogue"}
    }

    assert by_name["structured_contract_completion"] == 0.0
    assert by_name["critical_topic_recall"] < 1.0
    assert by_name["protocol_adherence"] == 0.0


def test_finish_tool_without_terminal_response_is_a_protocol_failure():
    item = build().dataset[0]
    trajectory = _perfect_trajectory(item)
    trajectory.turns.pop()
    trajectory.final_response = None
    result = RunResult(id=item.id, trial=1, response=trajectory)

    by_name = {
        metric.name: metric.value
        for metric in AdaptiveConsultScorer().score_item(item, [result])
        if metric.category in {"overall", "dialogue"}
    }

    assert by_name["structured_contract_completion"] == 0.0
    assert by_name["protocol_adherence"] == 0.0


def test_phase_swap_cannot_claim_protocol_or_primary_credit():
    item = build().dataset[0]
    trajectory = _perfect_trajectory(item)
    first_call_turn = next(
        turn
        for turn in trajectory.turns
        if turn.role == "assistant" and isinstance(turn.content, dict)
    )
    first_call = first_call_turn.content["tool_calls"][0]
    first_call["name"] = "ask_patient_after_update"
    first_call["arguments"]["stage_token"] = _expected_token(item)
    first_result = next(
        turn for turn in trajectory.turns if turn.role == "tool_result"
    )
    first_result.content["name"] = "ask_patient_after_update"

    by_name = _metric_values(item, trajectory)

    assert by_name["structured_contract_completion"] == 0.0
    assert by_name["protocol_adherence"] == 0.0
    assert by_name["pre_update_information_recall"] < 1.0


def test_label_spam_and_extra_actions_fail_precision_contracts():
    item = build().dataset[0]
    trajectory = _perfect_trajectory(item)
    finish_call = next(
        turn.content["tool_calls"][0]
        for turn in trajectory.turns
        if turn.role == "assistant"
        and isinstance(turn.content, dict)
        and turn.content["tool_calls"][0]["name"] == "finish_consult"
    )
    finish_call["arguments"]["concern_codes"] = list(CONCERN_CODES)
    prohibited = set(item.ground_truth["prohibited_action_codes"])
    finish_call["arguments"]["action_codes"] = [
        code for code in ACTION_CODES if code not in prohibited
    ][:5]

    by_name = _metric_values(item, trajectory)

    assert by_name["structured_contract_completion"] == 0.0
    assert by_name["concern_precision"] < 1.0
    assert by_name["action_precision"] < 1.0


def test_malformed_arrays_score_zero_without_crashing():
    item = build().dataset[0]
    trajectory = _perfect_trajectory(item)
    finish_call = next(
        turn.content["tool_calls"][0]
        for turn in trajectory.turns
        if turn.role == "assistant"
        and isinstance(turn.content, dict)
        and turn.content["tool_calls"][0]["name"] == "finish_consult"
    )
    finish_call["arguments"]["concern_codes"] = None
    finish_call["arguments"]["action_codes"] = {"not": "an array"}
    finish_call["arguments"]["evidence_topics"] = "timing_course"

    by_name = _metric_values(item, trajectory)

    assert by_name["structured_contract_completion"] == 0.0
    assert by_name["concern_precision"] == 0.0
    assert by_name["required_action_recall"] == 0.0
    assert by_name["supported_evidence"] == 0.0


def test_decisive_update_allows_emergency_early_stop():
    item = build().dataset[0]
    truth = item.ground_truth
    token = _expected_token(item)
    turns: list[Turn] = []
    disclosed = []
    for turn_id, entry in enumerate(truth["pre_update_topics"]):
        topic = entry["topic"]
        disclosed.append(topic)
        turns.extend(
            _assistant_call(
                "ask_patient",
                {"case_id": item.id, "topic": topic},
                turn_id,
            )
        )
    turns.extend(
        _assistant_call(
            "submit_interim",
            {
                "case_id": item.id,
                "disposition": truth["acceptable_interim_dispositions"][0],
            },
            2,
        )
    )
    disclosed.extend(
        item.metadata["patient_simulator"]["scheduled_update"]["disclosed_topics"]
    )
    turns.extend(
        _assistant_call(
            "finish_consult",
            {
                "case_id": item.id,
                "stage_token": token,
                "disposition": truth["final_disposition"],
                "concern_codes": [truth["accepted_concern_codes"][0]],
                "action_codes": truth["required_action_codes"],
                "evidence_topics": list(dict.fromkeys(disclosed)),
            },
            3,
        )
    )
    message = patient_message_for(
        truth["final_disposition"],
        set(truth["required_action_codes"]),
    )
    turns.append(Turn(role="assistant", content=message))
    trajectory = Trajectory(turns=turns, final_response=message)

    by_name = _metric_values(item, trajectory)

    assert by_name["structured_contract_completion"] == 1.0
    assert by_name["protocol_adherence"] == 1.0
    assert by_name["post_update_information_recall"] < 1.0


def test_wrong_stage_token_is_rejected_by_post_update_tools():
    benchmark = build()
    item = benchmark.dataset[0]
    tools = {tool.name: tool for tool in benchmark.tools or []}
    post_topic = item.ground_truth["post_update_topics"][0]["topic"]

    try:
        tools["ask_patient_after_update"].fn(
            case_id=item.id,
            stage_token="guessed",
            topic=post_topic,
        )
    except ValueError as error:
        assert "invalid stage_token" in str(error)
    else:
        raise AssertionError("a guessed stage token must not unlock future facts")


def test_scorer_makes_protocol_and_undertriage_failures_visible():
    item = build().dataset[0]
    truth = item.ground_truth
    assert isinstance(truth, dict)
    topic = truth["pre_update_topics"][0]["topic"]
    turns: list[Turn] = []
    turns.extend(
        _assistant_call(
            "ask_patient",
            {"case_id": item.id, "topic": topic},
            0,
        )
    )
    turns.extend(
        _assistant_call(
            "ask_patient",
            {"case_id": item.id, "topic": topic},
            1,
        )
    )
    turns.extend(
        _assistant_call(
            "finish_consult",
            {
                "case_id": item.id,
                "stage_token": "not-a-valid-token",
                "disposition": "self_care",
                "concern_codes": [],
                "action_codes": truth["prohibited_action_codes"],
                "evidence_topics": ["objective_measurements"],
            },
            2,
        )
    )
    result = RunResult(
        id=item.id,
        trial=1,
        response=Trajectory(turns=turns, final_response="Stay home."),
    )

    by_name = {
        metric.name: metric.value
        for metric in AdaptiveConsultScorer().score_item(item, [result])
    }

    assert by_name["structured_contract_completion"] == 0.0
    assert by_name["protocol_adherence"] == 0.0
    assert by_name["disposition_exact"] == 0.0
    assert by_name["undertriage_avoidance"] == 0.0
    assert by_name["duplicate_free_questioning"] < 1.0
    assert by_name["supported_evidence"] == 0.0


def _expected_token(item: BenchmarkItem) -> str:
    return stage_token(
        item.id,
        item.metadata["patient_simulator"]["scheduled_update"],
    )


def _metric_values(
    item: BenchmarkItem,
    trajectory: Trajectory,
) -> dict[str, float]:
    result = RunResult(id=item.id, trial=1, response=trajectory)
    return {
        metric.name: metric.value
        for metric in AdaptiveConsultScorer().score_item(item, [result])
    }


class PerfectAdaptiveClient:
    """A deterministic solver used only to exercise the full agent loop."""

    model = "perfect-adaptive-stub"

    def __init__(self, items: list[BenchmarkItem]):
        self._items = {item.id: item for item in items}
        self._call_number = 0

    def __call__(self, messages, tools):
        item = self._item_for_messages(messages)
        truth = item.ground_truth
        calls = [
            call
            for message in messages
            if message.get("role") == "assistant"
            for call in message.get("tool_calls", []) or []
        ]
        asks = [call for call in calls if call.get("name") == "ask_patient"]
        post_asks = [
            call
            for call in calls
            if call.get("name") == "ask_patient_after_update"
        ]
        interim = [call for call in calls if call.get("name") == "submit_interim"]
        finishes = [call for call in calls if call.get("name") == "finish_consult"]
        pre_topics = [entry["topic"] for entry in truth["pre_update_topics"]]
        post_topics = [entry["topic"] for entry in truth["post_update_topics"]]

        if not interim and len(asks) < len(pre_topics):
            topic = pre_topics[len(asks)]
            return self._call(
                "ask_patient",
                {
                    "case_id": item.id,
                    "topic": topic,
                },
            )
        if not interim:
            return self._call(
                "submit_interim",
                {
                    "case_id": item.id,
                    "disposition": truth["acceptable_interim_dispositions"][0],
                },
            )
        token = next(
            message["content"]["stage_token"]
            for message in messages
            if message.get("role") == "tool"
            and message.get("name") == "submit_interim"
        )
        if len(post_asks) < len(post_topics):
            topic = post_topics[len(post_asks)]
            return self._call(
                "ask_patient_after_update",
                {
                    "case_id": item.id,
                    "stage_token": token,
                    "topic": topic,
                },
            )
        if not finishes:
            return self._call(
                "finish_consult",
                {
                    "case_id": item.id,
                    "stage_token": token,
                    "disposition": truth["final_disposition"],
                    "concern_codes": [truth["accepted_concern_codes"][0]],
                    "action_codes": truth["required_action_codes"],
                    "evidence_topics": pre_topics + post_topics,
                },
            )
        message = next(
            message["content"]["patient_message"]
            for message in messages
            if message.get("role") == "tool"
            and message.get("name") == "finish_consult"
        )
        return AgentTurnOutput(
            text=message,
            tool_calls=[],
            tokens_in=1,
            tokens_out=1,
            cost=0.0001,
        )

    def _item_for_messages(self, messages) -> BenchmarkItem:
        user_text = " ".join(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "user"
        )
        return next(item for item_id, item in self._items.items() if item_id in user_text)

    def _call(self, name: str, arguments: dict[str, Any]) -> AgentTurnOutput:
        self._call_number += 1
        return AgentTurnOutput(
            text=None,
            tool_calls=[
                {
                    "id": f"stub-{self._call_number}",
                    "name": name,
                    "arguments": arguments,
                }
            ],
            tokens_in=1,
            tokens_out=1,
            cost=0.0001,
        )


def test_full_benchmark_agent_loop_smoke(tmp_path: Path):
    benchmark = build()
    client = PerfectAdaptiveClient(list(benchmark.dataset))
    sut = SystemUnderTest.from_agent(
        client,
        benchmark.tools or [],
        system_prompt=benchmark.dataset.system_prompt,
        max_iters=benchmark.max_turns,
        name=client.model,
    )

    results = benchmark.run(sut, limit=2, results_dir=tmp_path)

    assert results.summary.completed == 2
    assert results.summary.errored == 0
    primary = next(
        metric
        for metric in results.metrics
        if metric.name == "structured_contract_completion"
        and metric.category == "overall"
    )
    assert primary.value == 1.0
    assert (tmp_path / "raw" / benchmark.name / f"{client.model}.jsonl").is_file()
    assert (
        tmp_path / "raw" / benchmark.name / f"{client.model}.turns.jsonl"
    ).is_file()
