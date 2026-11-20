"""Validation gate for generated rubrics: the editor's validator, the scorer's rules, and authoring standards."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile

from pipeline.e2e.constants import APP_ROOT, KIT_ROOT
from pipeline.e2e.rubric import NO_PRECAUTIONS, PRECAUTIONS, STANDARD_BEST, TESTING, TREATMENT, Decision, Table
from tools.score_answer_table import appropriate_rows, validation_errors

TS_VALIDATOR = KIT_ROOT / "tools" / "validate_answer_table.ts"

CONDITIONAL = re.compile(r"^\s*If\b|\bif (?:symptoms|the|she|he|there|results?)\b", re.IGNORECASE)
NO_ACTION = re.compile(r"^(Do not|Defer|No )")
PRECAUTION_WORDS = re.compile(
    r"\b(emergency department|seek (?:prompt|immediate)|call 911|return precautions|report new)\b", re.IGNORECASE)


def standard_problems(rec: Table) -> list[str]:
    """Authoring standards a generated rubric must meet beyond the editor and scorer rules."""
    decisions = rec["decisions"]
    problems = [*_dual_mode(rec), *_standard_decisions(rec), *_follow_up(rec, decisions[0])]
    for index, d in enumerate(decisions):
        if d["question"] == PRECAUTIONS:
            problems += _precautions(rec, d)
        if d["question"] in STANDARD_BEST:
            problems += _testing_or_treatment(rec, d, later=decisions[index + 1:])
        else:
            problems += _leftover_host(rec, d)
    return problems


def _dual_mode(rec: Table) -> list[str]:
    return [] if rec.get("harmOverrides") is True else [f"{rec['caseId']}: not dual mode"]


def _standard_decisions(rec: Table) -> list[str]:
    """Testing, treatment, and return precautions appear at most once; return precautions is required."""
    cid, questions = rec["caseId"], [d["question"] for d in rec["decisions"]]
    problems = [f"{cid}: {q!r} appears {questions.count(q)} times"
                for q in (TESTING, TREATMENT, PRECAUTIONS) if questions.count(q) > 1]
    if PRECAUTIONS not in questions:
        problems.append(f"{cid}: missing standard Decision {PRECAUTIONS!r}")
    return problems


def _follow_up(rec: Table, d1: Decision) -> list[str]:
    """D1 (follow-up or triage) is always active, unconditional, and holds no return precautions."""
    cid = rec["caseId"]
    problems = [] if _always_active(d1) else [f"{cid}: D1 follow-up or triage must always be active"]
    problems += [f"{cid} {r['id']}: conditional text in D1: {r['text'][:80]!r}"
                 for r in d1["recommendations"] if CONDITIONAL.search(r["text"])]
    problems += [f"{cid} {r['id']}: return precautions still a D1 part"
                 for r in appropriate_rows(d1) for part in r.get("parts", []) if PRECAUTION_WORDS.search(part)]
    return problems


def _precautions(rec: Table, d: Decision) -> list[str]:
    """Return precautions are always active; "no specific precautions" as a best answer means harm none."""
    cid = rec["caseId"]
    problems = [] if _always_active(d) else [f"{cid} {d['id']}: return-precaution advice must always be active"]
    if NO_PRECAUTIONS in _best_texts(d) and d.get("harmIfNotAddressedOverride") != "none":
        problems.append(f"{cid} {d['id']}: no specific precautions requires harm none")
    return problems


def _testing_or_treatment(rec: Table, d: Decision, later: list[Decision]) -> list[str]:
    """Harm none, the standard best answer, and nothing but the other standard Decision after it."""
    cid = rec["caseId"]
    problems = []
    if d.get("harmIfNotAddressedOverride") != "none":
        problems.append(f"{cid} {d['id']}: standard Decision without harm none")
    if STANDARD_BEST[d["question"]] not in _best_texts(d):
        problems.append(f"{cid} {d['id']}: standard best recommendation text missing")
    if len(later) > 1 and any(x["question"] not in STANDARD_BEST for x in later):
        problems.append(f"{cid} {d['id']}: standard Decision is not last")
    return problems


def _leftover_host(rec: Table, d: Decision) -> list[str]:
    """A no-action best answer with harm none marks a leftover host Decision (except "no specific precautions")."""
    best = _best_texts(d)[0]
    if (d.get("harmIfNotAddressedOverride") == "none" and NO_ACTION.match(best)
            and not (d["question"] == PRECAUTIONS and best == NO_PRECAUTIONS)):
        return [f"{rec['caseId']} {d['id']}: ad hoc host Decision remains ({d['question'][:60]!r})"]
    return []


def _always_active(d: Decision) -> bool:
    return d.get("activation", {}).get("type") == "always"


def _best_texts(d: Decision) -> list[str]:
    appropriate = appropriate_rows(d)
    best = max(r["score"] for r in appropriate)
    return [r["text"] for r in appropriate if r["score"] == best]


def ts_errors(record: Table) -> list[str]:
    with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
        json.dump(record, f)
        f.flush()
        proc = subprocess.run(["node", "--import", "tsx", str(TS_VALIDATOR), f.name],
                              cwd=APP_ROOT, capture_output=True, text=True, check=False)
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"validate_answer_table.ts exit {proc.returncode}: {proc.stderr[:500]}")
    return json.loads(proc.stdout)


def table_errors(record: Table) -> list[str]:
    """Every gate error, prefixed by source. Exceptions surface as failed runs through call_json's check."""
    return ([f"validator: {e}" for e in ts_errors(record)]
            + [f"scorer: {e}" for e in validation_errors(record)]
            + [f"standard: {e}" for e in standard_problems(record)])
