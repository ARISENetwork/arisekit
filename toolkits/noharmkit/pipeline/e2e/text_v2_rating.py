"""Ratings-blinded appropriateness and error-severity ratings for text rubrics."""
from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pipeline.backends import Route
from pipeline.e2e.committee import RaterResult, is_disagreement, mean_tier, median_tier, quorum_met
from pipeline.e2e.constants import KIT_ROOT
from pipeline.e2e.project import Project
from pipeline.e2e.records import Case
from pipeline.e2e.text_v2 import SOURCE_COMMIT, is_text_v2, scoring_errors
from arisekit.common.hashing import json_sha256, sha256
from arisekit.common.logs import log
from arisekit.common.schemas import schema_errors, schema_sha256, strict_object
from pipeline.skillrun import run_skill, skill_prompt
from tools.noharm_science import score_text_rubric_v2 as scorer

SKILL = "rate-text-v2"
RULE = "rounded_mean"
USUAL_CARE_DEFINITION = "Continue current management or usual care, without additional input."
AUTHORING_RULES = KIT_ROOT / "docs/contracts/rubric-authoring-rules.md"


def project_for_rating(table: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"id": d["id"], "kind": d["kind"], "question": d["question"],
         "recommendations": [
             {"id": r["id"], "text": r["text"], "addOn": r.get("addOn") is True or r.get("optional") is True}
             for r in sorted(d["recommendations"], key=lambda row: row["id"])
         ]}
        for d in table["decisions"]
    ]


def rating_variables(case: Case, table: dict[str, Any]) -> dict[str, str]:
    return {"case": case["presentation"], "expert": case["recommendations"],
            "usual_care": USUAL_CARE_DEFINITION,
            "decisions": json.dumps(project_for_rating(table), indent=1),
            "authoring_rules": AUTHORING_RULES.read_text(encoding="utf-8")}


def _rating_schema() -> dict[str, Any]:
    return strict_object({"score": {"type": "integer", "minimum": 1, "maximum": 9},
                          "harm": {"type": "string", "enum": list(scorer.HARMS)},
                          "reason": {"type": "string", "minLength": 1}})


def rating_schema(table: dict[str, Any]) -> dict[str, Any]:
    schema = strict_object({
        "usualCare": {"$ref": "#/$defs/rating"},
        "decisions": strict_object({d["id"]: strict_object({
            "recommendations": strict_object({r["id"]: {"$ref": "#/$defs/rating"}
                                               for r in d["recommendations"]})
        }) for d in table["decisions"]}),
    })
    schema["$defs"] = {"rating": _rating_schema()}
    return schema


def _apply(table: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(table)
    merged["usualCare"] = {key: out["usualCare"][key] for key in ("score", "harm")}
    for d in merged["decisions"]:
        for r in d["recommendations"]:
            ratings = out["decisions"][d["id"]]["recommendations"][r["id"]]
            for key in ("score", "harm"):
                r[key] = ratings[key]
    return merged


def rating_errors(out: Any, table: dict[str, Any]) -> list[str]:
    errors = schema_errors(rating_schema(table), out, "text rubric ratings")
    if errors:
        return errors
    merged = _apply(table, out)
    errors = scoring_errors(merged)
    # The score-to-severity floor is advisory for imported human ratings, but a hard rule for this LLM pass.
    errors.extend(scorer.validate(merged, "scoring")[1])
    return errors


def missing_decisions(out: Any, table: dict[str, Any]) -> list[str]:
    decisions = out.get("decisions", {}) if isinstance(out, dict) else {}
    return [d["id"] for d in table["decisions"]
            if not isinstance(decisions, dict) or d["id"] not in decisions]


def merge_output(table: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    if errors := rating_errors(out, table):
        raise ValueError("Invalid text rubric ratings: " + "; ".join(errors))
    return _apply(table, out)


def _rounded_mean(votes: list[int]) -> int:
    total, count = sum(votes), len(votes)
    return -(-(2 * total - count) // (2 * count))


def _votes(ratings: list[dict[str, Any]], generator: dict[str, Any]) -> dict[str, Any]:
    scores = [r["score"] for r in ratings]
    harms = [r["harm"] for r in ratings]
    return {
        "score": {"votes": scores, "median": _rounded_mean(scores),
                  "medianVote": sorted(scores)[(len(scores) - 1) // 2],
                  "generator": generator.get("score"), "disagreement": max(scores) - min(scores) >= 2},
        "harm": {"votes": harms, "median": mean_tier(harms), "medianVote": median_tier(harms),
                 "generator": generator.get("harm"), "disagreement": is_disagreement(harms)},
    }


def _resolved(votes: dict[str, Any]) -> dict[str, Any]:
    return {"score": votes["score"]["median"], "harm": votes["harm"]["median"],
            "reason": "Rounded mean of independent model ratings; original votes are retained."}


def aggregate(committee: list[Route], raters: list[RaterResult], table: dict[str, Any]) -> dict[str, Any]:
    checked = copy.deepcopy(raters)
    for rater in checked:
        if rater["status"] == "pass" and (errors := rating_errors(rater["output"], table)):
            rater["status"], rater["errors"] = "failed", errors
    passed = [r for r in checked if r["status"] == "pass"]
    record: dict[str, Any] = {"format": scorer.FORMAT, "committee": committee, "raters": checked,
                              "rule": RULE, "status": "failed", "errors": [],
                              "usualCare": None, "decisions": {}, "output": None}
    if not committee or not quorum_met(len(passed), len(committee)):
        record["errors"] = [f"committee quorum not met: {len(passed)} of {len(committee)} raters passed"]
        return record
    record["usualCare"] = _votes([r["output"]["usualCare"] for r in passed], table["usualCare"])
    out = {"usualCare": _resolved(record["usualCare"]), "decisions": {}}
    for d in table["decisions"]:
        items = {}
        for row in d["recommendations"]:
            ratings = [r["output"]["decisions"][d["id"]]["recommendations"][row["id"]] for r in passed]
            items[row["id"]] = _votes(ratings, row)
        record["decisions"][d["id"]] = {"recommendations": items}
        out["decisions"][d["id"]] = {"recommendations": {rid: _resolved(value) for rid, value in items.items()}}
    record["output"] = out
    record["errors"] = rating_errors(out, table)
    record["status"] = "failed" if record["errors"] else "pass"
    return record


def merge(table: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    if record["status"] != "pass":
        raise ValueError("Cannot merge failed text rubric ratings: " + "; ".join(record["errors"]))
    return merge_output(table, record["output"])


def _rate_one(index: int, rater: Route, variables: dict[str, str], table: dict[str, Any],
              schema: dict[str, Any]) -> RaterResult:
    kwargs = {"reasoning_effort": rater["reasoning_effort"]} if "reasoning_effort" in rater else {}
    outcome = run_skill(SKILL, variables, rater["backend"], rater["model"], check=lambda o: rating_errors(o, table),
                        reject_duplicate_keys=True, json_schema=schema, **kwargs)
    log(f"{SKILL} rater {index} ({rater['backend']}/{rater['model']}) {outcome.status}")
    return {"rater": index, "status": outcome.status, "missing": missing_decisions(outcome.output, table),
            "output": outcome.output, "raw": outcome.raw, "errors": outcome.errors, "provenance": outcome.provenance}


def rate_table(case: Case, table: dict[str, Any], committee: list[Route]) -> dict[str, Any]:
    if not committee:
        raise ValueError("The rating committee must not be empty")
    variables, schema = rating_variables(case, table), rating_schema(table)
    with ThreadPoolExecutor(max_workers=len(committee)) as pool:
        raters = list(pool.map(lambda pair: _rate_one(pair[0], pair[1], variables, table, schema),
                               enumerate(committee)))
    return aggregate(committee, raters, table)


def rate(caseset: Path, case_id: str, table_label: str, repeats: int,
         committee: list[Route], tag: str = "committee") -> list[Path]:
    """Write advisory model-rating receipts without replacing the selected rubric."""
    if repeats < 1:
        raise ValueError("rating repeats must be positive")
    if not committee:
        raise ValueError("The rating committee must not be empty")
    project = Project(caseset)
    table, case = project.table(case_id, table_label), project.case(case_id)
    if not is_text_v2(table):
        raise ValueError("Rating needs a rubric in the text rubric format")
    variables, schema = rating_variables(case, table), rating_schema(table)
    system, prompt = skill_prompt(SKILL, variables)
    bindings = {"table": table_label, "table_sha256": scorer.rubric_sha256(table),
                "case_sha256": json_sha256(case), "toolingSourceCommit": SOURCE_COMMIT,
                "system_sha256": sha256(system), "prompt_sha256": sha256(prompt),
                "rating_schema_sha256": schema_sha256(schema), "authority": "llm-generated"}
    paths = project.new_ratings(tag, case_id, table_label, repeats)

    def one(path: Path) -> None:
        record = rate_table(case, table, committee)
        project.write_new(path, {**bindings, **record})
        log(f"{SKILL} {case_id} {table_label} {path.name} {record['status']}")

    # Not pool.map: its first error cancels repeats that have not started, so they would silently never run.
    with ThreadPoolExecutor(max_workers=repeats) as pool:
        futures = [pool.submit(one, path) for path in paths]
    for future in futures:
        future.result()
    return paths
