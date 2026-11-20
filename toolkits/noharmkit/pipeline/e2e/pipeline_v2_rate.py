"""Ask each rater family to rate the shared rubric, recording ratings only for items that lack a current one.

Every call is paid, so callers show `rating_plan` and get approval first. A failed rating is kept as a receipt and
never applied.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from arisekit.common.hashing import sha256
from arisekit.common.logs import log, now_iso

from pipeline.backends import Route, default_workers, resolve_route, run_paid
from pipeline.e2e import pipeline_v2_slots as slots
from pipeline.e2e.project import Project
from pipeline.e2e.text_v2_rating import (
    SKILL,
    rating_errors,
    rating_schema,
    rating_variables,
)
from pipeline.skillrun import run_skill, skill_prompt

DEFAULTS_FILE = Path(__file__).with_name("pipeline_v2_defaults.json")


def defaults() -> dict[str, Any]:
    return json.loads(DEFAULTS_FILE.read_text())


def parse_route(spec: str) -> tuple[str, Route]:
    """`family=backend/model[@effort]`; the model may itself contain "/" (OpenRouter), so only the first splits."""
    family, sep, rest = spec.partition("=")
    backend, slash, model = rest.partition("/")
    if not sep or not slash or not model:
        raise ValueError(f"route must look like family=backend/model[@effort], got {spec!r}")
    if family not in slots.REPLACEMENT_ORDER:
        raise ValueError(f"unknown rater family {family!r}; expected one of {slots.REPLACEMENT_ORDER}")
    model, _, effort = model.partition("@")
    parsed: Route = {"backend": backend, "model": model, **({"reasoning_effort": effort} if effort else {})}
    resolve_route(parsed["backend"], model, effort or None)
    return family, parsed


def _prepare_rubric(project: Project, case_ids: list[str], rubric: str | None, record: bool) -> None:
    slots.prepare_base_rubric(project, case_ids, rubric, record)


def _case_ids(project: Project, case_ids: list[str] | None) -> list[str]:
    known = [item["id"] for item in project.items()]
    return known if case_ids is None else [c for c in known if c in case_ids]


def _plan(project: Project, case_ids: list[str] | None, rubric: str | None) -> list[dict]:
    plan = []
    chosen = _case_ids(project, case_ids)
    for case_id in chosen:
        try:
            gaps = {s.family: s.missing for s in slots.slot_set(project, case_id).slots if s.family}
        except ValueError:
            if not rubric:
                raise
            every = list(slots.item_hashes(project.table(case_id, rubric)))
            gaps = {family: every for family in slots.REPLACEMENT_ORDER}
        plan.extend({"caseId": case_id, "family": f, "items": gaps[f]}
                    for f in slots.REPLACEMENT_ORDER if gaps.get(f))
    return plan


def rating_plan(project: Project, case_ids: list[str] | None = None, rubric: str | None = None) -> list[dict]:
    """One entry per case and family whose rater lacks a current rating, listing the missing item keys.
    `rubric` names the base for a project that has neither reviews nor a recorded base; nothing is written."""
    _prepare_rubric(project, _case_ids(project, case_ids), rubric, record=False)
    return _plan(project, case_ids, rubric)


def _rating_map(out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    ratings = {slots.USUAL_CARE: {k: out["usualCare"][k] for k in ("score", "harm")}}
    for did, decision in out["decisions"].items():
        for rid, row in decision["recommendations"].items():
            ratings[f"{did}/{rid}"] = {k: row[k] for k in ("score", "harm")}
    return ratings


def _next_path(folder: Path, case_id: str, family: str) -> Path:
    taken = [int(p.name.rsplit(".", 2)[1]) for p in folder.glob(f"{case_id}.{family}.*.json")] if folder.is_dir() else []
    return folder / f"{case_id}.{family}.{max(taken, default=0) + 1:03d}.json"


def rate_slots(caseset: Path, routes: dict[str, Route], case_ids: list[str] | None = None,
               rubric: str | None = None) -> list[Path]:
    """Run one whole-case call per planned (case, family) and write a receipt for each; returns the receipt paths."""
    project = Project(caseset)
    slots.require_current_grading(project, "rate-slots")
    _prepare_rubric(project, _case_ids(project, case_ids), rubric, record=True)
    plan = _plan(project, case_ids, rubric)
    if missing := sorted({e["family"] for e in plan} - set(routes)):
        raise ValueError(f"no route for rater families {missing}; pass --route family=backend/model[@effort]")
    jobs = []
    for entry in plan:
        case_id = entry["caseId"]
        found = slots.slot_set(project, case_id)
        table, case = found.shared_table, project.case(case_id)
        variables, schema = rating_variables(case, table), rating_schema(table)
        system, prompt = skill_prompt(SKILL, variables)
        jobs.append((entry, found.shared, table, schema, sha256(system + "\n\n" + prompt), variables))

    def call(job: tuple) -> Any:
        entry, _, table, schema, _, variables = job
        route = routes[entry["family"]]
        kwargs = {"reasoning_effort": route["reasoning_effort"]} if "reasoning_effort" in route else {}
        outcome = run_skill(SKILL, variables, route["backend"], route["model"],
                            check=lambda o: rating_errors(o, table), reject_duplicate_keys=True,
                            json_schema=schema, **kwargs)
        log(f"{SKILL} {entry['caseId']} {entry['family']} ({route['backend']}/{route['model']}) {outcome.status}")
        return outcome

    folder, paths = slots.model_ratings_dir(project), []

    def write(job: tuple, outcome: Any) -> None:
        entry, label, table, _, prompt_sha, _ = job
        ok = outcome.status == "pass"
        receipt = {"family": entry["family"], "caseId": entry["caseId"], "appliesTo": entry["items"],
                   "itemHashes": slots.item_hashes(table), "sharedRubric": label,
                   "ratings": _rating_map(outcome.output) if ok else {},
                   "route": routes[entry["family"]], "prompt_sha256": prompt_sha,
                   "status": "pass" if ok else "failed", "createdAt": now_iso(),
                   "errors": outcome.errors, "output": outcome.output, "raw": outcome.raw,
                   "provenance": outcome.provenance}
        path = _next_path(folder, entry["caseId"], entry["family"])
        project.write_new(path, receipt)
        paths.append(path)

    workers = min([len(jobs), *(default_workers(routes[job[0]["family"]]["backend"]) for job in jobs)])
    run_paid(jobs, call, write, workers)
    return paths

