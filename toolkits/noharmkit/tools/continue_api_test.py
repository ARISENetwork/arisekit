"""Continue an API test in a fresh UI project, preserving inputs and collection evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from arisekit.common.hashing import sha256
from arisekit.common.jsonio import json_text
from arisekit.common.logs import now_iso

EXCLUDED = ["results/judge", "results/*_scored.jsonl", "results/report.md",
            "web-execution/latest.json", "web-execution/judge-*"]
ROOT_FILES = {"items.jsonl", "api-pipeline.json"}
FOLDERS = ("cases/", "imports/", "answer-tables/", "results/responses/")


def _allowed_path(path: Path) -> None:
    if "holdout" in str(path).lower():
        raise ValueError("The requested project contains an excluded path")


def _snapshot(root: Path) -> dict[str, str | None]:
    manifest: dict[str, str | None] = {}

    def visit(folder: Path) -> None:
        for path in sorted(folder.iterdir()):
            _allowed_path(path)
            if path.is_symlink():
                raise ValueError("Continuation requires regular files and directories, not symbolic links")
            relative = str(path.relative_to(root))
            if path.is_dir():
                manifest[relative] = None
                visit(path)
            elif path.is_file():
                manifest[relative] = sha256(path.read_bytes())
            else:
                raise ValueError("Continuation requires regular files and directories")

    visit(root)
    return manifest


def _roots(source: Path, target: Path) -> tuple[Path, Path]:
    for path in (source, target):
        _allowed_path(path)
        if path.is_symlink() or not path.is_dir():
            raise ValueError("Source and target must be existing project directories, not symbolic links")
    source, target = source.resolve(), target.resolve()
    for path in (source, target):
        _allowed_path(path)
    if source == target or source.is_relative_to(target) or target.is_relative_to(source):
        raise ValueError("Source and target projects must be separate directories")
    return source, target


def _fresh_target(target: Path) -> tuple[dict[str, Any], dict[str, str | None]]:
    snapshot = _snapshot(target)
    if (set(snapshot) != {"items.jsonl", "provenance.json", "cases"}
            or snapshot["cases"] is not None or snapshot["items.jsonl"] is None
            or snapshot["provenance.json"] is None):
        raise ValueError("Target must be a fresh UI project containing only empty items.jsonl, cases, and provenance.json")
    provenance = json.loads((target / "provenance.json").read_bytes())
    if (target / "items.jsonl").read_bytes() != b"" or provenance.get("cases") != []:
        raise ValueError("Target already contains cases or items; create a fresh UI project")
    if provenance.get("execution_mode") != "api":
        raise ValueError("Target must use API Mode")
    if not provenance.get("created_at"):
        raise ValueError("Target must retain its UI project creation time")
    return provenance, snapshot


def _copy_file(relative: str) -> bool:
    if relative in ROOT_FILES or relative.startswith(FOLDERS):
        return True
    parts = Path(relative).parts
    return (len(parts) >= 2 and parts[0] == "web-execution" and parts[1].startswith("generate-")
            and (len(parts) > 2 or parts[1].endswith(".json")))


def continue_api_test(source: Path, target: Path, reason: str, *, write: bool = False) -> dict[str, Any]:
    if not reason.strip():
        raise ValueError("Provide a nonblank continuation reason")
    source, target = _roots(source, target)
    target_provenance, target_before = _fresh_target(target)
    source_before = _snapshot(source)
    if "provenance.json" not in source_before or "items.jsonl" not in source_before:
        raise ValueError("Source requires provenance.json and items.jsonl")
    original_provenance = (source / "provenance.json").read_bytes()
    provenance = json.loads(original_provenance)
    if provenance.get("execution_mode") != "api":
        raise ValueError("Source must use API Mode")
    latest = source / "web-execution/latest.json"
    if "web-execution/latest.json" in source_before and json.loads(latest.read_bytes()).get("status") == "running":
        raise ValueError("Source execution is still running; wait for a final status before continuing")
    files = {relative: digest for relative, digest in source_before.items()
             if digest is not None and _copy_file(relative)}
    report = {"write": write, "source": str(source), "target": str(target), "reason": reason.strip(),
              "copied_files": len(files), "copied_bytes": sum((source / name).stat().st_size for name in files),
              "paths": sorted(files), "excluded": EXCLUDED,
              "not_copied": sorted(name for name, digest in source_before.items()
                                   if digest is not None and name not in files and name != "provenance.json")}
    if not write:
        if _snapshot(source) != source_before or _snapshot(target) != target_before:
            raise ValueError("Source or target changed during the dry run")
        return report
    if _snapshot(source) != source_before or _snapshot(target) != target_before:
        raise ValueError("Source or target changed before copying; no files were copied")
    for relative, digest in files.items():
        payload = (source / relative).read_bytes()
        if sha256(payload) != digest:
            raise ValueError(f"Source changed during copying: {relative}; partial target retained")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if relative == "items.jsonl":
            if destination.read_bytes() != b"":
                raise ValueError("Target items changed during copying; partial target retained")
            destination.write_bytes(payload)
        else:
            with destination.open("xb") as output:
                output.write(payload)
        if sha256(destination.read_bytes()) != digest:
            raise ValueError(f"Copied bytes do not match: {relative}; partial target retained")
    with (target / "source-provenance.json").open("xb") as output:
        output.write(original_provenance)
    provenance.update(caseset_name=target.name, created_at=target_provenance["created_at"], updated_at=now_iso(),
                      continuation_of=source.name, continuation_reason=reason.strip())
    if sha256((target / "provenance.json").read_bytes()) != target_before["provenance.json"]:
        raise ValueError("Target provenance changed during copying; partial target retained")
    (target / "provenance.json").write_text(json_text(provenance))
    manifest = {"source_project": source.name, "source_path": str(source), "target_project": target.name,
                "reason": reason.strip(), "source_provenance_sha256": sha256(original_provenance),
                "files": files, "excluded": EXCLUDED, "not_copied": report["not_copied"],
                "source_snapshot_sha256": sha256(json.dumps(source_before, sort_keys=True)),
                "source_unchanged": _snapshot(source) == source_before}
    with (target / "continuation-manifest.json").open("x") as output:
        output.write(json_text(manifest))
    if not manifest["source_unchanged"]:
        raise ValueError("Source changed during copying; partial target retained for inspection")
    if any(sha256((target / name).read_bytes()) != digest for name, digest in files.items()):
        raise ValueError("Copied inputs changed before verification; partial target retained")
    return {**report, "source_unchanged": True, "verified": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path, help="existing, empty UI-created API project")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--write", action="store_true", help="copy after inspecting the default dry run")
    args = parser.parse_args()
    try:
        report = continue_api_test(args.source, args.target, args.reason, write=args.write)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
