from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from arisekit.benchmark import Benchmark
from arisekit.package import load_package
from arisekit.scorer import identify_scorer
from arisekit.generation.specialty_adapters import SPECIALTY_CANDIDATE_SCHEMA, SCTConcordanceScorer, compile_sct_items, specialty_scorer_from_spec
from arisekit.types import RunResult

PATH = Path(__file__).resolve().parents[1] / "scripts/package_generated_cohort.py"
SPEC = importlib.util.spec_from_file_location("generated_cohort_package", PATH)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def rows():
    payload = {"schema_version": SPECIALTY_CANDIDATE_SCHEMA, "kind": "sct", "name": "fictional-sct", "specialty": "Fictional medicine",
        "reference_origin": "synthetic", "items": [{"id": f"case-{i}", "scenario": f"Fictional scenario {i}", "hypothesis": "Fictional hypothesis",
        "new_evidence": "Fictional new evidence", "reference_counts": {"-2": 0, "-1": 1, "0": 2, "1": 3, "2": 4}, "expert_ratings": []} for i in range(2)]}
    values = [r.to_dict() for r in compile_sct_items(payload)]
    for r in values:
        r["prompt"] = "A fictional native SCT question. Respond with Rating: and an ordinal."
        r["metadata"]["native_prompt"] = True
    return values


def metrics(scorer, item, responses):
    return {r.name: r for r in scorer.score_item(item, responses)}


@pytest.mark.parametrize("text,credit,strict", [
    ("Rating: -2", 0, 1), ("Rating: -1", .25, 1), ("Rating: 0", .5, 1),
    ("Rating: +1", .75, 1), ("Rating: +2", 1, 1), ("+1", 0, 0),
    ("Rating: 10", .75, 0), ("Rating: +2\nRating: -1", .25, 0), ("Rating: 3", 0, 0),
])
def test_native_credit_and_whole_format_are_separate(text, credit, strict):
    from arisekit.types import BenchmarkItem
    item = BenchmarkItem.from_dict(rows()[0])
    result = metrics(SCTConcordanceScorer(response_format="mast-native-rating"), item, [RunResult(id=item.id, trial=0, response=text)])
    assert result["synthetic_concordance"].value == credit
    assert result["strict_format_rate"].value == strict


def test_native_failures_and_truncation_are_missing_without_changing_ordinal_mode():
    from arisekit.types import BenchmarkItem
    item = BenchmarkItem.from_dict(rows()[0])
    responses = [RunResult(id=item.id, trial=0, response="Rating: +1"),
        RunResult(id=item.id, trial=1, response="", error="transport"),
        RunResult(id=item.id, trial=2, response="Rating: +1", metadata={"finish_reason": "length"})]
    result = metrics(SCTConcordanceScorer(response_format="mast-native-rating"), item, responses)
    assert result["synthetic_concordance"].value == .75 and result["synthetic_concordance"].n == 1
    assert result["execution_error_rate"].value == result["truncated_response_rate"].value == 1/3
    ordinary = metrics(SCTConcordanceScorer(), item, [RunResult(id=item.id, trial=0, response="+1"), responses[1]])
    assert ordinary["synthetic_concordance"].value == .375 and ordinary["synthetic_concordance"].n == 2


def test_native_package_roundtrip_retains_frozen_items_and_scoring(tmp_path):
    values = rows()
    exporter.package(values, tmp_path / "package", family="sct", expected=2, study="frozen-fictional-study", input_sha256="a"*64)
    loaded = Benchmark.from_package(tmp_path / "package")
    assert [r.to_dict() for r in loaded.dataset] == values
    item = list(loaded.dataset)[0]
    result = metrics(loaded.scorer, item, [RunResult(id=item.id, trial=0, response="Rating: +1")])
    assert result["synthetic_concordance"].value == .75
    assert load_package(tmp_path / "package", verify_assets=True).manifest.provenance["provider_calls_during_export"] == 0
    assert identify_scorer(loaded.scorer).digest != identify_scorer(SCTConcordanceScorer()).digest


def test_native_package_refuses_partial_or_expert_relabeling(tmp_path):
    with pytest.raises(ValueError, match="complete frozen cohort"):
        exporter.package(rows()[:1], tmp_path / "partial", family="sct", expected=2, study="fixture", input_sha256="a"*64)
    changed = deepcopy(rows())
    changed[0]["ground_truth"]["reference_origin"] = "expert"
    with pytest.raises(ValueError, match="cannot relabel"):
        exporter.package(changed, tmp_path / "expert", family="sct", expected=2, study="fixture", input_sha256="a"*64)


def test_native_package_spec_cannot_silently_change_the_parser():
    spec = dict(SCTConcordanceScorer(response_format="mast-native-rating").configuration())
    spec["parser"] = "strict-first-token"
    with pytest.raises(ValueError, match="canonical scoring semantics"):
        specialty_scorer_from_spec(spec)


def test_cpc_package_uses_compiler_provenance_and_preserves_diagnostic_contract(tmp_path):
    from arisekit.generation.cpc_ddx import compile_candidate, generation_request
    from arisekit.scorer import DeferredScorer
    from test_cpc_ddx import candidate
    request = generation_request(specialty="Fictional medicine", need_statement="Fictional diagnostic task",
        evidence={"guideline": "Fictional evidence"}, case_count=2)
    values = [r.to_dict() for r in compile_candidate(request, candidate()).items]
    assert all(set(r["ground_truth"]) == {"final_diagnosis"} for r in values)
    exporter.package(values, tmp_path / "cpc", family="cpc", expected=2, study="fixture", input_sha256="a"*64)
    loaded = Benchmark.from_package(tmp_path / "cpc", scorer=DeferredScorer())
    assert [r.to_dict() for r in loaded.dataset] == values
    assert load_package(tmp_path / "cpc", verify_assets=True).manifest.scorer == {"kind": "deferred"}
    values[0]["metadata"]["reference_origin"] = "published_case_diagnosis"
    values[0]["ground_truth"]["reference_origin"] = "synthetic"
    with pytest.raises(ValueError, match="cannot relabel"):
        exporter.package(values, tmp_path / "source", family="cpc", expected=2, study="fixture", input_sha256="a"*64)
