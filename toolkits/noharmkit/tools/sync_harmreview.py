"""Check or update the rubric editor snapshots from explicit Git objects.

Two sources, each with its own pin, manifest and integration patch:
- noharm-science: the current rubric editor (`harmreview/`), synced into `app/harmreview/`. Its `@/` imports are
  pointed at that folder before the patch applies, so the toolkit's own modules keep their names.
- noharm-kit: the read-only archive, the final source of the legacy answer-table editor and its shared files.

Only maintainers updating a pin need access to the reference repo.
The check command is offline and uses only files shipped in this toolkit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
# Never traverse the reference checkout or copy data, APIs, or configuration.
LEGACY_FILES = frozenset({
    "harmreview/components/AnswerTableEditor.tsx",
    "harmreview/components/AnswerTableEditor.module.css",
    "harmreview/components/CompactRecommendationTags.tsx",
    "harmreview/components/CompactRecommendationTags.module.css",
    "harmreview/components/QuickAuthoringGuide.tsx",
    "harmreview/components/RemovalDialog.tsx",
    "harmreview/components/RemovalDialog.module.css",
    "harmreview/components/OnlyIfPreview.tsx",
    "harmreview/components/OnlyIfPreview.module.css",
    "harmreview/components/AnswerTablePanel.tsx",
    "harmreview/components/AnswerTablePanel.module.css",
    "harmreview/components/CaseSourcePanel.tsx",
    "harmreview/components/Dropdown.tsx",
    "harmreview/components/Dropdown.module.css",
    "harmreview/lib/answer-table.ts",
    "harmreview/lib/answer-score.ts",
    "harmreview/lib/reviewer-id.ts",
    "harmreview/lib/dropdown.ts",
    "harmreview/lib/types.ts",
    "harmreview/lib/caseset/notice.ts",
    "harmreview/app/globals.css",
})
EDITOR_FILES = frozenset({
    "harmreview/components/RubricEditor.tsx",
    "harmreview/components/RubricEditor.module.css",
    "harmreview/components/RubricPanel.tsx",
    "harmreview/components/RubricPanel.module.css",
    "harmreview/components/RubricGuide.tsx",
    "harmreview/components/CaseSourcePanel.tsx",
    "harmreview/components/Dropdown.tsx",
    "harmreview/components/Dropdown.module.css",
    "harmreview/components/RemovalDialog.tsx",
    "harmreview/components/RemovalDialog.module.css",
    "harmreview/lib/rubric.ts",
    "harmreview/lib/rubric-text-v2.ts",
    "harmreview/lib/clinician-review.ts",
    "harmreview/lib/dropdown.ts",
    "harmreview/lib/reviewer-id.ts",
    "harmreview/lib/types.ts",
    "harmreview/components/RubricTutorial.tsx",
    "harmreview/components/RubricTutorial.module.css",
    "harmreview/lib/rubric-tutorial.ts",
    "harmreview/lib/tutorial-placement.ts",
    "harmreview/data/tutorial/copy.json",
    "harmreview/data/tutorial/uti.json",
})


@dataclass(frozen=True)
class Source:
    name: str
    repository: str
    manifest: str
    patch: str
    files: frozenset[str]
    target: str  # toolkit folder that upstream `harmreview/` maps to
    rewrite_imports: bool


SOURCES = {
    "noharm-science": Source("noharm-science", "https://github.com/davidwumdphd/noharm-science",
                             "app/upstream/noharm-science.json", "app/upstream/noharm-science.patch",
                             EDITOR_FILES, "app/harmreview/", True),
    "noharm-kit": Source("noharm-kit", "https://github.com/ARISENetwork/noharm-kit",
                         "app/upstream/manifest.json", "app/upstream/toolkit.patch", LEGACY_FILES, "app/", False),
}
IMPORT = re.compile(rb"""((?:from|import)\s*\(?\s*["'])@/""")


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def toolkit_path(source: Source, source_path: str) -> str:
    return source.target + source_path.removeprefix("harmreview/")


def localize(source: Source, content: bytes) -> bytes:
    """Point a synced module's `@/` imports at the folder the source syncs into."""
    if not source.rewrite_imports:
        return content
    prefix = source.target.removeprefix("app/").encode()
    return IMPORT.sub(lambda match: match.group(1) + b"@/" + prefix, content)


def local_file(root: Path, name: str) -> Path:
    path = root / name
    current = path
    while True:
        if current.is_symlink():
            raise ValueError(f"Refusing symlink: {name}")
        if current == root:
            break
        current = current.parent
    return path


def read_manifest(root: Path, source: Source) -> dict[str, Any]:
    manifest = json.loads(local_file(root, source.manifest).read_text())
    if manifest.get("sourceRepository") != source.repository or manifest.get("integrationPatch") != source.patch:
        raise ValueError("Unexpected snapshot source or integration patch")
    if not re.fullmatch(r"[0-9a-f]{40}", manifest.get("sourceCommit", "")):
        raise ValueError("Snapshot must name a full Git commit")
    files = manifest.get("files", {})
    if not files or not set(files).issubset(source.files):
        raise ValueError("Snapshot contains paths outside the public UI allowlist")
    return manifest


def check(root: Path, source: Source, manifest: dict[str, Any]) -> None:
    drift = []
    for name, hashes in manifest["files"].items():
        path = local_file(root, toolkit_path(source, name))
        if not path.is_file() or digest(path.read_bytes()) != hashes["toolkitSha256"]:
            drift.append(name)
    patch = local_file(root, source.patch)
    if not patch.is_file() or digest(patch.read_bytes()) != manifest["integrationPatchSha256"]:
        drift.append(source.patch)
    if drift:
        raise ValueError("Local drift; refusing synchronization: " + ", ".join(drift))


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if result.returncode:
        raise ValueError(result.stderr.decode(errors="replace").strip() or "Git command failed")
    return result.stdout


def candidate(source: Source, repo: Path, ref: str, names: list[str], patch: bytes) -> tuple[str, dict[str, bytes], dict[str, bytes]]:
    if "holdout" in str(repo).casefold() or "holdout" in str(repo.resolve()).casefold():
        raise ValueError("Reference path is excluded")
    commit = git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Reference must resolve to a full Git commit")
    upstream = {}
    for name in names:
        entry = git(repo, "ls-tree", commit, "--", name).decode()
        if not entry.startswith("100644 blob ") or entry.rstrip().split("\t")[-1] != name:
            raise ValueError(f"Missing or non-regular public source file: {name}")
        upstream[name] = git(repo, "show", f"{commit}:{name}")
    with tempfile.TemporaryDirectory(prefix="noharm-ui-sync-") as temporary:
        staging = Path(temporary)
        for name, content in upstream.items():
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(localize(source, content))
        if patch:
            stats = subprocess.run(["git", "apply", "--numstat", "-z"], input=patch,
                                   cwd=staging, capture_output=True, check=False)
            touched = [entry.split(b"\t", 2)[-1].decode() for entry in stats.stdout.split(b"\0") if entry]
            if stats.returncode or not touched or not set(touched).issubset(names):
                raise ValueError("Integration patch touches paths outside this snapshot")
            for args in (("--check",), ()):
                applied = subprocess.run(["git", "apply", "--whitespace=nowarn", *args], input=patch,
                                         cwd=staging, capture_output=True, check=False)
                if applied.returncode:
                    raise ValueError("Integration patch conflict; no files updated: "
                                     + applied.stderr.decode(errors="replace").strip())
        adapted = {}
        for name in names:
            path = local_file(staging, name)
            if not path.is_file():
                raise ValueError(f"Integration patch removed public source file: {name}")
            adapted[name] = path.read_bytes()
    return commit, upstream, adapted


def synchronize(root: Path, source: Source, repo: Path, ref: str | None, *, verify: bool,
                include: list[str] | None = None) -> None:
    manifest = read_manifest(root, source)
    check(root, source, manifest)
    patch = local_file(root, source.patch).read_bytes()
    additions = set(include or [])
    if not additions.issubset(source.files):
        raise ValueError("Additional source paths are outside the public UI allowlist")
    names = sorted(set(manifest["files"]) | additions)
    for name in additions - set(manifest["files"]):
        if local_file(root, toolkit_path(source, name)).exists():
            raise ValueError(f"Refusing to replace an unpinned local file: {name}")
    commit, upstream, adapted = candidate(source, repo, ref or manifest["sourceCommit"], names, patch)
    if verify:
        for name, hashes in manifest["files"].items():
            if digest(upstream[name]) != hashes["upstreamSha256"] or digest(adapted[name]) != hashes["toolkitSha256"]:
                raise ValueError(f"Pinned source or integration mismatch: {name}")
        print(f"Verified public snapshot against {commit}")
        return
    # Every source file and patch is validated before touching the working tree.
    for name, content in adapted.items():
        path = local_file(root, toolkit_path(source, name))
        if not path.exists() or path.read_bytes() != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        manifest["files"][name] = {"upstreamSha256": digest(upstream[name]), "toolkitSha256": digest(content)}
    manifest["sourceCommit"] = commit
    local_file(root, source.manifest).write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Updated {len(adapted)} {source.name} files to {commit}; review the diff and run local checks")


def record(root: Path, source: Source, repo: Path) -> None:
    """Rebuild the integration patch and toolkit hashes from the pinned upstream files and the current toolkit
    copies, after local integration edits or a hand-resolved update. Review the patch before committing it."""
    manifest = read_manifest(root, source)
    commit, upstream, _ = candidate(source, repo, manifest["sourceCommit"], sorted(manifest["files"]), b"")
    with tempfile.TemporaryDirectory(prefix="noharm-ui-record-") as temporary:
        staging = Path(temporary)
        for name, content in upstream.items():
            for side, data in (("a", localize(source, content)), ("b", local_file(root, toolkit_path(source, name)).read_bytes())):
                path = staging / side / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        result = subprocess.run(["git", "diff", "--no-index", "--no-prefix", "--no-color", "a", "b"],
                                cwd=staging, capture_output=True, check=False)
        if result.returncode not in (0, 1):
            raise ValueError(result.stderr.decode(errors="replace").strip() or "git diff failed")
    patch = b"".join(line for line in result.stdout.splitlines(keepends=True)
                     if not line.startswith((b"diff --git ", b"index ")))
    local_file(root, source.patch).write_bytes(patch)
    for name in manifest["files"]:
        manifest["files"][name] = {"upstreamSha256": digest(upstream[name]),
                                   "toolkitSha256": digest(local_file(root, toolkit_path(source, name)).read_bytes())}
    manifest["integrationPatchSha256"] = digest(patch)
    local_file(root, source.manifest).write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Recorded the {source.name} integration patch against {commit}; review it, then run verify")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "verify", "update", "record"))
    parser.add_argument("--root", type=Path, default=ROOT, help="Toolkit root (default: this checkout)")
    parser.add_argument("--source", choices=sorted(SOURCES),
                        help="Snapshot to act on: check covers every source unless one is named; verify and update "
                             "default to noharm-kit")
    parser.add_argument("--repo", type=Path, help="Maintainer checkout of the reference repository")
    parser.add_argument("--ref", help="Explicit reference commit or ref, required for update")
    parser.add_argument("--include", action="append", help="Additional public source path to pin during update")
    args = parser.parse_args()
    if args.command != "check" and args.repo is None:
        parser.error("--repo is required for verify and update")
    if args.command == "update" and not args.ref:
        parser.error("--ref is required for update")
    if args.command != "update" and args.ref:
        parser.error("--ref is only used by update; verify always reconstructs the recorded pin")
    if args.command != "update" and args.include:
        parser.error("--include is only used by update")
    try:
        if args.command == "check":
            for source in [SOURCES[args.source]] if args.source else SOURCES.values():
                manifest = read_manifest(args.root, source)
                check(args.root, source, manifest)
                print(f"No {source.name} drift: {len(manifest['files'])} files, pin {manifest['sourceCommit']}")
        elif args.command == "record":
            record(args.root, SOURCES[args.source or "noharm-kit"], args.repo)
        else:
            synchronize(args.root, SOURCES[args.source or "noharm-kit"], args.repo, args.ref,
                        verify=args.command == "verify", include=args.include)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"harmreview sync: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
