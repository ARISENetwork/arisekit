"""Regression tests for the contents of published Python distributions."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def built_distributions(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Build the real wheel and sdist once, outside the repository tree."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.fail("distribution tests require uv, which owns this project's lockfile")

    output = tmp_path_factory.mktemp("distributions")
    completed = subprocess.run(
        [
            uv,
            "build",
            "--wheel",
            "--sdist",
            "--out-dir",
            str(output),
            "--no-create-gitignore",
            str(REPO_ROOT),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    wheels = list(output.glob("*.whl"))
    sdists = list(output.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1
    return wheels[0], sdists[0]


def test_wheel_contains_fhir_environment(
    built_distributions: tuple[Path, Path],
) -> None:
    wheel, _ = built_distributions
    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())

    assert "arisekit/env/__init__.py" in members
    assert "arisekit/env/fhir.py" in members
    assert "arisekit/scaffold.py" in members
    assert "noharm_reference/__init__.py" in members
    assert "noharm_reference/adapter.py" in members
    assert "noharm_reference/runtime.py" in members


def test_wheel_imports_public_benchmark_adapter_outside_checkout(
    built_distributions: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    wheel, _ = built_distributions
    script = """
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import arisekit.cli
import noharm_reference
from noharm_reference.runtime import build_public_command

wheel = Path(sys.argv[1]).resolve()
assert str(arisekit.cli.__file__).startswith(str(wheel))
assert str(noharm_reference.__file__).startswith(str(wheel))
args = arisekit.cli.build_parser().parse_args(
    ["public-benchmark", "noharm", "--source", "bundle", "inspect"]
)
assert args.func is arisekit.cli.cmd_public_benchmark
assert callable(build_public_command)
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script, str(wheel.resolve())],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_sdist_excludes_repo_local_dependencies_and_debug_output(
    built_distributions: tuple[Path, Path],
) -> None:
    _, sdist = built_distributions
    with tarfile.open(sdist, "r:gz") as archive:
        members = [PurePosixPath(member.name) for member in archive.getmembers()]

    assert any(
        path.match("*/benchmarks/noharm_reference/runtime.py") for path in members
    )
    assert not any("node_modules" in path.parts for path in members)
    assert not any(path.name.endswith("-debug.log") for path in members)
