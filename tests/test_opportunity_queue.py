"""The released MAST action queue is imported without collapsing its actions."""

from __future__ import annotations

import hashlib

import pytest

from arisekit.authoring.opportunity import (
    EvidenceAccessClass,
    EvidenceBoundary,
    OpportunityTrack,
    PortfolioActionKind,
    PortfolioActionQueue,
    load_portfolio_action_queue,
)


def _hash(value: bytes | str) -> str:
    payload = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _queue_bytes() -> bytes:
    return (
        "action,target,rationale,utility,cost\n"
        "harden_items,donoharm,Add frontier-matched items,1.0,high\n"
        "new_benchmark,calibration,Under-measured construct,0.75,very high\n"
        "cell_fill,scin,Run the missing model panel,0.5,low\n"
        "persist_items,cpcbench-ddx,Persist per-item outcomes,0.4,medium\n"
        "label_collect,benchmark-x,Collect absent labels,0.3,medium\n"
    ).encode("utf-8")


def _boundary(payload: bytes) -> EvidenceBoundary:
    return EvidenceBoundary(
        access_class=EvidenceAccessClass.PUBLIC,
        released_artifact_hash=_hash(payload),
        reviewed_by="portfolio-data-owner",
        reviewed_at="2026-07-22T12:00:00Z",
    )


def test_queue_import_preserves_ranked_source_fields_and_derives_routes(tmp_path):
    payload = _queue_bytes()
    source = tmp_path / "queue.csv"
    source.write_bytes(payload)

    queue = load_portfolio_action_queue(
        source,
        expected_sha256=_hash(payload),
        analysis_code_hash=_hash("analysis-code"),
        source_revision="mast-geometry-commit-abc123",
        evidence_boundary=_boundary(payload),
        source_artifact="analysis/benchmark_geometry/output/data_collection_queue.csv",
    )

    assert [action.rank for action in queue.actions] == [1, 2, 3, 4, 5]
    assert queue.actions[0].action is PortfolioActionKind.HARDEN_ITEMS
    assert queue.actions[0].rationale == "Add frontier-matched items"
    assert queue.actions[0].utility == 1.0
    assert queue.actions[0].cost == "high"
    assert [
        action.action for action in queue.by_track(OpportunityTrack.BENCHMARK_DESIGN)
    ] == [PortfolioActionKind.NEW_BENCHMARK]
    assert [
        action.action
        for action in queue.by_track(OpportunityTrack.PORTFOLIO_MAINTENANCE)
    ] == [PortfolioActionKind.HARDEN_ITEMS]
    assert [
        action.action for action in queue.by_track(OpportunityTrack.RESULT_COLLECTION)
    ] == [
        PortfolioActionKind.CELL_FILL,
        PortfolioActionKind.PERSIST_ITEMS,
        PortfolioActionKind.LABEL_COLLECT,
    ]

    restored = PortfolioActionQueue.from_dict(queue.to_dict())
    assert restored.to_dict() == queue.to_dict()
    assert restored.digest == queue.digest


def test_queue_import_rejects_untrusted_or_changed_source_bytes(tmp_path):
    payload = _queue_bytes()
    source = tmp_path / "queue.csv"
    source.write_bytes(payload)

    with pytest.raises(ValueError, match="expected_sha256"):
        load_portfolio_action_queue(
            source,
            expected_sha256=_hash("different"),
            analysis_code_hash=_hash("analysis-code"),
            source_revision="revision",
            evidence_boundary=_boundary(payload),
        )

    changed = payload.replace(b"cell_fill", b"unknown_action")
    source.write_bytes(changed)
    with pytest.raises(ValueError, match="not a valid PortfolioActionKind"):
        load_portfolio_action_queue(
            source,
            expected_sha256=_hash(changed),
            analysis_code_hash=_hash("analysis-code"),
            source_revision="revision",
            evidence_boundary=_boundary(changed),
        )


def test_queue_serialization_rejects_a_forged_route(tmp_path):
    payload = _queue_bytes()
    source = tmp_path / "queue.csv"
    source.write_bytes(payload)
    queue = load_portfolio_action_queue(
        source,
        expected_sha256=_hash(payload),
        analysis_code_hash=_hash("analysis-code"),
        source_revision="revision",
        evidence_boundary=_boundary(payload),
    )
    serialized = queue.to_dict()
    serialized["actions"][0]["track"] = "benchmark-design"

    with pytest.raises(ValueError, match="track"):
        PortfolioActionQueue.from_dict(serialized)
