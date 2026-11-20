"""Upgrade an existing text rubric project to the current grading.

Old results are moved aside unchanged, the project's pin is switched, then each stage runs from its own receipts:
rate slots, judge every response, severe review, score. Every stage is paid, so callers show `upgrade_plan` and get
approval first. Rerunning resumes; the old results are moved only once.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from arisekit.common.hashing import sha256
from arisekit.common.jsonio import json_text, read_json
from arisekit.common.logs import log, now_iso

from pipeline.backends import Route
from pipeline.e2e import (
    judge,
    noharm_p2_loader,
    pipeline_v2,
    pipeline_v2_rate,
    pipeline_v2_review,
    pipeline_v2_score,
    pipeline_v2_slots,
    text_v2,
    text_v2_runtime,
)
from pipeline.e2e.pipeline_v2_review import review_prompt
from pipeline.e2e.project import Project, passed
from pipeline.e2e.text_v2_rating import SKILL, rating_variables
from pipeline.skillrun import skill_prompt

PREVIOUS = "previous"
MANIFEST = "MANIFEST.json"
MOVING = "MOVING.json"
Prices = dict[str, dict[str, float]]


def _max_output() -> int:
    return read_json(noharm_p2_loader.FREEZE_DIR / "config.json")["judge"]["max_output"]


def _old_pin(project: Project) -> str:
    return project.provenance().get(text_v2_runtime.PIN, text_v2.SOURCE_COMMIT)


def _upgrade_state(project: Project) -> dict[str, Any]:
    return project.provenance().get("pipeline_v2", {})


def _check_upgradable(project: Project, base_rubric: str) -> None:
    """Refuse a project that does not use text rubrics, or that is already on current grading with another base rubric."""
    if not project.items():
        raise ValueError("this project has no cases to upgrade")
    state = _upgrade_state(project)
    if _old_pin(project) == text_v2_runtime.PIPELINE_V2_COMMIT and state.get("base_rubric", base_rubric) != base_rubric:
        raise ValueError(f"this project is already upgraded with base rubric {state['base_rubric']}; "
                         f"--base-rubric {base_rubric} differs")
    for item in project.items():
        base = item["metadata"]["base_id"]
        if not text_v2.is_text_v2(text_v2.unwrap(_raw_rubric(project, base, base_rubric))):
            raise ValueError(f"{base}: rubric {base_rubric} is not a text rubric; only text projects can upgrade")


def _raw_rubric(project: Project, case_id: str, base_rubric: str) -> dict[str, Any]:
    path = project.artifact(case_id, base_rubric)
    if not path.is_file():
        raise ValueError(f"{case_id}: no rubric {base_rubric}; this project has no text rubric to upgrade")
    table = read_json(path)
    return table["record"] if base_rubric.startswith("reviewed-") else table


def _label(project: Project, case_id: str, base_rubric: str) -> str:
    try:
        return pipeline_v2_slots.shared_label(project, case_id)
    except ValueError:
        return base_rubric


def _usd(calls: int, input_tokens: int, route: Route, prices: Prices | None, max_output: int) -> float | None:
    price = (prices or {}).get(route["model"])
    if price is None:
        return None
    return round(input_tokens / 1e6 * price["input"] + calls * max_output / 1e6 * price["output"], 4)


def _stage(calls: int, input_tokens: int, routes: dict[str, Route], prices: Prices | None, max_output: int,
           per_route: dict[str, tuple[int, int]]) -> dict[str, Any]:
    dollars = [_usd(c, t, routes[name], prices, max_output) for name, (c, t) in per_route.items()]
    known = None not in dollars
    return {"calls": calls, "routes": {name: routes[name] for name in per_route},
            "inputTokens": input_tokens, "maxOutputTokens": calls * max_output,
            "usd": round(sum(dollars), 4) if known and dollars else (0.0 if not per_route else None),
            "priceUnknown": not known}


def upgrade_plan(project: Project, base_rubric: str, routes: dict[str, Route], prices: Prices | None) -> dict[str, Any]:
    """Calls, input tokens (prompt characters / 4), and an upper-bound cost per stage. Makes no calls, moves nothing.
    Output is bounded by the vendored per-call `max_output`; severe review is "up to" one call per response."""
    _check_upgradable(project, base_rubric)
    cap = _max_output()
    bases = {item["id"]: item["metadata"]["base_id"] for item in project.items()}

    def table_for(case_id: str) -> Any:
        return project.table(case_id, _label(project, case_id, base_rubric))

    rate_per: dict[str, tuple[int, int]] = {}
    for entry in pipeline_v2_rate.rating_plan(project, rubric=base_rubric):
        case_id = entry["caseId"]
        system, prompt = skill_prompt(SKILL, rating_variables(project.case(case_id), table_for(case_id)))
        calls, tokens = rate_per.get(entry["family"], (0, 0))
        rate_per[entry["family"]] = (calls + 1, tokens + (len(system) + len(prompt)) // 4)
    judge_tokens = review_tokens = responses = 0
    for name in project.model_names():
        for (item_id, _), record in project.responses(name)[0].items():
            case_id = bases[item_id]
            context, table = project.case(case_id)["presentation"], table_for(case_id)
            body = pipeline_v2.judge_prompt(table, context, record["response"])
            judge_tokens += (len(pipeline_v2.INSTRUCTIONS) + len(body)) // 4
            review_tokens += (len(pipeline_v2.INSTRUCTIONS) + len(review_prompt(table, context, record["response"], {}, []))) // 4
            responses += 1
    rate = _stage(sum(c for c, _ in rate_per.values()), sum(t for _, t in rate_per.values()), routes, prices, cap,
                  rate_per)
    return {"rate": rate,
            "judge": _stage(responses, judge_tokens, routes, prices, cap, {"judge": (responses, judge_tokens)}),
            "severe review": {**_stage(responses, review_tokens, routes, prices, cap,
                                       {"review": (responses, review_tokens)}), "upTo": responses},
            "alreadyUpgraded": "upgradedFrom" in _upgrade_state(project)}


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else [root]


def _move_previous(project: Project, old_pin: str) -> list[dict[str, str]]:
    """Move the old pipeline's results into results/previous/<pin>/ with their bytes and relative paths unchanged.
    A marker listing the planned moves is written first, so a rerun after a crash finishes the same moves."""
    target = project.results / PREVIOUS / old_pin[:12]
    marker = target / MOVING
    if marker.is_file():
        planned = read_json(marker)["planned"]
    elif target.exists():
        raise ValueError(f"{target} already exists but this project is not marked upgraded and no upgrade was in "
                         "progress there; another attempt or pin left it. The upgrade will not write into it. "
                         "Inspect it and its MANIFEST.json before rerunning")
    else:
        sources = [project.results / "judge", project.results / "ratings", project.results / "report.md",
                   *sorted(project.results.glob("*_scored.jsonl"))]
        planned = [str(s.relative_to(project.results)) for s in sources if s.exists()]
        target.mkdir(parents=True)
        marker.write_text(json_text({"oldPin": old_pin, "planned": planned, "startedAt": now_iso()}))
    for relative in planned:
        source, destination = project.results / relative, target / relative
        if not source.exists():
            continue
        if destination.exists():
            raise ValueError(f"both {source} and {destination} exist; the upgrade will not overwrite either. "
                             "Inspect them before rerunning")
        os.replace(source, destination)
    moved = [{"path": str(f.relative_to(target)), "sha256": sha256(f.read_bytes())}
             for relative in planned for f in _files(target / relative)]
    (target / MANIFEST).write_text(json_text({"oldPin": old_pin, "movedAt": now_iso(), "files": moved}))
    return moved


def _check_stage(name: str, problems: list[str]) -> None:
    """Stop the run when a stage cannot continue; rerunning resumes."""
    if problems:
        raise RuntimeError(f"upgrade stopped at {name}: {'; '.join(problems)}. Fix this and rerun to resume.")


def upgrade(caseset: Path, base_rubric: str, routes: dict[str, Route], yes: bool) -> dict[str, Any]:
    """The plan without `yes`; with it, the full upgrade, resuming from each stage's own receipts."""
    project = Project(caseset)
    if not yes:
        return {"plan": upgrade_plan(project, base_rubric, routes, None), "ran": False}
    _check_upgradable(project, base_rubric)
    state = _upgrade_state(project)
    old_pin = _old_pin(project)
    moved: list[dict[str, str]] = []
    if "upgradedFrom" not in state and old_pin != text_v2_runtime.PIPELINE_V2_COMMIT:
        moved = _move_previous(project, old_pin)
        # Written before any rating so a resumed upgrade never moves current-grading receipts.
        project.update_provenance(**{text_v2_runtime.PIN: text_v2_runtime.PIPELINE_V2_COMMIT},
                                  pipeline_v2={"tieRule": "less", **state, "base_rubric": base_rubric,
                                               "upgradedFrom": old_pin, "upgradedAt": now_iso()})
        (project.results / PREVIOUS / old_pin[:12] / MOVING).unlink()
        log(f"upgrade: moved {len(moved)} files to results/{PREVIOUS}/{old_pin[:12]}")
    elif "base_rubric" not in state:
        project.update_provenance(pipeline_v2={"tieRule": "less", **state, "base_rubric": base_rubric})

    raters = {family: routes[family] for family in pipeline_v2_slots.REPLACEMENT_ORDER}
    pipeline_v2_rate.rate_slots(caseset, raters, rubric=base_rubric)
    _check_stage("rating", [f"{e['caseId']} {e['family']} still lacks ratings"
                            for e in pipeline_v2_rate.rating_plan(project, rubric=base_rubric)])

    route = routes["judge"]
    judge.judge(caseset, base_rubric, route["backend"], route["model"], route.get("reasoning_effort"), resume=True)
    # A failed judgment is stored evidence that resume keeps, so it is reported rather than stopping the upgrade.
    judging_failures = [{"model": m, "id": r.get("id"), "trial": r.get("trial", 1), "errors": r.get("errors", [])}
                        for m in project.model_names() for r in project.judgments(m) if not passed(r)]

    reviews = pipeline_v2_review.severe_review(caseset, routes["review"], True)
    review_failures = [{"model": None, "id": r["id"], "trial": r["trial"], "errors": r["errors"]}
                       for r in reviews if r["status"] != "pass"]

    report, problems = pipeline_v2_score.score(caseset, allow_partial=True)
    return {"ran": True, "moved": len(moved), "reviews": len(reviews),
            "judgments": sum(len(project.passed_judgments(m)[0]) for m in project.model_names()),
            "judgingFailures": judging_failures, "reviewFailures": review_failures,
            "report": str(report) if report else None, "problems": problems}
