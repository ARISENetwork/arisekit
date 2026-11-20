"""Descriptive diversity and deterministic SCT execution sanity checks."""

from collections import Counter
from difflib import SequenceMatcher
import json
import math

from arisekit.types import BenchmarkItem, RunResult


def audit_sct(generated, original, *, novelty_original=None):
    checks, references = [], []
    for arm, benchmark, key in (("generated", generated, "reference_counts"), ("original", original, "published_weights")):
        for item in benchmark.dataset:
            raw = item.ground_truth[key]
            weights = [raw[str(i)] for i in range(-2, 3)] if isinstance(raw, dict) else raw
            expected = [value / max(weights) for value in weights]
            observed = []
            for ordinal in range(-2, 3):
                metrics = benchmark.scorer.score_item(item, [RunResult(id=item.id, trial=1, response=str(ordinal))])
                observed.append(next(metric.value for metric in metrics if metric.name.endswith("_concordance")))
            invalid = benchmark.scorer.score_item(item, [RunResult(id=item.id, trial=1, response="1 or 2")])
            failed = benchmark.scorer.score_item(item, [RunResult(id=item.id, trial=1, response="1", error="sanity-check transport failure")])
            invalid_score = next(metric.value for metric in invalid if metric.name.endswith("_concordance"))
            failed_score = next(metric.value for metric in failed if metric.name.endswith("_concordance"))
            checks.append({"arm": arm, "case_id": item.id,
                "all_ordinals_match_reference": observed == expected,
                "finite_and_bounded": all(math.isfinite(value) and 0 <= value <= 1 for value in observed),
                "modal_score_is_one": max(observed) == 1,
                "malformed_response_is_zero": invalid_score == 0,
                "failed_response_is_zero": failed_score == 0,
                "reference_fields_hidden": all(token not in item.prompt for token in ("reference_counts", "expert_ratings", "published_weights"))})
            total = sum(weights)
            references.append({"arm": arm, "case_id": item.id,
                "modal_ratings": [i - 2 for i, value in enumerate(weights) if value == max(weights)],
                "entropy_bits": -sum((value / total) * math.log2(value / total) for value in weights if value)})
    diagnostics = prompt_diagnostics(generated, novelty_original if novelty_original is not None else original)
    return {"schema_version": "arisekit.sct-validity-sanity.v1",
        "execution_sanity": {"passed": all(all(value for key, value in check.items() if key not in {"arm", "case_id"}) for check in checks),
            "cases_checked": len(checks), "checks": checks},
        **diagnostics,
        "diversity": {**diagnostics["diversity"], "reference_profiles": references},
        "interpretation": "Execution checks and descriptive diversity diagnostics; clinical/content validity is assessed separately"}


def prompt_diagnostics(generated, original, *, presentation_only=False):
    def content(item):
        return item.metadata["presentation"] if presentation_only else str(item.prompt)
    prompts = [(item.id, " ".join(content(item).casefold().split())) for item in generated.dataset]
    counts = Counter(prompt for _, prompt in prompts)
    pairs = [{"case_ids": [left[0], right[0]], "lexical_similarity": SequenceMatcher(None, left[1], right[1]).ratio()}
             for index, left in enumerate(prompts) for right in prompts[index + 1:]]
    sources = [(item.id, " ".join(content(item).casefold().split())) for item in original.dataset]
    original_pairs = [{"generated_id": left[0], "original_id": right[0],
                       "lexical_similarity": SequenceMatcher(None, left[1], right[1]).ratio()}
                      for left in prompts for right in sources]
    return {"diversity": {"generated_cases": len(prompts), "distinct_prompts": len(counts),
            "exact_duplicate_groups": [[identity for identity, text in prompts if text == prompt]
                for prompt, count in counts.items() if count > 1],
            "closest_prompt_pairs": sorted(pairs, key=lambda pair: pair["lexical_similarity"], reverse=True)[:5],
        },
        "novelty": {"original_cases_checked": len(sources),
            "exact_original_matches": [pair for pair in original_pairs if pair["lexical_similarity"] == 1],
            "closest_original_pairs": sorted(original_pairs, key=lambda pair: pair["lexical_similarity"], reverse=True)[:5]}}


def audit_cpc(generated, original, *, novelty_original=None):
    from arisekit.generation.cpc_ddx import JudgmentScorer, solver_prompt
    scorer = JudgmentScorer()
    probes = []
    for rank in range(1, 11):
        item = BenchmarkItem(id="probe", prompt="", metadata={"differential_size": 10})
        response = RunResult(id="probe", trial=1, response=json.dumps({"present": "yes", "matching_diagnosis": "probe", "rank": rank}))
        observed = {metric.name: metric.value for metric in scorer.score_item(item, [response])}
        probes.append(all(observed[f"top{k}"] == float(rank <= k) for k in (1, 5, 10)))
    checks = [{"arm": arm, "case_id": item.id,
        "shared_solver_template": item.prompt == solver_prompt(item.metadata["presentation"]),
        "reference_fields_hidden": all(token not in item.prompt for token in ("final_diagnosis", "reference_explanation", "source_ids")),
        "all_ranks_match_top_k": all(probes)}
        for arm, benchmark in (("generated", generated), ("original", original)) for item in benchmark.dataset]
    return {"schema_version": "arisekit.cpc-ddx-validity-sanity.v1",
        "execution_sanity": {"passed": all(all(value for key, value in row.items() if key not in {"arm", "case_id"}) for row in checks),
            "cases_checked": len(checks), "checks": checks},
        **prompt_diagnostics(generated, novelty_original if novelty_original is not None else original, presentation_only=True),
        "interpretation": "Top-k arithmetic and prompt separation checks; clinical validity and AI matching correctness require separate assessment"}
