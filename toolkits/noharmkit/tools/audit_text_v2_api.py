"""Read-only coverage, binding, and scorer recomputation audit for native API smoke tests."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.e2e import text_v2, text_v2_runtime
from pipeline.e2e.project import Project, record_pair, sanitize_model
from arisekit.common.hashing import json_sha256, sha256
from arisekit.common.jsonio import read_json, read_jsonl
from tools.run_inference import preflight
from tools.web_pipeline_teams import validate_config


def _check_path(path: Path) -> None:
    if "holdout" in str(path).lower():
        raise ValueError("The requested audit contains an excluded path")
    if path.is_symlink():
        raise ValueError("Audit inputs must not be symbolic links")


def audit_project(root: Path) -> dict[str, Any]:
    """Verify stored native API results without writing files or calling providers."""
    _check_path(root)
    root = root.resolve()
    _check_path(root)
    project = Project(root)
    adapter = text_v2_runtime.for_project(project)
    for relative in ("provenance.json", "api-pipeline.json", "items.jsonl", "cases",
                     "answer-tables", "results", "results/responses", "results/judge"):
        _check_path(root / relative)
    provenance = project.provenance()
    if provenance.get("execution_mode") != "api":
        raise ValueError("Project must declare API Mode")
    config = validate_config(read_json(root / "api-pipeline.json"))
    raw_models = config["teams"]["responses"]["models"]
    models = project.model_names()
    if not models or len(set(models)) != len(models) or set(models) != {sanitize_model(m) for m in raw_models}:
        raise ValueError("API response models must match unique declared project models")
    expected = project.expected()
    if not expected:
        raise ValueError("Project has no expected cases")
    items = {item["id"]: item for item in project.items()}
    for item in items.values():
        _check_path(root / "cases" / f"{item['metadata']['base_id']}.json")
    for folder, suffix, names in ((project.results / "responses", ".jsonl", set(models)),
                                  (project.results / "judge", ".jsonl", set(models)),
                                  (project.results, "_scored.jsonl", set(models))):
        for path in folder.glob(f"*{suffix}"):
            _check_path(path)
            if path.name.removesuffix(suffix) not in names:
                raise ValueError(f"Undeclared model file: {path.name}")
    report_models = []
    for raw_model in raw_models:
        model = sanitize_model(raw_model)
        response_path = project.responses_path(model)
        judgment_path = project.judgments_path(model)
        scored_path = project.scored_path(model)
        for path in (response_path, judgment_path, scored_path):
            _check_path(path)
        effort = config["teams"]["responses"].get("modelReasoning", {}).get(raw_model)
        _, collected = preflight(root, raw_model, project.items(), "", project.trials(),
                                 backend="openrouter", reasoning_effort=effort)
        responses, response_errors = project.responses(model)
        judgments, judgment_errors = project.passed_judgments(model)
        if response_errors or judgment_errors:
            raise ValueError("; ".join(response_errors + judgment_errors))
        scores = read_jsonl(scored_path)
        scored = {record_pair(row): row for row in scores}
        if len(scored) != len(scores):
            raise ValueError(f"{model}: duplicate score identity")
        if any(set(found) != expected for found in (collected, responses, judgments, scored)):
            raise ValueError(f"{model}: response, judgment, or score coverage differs from expected pairs")
        rows = []
        for pair in sorted(expected):
            judgment = judgments[pair]
            base = items[pair[0]]["metadata"]["base_id"]
            label = judgment["rubric"]
            for path in (project.artifact(base, label), project.artifact(base, label, "status.json")):
                _check_path(path)
            rubric = project.table(base, label)
            if not text_v2.is_text_v2(rubric):
                raise ValueError(f"{model} {pair}: expected a text rubric")
            response = responses[pair]["response"]
            bindings = project.judgment_bindings(base, label, rubric, response)
            if any(judgment.get(key) != value for key, value in bindings.items()):
                raise ValueError(f"{model} {pair}: stale judgment bindings")
            result = (adapter.scorer.score_case_s2(rubric, judgment["judge"], response,
                                                 project.case(base)["presentation"]) if adapter is text_v2
                      else adapter.score_case(rubric, judgment["judge"], response, project.case(base)["presentation"]))
            required = {"id": pair[0], "trial": pair[1], **bindings, **result,
                        "judgment_sha256": json_sha256(judgment["judge"]),
                        "offRubricProvisional": any(row["actionable"] for row in judgment["judge"]["offRubric"])}
            if changed := [key for key, value in required.items() if key not in scored[pair] or scored[pair][key] != value]:
                raise ValueError(f"{model} {pair}: score mismatch in {', '.join(changed)}")
            rows.append({"id": pair[0], "trial": pair[1], "caseId": base, "rubric": label,
                         "worstError": result["worstError"], "worstErrorBounds": result["worstErrorBounds"],
                         "provisional": result["provisional"],
                         "actionableUnmatched": {key: sum(u["actionable"] for u in value["unmatched"])
                                                 for key, value in judgment["judge"]["decisions"].items()},
                         "actionableOffRubric": sum(u["actionable"] for u in judgment["judge"]["offRubric"])})
        report_models.append({"model": raw_model, "responses": len(responses), "judgments": len(judgments),
                              "scores": len(scored), "results": rows})
    return {"status": "pass", "project": str(root), "expectedPerModel": len(expected),
            "sourceCommit": adapter.SOURCE_COMMIT,
            "scorerSourceSha256": sha256(Path(adapter.scorer.__file__).read_bytes()), "models": report_models}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    try:
        result = audit_project(args.project)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
