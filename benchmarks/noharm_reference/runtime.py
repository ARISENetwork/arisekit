"""Validated launcher for the official public First Do NOHARM run kit.

NOHARM's released scorer is a staged, cohort-pooled judge.  It cannot be
represented faithfully as an ARISEKit ``BaseScorer``, whose contract scores
one item at a time.  This adapter therefore validates and fingerprints the
public release bundle, then delegates execution to the release's own
``run.py`` or ``score.py`` entry point.

The launcher never invokes a shell.  Arguments after the ARISEKit command's
``--`` separator are passed literally to the selected upstream script.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .adapter import NoHarmReferenceBundle


PUBLIC_BENCHMARK_ID = "noharm"
_ENTRYPOINTS = {"run": "run.py", "score": "score.py"}


@dataclass(frozen=True)
class NoHarmPublicCommand:
    """One validated invocation of a released NOHARM entry point."""

    bundle: NoHarmReferenceBundle
    bundle_sha256: str
    action: str
    argv: tuple[str, ...]

    @property
    def cwd(self) -> Path:
        return self.bundle.root

    @property
    def display(self) -> str:
        return shlex.join(self.argv)


def build_public_command(
    source: str | Path,
    *,
    action: str,
    upstream_args: Sequence[str] = (),
    python_executable: str | Path | None = None,
) -> NoHarmPublicCommand:
    """Validate ``source`` and construct its literal upstream command."""

    if action not in _ENTRYPOINTS:
        supported = ", ".join(sorted(_ENTRYPOINTS))
        raise ValueError(
            f"unsupported NOHARM action {action!r}; expected one of {supported}"
        )
    if isinstance(upstream_args, (str, bytes)):
        raise TypeError("upstream_args must be a sequence of argument strings")
    normalized_args: list[str] = []
    for index, value in enumerate(upstream_args):
        if not isinstance(value, str):
            raise TypeError(f"upstream argument {index} must be a string")
        if "\x00" in value:
            raise ValueError(f"upstream argument {index} contains a null byte")
        normalized_args.append(value)

    bundle = NoHarmReferenceBundle(source)
    bundle_sha256 = bundle.hashes.bundle_sha256
    entrypoint = bundle.root / _ENTRYPOINTS[action]
    executable = str(python_executable or sys.executable)
    return NoHarmPublicCommand(
        bundle=bundle,
        bundle_sha256=bundle_sha256,
        action=action,
        argv=(executable, str(entrypoint), *normalized_args),
    )


def execute_public_command(command: NoHarmPublicCommand) -> int:
    """Execute a command after rechecking its bundle has not changed."""

    if not isinstance(command, NoHarmPublicCommand):
        raise TypeError("command must be a NoHarmPublicCommand")
    current = NoHarmReferenceBundle(command.bundle.root)
    if current.hashes.bundle_sha256 != command.bundle_sha256:
        raise ValueError("NOHARM bundle changed after command construction")
    completed = subprocess.run(command.argv, cwd=command.cwd, check=False)
    return int(completed.returncode)


def inspection_lines(bundle: NoHarmReferenceBundle) -> tuple[str, ...]:
    """Return a stable human-readable inspection of a validated release."""

    return (
        f"public benchmark: {PUBLIC_BENCHMARK_ID}",
        f"source: {bundle.root}",
        f"base cases: {bundle.base_case_count}",
        f"rows: {bundle.row_count}",
        f"canonical k=5 rows: {len(bundle.select(5))}",
        f"content sha256: {bundle.hashes.content_sha256}",
        f"judge sha256: {bundle.hashes.judge_sha256}",
        f"bundle sha256: {bundle.hashes.bundle_sha256}",
        "execution: delegated to the validated release run.py or score.py",
        "claim boundary: structural compatibility only; the released scorer "
        "and its documented access, model, judge, cost, and dependency "
        "requirements remain authoritative",
    )


__all__ = [
    "NoHarmPublicCommand",
    "PUBLIC_BENCHMARK_ID",
    "build_public_command",
    "execute_public_command",
    "inspection_lines",
]
