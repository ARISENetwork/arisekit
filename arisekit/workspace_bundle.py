"""Portable, checksum-bound views exported from a verified results workspace."""
from __future__ import annotations

import hashlib
import json

SCHEMA_VERSION = "arisekit.workspace-export.v1"
MAX_BUNDLE_BYTES = 64 * 1024 * 1024


def export_bundle(workspace):
    from arisekit.workspace import _file

    snapshot = workspace.snapshot()
    evidence = {}
    for run in snapshot["runs"]:
        paths = [run["id"], run["bundle"]["raw_checkpoint"]["path"], run["bundle"]["scores"]["path"]]
        checkpoint = _file(workspace.results, paths[1])
        paths.append((checkpoint.parent / "run-manifest.json").relative_to(workspace.results).as_posix())
        for relative in paths:
            payload = _file(workspace.results, relative).read_bytes()
            evidence[relative] = {"text": payload.decode("utf-8"), "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
    # Operation history can contain unrelated iteration receipts. The portable
    # view carries the verified runs and source plan only.
    snapshot["operations"] = []
    payload = {
        "schema_version": SCHEMA_VERSION,
        "build_spec_text": _file(workspace.authoring, "benchmark-build-spec.json").read_bytes().decode("utf-8"),
        "workspace": snapshot,
        "evidence": evidence,
    }
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if len(text.encode("utf-8")) > MAX_BUNDLE_BYTES:
        raise ValueError("Portable result bundles are limited to 64 MiB; inspect this run in the worker workspace")
    return {"text": text, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
