"""Snapshots preserve opaque future formats and refuse unsafe destinations."""
from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from cases import each_case

from arisekit.common import files as snapshot
from tools import noharm


def _source(base: Path) -> Path:
    root = base / "source-project"
    (root / "answer-tables/history/previous").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / "provenance.json").write_bytes(b'{"future_metadata":true}\n')
    (root / "answer-tables/history/previous/rubric.bin").write_bytes(b"\x00\xffopaque rubric")
    (root / "new-upstream-format.txt").write_bytes(b"This is not JSON.\r\n")
    return root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return _source(tmp_path)


def test_snapshot_preserves_all_bytes_and_empty_directories(project: Path, tmp_path: Path) -> None:
    destination = tmp_path / "backup"
    before = snapshot._manifest(project)
    assert snapshot.snapshot(project, destination) == destination
    assert snapshot._manifest(project) == snapshot._manifest(destination) == before


@pytest.mark.parametrize("existing", ["directory", "file", "link", "dangling link"])
def test_existing_destination_is_never_replaced(project: Path, tmp_path: Path, existing: str) -> None:
    destination = tmp_path / "backup"
    if existing == "directory":
        destination.mkdir()
    elif existing == "file":
        destination.write_text("keep me")
    else:
        destination.symlink_to(project if existing == "link" else tmp_path / "missing")
    before = destination.lstat()
    with pytest.raises(FileExistsError, match="already exists"):
        snapshot.snapshot(project, destination)
    assert destination.lstat() == before


def _nested(base: Path, project: Path) -> tuple[Path, Path, Path]:
    return project, project / "backup", project / "backup"


def _source_symlink(kind: str) -> Callable[[Path, Path], tuple[Path, Path, Path]]:
    def setup(base: Path, project: Path) -> tuple[Path, Path, Path]:
        target = {"file": project / "new-upstream-format.txt", "directory": base, "dangling": base / "missing"}[kind]
        (project / "redirect").symlink_to(target)
        return project, base / "backup", base / "backup"
    return setup


def _root_symlink(base: Path, project: Path) -> tuple[Path, Path, Path]:
    link = base / "source-link"
    link.symlink_to(project)
    return link, base / "backup", base / "backup"


def _fifo(base: Path, project: Path) -> tuple[Path, Path, Path]:
    os.mkfifo(project / "pipe")
    return project, base / "backup", base / "backup"


def _redirected_parent(base: Path, project: Path) -> tuple[Path, Path, Path]:
    parent = base / "redirect"
    parent.symlink_to(base)
    return project, parent / "backup", base / "backup"


UnsafeSnapshot = tuple[str, Callable[[Path, Path], tuple[Path, Path, Path]], str]


def test_unsafe_snapshot_is_refused_before_writes(tmp_path: Path) -> None:
    cases: list[UnsafeSnapshot] = [
        ("nested destination", _nested, "separate folders"),
        ("file symlink in source", _source_symlink("file"), "regular files"),
        ("directory symlink in source", _source_symlink("directory"), "regular files"),
        ("dangling symlink in source", _source_symlink("dangling"), "regular files"),
        ("source root symlink", _root_symlink, "not a symlink"),
        ("FIFO in source", _fifo, "regular files"),
        ("redirected destination parent", _redirected_parent, "parent"),
    ]

    def run(case: UnsafeSnapshot) -> None:
        label, setup, match = case
        base = tmp_path / label.replace(" ", "-")
        base.mkdir()
        source, destination, written = setup(base, _source(base))
        with pytest.raises(ValueError, match=match):
            snapshot.snapshot(source, destination)
        assert not written.exists()

    each_case(cases, lambda c: c[0], run)


def test_source_change_does_not_claim_a_complete_snapshot(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = snapshot._manifest
    reads = 0

    def changed(root: Path) -> dict[Path, str | None]:
        nonlocal reads
        reads += 1
        if reads == 2:
            (project / "new-upstream-format.txt").write_bytes(b"changed source")
        return original(root)

    monkeypatch.setattr(snapshot, "_manifest", changed)
    destination = tmp_path / "backup"
    with pytest.raises(ValueError, match="Incomplete snapshot retained.*source changed"):
        snapshot.snapshot(project, destination)
    assert (destination / "new-upstream-format.txt").read_bytes() == b"This is not JSON.\r\n"
    assert (project / "new-upstream-format.txt").read_bytes() == b"changed source"


def test_cli_snapshot_uses_no_provider_route(project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = tmp_path / "backup"
    monkeypatch.setattr(noharm, "load_env", lambda: None)
    monkeypatch.setattr(noharm, "route", lambda *_: pytest.fail("snapshot must not resolve a model"))
    monkeypatch.setattr(sys, "argv", ["noharm", "snapshot", str(project), str(destination)])
    noharm.main()
    assert snapshot._manifest(destination) == snapshot._manifest(project)
