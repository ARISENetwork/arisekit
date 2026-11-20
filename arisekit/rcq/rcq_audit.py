"""Offline assignment and source-binding audits for retained RCQ AI ratings."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from typing import Any, Mapping, Sequence

from arisekit.rcq import AXES, RUBRIC, digest, validate_judgment, validate_response_record
from arisekit.rcq.rcq_sources import resolve_support
from arisekit.types import BenchmarkItem


def audit_proxy_judgments(request: BenchmarkItem, records: Sequence[Mapping[str, Any]],
                          payload: Mapping[str, Any] | None, *, rater_id: str) -> dict:
    """Keep every assignment while checking response, rubric and citation identity.

    A valid citation proves an exact source binding, not clinical entailment.
    Invalid or missing ratings have no admitted judgment; their original supplied
    values remain in the audit. This never rewrites historical assessments.
    """
    from jsonschema import Draft202012Validator

    frozen = {r["response_key"]: validate_response_record(r) for r in records}
    if len(frozen) != len(records) or any(r.get("error") for r in records):
        raise ValueError("audit requires distinct completed frozen responses")
    prompt = json.loads(request.prompt)
    shown = {r["response_key"]: r for r in prompt["records"]}
    if (len(shown) != len(prompt["records"]) or set(shown) != set(frozen)
            or digest(prompt["rubric"]) != digest(RUBRIC)):
        raise ValueError("request changed frozen assignments or rubric")
    if not isinstance(rater_id, str) or not rater_id.strip():
        raise ValueError("audit requires a rater identity")
    for key, record in frozen.items():
        if any(shown[key][field] != record[field] for field in ("query", "response")):
            raise ValueError("request changed frozen response material")
    row_schema = request.metadata["response_schema"]["properties"]["judgments"]["items"]
    grounded = "deduction_evidence" in row_schema["required"]
    if grounded:
        evidence = {sid: text for row in shown.values() for sid, text in row["evidence"].items()}
        if (evidence != request.metadata["evidence"]
                or prompt["source_catalog"] != request.metadata["source_catalog"]
                or any(text != evidence[sid] for row in shown.values() for sid, text in row["evidence"].items())):
            raise ValueError("request evidence or source catalog changed")
        for sid, source in request.metadata["source_catalog"].items():
            resolve_support([{"source_id": sid, "span_ids": [s["span_id"] for s in source["spans"]],
                              "supports": "Audit frozen source identities"}], evidence, request.metadata["source_catalog"])
    supplied = payload.get("judgments") if isinstance(payload, Mapping) else None
    envelope_issues = []
    if payload is not None and (not isinstance(supplied, list) or set(payload) != {"judgments"}):
        envelope_issues.append("invalid judgment response envelope")
    supplied = supplied if isinstance(supplied, list) else []
    keys = [r.get("response_key") if isinstance(r, Mapping) else None for r in supplied]
    counts = Counter(k for k in keys if isinstance(k, str))
    unexpected = [{"index": i, "supplied": deepcopy(row)} for i, (key, row) in enumerate(zip(keys, supplied))
                  if not isinstance(key, str) or key not in frozen]
    validator = Draft202012Validator(row_schema)
    assignments = []
    for key, record in frozen.items():
        rows = [row for row in supplied if isinstance(row, Mapping) and row.get("response_key") == key]
        result = {"response_key": key, "response_sha256": record["response_sha256"], "rater_id": rater_id,
                  "status": "missing", "issues": [], "supplied": deepcopy(rows), "judgment": None,
                  "deduction_evidence": [], "resolved_support": []}
        if rows:
            issues = list(envelope_issues)
            if counts[key] != 1:
                issues.append("duplicate ratings for one assigned response")
            row = rows[0]
            issues += [error.message for error in validator.iter_errors(row)]
            claims = row.get("deduction_evidence", [])
            result["deduction_evidence"] = deepcopy(claims)
            valid_axes = set()
            if not issues and grounded:
                for claim in claims:
                    if claim["source_id"] not in shown[key]["evidence"]:
                        issues.append("deduction cites evidence assigned to another response")
                        continue
                    try:
                        support = resolve_support([{"source_id": claim["source_id"], "span_ids": claim["span_ids"],
                                                    "supports": claim["claim"]}], evidence, request.metadata["source_catalog"])
                    except (ValueError, KeyError, TypeError) as error:
                        issues.append(str(error))
                    else:
                        valid_axes.add(claim["axis"])
                        result["resolved_support"] += [{"axis": claim["axis"], **span} for span in support]
                issues += ["missing valid deduction binding: " + axis for axis in AXES[:3]
                           if row[axis] < 4 and axis not in valid_axes]
            if not issues:
                values = {k: v for k, v in row.items() if k != "deduction_evidence"}
                try:
                    result["judgment"] = validate_judgment({**values, "origin": "ai-proxy", "rater_id": rater_id,
                        "response_sha256": record["response_sha256"], "rubric_sha256": digest(RUBRIC)})
                except ValueError as error:
                    issues.append(str(error))
            result.update(status="invalid" if issues else "valid", issues=issues)
        assignments.append(result)
    return {"method": "source-bound" if grounded else "original", "assigned": len(frozen), "received": len(supplied),
            "valid": sum(r["status"] == "valid" for r in assignments),
            "invalid": sum(r["status"] == "invalid" for r in assignments),
            "missing": sum(r["status"] == "missing" for r in assignments),
            "envelope_issues": envelope_issues, "unexpected": unexpected, "assignments": assignments,
            "clinical_entailment_assessed": False}
