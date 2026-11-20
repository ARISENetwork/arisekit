"""Compile generated SCT and CPC candidates into deterministic text benchmarks.

Generation contracts request synthetic references. Expert references require an
explicit import choice and supplied rating/review records; the adapter verifies
their structure and bindings, not the identity or expertise of their authors.
CPC scores diagnosis ranking only. Its separate evidence-stage categories avoid
pooling cumulative observations as independent cases in Benchmark aggregation.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping
from typing import Any

from arisekit.benchmark import Benchmark
from arisekit.common.hashing import canonical_sha256 as _digest
from arisekit.common.jsonio import strict_json_loads
from arisekit.dataset import Dataset
from arisekit.scorer import BaseScorer
from arisekit.types import BenchmarkItem, Metric, RunResult


SPECIALTY_CANDIDATE_SCHEMA = "arisekit.specialty-candidate.v1"
_SCT_REFERENCE_SCHEMA = "arisekit.sct-reference.v1"
_CPC_REFERENCE_SCHEMA = "arisekit.cpc-reference.v1"
_ORDINALS = ("-2", "-1", "0", "1", "2")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_ENVELOPE_FIELDS = {"schema_version", "kind", "name", "specialty", "reference_origin"}


def _object(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{label} must contain exactly {sorted(fields)}")
    return value


# Candidate compile errors are sent back to the model in repair prompts, so _text and _identifier keep their
# original wording rather than the shared validators'.
def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(f"{label} must be an identifier using letters, digits, '.', '_' or '-'")
    return value


def _list(value: Any, label: str, *, nonempty: bool = True) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{label} must be {'a nonempty' if nonempty else 'a'} list")
    return value


def _origin(value: Any) -> str:
    if value not in ("synthetic", "expert"):
        raise ValueError("reference_origin must be synthetic or expert")
    return value


def _envelope(payload: Any, kind: str, allow_expert_references: bool) -> Mapping[str, Any]:
    if not isinstance(allow_expert_references, bool):
        raise ValueError("allow_expert_references must be boolean")
    fields = _ENVELOPE_FIELDS | ({"items"} if kind == "sct" else {"diagnoses", "cases"})
    value = _object(payload, fields, "candidate")
    if value["schema_version"] != SPECIALTY_CANDIDATE_SCHEMA or value["kind"] != kind:
        raise ValueError(f"candidate must use {SPECIALTY_CANDIDATE_SCHEMA} and kind {kind}")
    _identifier(value["name"], "name")
    _text(value["specialty"], "specialty")
    origin = _origin(value["reference_origin"])
    if origin == "expert" and not allow_expert_references:
        raise ValueError("expert references require allow_expert_references=True and supplied evidence")
    return value


def _sct_reference(reference: Any) -> Mapping[str, Any]:
    value = _object(reference, {"schema_version", "reference_origin", "reference_counts",
                                "expert_ratings"}, "SCT reference")
    if value["schema_version"] != _SCT_REFERENCE_SCHEMA:
        raise ValueError("unsupported SCT reference schema")
    origin = _origin(value["reference_origin"])
    counts = _object(value["reference_counts"], set(_ORDINALS), "reference_counts")
    if any(type(count) is not int or count < 0 for count in counts.values()) or not sum(counts.values()):
        raise ValueError("reference_counts must be nonnegative integer counts with a positive total")
    ratings = _list(value["expert_ratings"], "expert_ratings", nonempty=origin == "expert")
    if origin == "synthetic" and ratings:
        raise ValueError("synthetic references cannot carry expert_ratings")
    observed: Counter[str] = Counter()
    reviewers: set[str] = set()
    for rating in ratings:
        rating = _object(rating, {"reviewer_id", "rating", "evidence_ref"}, "expert rating")
        reviewer = _identifier(rating["reviewer_id"], "reviewer_id")
        if reviewer in reviewers:
            raise ValueError("expert_ratings contains a duplicate reviewer")
        reviewers.add(reviewer)
        score = rating["rating"]
        if type(score) is not int or str(score) not in _ORDINALS:
            raise ValueError("expert rating must be an integer from -2 to 2")
        _text(rating["evidence_ref"], "expert rating evidence_ref")
        observed[str(score)] += 1
    if origin == "expert" and any(observed[key] != counts[key] for key in _ORDINALS):
        raise ValueError("reference_counts do not match the supplied expert_ratings")
    return value


def normalize_diagnosis(value: str) -> str:
    """Normalize case, Unicode width and whitespace without erasing clinical words."""
    return " ".join(unicodedata.normalize("NFKC", _text(value, "diagnosis")).casefold().split())


def _diagnosis_index(diagnoses: Any) -> dict[str, str]:
    index: dict[str, str] = {}
    ids: set[str] = set()
    for diagnosis in _list(diagnoses, "diagnoses"):
        diagnosis = _object(diagnosis, {"id", "label", "aliases"}, "diagnosis")
        identity = _identifier(diagnosis["id"], "diagnosis.id")
        if identity in ids:
            raise ValueError("duplicate diagnosis id")
        ids.add(identity)
        labels = [identity, _text(diagnosis["label"], "diagnosis.label")]
        labels.extend(_list(diagnosis["aliases"], "diagnosis.aliases", nonempty=False))
        for label in labels:
            normalized = normalize_diagnosis(label)
            if normalized in index and index[normalized] != identity:
                raise ValueError(f"ambiguous diagnosis label or alias: {label!r}")
            index[normalized] = identity
    return index


def _expert_reviews(reviews: Any, origin: str, diagnosis_id: str) -> None:
    rows = _list(reviews, "expert_reviews", nonempty=origin == "expert")
    if origin == "synthetic" and rows:
        raise ValueError("synthetic references cannot carry expert_reviews")
    seen: set[str] = set()
    for row in rows:
        row = _object(row, {"reviewer_id", "diagnosis_id", "evidence_ref"}, "expert review")
        reviewer = _identifier(row["reviewer_id"], "reviewer_id")
        if reviewer in seen:
            raise ValueError("duplicate expert reviewer")
        seen.add(reviewer)
        if row["diagnosis_id"] != diagnosis_id:
            raise ValueError("expert review does not support the declared final diagnosis")
        _text(row["evidence_ref"], "expert review evidence_ref")


def _differential(value: Any, diagnosis_ids: set[str], evidence_ids: list[str]) -> None:
    seen: set[str] = set()
    for row in _list(value, "reference_differential"):
        row = _object(row, {"diagnosis_id", "evidence_ids"}, "differential reference")
        diagnosis = _identifier(row["diagnosis_id"], "reference diagnosis_id")
        if diagnosis not in diagnosis_ids or diagnosis in seen:
            raise ValueError("reference differential has unknown or duplicate diagnoses")
        seen.add(diagnosis)
        links = _list(row["evidence_ids"], "evidence_ids")
        if any(not isinstance(link, str) or link not in evidence_ids for link in links):
            raise ValueError("reference differential links to unknown or future evidence")
        if len(set(links)) != len(links):
            raise ValueError("duplicate differential evidence link")


def _cpc_reference(reference: Any) -> tuple[Mapping[str, Any], dict[str, str]]:
    value = _object(reference, {"schema_version", "reference_origin", "diagnoses",
                                "final_diagnosis_id", "expert_reviews", "reference_differential",
                                "disclosed_evidence_ids"}, "CPC reference")
    if value["schema_version"] != _CPC_REFERENCE_SCHEMA:
        raise ValueError("unsupported CPC reference schema")
    origin = _origin(value["reference_origin"])
    index = _diagnosis_index(value["diagnoses"])
    diagnosis_id = _identifier(value["final_diagnosis_id"], "final_diagnosis_id")
    if diagnosis_id not in set(index.values()):
        raise ValueError("final diagnosis is not in the diagnosis vocabulary")
    _expert_reviews(value["expert_reviews"], origin, diagnosis_id)
    evidence_ids = _list(value["disclosed_evidence_ids"], "disclosed_evidence_ids")
    if any(not isinstance(identity, str) for identity in evidence_ids):
        raise ValueError("disclosed evidence identifiers must be strings")
    if len(set(evidence_ids)) != len(evidence_ids) or evidence_ids[0] != "presentation":
        raise ValueError("disclosed evidence must start with presentation and have unique identifiers")
    _differential(value["reference_differential"], set(index.values()), evidence_ids)
    return value, index


def _item(identity: str, prompt: str, metadata: dict[str, Any], reference: Mapping[str, Any]) -> BenchmarkItem:
    detached = json.loads(json.dumps(reference, allow_nan=False))
    metadata["reference_sha256"] = _digest(detached)
    return BenchmarkItem(id=identity, prompt=prompt, metadata=metadata, ground_truth=detached)


def sct_prompt(scenario: str, hypothesis: str, new_evidence: str) -> str:
    return (
        f"Scenario:\n{_text(scenario, 'scenario')}\n\n"
        f"Hypothesis or proposed action:\n{_text(hypothesis, 'hypothesis')}\n\n"
        f"New evidence:\n{_text(new_evidence, 'new_evidence')}\n\n"
        "How does the new evidence change support for the hypothesis or action?\n"
        "-2: much less support; -1: less support; 0: unchanged; "
        "+1: more support; +2: much more support.\n"
        "Return only one integer from -2 to +2, without explanation."
    )


def compile_sct_items(payload: Mapping[str, Any], *, allow_expert_references: bool = False) -> list[BenchmarkItem]:
    """Compile count-based SCT references, with modal-normalized partial credit."""
    value = _envelope(payload, "sct", allow_expert_references)
    items: list[BenchmarkItem] = []
    seen: set[str] = set()
    candidate_hash = _digest(value)
    for row in _list(value["items"], "items"):
        row = _object(row, {"id", "scenario", "hypothesis", "new_evidence", "reference_counts",
                            "expert_ratings"}, "SCT item")
        identity = _identifier(row["id"], "item.id")
        if identity in seen:
            raise ValueError("duplicate SCT item id")
        seen.add(identity)
        reference = _sct_reference({"schema_version": _SCT_REFERENCE_SCHEMA,
                                    "reference_origin": value["reference_origin"],
                                    "reference_counts": row["reference_counts"],
                                    "expert_ratings": row["expert_ratings"]})
        prompt = sct_prompt(row["scenario"], row["hypothesis"], row["new_evidence"])
        items.append(_item(identity, prompt, {
            "kind": "sct", "specialty": value["specialty"], "category": value["specialty"],
            "reference_origin": value["reference_origin"], "candidate_sha256": candidate_hash,
            "independent_unit": "scenario", "scenario_id": identity,
            "sct_fields": {key: row[key] for key in ("scenario", "hypothesis", "new_evidence")},
        }, reference))
    return items


def compile_cpc_items(payload: Mapping[str, Any], *, allow_expert_references: bool = False) -> list[BenchmarkItem]:
    """Compile cumulative evidence stages; only disclosed evidence reaches prompts.

    Each stage is a separate single-turn item. Diagnosis rank is assessed against
    the case's final diagnosis. Reference differentials and evidence links remain
    retained scorer-side material; no reasoning-quality score is fabricated.
    """
    value = _envelope(payload, "cpc", allow_expert_references)
    index = _diagnosis_index(value["diagnoses"])
    items: list[BenchmarkItem] = []
    cases: set[str] = set()
    candidate_hash = _digest(value)
    for case in _list(value["cases"], "cases"):
        case = _object(case, {"id", "presentation", "final_diagnosis_id", "expert_reviews", "stages"}, "CPC case")
        identity = _identifier(case["id"], "case.id")
        if identity in cases:
            raise ValueError("duplicate CPC case id")
        cases.add(identity)
        diagnosis_id = _identifier(case["final_diagnosis_id"], "final_diagnosis_id")
        if diagnosis_id not in set(index.values()):
            raise ValueError("final diagnosis is not in the diagnosis vocabulary")
        _expert_reviews(case["expert_reviews"], value["reference_origin"], diagnosis_id)
        evidence_ids = ["presentation"]
        evidence = [f"Presentation:\n{_text(case['presentation'], 'presentation')}"]
        for position, stage in enumerate(_list(case["stages"], "stages"), 1):
            stage = _object(stage, {"id", "evidence", "reference_differential"}, "evidence stage")
            stage_id = _identifier(stage["id"], "stage.id")
            if stage_id in evidence_ids:
                raise ValueError("duplicate or reserved evidence stage id")
            evidence_ids.append(stage_id)
            evidence.append(f"Evidence stage {position}:\n{_text(stage['evidence'], 'stage.evidence')}")
            reference, _ = _cpc_reference({
                "schema_version": _CPC_REFERENCE_SCHEMA, "reference_origin": value["reference_origin"],
                "diagnoses": value["diagnoses"], "final_diagnosis_id": diagnosis_id,
                "expert_reviews": case["expert_reviews"], "reference_differential": stage["reference_differential"],
                "disclosed_evidence_ids": list(evidence_ids),
            })
            prompt = "\n\n".join(evidence) + (
                '\n\nReturn a ranked differential as a JSON object with exactly one key, '
                '"diagnoses", containing 1 to 10 distinct diagnosis names, most likely first. '
                'Return no explanation or Markdown.'
            )
            items.append(_item(f"{identity}::{stage_id}", prompt, {
                "kind": "cpc", "specialty": value["specialty"],
                "category": f"{value['specialty']}/stage-{position}",
                "reference_origin": value["reference_origin"], "candidate_sha256": candidate_hash,
                "independent_unit": "case", "case_id": identity, "stage_id": stage_id,
                "stage_index": position, "disclosed_evidence_ids": list(evidence_ids),
                "previous_item_id": None if position == 1 else f"{identity}::{evidence_ids[-2]}",
            }, reference))
    return items


def _scoring_context(item: BenchmarkItem, responses: list[RunResult], reference: Mapping[str, Any]) -> tuple[str, str]:
    origin = reference["reference_origin"]
    if item.metadata.get("reference_origin") != origin:
        raise ValueError("item metadata and reference origin differ")
    if item.metadata.get("reference_sha256") != _digest(reference):
        raise ValueError("item reference differs from its compiled binding")
    category = _text(item.metadata.get("category", "overall"), "metric category")
    trials: set[int] = set()
    for response in responses:
        if response.id != item.id or type(response.trial) is not int or response.trial < 0:
            raise ValueError("response item/trial identity does not match the scored item")
        if response.trial in trials:
            raise ValueError("duplicate response trial")
        trials.add(response.trial)
    return origin, category


def _metrics(values: Mapping[str, list[float]], category: str) -> list[Metric]:
    return [Metric(name, sum(rows) / len(rows) if rows else 0.0, category=category, n=len(rows))
            for name, rows in values.items()]


class SCTConcordanceScorer(BaseScorer):
    """Modal-normalized SCT credit with an explicit response and missing-data policy."""

    rescore_safe = True

    def __init__(self, *, response_format: str = "ordinal-only", unparseable_policy: str = "zero"):
        if response_format not in {"ordinal-only", "mast-native-rating"}:
            raise ValueError("Unsupported SCT response format")
        if unparseable_policy not in {"zero", "skip"}:
            raise ValueError("Unsupported SCT unparseable response policy")
        if unparseable_policy == "skip" and response_format != "mast-native-rating":
            raise ValueError("SCT skip policy requires mast-native-rating response format")
        self.response_format = response_format
        self.unparseable_policy = unparseable_policy

    def configuration(self) -> Mapping[str, Any]:
        result = {"kind": "sct-concordance", "reference_schema": _SCT_REFERENCE_SCHEMA,
                "normalization": "count-divided-by-modal-count", "response_format": self.response_format}
        if self.response_format == "mast-native-rating":
            result.update(parser="last-Rating-marker-first-signed-012-in-next-ten-characters",
                          missing_policy="exclude-execution-errors-and-truncation-report-separately")
            if self.unparseable_policy == "skip":
                result.update(unparseable_policy="skip",
                              missing_policy="exclude-execution-errors-truncation-and-unparseable-report-separately")
        return result

    def score_item(self, item: BenchmarkItem, responses: list[RunResult]) -> list[Metric]:
        reference = _sct_reference(item.ground_truth)
        origin, category = _scoring_context(item, responses, reference)
        counts = reference["reference_counts"]
        modal = max(counts.values())
        values: dict[str, list[float]] = {f"{origin}_concordance": [], "invalid_response_rate": [],
                                       "execution_error_rate": []}
        native = self.response_format == "mast-native-rating"
        if native:
            values.update(strict_format_rate=[], truncated_response_rate=[])
        for response in responses:
            text = response.response.strip() if isinstance(response.response, str) else None
            error = response.error is not None
            values["execution_error_rate"].append(float(error))
            if native:
                truncated = response.metadata.get("finish_reason") == "length"
                values["truncated_response_rate"].append(float(truncated))
                # Native study comparisons treat transport loss as missing, not a wrong clinical answer.
                if error or truncated:
                    continue
                answer = _native_sct_rating(text)
                values["strict_format_rate"].append(float(bool(text and re.fullmatch(r"Rating:\s*[+-]?[012]", text))))
                if answer is None and self.unparseable_policy == "skip":
                    values["invalid_response_rate"].append(1.0)
                    continue
            else:
                answer = text.removeprefix("+") if text in (*_ORDINALS, "+1", "+2") else None
            values[f"{origin}_concordance"].append(counts[answer] / modal if answer is not None and not error else 0.0)
            values["invalid_response_rate"].append(float(not error and answer is None))
        if native and self.unparseable_policy == "skip":
            # The shared aggregator averages emitted metrics regardless of n.
            values = {name: rows for name, rows in values.items() if rows}
        return _metrics(values, category)


def _native_sct_rating(text: str | None) -> str | None:
    if not isinstance(text, str) or "Rating:" not in text:
        return None
    # Preserve the original parser's permissiveness, including Rating:10 -> 1.
    section = text[text.rfind("Rating:") + len("Rating:"):][:10]
    match = re.search(r"[+-]?[012]", section)
    return str(int(match.group())) if match else None


def _ranked_diagnoses(response: Any, index: dict[str, str], maximum: int) -> list[str]:
    value = strict_json_loads(response, "response", allow_nan=True)
    value = _object(value, {"diagnoses"}, "ranked differential response")
    labels = _list(value["diagnoses"], "response diagnoses")
    if len(labels) > maximum:
        raise ValueError("response exceeds maximum differential length")
    diagnoses: list[str] = []
    seen: set[tuple[str, str]] = set()
    for label in labels:
        normalized = normalize_diagnosis(label)
        identity = index.get(normalized)
        key = ("known", identity) if identity is not None else ("unknown", normalized)
        if key in seen:
            raise ValueError("response repeats a diagnosis or its alias")
        seen.add(key)
        diagnoses.append(identity if identity is not None else "")
    return diagnoses


class CPCRankedDifferentialScorer(BaseScorer):
    """Exact vocabulary/alias matching, reciprocal rank and top-k accuracy."""

    rescore_safe = True

    def __init__(self, *, top_k: tuple[int, ...] = (1, 3, 10), max_diagnoses: int = 10):
        if type(max_diagnoses) is not int or max_diagnoses < 1:
            raise ValueError("max_diagnoses must be a positive integer")
        if (not isinstance(top_k, tuple) or not top_k
                or any(type(k) is not int or not 1 <= k <= max_diagnoses for k in top_k)
                or tuple(sorted(set(top_k))) != top_k):
            raise ValueError("top_k must be increasing distinct positive integers no greater than max_diagnoses")
        self.top_k = top_k
        self.max_diagnoses = max_diagnoses

    def configuration(self) -> Mapping[str, Any]:
        return {"kind": "cpc-ranked-differential", "reference_schema": _CPC_REFERENCE_SCHEMA,
                "top_k": list(self.top_k), "max_diagnoses": self.max_diagnoses,
                "normalization": "nfkc-casefold-whitespace-exact-alias", "ranking": "reciprocal-rank"}

    def score_item(self, item: BenchmarkItem, responses: list[RunResult]) -> list[Metric]:
        reference, index = _cpc_reference(item.ground_truth)
        origin, category = _scoring_context(item, responses, reference)
        values: dict[str, list[float]] = {f"{origin}_reciprocal_rank": []}
        values.update({f"{origin}_ddx_at_{k}": [] for k in self.top_k})
        values.update({"invalid_response_rate": [], "execution_error_rate": []})
        for response in responses:
            error = response.error is not None
            invalid = False
            rank = 0
            if not error:
                try:
                    diagnoses = _ranked_diagnoses(response.response, index, self.max_diagnoses)
                except (ValueError, TypeError, RecursionError):
                    invalid = True
                else:
                    if reference["final_diagnosis_id"] in diagnoses:
                        rank = diagnoses.index(reference["final_diagnosis_id"]) + 1
            values[f"{origin}_reciprocal_rank"].append(1.0 / rank if rank else 0.0)
            for k in self.top_k:
                values[f"{origin}_ddx_at_{k}"].append(float(0 < rank <= k))
            values["invalid_response_rate"].append(float(invalid))
            values["execution_error_rate"].append(float(error))
        return _metrics(values, category)


def specialty_scorer_from_spec(spec: Mapping[str, Any]) -> BaseScorer:
    """Restore a package scorer only when its complete semantics match this adapter."""
    if not isinstance(spec, Mapping):
        raise ValueError("specialty scorer specification must be an object")
    if spec.get("kind") == "sct-concordance":
        scorer: BaseScorer = SCTConcordanceScorer(response_format=spec.get("response_format", "ordinal-only"),
            unparseable_policy=spec.get("unparseable_policy", "zero"))
    elif spec.get("kind") == "cpc-ranked-differential":
        top_k = spec.get("top_k")
        if not isinstance(top_k, list):
            raise ValueError("CPC scorer top_k must be a JSON list")
        scorer = CPCRankedDifferentialScorer(top_k=tuple(top_k), max_diagnoses=spec.get("max_diagnoses"))
    else:
        raise ValueError("unsupported specialty scorer kind")
    if dict(spec) != scorer.configuration():
        raise ValueError("specialty scorer specification changes canonical scoring semantics")
    return scorer


def build_specialty_benchmark(payload: Mapping[str, Any], *, allow_expert_references: bool = False) -> Benchmark:
    """Build a text Benchmark without provider calls or generated executable code."""
    if not isinstance(payload, Mapping) or payload.get("kind") not in ("sct", "cpc"):
        raise ValueError("candidate kind must be sct or cpc")
    if payload["kind"] == "sct":
        items = compile_sct_items(payload, allow_expert_references=allow_expert_references)
        scorer: BaseScorer = SCTConcordanceScorer()
    else:
        items = compile_cpc_items(payload, allow_expert_references=allow_expert_references)
        scorer = CPCRankedDifferentialScorer()
    return Benchmark(name=payload["name"], dataset=Dataset.from_items(items, name=payload["name"]), scorer=scorer)


def _schema_object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def specialty_generation_contract(kind: str) -> dict[str, Any]:
    """Return data-only instructions and a JSON Schema for synthetic generation."""
    if kind not in ("sct", "cpc"):
        raise ValueError("generation kind must be sct or cpc")
    text = {"type": "string", "minLength": 1}
    identity = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"}
    empty = {"type": "array", "items": {"type": "string"}, "maxItems": 0}
    properties: dict[str, Any] = {
        "schema_version": {"const": SPECIALTY_CANDIDATE_SCHEMA}, "kind": {"const": kind},
        "name": identity, "specialty": text, "reference_origin": {"const": "synthetic"},
    }
    if kind == "sct":
        properties["items"] = {"type": "array", "minItems": 1, "items": _schema_object({
            "id": identity, "scenario": text, "hypothesis": text, "new_evidence": text,
            "reference_counts": _schema_object({key: {"type": "integer", "minimum": 0} for key in _ORDINALS}),
            "expert_ratings": empty,
        })}
        instructions = [
            "Generate original specialty-specific scenarios about decisions under clinical uncertainty.",
            "The base scenario must support at least two clinically plausible diagnoses or management options. "
            "Include the relevant context that makes those alternatives credible, rather than naming an obvious answer and adding irrelevant distractors.",
            "Each item has a scenario, a hypothesis or proposed action, and new evidence whose effect can strengthen, weaken, or leave support unchanged.",
            "Make the scenario necessary for interpreting the new finding: use conditional clinical mechanisms, test limitations, "
            "competing risks or patient priorities when relevant. Do not reduce most questions to a context-free disease association, "
            "a single cutoff or a confirmatory test result. Some findings can legitimately give a clear update.",
            "Include clinically justified neutral effects and modest contextual shifts as well as some strong updates; do not make every finding decisive or force rating quotas.",
            "Provide a synthetic distribution of ordinal ratings using integer counts for every value from -2 to 2 and a positive total.",
            "These counts are proposed synthetic references, not observed expert judgments. expert_ratings must be empty.",
            "Do not put the intended rating, reference counts, or reference rationale in solver-facing scenario, hypothesis, or evidence text.",
            "Recompute any named clinical risk score from the disclosed components before stating its total. "
            "For CRB65, confusion, respiratory rate at least 30/min, systolic blood pressure below 90 mmHg "
            "or diastolic at most 60 mmHg, and age at least 65 years each contribute one point; "
            "the blood-pressure criterion contributes only one point even when both measurements qualify. "
            "Disclose the components used, or omit an unnecessary computed score. "
            "A risk score alone does not replace clinical judgment about the proposed action.",
        ]
    else:
        differential = _schema_object({"diagnosis_id": identity,
                                       "evidence_ids": {"type": "array", "minItems": 1, "uniqueItems": True, "items": identity}})
        properties["diagnoses"] = {"type": "array", "minItems": 1, "items": _schema_object({
            "id": identity, "label": text, "aliases": {"type": "array", "items": text},
        })}
        properties["cases"] = {"type": "array", "minItems": 1, "items": _schema_object({
            "id": identity, "presentation": text, "final_diagnosis_id": identity, "expert_reviews": empty,
            "stages": {"type": "array", "minItems": 1, "items": _schema_object({
                "id": identity, "evidence": text,
                "reference_differential": {"type": "array", "minItems": 1, "items": differential},
            })},
        })}
        instructions = [
            "Generate original specialty-specific diagnostic cases with cumulative evidence in chronological order.",
            "Supply a diagnosis vocabulary with unique identifiers, precise labels and only genuinely equivalent aliases; aliases cannot name two diagnoses.",
            "Each final_diagnosis_id and differential diagnosis_id must name that vocabulary.",
            "Evidence links use presentation or current/earlier stage IDs in the same case. Never refer to future evidence; presentation is a reserved stage ID.",
            "Keep the final diagnosis and reference differential outside solver-facing text. Do not insert answer cues or report undisclosed future results.",
            "The references are synthetic. expert_reviews must be empty. Ranking is evaluated against the final diagnosis separately at each stage; reasoning quality is not scored.",
        ]
    return {"kind": kind, "schema_version": SPECIALTY_CANDIDATE_SCHEMA,
            "instructions": instructions + ["Return only the schema-conforming JSON object; do not fabricate expert review, approval, or observed study results."],
            "response_schema": _schema_object(properties)}
