"""Finished clinician judgment reviews: the clinician's reading of one judged response, read back for scoring.

A review is current only while the judge record it was made on, and the response, case presentation and rubric
text it was bound to, are unchanged. Ratings-only rubric edits do not change the rubric text, so they keep it.
"""
from __future__ import annotations

from pathlib import Path

from arisekit.common.hashing import json_sha256
from arisekit.common.jsonio import read_jsonl

from pipeline.e2e.pipeline_v2_review import _errors
from pipeline.e2e.project import Pair, Project

REVIEW_DIR = "judge-reviews"
BINDINGS = ("response_sha256", "case_presentation_sha256", "rubric_text_sha256")


class InvalidJudgmentReview(ValueError):
    """The newest current review no longer validates; an older review is never used in its place."""


def review_path(project: Project, model: str) -> Path:
    return project.results / REVIEW_DIR / f"{model}.jsonl"


def current_judgment_review(project: Project, model: str, pair: Pair, judge_record: dict, table: dict,
                            response: str, context: str) -> dict | None:
    path = review_path(project, model)
    if not path.is_file():
        return None
    judgment_sha = json_sha256(judge_record["judge"])
    for line in reversed(read_jsonl(path)):
        if (line.get("status") == "finished" and (line.get("id"), line.get("trial", 1)) == pair
                and line.get("judgment_sha256") == judgment_sha
                and all(line.get(k) == judge_record.get(k) for k in BINDINGS)):
            if errors := _errors(table, line["reading"], response, context):
                raise InvalidJudgmentReview(f"{model} {pair[0]} trial {pair[1]}: {'; '.join(errors)}")
            return line
    return None
