"""Severe review: a second model rechecks the judge reading when the slot median says severe, and its corrected
reading replaces the judge's for scoring.

Every call is paid, so callers show `review_plan` and get approval first. An invalid reply is kept as a failed
receipt and never used. Receipts are append-only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from arisekit.common.hashing import json_sha256, sha256
from arisekit.common.jsonio import append_jsonl, read_jsonl
from arisekit.common.logs import log, now_iso

from pipeline.backends import Route, default_workers, run_paid
from pipeline.e2e import pipeline_v2
from pipeline.e2e.pipeline_v2_scoring import TieRule, score_slots, slot_median_level
from pipeline.e2e.pipeline_v2_slots import SlotSet, require_current_grading, slot_set
from pipeline.e2e.project import Pair, Project
from pipeline.skillrun import call_json

REVIEW_DIR = "severe-review"


UPSTREAM_FAMILY_ORDER = ("opus", "sol", "gemini")


def in_upstream_order(slots: SlotSet, slot_results: dict[str, dict]) -> dict[str, dict]:
    """Slot results reordered as upstream walks its raters: opus, sol, gemini by each slot's family (a clinician
    slot counts as the family it replaced), then slots with no family in slot order."""
    rank = {s.id: (UPSTREAM_FAMILY_ORDER.index(s.family) if s.family in UPSTREAM_FAMILY_ORDER
                   else len(UPSTREAM_FAMILY_ORDER), i) for i, s in enumerate(slots.slots)}
    return {k: slot_results[k] for k in sorted(slot_results, key=rank.__getitem__)}


def drivers(slot_results: dict[str, dict], tie: TieRule) -> list[dict]:
    """When the slot-median lower bound is severe, the firm severe events of the slots whose own lower bound is
    severe, de-duplicated by (criterion, item, kind). Slots are walked in the dict order given, so an event's
    position follows the first slot that reports it; callers pass `in_upstream_order` results."""
    lows = [r["worstErrorBounds"][0] for r in slot_results.values()]
    if slot_median_level(lows, tie) != "severe":
        return []
    seen: set[tuple[str, str, str]] = set()
    out = []
    for result in slot_results.values():
        if result["worstErrorBounds"][0] != "severe":
            continue
        for did, decision in result["decisions"].items():
            for event in decision["events"]:
                ident = (did, event["rowId"], event["kind"])
                if event["severity"] == "severe" and not event["possible"] and ident not in seen:
                    seen.add(ident)
                    out.append({"criterion": did, "item": event["rowId"], "kind": event["kind"],
                                "quote": event["evidence"]})
    return out


def review_prompt(record: dict, case_context: str, response: str, reading: dict, drv: list[dict]) -> str:
    folder = pipeline_v2.FREEZE_DIR / "review"
    task = (folder / "second.md").read_text().replace("{{task}}", (folder / "severe3.md").read_text())
    packet = json.dumps({"reading": reading, "severe_drivers": drv}, indent=1, ensure_ascii=False)
    return f"{task}{pipeline_v2.judge_prompt(record, case_context, response)}\n\n## Reading to check\n\n{packet}\n"


def review_bindings(judgment_sha256: str, slots: SlotSet, prompt: str, route: Route) -> dict[str, Any]:
    return {"judgment_sha256": judgment_sha256, "slots_sha256": json_sha256(slots.tables()),
            "prompt_sha256": sha256(prompt), "route": route}


def _stamped(record: dict, reading: dict) -> dict:
    return {**reading, "rubricSha256": pipeline_v2.scorer.rubric_sha256(record)}


def _errors(record: dict, reading: dict, response: str, context: str) -> list[str]:
    return pipeline_v2.scorer.judgment_errors(record, _stamped(record, reading), response, context)


def review_path(project: Project, model: str) -> Path:
    return project.results / REVIEW_DIR / f"{model}.jsonl"


def current_review(project: Project, model: str, pair: Pair, judgment_sha256: str, slots: SlotSet) -> dict | None:
    """The latest passing receipt for this reading and these slot rubrics whose reading still validates.
    The prompt and route are recorded but do not make a review stale: they follow from the reading and slots."""
    path = review_path(project, model)
    if not path.is_file() or not slots.complete:
        return None
    slots_sha = json_sha256(slots.tables())
    response = project.responses(model)[0].get(pair)
    if response is None:
        return None
    context = project.case(slots.case_id)["presentation"]
    for receipt in reversed(read_jsonl(path)):
        if (receipt.get("status") == "pass" and receipt.get("review") is not None
                and (receipt.get("id"), receipt.get("trial", 1)) == pair
                and receipt.get("judgment_sha256") == judgment_sha256 and receipt.get("slots_sha256") == slots_sha
                and not _errors(slots.shared_table, receipt["review"], response["response"], context)):
            return receipt
    return None


def _tie(project: Project) -> TieRule:
    return project.provenance().get("pipeline_v2", {}).get("tieRule", "less")


def _clinician_reviewed(project: Project, model: str, pair: Pair, judgment: dict, table: dict, response: str,
                        context: str) -> bool:
    """A current clinician review wins over any severe review, so the response needs none. An invalid one also
    skips planning: scoring reports it, and a clinician must fix it."""
    from pipeline.e2e.judgment_reviews import InvalidJudgmentReview, current_judgment_review
    try:
        return current_judgment_review(project, model, pair, judgment, table, response, context) is not None
    except InvalidJudgmentReview as error:
        log(f"severe-review skips {model} {pair[0]} t{pair[1]}: invalid clinician review, {error}")
        return True


def _candidates(project: Project) -> list[dict]:
    require_current_grading(project, "severe-review")
    tie = _tie(project)
    base = {item["id"]: item["metadata"]["base_id"] for item in project.items()}
    found = []
    for model in project.model_names():
        judgments, _ = project.passed_judgments(model)
        responses, _ = project.responses(model)
        for pair in sorted(judgments, key=lambda p: (p[0], p[1])):
            if pair not in responses or pair[0] not in base:
                continue
            case_id = base[pair[0]]
            slots = slot_set(project, case_id)
            if not slots.complete:
                continue
            judgment, text = judgments[pair], responses[pair]["response"]
            context = project.case(case_id)["presentation"]
            results = score_slots(slots.tables(), judgment["judge"], text, context, tie)["slots"]
            drv = drivers(in_upstream_order(slots, {k: v["result"] for k, v in results.items()}), tie)
            judgment_sha = json_sha256(judgment["judge"])
            if drv and _clinician_reviewed(project, model, pair, judgment, slots.shared_table, text, context):
                continue
            if drv and not current_review(project, model, pair, judgment_sha, slots):
                found.append({"model": model, "id": pair[0], "trial": pair[1], "caseId": case_id, "drivers": drv,
                              "judgment": judgment["judge"], "judgment_sha256": judgment_sha, "slots": slots,
                              "response": text, "context": context})
    return found


def review_plan(project: Project) -> list[dict]:
    """One entry per response that needs a severe review: complete slots, severe slot median, no current review."""
    return [{k: e[k] for k in ("model", "id", "trial", "caseId", "drivers")} for e in _candidates(project)]


def severe_review(caseset: Path, route: Route, yes: bool) -> list[dict]:
    """The plan without `yes`; with it, one call per planned response, each recorded as a receipt."""
    project = Project(caseset)
    jobs = _candidates(project)
    if not yes:
        return [{k: e[k] for k in ("model", "id", "trial", "caseId", "drivers")} for e in jobs]
    for job in jobs:
        job["prompt"] = review_prompt(job["slots"].shared_table, job["context"], job["response"], job["judgment"],
                                      job["drivers"])
    kwargs = {"reasoning_effort": route["reasoning_effort"]} if "reasoning_effort" in route else {}

    def call(job: dict) -> Any:
        record = job["slots"].shared_table
        outcome = call_json(route["backend"], route["model"], pipeline_v2.INSTRUCTIONS, job["prompt"],
                            pipeline_v2.canonical_schema(),
                            check=lambda o: _errors(record, o, job["response"], job["context"]),
                            normalize_output=pipeline_v2.restamp(record), reject_duplicate_keys=True,
                            provenance={"stage": "severe-review", "judge": pipeline_v2.JUDGE}, **kwargs)
        log(f"severe-review {job['model']} {job['id']} t{job['trial']} {outcome.status}")
        return outcome

    receipts = []

    def write(job: dict, outcome: Any) -> None:
        ok = outcome.status == "pass"
        receipt = {"id": job["id"], "trial": job["trial"], "caseId": job["caseId"],
                   **review_bindings(job["judgment_sha256"], job["slots"], job["prompt"], route),
                   "status": "pass" if ok else "failed",
                   "review": outcome.output if ok else None,
                   "errors": outcome.errors, "raw": outcome.raw, "provenance": outcome.provenance,
                   "createdAt": now_iso()}
        append_jsonl(review_path(project, job["model"]), receipt)
        receipts.append(receipt)

    run_paid(jobs, call, write, min(len(jobs), default_workers(route["backend"])))
    return receipts
