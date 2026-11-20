"""Verify the pinned text rubric import offline without accessing its source repository."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def check() -> list[str]:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "upstream-text-v2.json").read_text())
    errors = []
    expected = {name: entry["sha256"] for name, entry in manifest["files"].items()}
    expected[manifest["patch"]] = manifest["patch_sha256"]
    for name, digest in expected.items():
        path = root / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            errors.append(f"Pinned text rubric import differs: {name}")
    return errors


if __name__ == "__main__":
    problems = check()
    if problems:
        raise SystemExit("\n".join(problems))
    print("Text rubric import verified against pinned file hashes.")
