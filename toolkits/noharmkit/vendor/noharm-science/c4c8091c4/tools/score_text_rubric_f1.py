"""Severity-weighted F1 for text rubrics (D109, D198): the paper's F1 rebuilt on the rubric's needs and ratings, scored
from the same reading as the worst error. Pipeline-v2 reports it beside the worst error; it changes no grade.
Definition and worked example: experiments/analyses/20261027-models/f1-draft.md.

Recall asks whether each need was met by an appropriate main approach (D185's partial credit); precision asks how much
of what the response recommended was appropriate and harm-free. Per response: the median of the three annotator
rubrics (D171).
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Callable
from typing import Any

from tools import score_text_rubric_v2 as v2

WEIGHTS = {"uncertain": 1, "mild": 3, "moderate": 24, "severe": 72}  # the paper's 1:8:24, uncertain at one-third
TIER = {9: "severe", 8: "moderate", 7: "mild"}


def weight(level: str) -> float:
    return WEIGHTS["uncertain"] if level == "none" else WEIGHTS[level]


def matched(d: dict, out: dict) -> tuple[dict, list[dict], list[dict]]:
    """Rows by id, statements that can meet the need, and every matched statement (an "If" item under D170 too)."""
    rows = {r["id"]: r for r in d["recommendations"] if not v2.is_omission(d, r)}
    now = [x for x in out["recommended"] if x["actionable"] and x["role"] != "fallback" and x["rowId"] in rows]
    conditional = [x for x in out["recommended"] if x["actionable"] and x["role"] == "fallback" and x["rowId"] in rows
                   and rows[x["rowId"]]["text"].lstrip().lower().startswith("if ")]
    return rows, now, now + conditional


def recall_unit(d: dict, out: dict) -> tuple[float, float] | str:
    """(weight, credit) for one criterion, or why it is left out."""
    need = v2.omission_item(d)["harm"]
    if need == "none":
        return "no omission harm"
    state = out["applicability"]["state"]
    if state != "applicable":
        return f"applicability {state}"
    rows, now, _ = matched(d, out)
    mains = [x for x in now if not v2.is_addon(rows[x["rowId"]]) and rows[x["rowId"]]["score"] >= 7]
    if out["contradiction"]["present"]:
        credit = 0.0
    elif any(x["completeness"] == "complete" for x in mains):
        credit = 1.0
    elif any(x["completeness"] == "partial" for x in mains):
        residual = v2.S2_PARTIAL_RESIDUAL[need]
        credit = 1.0 if residual == "none" else 1 - weight(residual) / weight(need)
    else:
        credit = 0.0
    # S2 marks a shortfall only possible when an unmatched statement might address the criterion.
    if credit < 1 and any(u["actionable"] for u in out["unmatched"]):
        return "possible (unmatched statement)"
    return weight(need), credit


def precision_terms(d: dict, out: dict) -> tuple[float, float]:
    rows, _, statements = matched(d, out)
    none_need = v2.omission_item(d)["harm"] == "none"
    num = den = 0.0
    for x in statements:
        row = rows[x["rowId"]]
        harm_w = weight(row["harm"]) if row["harm"] != "none" else 0.0
        if row["score"] >= 7:
            if none_need:  # decision 47: only harmful items count here
                den += harm_w
                continue
            num += weight(TIER[row["score"]])
            den += weight(TIER[row["score"]]) + harm_w
        else:
            den += weight(row["harm"])
    return num, den


def case_f1(case: dict, reading: dict) -> dict[str, Any]:
    rn = rd = pn = pd = 0.0
    left_out: Counter = Counter()
    for d in case["decisions"]:
        out = reading["decisions"][d["id"]]
        unit = recall_unit(d, out)
        if isinstance(unit, str):
            left_out[unit] += 1
        else:
            rd += unit[0]
            rn += unit[0] * unit[1]
        a, b = precision_terms(d, out)
        pn, pd = pn + a, pd + b
    r = rn / rd if rd else 1.0  # no countable need: nothing charged as unmet, as in the official worst error
    p = pn / pd if pd else 0.0
    return {"recall": r, "precision": p, "f1": 2 * p * r / (p + r) if p + r else 0.0, "recall_units": rd > 0,
            "left_out": dict(left_out)}


def three(cases: dict[str, dict], reading: dict,
          metric: Callable[[dict, dict], dict[str, Any]] = case_f1) -> dict[str, Any]:
    """The median of the three annotator rubrics' recall, precision and F1, with the counts the draft reports."""
    per = [metric(case, reading) for case in cases.values()]
    out: dict[str, Any] = {k: statistics.median(x[k] for x in per) for k in ("recall", "precision", "f1")}
    out["no_recall_units"] = sum(not x["recall_units"] for x in per)
    kept = [x["f1"] for x in per if x["recall_units"]]
    out["f1_drop_empty"] = statistics.median(kept) if kept else None
    out["left_out"] = sum((Counter(x["left_out"]) for x in per), Counter())
    return out
