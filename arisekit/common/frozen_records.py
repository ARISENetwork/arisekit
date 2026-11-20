"""Digest-bound JSON files for local benchmark artifacts."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

from arisekit.common.hashing import canonical_sha256 as digest
from arisekit.common.jsonio import canonical_json as canonical
from arisekit.common.jsonio import strict_json_object


def write_record(path: Path, value: dict) -> None:
    if path.is_symlink():
        raise ValueError("artifact path cannot be a symlink")
    if path.exists():
        if canonical(read_record(path)) != canonical(value):
            raise ValueError(f"frozen artifact differs: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".record-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(canonical({"sha256": digest(value), "payload": value}) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_record(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError("artifact path cannot be a symlink")
    record = strict_json_object(path.read_text(encoding="utf-8"), "frozen record")
    if set(record) != {"sha256", "payload"} or digest(record["payload"]) != record["sha256"]:
        raise ValueError(f"artifact integrity mismatch: {path.name}")
    return record["payload"]
