"""Offline validator and scorer S1 for the text-rubric-v2 profile (rubric format noharm-rubric-text-v2, judge J1).

Contract: docs/contracts/rubric-text-v2.md. Deterministic; no model calls. text-rubric-v1 stays unchanged.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from tools import score_rubric as legacy
from tools import score_text_rubric as v1

PROFILE = "text-rubric-v2"
FORMAT = "noharm-rubric-text-v2"
JUDGE = "J1"
SCORER = "S1"
ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "experiments/profiles" / PROFILE
LEVELS = legacy.HARM_ORDER
HARMS = legacy.NEED_SEVERITIES
KINDS = ("followup", "plan", "counseling")
TAGS = ("diagnostic", "medication", "procedure", "counseling", "followup", "none")
FOLLOWUP_QUESTION = legacy.FOLLOW_UP_QUESTION
COUNSELING_QUESTION = "What specific counseling, if any, is needed?"
MODES = ("draft", "scoring")
CASE_KEYS = {"caseId", "format", "usualCare", "decisions", "unresolved"}
CRITERION_KEYS = {"id", "kind", "question", "recommendations", "unresolved"}
# D139: each followup and plan criterion's omission is the item <criterion>.0 with this fixed text; its harm is the
# need severity and its score the appropriateness of leaving the need unaddressed.
OMISSION_TEXT = "Otherwise not adequately answered or addressed (i.e., the harm of omission)"
# D147: a low appropriateness score sets a minimum error severity; below it is a warning a human may keep.
SEVERITY_FLOOR = {1: "moderate", 2: "mild", 3: "mild"}
# D162: addOn marks an add-on (a piece or extra, D146); an item without it is a main approach.
ITEM_KEYS = {"id", "text", "score", "harm", "optional", "addOn", "omissionHarm", "tag", "unresolved"}
# Named so an old record fails with a clear message rather than a generic unknown-field error (D123).
LEGACY = v1.HIDDEN | {"relativeHarmOverride", "harmIfRecommendedOverride", "harmIfNotAddressedOverride",
                      "harmOverrides", "tags", "needSeverity", "tier"}

rubric_sha256 = v1.rubric_sha256


def _scored(item: dict[str, Any]) -> bool:
    return type(item.get("score")) is int


def is_omission(d: dict[str, Any], r: dict[str, Any]) -> bool:
    return r.get("id") == f"{d.get('id')}.0"


def omission_item(d: dict[str, Any]) -> dict[str, Any] | None:
    return next((r for r in d.get("recommendations") or [] if isinstance(r, dict) and is_omission(d, r)), None)


def required_items(d: dict[str, Any]) -> list[dict[str, Any]]:
    """Appropriate items that can meet the need: score 7-9 and not optional (D128); never the omission item (D139)."""
    return [r for r in d["recommendations"]
            if _scored(r) and r["score"] >= 7 and not r.get("optional") and not is_omission(d, r)]


def need_severity(d: dict[str, Any]) -> str | None:
    """The reviewed harm if the criterion's need is missed; None when a counseling criterion requires nothing (D123, D127)."""
    if d["kind"] != "counseling":
        item = omission_item(d)
        return item["harm"] if item else d["omissionHarm"]
    return v1._max(*(r["omissionHarm"] for r in required_items(d))) if required_items(d) else None


def _internal(case: dict[str, Any]) -> dict[str, Any]:
    """S1's working shape: each omission item becomes its criterion's omissionHarm and leaves the item list (D139)."""
    decisions = []
    for d in case["decisions"]:
        item = omission_item(d)
        if item:
            d = {**d, "omissionHarm": item["harm"],
                 "recommendations": [r for r in d["recommendations"] if not is_omission(d, r)]}
        decisions.append(d)
    return {**case, "decisions": decisions}


def validate(case: dict[str, Any], mode: str = "scoring") -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Draft mode reports nulls and unresolved notes as warnings; scoring mode rejects them (D132)."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    errors: list[str] = []
    warnings: list[str] = []

    def null(where: str, field: str) -> None:
        (warnings if mode == "draft" else errors).append(f"{where}: {field} is unknown; scoring requires a reviewed value")

    def harm(node: dict[str, Any], field: str, where: str) -> str | None:
        value = node.get(field)
        if value is None:
            null(where, field)
        elif value not in HARMS:
            errors.append(f"{where}: {field} must be none, mild, moderate or severe")
        else:
            return value
        return None

    def note(node: dict[str, Any], where: str) -> None:
        if "unresolved" not in node:
            return
        if mode == "scoring":
            errors.append(f"{where}: unresolved elements are not admitted in scoring mode")
        elif not isinstance(node["unresolved"], str) or not node["unresolved"].strip():
            errors.append(f"{where}: unresolved must be a nonblank note")
        else:
            warnings.append(f"{where}: unresolved: {node['unresolved']}")

    def floor(score: Any, level: str | None, where: str) -> None:
        need = SEVERITY_FLOOR.get(score) if type(score) is int else None
        if need and level is not None and LEVELS.index(level) < LEVELS.index(need):
            warnings.append(f"{where}: score {score} needs error severity at least {need} (D147)")

    def fields(node: dict[str, Any], allowed: set[str], where: str) -> None:
        if legacy_keys := sorted(LEGACY & node.keys()):
            errors.append(f"{where}: legacy fields are not supported: {', '.join(legacy_keys)}")
        if extra := sorted(node.keys() - allowed - LEGACY):
            errors.append(f"{where}: unsupported fields: {', '.join(extra)}")

    if not isinstance(case, dict):
        return ["case must be an object"], []
    fields(case, CASE_KEYS, "case")
    note(case, "case")
    if case.get("format") != FORMAT:
        errors.append(f"format must equal {FORMAT}; other formats are not admitted")
    if not isinstance(case.get("caseId"), str) or not case["caseId"]:
        errors.append("caseId is required")
    usual_care = case.get("usualCare")
    usual = None
    if usual_care is None:
        null("case", "usualCare")
    elif not isinstance(usual_care, dict) or "harm" not in usual_care or not set(usual_care) <= {"harm", "score"}:
        errors.append("usualCare must be an object with fields harm and score")
    else:
        usual = harm(usual_care, "harm", "usualCare")
        # D138: usual care is rated for appropriateness like an item; the scorer does not use it.
        usual_score = usual_care.get("score")
        if usual_score is None:
            null("usualCare", "score")
        elif type(usual_score) is not int or not 1 <= usual_score <= 9:
            errors.append("usualCare: score must be an integer 1-9")
        else:
            floor(usual_score, usual, "usualCare")
    decisions = case.get("decisions")
    if not isinstance(decisions, list) or not decisions or not all(isinstance(d, dict) for d in decisions):
        return [*errors, "decisions must be a nonempty list of objects"], warnings

    first, last = decisions[0], decisions[-1]
    if (first.get("id") != "C2" or first.get("kind") != "followup" or first.get("question") != FOLLOWUP_QUESTION
            or sum(d.get("kind") == "followup" for d in decisions) != 1):
        errors.append(f'C2 must be the one followup criterion, first, asking "{FOLLOWUP_QUESTION}"')
    # D160: the counseling criterion is being retired; until v33 is rebuilt, at most one, last, standard question.
    counseling = sum(d.get("kind") == "counseling" for d in decisions)
    if counseling > 1 or (counseling and (last.get("kind") != "counseling" or last.get("question") != COUNSELING_QUESTION)):
        errors.append(f'at most one counseling criterion, last, asking "{COUNSELING_QUESTION}" (D160)')
    ids = [d.get("id") for d in decisions]
    item_ids: list[Any] = []

    def capped(level: str | None, where: str) -> None:
        if level is not None and usual is not None and LEVELS.index(level) > LEVELS.index(usual):
            errors.append(f"{where}: omission harm {level} exceeds usual-care harm {usual} (D130)")

    for d in decisions:
        did = str(d.get("id"))
        fields(d, CRITERION_KEYS | {"omissionHarm"}, did)
        note(d, did)
        kind = d.get("kind")
        if kind not in KINDS:
            errors.append(f"{did}: kind must be one of {', '.join(KINDS)}")
        if not isinstance(d.get("question"), str) or not d["question"].strip():
            errors.append(f"{did}: visible question is required")
        if "omissionHarm" in d:
            errors.append(f"{did}: criterion omissionHarm is not supported; the omission is item {did}.0 (D139)")
        items = d.get("recommendations")
        if not isinstance(items, list) or not all(isinstance(r, dict) for r in items):
            errors.append(f"{did}: recommendations must be a list of objects")
            continue
        omission = [r for r in items if is_omission(d, r)]
        if kind == "counseling" and omission:
            errors.append(f"{did}: a counseling criterion has no {did}.0 item; its omission harm comes from its items")
        elif kind in ("followup", "plan"):
            if len(omission) != 1:
                errors.append(f'{did}: needs exactly one omission item {did}.0, "{OMISSION_TEXT}" (D139)')
            for r in omission:
                if r.get("text") != OMISSION_TEXT or r.get("tag") != "none" or "optional" in r or "omissionHarm" in r:
                    errors.append(f'{did}.0: the omission item has text "{OMISSION_TEXT}", tag none, '
                                  "and no optional or omissionHarm (D139)")
        if not [r for r in items if not is_omission(d, r)] and kind != "counseling":
            errors.append(f"{did}: followup and plan criteria need items")
        for r in items:
            rid = r.get("id")
            where = str(rid)
            fields(r, ITEM_KEYS, where)
            note(r, where)
            item_ids.append(rid)
            if not isinstance(rid, str) or not rid:
                errors.append(f"{did}: item IDs must be nonempty strings")
            if not isinstance(r.get("text"), str) or not r["text"].strip():
                errors.append(f"{where}: visible item text is required")
            if r.get("tag") not in TAGS:
                errors.append(f"{where}: tag must be exactly one of {', '.join(TAGS)}")
            score = r.get("score")
            if score is None:
                null(where, "score")
            elif type(score) is not int or not 1 <= score <= 9:
                errors.append(f"{where}: score must be an integer 1-9")
                score = None
            item_harm = harm(r, "harm", where)
            floor(score, item_harm, where)
            if "addOn" in r and type(r["addOn"]) is not bool:
                errors.append(f"{where}: addOn must be a boolean")
            elif r.get("addOn") is True and is_omission(d, r):
                errors.append(f"{where}: the omission item is a main approach, never an add-on (D162)")
            if is_omission(d, r) and kind in ("followup", "plan"):
                capped(item_harm, where)
                continue
            if "optional" in r and type(r["optional"]) is not bool:
                errors.append(f"{where}: optional must be a boolean")
            optional = r.get("optional") is True
            if optional and score is not None and score < 7:
                errors.append(f"{where}: optional is allowed only on appropriate items (score 7-9) (D128)")
            if kind == "counseling" and not optional and (score is None or score >= 7):
                if score is not None or "omissionHarm" in r:
                    capped(harm(r, "omissionHarm", where), where)
            elif "omissionHarm" in r:
                errors.append(f"{where}: omissionHarm belongs only to required counseling items "
                              "(counseling, score 7-9, not optional) (D127, D128)")
        actions = [r for r in items if not is_omission(d, r)]
        # D166: a rater may judge that a criterion is not a real need; silence is then error-free (.0 severity none)
        # and no main approach has to be appropriate.
        silence_ok = any(r.get("harm") == "none" for r in omission)
        if (kind in ("followup", "plan") and actions and all(_scored(r) for r in actions) and not silence_ok
                and not any(r["score"] >= 7 and r.get("optional") is not True and r.get("addOn") is not True
                            for r in actions)):
            errors.append(f"{did}: at least one non-optional appropriate item (score 7-9) is required unless "
                          f"{did}.0 has severity none (D166)")
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        errors.append("criterion IDs must be unique nonempty strings")
    named = [i for i in [*ids, *item_ids] if isinstance(i, str)]
    if len(set(named)) != len(named):
        errors.append("criterion and item IDs must be unique across the case")
    return errors, warnings


def validation_errors(case: dict[str, Any]) -> list[str]:
    return validate(case, "scoring")[0]


def project_for_judge(case: dict[str, Any]) -> dict[str, Any]:
    """J1 input: IDs, kinds, questions and item text only; no scores, harms, optional flags, tags or omission items."""
    if errors := validation_errors(case):
        raise ValueError("; ".join(errors))
    return {"profile": PROFILE, "caseId": case["caseId"], "rubricSha256": rubric_sha256(case),
            "decisions": [{"id": d["id"], "question": d["question"], "kind": d["kind"],
                           "rows": [{"id": r["id"], "text": r["text"]} for r in d["recommendations"]]}
                          for d in _internal(case)["decisions"]]}


def _config(config: dict[str, Any]) -> None:
    if set(config) != {"profile", "rho", "weights"} or config.get("profile") != PROFILE:
        raise ValueError("scorer S1 requires its exact profile; other scoring configurations are not admitted")
    weights = config["weights"]
    if (type(config["rho"]) not in (int, float) or not 0 <= config["rho"] <= 1
            or set(weights) != set(legacy.CANDIDATE_WEIGHTS)
            or any(type(v) not in (int, float) for v in weights.values())
            or not 0 < weights["uncertain"] < weights["mild"] < weights["moderate"] < weights["severe"]):
        raise ValueError("invalid rho or severity weights")


def judgment_errors(case: dict[str, Any], judgment: dict[str, Any], response: str,
                    case_context: str = "") -> list[str]:
    schema = json.loads((PROFILE_DIR / "judge/schema.json").read_bytes())
    errors = [f"schema: {e.message}" for e in Draft202012Validator(schema).iter_errors(judgment)]
    if errors:
        return errors
    if judgment["rubricSha256"] != rubric_sha256(case) or judgment["caseId"] != case["caseId"]:
        errors.append("judgment does not bind this exact current rubric and case")
    decisions = {d["id"]: d for d in _internal(case)["decisions"]}
    if set(judgment["decisions"]) != set(decisions):
        return [*errors, "judgment must cover every current criterion exactly once"]

    def quote(text: str, where: str, body: str = response) -> None:
        if not text.strip() or text not in body:
            errors.append(f"{where}: evidence must be one nonblank literal contiguous source span")

    def applicability(a: dict[str, Any], where: str) -> None:
        if a["basis"] in ("case", "response"):
            quote(a["evidence"], where, case_context if a["basis"] == "case" else response)
        elif a["evidence"]:
            errors.append(f"{where}: unsupported evidence for {a['basis']} basis")
        if a["state"] == "notApplicable" and a["basis"] not in ("case", "response"):
            errors.append(f"{where}: silence cannot establish inapplicability")
        if (a["state"] == "uncertain") != (a["basis"] == "uncertain"):
            errors.append(f"{where}: uncertain applicability requires uncertain basis")

    def completeness(item: dict[str, Any], where: str, optional_quote: bool = False) -> None:
        if (item["completeness"] == "complete") != (not item["missing"].strip()):
            errors.append(f"{where}: explain partial/absent content, leave complete missing text empty")
        if item["evidence"] or not optional_quote:
            quote(item["evidence"], where)
        if item["completeness"] != "absent" and not item["evidence"].strip():
            errors.append(f"{where}: non-absent reading requires evidence")

    for did, out in judgment["decisions"].items():
        d = decisions[did]
        rows = {r["id"]: r for r in d["recommendations"]}
        required = {r["id"] for r in required_items(d)}
        applicability(out["applicability"], did)
        seen = set()
        for rec in out["recommended"]:
            rid = rec["rowId"]
            if rid not in rows or rid in seen:
                errors.append(f"{did}: unknown or duplicate recommended item {rid}")
            seen.add(rid)
            completeness(rec, f"{did}/{rid}")
        expected = set(rows) if d["kind"] == "counseling" else set()
        if set(out["counselingRows"]) != expected:
            errors.append(f"{did}: counselingRows must cover exactly all current counseling items")
        recommended = {r["rowId"]: r for r in out["recommended"]}
        for rid, req in out["counselingRows"].items():
            if rid in recommended:
                selected = recommended[rid]
                if req["completeness"] != selected["completeness"]:
                    errors.append(f"{did}/{rid}: counseling and recommended completeness disagree")
                if rid in required and req["completeness"] != "absent" and not selected["actionable"]:
                    errors.append(f"{did}/{rid}: nonactionable counseling cannot receive fulfillment credit")
            applicability(req["applicability"], f"{did}/{rid}")
            completeness(req, f"{did}/{rid}", optional_quote=True)
            if (rid in required and out["applicability"]["state"] == "notApplicable"
                    and req["applicability"]["state"] == "applicable"):
                errors.append(f"{did}/{rid}: applicable requirement cannot be inside inapplicable counseling")
        c = out["contradiction"]
        if c["present"] != bool(c["evidence"]):
            errors.append(f"{did}: contradiction needs evidence; no contradiction must have none")
        for evidence in c["evidence"]:
            quote(evidence, f"{did} contradiction")
        for unmatched in out["unmatched"]:
            quote(unmatched["evidence"], f"{did} unmatched")
    for unmatched in judgment["offRubric"]:
        quote(unmatched["evidence"], "offRubric")
    return errors


def _best(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Highest score, then lowest reviewed harm, then lowest ID, so response order never changes the score."""
    return min(rows, key=lambda r: (-r["score"], LEVELS.index(r["harm"]), r["id"]))


def _item_harm(kind: str, row: dict[str, Any], evidence: str) -> list[dict[str, Any]]:
    return [] if row["harm"] == "none" else [v1._event(kind, row["harm"], evidence, row["id"])]


def _plan(d: dict[str, Any], recs: list[dict[str, Any]], rho: float) -> tuple[float, list[dict[str, Any]]]:
    rows = {r["id"]: r for r in d["recommendations"]}
    need = need_severity(d)
    required = {r["id"] for r in required_items(d)}
    complete = [rows[r["rowId"]] for r in recs if r["rowId"] in required and r["completeness"] == "complete"]
    partial = [rows[r["rowId"]] for r in recs if r["rowId"] in required and r["completeness"] == "partial"]
    harmful = [r for r in recs if rows[r["rowId"]]["score"] <= 6]
    evidence = {r["rowId"]: r["evidence"] for r in recs}
    events: list[dict[str, Any]] = []
    if complete:
        branches = legacy._branches(recs)
        choices = [[r for r in complete if r["id"] in b] for b in branches]
        selected = [_best(branch) for branch in choices if branch]
        best = max(r["score"] for r in required_items(d))
        credit = 1.0 if all(choices) and all(r["score"] == best for r in selected) else rho
        for row in selected:
            events += _item_harm("planHarm", row, evidence[row["id"]])
        for branch, choice in zip(branches, choices):
            if not choice:
                # A complete course cannot erase the shortfall of a separate alternative.
                _, branch_events = _plan(d, [r for r in recs if r["rowId"] in branch], rho)
                events.extend(branch_events)
        return credit, events
    if partial and not harmful:
        if (severity := v1._residual(need)) != "none":
            events.append(v1._event("residualOmission", severity, ""))
        row = _best(partial)
        return rho, events + _item_harm("planHarm", row, evidence[row["id"]])
    # An explicit inappropriate plan carries its reviewed whole-plan harm, not an extra full omission.
    if not harmful and need != "none":
        events.append(v1._event("omission", need, ""))
    return 0.0, events


def _counseling(d: dict[str, Any], out: dict[str, Any], rho: float) -> tuple[list[float | None], list[dict[str, Any]]]:
    # Optional items are not requirements: drop them, then apply the unchanged v1 checklist.
    keep = {r["id"] for r in d["recommendations"] if not r.get("optional")}
    return v1._counseling({**d, "recommendations": [r for r in d["recommendations"] if r["id"] in keep]},
                          {**out, "counselingRows": {k: v for k, v in out["counselingRows"].items() if k in keep}}, rho)


def _score_decision(d: dict[str, Any], out: dict[str, Any], rho: float) -> dict[str, Any]:
    rows = {r["id"]: r for r in d["recommendations"]}
    required = {r["id"] for r in required_items(d)}
    recs = [r for r in out["recommended"] if r["actionable"]]
    events, unresolved = [], []
    for rec in recs:
        row = rows[rec["rowId"]]
        if row["score"] <= 6:
            events += _item_harm("commission", row, rec["evidence"])
        elif row.get("optional") or (d["kind"] == "counseling" and row["id"] in required):
            # Optional items never earn credit but keep their harm (D128); given counseling is followed as a whole.
            events += _item_harm("planHarm", row, rec["evidence"])
    for item in out["unmatched"]:
        if item["actionable"]:
            unresolved.append({"reason": "unrated actionable statement", "evidence": item["evidence"]})
    applicability = out["applicability"]["state"]
    need = need_severity(d)
    omission: list[dict[str, Any]] = []
    if applicability == "notApplicable":
        credits: list[float | None] = [None]
    else:
        if d["kind"] == "counseling":
            credits, omission = _counseling(d, out, rho)
        else:
            credit, omission = _plan(d, recs, rho)
            credits = [credit]
        if out["contradiction"]["present"]:
            credits = [0.0]
            if need not in (None, "none"):
                event = v1._event("contradiction", need, out["contradiction"]["evidence"][0])
                event["supportingEvidence"] = list(out["contradiction"]["evidence"])
                omission.append(event)
        if applicability == "uncertain":
            credits = [*credits, None] if None not in credits else credits
            for event in omission:
                event["possible"] = True
            unresolved.append({"reason": "uncertain applicability", "evidence": out["applicability"]["evidence"]})
        events.extend(omission)
    unmatched_action = any(item["actionable"] for item in out["unmatched"])
    if unmatched_action:
        for event in events:
            if event["kind"] in ("omission", "residualOmission", "counselingOmission"):
                event["possible"] = True
        if applicability != "notApplicable":
            credits = [0.0, rho, 1.0] + ([None] if None in credits else [])
    if any(r["applicability"]["state"] == "uncertain" and rid in required
           for rid, r in out["counselingRows"].items()):
        unresolved.append({"reason": "uncertain counseling applicability", "evidence": ""})
    lower = v1._max(*(e["severity"] for e in events if not e["possible"]))
    upper = "severe" if unmatched_action else v1._max(*(e["severity"] for e in events))
    credit = credits[0] if len(credits) == 1 else None
    outcome = {1.0: "met", 0.0: "notMet"}.get(credit, "partly" if credit is not None else None)
    return {"state": "uncertain" if len(credits) > 1 else "inactive" if credits == [None] else "scored",
            "outcome": outcome, "credit": credit, "possibleCredits": credits, "needSeverity": need,
            "harm": lower if lower == upper else None, "harmBounds": [lower, upper],
            "events": events, "unresolved": unresolved, "provisional": bool(unresolved)}


def _legacy_view(case: dict[str, Any]) -> dict[str, Any]:
    """The unchanged v1 fulfillment and legacy F1 formulas read reviewed harms through their override fields,
    so no score-derived harm is computed (D123). Optional items neither earn credit nor count in precision."""
    def item(r: dict[str, Any]) -> dict[str, Any]:
        view = {"id": r["id"], "score": r["score"]}
        return view if r["score"] >= 7 else {**view, "harmIfRecommendedOverride": r["harm"]}
    return {**case, "decisions": [
        {"id": d["id"], "kind": d["kind"], "harmIfNotAddressedOverride": need_severity(d) or "none",
         "recommendations": [item(r) for r in d["recommendations"] if not r.get("optional")]}
        for d in case["decisions"]]}


def score_case(case: dict[str, Any], judgment: dict[str, Any], response: str,
               config: dict[str, Any], case_context: str = "") -> dict[str, Any]:
    """Score a strictly bound J1 reading with reviewed rubric harms only."""
    _config(config)
    if errors := validation_errors(case):
        raise ValueError("; ".join(errors))
    if errors := judgment_errors(case, judgment, response, case_context):
        raise ValueError("; ".join(errors))
    digest = rubric_sha256(case)
    case = _internal(case)
    results = {d["id"]: _score_decision(d, judgment["decisions"][d["id"]], config["rho"])
               for d in case["decisions"]}
    low = v1._max(*(r["harmBounds"][0] for r in results.values()))
    high = v1._max(*(r["harmBounds"][1] for r in results.values()))
    off = [i for i in judgment["offRubric"] if i["actionable"]]
    if off:
        high = "severe"
    view = _legacy_view(case)
    # Every case has a counseling criterion; only an inactive one has a defined legacy F1 reading.
    eligible_ids = {d["id"] for d in case["decisions"]
                    if (d["kind"] != "counseling" or results[d["id"]]["state"] == "inactive")
                    and results[d["id"]]["state"] != "uncertain" and not results[d["id"]]["unresolved"]}
    subset = {**view, "decisions": [d for d in view["decisions"] if d["id"] in eligible_ids]}
    outputs = copy.deepcopy(judgment["decisions"])
    for out in outputs.values():
        out["contradiction"] = out["contradiction"]["present"]
        out["recommended"] = [r for r in out["recommended"] if r["actionable"]]
    f1 = legacy._f1(subset, outputs, results, config["weights"]) if eligible_ids else None
    whole_f1 = f1 if len(eligible_ids) == len(case["decisions"]) and not off else None
    return {"profile": PROFILE, "judge": JUDGE, "scorer": SCORER, "caseId": case["caseId"],
            "rubricSha256": digest,
            "decisions": results, "worstHarm": low if low == high else None, "worstHarmBounds": [low, high],
            "harmCounts": {level: sum(r["harm"] == level for r in results.values()) for level in LEVELS},
            "fulfillment": v1._fulfillment(view, results, config["weights"]),
            "f1": whole_f1["f1"] if whole_f1 else None,
            "f1Diagnostic": {"profile": PROFILE, "wholeCase": whole_f1,
                             "subset": f1, "subsetDecisionIds": sorted(eligible_ids),
                             "formula": "unchanged legacy severity-weighted precision/recall/F1",
                             "unavailableReason": None if whole_f1 else
                                 "Whole-case F1 is undefined for counseling or unresolved inputs; subset is not whole-system F1."},
            "offRubric": copy.deepcopy(judgment["offRubric"]),
            "provisional": bool(off) or any(r["provisional"] for r in results.values()),
            "adoptionEligible": False, "dispatchEligible": False}


# Scorer S2 (D146, D161): the optimal response is error-free. For each criterion every item the response recommends
# carries its own error severity (commission); items the judge tags as fallback (later care) do not count; the .0 row
# applies only when no main approach is completely given (omission). The criterion's error is the worst of these.
SCORER_S2 = "S2"


def is_addon(r: dict[str, Any]) -> bool:
    """An add-on (D162); a legacy optional item is treated the same way (D135)."""
    return r.get("addOn") is True or r.get("optional") is True


S2_ONE_LOWER = {"mild": "none", "moderate": "mild", "severe": "moderate"}  # D168 partial rule
S2_PARTIAL_NONE = {"mild": "none", "moderate": "none", "severe": "none"}  # D183 (EXP122), amended by D185
# D185: a partial main approach addresses a mild or moderate need; a severe need keeps a moderate residual omission
# (one level down, as D168). Kept as a table so experiments can score the earlier rules by swapping one in.
S2_PARTIAL_RESIDUAL = {"mild": "none", "moderate": "none", "severe": "moderate"}


def _s2_decision(d: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    rows = {r["id"]: r for r in d["recommendations"]}
    recs = [x for x in out["recommended"] if x["actionable"] and x["role"] != "fallback" and x["rowId"] in rows]
    # D170: later care counts only against an item that states the same condition itself ("If ..."), because that
    # item's severity was rated for acting under the condition; it never addresses the criterion.
    conditional = [x for x in out["recommended"] if x["actionable"] and x["role"] == "fallback" and x["rowId"] in rows
                   and rows[x["rowId"]]["text"].lstrip().lower().startswith("if ")]
    events = [{"kind": "commission", "severity": rows[x["rowId"]]["harm"], "rowId": x["rowId"],
               "evidence": x["evidence"], "possible": False}
              for x in recs + conditional if rows[x["rowId"]]["harm"] != "none"]
    mains = [x for x in recs if not is_addon(rows[x["rowId"]]) and not is_omission(d, rows[x["rowId"]])]
    addressed = any(x["completeness"] == "complete" for x in mains)
    # A partial main approach leaves the residual omission in S2_PARTIAL_RESIDUAL (D185: moderate for a severe need,
    # none otherwise).
    partial = not addressed and any(x["completeness"] == "partial" for x in mains)
    omission = omission_item(d)
    need = omission["harm"] if omission else "none"
    state = out["applicability"]["state"]
    if state != "notApplicable" and need != "none":
        if not addressed:
            residual = S2_PARTIAL_RESIDUAL[need] if partial else need
            if residual != "none":
                events.append({"kind": "omission", "severity": residual, "rowId": omission["id"], "evidence": "",
                               "possible": state == "uncertain"})
        if out["contradiction"]["present"]:
            events.append({"kind": "contradiction", "severity": need, "rowId": omission["id"],
                           "evidence": out["contradiction"]["evidence"][0], "possible": state == "uncertain"})
    unmatched = sum(u["actionable"] for u in out["unmatched"])
    if unmatched:  # it may be an unlisted way of addressing the criterion
        for event in events:
            if event["kind"] != "commission":
                event["possible"] = True
    lower = v1._max(*(e["severity"] for e in events if not e["possible"]))
    # D179: unmatched statements are 94 to 96% harmless extras, so they no longer open the upper bound to severe;
    # they are counted instead and stay in the rubric-gap log.
    upper = v1._max(*(e["severity"] for e in events))
    return {"addressed": addressed, "needSeverity": need, "events": events,
            "omission": v1._max(*(e["severity"] for e in events if e["kind"] != "commission" and not e["possible"])),
            "commission": v1._max(*(e["severity"] for e in events if e["kind"] == "commission")),
            "error": lower if lower == upper else None, "errorBounds": [lower, upper], "unmatched": unmatched,
            "provisional": lower != upper or state == "uncertain"}


def score_case_s2(case: dict[str, Any], judgment: dict[str, Any], response: str,
                  case_context: str = "") -> dict[str, Any]:
    """Score a strictly bound J1 reading under S2. Legacy counseling criteria are refused (D160: rebuild them first)."""
    if errors := validation_errors(case):
        raise ValueError("; ".join(errors))
    if any(d["kind"] == "counseling" for d in case["decisions"]):
        raise ValueError("S2 scores the D160 format; rebuild the legacy counseling criterion first")
    if errors := judgment_errors(case, judgment, response, case_context):
        raise ValueError("; ".join(errors))
    results = {d["id"]: _s2_decision(d, judgment["decisions"][d["id"]]) for d in case["decisions"]}
    off = sum(i["actionable"] for i in judgment["offRubric"])
    low = v1._max(*(r["errorBounds"][0] for r in results.values()))
    high = v1._max(*(r["errorBounds"][1] for r in results.values()))  # D179: off-rubric statements are counted only
    return {"profile": PROFILE, "judge": JUDGE, "scorer": SCORER_S2, "caseId": case["caseId"],
            "rubricSha256": rubric_sha256(case), "decisions": results,
            "worstError": low if low == high else None, "worstErrorBounds": [low, high],
            "optimal": high == "none",
            "errorCounts": {kind: {level: sum(r[kind] == level for r in results.values()) for level in LEVELS}
                            for kind in ("omission", "commission")},
            "unmatched": sum(r["unmatched"] for r in results.values()) + off,
            "offRubric": copy.deepcopy(judgment["offRubric"]),
            "provisional": any(r["provisional"] for r in results.values())}


def score_case_three(cases: dict[str, dict[str, Any]], judgment: dict[str, Any], response: str,
                     case_context: str = "") -> dict[str, Any]:
    """Three-rubric grading (D122, D171): one reading scored under each of the three annotator rubrics. The official
    worst error is the median of the three (never an average), as the registered specialist rule takes the median of
    three ratings; every family's result and the spread (lowest and highest lower bound) are kept."""
    if len(cases) != 3:
        raise ValueError("three-rubric grading needs exactly three annotator rubrics")
    texts = []
    for case in cases.values():
        projected = project_for_judge(case)
        projected.pop("rubricSha256")
        texts.append(projected)
    if any(t != texts[0] for t in texts[1:]):
        raise ValueError("the three annotator rubrics must have the same text")
    families = {name: score_case_s2(case, {**judgment, "rubricSha256": rubric_sha256(case)}, response, case_context)
                for name, case in cases.items()}

    def median(values: list[str]) -> str:
        return sorted(values, key=LEVELS.index)[1]

    lows = [r["worstErrorBounds"][0] for r in families.values()]
    low, high = median(lows), median([r["worstErrorBounds"][1] for r in families.values()])
    return {"profile": PROFILE, "scorer": f"{SCORER_S2}-three", "caseId": next(iter(cases.values()))["caseId"],
            "families": {name: {"rubricSha256": r["rubricSha256"], "worstErrorBounds": r["worstErrorBounds"],
                                "provisional": r["provisional"]} for name, r in families.items()},
            "worstErrorBounds": [low, high], "worstError": low if low == high else None,
            "spread": [min(lows, key=LEVELS.index), max(lows, key=LEVELS.index)]}
