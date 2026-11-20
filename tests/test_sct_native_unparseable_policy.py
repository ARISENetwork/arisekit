"""Native SCT skip policy over synthetic fixtures and retained offline responses."""

import json

import pytest

from arisekit.benchmark import Benchmark
from arisekit.client import ModelResponse
from arisekit.package import BenchmarkManifest, load_package, write_package
from arisekit.runner import RunnerConfig
from arisekit.scorer import identify_scorer
from arisekit.analysis.stats import aggregate
from arisekit.generation.specialty_adapters import (
    SCTConcordanceScorer,
    SPECIALTY_CANDIDATE_SCHEMA,
    compile_sct_items,
    specialty_scorer_from_spec,
)
from arisekit.types import RunResult


def items(count=2):
    return list(compile_sct_items({"schema_version": SPECIALTY_CANDIDATE_SCHEMA,
        "kind": "sct", "name": "sct-policy-fixture", "specialty": "Fictional medicine",
        "reference_origin": "synthetic", "items": [{"id": f"case-{index}",
            "scenario": f"Fictional scenario {index}", "hypothesis": "Fictional option",
            "new_evidence": "Fictional finding", "reference_counts": {"-2": 0, "-1": 1, "0": 2, "1": 3, "2": 4},
            "expert_ratings": []} for index in range(count)]}))


def metrics(scorer, responses):
    return {value.name: value for value in scorer.score_item(items()[0], responses)}


def native(policy="zero"):
    return SCTConcordanceScorer(response_format="mast-native-rating", unparseable_policy=policy)


@pytest.mark.parametrize("answer", [None, "", "  \n", "No rating provided", "Rating: 3", 1, {}])
def test_skip_keeps_malformed_attempts_in_diagnostics_but_out_of_concordance(answer):
    response = RunResult(id="case-0", trial=0, response=answer)
    skipped, legacy = metrics(native("skip"), [response]), metrics(native(), [response])
    assert "synthetic_concordance" not in skipped
    assert legacy["synthetic_concordance"].n == 1 and legacy["synthetic_concordance"].value == 0
    assert skipped["invalid_response_rate"].n == skipped["strict_format_rate"].n == 1
    assert skipped["invalid_response_rate"].value == 1 and skipped["strict_format_rate"].value == 0
    assert skipped["execution_error_rate"].n == skipped["truncated_response_rate"].n == 1


@pytest.mark.parametrize("answer,credit,strict", [
    ("Rating: -2", 0., 1.), ("Rating: 0", .5, 1.), ("Rating: +1", .75, 1.),
    ("Rating: +2", 1., 1.), ("Rating: 10", .75, 0.), ("Rating: +2\nRating: -1", .25, 0.),
])
def test_valid_zero_and_permissive_native_ratings_keep_their_credit(answer, credit, strict):
    result = metrics(native("skip"), [RunResult(id="case-0", trial=0, response=answer)])
    assert result["synthetic_concordance"].n == 1
    assert result["synthetic_concordance"].value == credit
    assert result["invalid_response_rate"].value == 0
    assert result["strict_format_rate"].value == strict


def test_execution_errors_and_truncations_remain_separate_for_both_policies():
    responses = [RunResult(id="case-0", trial=0, response="Rating: +2", error="transport failed"),
        RunResult(id="case-0", trial=1, response="Rating: +2", metadata={"finish_reason": "length"}),
        RunResult(id="case-0", trial=2, response="Rating: -2")]
    for policy in ("zero", "skip"):
        result = metrics(native(policy), responses)
        assert result["synthetic_concordance"].n == 1 and result["synthetic_concordance"].value == 0
        assert result["execution_error_rate"].value == result["truncated_response_rate"].value == 1/3
        assert result["invalid_response_rate"].n == 1 and result["invalid_response_rate"].value == 0


def test_skip_aggregates_format_diagnostics_only_over_eligible_responses():
    values = items(3)
    responses = [RunResult(id=values[0].id, trial=0, response="Rating: +2"),
        RunResult(id=values[1].id, trial=0, response="No rating"),
        RunResult(id=values[2].id, trial=0, response=None, error="Offline transport error")]
    result = {metric.name: metric for metric in aggregate(
        native("skip").score_item(item, [response]) for item, response in zip(values, responses))}
    assert result["synthetic_concordance"].value == 1 and result["synthetic_concordance"].n == 1
    for name in ("invalid_response_rate", "strict_format_rate"):
        assert result[name].value == .5 and result[name].n == 2
    assert result["execution_error_rate"].value == 1/3 and result["execution_error_rate"].n == 3
    assert result["truncated_response_rate"].value == 0 and result["truncated_response_rate"].n == 3


def test_skip_does_not_invent_format_observations_when_every_response_is_unavailable():
    responses = [RunResult(id="case-0", trial=0, response=None, error="Offline transport error"),
        RunResult(id="case-0", trial=1, response="Rating: +2", metadata={"finish_reason": "length"})]
    result = metrics(native("skip"), responses)
    assert set(result) == {"execution_error_rate", "truncated_response_rate"}
    assert all(metric.n == 2 and metric.value == .5 for metric in result.values())
    assert native("skip").score_item(items()[0], []) == []
    legacy = metrics(native(), responses)
    assert legacy["strict_format_rate"].n == legacy["invalid_response_rate"].n == 0


def test_existing_canonical_configuration_bytes_and_explicit_zero_stay_unchanged():
    expected = {
        "ordinal-only": '{"kind":"sct-concordance","normalization":"count-divided-by-modal-count","reference_schema":"arisekit.sct-reference.v1","response_format":"ordinal-only"}',
        "mast-native-rating": '{"kind":"sct-concordance","missing_policy":"exclude-execution-errors-and-truncation-report-separately","normalization":"count-divided-by-modal-count","parser":"last-Rating-marker-first-signed-012-in-next-ten-characters","reference_schema":"arisekit.sct-reference.v1","response_format":"mast-native-rating"}',
    }
    for response_format, before in expected.items():
        default = SCTConcordanceScorer(response_format=response_format)
        explicit = SCTConcordanceScorer(response_format=response_format, unparseable_policy="zero")
        assert json.dumps(dict(default.configuration()), sort_keys=True, separators=(",", ":")) == before
        assert default.configuration() == explicit.configuration()
        assert identify_scorer(default).digest == identify_scorer(explicit).digest
        assert specialty_scorer_from_spec(json.loads(before)).configuration() == default.configuration()


@pytest.mark.parametrize("kwargs", [{"unparseable_policy": "skip"},
    {"response_format": "mast-native-rating", "unparseable_policy": "impute"}])
def test_skip_requires_native_format_and_only_supported_policies(kwargs):
    with pytest.raises(ValueError):
        SCTConcordanceScorer(**kwargs)


def test_skip_package_spec_roundtrip_cannot_claim_legacy_missing_semantics():
    spec = dict(native("skip").configuration())
    assert specialty_scorer_from_spec(spec).configuration() == spec
    changed = {**spec, "missing_policy": dict(native().configuration())["missing_policy"]}
    with pytest.raises(ValueError, match="canonical scoring semantics"):
        specialty_scorer_from_spec(changed)


@pytest.mark.parametrize("answers,legacy_value,eligible,skip_value", [
    ([None, "", "No rating", "Rating: -2", "Rating: +1"], .15, 2, .375),
    ([None, "", "No rating", "Rating: 3", "null"], 0., 0, None),
    ([RuntimeError("fixture transport error"), ("Rating: +2", "length"),
      RuntimeError("fixture transport error"), ("Rating: +1", "length"),
      RuntimeError("fixture transport error")], 0., 0, None),
])
def test_portable_skip_load_and_rescore_preserve_saved_responses_without_new_calls(
    tmp_path, answers, legacy_value, eligible, skip_value,
):
    values = items(5)
    for name, scorer in (("legacy", native()), ("skip", native("skip"))):
        write_package(tmp_path/name, manifest=BenchmarkManifest(id="sct-policy-fixture", name="sct-policy-fixture",
            scorer=dict(scorer.configuration())), items=values, write_asset_manifest=True)
        assert [row.to_dict() for row in load_package(tmp_path/name, verify_assets=True).items] == [row.to_dict() for row in values]
    old = Benchmark.from_package(tmp_path/"legacy")
    updated = Benchmark.from_package(tmp_path/"skip")
    old.runner_config = RunnerConfig(results_dir=tmp_path/"run", threads=1, trials=1, max_retries=1, retry_backoff=0)
    class OfflineClient:
        model = "offline/sct-policy-fixture"
        calls = 0
        def __call__(self, call):
            self.calls += 1
            answer = answers[int(call.item.id.split("-")[-1])]
            if isinstance(answer, Exception):
                raise answer
            text, finish_reason = answer if isinstance(answer, tuple) else (answer, "stop")
            return ModelResponse(text=text, finish_reason=finish_reason, cost=0.)
    client = OfflineClient()
    run = old.run(client, auto_manifest=True)
    checkpoint = run.summary.output_path
    before = checkpoint.read_bytes()
    legacy = old.rescore(checkpoint, results_dir=tmp_path/"legacy-revision")
    skipped = updated.rescore(checkpoint, results_dir=tmp_path/"skip-revision")
    old_metric = next(value for value in legacy.metrics if value.name == "synthetic_concordance")
    new_metric = next((value for value in skipped.metrics if value.name == "synthetic_concordance"), None)
    assert old_metric.n == 5 and old_metric.value == pytest.approx(legacy_value)
    if eligible:
        assert new_metric.n == eligible and new_metric.value == pytest.approx(skip_value)
    else:
        assert new_metric is None
    saved = [json.loads(line) for line in before.decode().splitlines()]
    assert len(saved) == 5
    assert sum(bool(row.get("error")) for row in saved) == sum(isinstance(value, Exception) for value in answers)
    assert sum(row.get("metadata", {}).get("finish_reason") == "length" for row in saved) == sum(isinstance(value, tuple) for value in answers)
    assert skipped.scorer_identity.digest == identify_scorer(updated.scorer).digest
    assert client.calls == 5 and checkpoint.read_bytes() == before
    assert json.loads(skipped.receipt_path.read_text())["solver_calls"] == 0
