"""A rubric (answer table) and the blinded views of it that models see."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from arisekit.common.hashing import sha256

# Harm tiers, least to most severe.
NEED_SEVERITIES = ("none", "mild", "moderate", "severe")
# Standard decision questions. Every generated rubric starts with follow-up and ends with testing and treatment.
FOLLOW_UP = "What follow-up or triage is appropriate?"
TESTING = "What additional testing is needed?"
TREATMENT = "What additional treatment is needed now?"
PRECAUTIONS = "What specific return precautions are needed, if any?"
NO_PRECAUTIONS = "No specific return precautions are needed."
# The best option text for testing and treatment, which always carry harm none.
STANDARD_BEST = {TESTING: "No additional testing is needed.", TREATMENT: "No additional treatment is needed now."}

# Option fields a model may see: no scores, harms, or tags.
OPTION_FIELDS = {"text", "parts", "timing", "equivalents", "drugClass"}
DECISION_FIELDS = {"id", "kind", "question", "activation"}
ACTIVATION_FIELDS = {"type", "trigger", "scoredNow", "match"}


class Activation(TypedDict, total=False):
    type: str  # always | onlyIf | ...
    rows: list[str]
    match: str
    trigger: str
    scoredNow: bool


class Option(TypedDict, total=False):
    """One recommendation row. Scores, harms, and tags are never shown to models."""
    id: str
    text: str
    score: int
    tags: list[str]
    timing: str
    parts: list[str]
    equivalents: list[str]
    drugClass: str
    harmIfRecommendedOverride: str
    relativeHarmOverride: str
    alsoTakesCareOf: list[str]


class Decision(TypedDict, total=False):
    id: str
    kind: str
    question: str
    activation: Activation
    recommendations: list[Option]
    harmIfNotAddressedOverride: str


class Table(TypedDict):
    """A rubric (answer table): the decisions a good answer makes and the harm of getting them wrong."""
    caseId: str
    harmOverrides: bool
    usualCare: dict[str, str]
    decisions: list[Decision]


@dataclass(frozen=True)
class Rubric:
    table: Table

    @property
    def case_id(self) -> str:
        return self.table["caseId"]

    @property
    def decisions(self) -> list[Decision]:
        return self.table["decisions"]

    def _option_texts(self) -> dict[str, str]:
        return {r["id"]: r["text"] for d in self.decisions for r in d["recommendations"]}

    def _neutral_options(self, decision: Decision) -> list[tuple[str, Option]]:
        """Options relabeled R1..Rn in a hash order, so neither IDs nor order reveal which are appropriate."""
        rows = sorted(decision["recommendations"], key=lambda r: sha256(f"{self.case_id}:{r['id']}"))
        return [(f"R{i}", row) for i, row in enumerate(rows, 1)]

    def _neutral_activation(self, decision: Decision) -> dict[str, Any]:
        """Activation with option IDs replaced by their text, for views that relabel options."""
        activation = decision.get("activation", {"type": "always"})
        out = {k: v for k, v in activation.items() if k in ACTIVATION_FIELDS}
        if activation.get("type") == "onlyIf":
            texts = self._option_texts()
            out["ifRecommended"] = [texts[rid] for rid in activation["rows"]]
        return out

    def neutral_view(self, decisions: list[Decision],
                     fields: set[str]) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
        """What a blinded rater sees: each Decision with options relabeled R1..Rn, keeping only `fields`;
        plus each Decision's label -> option-ID map."""
        view, labels = [], {}
        for d in decisions:
            options = self._neutral_options(d)
            labels[d["id"]] = {label: r["id"] for label, r in options}
            rows = [{"id": label, **{k: v for k, v in r.items() if k in fields}} for label, r in options]
            view.append({"id": d["id"], "question": d["question"], "activation": self._neutral_activation(d),
                         "rows": rows})
        return view, labels

    def for_judge(self) -> dict[str, Any]:
        """Structure with real option IDs, without scores or harms."""
        from pipeline.e2e import text_v2
        if text_v2.is_text_v2(self.table):
            return text_v2.scorer.project_for_judge(self.table)
        return {"caseId": self.case_id, "decisions": [
            {**{k: v for k, v in d.items() if k in DECISION_FIELDS},
             "rows": [{k: v for k, v in r.items() if k == "id" or k in OPTION_FIELDS} for r in d["recommendations"]]}
            for d in self.decisions]}
