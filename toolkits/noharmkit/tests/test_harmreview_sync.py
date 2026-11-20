"""A public editor pin must be reproducible and never overwrite unreviewed drift."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from cases import each_case

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "sync_harmreview.py"
SOURCE_PATH = "harmreview/lib/dropdown.ts"
LOCAL_PATH = "app/lib/dropdown.ts"
PATCH_PATH = "app/upstream/toolkit.patch"
MANIFEST_PATH = "app/upstream/manifest.json"
ORIGINAL = b'export const example = "upstream";\n'
ADVANCED = b'export const example = "advanced";\n'


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, content: bytes) -> str:
    path = repo / SOURCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    _git(repo, "add", SOURCE_PATH)
    _git(repo, "commit", "-m", "Update synthetic source")
    return _git(repo, "rev-parse", "HEAD")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_pin(root: Path, pin: str, patch: bytes = b"", local: bytes = ORIGINAL) -> None:
    (root / LOCAL_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / LOCAL_PATH).write_bytes(local)
    (root / PATCH_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / PATCH_PATH).write_bytes(patch)
    manifest = {
        "sourceRepository": "https://github.com/ARISENetwork/noharm-kit",
        "sourceCommit": pin,
        "integrationPatch": PATCH_PATH,
        "integrationPatchSha256": _sha(patch),
        "files": {
            SOURCE_PATH: {
                "upstreamSha256": _sha(ORIGINAL),
                "toolkitSha256": _sha(local),
            },
        },
    }
    (root / MANIFEST_PATH).write_text(json.dumps(manifest, indent=2) + "\n")


def _run(root: Path, command: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    # These fixtures pin only the noharm-kit snapshot; a bare check covers every source.
    if command == "check" and "--source" not in arguments:
        arguments = ("--source", "noharm-kit", *arguments)
    return subprocess.run(
        [sys.executable, str(SCRIPT), command, "--root", str(root), *arguments],
        capture_output=True,
        text=True,
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _pinned(base: Path) -> tuple[Path, Path, str]:
    repo = base / "reference"
    repo.mkdir(parents=True)
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "Synthetic Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "commit", "--allow-empty", "-m", "Empty synthetic source")
    pin = _commit(repo, ORIGINAL)
    root = base / "toolkit"
    _write_pin(root, pin)
    return root, repo, pin


@pytest.fixture
def pinned(tmp_path: Path) -> tuple[Path, Path, str]:
    return _pinned(tmp_path)


def test_offline_check_rejects_manifest_paths_outside_public_allowlist(
    pinned: tuple[Path, Path, str],
) -> None:
    root, _, _ = pinned
    path = root / MANIFEST_PATH
    manifest = json.loads(path.read_text())
    manifest["files"]["data/private.json"] = {
        "upstreamSha256": _sha(b"Synthetic excluded content\n"),
        "toolkitSha256": _sha(b"Synthetic excluded content\n"),
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    before = _snapshot(root)

    result = _run(root, "check")

    assert result.returncode != 0
    assert "allowlist" in (result.stdout + result.stderr).lower()
    assert _snapshot(root) == before


@pytest.mark.parametrize("changed_path", [LOCAL_PATH, PATCH_PATH])
def test_local_drift_blocks_update_without_overwriting(
    pinned: tuple[Path, Path, str], changed_path: str,
) -> None:
    root, repo, _ = pinned
    new_pin = _commit(repo, ADVANCED)
    (root / changed_path).write_bytes(b"Unreviewed local change\n")
    before = _snapshot(root)

    assert _run(root, "check").returncode != 0
    result = _run(root, "update", "--repo", str(repo), "--ref", new_pin)

    assert result.returncode != 0
    assert _snapshot(root) == before
    unavailable = _run(root, "update", "--repo", str(root / "absent-reference"), "--ref", new_pin)
    assert unavailable.returncode != 0
    assert "local drift" in (unavailable.stdout + unavailable.stderr).lower()
    assert _snapshot(root) == before


def test_valid_update_from_committed_source(pinned: tuple[Path, Path, str]) -> None:
    root, repo, _ = pinned
    offline = _run(root, "check")
    assert offline.returncode == 0, offline.stdout + offline.stderr
    new_pin = _commit(repo, ADVANCED)
    dirty = b"Uncommitted reference work must remain private\n"
    (repo / SOURCE_PATH).write_bytes(dirty)

    result = _run(root, "update", "--repo", str(repo), "--ref", new_pin)

    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((root / MANIFEST_PATH).read_text())
    assert manifest["sourceCommit"] == new_pin
    assert (root / LOCAL_PATH).read_bytes() == ADVANCED
    assert not (root / "harmreview").exists()
    assert (repo / SOURCE_PATH).read_bytes() == dirty
    assert _run(root, "check").returncode == 0
    assert _run(root, "verify", "--repo", str(repo)).returncode == 0


def test_symlinked_local_source_is_refused_without_overwriting_target(
    pinned: tuple[Path, Path, str],
) -> None:
    root, repo, pin = pinned
    # Keep the original source and add a new synthetic root containing a symlink.
    linked = root.parent / "linked-toolkit"
    _write_pin(linked, pin)
    source = linked / LOCAL_PATH
    original = source.with_suffix(".original.ts")
    source.rename(original)
    source.symlink_to(root / LOCAL_PATH)
    before = _snapshot(linked)
    target_before = (root / LOCAL_PATH).read_bytes()
    new_pin = _commit(repo, ADVANCED)

    result = _run(linked, "update", "--repo", str(repo), "--ref", new_pin)

    assert result.returncode != 0
    assert "symlink" in (result.stdout + result.stderr).lower()
    assert source.is_symlink()
    assert _snapshot(linked) == before
    assert (root / LOCAL_PATH).read_bytes() == target_before


def test_verify_rejects_falsified_upstream_hash(
    pinned: tuple[Path, Path, str],
) -> None:
    root, repo, _ = pinned
    manifest_path = root / MANIFEST_PATH
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][SOURCE_PATH]["upstreamSha256"] = _sha(b"Falsified source\n")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    before = _snapshot(root)
    assert _run(root, "check").returncode == 0

    result = _run(root, "verify", "--repo", str(repo))

    assert result.returncode != 0
    assert _snapshot(root) == before


NEW_SOURCE_PATH = "harmreview/components/QuickAuthoringGuide.tsx"
NEW_LOCAL_PATH = "app/components/QuickAuthoringGuide.tsx"


def test_include_adds_only_selected_committed_public_source(
    pinned: tuple[Path, Path, str],
) -> None:
    root, repo, _ = pinned
    content = b'export const guide = "Synthetic guide";\n'
    path = repo / NEW_SOURCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    _git(repo, "add", NEW_SOURCE_PATH)
    _git(repo, "commit", "-m", "Add synthetic public component")
    pin = _git(repo, "rev-parse", "HEAD")
    path.write_bytes(b"Uncommitted source must not be copied\n")

    result = _run(root, "update", "--repo", str(repo), "--ref", pin, "--include", NEW_SOURCE_PATH)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / NEW_LOCAL_PATH).read_bytes() == content
    manifest = json.loads((root / MANIFEST_PATH).read_text())
    assert set(manifest["files"]) == {SOURCE_PATH, NEW_SOURCE_PATH}
    assert _run(root, "check").returncode == 0
    assert _run(root, "verify", "--repo", str(repo)).returncode == 0


UNAPPROVED = "harmreview/lib/unapproved.ts"


def _patch_outside(root: Path, repo: Path, pin: str) -> list[str]:
    patch = (
        f"diff --git a/{UNAPPROVED} b/{UNAPPROVED}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{UNAPPROVED}\n"
        "@@ -0,0 +1 @@\n"
        '+export const excluded = "synthetic";\n'
    ).encode()
    _write_pin(root, pin, patch)
    assert _run(root, "check").returncode == 0
    return ["--ref", _commit(repo, ADVANCED)]


def _source_missing_at_pin(root: Path, repo: Path, pin: str) -> list[str]:
    return ["--ref", _git(repo, "rev-parse", f"{pin}^")]


def _patch_conflict(root: Path, repo: Path, pin: str) -> list[str]:
    patch = (
        f"diff --git a/{SOURCE_PATH} b/{SOURCE_PATH}\n"
        f"--- a/{SOURCE_PATH}\n"
        f"+++ b/{SOURCE_PATH}\n"
        "@@ -1 +1 @@\n"
        '-export const example = "upstream";\n'
        '+export const example = "toolkit";\n'
    ).encode()
    _write_pin(root, pin, patch, b'export const example = "toolkit";\n')
    assert _run(root, "verify", "--repo", str(repo)).returncode == 0
    return ["--ref", _commit(repo, ADVANCED)]


def _include(included: str) -> Callable[[Path, Path, str], list[str]]:
    return lambda root, repo, pin: ["--ref", _commit(repo, ADVANCED), "--include", included]


def _include_over_unpinned(root: Path, repo: Path, pin: str) -> list[str]:
    path = root / NEW_LOCAL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"Existing local source\n")
    return ["--ref", pin, "--include", NEW_SOURCE_PATH]


RefusedUpdate = tuple[
    str, Callable[[Path, Path, str], list[str]], Callable[[subprocess.CompletedProcess[str]], bool] | None, str | None
]


def test_refused_update_leaves_all_local_bytes_unchanged(tmp_path: Path) -> None:
    cases: list[RefusedUpdate] = [
        ("patch writes outside selected files", _patch_outside,
         lambda result: "outside" in (result.stdout + result.stderr).lower(), UNAPPROVED),
        ("selected source missing at the pin", _source_missing_at_pin, None, None),
        ("integration patch conflicts", _patch_conflict, None, None),
        ("include of a private path", _include("data/private.json"), None, None),
        ("include of a path missing at the pin", _include(NEW_SOURCE_PATH), None, None),
        ("include over an existing unpinned file", _include_over_unpinned,
         lambda result: "unpinned" in result.stdout, None),
    ]

    def run(case: RefusedUpdate) -> None:
        label, setup, message, absent = case
        root, repo, pin = _pinned(tmp_path / label.replace(" ", "-"))
        arguments = setup(root, repo, pin)
        before = _snapshot(root)

        result = _run(root, "update", "--repo", str(repo), *arguments)

        assert result.returncode != 0
        if message is not None:
            assert message(result), result.stdout + result.stderr
        assert _snapshot(root) == before
        if absent is not None:
            assert not (root / absent).exists()

    each_case(cases, lambda c: c[0], run)


EDITOR_SOURCE = "harmreview/components/Dropdown.tsx"
EDITOR_LOCAL = "app/harmreview/components/Dropdown.tsx"
EDITOR_ORIGINAL = b'import { menu } from "@/lib/dropdown";\nexport const where = "upstream";\n'


def _editor_pin(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "noharm-science"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "Synthetic Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / EDITOR_SOURCE).parent.mkdir(parents=True)
    (repo / EDITOR_SOURCE).write_bytes(EDITOR_ORIGINAL)
    _git(repo, "add", EDITOR_SOURCE)
    _git(repo, "commit", "-m", "Synthetic editor")
    pin = _git(repo, "rev-parse", "HEAD")
    root = tmp_path / "toolkit"
    localized = EDITOR_ORIGINAL.replace(b'"@/lib/', b'"@/harmreview/lib/')
    (root / EDITOR_LOCAL).parent.mkdir(parents=True)
    (root / EDITOR_LOCAL).write_bytes(localized)
    (root / "app/upstream").mkdir(parents=True)
    (root / "app/upstream/noharm-science.patch").write_bytes(b"")
    (root / "app/upstream/noharm-science.json").write_text(json.dumps({
        "sourceRepository": "https://github.com/davidwumdphd/noharm-science", "sourceCommit": pin,
        "integrationPatch": "app/upstream/noharm-science.patch", "integrationPatchSha256": _sha(b""),
        "files": {EDITOR_SOURCE: {"upstreamSha256": _sha(EDITOR_ORIGINAL), "toolkitSha256": _sha(localized)}},
    }, indent=2) + "\n")
    return root, repo, pin


def test_editor_source_sync_record_and_bare_check(tmp_path: Path) -> None:
    root, repo, _ = _editor_pin(tmp_path)
    assert _run(root, "check", "--source", "noharm-science").returncode == 0
    result = _run(root, "verify", "--source", "noharm-science", "--repo", str(repo))
    assert result.returncode == 0, result.stdout + result.stderr
    assert b'from "@/harmreview/lib/dropdown"' in (root / EDITOR_LOCAL).read_bytes()

    bare = subprocess.run([sys.executable, str(SCRIPT), "check", "--root", str(root)], capture_output=True, text=True, check=False)
    assert bare.returncode != 0 and "manifest.json" in bare.stdout

    edited = (root / EDITOR_LOCAL).read_bytes().replace(b'"upstream"', b'"toolkit"')
    (root / EDITOR_LOCAL).write_bytes(edited)
    assert _run(root, "check", "--source", "noharm-science").returncode != 0
    result = _run(root, "record", "--source", "noharm-science", "--repo", str(repo))
    assert result.returncode == 0, result.stdout + result.stderr
    patch = (root / "app/upstream/noharm-science.patch").read_text()
    assert "--- a/harmreview/components/Dropdown.tsx" in patch and '+export const where = "toolkit";' in patch
    assert _run(root, "check", "--source", "noharm-science").returncode == 0
    assert _run(root, "verify", "--source", "noharm-science", "--repo", str(repo)).returncode == 0
    assert (root / EDITOR_LOCAL).read_bytes() == edited
