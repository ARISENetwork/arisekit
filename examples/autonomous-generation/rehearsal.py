"""Offline generation, packaging, scoring and resume with illustrative fixtures."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from arisekit.generation.autonomous_generation import (
    novel_design_request,
    run_autonomous_generation,
    specialty_generation_request,
)
from arisekit.client import ModelResponse
from arisekit.dataset import Dataset
from arisekit.generation.international_adaptation import (
    AdaptationEvidence,
    InternationalAdaptationPlan,
    write_international_baseline,
)
from arisekit.package import load_package, scorer_from_manifest
from arisekit.runner import RunnerConfig
from arisekit.types import BenchmarkItem, RunResult


SPECIALTY = "illustrative-neurology"
EVIDENCE = {"toy-rules": "Fictional condition A can cause symptom X and test pattern Z; feature Y offers some support."}


def specialty_candidate(kind):
    candidate = {
        "schema_version": "arisekit.specialty-candidate.v1", "kind": kind,
        "name": f"illustrative-{kind}", "specialty": SPECIALTY, "reference_origin": "synthetic",
    }
    if kind == "sct":
        candidate["items"] = [{
            "id": "scenario-1", "scenario": "An adult reports intermittent symptom X.",
            "hypothesis": "Condition A explains the presentation.",
            "new_evidence": "Feature Y is observed.",
            "reference_counts": {"-2": 0, "-1": 0, "0": 1, "1": 3, "2": 1},
            "expert_ratings": [],
        }]
    else:
        candidate["diagnoses"] = [
            {"id": "condition-a", "label": "Condition A", "aliases": []},
            {"id": "condition-b", "label": "Condition B", "aliases": []},
        ]
        candidate["cases"] = [{
            "id": "case-1", "presentation": "An adult reports symptom X.",
            "final_diagnosis_id": "condition-a", "expert_reviews": [],
            "stages": [
                {"id": "initial", "evidence": "Feature Y is present.",
                 "reference_differential": [{"diagnosis_id": "condition-b", "evidence_ids": ["initial"]}]},
                {"id": "test", "evidence": "Test pattern Z is present.",
                 "reference_differential": [{"diagnosis_id": "condition-a", "evidence_ids": ["test"]}]},
            ],
        }]
    return candidate


def administrative_candidate():
    return {
        "name": "Illustrative scheduling", "task": "Route a request using its stated priority.",
        "population": "Scheduling staff", "setting": "Fictional clinic",
        "response_contract": "Return exactly routine or urgent.",
        "rubric": {"criteria": ["Use the priority stated in the request."]},
        "scorer": {"kind": "exact-match"},
        "items": [{"id": "request-1", "prompt": "A booking request is marked routine. Give its route.",
                   "ground_truth": "routine", "source_ids": ["booking-rule"]}],
    }


def international_plan():
    return InternationalAdaptationPlan(
        source=BenchmarkItem(
            id="urn:illustration:booking/1",
            prompt="At Source clinic the front desk books routine visits. Which desk books them? Return only its name.",
            ground_truth="front desk", metadata={"reference_origin": "synthetic"},
        ),
        rubric={"criterion": "Identify the desk named by the supplied booking rule."},
        source_benchmark_id="illustrative-booking", source_benchmark_version="1.0.0",
        source_language="en", source_setting="Source clinic",
        target_language="sv", target_setting="Target clinic",
        evidence=(AdaptationEvidence(
            "target-booking-rule", "At Target clinic, central booking books routine visits.",
            setting="Target clinic", locator="fixture://target-booking-rule",
        ),),
        scorer_spec={"kind": "exact-match", "primitive": "arisekit.scorer.exact_match",
                     "options": {"name": "synthetic_reference_exact_match"}},
    )


def international_candidate(cell):
    wording = {
        "language-only": (
            "På Source clinic bokar receptionen rutinbesök. Vem bokar dem? Svara endast med namnet.",
            "receptionen", "Ange den funktion som nämns i bokningsregeln.", ["language"],
        ),
        "system-only": (
            "At Target clinic central booking books routine visits. Who books them? Return only its name.",
            "central booking", "Identify central booking under the supplied target rule.", ["system"],
        ),
        "combined": (
            "På Target clinic bokar central bokning rutinbesök. Vem bokar dem? Svara endast med namnet.",
            "central bokning", "Ange central bokning enligt den angivna regeln.", ["language", "system"],
        ),
    }
    prompt, reference, criterion, kinds = wording[cell]
    ids = ["source-item"] if cell == "language-only" else ["target-booking-rule"]
    return {
        "prompt": prompt, "reference": reference, "rubric": {"criterion": criterion},
        "changes": [{"field": name, "change_kinds": kinds,
                     "rationale": "Apply the requested wording and/or the supplied target booking rule.",
                     "evidence_ids": ids} for name in ("prompt", "reference", "rubric")],
    }


class FixtureGenerator:
    """Canned illustrative outputs; no provider, credentials, or network access."""

    model = "fixture/autonomous-rehearsal"

    def __init__(self):
        self.calls = 0

    def __call__(self, call):
        self.calls += 1
        kind = call.item.metadata.get("candidate_kind")
        if kind in {"sct", "cpc"}:
            candidate = specialty_candidate(kind)
        elif kind == "novel-text":
            candidate = administrative_candidate()
        else:
            candidate = international_candidate(call.item.metadata["international_adaptation"]["cell"])
        return ModelResponse(text=json.dumps(candidate, ensure_ascii=False), cost=0.0,
                             provider_model=self.model)


def run_branch(name, dataset, root):
    client = FixtureGenerator()
    config = RunnerConfig(max_calls=len(dataset), max_cost=1.0, max_cost_per_call=0.1,
                          max_retries=1, require_known_cost=True)
    output = root / name
    arguments = dict(model=client, config=config, output_dir=output,
                     data_classification="synthetic", max_repairs=0)
    report = run_autonomous_generation(dataset, **arguments)
    if report["compiled"] != len(dataset):
        raise RuntimeError(f"{name}: compilation failed: {report['outcomes']}")
    first_calls = client.calls
    resumed = run_autonomous_generation(dataset, **arguments)
    if client.calls != first_calls or resumed != report:
        raise RuntimeError(f"{name}: resume changed the completed run")
    checks = []
    for outcome in report["outcomes"]:
        package = load_package(output / outcome["package"], verify_assets=True)
        scorer = scorer_from_manifest(package.manifest)
        for item in package.items:
            if name == "sct":
                response = "+1"
            elif name == "cpc":
                response = '{"diagnoses":["Condition A","Condition B"]}'
            elif name == "novel-admin":
                response = "routine"
            else:
                response = international_candidate(item.metadata["international_adaptation"]["cell"])["reference"]
            metrics = scorer.score_item(item, [RunResult(item.id, 1, response)])
            checks.append({"item_id": item.id, "fixture_metrics": [metric.to_dict() for metric in metrics]})
    return {"branch": name, "compiled_packages": report["compiled"], "fixture_calls_this_invocation": first_calls,
            "resume_new_calls": client.calls - first_calls, "cost_total": report["cost_total"],
            "report": str(output / "generation-report.json"), "scoring_checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Directory for retained local artifacts")
    root = parser.parse_args().output.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    plan = international_plan()
    international = plan.generation_dataset()
    baseline = root / "international-source-baseline"
    if baseline.exists():
        stored = load_package(baseline, verify_assets=True)
        if stored.items[0].to_dict() != plan.baseline().to_dict():
            raise RuntimeError("Existing baseline differs from this rehearsal")
    else:
        write_international_baseline(international[0], baseline)
    branches = [
        (kind, Dataset([specialty_generation_request(
            request_id=f"illustrative-{kind}", kind=kind, specialty=SPECIALTY, evidence=EVIDENCE,
        )])) for kind in ("sct", "cpc")
    ]
    branches.append(("novel-admin", Dataset([novel_design_request(
        request_id="illustrative-admin", need="Design a stated-priority booking task.",
        evidence={"booking-rule": "Routine requests use the routine route; urgent requests use the urgent route."},
        item_count=1,
    )])))
    branches.append(("international", international))
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(run_branch, name, dataset, root) for name, dataset in branches]
        reports = [future.result() for future in futures]
    summary = {"evidence_kind": "illustrative-offline-software-rehearsal",
               "source_baseline": str(baseline), "branches": reports}
    (root / "rehearsal-summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for report in reports:
        print(f"{report['branch']}: {report['compiled_packages']} packages; "
              f"{report['fixture_calls_this_invocation']} fixture calls; "
              f"{report['resume_new_calls']} new calls on resume")
    print(f"Summary: {root / 'rehearsal-summary.json'}")


if __name__ == "__main__":
    main()
