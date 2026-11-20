"""Harm-rating committee: independent raters set usual-care harm and each Decision's harm if not addressed.

Raters see structure only (no scores or harm fields). The rounded mean of the votes present replaces the
generator's values, except where a Decision lacks a majority of votes.
"""
from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypedDict

from pipeline.backends import BACKENDS, CallProvenance, Route, route
from pipeline.e2e.constants import KIT_ROOT, SKILLS_ROOT
from pipeline.e2e.project import Project
from pipeline.e2e.records import Case
from pipeline.e2e.rubric import NEED_SEVERITIES, PRECAUTIONS, TESTING, TREATMENT, Decision, Rubric, Table
from pipeline.skillrun import run_skill
from tools.score_answer_table import need_severity
from arisekit.common.hashing import json_sha256
from arisekit.common.jsonio import read_json
from arisekit.common.logs import log
from arisekit.common.schemas import strict_object

SKILL = "rate-harm"
DEFAULT_COMMITTEE = SKILLS_ROOT / SKILL / "committee.default.json"
HARM_SCALE = KIT_ROOT / "docs/context/harm-scale-source.md"
USUAL_CARE_DEFINITION = ("Continuation of the patient's current management or usual care, "
                         "without additional input.")
# Testing and treatment stay at harm none by rule; return precautions keep their stored harm. None are rated.
UNRATED_QUESTIONS = (TESTING, TREATMENT, PRECAUTIONS)
RATER_KEYS = {"backend", "model", "reasoning_effort"}
QUORUM_REASON = "committee quorum not met"
RULE = "rounded_mean"


class CommitteeItem(TypedDict):
    """One rated unit. `median` is the committee value (the rounded mean; key kept for stored records);
    `medianVote` is the lower median vote, the former rule."""
    votes: list[str]
    median: str | None
    medianVote: str | None
    generator: str
    disagreement: bool
    quorum: bool


class RaterResult(TypedDict):
    """One rater's reply and check outcome; `missing` lists rated Decisions the rater left out."""
    rater: int
    status: str
    missing: list[str]
    output: Any
    raw: str | None
    errors: list[str]
    provenance: CallProvenance


class CommitteeRatings(TypedDict):
    """One committee pass: saved as <case>.runN.ratings.json (read by the app) and in `noharm rate` receipts."""
    committee: list[Route]
    raters: list[RaterResult]
    rule: str
    status: str
    errors: list[str]
    usualCare: CommitteeItem | None
    decisions: dict[str, CommitteeItem]
    capAdjustment: dict[str, str] | None


def load_committee(path: Path) -> list[Route]:
    """A committee file: a non-empty list of {backend, model, reasoning_effort?}, each a valid route."""
    committee = read_json(path)
    if not isinstance(committee, list) or not committee:
        raise ValueError(f"{path}: committee must be a non-empty JSON list")
    members = []
    for i, r in enumerate(committee):
        if not isinstance(r, dict) or set(r) - RATER_KEYS or not r.get("model"):
            raise ValueError(f"{path}: rater {i} must be {{backend: {' | '.join(BACKENDS)}, model, reasoning_effort?}}")
        try:
            members.append(route(r.get("backend", ""), r["model"], r.get("reasoning_effort")))
        except ValueError as error:
            raise ValueError(f"{path}: rater {i}: {error}") from error
    return members


def rated_decisions(table: Table) -> list[Decision]:
    return [d for d in table["decisions"] if d["question"] not in UNRATED_QUESTIONS]


def median_tier(votes: list[str]) -> str:
    """Middle vote over none < mild < moderate < severe; the lower middle for an even count."""
    ordered = sorted(votes, key=NEED_SEVERITIES.index)
    return ordered[(len(ordered) - 1) // 2]


def mean_tier(votes: list[str]) -> str:
    """Rounded mean of the tier positions (none 0 ... severe 3), halves rounding down: index = ceil(mean - 0.5)."""
    total, n = sum(NEED_SEVERITIES.index(v) for v in votes), len(votes)
    return NEED_SEVERITIES[-(-(2 * total - n) // (2 * n))]


def is_disagreement(votes: list[str]) -> bool:
    """Raters two or more tiers apart (mild and severe); adjacent tiers are not flagged."""
    if not votes:
        return False
    levels = [NEED_SEVERITIES.index(v) for v in votes]
    return max(levels) - min(levels) >= 2


def quorum_met(passed: int, size: int) -> bool:
    return 2 * passed > size


def cap_adjustment(usual: str, medians: dict[str, str]) -> dict[str, str] | None:
    """Usual care rises to the highest Decision median; the first such Decision is named."""
    top = max(medians.items(), key=lambda kv: NEED_SEVERITIES.index(kv[1]), default=None)
    if top is None or NEED_SEVERITIES.index(top[1]) <= NEED_SEVERITIES.index(usual):
        return None
    return {"from": usual, "to": top[1], "decision": top[0]}


def final_usual_care(record: CommitteeRatings) -> str:
    cap = record["capAdjustment"]
    return cap["to"] if cap else record["usualCare"]["median"]


def _item(votes: list[str], generator: str, size: int) -> CommitteeItem:
    """A vote count below a strict majority of the committee leaves both values null and the stored harm in place."""
    quorum = quorum_met(len(votes), size)
    return {"votes": votes, "median": mean_tier(votes) if quorum else None,
            "medianVote": median_tier(votes) if quorum else None, "generator": generator,
            "disagreement": is_disagreement(votes), "quorum": quorum}


def aggregate(committee: list[Route], raters: list[RaterResult], table: Table) -> CommitteeRatings:
    passed = [r for r in raters if r["status"] == "pass"]
    record: CommitteeRatings = {"committee": committee, "raters": raters, "rule": RULE, "status": "pass", "errors": [],
                              "usualCare": None, "decisions": {}, "capAdjustment": None}
    if not quorum_met(len(passed), len(committee)):
        record["status"] = "failed"
        record["errors"] = [f"{QUORUM_REASON}: {len(passed)} of {len(committee)} raters passed"]
        return record
    size = len(committee)
    record["usualCare"] = _item([r["output"]["usualCare"]["harm"] for r in passed], table["usualCare"]["harm"], size)
    for d in rated_decisions(table):
        votes = [r["output"]["decisions"][d["id"]]["harm"] for r in passed if d["id"] in r["output"]["decisions"]]
        record["decisions"][d["id"]] = _item(votes, need_severity(d), size)
    record["capAdjustment"] = cap_adjustment(record["usualCare"]["median"],
                                             {k: v["median"] for k, v in record["decisions"].items()
                                              if v["median"] is not None})
    return record


def merge(table: Table, record: CommitteeRatings) -> Table:
    merged = copy.deepcopy(table)
    merged["usualCare"]["harm"] = final_usual_care(record)
    for d in merged["decisions"]:
        if record["decisions"].get(d["id"], {}).get("median") is not None:
            d["harmIfNotAddressedOverride"] = record["decisions"][d["id"]]["median"]
    return merged


def harm_scale_text() -> str:
    """The scale's grading guidance for raters, copied verbatim at run time from the single source.

    The source marks each included piece with a `<!-- rater-scale -->` line; a piece runs to the next blank line.
    Included: the commission and omission definitions, plausibility and magnitude, the scenario table, and the
    severity-tier table, in that order.
    """
    blocks = HARM_SCALE.read_text().split("\n\n")
    pieces = [blocks[i + 1] for i, block in enumerate(blocks) if block.strip() == "<!-- rater-scale -->"]
    if len(pieces) != 4:
        raise ValueError(f"{HARM_SCALE}: expected 4 rater-scale pieces, found {len(pieces)}")
    definitions, plausibility, scenarios, tiers = pieces
    return "\n\n".join([definitions, plausibility, scenarios, f"Severity tiers:\n\n{tiers}"])


def project_for_rating(table: Table) -> list[dict[str, Any]]:
    """Structure only: neutral option labels and text, so nothing reveals which options are appropriate."""
    return Rubric(table).neutral_view(rated_decisions(table), {"text"})[0]


def rating_variables(case: Case, table: Table) -> dict[str, str]:
    return {"case": case["presentation"], "expert": case["recommendations"], "harm_scale": harm_scale_text(),
            "usual_care": USUAL_CARE_DEFINITION, "decisions": json.dumps(project_for_rating(table), indent=1)}


def rating_schema(table: Table) -> dict[str, Any]:
    """The exact reply shape for one table, enforced by the provider; inline and strict-mode safe (no $ref)."""
    def rating() -> dict[str, Any]:
        return strict_object({"harm": {"type": "string", "enum": list(NEED_SEVERITIES)},
                               "reason": {"type": "string", "minLength": 1}})

    return strict_object({"usualCare": rating(),
                           "decisions": strict_object({d["id"]: rating() for d in rated_decisions(table)})})


def rating_errors(out: dict[str, Any], table: Table) -> list[str]:
    rated = [d["id"] for d in rated_decisions(table)]
    standard = {d["id"] for d in table["decisions"] if d["question"] in (TESTING, TREATMENT)}
    errors = [f"{did}: standard Decision is not rated" if did in standard else f"unknown Decision {did}"
              for did in out["decisions"] if did not in rated]
    return errors


def missing_decisions(out: dict[str, Any], table: Table) -> list[str]:
    """Rated Decisions a rater left out; they cost that Decision a vote, not the rater's pass."""
    return [d["id"] for d in rated_decisions(table) if d["id"] not in out["decisions"]]


def _rate_one(index: int, rater: Route, variables: dict[str, str], table: Table,
              schema: dict[str, Any]) -> RaterResult:
    kwargs = {"reasoning_effort": rater["reasoning_effort"]} if "reasoning_effort" in rater else {}
    outcome = run_skill(SKILL, variables, rater["backend"], rater["model"], check=lambda o: rating_errors(o, table),
                        reject_duplicate_keys=True, json_schema=schema, **kwargs)
    errors = outcome.errors
    log(f"rate-harm rater {index} ({rater['backend']}/{rater['model']}) {'failed' if errors else 'pass'}")
    missing = missing_decisions(outcome.output, table) if not errors else []
    return {"rater": index, "status": "failed" if errors else "pass", "missing": missing, "output": outcome.output,
            "raw": outcome.raw, "errors": errors, "provenance": outcome.provenance}


def rate_table(case: Case, table: Table, committee: list[Route]) -> CommitteeRatings:
    """One committee pass over one table: every rater in parallel, then the committee values."""
    variables, schema = rating_variables(case, table), rating_schema(table)

    def one(index: int, rater: Route) -> RaterResult:
        return _rate_one(index, rater, variables, table, schema)

    with ThreadPoolExecutor(max_workers=len(committee)) as pool:
        raters = list(pool.map(one, range(len(committee)), committee))
    return aggregate(committee, raters, table)


def rate(caseset: Path, case_id: str, table_label: str, repeats: int,
         committee: list[Route], tag: str = "committee") -> list[Path]:
    """Re-rate an existing table's structure `repeats` times. Never modifies the table."""
    project = Project(caseset)
    table, case = project.table(case_id, table_label), project.case(case_id)
    paths = project.new_ratings(tag, case_id, table_label, repeats)
    sha = json_sha256(table)

    def one(r: int, path: Path) -> None:
        record = rate_table(case, table, committee)
        project.write_new(path, {"table": table_label, "table_sha256": sha, **record})
        log(f"rate {case_id} {table_label} rep{r} {record['status']}")

    # Not pool.map: its first error cancels repeats that have not started, so they would silently never run.
    with ThreadPoolExecutor(max_workers=repeats) as pool:
        futures = [pool.submit(one, r, path) for r, path in enumerate(paths, 1)]
    for future in futures:
        future.result()
    return paths
