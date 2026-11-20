"""Score stage: deterministic answer-table scoring of judged responses, plus report.md."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.e2e.project import REVIEWED_LABEL, Project
from pipeline.e2e import text_v2, text_v2_runtime
from tools.score_answer_table import CANDIDATE_WEIGHTS, HARM_ORDER, score_case, summarize
from arisekit.common.hashing import json_sha256
from arisekit.common.jsonio import read_json


# Binding hashes a judgment must still match to be scored, in the order a stale judgment reports them.
STALE_KEYS = ("response_sha256", "case_presentation_sha256", "rubric_sha256")
RUNTIME_KEYS = ("judge_scoring_source_commit", "judge_protocol", "judge_contract_sha256")


def offrubric_provisional(judge_out: dict[str, Any]) -> bool:
    return any(o["actionable"] and o["harm"] != "none" for o in judge_out.get("offRubric", []))


def coverage(project: Project, model: str) -> tuple[dict, dict, list[str]]:
    """A model's collected responses and passed judgments, and the problems that keep records out of scoring:
    duplicated, undeclared, malformed, or failed records, and responses and judgments without a counterpart."""
    responses, invalid = project.responses(model)
    passed, failed = project.passed_judgments(model)
    problems = invalid + failed
    if gap := project.response_gap(model):
        problems.append(gap)
    if missing := sorted(set(responses) - set(passed)):
        problems.append(f"{model}: not judged (or judge failed) for {missing}")
    if extra := sorted(set(passed) - set(responses)):
        problems.append(f"{model}: judgment without a response for {extra}")
    return responses, passed, problems


def score(caseset: Path, rho: float = 0.5,
          allow_partial: bool = False) -> tuple[Path | None, list[str]]:
    project = Project(caseset)
    adapter = text_v2_runtime.for_project(project)
    if getattr(adapter, "FREEZE", None) == "pipeline-v2":
        from pipeline.e2e import pipeline_v2_score
        return pipeline_v2_score.score(caseset, allow_partial)
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
    rows: list[dict[str, Any]] = []
    for model in models:
        responses, passed, found = coverage(project, model)
        problems += found
        scored = []
        for pair, j in passed.items():
            if pair not in responses:
                continue
            base = items[j["id"]]["metadata"]["base_id"]  # the item ID, or a legacy perturbation variant's base case
            if j.get("caseId") != base:
                problems.append(f"{model}: stale judgment for {pair}: case identity changed")
                continue
            table = project.table(base, j["rubric"])
            # A judgment only scores against the exact response, task, and rubric it was judged on.
            bound = project.judgment_bindings(base, j["rubric"], table, responses[pair]["response"])
            binding_keys = (*STALE_KEYS, *RUNTIME_KEYS) if text_v2.is_text_v2(table) else STALE_KEYS
            if changed := [key for key in binding_keys if j.get(key) != bound.get(key)]:
                problems.append(f"{model}: stale judgment for {pair}: {', '.join(changed)} changed since it was "
                                f"judged against {j['rubric']}")
                continue
            if text_v2.is_text_v2(table):
                try:
                    if adapter is text_v2:
                        result = adapter.scorer.score_case_s2(
                            table, j["judge"], responses[pair]["response"], project.case(base)["presentation"])
                    else:
                        result = adapter.score_case(
                            table, j["judge"], responses[pair]["response"], project.case(base)["presentation"])
                except ValueError as error:
                    problems.append(f"{model}: invalid judgment for {pair}: {text_v2_runtime.readable(str(error))}")
                    continue
                off = any(o["actionable"] for o in j["judge"]["offRubric"])
            else:
                result = score_case(table, j["judge"], rho)
                off = offrubric_provisional(j["judge"])
            scored.append({"id": j["id"], "trial": pair[1], "caseId": base, "rubric": j["rubric"], **result,
                           "response_sha256": bound["response_sha256"],
                           "case_presentation_sha256": bound["case_presentation_sha256"],
                           "tableReview": _table_review(project, base, j["rubric"]),
                           "rubric_sha256": j["rubric_sha256"], "judgment_sha256": json_sha256(j["judge"]),
                           "offRubricProvisional": off, "provisional": result["provisional"] or off,
                           "judgeModel": "/".join(j.get("provenance", {}).get(k, "?") for k in ("backend", "model"))})
        judge_failed = sum(j.get("status") != "pass" for j in project.judgments(model))
        rows.append({"model": model, "responses": len(responses), "judge_failed": judge_failed, "scored": scored})
    if problems and not allow_partial:
        return None, problems
    for r in rows:
        project.scored_path(r["model"]).write_text("".join(json.dumps(s) + "\n" for s in r["scored"]))
    project.report_path.write_text(_render(rows, rho, problems))
    return project.report_path, problems


def _table_review(project: Project, case_id: str, rubric: str) -> dict[str, Any] | None:
    """Record saved review provenance, without inferring clinical acceptance."""
    if not (match := REVIEWED_LABEL.fullmatch(rubric)):
        return None
    saved = read_json(project.artifact(case_id, rubric))
    if saved.get("reviewer") != match.group(1) or not saved.get("savedAt") or not saved.get("basedOn"):
        return None
    # Project.table has already required a passing review status.
    return {"reviewer": saved["reviewer"], "savedAt": saved["savedAt"], "status": "pass"}


def _render(rows: list[dict[str, Any]], rho: float, problems: list[str]) -> str:
    text_rows = [{**r, "scored": [s for s in r["scored"] if s.get("scorer") == "S2"]} for r in rows]
    text_rows = [r for r in text_rows if r["scored"]]
    if text_rows:
        legacy_rows = [{**r, "scored": [s for s in r["scored"] if s.get("scorer") != "S2"]} for r in rows]
        legacy_rows = [r for r in legacy_rows if r["scored"]]
        legacy = _render(legacy_rows, rho, []) + "\n" if legacy_rows else ""
        return legacy + _render_text_v2(text_rows, problems)
    weights = "/".join(f"{w:g}" for w in CANDIDATE_WEIGHTS.values())
    tables = {(s["caseId"], s["rubric"], s["rubric_sha256"]): s.get("tableReview")
              for r in rows for s in r["scored"]}
    reviewed = sum(review is not None for review in tables.values())
    # Which rubric labels and judge models produced these scores, so reports from different runs stay distinct.
    scored = [s for r in rows for s in r["scored"]]
    rubrics = ", ".join(sorted({s["rubric"] for s in scored})) or "-"
    judges = ", ".join(sorted({s["judgeModel"] for s in scored})) or "-"
    lines = [
        "# Answer-table report",
        "",
        (
            "Judgments are LLM-provisional; clinician acceptance of judgments is not established. "
            f"Tables with passing saved review provenance: {reviewed}; "
            f"without verified saved review provenance: {len(tables) - reviewed}. "
            "A saved table review does not establish clinical acceptance of the benchmark. "
            f"F1 weights {weights} are candidate, not frozen. rho = {rho}. "
            "Worst harm excludes off-rubric harm, and so do severe events; off-rubric harm is not scored yet; "
            "a response with actionable off-rubric harm is counted as provisional."
        ),
        "",
        f"Rubric: {rubrics}. Judge: {judges}.",
        "",
        "| Model | Responses | Scored | Judge failed | Mean F1 | Worst harm (" + " / ".join(HARM_ORDER) + ") | Severe events | Provisional |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        s = r["scored"]
        if s:
            summ = summarize(s)
            worst = " / ".join(str(summ["worstHarm"][h]) for h in HARM_ORDER)
            f1 = f"{summ['meanF1']:.3f}"
            severe = sum(x["harmCounts"]["severe"] for x in s)
            prov = sum(x["provisional"] for x in s)
        else:
            worst, f1, severe, prov = "-", "-", "-", "-"
        lines.append(f"| {r['model']} | {r['responses']} | {len(s)} | {r['judge_failed']} | {f1} | {worst} | {severe} | {prov} |")
    if problems:
        lines += ["", "Coverage gaps (partial report):", *[f"- {p}" for p in problems]]
    return "\n".join(lines) + "\n"


def _render_text_v2(rows: list[dict[str, Any]], problems: list[str]) -> str:
    source = next(s.get("judge_scoring_source_commit", text_v2.SOURCE_COMMIT) for row in rows for s in row["scored"])
    # scored.jsonl keeps the stored judge label; the report names the rules in plain words.
    protocol = next(s["judge"] for row in rows for s in row["scored"])
    rules = "current judge rules" if protocol == "J2.3" else "earlier judge rules"
    lines = ["# Text rubric report", "",
             f"Rubric: text rubric format. Judge: {rules}. "
             "Judgments are LLM-provisional; rubric import and automated scoring do not establish clinical acceptance. "
             "The scorer reports error severity against the best option and does not calculate legacy F1. "
             "Unresolved mappings retain their error bounds and provisional status.", "",
             f"Tooling source: noharm-science {source}.", "",
             "| Model | Responses | Scored | Judge failed | Optimal | Worst error (none / mild / moderate / severe / unresolved) | Provisional |",
             "|---|---|---|---|---|---|---|"]
    for row in rows:
        scored = row["scored"]
        worst = " / ".join(str(sum(s["worstError"] == level for s in scored))
                           for level in ("none", "mild", "moderate", "severe", None))
        lines.append(f"| {row['model']} | {row['responses']} | {len(scored)} | {row['judge_failed']} | "
                     f"{sum(s['optimal'] for s in scored)} | {worst} | {sum(s['provisional'] for s in scored)} |")
    if problems:
        lines += ["", "Coverage gaps (partial report):", *[f"- {p}" for p in problems]]
    return "\n".join(lines) + "\n"
