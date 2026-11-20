"""Earlier judge rules and scorer adapter; the vendored source and legacy adapter stay unchanged."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.e2e import text_v2
from pipeline.e2e.noharm_j22_loader import ROOT, SOURCE_COMMIT, load_scorer
from arisekit.common.hashing import json_sha256, sha256
from arisekit.common.jsonio import read_json
from arisekit.common.schemas import strict_schema

scorer = load_scorer()
JUDGE = "J2.2"
JUDGE_DIR = ROOT / "experiments/analyses/20261025-v34-e2e/judge-j2"
FORMAT_INSTRUCTIONS = text_v2.FORMAT_INSTRUCTIONS


def scoring_errors(record: dict[str, Any]) -> list[str]:
    errors = scorer.validate(record, "scoring")[0]
    if any(d.get("kind") == "counseling" for d in record.get("decisions", [])):
        errors.append("Scoring needs the current rubric format; rebuild the legacy counseling criterion first")
    return errors


def canonical_schema() -> dict[str, Any]:
    return read_json(JUDGE_DIR / "schema.json")


def provider_schema(record: dict[str, Any]) -> dict[str, Any]:
    canonical = canonical_schema()
    decision = strict_schema(canonical["properties"]["decisions"]["additionalProperties"])
    schema = strict_schema(canonical)
    for key in ("x-noharm-profile", "x-noharm-completeness", "x-noharm-judge"):
        schema.pop(key, None)
    schema["properties"]["profile"] = {"type": "string", "const": scorer.PROFILE}
    schema["properties"]["caseId"] = {"type": "string", "const": record["caseId"]}
    schema["properties"]["rubricSha256"] = {"type": "string", "const": scorer.rubric_sha256(record)}
    schema["$defs"] = {"criterion": decision}
    schema["properties"]["decisions"] = {
        "type": "object", "properties": {d["id"]: {"$ref": "#/$defs/criterion"} for d in record["decisions"]},
        "required": [d["id"] for d in record["decisions"]], "additionalProperties": False,
    }
    return schema


def variables(record: dict[str, Any], case_context: str, response: str) -> dict[str, str]:
    return {"case": case_context, "response": response,
            "table": json.dumps(scorer.project_for_judge(record), indent=1),
            "judge_rules": (JUDGE_DIR / "rules.md").read_text(encoding="utf-8"),
            "schema": json.dumps(canonical_schema(), indent=1)}


def prompt(values: dict[str, str], suffix: str = "") -> tuple[str, str]:
    template = (JUDGE_DIR / "prompt.md").read_text(encoding="utf-8")
    # Substitute only template placeholders, never placeholder-like text inside case evidence.
    import re
    body = re.sub(r"\{\{(judge_rules|schema|case|table|response)\}\}",
                  lambda match: values[match.group(1)], template)
    if suffix:
        body += "\n\n" + suffix
    return "Apply the pinned NOHARM judge instructions. Return only the required JSON object.", body


def source_paths() -> list[Path]:
    return [ROOT / "tools" / name for name in
            ("score_rubric.py", "score_text_rubric.py", "score_text_rubric_v2.py")] + [
                scorer.PROFILE_DIR / "judge/schema.json",
                *(JUDGE_DIR / name for name in ("prompt.md", "rules.md", "schema.json")),
            ]


def bindings() -> dict[str, str]:
    sources = {str(path.relative_to(ROOT)): sha256(path.read_bytes()) for path in source_paths()}
    sources["adapter.py"] = sha256(Path(__file__).read_bytes())
    return {"judge_scoring_source_commit": SOURCE_COMMIT, "judge_protocol": JUDGE,
            "judge_contract_sha256": json_sha256(sources)}


def score_case(record: dict[str, Any], judgment: dict[str, Any], response: str,
               case_context: str) -> dict[str, Any]:
    result = scorer.score_case_s2(record, judgment, response, case_context)
    # Upstream keeps an older schema-family label; the toolkit records the judge rules actually used.
    return {**result, "judge": JUDGE, "schemaJudge": result["judge"], **bindings()}
