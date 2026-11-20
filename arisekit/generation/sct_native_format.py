"""Apply a source-verified native SCT prompt without changing clinical content."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re

from arisekit.benchmark import Benchmark
from arisekit.dataset import Dataset
from arisekit.common.frozen_records import read_record, write_record
from arisekit.common.jsonio import canonical_json as canonical
from arisekit.package import BenchmarkManifest, write_package
from arisekit.scorer import BaseScorer
from arisekit.generation.specialty_adapters import SCTConcordanceScorer, _native_sct_rating
from arisekit.types import BenchmarkItem, Metric

FIELDS = {"scenario", "hypothesis", "new_evidence"}


def validate_profile(profile):
    if (not isinstance(profile, dict) or profile.get("schema_version") != "arisekit.native-sct-prompt.v1"
        or not isinstance(profile.get("segments"), list) or len(profile["segments"]) != 4
        or any(not isinstance(v, str) for v in profile["segments"])
        or not isinstance(profile.get("field_order"), list) or len(profile["field_order"]) != 3
        or set(profile["field_order"]) != FIELDS
        or not isinstance(profile.get("source_assets_sha256"), dict)
        or set(profile["source_assets_sha256"]) != {"score.py", "data_loader.py", "templates/guideline.md", "templates/testcase.md"}
        or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in profile["source_assets_sha256"].values())
        or type(profile.get("source_prompt_parity_checks")) is not int or profile["source_prompt_parity_checks"] < 1):
        raise ValueError("Use a complete source-verified native SCT prompt profile")
    return profile


def render(fields, profile):
    validate_profile(profile)
    if set(fields) != FIELDS or any(not isinstance(v, str) or not v.strip() for v in fields.values()):
        raise ValueError("Preserve all three complete SCT clinical fields")
    return "".join(profile["segments"][i] + fields[key] for i, key in enumerate(profile["field_order"])) + profile["segments"][-1]


class NativePublishedSCTScorer(BaseScorer):
    rescore_safe = True

    def configuration(self):
        return {"kind": "published-sct-native-concordance", "normalization": "weight-divided-by-modal-weight",
            "parser": "last-Rating-marker-first-signed-012-in-next-ten-characters",
            "missing_policy": "exclude-execution-errors-and-truncation-report-separately"}

    def score_item(self, item, responses):
        weights = item.ground_truth["published_weights"]
        values = {k: [] for k in ("published_concordance", "invalid_response_rate", "execution_error_rate", "strict_format_rate", "truncated_response_rate")}
        for response in responses:
            failed = response.error is not None
            truncated = response.metadata.get("finish_reason") == "length"
            values["execution_error_rate"].append(float(failed))
            values["truncated_response_rate"].append(float(truncated))
            if failed or truncated:
                continue
            answer = _native_sct_rating(response.response)
            values["published_concordance"].append(weights[int(answer)+2]/max(weights) if answer is not None else 0.)
            values["invalid_response_rate"].append(float(answer is None))
            values["strict_format_rate"].append(float(isinstance(response.response, str) and bool(re.fullmatch(r"Rating:\s*[+-]?[012]", response.response.strip()))))
        return [Metric(name=k, value=sum(v)/len(v), n=len(v), category="original") for k, v in values.items() if v]


def convert(benchmark, profile):
    validate_profile(profile)
    digest = hashlib.sha256(canonical(profile).encode()).hexdigest()
    items = []
    for original in benchmark.dataset:
        item = BenchmarkItem.from_dict(original.to_dict())
        item.prompt = render(item.metadata.get("sct_fields", {}), profile)
        item.metadata.update(native_prompt=True, native_prompt_profile_sha256=digest)
        items.append(item)
    published = ["published_weights" in r.ground_truth for r in items]
    if not items or any(published) and not all(published):
        raise ValueError("Keep published and synthetic SCT reference arms separate")
    return Benchmark(name=benchmark.name, dataset=Dataset(items),
        scorer=NativePublishedSCTScorer() if all(published) else SCTConcordanceScorer(response_format="mast-native-rating"),
        runner_config=benchmark.runner_config)


def prepare_evaluation(root, generated_path, original, profile):
    root, generated_path = Path(root), Path(generated_path)
    generated = convert(Benchmark.from_package(generated_path), profile)
    original = convert(original, profile)
    manifest = BenchmarkManifest.from_dict(json.loads((generated_path / "benchmark.json").read_text()))
    items = [r.to_dict() for r in generated.dataset]
    binding = {"source_manifest_sha256": hashlib.sha256(canonical(manifest.to_dict()).encode()).hexdigest(),
        "native_profile_sha256": hashlib.sha256(canonical(profile).encode()).hexdigest(),
        "evaluated_items_sha256": hashlib.sha256(canonical(items).encode()).hexdigest()}
    destination = root / "native-evaluation/candidate"
    if not destination.exists():
        native_manifest = replace(manifest, scorer=dict(generated.scorer.configuration()),
            provenance={**manifest.provenance, "native_sct_prompt_profile": profile, "source_package_binding": binding})
        write_package(destination, manifest=native_manifest, items=generated.dataset,
            readme="Native SCT prompts and modal-normalized AI uncertainty references. Counts are numerical units, not observed expert votes.\n")
    write_record(destination.parent / "binding.json", binding)
    packaged = Benchmark.from_package(destination)
    if [r.to_dict() for r in packaged.dataset] != items:
        raise ValueError("The evaluated native SCT package changed")
    write_record(destination.parent / "original.json", {"items": [r.to_dict() for r in original.dataset]})
    return packaged, original, destination
