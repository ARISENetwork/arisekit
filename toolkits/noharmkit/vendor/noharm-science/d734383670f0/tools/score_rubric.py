"""Scorer for the Decision-based rubric, the development rubric under D010 (decisions 16-48).

Contract: docs/contracts/rubric-v1.md. Deterministic; no model calls.
Not clinically accepted: scores stay LLM-provisional until clinician review.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Literal

Severity = Literal["mild", "moderate", "severe"]
NeedSeverity = Literal["none", "mild", "moderate", "severe"]
EventSeverity = Literal["uncertain", "mild", "moderate", "severe"]
Outcome = Literal["met", "partly", "notMet"]

NEED_SEVERITIES: tuple[NeedSeverity, ...] = ("none", "mild", "moderate", "severe")
ONE_STEP_LOWER: dict[str, EventSeverity] = {
    "severe": "moderate",
    "moderate": "mild",
    "mild": "uncertain",
}
COMMISSION_SEVERITY: dict[int, Severity] = {1: "severe", 2: "moderate", 3: "mild"}
# Decision 39: the best appropriate score sets the Decision's harm if not addressed,
# and a lower appropriate score carries relative harm by its gap from the best.
SCORE_NEED: dict[int, Severity] = {9: "severe", 8: "moderate", 7: "mild"}
GAP_HARM: dict[int, Severity] = {1: "mild", 2: "moderate"}
# Decision 42: how each recommended row relates to the others. "first" and "addOn"
# make up the plan given now; each "alternative" is a separate branch the reader may
# choose instead; "fallback" applies only if the plan given now fails.
ROLES = ("first", "addOn", "alternative", "fallback")
TIMINGS = ("emergency", "urgent", "routine", "none")
# Descriptive authoring metadata only; never an input to scoring or judging.
RECOMMENDATION_TAGS = ("diagnostic", "medication", "procedure", "counseling", "followUp", "none")
FOLLOW_UP_QUESTION = "What follow-up or triage is appropriate?"
# D062: the fixed Decision kinds; followUp marks D1 only. Optional; the judge sees the kind, the scorer ignores it.
KINDS = ("followUp", "workup", "treatment", "medication", "counseling", "returnPrecautions", "otherActions")
OUTCOMES = ("met", "partly", "notMet")
# Decision 41: the S01 candidate weights (docs/design/s01-design.md section 7), an
# explicit input. "uncertain" is the neutral weight for 4-6 rows and None needs.
CANDIDATE_WEIGHTS: dict[str, float] = {"uncertain": 1.0, "mild": 3.0, "moderate": 24.0, "severe": 72.0}
HARM_ORDER = ("none", "uncertain", "mild", "moderate", "severe")
SCORE_SEVERITY: dict[int, Severity] = {9: "severe", 8: "moderate", 7: "mild"}
# The tier is derived from the score, never stored: 7-9 appropriate (can meet the need),
# 4-6 uncertain, 1-3 inappropriate. These fields belong to one side of that line.
APPROPRIATE_ONLY = ("timing", "parts", "equivalents", "drugClass", "alsoTakesCareOf", "relativeHarmOverride")
NOT_APPROPRIATE_ONLY = ("incompleteVersionOf", "harmIfRecommendedOverride")


def appropriate_rows(d: dict[str, Any]) -> list[dict[str, Any]]:
    """The Decision's recommendations scored 7-9, in their stored order."""
    return [r for r in d["recommendations"] if r["score"] >= 7]


def not_appropriate_rows(d: dict[str, Any]) -> list[dict[str, Any]]:
    """The Decision's recommendations scored 1-6 (uncertain or inappropriate), in their stored order."""
    return [r for r in d["recommendations"] if r["score"] <= 6]


def _valid_score(row: dict[str, Any]) -> bool:
    score = row.get("score")
    return isinstance(score, int) and not isinstance(score, bool) and 1 <= score <= 9


def validation_errors(case: dict[str, Any], completeness_mode: str | None = None) -> list[str]:
    """Structural errors in one case's rubric record; empty when valid."""
    errors: list[str] = []
    decisions = case.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        return ["decisions must be a non-empty list"]
    decision_ids = [d.get("id") for d in decisions]
    if len(set(decision_ids)) != len(decision_ids):
        errors.append("decision ids must be unique")
    follow_ups = [d for d in decisions if d.get("kind") == "followUp"]
    first = decisions[0]
    if (len(follow_ups) != 1 or first.get("kind") != "followUp" or first.get("id") != "D1"
            or first.get("question") != FOLLOW_UP_QUESTION):
        errors.append(f'D1 must be the one Follow-up Decision, "{FOLLOW_UP_QUESTION}"')
    overrides = case.get("harmOverrides", False)
    if not isinstance(overrides, bool):
        errors.append("harmOverrides must be true or false")
    row_ids: list[str] = []
    for d in decisions:
        did = d.get("id")
        if not isinstance(d.get("recommendations"), list) or not all(isinstance(r, dict) for r in d["recommendations"]):
            errors.append(f"{did}: recommendations must be a list of rows")
        row_ids += [r.get("id") for r in _rows(d)]
        errors += _unit_errors(d, did, overrides is True, completeness_mode)
        if "kind" in d and d["kind"] not in KINDS:
            errors.append(f"{did}: kind must be one of {', '.join(KINDS)}")
        if d.get("kind") == "followUp":
            for r in _scored(d, appropriate=True):
                if r.get("timing") not in TIMINGS:
                    errors.append(f"{r.get('id')}: Follow-up appropriate recommendations need a timing")
        activation = d.get("activation", {"type": "always"})
        kind = activation.get("type")
        if kind not in {"always", "onlyIf", "future"}:
            errors.append(f"{did}: activation type must be always, onlyIf, or future")
        if kind == "future" and not isinstance(activation.get("scoredNow"), bool):
            errors.append(f"{did}: future activation needs a boolean scoredNow")
    # Decision 46 (dual mode only): no Decision's harm if not addressed may exceed the harm of usual care.
    usual = (case.get("usualCare") or {}).get("harm")
    if usual in NEED_SEVERITIES and overrides is True:
        for d in decisions:
            if _scored(d, appropriate=True) and all(_valid_score(r) for r in _rows(d)):
                need = need_severity(d)
                if need in NEED_SEVERITIES and NEED_SEVERITIES.index(need) > NEED_SEVERITIES.index(usual):
                    errors.append(f"{d.get('id')}: harm if not addressed ({need}) exceeds usual-care harm ({usual})")
    all_rows = set(row_ids)
    if len(all_rows) != len(row_ids):
        errors.append("row ids must be unique across the case")
    for d in decisions:
        activation = d.get("activation", {"type": "always"})
        if activation.get("type") == "onlyIf":
            if activation.get("match", "any") not in ("any", "all"):
                errors.append(f"{d.get('id')}: condition match must be any or all")
            missing = [r for r in activation.get("rows", []) if r not in all_rows]
            if not activation.get("rows") or missing:
                errors.append(f"{d.get('id')}: onlyIf must list existing rows")
        for r in _scored(d, appropriate=True):
            for target in r.get("alsoTakesCareOf", []):
                if target not in decision_ids or target == d.get("id"):
                    errors.append(f"{r.get('id')}: alsoTakesCareOf must name another decision")
    return errors


def _rows(d: dict[str, Any]) -> list[dict[str, Any]]:
    rows = d.get("recommendations")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _scored(d: dict[str, Any], appropriate: bool) -> list[dict[str, Any]]:
    """Rows with a valid score on one side of the 6/7 line; rows with an invalid score are on neither."""
    return [r for r in _rows(d) if _valid_score(r) and (r["score"] >= 7) == appropriate]


def _unit_errors(unit: dict[str, Any], label: Any, overrides: bool,
                 completeness_mode: str | None = None) -> list[str]:
    errors: list[str] = []
    for r in _rows(unit):
        if "tags" in r:
            tags = r["tags"]
            if not isinstance(tags, list) or any(not isinstance(tag, str) or tag not in RECOMMENDATION_TAGS for tag in tags):
                errors.append(f"{r.get('id')}: tags must be a list of recognized recommendation tags")
            elif len(tags) != len(set(tags)):
                errors.append(f"{r.get('id')}: tags must be unique")
        if not _valid_score(r):
            errors.append(f"{r.get('id')}: score must be an integer 1-9")
        if "tier" in r:
            errors.append(f"{r.get('id')}: tier is derived from the score; remove it")
    appropriate = _scored(unit, appropriate=True)
    if not appropriate:
        errors.append(f"{label}: at least one appropriate recommendation (score 7-9) is required")
    best = max((r["score"] for r in appropriate), default=None)
    for r in appropriate:
        if misplaced := [k for k in NOT_APPROPRIATE_ONLY if k in r]:
            errors.append(f"{r.get('id')}: rows scored 7-9 cannot carry {', '.join(misplaced)}")
        parts = r.get("parts")
        if parts is not None and (not isinstance(parts, list) or len(parts) < 2):
            errors.append(f"{r.get('id')}: parts must list at least two items")
        if "relativeHarmOverride" in r:
            if not overrides:
                errors.append(f"{r.get('id')}: overrides need harmOverrides")
            elif r["relativeHarmOverride"] not in NEED_SEVERITIES:
                errors.append(f"{r.get('id')}: relativeHarmOverride must be none, mild, moderate, or severe")
            elif r["score"] == best:
                errors.append(f"{r.get('id')}: the best option has no relative harm")
    if "needSeverity" in unit:
        errors.append(f"{label}: needSeverity is derived from the best score; use harmIfNotAddressedOverride")
    if "harmIfNotAddressedOverride" in unit:
        if not overrides:
            errors.append(f"{label}: overrides need harmOverrides")
        elif unit["harmIfNotAddressedOverride"] not in NEED_SEVERITIES:
            errors.append(f"{label}: harmIfNotAddressedOverride must be none, mild, moderate, or severe")
    # Decision 43: urgency cannot be derived from the score, so this is editable in both modes.
    if "harmIfDelayedOverride" in unit and unit["harmIfDelayedOverride"] not in NEED_SEVERITIES:
        errors.append(f"{label}: harmIfDelayedOverride must be none, mild, moderate, or severe")
    return errors + _not_appropriate_errors(_scored(unit, appropriate=False), appropriate, overrides, completeness_mode)


def _not_appropriate_errors(rows: list[dict[str, Any]], appropriate: list[dict[str, Any]],
                            overrides: bool, completeness_mode: str | None = None) -> list[str]:
    errors: list[str] = []
    for x in rows:
        if misplaced := [k for k in APPROPRIATE_ONLY if k in x]:
            errors.append(f"{x.get('id')}: rows scored 1-6 cannot carry {', '.join(misplaced)}")
        target = x.get("incompleteVersionOf")
        if target is not None:
            row = next((r for r in appropriate if r.get("id") == target), None)
            if row is None or (completeness_mode != "direct-v1" and not row.get("parts")):
                suffix = "" if completeness_mode == "direct-v1" else " with parts"
                errors.append(f"{x.get('id')}: incompleteVersionOf must name an appropriate recommendation{suffix}")
        if "harmIfRecommendedOverride" in x:
            if not overrides:
                errors.append(f"{x.get('id')}: overrides need harmOverrides")
            elif x["harmIfRecommendedOverride"] not in NEED_SEVERITIES:
                errors.append(f"{x.get('id')}: harmIfRecommendedOverride must be none, mild, moderate, or severe")
    return errors


def need_severity(d: dict[str, Any]) -> NeedSeverity:
    """The Decision's harm if not addressed: the override, else set by the best score."""
    return d.get("harmIfNotAddressedOverride") or SCORE_NEED[max(r["score"] for r in appropriate_rows(d))]


def delay_harm(d: dict[str, Any]) -> NeedSeverity | EventSeverity:
    """Harm of trying a 1-6 row before the best option (decisions 40, 43): the rater's value, else one step below the need."""
    if "harmIfDelayedOverride" in d:
        return d["harmIfDelayedOverride"]
    need = need_severity(d)
    return "none" if need == "none" else ONE_STEP_LOWER[need]


def relative_harm(d: dict[str, Any], row: dict[str, Any]) -> NeedSeverity | EventSeverity:
    """Harm of choosing this appropriate recommendation instead of the best one: the override,
    else the score gap capped one step below the Decision's harm if not addressed, so an
    accepted recommendation always costs less than silence."""
    gap = max(r["score"] for r in appropriate_rows(d)) - row["score"]
    if gap == 0:
        return "none"
    if row.get("relativeHarmOverride"):
        return row["relativeHarmOverride"]
    need = need_severity(d)
    cap = "none" if need == "none" else ONE_STEP_LOWER[need]
    derived = GAP_HARM[gap]
    return derived if HARM_ORDER.index(derived) <= HARM_ORDER.index(cap) else cap


def addresses_need(d: dict[str, Any], row: dict[str, Any]) -> bool:
    """Decision 45: an appropriate recommendation whose relative-harm override is at or above
    the Decision's harm if not addressed does not address the need. Only an explicit override
    triggers it, and never in a Decision whose harm if not addressed is none."""
    need = need_severity(d)
    override = row.get("relativeHarmOverride")
    if need == "none" or override is None or row["score"] == max(r["score"] for r in appropriate_rows(d)):
        return True
    return NEED_SEVERITIES.index(override) < NEED_SEVERITIES.index(need)


def _recommended_harm_event(x: dict[str, Any]) -> dict[str, Any] | None:
    """A recommended 1-6 row: the override's severity if set, else derived from the score."""
    level = x.get("harmIfRecommendedOverride")
    if level == "none":
        return None
    if level:
        return {"kind": "commission", "severity": level, "rowId": x["id"], "overridden": True}
    if x["score"] <= 3:
        return {"kind": "commission", "severity": COMMISSION_SEVERITY[x["score"]], "rowId": x["id"]}
    return {"kind": "uncertain", "severity": "uncertain", "rowId": x["id"]}


def _best(d: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """D060: the highest-scored row; among ties the one with the lowest relative harm, then the lowest row id,
    so the order the response lists its rows never changes the score."""
    return min(rows, key=lambda a: (-a["score"], HARM_ORDER.index(relative_harm(d, a)), a["id"]))


def _relative_event(d: dict[str, Any], row: dict[str, Any]) -> list[dict[str, Any]]:
    level = relative_harm(d, row)
    need = need_severity(d)
    # Choosing a lesser recommendation can never cost more than leaving the need unaddressed.
    if HARM_ORDER.index(level) > HARM_ORDER.index(need):
        level = need
    return [] if level == "none" else [{"kind": "relativeHarm", "severity": level, "rowId": row["id"]}]


def _complete(row: dict[str, Any], rec: dict[str, Any], completeness_mode: str | None = None) -> bool:
    if completeness_mode == "direct-v1":
        return rec["completeness"] == "complete"
    parts = row.get("parts")
    return not parts or set(rec.get("partsPresent", [])) >= set(parts)


def _enough_parts(row: dict[str, Any], rec: dict[str, Any]) -> bool:
    present = set(rec.get("partsPresent", [])) & set(row["parts"])
    return 2 * len(present) >= len(row["parts"])


def _branches(recs: list[dict[str, Any]]) -> list[set[str]]:
    """The plans a reader could follow first: the plan given now, and each alternative."""
    now = {r["rowId"] for r in recs if r.get("role", "first") in ("first", "addOn")}
    branches = ([now] if now else []) + [{r["rowId"]} for r in recs if r.get("role") == "alternative"]
    return branches or [{r["rowId"] for r in recs}]


def _recommended_ids(judge: dict[str, Any]) -> set[str]:
    return {
        rec["rowId"]
        for output in judge.get("decisions", {}).values()
        for rec in output.get("recommended", [])
    }


def score_case(
    case: dict[str, Any], judge: dict[str, Any], rho: float,
    weights: dict[str, float] = CANDIDATE_WEIGHTS,
    completeness_mode: str | None = None,
) -> dict[str, Any]:
    """Score one response against one case record. Deterministic; no model calls."""
    errors = validation_errors(case, completeness_mode)
    if errors:
        raise ValueError("; ".join(errors))
    if not 0 <= rho <= 1:
        raise ValueError("rho must be between 0 and 1")
    if not 0 < weights["uncertain"] < weights["mild"] < weights["moderate"] < weights["severe"]:
        raise ValueError("weights must increase from uncertain through mild, moderate, and severe")
    if completeness_mode not in (None, "direct-v1"):
        raise ValueError("unknown completeness mode")
    if completeness_mode == "direct-v1":
        from pipeline.rubric_validation import direct_completeness_errors
        if problems := direct_completeness_errors(judge):
            raise ValueError("; ".join(problems))
    outputs = judge.get("decisions", {})
    for did, output in outputs.items():
        for rec in output.get("recommended", []):
            if rec.get("role", "first") not in ROLES:
                raise ValueError(f"{did}: role must be one of {', '.join(ROLES)}")
    recommended = _recommended_ids(judge)

    fully_met_rows: set[str] = set()
    for d in case["decisions"]:
        out = outputs.get(d["id"], {})
        recs = out.get("recommended", [])
        if out.get("contradiction") or any(r.get("role") == "alternative" for r in recs):
            continue
        unsafe_targets = {r.get("incompleteVersionOf") for r in _scored(d, appropriate=False)
                          if any(rec["rowId"] == r["id"] for rec in recs)}
        for rec in recs:
            row = next((r for r in appropriate_rows(d) if r["id"] == rec["rowId"]), None)
            if (row is not None and _complete(row, rec, completeness_mode) and addresses_need(d, row)
                    and (completeness_mode != "direct-v1" or row["id"] not in unsafe_targets)
                    and rec.get("role", "first") in ("first", "addOn")):
                fully_met_rows.add(row["id"])

    results: dict[str, dict[str, Any]] = {}
    for d in case["decisions"]:
        results[d["id"]] = _score_decision(
            case, d, outputs, recommended, fully_met_rows, rho, completeness_mode
        )
    tally = {s: 0 for s in ("severe", "moderate", "mild", "uncertain")}
    tally["contradiction"] = 0
    for r in results.values():
        for e in r["events"]:
            tally["contradiction" if e["kind"] == "contradiction" else e["severity"]] += 1
    worst = max((e["severity"] for r in results.values() for e in r["events"]),
                key=HARM_ORDER.index, default="none")
    return {
        "caseId": case.get("caseId"),
        "decisions": results,
        "worstHarm": worst,
        **_f1(case, outputs, results, weights),
        "harmCounts": tally,
        "provisional": any(r["provisional"] for r in results.values()),
    }


def _f1(case: dict[str, Any], outputs: dict[str, Any], results: dict[str, dict[str, Any]],
        weights: dict[str, float]) -> dict[str, float]:
    """Severity-weighted Recall, Precision, and F1 (S01 design section 7; decision 41)."""
    def weight(level: str) -> float:
        return weights["uncertain"] if level in ("none", "uncertain") else weights[level]

    recall_num = recall_den = precision_num = precision_den = 0.0
    for d in case["decisions"]:
        r = results[d["id"]]
        if r["state"] == "inactive":
            for e in r["events"]:
                precision_den += weight(e["severity"])
            continue
        out = outputs.get(d["id"], {})
        # Decision 47: a Decision whose harm if not addressed is none only catches harmful
        # rows: it is left out of Recall, and its appropriate rows are left out of Precision.
        none_need = need_severity(d) == "none"
        if not none_need:
            w = weight(need_severity(d))
            recall_den += w
            recall_num += w * r["credit"]
        appropriate = {a["id"]: a for a in appropriate_rows(d)}
        not_appropriate = {x["id"]: x for x in not_appropriate_rows(d)}
        for rec in out.get("recommended", []):
            if rec["rowId"] in appropriate:
                if none_need or not addresses_need(d, appropriate[rec["rowId"]]):
                    continue
                w_row = weight(SCORE_SEVERITY[appropriate[rec["rowId"]]["score"]])
                precision_den += w_row
                if not out.get("contradiction"):
                    precision_num += w_row
            elif rec["rowId"] in not_appropriate:
                event = _recommended_harm_event(not_appropriate[rec["rowId"]])
                precision_den += weight(event["severity"] if event else "none")
        for statement in out.get("unmatched", []):
            harm = statement.get("provisional", {}).get("harm")
            if harm:
                precision_den += weight(harm["severity"])
    recall = recall_num / recall_den if recall_den else 0.0
    precision = precision_num / precision_den if precision_den else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"recall": recall, "precision": precision, "f1": f1}


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Headlines across scored responses: worst-harm distribution, share with a severe harm, mean F1."""
    n = len(results)
    if not n:
        raise ValueError("no results to summarize")
    return {
        "responses": n,
        "worstHarm": {level: sum(r["worstHarm"] == level for r in results) for level in HARM_ORDER},
        "severeShare": sum(r["worstHarm"] == "severe" for r in results) / n,
        "meanF1": sum(r["f1"] for r in results) / n,
        "provisional": sum(r["provisional"] for r in results),
    }


def _inactive(reason: str) -> dict[str, Any]:
    return {"state": "inactive", "reason": reason, "outcome": None, "credit": None,
            "events": [], "provisional": False}


def _score_decision(
    case: dict[str, Any],
    d: dict[str, Any],
    outputs: dict[str, Any],
    recommended: set[str],
    fully_met_rows: set[str],
    rho: float,
    completeness_mode: str | None = None,
) -> dict[str, Any]:
    out = outputs.get(d["id"], {})
    recs = out.get("recommended", [])
    unmatched = out.get("unmatched", [])
    need = need_severity(d)

    activation = d.get("activation", {"type": "always"})
    appropriate = {a["id"]: a for a in appropriate_rows(d)}
    not_appropriate = {x["id"]: x for x in not_appropriate_rows(d)}

    def _recommended_harms() -> list[dict[str, Any]]:
        return [e for e in (_recommended_harm_event(not_appropriate[r["rowId"]])
                            for r in recs if r["rowId"] in not_appropriate) if e]

    def _inactive_charging(reason: str) -> dict[str, Any]:
        # An inactive Decision still charges any harmful row the response recommends.
        result = _inactive(reason)
        result["events"] = _recommended_harms()
        result["events"] += _unmatched_events(unmatched)
        result["provisional"] = bool(unmatched)
        return result

    if activation["type"] == "onlyIf":
        gate_rows = set(activation["rows"])
        if not gate_rows & recommended:
            return _inactive_charging("upstream recommendation not selected")
        require_all = activation.get("match", "any") == "all"
        parents = [p for p in case["decisions"] if gate_rows & {r["id"] for r in _rows(p)}]
        satisfied = []
        for parent in parents:
            required = gate_rows & {r["id"] for r in _rows(parent)}
            parent_out = outputs.get(parent["id"], {})
            extras = {a["id"] for a in appropriate_rows(parent) if not addresses_need(parent, a)}
            current = [r for r in parent_out.get("recommended", []) if r.get("role", "first") != "fallback"
                       and (completeness_mode != "direct-v1" or r["completeness"] != "absent")]
            plans = [b for b in _branches(current) if not b <= extras]
            satisfied.append(not parent_out.get("contradiction") and bool(plans) and all(
                required <= b if require_all else bool(b & required) for b in plans))
        if not (all(satisfied) if require_all else any(satisfied)):
            return _inactive_charging("trigger recommendations not included in every current plan")
    if activation["type"] == "future" and not activation["scoredNow"] and not recs and not unmatched:
        return _inactive("future event; silence not charged")
    if not recs and not unmatched:
        coverer = next(
            (a["id"] for p in case["decisions"] for a in appropriate_rows(p)
             if d["id"] in a.get("alsoTakesCareOf", []) and a["id"] in fully_met_rows),
            None,
        )
        if coverer:
            return _inactive(f"taken care of by {coverer}")

    events: list[dict[str, Any]] = []
    if out.get("contradiction"):
        # A contradiction still charges every harmful row the response recommends.
        events += _recommended_harms()
        events += _unmatched_events(unmatched)
        events.append({"kind": "contradiction", "severity": need})
        return {"state": "scored", "outcome": "notMet", "credit": 0.0,
                "events": events, "provisional": bool(unmatched)}

    if not recs and unmatched:
        return _provisional(unmatched, need, rho)

    # Decision 45: an appropriate row that does not address the need is ignored for the outcome.
    appropriate_recs = [(appropriate[r["rowId"]], r) for r in recs
                        if r["rowId"] in appropriate and addresses_need(d, appropriate[r["rowId"]])]
    not_appropriate_recs = [not_appropriate[r["rowId"]] for r in recs if r["rowId"] in not_appropriate]
    events += _recommended_harms()
    events += _unmatched_events(unmatched)
    overridden = {x["incompleteVersionOf"] for x in not_appropriate_recs
                  if x.get("incompleteVersionOf") and addresses_need(d, appropriate[x["incompleteVersionOf"]])}

    best = max(a["score"] for a in appropriate.values())
    complete = [a for a, r in appropriate_recs if _complete(a, r, completeness_mode)
                and (completeness_mode != "direct-v1" or a["id"] not in overridden)]
    half = [a for a, r in appropriate_recs if a["id"] not in overridden and (
        r["completeness"] == "partial" if completeness_mode == "direct-v1"
        else a.get("parts") and not _complete(a, r) and _enough_parts(a, r))]
    branches = _branches(recs)
    branch_rows = [[a for a in complete if a["id"] in b] for b in branches]
    outcome: Outcome
    if complete and all(branch_rows):
        # Every plan the reader could follow first gives an appropriate recommendation; the
        # weakest branch's best recommendation sets the outcome.
        chosen = [_best(d, br) for br in branch_rows]
        if all(a["score"] == best for a in chosen):
            outcome = "met"
        else:
            outcome = "partly"
            events += _relative_event(d, min(chosen, key=lambda a: (-HARM_ORDER.index(relative_harm(d, a)), a["id"])))
    elif complete:
        # Decisions 40 and 42: a plan the reader could follow first has no appropriate
        # recommendation (a 1-6 row tried first or offered as an equal alternative).
        available = _best(d, complete)
        delay = delay_harm(d)
        if available["score"] < best:
            outcome = "partly"
            events += _relative_event(d, available)
        elif delay == "none":
            outcome = "met"
        else:
            outcome = "partly"
            empty = set().union(*(b for b, br in zip(branches, branch_rows) if not br))
            ahead = min((r["rowId"] for r in recs if r["rowId"] in empty and r["rowId"] in not_appropriate), default=None)
            events.append({"kind": "delay", "severity": delay, "rowId": ahead})
    elif half:
        outcome = "partly"
        if need != "none":
            events.append({"kind": "residualOmission", "severity": ONE_STEP_LOWER[need]})
        events += _relative_event(d, _best(d, half))
    else:
        outcome = "notMet"
        # Decision 41: the unmet need is always charged, except for a future plan not
        # yet scored (decision 26); an incomplete-version row's score is the whole
        # charge (decision 25).
        future_only = activation["type"] == "future" and not activation["scoredNow"]
        if need != "none" and not overridden and not future_only:
            events.append({"kind": "omission", "severity": need})
    return {
        "state": "scored",
        "outcome": outcome,
        "credit": {"met": 1.0, "partly": rho, "notMet": 0.0}[outcome],
        "events": events,
        "provisional": bool(unmatched),
    }


def _unmatched_events(unmatched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every unmatched statement's provisional harm is charged, not just the first."""
    return [{"kind": h["kind"], "severity": h["severity"]}
            for h in (s.get("provisional", {}).get("harm") for s in unmatched) if h]


def _provisional(unmatched: list[dict[str, Any]], need: NeedSeverity, rho: float) -> dict[str, Any]:
    read = [s.get("provisional", {}).get("outcome", "notMet") for s in unmatched]
    if bad := [o for o in read if o not in OUTCOMES]:
        raise ValueError(f"invalid provisional outcome: {bad[0]}")
    # D060: the best statement sets the outcome, as the best row of a plan does, so statement order never matters.
    outcome = min(read, key=OUTCOMES.index)
    events = _unmatched_events(unmatched)
    if need == "none":
        pass
    elif outcome == "partly":
        events.append({"kind": "residualOmission", "severity": ONE_STEP_LOWER[need]})
    elif outcome == "notMet":
        events.append({"kind": "omission", "severity": need})
    return {
        "state": "provisional",
        "outcome": outcome,
        "credit": {"met": 1.0, "partly": rho, "notMet": 0.0}[outcome],
        "events": events,
        "provisional": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path, help="rubric case record (JSON)")
    parser.add_argument("judge", type=Path, help="judge output for one response (JSON)")
    parser.add_argument("--rho", type=float, required=True)
    args = parser.parse_args()
    case = json.loads(args.case.read_text())
    judge = json.loads(args.judge.read_text())
    print(json.dumps(score_case(case, judge, args.rho), indent=2))


if __name__ == "__main__":
    main()
