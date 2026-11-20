"""Derive a case's current rater slots from reviewed rubrics and model rating receipts on disk. Makes no model calls.

A slot holds one rater's scores and harms over the shared rubric text. Ratings are tracked per item and count only
while the item's text hash still equals the shared rubric's.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from arisekit.common.logs import now_iso

from pipeline.e2e import noharm_p2_loader
from pipeline.e2e.case_edits import rubric_outdated
from pipeline.e2e.project import REVIEWED_LABEL, RUN_LABEL, Project
from pipeline.e2e.text_v2_rating import USUAL_CARE_DEFINITION

REPLACEMENT_ORDER = ("sol", "gemini", "opus")
USUAL_CARE = "usualCare"


def _sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def item_hashes(table: dict) -> dict[str, str]:
    """Item key to the hash of the text a rater sees for it; scores and harms are not part of the hash."""
    hashes = {USUAL_CARE: _sha256(USUAL_CARE_DEFINITION)}
    for decision in table["decisions"]:
        for row in decision["recommendations"]:
            hashes[f"{decision['id']}/{row['id']}"] = _sha256(
                {"kind": decision["kind"], "question": decision["question"], "text": row["text"]})
    return hashes


def text_sha256(table: dict) -> str:
    projected = noharm_p2_loader.load().v2.project_for_judge(table)
    projected.pop("rubricSha256")
    return _sha256(projected)


def _ratings_of(table: dict) -> dict[str, dict[str, Any]]:
    ratings = {USUAL_CARE: {"score": table["usualCare"]["score"], "harm": table["usualCare"]["harm"]}}
    for decision in table["decisions"]:
        for row in decision["recommendations"]:
            ratings[f"{decision['id']}/{row['id']}"] = {"score": row["score"], "harm": row["harm"]}
    return ratings


def _apply(table: dict, key: str, rating: dict[str, Any]) -> None:
    if key == USUAL_CARE:
        target = table["usualCare"]
    else:
        decision_id, row_id = key.split("/", 1)
        target = next(r for d in table["decisions"] if d["id"] == decision_id
                      for r in d["recommendations"] if r["id"] == row_id)
    target["score"], target["harm"] = rating["score"], rating["harm"]


@dataclass
class Clinician:
    reviewer: str
    label: str
    first_saved_at: str
    saved_at: str
    table: dict


def _clinicians(project: Project, case_id: str) -> list[Clinician]:
    """Reviewers with a passing saved review of the current case text, ordered by their first save (review log,
    else the file's savedAt). A review of a rubric made before the case text was edited no longer counts."""
    log = project.root / "reviews.jsonl"
    first: dict[str, str] = {}
    if log.exists():
        for line in log.read_text().splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("step") == "rubrics" and record.get("caseId") == case_id and "reviewedAt" in record:
                item = record.get("item", "")
                first[item] = min(first.get(item, record["reviewedAt"]), record["reviewedAt"])
    found = []
    folder = project.root / "answer-tables"
    for path in sorted(folder.glob(f"{case_id}.reviewed-*.json")):
        label = path.name[len(case_id) + 1:-len(".json")]
        match = REVIEWED_LABEL.fullmatch(label)
        if not match or not project.artifact(case_id, label, "status.json").exists():
            continue
        if project.status(case_id, label)["status"] != "pass" or rubric_outdated(project, case_id, label):
            continue
        saved_at = json.loads(path.read_text())["savedAt"]
        found.append(Clinician(match.group(1), label, min(first.get(label, saved_at), saved_at), saved_at,
                               copy.deepcopy(dict(project.table(case_id, label)))))
    return sorted(found, key=lambda c: (c.first_saved_at, c.reviewer))


def require_current_grading(project: Project, command: str) -> None:
    """Refuse slot rating, severe review and tie settings on a project still on an earlier grading pipeline."""
    from pipeline.e2e import text_v2_runtime
    if getattr(text_v2_runtime.for_project(project), "FREEZE", None) != "pipeline-v2":
        raise ValueError(f"{command} needs a project on the current grading; this project uses an earlier one. "
                         "Upgrade it first with tools/noharm.py upgrade")


def _recorded_base(project: Project, case_id: str) -> str | None:
    state = project.provenance().get("pipeline_v2", {})
    return state.get("case_base_rubrics", {}).get(case_id) or state.get("base_rubric")


def _current_run(project: Project, case_id: str) -> str | None:
    """The newest passing generated rubric made from the current case text."""
    runs = []
    for path in (project.root / "answer-tables").glob(f"{case_id}.run*.status.json"):
        label = path.name[len(case_id) + 1:-len(".status.json")]
        if (match := RUN_LABEL.fullmatch(label)) and project.status(case_id, label)["status"] == "pass" \
                and not rubric_outdated(project, case_id, label):
            runs.append((int(match.group(1)), label))
    return max(runs)[1] if runs else None


def shared_label(project: Project, case_id: str) -> str:
    """The latest current clinician review, else the case's recorded base; when an edit to the case text put that
    base out of date, the newest passing rubric generated since takes its place."""
    reviews = _clinicians(project, case_id)
    if reviews:
        return max(reviews, key=lambda c: (c.saved_at, c.reviewer)).label
    base = _recorded_base(project, case_id)
    if base and not rubric_outdated(project, case_id, base):
        return base
    if base:
        if current := _current_run(project, case_id):
            return current
        raise ValueError(f"{case_id}: rubric {base} was made before the case text was edited. "
                         "Generate a rubric for the current text first.")
    raise ValueError(f"{case_id} has no shared rubric: no passing reviewed rubric and no base rubric set. "
                     "Run judging or rating with --rubric LABEL first to choose one.")


def prepare_base_rubric(project: Project, case_ids: list[str], rubric: str | None, record: bool) -> None:
    """Check `rubric` against the recorded base, and when `record` is set and no base exists, record it.
    A label that is already every case's current shared rubric is accepted and changes nothing."""
    base = project.provenance().get("pipeline_v2", {}).get("base_rubric")
    if base and rubric and rubric != base and any(shared_label(project, c) != rubric for c in case_ids):
        raise ValueError(f"this project's base rubric is {base}; --rubric {rubric} differs. Edit and review "
                         "the rubric instead of choosing a different base.")
    if base and record:
        _record_switches(project, case_ids)
    if base or not rubric:
        return
    unresolved = [c for c in case_ids if not _clinicians(project, c)]
    for case_id in unresolved:
        if not project.artifact(case_id, rubric, "status.json").exists() or project.status(case_id, rubric)["status"] != "pass":
            raise ValueError(f"{case_id} has no passing rubric {rubric}")
    if unresolved and record:
        project.update_provenance(pipeline_v2={**project.provenance().get("pipeline_v2", {}), "base_rubric": rubric})


def _record_switches(project: Project, case_ids: list[str]) -> None:
    """Record each case whose base moved to a newer rubric because its case text was edited."""
    switches = []
    for case_id in case_ids:
        recorded, label = _recorded_base(project, case_id), shared_label(project, case_id)
        if recorded and label != recorded and not _clinicians(project, case_id):
            switches.append({"caseId": case_id, "from": recorded, "to": label, "reason": "case text edited"})
    if not switches:
        return
    state = project.provenance().get("pipeline_v2", {})
    at = now_iso()
    project.update_provenance(pipeline_v2={
        **state,
        "case_base_rubrics": {**state.get("case_base_rubrics", {}), **{s["caseId"]: s["to"] for s in switches}},
        "base_switches": [*state.get("base_switches", []), *({**s, "at": at} for s in switches)],
    })


def model_ratings_dir(project: Project) -> Path:
    return project.results / "ratings" / "pipeline-v2"


def _receipts(project: Project, case_id: str) -> list[dict]:
    """Passing receipts for the case, oldest first. Order is `createdAt` when present, then file name."""
    folder = model_ratings_dir(project)
    if not folder.is_dir():
        return []
    loaded = [(json.loads(p.read_text()), p.name) for p in sorted(folder.glob("*.json"))]
    passing = [(r, n) for r, n in loaded if r.get("status") == "pass" and r.get("caseId") == case_id]
    return [r for r, _ in sorted(passing, key=lambda x: (x[0].get("createdAt", ""), x[1]))]


@dataclass
class Slot:
    id: str
    kind: Literal["model", "clinician"]
    family: str | None
    reviewer: str | None
    table: dict
    rated_by: dict[str, int]
    missing: list[str]
    routes: list[Any] = field(default_factory=list)
    prompt_sha256s: list[str] = field(default_factory=list)


@dataclass
class SlotSet:
    case_id: str
    shared: str
    shared_table: dict
    slots: list[Slot]

    @property
    def complete(self) -> bool:
        return len(self.slots) >= 3 and all(not s.missing for s in self.slots)

    def tables(self, allow_incomplete: bool = False) -> dict[str, dict]:
        """Full rubric per slot. Items in `missing` carry the shared table's values, which are not that slot's
        ratings, so an incomplete set raises unless the caller will mark its scores incomplete."""
        if not self.complete and not allow_incomplete:
            gaps = {s.id: s.missing for s in self.slots if s.missing}
            raise ValueError(f"{self.case_id} rater slots are incomplete (slots: {len(self.slots)}, "
                             f"missing items by slot: {gaps})")
        return {s.id: s.table for s in self.slots}

    def summary(self) -> dict[str, Any]:
        return {"slots": [{"id": s.id, "kind": s.kind, "family": s.family, "reviewer": s.reviewer,
                           "routes": s.routes, "prompt_sha256s": s.prompt_sha256s} for s in self.slots],
                "ratedBy": {k: sum(s.rated_by[k] for s in self.slots) for k in ("clinician", "model")},
                "complete": self.complete, "slotCount": len(self.slots)}


def _build(slot_id: str, kind: Literal["model", "clinician"], family: str | None, reviewer: str | None,
           shared_table: dict, hashes: dict[str, str], own: dict[str, dict] | None,
           receipts: list[dict]) -> Slot:
    table = copy.deepcopy(shared_table)
    rated_by = {"clinician": 0, "model": 0}
    missing: list[str] = []
    used: list[dict] = []
    for key, want in hashes.items():
        if own is not None and key in own:
            _apply(table, key, own[key])
            rated_by["clinician"] += 1
            continue
        hit = None
        if family is not None:
            for receipt in reversed(receipts):
                if (receipt["family"] == family and key in receipt["appliesTo"] and key in receipt["ratings"]
                        and receipt["itemHashes"].get(key) == want):
                    hit = receipt
                    break
        if hit is None:
            missing.append(key)
            continue
        _apply(table, key, hit["ratings"][key])
        rated_by["model"] += 1
        used.append(hit)
    routes = list({json.dumps(r["route"], sort_keys=True): r["route"] for r in used}.values())
    return Slot(slot_id, kind, family, reviewer, table, rated_by, missing, routes,
                sorted({r["prompt_sha256"] for r in used}))


def slot_set(project: Project, case_id: str) -> SlotSet:
    label = shared_label(project, case_id)
    shared_table = copy.deepcopy(dict(project.table(case_id, label)))
    hashes = item_hashes(shared_table)
    clinicians = _clinicians(project, case_id)
    receipts = _receipts(project, case_id)
    slots = []
    for k, clinician in enumerate(clinicians):
        theirs = item_hashes(clinician.table)
        own = {key: rating for key, rating in _ratings_of(clinician.table).items() if theirs[key] == hashes.get(key)}
        family = REPLACEMENT_ORDER[k] if k < len(REPLACEMENT_ORDER) else None
        slots.append(_build(f"clinician:{clinician.reviewer}", "clinician", family, clinician.reviewer,
                            shared_table, hashes, own, receipts))
    for family in REPLACEMENT_ORDER[min(len(clinicians), len(REPLACEMENT_ORDER)):]:
        slots.append(_build(f"model:{family}", "model", family, None, shared_table, hashes, None, receipts))
    return SlotSet(case_id, label, shared_table, slots)
