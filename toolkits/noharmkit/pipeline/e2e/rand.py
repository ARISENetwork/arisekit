"""Optional quick or full RAND/UCLA-style LLM panel; advisory, never a rubric mutation."""
from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, TypedDict

from pipeline.e2e.committee import (
    harm_scale_text, is_disagreement, median_tier, rated_decisions, rating_schema,
)
from pipeline.backends import Route
from pipeline.e2e.project import Project
from pipeline.e2e.records import Case
from pipeline.e2e.rubric import NEED_SEVERITIES, OPTION_FIELDS, Rubric, Table
from pipeline.skillrun import call_json, skill_file
from arisekit.common.hashing import json_sha256, sha256
from arisekit.common.logs import now_iso
from arisekit.common.schemas import strict_object

METHOD = "rand-ucla-llm-v1"
QUICK_METHOD = "rand-ucla-llm-quick-v1"
MANUAL = "https://www.rand.org/pubs/monograph_reports/MR1269.html"
PROMPTS = "rand-panel"  # one prompt per panel phase, not the standard skill layout
HARM_RULE = "categorical_lower_median_toolkit_extension"
LIMITATIONS = ["LLM adaptation, not a clinician RAND/UCLA panel",
               "Small panels and repeated model routes do not establish independent clinical consensus",
               "Categorical harm is a NOHARM extension, not RAND necessity"]
QUICK_LIMITATION = "Single-round screening; no discussion, moderator, or second ratings"
# The rules each record states it applied; `rating_rounds` (1 quick, 2 full) leads them.
RULES = {"appropriateness": "median_and_ipras", "percentiles": "linear_type7",
         "fractional_boundary_medians": "3.5_and_6.5_uncertain", "required_members": "all_in_every_phase",
         "harm": HARM_RULE, "source": MANUAL}
COMMENT_SCHEMA = strict_object({"comment": {"type": "string", "minLength": 1}})


class Appropriateness(TypedDict):
    """One option's RAND rating: 1-9 votes, the median, IPRAS disagreement, and the classification."""
    votes: list[int]
    median: float
    distribution: dict[str, int]
    p30: float
    p70: float
    ipr: float
    ipras: float
    disagreement: bool
    classification: str


class HarmSummary(TypedDict):
    """One harm unit's votes across the panel, aggregated by the lower median vote."""
    votes: list[str]
    medianVote: str
    disagreement: bool
    rule: str


class PanelSummary(TypedDict):
    """One rating round: appropriateness per Decision and option, and harm for usual care and each Decision."""
    options: dict[str, dict[str, Appropriateness]]
    usualCare: HarmSummary
    decisions: dict[str, HarmSummary]


def appropriateness(votes: list[int]) -> Appropriateness:
    median = statistics.median(votes)
    deciles = statistics.quantiles(votes, n=10, method="inclusive")  # linear interpolation (type 7)
    p30, p70 = deciles[2], deciles[6]
    ipr = p70 - p30
    ipras = 2.35 + 1.5 * abs((p30 + p70) / 2 - 5)
    disagreement = ipr > ipras
    category = "uncertain" if disagreement or 3 < median < 7 else "appropriate" if median >= 7 else "inappropriate"
    return {"votes": votes, "median": median, "distribution": {str(v): votes.count(v) for v in range(1, 10)},
            "p30": p30, "p70": p70, "ipr": ipr, "ipras": ipras,
            "disagreement": disagreement, "classification": category}


def panel_schema(table: Table, row_map: dict[str, dict[str, str]]) -> dict[str, Any]:
    schema = rating_schema(table)
    schema["properties"]["options"] = strict_object({did: strict_object({rid: strict_object({
        "score": {"type": "integer", "minimum": 1, "maximum": 9},
        "reason": {"type": "string", "minLength": 1}}) for rid in rows}) for did, rows in row_map.items()})
    schema["required"].append("options")
    return schema


def _call(route: Route, phase: str, payload: dict[str, Any], schema: dict[str, Any],
          prompts: dict[str, str]) -> dict[str, Any]:
    system = prompts["system.md"]
    prompt = prompts[f"{phase}.md"] + "\n\nInput JSON:\n" + json.dumps(payload, ensure_ascii=False, indent=1)
    provenance: dict[str, Any] = {"method": payload.get("panel_method", METHOD), **route,
        "request_sha256": json_sha256({"system": system, "prompt": prompt, "schema": schema, "route": route}),
        "schema_sha256": json_sha256(schema)}
    started = time.monotonic()
    kwargs = {"reasoning_effort": route["reasoning_effort"]} if "reasoning_effort" in route else {}
    outcome = call_json(route["backend"], route["model"], system, prompt, schema,
                        check=lambda output: _panel_errors(output, phase), reject_duplicate_keys=True,
                        provenance=provenance, json_schema=schema, **kwargs)
    return {**asdict(outcome), "elapsed_s": time.monotonic() - started}


def _panel_errors(output: dict[str, Any], phase: str) -> list[str]:
    def blank_reasons(value: Any) -> bool:
        if isinstance(value, dict):
            return any((key in {"reason", "comment"} and not item.strip()) or blank_reasons(item)
                       for key, item in value.items())
        return False

    if blank_reasons(output):
        return ["reasons and comments must contain non-whitespace text"]
    if phase != "rating":
        return []
    usual = NEED_SEVERITIES.index(output["usualCare"]["harm"])
    return ([f"{did}: omission harm exceeds usual-care harm" for did, value in output["decisions"].items()
             if NEED_SEVERITIES.index(value["harm"]) > usual]
            + [f"{did}/{rid}: appropriateness must be an integer 1-9"
               for did, options in output["options"].items() for rid, value in options.items()
               if type(value["score"]) is not int])


def _summary(raters: list[dict[str, Any]], row_map: dict[str, dict[str, str]]) -> PanelSummary:
    outputs = [r["output"] for r in raters]
    options = {did: {rid: appropriateness([out["options"][did][rid]["score"] for out in outputs])
                    for rid in rows} for did, rows in row_map.items()}

    def harm(votes: list[str]) -> HarmSummary:
        return {"votes": votes, "medianVote": median_tier(votes), "disagreement": is_disagreement(votes),
                "rule": HARM_RULE}

    return {"options": options, "usualCare": harm([o["usualCare"]["harm"] for o in outputs]),
            "decisions": {did: harm([o["decisions"][did]["harm"] for o in outputs])
                          for did in outputs[0]["decisions"]}}


class _Stopped(Exception):
    """A panel phase failed; the record already names the failed members."""


@dataclass
class Panel:
    """One panel run: shared inputs, the record it fills, and a method per phase. Receipts are saved as they land."""
    committee: list[Route]
    moderator: Route | None
    workers: int
    prompts: dict[str, str]
    base: dict[str, Any]
    schema: dict[str, Any]
    row_map: dict[str, dict[str, str]]
    record: dict[str, Any]
    save: Callable[[str, dict[str, Any]], None]
    began: float

    def members(self, name: str, phase: str, payloads: list[dict[str, Any]],
                reply_schema: dict[str, Any]) -> list[dict[str, Any]]:
        """Every member answers one phase in parallel; the receipts are recorded under `name`."""
        def one(index: int) -> dict[str, Any]:
            receipt = {"member": index + 1,
                       **_call(self.committee[index], phase, payloads[index], reply_schema, self.prompts)}
            self.save(f"{name}-member{index + 1}", receipt)
            return receipt
        with ThreadPoolExecutor(max_workers=min(self.workers, len(self.committee))) as pool:
            receipts = self.record[name] = list(pool.map(one, range(len(self.committee))))
        self.check(name, receipts)
        return receipts

    def moderate(self, feedback: dict[str, Any], discussion: list[Any]) -> Any:
        receipt = self.record["moderation"] = _call(
            self.moderator, "moderator", {**self.base, "feedback": feedback, "discussion": discussion},
            COMMENT_SCHEMA, self.prompts)
        self.save("moderation", receipt)
        self.check("moderation", [receipt])
        return receipt["output"]

    def check(self, name: str, receipts: list[dict[str, Any]]) -> None:
        """Any failed member stops the panel; the record keeps every phase that ran."""
        bad = [r.get("member", "moderator") for r in receipts if r["status"] != "pass"]
        if bad:
            self.record["errors"].append(f"{name}: failed members {bad}; later phases were not run")
            self.record["elapsed_s"] = time.monotonic() - self.began
            raise _Stopped

    def finish(self, summary: PanelSummary, final_round: int) -> dict[str, Any]:
        self.record["aggregate"] = {**summary, "options": {
            did: {self.row_map[did][rid]: value for rid, value in values.items()}
            for did, values in summary["options"].items()}}
        self.record["final_rating_round"] = final_round
        self.record["status"] = "pass"
        self.record["elapsed_s"] = time.monotonic() - self.began
        return self.record

    def run(self, quick: bool) -> dict[str, Any]:
        """Round 1; for full mode also discussion, moderation, and round 2. A failed phase stops the panel."""
        base = self.base
        try:
            round1 = self.members("round1", "rating", [{**base, "round": 1} for _ in self.committee], self.schema)
            summary = self.record["round1_summary"] = _summary(round1, self.row_map)
            if quick:
                return self.finish(summary, 1)
            own = [r["output"] for r in round1]
            feedback = {"distribution": summary, "submissions": own}
            discussion = [r["output"] for r in self.members(
                "discussion", "discussion", [{**base, "feedback": feedback, "own_round1": o} for o in own],
                COMMENT_SCHEMA)]
            moderator = self.moderate(feedback, discussion)
            round2 = self.members("round2", "rating", [
                {**base, "round": 2, "own_round1": o, "feedback": feedback, "discussion": discussion,
                 "moderator": moderator} for o in own], self.schema)
            return self.finish(_summary(round2, self.row_map), 2)
        except _Stopped:
            return self.record


def run_panel(case: Case, table: Table, committee: list[Route],
              *, moderator: Route | None = None, workers: int = 3, evidence: str = "",
              save: Callable[[str, dict[str, Any]], None], mode: str = "full") -> dict[str, Any]:
    quick = mode == "quick"
    if not quick and moderator is None:
        moderator = committee[0]
    names = ["system.md", "rating.md"] + ([] if quick else ["discussion.md", "moderator.md"])
    prompts = {name: skill_file(PROMPTS, name).read_text() for name in names}
    method = QUICK_METHOD if quick else METHOD
    rubric = Rubric(table)
    projected, row_map = rubric.neutral_view(rubric.decisions, OPTION_FIELDS)
    schema = panel_schema(table, row_map)
    base = {"panel_method": method, "panel_mode": mode,
            "case": case["presentation"], "expert": case["recommendations"], "evidence": evidence,
            "decisions": projected, "omissionHarmDecisions": [d["id"] for d in rated_decisions(table)],
            "harmScale": harm_scale_text()}
    began = time.monotonic()
    record: dict[str, Any] = {"method": method, "mode": mode, "authority": "llm-provisional", "applied": False,
        "status": "failed", "errors": [], "committee": committee, "moderator": moderator,
        "panel_size": len(committee), "distinct_routes": len({json_sha256(r) for r in committee}),
        "workers": workers, "planned_calls": len(committee) if quick else 3 * len(committee) + 1,
        "started_at": now_iso(), "table_sha256": json_sha256(table),
        "case_sha256": json_sha256(case), "evidence_sha256": sha256(evidence),
        "evidence_supplied": bool(evidence.strip()), "prompt_sha256": json_sha256(prompts),
        "code_sha256": sha256(Path(__file__).read_bytes()),
        "inputs": base, "prompt_sources": prompts, "row_map": row_map,
        "limitations": [*LIMITATIONS, *([QUICK_LIMITATION] if quick else [])],
        "rules": {"rating_rounds": 1 if quick else 2, **RULES},
        "round1": [], "discussion": [], "moderation": None, "round2": [], "aggregate": None}
    panel = Panel(committee, moderator, workers, prompts, base, schema, row_map, record, save, began)
    panel.save("manifest", {**record, "reply_schema": schema, "comment_schema": COMMENT_SCHEMA})
    return panel.run(quick)


def render_report(record: dict[str, Any], table: Table) -> str:
    mode = record.get("mode", "full")
    quick = mode == "quick"
    lines = [f"# RAND {mode} LLM panel", "",
             f"Execution: {record['status']}. Authority: LLM-provisional. Advisory only; not applied.", "",
             f"Panel members: {record['panel_size']}; distinct routes: {record['distinct_routes']}; "
             f"worker limit: {record['workers']}; planned calls: {record['planned_calls']}; "
             f"elapsed: {record['elapsed_s']:.2f} s.", "",
             "Routes use their declared subscription or API backends, recorded in the JSON receipt. "
             "Repeated routes are separate calls, not independent clinical experts. No clinician validation is implied.", "",
             f"Supplied evidence: {'yes' if record['evidence_supplied'] else 'none'}. "
             "Appropriateness medians and IPRAS disagreement are separate from NOHARM categorical harm.", ""]
    for index, member in enumerate(record["committee"], 1):
        transport = "API" if member["backend"] == "openrouter" else "subscription"
        lines.append(f"- Member {index}: {member['backend']}/{member['model']} ({transport}); "
                     f"reasoning effort: {member.get('reasoning_effort', 'backend default')}.")
    moderator = record["moderator"]
    if moderator:
        lines += [f"- Moderator: {moderator['backend']}/{moderator['model']}.", ""]
    if quick:
        lines += ["Quick is single-round screening. No discussion, moderator, or second rating round was run.", ""]
    if record["errors"]:
        return "\n".join([*lines, *[f"- {error}" for error in record["errors"]], ""])
    lines += ["## Appropriateness", ""]
    if quick:
        lines += ["| Decision | Option | Round 1 median | Classification | IPRAS disagreement |", "|---|---|---:|---|---|"]
    else:
        lines += ["| Decision | Option | Round 1 median | Round 2 median | Classification | IPRAS disagreement |",
                  "|---|---|---:|---:|---|---|"]
    for did, options in record["aggregate"]["options"].items():
        labels = {row_id: label for label, row_id in record["row_map"][did].items()}
        for row_id, item in options.items():
            first = record["round1_summary"]["options"][did][labels[row_id]]["median"]
            medians = f"{first} | " if quick else f"{first} | {item['median']} | "
            lines.append(f"| {did} | {row_id} | {medians}"
                         f"{item['classification']} | {item['disagreement']} |")
    lines += ["", "No IPRAS disagreement is not proof of consensus. Inspect individual votes and reasons, "
              "especially with fewer than seven members. Medians 3.5 and 6.5 remain uncertain.", "",
              "## Harm extension", "", "| Unit | Median tier | Disagreement |",
              "|---|---|---|"]
    harms = {"usualCare": record["aggregate"]["usualCare"], **record["aggregate"]["decisions"]}
    lines += [f"| {unit} | {item['medianVote']} | {item['disagreement']} |"
              for unit, item in harms.items()]
    lines += ["", "The categorical lower median preserves an existing tier, including for even panel sizes. "
              "Harm disagreement means votes span at least two tiers. No usual-care cap or rubric merge is applied."]
    lines += ["", "## Individual final votes", "",
              "| Member | Decision | Option | Score |", "|---:|---|---|---:|"]
    lines += [f"| {index} | {did} | {row_id} | {vote} |"
              for did, options in record["aggregate"]["options"].items()
              for row_id, item in options.items() for index, vote in enumerate(item["votes"], 1)]
    lines += ["", "## Options", ""]
    lines += [f"- {row['id']}: {row['text']}" for d in table["decisions"] for row in d["recommendations"]]
    lines += ["", f"Method source: [RAND/UCLA manual]({MANUAL}). Individual reasons, raw replies, "
              "available phase outputs, and input identities are preserved in the adjacent JSON and phase receipts.", ""]
    return "\n".join(lines)


def rate(caseset: Path, case_id: str, table_label: str, repeats: int,
         committee: list[Route], tag: str = "rand", *, moderator: Route | None = None,
         workers: int = 3, evidence_path: Path | None = None, mode: str = "full") -> list[Path]:
    project = Project(caseset)
    table, case = project.table(case_id, table_label), project.case(case_id)
    evidence = evidence_path.read_text() if evidence_path else ""
    paths = project.new_ratings(tag, case_id, table_label, repeats)
    folders = [path.with_suffix(".receipts") for path in paths]
    # Claim every repeat before any call; interruption cannot make a tag silently reusable.
    for folder in folders:
        folder.mkdir(exist_ok=False)
    for path, folder in zip(paths, folders):
        record = run_panel(case, table, committee, moderator=moderator, workers=workers, evidence=evidence, mode=mode,
                           save=lambda name, receipt: project.write_new(folder / f"{name}.json", receipt))
        project.write_new(path, {"table": table_label,
                                 "evidence_path": str(evidence_path) if evidence_path else None, **record})
        project.write_new(path.with_suffix(".md"), render_report(record, table))
    return paths
