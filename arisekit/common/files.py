"""Files: safe reads, atomic and write-once writes, safe paths inside a folder, and verified folder snapshots."""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from arisekit.common.hashing import sha256


# Reading
def existing_file(value: Any, label: str, *, check_type: bool = False) -> Path:
    """The resolved regular file `value` names. A symlink raises ValueError and a missing file FileNotFoundError;
    check_type also rejects a value that is not a path with ValueError."""
    if check_type and not isinstance(value, (str, os.PathLike)):
        raise ValueError(f"{label} path must be a filesystem path")
    supplied = Path(value).expanduser()
    if supplied.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    path = supplied.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


# Writing
def atomic_write(path: Path, payload: bytes, *, make_parents: bool = False) -> None:
    """Replace path with payload in one rename, through a synced temporary file beside it."""
    if make_parents:
        path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def atomic_directory(destination: Path, files: Mapping[str, bytes], verify: Callable[[Path, Mapping[str, bytes]], None],
                     *, symlink_counts_as_existing: bool = False) -> None:
    """Publish a directory of files in one rename, through a synced temporary directory beside it. An existing
    destination (including a symlink, with symlink_counts_as_existing) is checked with verify instead."""
    def exists() -> bool:
        return destination.exists() or (symlink_counts_as_existing and destination.is_symlink())

    if exists():
        verify(destination, files)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        for name, content in files.items():
            with (temporary / name).open("wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        try:
            os.replace(temporary, destination)
        except OSError:
            if exists():
                verify(destination, files)
            else:
                raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def write_text_once(path: Path, text: str) -> None:
    """Create path with text, or accept an existing file with exactly that text; different text raises
    FileExistsError."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise FileExistsError(f"artifact exists with different content: {path}")
        return
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)


def write_private_once(path: Path, content: bytes, *, make_parents: bool = False) -> None:
    """Create path readable only by its owner and synced, or accept an identical existing file; a symlink or
    different bytes raise ValueError."""
    if make_parents:
        path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != content:
            raise ValueError(f"refusing to overwrite non-identical artifact {path}")
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


# Safe paths
def check_destination(project: Path, path: Path, *, directory: bool = False) -> None:
    """Reject redirected paths and unsupported entries before stage work starts."""
    try:
        parts = path.absolute().relative_to(project.absolute()).parts
    except ValueError as error:
        raise ValueError(f"storage path leaves the selected project: {path}") from error
    current = project
    for index, part in enumerate(parts):
        current /= part
        if current.is_symlink() or not current.resolve().is_relative_to(project.resolve()):
            raise ValueError(f"storage path redirects or leaves the selected project: {current}")
        if not current.exists():
            continue
        wants_directory = index < len(parts) - 1 or directory
        if wants_directory and not current.is_dir():
            raise ValueError(f"storage directory is not a directory: {current}")
        if not wants_directory and not current.is_file():
            raise ValueError(f"storage artifact is not a regular file: {current}")


# Verified snapshots
def _manifest(root: Path) -> dict[Path, str | None]:
    """Every entry under root with its content digest (None for a folder). Links and special files are refused
    before any file is opened, so a snapshot never follows a path out of the project."""
    paths = sorted(root.rglob("*"))
    for path in paths:
        mode = path.lstat().st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError(f"snapshot requires regular files and directories: {path}")
    return {path.relative_to(root): None if path.is_dir() else sha256(path.read_bytes()) for path in paths}


def snapshot(source: Path, destination: Path) -> Path:
    """Copy a folder byte for byte into a new folder, then verify the source is unchanged and the copy matches.

    Pause writers first. If the copy fails or the source changes, the incomplete copy is kept for inspection and
    this raises. Nothing in the source is removed or rewritten, including formats this kit does not know.
    """
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"snapshot source must be a directory, not a symlink: {source}")
    source = source.resolve()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"snapshot destination already exists: {destination}")
    target = destination.resolve()
    if target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("snapshot source and destination must be separate folders")
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ValueError("snapshot destination parent must be an existing directory, not a symlink")
    before = _manifest(source)
    target.mkdir(mode=0o700, exist_ok=False)  # exclusive, so a destination created after the checks is refused
    try:
        for relative, digest in before.items():
            if digest is None:
                (target / relative).mkdir(exist_ok=False)
            else:
                with (target / relative).open("xb") as copy:
                    copy.write((source / relative).read_bytes())
        if _manifest(source) != before:
            raise ValueError("source changed during snapshot; pause project writers before trying again")
        if _manifest(target) != before:
            raise ValueError("snapshot content does not match the source")
    except (OSError, ValueError) as error:
        raise ValueError(f"Incomplete snapshot retained at {target}: {error}") from error
    return target
