"""Score a current-grading project: pick each response's reading, score it over the case's rater slots, report.

Deterministic and local. Never calls a model.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from arisekit.common.hashing import json_sha256

from pipeline.e2e import pipeline_v2
from pipeline.e2e.judgment_reviews import InvalidJudgmentReview, current_judgment_review
from pipeline.e2e.pipeline_v2_review import _tie, current_review, drivers, in_upstream_order
from pipeline.e2e.pipeline_v2_scoring import f1_slots, recall_left_out_by, score_slots
from pipeline.e2e.pipeline_v2_slots import slot_set
from pipeline.e2e.project import Project
from pipeline.e2e.score import _table_review, coverage

RUNTIME_KEYS = ("judge_scoring_source_commit", "judge_protocol", "judge_contract_sha256")
PENDING = "judge (severe review pending)"
LEVELS = ("none", "mild", "moderate", "severe")


def _judge_route(judgment: dict[str, Any]) -> dict[str, Any]:
    prov = judgment.get("provenance", {})
    return {k: prov.get(k) for k in ("backend", "model", "reasoning_effort")}


def _score_row(project: Project, model: str, pair: tuple[str, int], j: dict, response: str, tie: Any) -> dict[str, Any]:
    base = j["caseId"]
    slots = slot_set(project, base)
    table = slots.shared_table
    bound = project.judgment_bindings(base, slots.shared, table, response)
    if changed := [key for key in pipeline_v2.STALE_KEYS if j.get(key) != bound.get(key)]:
        raise LookupError(f"stale judgment for {pair}: {', '.join(changed)} changed since it was judged")
    context = project.case(base)["presentation"]
    tables = slots.tables(allow_incomplete=True)
    judge_reading = j["judge"]
    judge_sha = json_sha256(judge_reading)
    judged = score_slots(tables, judge_reading, response, context, tie)
    clinician = current_judgment_review(project, model, pair, j, table, response, context)
    review = None if clinician else current_review(project, model, pair, judge_sha, slots)
    if clinician:
        reading, label = clinician["reading"], "clinician review"
        result = score_slots(tables, reading, response, context, tie)
    elif review:
        reading, label = review["review"], "severe review"
        result = score_slots(tables, reading, response, context, tie)
    else:
        reading = judge_reading
        pending = drivers(in_upstream_order(slots, {k: v["result"] for k, v in judged["slots"].items()}), tie)
        label, result = (PENDING if pending else "judge"), judged
    f1 = f1_slots(tables, reading, tie) | {"recallLeftOutBy": recall_left_out_by(tables, reading)}
    summary = slots.summary()
    judge_route = _judge_route(j)
    review_route = review.get("route") if review else None
    complete = summary["complete"]
    return {"id": j["id"], "trial": pair[1], "caseId": base, "rubric": slots.shared,
            "response_sha256": bound["response_sha256"],
            "case_presentation_sha256": bound["case_presentation_sha256"],
            "rubric_text_sha256": bound["rubric_text_sha256"], "rubric_sha256": bound["rubric_sha256"],
            **{k: j[k] for k in RUNTIME_KEYS},
            "judgment_sha256": judge_sha, "tableReview": _table_review(project, base, slots.shared),
            "freeze": pipeline_v2.FREEZE, "judge": pipeline_v2.JUDGE, "scorer": "S2",
            **{k: result[k] for k in ("worstError", "worstErrorBounds", "provisional", "spread")}, **f1,
            "reading": label, "readingSha256": json_sha256(reading),
            **({"reviewer": clinician["reviewer"], "reviewedAt": clinician["reviewedAt"],
                "reviewedReadingSha256": clinician["readingSha256"]} if clinician else {}),
            "slots": summary["slots"], "ratedBy": summary["ratedBy"], "complete": complete,
            "final": complete and label != PENDING, "tieRule": tie, "slotCount": summary["slotCount"],
            "models": {"judge": judge_route, "review": review_route}}


def score(caseset: Path, allow_partial: bool = False) -> tuple[Path | None, list[str]]:
    project = Project(caseset)
    try:
        expected = project.expected()
    except ValueError as exc:
        return None, [f"invalid project: {exc}"]
    items = {i["id"]: i for i in project.items()}
    models = sorted(project.model_names())
    problems: list[str] = []
    if not expected:
        problems.append("items.jsonl has no expected cases")
    if not models:
        problems.append("provenance.json lists no models; run run_inference.py first")
    if extra := sorted({path.stem for path in project.response_files()} - set(models)):
        problems.append(f"responses files for models not in provenance: {extra}")
    tie = _tie(project)
    rows = []
    for model in models:
        responses, passed, found = coverage(project, model)
        problems += found
        scored = []
        for pair, j in passed.items():
            if pair not in responses:
                continue
            if j.get("caseId") != items[j["id"]]["metadata"]["base_id"]:
                problems.append(f"{model}: stale judgment for {pair}: case identity changed")
                continue
            try:
                scored.append(_score_row(project, model, pair, j, responses[pair]["response"], tie))
            except InvalidJudgmentReview as error:
                problems.append(f"{model}: invalid clinician review, {error}")
            except (LookupError, ValueError) as error:
                problems.append(f"{model}: {error}")
        judge_failed = sum(j.get("status") != "pass" for j in project.judgments(model))
        rows.append({"model": model, "responses": len(responses), "judge_failed": judge_failed, "scored": scored})
    if problems and not allow_partial:
        return None, problems
    for r in rows:
        project.scored_path(r["model"]).write_text("".join(json.dumps(s) + "\n" for s in r["scored"]))
    project.report_path.write_text(_render(rows, tie, problems))
    return project.report_path, problems


def _render(rows: list[dict[str, Any]], tie: str, problems: list[str]) -> str:
    lines = ["# Scoring report", "",
             "Each response is scored on the judge's reading, or on the clinician review's or the severe review's "
             "reading when a current one exists. The score is the median over the case's rater slots. Worst error is the median of the "
             "slots' lower bounds. F1 is the median of the slots' F1. Judgments are LLM-provisional; scoring does "
             "not establish clinical acceptance.", "",
             "A score is final only when every rater slot has rated every item and no severe review is waiting. "
             "Mean F1 averages final scores only; the next column counts the scores left out.", "",
             "| Model | Responses | Scored | Final | Incomplete ratings | Severe review pending "
             "| Clinician review used | Severe review used | Mean F1 | Left out of mean F1 | None | Mild | Moderate | Severe | Provisional |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        s = row["scored"]
        counts = Counter(x["worstError"] for x in s)
        final = [x["f1"] for x in s if x["final"]]
        f1 = f"{sum(final) / len(final):.3f}" if final else "-"
        lines.append(
            f"| {row['model']} | {row['responses']} | {len(s)} | {sum(x['final'] for x in s)} "
            f"| {sum(not x['complete'] for x in s)} | {sum(x['reading'] == PENDING for x in s)} "
            f"| {sum(x['reading'] == 'clinician review' for x in s)} "
            f"| {sum(x['reading'] == 'severe review' for x in s)} | {f1} | {len(s) - len(final)} "
            f"| {' | '.join(str(counts[level]) for level in LEVELS)} | {sum(x['provisional'] for x in s)} |")
    lines += ["", f"Ties between an even number of raters break toward the {'less' if tie == 'less' else 'more'} severe level."]
    if problems:
        lines += ["", "Coverage gaps (partial report):", *[f"- {p}" for p in problems]]
    return "\n".join(lines) + "\n"
