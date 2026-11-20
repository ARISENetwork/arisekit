"""NOHARMKit rubric pipeline CLI (MVP). Runbook: docs/runbook-e2e-mvp.md."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.backends import (BACKEND_HELP, BACKENDS, JUDGE_DEFAULT_EFFORT, JUDGE_DEFAULT_MODELS,
                               REASONING_EFFORT_BACKENDS, Route, route)
from pipeline.e2e import committee as committee_module
from pipeline.e2e import (generate, import_rubric, judge, pipeline_v2_rate, pipeline_v2_review, pipeline_v2_slots,
                          pipeline_v2_upgrade, project, rand, score, text_v2, text_v2_rating, text_v2_runtime, view)
from pipeline.e2e.constants import KIT_ROOT
from tools import supersede
from tools.cli import case_id, load_env, new_project, positive_int, rating_tag, require, rubric_label
from arisekit.common.files import snapshot
from arisekit.common.jsonio import read_json

COMMITTEE_FILE = committee_module.DEFAULT_COMMITTEE.relative_to(KIT_ROOT).as_posix()  # shown in --help
# --committee values that are not a path: no committee (generate only), or the bundled committee file.
NO_COMMITTEE, BUNDLED_COMMITTEE = "none", "default"


class RatingMethod(NamedTuple):
    panel_mode: str | None  # the RAND panel mode it runs ("quick" or "full"); None for the committee
    default_tag: str  # the results/ratings/<tag> folder when --tag is not given
    default_repeats: int  # independent repetitions when --repeats is not given


# --method values for `rate`, in the order --help lists them.
RATING_METHODS = {
    "committee": RatingMethod(None, "committee", 3),
    "rand-quick": RatingMethod("quick", "rand-quick", 1),
    "rand-full": RatingMethod("full", "rand-full", 1),
    "rand": RatingMethod("full", "committee", 1),  # legacy alias of rand-full; keeps its original folder
}


def committee_arg(value: str) -> list[dict[str, str]] | None:
    """--committee: 'none' skips the committee, 'default' is the bundled committee file, anything else is a path."""
    if value == NO_COMMITTEE:
        return None
    return committee_module.load_committee(
        committee_module.DEFAULT_COMMITTEE if value == BUNDLED_COMMITTEE else Path(value))


def _readable(errors: list[str]) -> list[str]:
    """Stored failure messages as printed: the pinned validator's upstream decision numbers removed."""
    return [text_v2_runtime.readable(error) for error in errors]


# Parser
def _add_item(p: argparse.ArgumentParser) -> None:
    """--item (alias --case): the required case ID, stored as args.case."""
    p.add_argument("--item", "--case", dest="case", metavar="ITEM", type=case_id, required=True,
                   help="item ID (--case is a compatibility alias)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="stage", required=True)

    p = sub.add_parser("create", help="create an empty benchmark project; refuses existing folders")
    p.add_argument("project", type=new_project)
    p.add_argument("--trials", type=positive_int, default=1, help="responses per item/model (default: 1)")

    p = sub.add_parser("snapshot", help="copy all project artifacts without changing their formats or identities")
    p.add_argument("project", type=Path)
    p.add_argument("destination", type=Path, help="new folder under an existing parent; refuses existing folders")

    p = sub.add_parser("import", help="copy a supplied input and reference into the project")
    p.add_argument("project", type=Path)
    _add_item(p)
    p.add_argument("--inputs-dir", "--cases-dir", dest="cases_dir", metavar="INPUTS_DIR", type=Path, required=True,
                   help="source folder with <ID>.json inputs and references (--cases-dir is a compatibility alias)")

    p = sub.add_parser("import-rubric", help="import one supplied text rubric without replacing evidence")
    p.add_argument("project", type=Path)
    _add_item(p)
    p.add_argument("--file", type=Path, required=True, help="raw rubric or source envelope JSON")
    p.add_argument("--version", type=rubric_label, help="new run<k> version (default: next unused run)")
    p.add_argument("--dry-run", action="store_true", help="validate and show the destination without writing")

    p = sub.add_parser("generate", help="generate rubrics from input + reference")
    p.add_argument("project", type=Path)
    _add_item(p)
    p.add_argument("--runs", type=positive_int, default=3)
    p.add_argument("--format", dest="rubric_format", choices=("text-v2", "answer-table"), default="text-v2",
                   help="new rubric format: text-v2 is the text rubric format (default); answer-table preserves the legacy generator")
    p.add_argument("--start-run", type=positive_int, default=1,
                   help="first run number; use a fresh slot when earlier evidence exists (default: 1)")
    p.add_argument("--backend", default="claude", choices=BACKENDS, help=BACKEND_HELP)
    p.add_argument("--model", help="model ID (default: opus for Claude; gpt-6-astra for Codex; "
                                   "openai/gpt-6-astra for OpenRouter)")
    p.add_argument("--reasoning-effort", help="reasoning effort for Codex, OpenRouter, or OpenAI")
    p.add_argument("--committee", default=NO_COMMITTEE,
                   help=f"harm committee: '{NO_COMMITTEE}' (default, MVP behavior), "
                        f"'{BUNDLED_COMMITTEE}' ({COMMITTEE_FILE}), or a committee JSON path")

    p = sub.add_parser("rate", help="advisory committee or RAND-style rubric rating; never modifies it")
    p.add_argument("project", type=Path)
    _add_item(p)
    p.add_argument("--rubric", "--table", dest="rubric", type=rubric_label, required=True,
                   help="rubric version: run<k> or reviewed-<reviewer> (--table is a compatibility alias)")
    p.add_argument("--repeats", type=positive_int, help="independent repetitions (default: committee 3, RAND modes 1)")
    p.add_argument("--method", choices=tuple(RATING_METHODS), default="committee",
                   help="rand-quick: one independent round; rand-full: two rounds with discussion; "
                        "rand: alias for rand-full")
    p.add_argument("--committee", default=BUNDLED_COMMITTEE,
                   help=f"'{BUNDLED_COMMITTEE}' ({COMMITTEE_FILE}) or a committee JSON path")
    p.add_argument("--tag", type=rating_tag,
                   help="output folder under results/ratings/ (default: selected method; legacy rand uses committee)")
    p.add_argument("--backend", choices=BACKENDS, help="use one rater via " + BACKEND_HELP)
    p.add_argument("--model", help="single-rater model ID; requires --backend")
    p.add_argument("--reasoning-effort",
                   help="single-rater reasoning effort for Codex, OpenRouter, or OpenAI; requires --backend")
    p.add_argument("--workers", type=positive_int, help="RAND panel concurrent member calls (default: 3)")
    p.add_argument("--evidence", type=Path, help="RAND panel supplied literature/evidence text file")
    p.add_argument("--moderator-backend", choices=BACKENDS, help="RAND moderator route (default: first panel member)")
    p.add_argument("--moderator-model", help="RAND moderator model; requires --moderator-backend")
    p.add_argument("--moderator-reasoning-effort", help="RAND moderator effort; requires --moderator-backend")

    p = sub.add_parser("rate-slots", help="rate the shared rubric per model family for items without a current "
                                          "rating; shows the plan and calls a provider only with --yes")
    p.add_argument("project", type=Path)
    p.add_argument("--case", "--item", dest="cases", metavar="ID", type=case_id, action="append",
                   help="limit to this case; repeatable (default: all cases)")
    p.add_argument("--route", action="append", default=[], metavar="FAMILY=BACKEND/MODEL[@EFFORT]",
                   help="override a family's default route (families: sol, gemini, opus)")
    p.add_argument("--rubric", type=rubric_label,
                   help="base rubric version, required when the project has no reviewed rubric or recorded base")
    p.add_argument("--yes", action="store_true", help="approve the provider spend and make the calls")

    p = sub.add_parser("severe-review", help="have a second model recheck judge readings whose slot-median worst "
                                             "error is severe; shows the plan and calls a provider only with --yes")
    p.add_argument("project", type=Path)
    p.add_argument("--route", metavar="BACKEND/MODEL[@EFFORT]",
                   help="override the review route (default: the bundled review route)")
    p.add_argument("--yes", action="store_true", help="approve the provider spend and make the calls")

    p = sub.add_parser("upgrade", help="move an existing project to the current grading: rate the slots, re-judge "
                                       "every response, run severe reviews, and score; shows the plan and calls a "
                                       "provider only with --yes")
    p.add_argument("project", type=Path)
    p.add_argument("--base-rubric", type=rubric_label, required=True, help="the project's shared rubric: run<k>")
    p.add_argument("--prices", type=Path, metavar="FILE",
                   help='JSON {"model": {"input": usd_per_mtok, "output": usd_per_mtok}} for the cost estimate')
    p.add_argument("--route", action="append", default=[], metavar="STAGE=BACKEND/MODEL[@EFFORT]",
                   help="override a route (stages: sol, gemini, opus, judge, review)")
    p.add_argument("--yes", action="store_true", help="approve the provider spend and run the upgrade")

    p = sub.add_parser("judge", help="map every response onto the rubric")
    p.add_argument("project", type=Path)
    p.add_argument("--rubric", type=rubric_label, default="run1", help="run<k> or reviewed-<reviewer>")
    p.add_argument("--backend", choices=BACKENDS,
                   help=f"{BACKEND_HELP} (default: direct OpenAI with GPT-6.1 Sol at high effort, the study's "
                        "judge, on projects using the current grading; openrouter otherwise)")
    p.add_argument("--model",
                   help="judge model ID (default: GPT-6.1 Sol for OpenRouter, OpenAI, and Codex; opus for Claude)")
    p.add_argument("--reasoning-effort",
                   help=f"Codex/OpenRouter/OpenAI reasoning effort (default: {JUDGE_DEFAULT_EFFORT})")
    p.add_argument("--workers", type=positive_int, help="concurrent calls (default: 24 for APIs, 8 for subscriptions)")
    p.add_argument("--resume", action="store_true",
                   help="OpenAI only: verify and retain saved receipts, run missing jobs")
    p.add_argument("--timeout", type=positive_int,
                   help="request timeout in seconds (default for API judging: 1800 on projects using the current "
                        "grading, 120 otherwise)")

    p = sub.add_parser("score", help="score judged responses and write results/report.md")
    p.add_argument("project", type=Path)
    p.add_argument("--rho", type=float, default=0.5)
    p.add_argument("--allow-partial", action="store_true")

    p = sub.add_parser("settings", help="set how scoring breaks ties between an even number of rater slots")
    p.add_argument("project", type=Path)
    p.add_argument("--tie-rule", choices=("less", "more"), required=True,
                   help="even slot counts: take the less (default) or more severe middle value")

    p = sub.add_parser("replace-outdated", help="after an edit to the case text, move out-of-date responses and "
                       "judgments (with their scores) to results/superseded/ so they can be redone")
    p.add_argument("project", type=Path)
    p.add_argument("--case", dest="cases", type=case_id, action="append", help="limit to this case (repeatable)")
    p.add_argument("--dry-run", action="store_true", help="print what would move and change nothing")

    p = sub.add_parser("view", help="open the local project viewer")
    p.add_argument("projects", type=Path, nargs="?",
                   help="project storage folder (default: projects, or an existing legacy casesets folder)")
    p.add_argument("--port", type=int, default=9000, help="viewer port (default: 9000)")
    return ap


# Shared preflight
def _resolve_route(args: argparse.Namespace, ap: argparse.ArgumentParser) -> Route:
    """generate and judge: the validated route, with the judge's default model and effort filled in. Direct OpenAI
    also requires OPENAI_API_KEY here, before any work."""
    effort, model = args.reasoning_effort, args.model
    if args.stage == "judge":
        if effort is None and args.backend in REASONING_EFFORT_BACKENDS:
            effort = JUDGE_DEFAULT_EFFORT
        if model is None:
            model = JUDGE_DEFAULT_MODELS.get(args.backend)
    try:
        resolved = route(args.backend, model, effort)
    except ValueError as error:
        ap.error(str(error))
    if resolved["backend"] == "openai":
        try:
            require("OPENAI_API_KEY")
        except RuntimeError as error:
            ap.error(str(error))
    return resolved


# Stages
def _create(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    try:
        project.Project.create(args.project, trials=args.trials)
    except (ValueError, FileExistsError) as error:
        ap.error(str(error))
    print(f"Created project {args.project}")


def _snapshot(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    try:
        path = snapshot(args.project, args.destination)
    except (OSError, ValueError) as error:
        ap.error(str(error))
    print(f"Verified project snapshot {path}. Stored identities are unchanged; this is a backup, not a new run.")


def _import(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    try:
        project.Project(args.project).import_case(args.case, args.cases_dir)
    except ValueError as error:
        ap.error(str(error))


def _import_rubric(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    try:
        receipt = import_rubric.import_rubric(project.Project(args.project), args.case, args.file, args.version,
                                              args.dry_run)
    except (OSError, ValueError) as error:
        ap.error(str(error))
    print(json.dumps(receipt, indent=2))


def _generate(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    resolved = _resolve_route(args, ap)
    try:
        statuses = generate.generate(args.project, args.case, args.runs, resolved["backend"], resolved["model"],
                            committee=committee_arg(args.committee),
                            reasoning_effort=resolved.get("reasoning_effort"),
                            rubric_format=args.rubric_format, start_run=args.start_run)
    except ValueError as error:
        ap.error(str(error))
    print(" ".join(f"run{i}={s}" for i, s in enumerate(statuses, args.start_run)))
    if "pass" not in statuses:
        sys.exit(1)


def _rate_routes(args: argparse.Namespace, ap: argparse.ArgumentParser,
                 method: RatingMethod) -> tuple[list[Route] | None, Route | None]:
    """The raters and the RAND moderator for `rate`, after checking that the flags fit the method.
    The checks run in this order, so the first error reported never changes."""
    is_panel = method.panel_mode is not None
    moderator_given = any(flag is not None for flag in (
        args.moderator_backend, args.moderator_model, args.moderator_reasoning_effort))
    panel_flags_given = moderator_given or args.workers is not None or args.evidence is not None

    # Which flags the method allows.
    if is_panel and (args.backend or args.committee in {BUNDLED_COMMITTEE, NO_COMMITTEE}):
        ap.error("RAND modes require an explicit --committee JSON path with at least 3 members")
    if method.panel_mode == "quick" and moderator_given:
        ap.error("moderator settings require --method rand-full")
    if not is_panel and panel_flags_given:
        ap.error("panel workers, evidence, and moderator flags require a RAND method")

    # The raters: one --backend route, or the --committee file.
    if args.backend:
        if args.committee != BUNDLED_COMMITTEE:
            ap.error("choose --backend for one rater or --committee for a committee, not both")
        committee = [route(args.backend, args.model, args.reasoning_effort)]
    else:
        if args.model or args.reasoning_effort:
            ap.error("--model and --reasoning-effort require --backend for a single rater")
        committee = committee_arg(args.committee)
    if is_panel and committee is not None and len(committee) < 3:
        ap.error("RAND-style testing requires at least 3 configured panel members")

    # The moderator, for a RAND panel only.
    if not is_panel:
        return committee, None
    if args.moderator_backend:
        return committee, route(args.moderator_backend, args.moderator_model, args.moderator_reasoning_effort)
    if args.moderator_model or args.moderator_reasoning_effort:
        ap.error("moderator model and reasoning effort require --moderator-backend")
    return committee, None


def _rate(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    method = RATING_METHODS[args.method]
    try:
        native_text_v2 = text_v2.is_text_v2(project.Project(args.project).table(args.case, args.rubric))
    except (OSError, ValueError) as error:
        ap.error(str(error))
    if native_text_v2 and method.panel_mode is not None:
        ap.error("RAND modes retain the legacy answer-table contract; use committee for text rubrics")
    tag = args.tag if args.tag is not None else method.default_tag
    repeats = args.repeats if args.repeats is not None else method.default_repeats
    try:
        committee, moderator = _rate_routes(args, ap, method)
    except ValueError as error:
        ap.error(str(error))
    if committee is None:
        sys.exit("rate needs a committee; 'none' applies only to generate")
    try:
        if method.panel_mode is not None:
            paths = rand.rate(args.project, args.case, args.rubric, repeats, committee, tag,
                              moderator=moderator, workers=args.workers if args.workers is not None else 3,
                              evidence_path=args.evidence, mode=method.panel_mode)
        else:
            rate = text_v2_rating.rate if native_text_v2 else committee_module.rate
            paths = rate(args.project, args.case, args.rubric, repeats, committee, tag)
    except (ValueError, OSError) as error:
        ap.error(str(error))
    for path in paths:
        print(path)
    failed = []
    for path in paths:
        record = read_json(path)
        if record.get("status") != "pass" or record.get("errors"):
            failed.append(path)
            print(f"rate: failed or unresolved rating at {path}: {_readable(record.get('errors', []))}", file=sys.stderr)
    if failed:
        sys.exit(1)


def _route_text(route: Route) -> str:
    return f"{route['backend']}/{route['model']}" + (f"@{route['reasoning_effort']}" if "reasoning_effort" in route else "")


def _rate_slots(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    try:
        routes = dict(pipeline_v2_rate.defaults()["raters"])
        routes.update(pipeline_v2_rate.parse_route(spec) for spec in args.route)
        proj = project.Project(args.project)
        pipeline_v2_slots.require_current_grading(proj, "rate-slots")
        plan = pipeline_v2_rate.rating_plan(proj, args.cases, args.rubric)
        for entry in plan:
            print(f"{entry['caseId']}  {entry['family']}  {len(entry['items'])} items  {_route_text(routes[entry['family']])}")
        print(f"{len(plan)} provider calls planned" + ("" if args.yes or not plan else "; rerun with --yes to make them"))
        if not args.yes or not plan:
            return
        paths = pipeline_v2_rate.rate_slots(args.project, routes, args.cases, args.rubric)
    except (ValueError, OSError) as error:
        ap.error(str(error))
    failed = 0
    for path in paths:
        print(path)
        if read_json(path)["status"] != "pass":
            failed += 1
            print(f"rate-slots: failed rating at {path}: {_readable(read_json(path)['errors'])}", file=sys.stderr)
    if failed:
        sys.exit(1)


def _severe_review(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    try:
        route = pipeline_v2_rate.defaults()["review"]
        if args.route:
            route = pipeline_v2_rate.parse_route(f"sol={args.route}")[1]
        plan = pipeline_v2_review.review_plan(project.Project(args.project))
        for entry in plan:
            print(f"{entry['model']}  {entry['id']}  trial {entry['trial']}  {len(entry['drivers'])} severe findings")
        print(f"{len(plan)} provider calls planned with {_route_text(route)}"
              + ("" if args.yes or not plan else "; rerun with --yes to make them"))
        if not args.yes or not plan:
            return
        receipts = pipeline_v2_review.severe_review(args.project, route, True)
    except (ValueError, OSError) as error:
        ap.error(str(error))
    failed = [r for r in receipts if r["status"] != "pass"]
    for r in receipts:
        print(f"{r['id']} trial {r['trial']}: {r['status']}")
    for r in failed:
        print(f"severe-review: failed review for {r['id']} trial {r['trial']}: {_readable(r['errors'])}", file=sys.stderr)
    if failed:
        sys.exit(1)


def _upgrade(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    try:
        defaults = pipeline_v2_rate.defaults()
        routes = {**defaults["raters"], "judge": defaults["judge"], "review": defaults["review"]}
        for spec in args.route:
            stage, _, rest = spec.partition("=")
            if stage not in routes:
                raise ValueError(f"unknown stage {stage!r}; expected sol, gemini, opus, judge, or review")
            routes[stage] = pipeline_v2_rate.parse_route(f"sol={rest}")[1]
        prices = read_json(args.prices) if args.prices else None
        proj = project.Project(args.project)
        plan = pipeline_v2_upgrade.upgrade_plan(proj, args.base_rubric, routes, prices)
        for name in ("rate", "judge", "severe review"):
            stage = plan[name]
            cost = "price unknown" if stage["usd"] is None else f"up to ${stage['usd']:.2f}"
            calls = f"up to {stage['upTo']}" if "upTo" in stage else stage["calls"]
            print(f"{name}: {calls} calls, about {stage['inputTokens']} input tokens, {cost}")
        print("previous results move to results/previous/ unchanged" if not plan["alreadyUpgraded"]
              else "already upgraded; resuming")
        if not args.yes:
            print("Rerun with --yes to approve the spend and run the upgrade.")
            return
        summary = pipeline_v2_upgrade.upgrade(args.project, args.base_rubric, routes, True)
    except (ValueError, OSError, RuntimeError) as error:
        ap.error(str(error))
    print(json.dumps(summary, indent=2))
    failures = [*summary["judgingFailures"], *summary["reviewFailures"]]
    for f in summary["judgingFailures"]:
        print(f"upgrade: failed judgment for {f['model']} {f['id']} trial {f['trial']}: {_readable(f['errors'])}",
              file=sys.stderr)
    for f in summary["reviewFailures"]:
        print(f"upgrade: failed severe review for {f['id']} trial {f['trial']}: {_readable(f['errors'])}", file=sys.stderr)
    for problem in summary["problems"]:
        print(f"upgrade: {problem}", file=sys.stderr)
    if failures or summary["problems"]:
        sys.exit(1)


def _judge(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    if args.backend is None:
        try:
            current = getattr(text_v2_runtime.for_project(project.Project(args.project)), "FREEZE", None)
        except (ValueError, OSError) as error:
            ap.error(str(error))
        study = pipeline_v2_rate.defaults()["judge"] if current == "pipeline-v2" else {"backend": "openrouter"}
        args.backend = study["backend"]
        if args.model is None:
            args.model = study.get("model")
        if args.reasoning_effort is None:
            args.reasoning_effort = study.get("reasoning_effort")
    resolved = _resolve_route(args, ap)
    if args.resume and resolved["backend"] != "openai":
        ap.error("verified resume currently requires direct OpenAI judging")
    try:
        paths = judge.judge(args.project, args.rubric, resolved["backend"], resolved["model"],
                            resolved.get("reasoning_effort"), args.workers,
                            **({"resume": True} if args.resume else {}),
                            **({"timeout": args.timeout} if args.timeout is not None else {}))
    except ValueError as error:
        ap.error(str(error))
    for path in paths:
        print(path)
    problems = judge.judge_problems(args.project, paths)
    for problem in problems:
        print(f"judge: {problem}", file=sys.stderr)
    if problems:
        sys.exit(1)


def _score(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    report, problems = score.score(args.project, args.rho, allow_partial=args.allow_partial)
    for p in problems:
        print(f"coverage: {p}", file=sys.stderr)
    if report is None:
        sys.exit(1)
    print(report)


def _settings(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    p = project.Project(args.project)
    try:
        pipeline_v2_slots.require_current_grading(p, "settings")
    except ValueError as error:
        ap.error(str(error))
    p.update_provenance(pipeline_v2={**p.provenance().get("pipeline_v2", {}), "tieRule": args.tie_rule})
    print(f"tie rule: {args.tie_rule}")


def _replace_outdated(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    manifest = supersede.replace_outdated(project.Project(args.project), args.cases, args.dry_run)
    if not manifest["files"]:
        print("Nothing an edit to the case text put out of date. Nothing to move.")
        return
    for entry in manifest["files"]:
        print(f"{entry['file']}: {len(entry['rows'])} row(s) -> {entry['archived_as']}")
    if "report" in manifest:
        print(f"results/report.md -> {manifest['report']}")
    print("Dry run: nothing moved." if args.dry_run else "Moved. Collect, judge, and score these cases again as needed.")


def _view(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    sys.exit(view.serve(args.projects if args.projects is not None else project.projects_root(), args.port))


STAGES: dict[str, Callable[[argparse.Namespace, argparse.ArgumentParser], None]] = {
    "create": _create, "snapshot": _snapshot, "import": _import, "import-rubric": _import_rubric,
    "generate": _generate, "rate": _rate, "rate-slots": _rate_slots,
    "severe-review": _severe_review, "upgrade": _upgrade,
    "judge": _judge, "score": _score, "settings": _settings, "replace-outdated": _replace_outdated, "view": _view,
}


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    load_env()
    STAGES[args.stage](args, ap)


if __name__ == "__main__":
    main()
