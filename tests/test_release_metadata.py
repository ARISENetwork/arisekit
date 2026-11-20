import json
import re
from pathlib import Path

import arisekit


ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = re.search(
        r"^\[project\]\s*$\n(?P<body>.*?)(?=^\[|\Z)",
        pyproject,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert project is not None
    version = re.search(
        r'^version\s*=\s*"(?P<version>[^"]+)"\s*$',
        project.group("body"),
        flags=re.MULTILINE,
    )
    assert version is not None
    return version.group("version")


def test_release_versions_agree() -> None:
    release = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"v\d+\.\d+\.\d+", release)
    version = release.removeprefix("v")

    npm_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    npm_lock = json.loads(
        (ROOT / "package-lock.json").read_text(encoding="utf-8")
    )

    assert _project_version() == version
    assert arisekit.__version__ == version
    assert npm_package["version"] == version
    assert npm_lock["version"] == version
    assert npm_lock["packages"][""]["version"] == version

    toolkit_package = json.loads((ROOT / "toolkits/noharmkit/app/package.json").read_text())
    toolkit_lock = json.loads((ROOT / "toolkits/noharmkit/app/package-lock.json").read_text())
    assert toolkit_package["version"] == version
    assert toolkit_lock["version"] == version
    assert toolkit_lock["packages"][""]["version"] == version
