"""Continuation copies immutable API test evidence into an unused UI project."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from cases import each_case

from arisekit.common.hashing import sha256
from tools import continue_api_test as continuation


def put(root: Path, relative: str, payload: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def fresh(root: Path, **fields: Any) -> None:
    root.mkdir()
    (root / "cases").mkdir()
    put(root, "items.jsonl", b"")
    put(root, "provenance.json", json.dumps({"caseset_name": root.name, "cases": [], "trials": 1,
                                           "execution_mode": "api", "created_at": "target-created",
                                           **fields}).encode())


def make_projects(root: Path) -> tuple[Path, Path]:
    root.mkdir(exist_ok=True)
    source, target = root / "original", root / "continuation"
    fresh(source, cases=["Case001"], models=["test/model"], trials=2, created_at="source-created",
          inference={"binding_version": 2}, synthetic=True)
    fresh(target)
    for relative, payload in {
        "items.jsonl": '{"id":"Case001","prompt":"café"}\r\n'.encode(),
        "api-pipeline.json": b'{ "version": 2 }\n',
        "cases/Case001.json": b'{"presentation":"task","recommendations":"solution"}',
        "imports/supplied.json": b"original import bytes\r\n",
        "answer-tables/Case001.run1.json": b'{"format":"noharm-rubric-text-v2"}',
        "results/responses/test-model.jsonl": b'{"response":"saved"}\n',
        "results/judge/test-model.jsonl": b'{"status":"failed","raw":"retained"}\n',
        "results/test-model_scored.jsonl": b'{"scorer":"S2"}\n',
        "results/report.md": b"previous report",
        "web-execution/latest.json": b'{"status":"failed"}',
        "web-execution/generate-one.json": b'{"status":"completed"}',
        "web-execution/generate-one/calls/member.json": b'{"reference":"saved"}',
        "web-execution/judge-one.json": b'{"status":"failed"}',
        "web-execution/judge-one/calls/member.json": b'{"raw":"failed judgment"}',
    }.items():
        put(source, relative, payload)
    return source, target


@pytest.fixture
def projects(tmp_path: Path) -> tuple[Path, Path]:
    return make_projects(tmp_path)


def test_dry_run_then_copy(projects: tuple[Path, Path]) -> None:
    source, target = projects
    before = continuation._snapshot(source), continuation._snapshot(target)
    report = continuation.continue_api_test(source, target, "Retry J1")
    assert report["write"] is False and report["copied_files"] == 8
    assert "web-execution/generate-one/calls/member.json" in report["paths"]
    assert "results/judge/test-model.jsonl" in report["not_copied"]
    assert (continuation._snapshot(source), continuation._snapshot(target)) == before

    before = continuation._snapshot(source)
    original_provenance = (source / "provenance.json").read_bytes()
    report = continuation.continue_api_test(source, target, "Retry J1 with corrected request schema", write=True)
    assert report["verified"] and report["source_unchanged"]
    assert continuation._snapshot(source) == before
    assert (target / "source-provenance.json").read_bytes() == original_provenance
    manifest = json.loads((target / "continuation-manifest.json").read_bytes())
    assert manifest["source_provenance_sha256"] == sha256(original_provenance)
    assert manifest["source_unchanged"]
    for relative, digest in manifest["files"].items():
        assert (target / relative).read_bytes() == (source / relative).read_bytes()
        assert sha256((target / relative).read_bytes()) == digest
    provenance = json.loads((target / "provenance.json").read_bytes())
    assert provenance["caseset_name"] == target.name and provenance["created_at"] == "target-created"
    assert provenance["models"] == ["test/model"] and provenance["trials"] == 2
    assert provenance["inference"] == {"binding_version": 2} and provenance["cases"] == ["Case001"]
    assert provenance["continuation_of"] == source.name and provenance["continuation_reason"]
    for relative in ("results/judge", "results/test-model_scored.jsonl", "results/report.md",
                     "web-execution/latest.json", "web-execution/judge-one.json", "web-execution/judge-one"):
        assert not (target / relative).exists()
    with pytest.raises(ValueError, match="fresh UI project"):
        continuation.continue_api_test(source, target, "Do not reuse", write=True)


def test_unsafe_source_or_target_is_rejected_before_writes(tmp_path: Path) -> None:
    cases = [("target", "items"), ("target", "case"), ("target", "extra"), ("target", "mode"),
             ("source", "running"), ("source", "local"), ("source", "symlink")]

    def run(case: tuple[str, str]) -> None:
        side, change = case
        source, target = make_projects(tmp_path / f"{side}-{change}")
        if change == "items":
            put(target, "items.jsonl", b"already imported")
        elif change == "case":
            put(target, "cases/Case001.json", b"already imported")
        elif change == "extra":
            put(target, "api-pipeline.json", b"already configured")
        elif change == "mode":
            provenance = json.loads((target / "provenance.json").read_bytes())
            put(target, "provenance.json", json.dumps({**provenance, "execution_mode": "local"}).encode())
        elif change == "running":
            put(source, "web-execution/latest.json", b'{"status":"running"}')
        elif change == "local":
            provenance = json.loads((source / "provenance.json").read_bytes())
            put(source, "provenance.json", json.dumps({**provenance, "execution_mode": "local"}).encode())
        else:
            (source / "cases/linked.json").symlink_to(source / "cases/Case001.json")
        before = continuation._snapshot(target)
        with pytest.raises(ValueError):
            continuation.continue_api_test(source, target, "Retry", write=True)
        assert continuation._snapshot(target) == before

    each_case(cases, lambda c: f"{c[0]} {c[1]}", run)


def test_detects_source_change_before_copying(projects: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    source, target = projects
    real_snapshot = continuation._snapshot
    source_reads = 0

    def changed_snapshot(root: Path) -> dict[str, str | None]:
        nonlocal source_reads
        if root == source:
            source_reads += 1
            if source_reads == 2:
                put(source, "cases/Case001.json", b"external writer changed source")
        return real_snapshot(root)

    before = real_snapshot(target)
    monkeypatch.setattr(continuation, "_snapshot", changed_snapshot)
    with pytest.raises(ValueError, match="changed before copying"):
        continuation.continue_api_test(source, target, "Retry", write=True)
    assert real_snapshot(target) == before
