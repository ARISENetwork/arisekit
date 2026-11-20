"""Current judge adapter: the earlier judge rules with a short output description and no provider schema.

The vendored source and the earlier judge adapter stay unchanged. Readings are validated after the call.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arisekit.common.hashing import json_sha256, sha256
from arisekit.common.jsonio import read_json

from pipeline.e2e import noharm_p2_loader

SOURCE_COMMIT = noharm_p2_loader.SOURCE_COMMIT
ROOT = noharm_p2_loader.ROOT
FREEZE_DIR = noharm_p2_loader.FREEZE_DIR
scorer = noharm_p2_loader.load().v2
JUDGE = "J2.3"
FREEZE = "pipeline-v2"
PROVIDER_SCHEMA = False
FORMAT_INSTRUCTIONS = ""
INSTRUCTIONS = "Complete this task without tools. Return only the requested output."
STALE_KEYS = ("response_sha256", "case_presentation_sha256", "rubric_text_sha256")
# The study judge's API request timeout in seconds; NOHARMKit's own default is far shorter.
JUDGE_TIMEOUT = read_json(FREEZE_DIR / "config.json")["judge"]["timeout"]


def scoring_errors(record: dict[str, Any]) -> list[str]:
    errors = scorer.validate(record, "scoring")[0]
    if any(d.get("kind") == "counseling" for d in record.get("decisions", [])):
        errors.append("Scoring needs the current rubric format; rebuild the legacy counseling criterion first")
    return errors


def restamp(record: dict[str, Any]) -> Callable[[Any], Any]:
    """Upstream's valid() re-stamps the shared rubric's hash on every reading before checking it."""
    def stamp_rubric_hash(output: Any) -> Any:
        return {**output, "rubricSha256": scorer.rubric_sha256(record)} if isinstance(output, dict) else output
    return stamp_rubric_hash


def canonical_schema() -> dict[str, Any]:
    return read_json(scorer.PROFILE_DIR / "judge/schema.json")


def variables(record: dict[str, Any], case_context: str, response: str) -> dict[str, str]:
    return {"case": case_context, "response": response,
            "table": json.dumps(scorer.project_for_judge(record), indent=1, ensure_ascii=False),
            "judge_rules": (FREEZE_DIR / "judge/rules.md").read_text()}


def prompt(values: dict[str, str], suffix: str = "") -> tuple[str, str]:
    body = (FREEZE_DIR / "judge/prompt.md").read_text()
    # Chained replace in upstream's order, so placeholder-like text inside an earlier substitution is replaced
    # too: the prompt must stay byte-identical to upstream's.
    for name in ("judge_rules", "case", "table", "response"):
        body = body.replace("{{" + name + "}}", values[name])
    if suffix:
        body += "\n\n" + suffix
    return INSTRUCTIONS, body


def judge_prompt(record: dict[str, Any], case_context: str, response: str) -> str:
    return prompt(variables(record, case_context, response))[1]


def source_paths() -> list[Path]:
    return [ROOT / "tools" / name for name in
            ("score_rubric.py", "score_text_rubric.py", "score_text_rubric_v2.py", "score_text_rubric_f1.py")] + [
                scorer.PROFILE_DIR / "judge/schema.json",
                *(FREEZE_DIR / "judge" / name for name in ("prompt.md", "rules.md")),
            ]


def bindings() -> dict[str, str]:
    sources = {str(path.relative_to(ROOT)): sha256(path.read_bytes()) for path in source_paths()}
    sources["adapter.py"] = sha256(Path(__file__).read_bytes())
    return {"judge_scoring_source_commit": SOURCE_COMMIT, "judge_protocol": JUDGE,
            "judge_contract_sha256": json_sha256(sources)}
