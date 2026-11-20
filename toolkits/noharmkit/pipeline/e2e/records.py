"""Shapes of the JSON records a project stores. Field names are the on-disk format, so they never change."""
from __future__ import annotations

from typing import Any, TypedDict

from pipeline.backends import CallProvenance


class Provenance(TypedDict, total=False):
    """provenance.json. The app and import may add fields; unknown fields are preserved on update."""
    caseset_name: str
    cases: list[str]
    trials: int
    created_at: str
    updated_at: str
    case_source: str
    description: str
    synthetic: bool
    models: list[str]
    model_labels: dict[str, str]
    judge_scoring_source_commit: str


class _CaseText(TypedDict):
    presentation: str
    recommendations: str


class Case(_CaseText, total=False):
    """cases/<id>.json: task (presentation), solution (recommendations), optional errors."""
    errors: Any


class ItemMetadata(TypedDict):
    """`base_id` is the case whose rubric judges this item: the item ID itself, except for legacy perturbation
    variants, which map to their base case. The other fields are legacy and fixed for new imports."""
    base_id: str
    perturb_id: int | None
    category: str
    candidate_id: str | None
    open: bool


class Item(TypedDict):
    """One items.jsonl row: the task sent to evaluated models."""
    id: str
    prompt: str
    metadata: ItemMetadata


class RunStatus(TypedDict, total=False):
    """answer-tables/<case>.<label>.status.json, written beside each generated or reviewed rubric."""
    status: str
    errors: list[str]
    provenance: CallProvenance
    generation_sha256: str
    table_sha256: str | None


class ResponseRecord(TypedDict, total=False):
    """results/responses/<model>.jsonl: one collected response per case and trial (error instead on failure)."""
    id: str
    trial: int
    model: str
    input_sha256: str
    route: dict[str, Any]
    response: str | None
    runtime: float | None
    usage: dict[str, Any] | None
    error: str
    provider_provenance: CallProvenance
    provider_raw: str


class _JudgeRuntimeBindings(TypedDict, total=False):
    judge_scoring_source_commit: str
    judge_protocol: str
    judge_contract_sha256: str


class JudgmentBindings(_JudgeRuntimeBindings):
    """What a judgment was made against; resume requires a saved receipt to match all of it."""
    caseId: str
    rubric: str
    rubric_sha256: str
    response_sha256: str
    case_presentation_sha256: str


class JudgmentReceipt(JudgmentBindings, total=False):
    """results/judge/<model>.jsonl: one judgment per response, bound to the rubric, response, and task it used."""
    id: str
    trial: int
    status: str
    judge: dict[str, Any] | None
    errors: list[str]
    raw: str | None
    provenance: CallProvenance
