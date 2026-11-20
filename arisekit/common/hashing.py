"""SHA-256 digests of exact bytes and of JSON values."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from arisekit.common.jsonio import canonical_json, strict_canonical_json


def sha256(data: str | bytes) -> str:
    """Digest of exact bytes; text is UTF-8 encoded without normalization."""
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def source_file(path: str, root: str | Path) -> Path:
    """The source file at package-relative `path` under `root`, the arisekit directory the caller runs from.

    Callers pass `Path(__file__).parents[1]`, so a module run from a frozen snapshot that mirrors the package
    layout reads its snapshot copies."""
    file = Path(root) / path
    if not file.is_file():
        raise FileNotFoundError(f"arisekit source file not found: {file}")
    return file


def source_sha256(paths: Iterable[str], root: str | Path) -> dict[str, str]:
    """Digest of each source file, keyed by package-relative path; see source_file."""
    return {path: sha256(source_file(path, root).read_bytes()) for path in paths}


def json_sha256(value: Any, *, ensure_ascii: bool = True) -> str:
    """Digest of sorted-key JSON. Stored identities depend on ensure_ascii, so callers keep their setting.
    NOHARMKit's app/lib/caseset/hash.ts reproduces the ensure_ascii=True form."""
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=ensure_ascii))


def canonical_sha256(value: Any, *, ensure_ascii: bool = False) -> str:
    """Digest of a value's canonical JSON; errors as canonical_json. Stored identities depend on ensure_ascii, so
    callers keep their setting."""
    return sha256(canonical_json(value, ensure_ascii=ensure_ascii))


def strict_canonical_sha256(value: Any) -> str:
    """Digest of a value's canonical JSON; errors as strict_canonical_json."""
    return sha256(strict_canonical_json(value))
