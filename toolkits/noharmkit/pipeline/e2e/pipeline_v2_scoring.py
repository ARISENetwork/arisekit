"""Score one judge reading under every rater slot's rubric and take the median across slots (never an average).

Upstream supports exactly three slots; this generalises to three or more, with a tie rule for even counts.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from pipeline.e2e import noharm_p2_loader

TieRule = Literal["less", "more"]
MIN_SLOTS = 3


def _middle(count: int, tie: TieRule, lower_is_less: bool) -> int:
    if count % 2:
        return count // 2
    # Even counts have two middle ranks: pick the less severe or the more severe one.
    return count // 2 - 1 if lower_is_less == (tie == "less") else count // 2


def slot_median_level(levels: list[str], tie: TieRule) -> str:
    ordered = sorted(levels, key=noharm_p2_loader.load().v2.LEVELS.index)
    return ordered[_middle(len(ordered), tie, True)]


def slot_median_value(values: list[float], tie: TieRule) -> float:
    """Less severe means a higher value (recall, precision, F1)."""
    return sorted(values)[_middle(len(values), tie, False)]


def _need_slots(slots: dict[str, dict]) -> None:
    if len(slots) < MIN_SLOTS:
        raise ValueError(f"Slot grading needs at least three rater slots, got {len(slots)}")


def score_slots(slots: dict[str, dict], reading: dict, response: str, context: str, tie: TieRule) -> dict[str, Any]:
    _need_slots(slots)
    v2 = noharm_p2_loader.load().v2
    texts = []
    for case in slots.values():
        projected = v2.project_for_judge(case)
        projected.pop("rubricSha256")
        texts.append(projected)
    if any(t != texts[0] for t in texts[1:]):
        raise ValueError("The rater slots must have the same text")
    results = {name: v2.score_case_s2(case, {**reading, "rubricSha256": v2.rubric_sha256(case)}, response, context)
               for name, case in slots.items()}
    lows = [r["worstErrorBounds"][0] for r in results.values()]
    low = slot_median_level(lows, tie)
    high = slot_median_level([r["worstErrorBounds"][1] for r in results.values()], tie)
    return {"worstError": low, "worstErrorBounds": [low, high], "provisional": low != high,
            "spread": [min(lows, key=v2.LEVELS.index), max(lows, key=v2.LEVELS.index)],
            "slots": {name: {"rubricSha256": r["rubricSha256"], "worstErrorBounds": r["worstErrorBounds"],
                             "provisional": r["provisional"], "result": r} for name, r in results.items()},
            "slotCount": len(slots)}


def f1_slots(slots: dict[str, dict], reading: dict, tie: TieRule) -> dict[str, Any]:
    _need_slots(slots)
    f1 = noharm_p2_loader.load().f1
    per = [f1.case_f1(case, reading) for case in slots.values()]
    out: dict[str, Any] = {k: slot_median_value([x[k] for x in per], tie) for k in ("f1", "recall", "precision")}
    out["noRecallUnits"] = sum(not x["recall_units"] for x in per)
    out["recallLeftOut"] = dict(sum((Counter(x["left_out"]) for x in per), Counter()))
    return out


def recall_left_out_by(slots: dict[str, dict], reading: dict) -> dict[str, dict[str, int]]:
    """Per criterion, how many slots leave it out of recall and why; `recallLeftOut` is the sum over criteria."""
    _need_slots(slots)
    f1 = noharm_p2_loader.load().f1
    out: dict[str, Counter] = {}
    for case in slots.values():
        for d in case["decisions"]:
            unit = f1.recall_unit(d, reading["decisions"][d["id"]])
            if isinstance(unit, str):
                out.setdefault(d["id"], Counter())[unit] += 1
    return {cid: dict(reasons) for cid, reasons in out.items()}
