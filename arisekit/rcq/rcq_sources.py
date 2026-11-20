"""Deterministic public-evidence spans, selected by ID instead of recopied text."""

from __future__ import annotations

import hashlib
from typing import Mapping, Sequence, Any


def source_catalog(evidence: Mapping[str, str], *, chunk_chars: int = 640, overlap_chars: int = 120) -> dict:
    """Bind short overlapping source windows to raw offsets and content hashes.

    Window sizes bound prompt overhead and retain nearby context. They are not
    clinical relevance or source-quality thresholds; semantic support still
    requires independent assessment.
    """
    if type(chunk_chars) is not int or type(overlap_chars) is not int or not 0 <= overlap_chars < chunk_chars:
        raise ValueError("source window dimensions must allow forward progress")
    catalog = {}
    for source_index, source_id in enumerate(sorted(evidence), 1):
        text = evidence[source_id]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("source evidence must contain text")
        spans, start = [], 0
        source_hash = hashlib.sha256(text.encode()).hexdigest()
        while start < len(text):
            end = min(len(text), start + chunk_chars)
            if end < len(text):
                boundary = max(text.rfind("\n", start + chunk_chars // 2, end),
                               text.rfind(" ", start + chunk_chars // 2, end))
                if boundary > start:
                    end = boundary
            excerpt = text[start:end]
            if excerpt.strip():
                spans.append({"span_id": f"E{source_index:02d}-S{len(spans)+1:04d}",
                    "start": start, "end": end, "text": excerpt,
                    "text_sha256": hashlib.sha256(excerpt.encode()).hexdigest()})
            if end == len(text):
                break
            start = max(start + 1, end - overlap_chars)
        catalog[source_id] = {"source_sha256": source_hash, "spans": spans}
    return catalog


def resolve_support(selections: Sequence[Mapping[str, Any]], evidence: Mapping[str, str], catalog: Mapping[str, Any]) -> list[dict]:
    """Validate selected span identities and recover the exact frozen source text."""
    output = []
    for selection in selections:
        source_id = selection["source_id"]
        if source_id not in catalog or source_id not in evidence:
            raise ValueError("selected source is not in the frozen evidence")
        source = catalog[source_id]
        if hashlib.sha256(evidence[source_id].encode()).hexdigest() != source["source_sha256"]:
            raise ValueError("source changed after indexing")
        span_ids = selection.get("span_ids")
        if not isinstance(span_ids, list) or not span_ids or len(set(span_ids)) != len(span_ids):
            raise ValueError("select distinct nonempty source span IDs")
        if not isinstance(selection.get("supports"), str) or not selection["supports"].strip():
            raise ValueError("explain what the source selection supports")
        known = {s["span_id"]: s for s in source["spans"]}
        for span_id in span_ids:
            if span_id not in known:
                raise ValueError("source span belongs to another source or is unknown")
            span = known[span_id]
            excerpt = evidence[source_id][span["start"]:span["end"]]
            if excerpt != span["text"] or hashlib.sha256(excerpt.encode()).hexdigest() != span["text_sha256"]:
                raise ValueError("indexed source span or offsets changed")
            output.append({"source_id": source_id, "span_id": span_id, "excerpt": excerpt,
                "start": span["start"], "end": span["end"], "source_sha256": source["source_sha256"],
                "supports": selection["supports"]})
    return output
