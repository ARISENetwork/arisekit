"""Apply release-gate markers from tests/test-groups.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


TEST_ROOT = Path(__file__).resolve().parent
GROUP_MANIFEST = TEST_ROOT / "test-groups.json"
ALLOWED_MARKERS = frozenset({"live", "slow", "study"})


def _load_group_manifest() -> dict[Path, tuple[str, ...]]:
    raw: Any = json.loads(GROUP_MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise pytest.UsageError("tests/test-groups.json has an unsupported schema")

    groups = raw.get("groups")
    if not isinstance(groups, dict) or not groups:
        raise pytest.UsageError("tests/test-groups.json must declare test groups")

    classified: dict[Path, tuple[str, ...]] = {}
    declared: set[Path] = set()
    for group_name, group in groups.items():
        if not isinstance(group_name, str) or not isinstance(group, dict):
            raise pytest.UsageError("test group names and definitions must be objects")
        if set(group) != {"markers", "paths"}:
            raise pytest.UsageError(f"test group {group_name!r} has unknown fields")

        markers = group["markers"]
        paths = group["paths"]
        if not isinstance(markers, list) or any(
            marker not in ALLOWED_MARKERS for marker in markers
        ):
            raise pytest.UsageError(f"test group {group_name!r} has invalid markers")
        if group_name == "core" and markers:
            raise pytest.UsageError("the core test group must not apply markers")
        if group_name != "core" and not markers:
            raise pytest.UsageError(f"test group {group_name!r} has no markers")
        if not isinstance(paths, list) or not paths:
            raise pytest.UsageError(f"test group {group_name!r} has no paths")

        normalized_markers = tuple(dict.fromkeys(markers))
        for relative in paths:
            if not isinstance(relative, str):
                raise pytest.UsageError(f"test group {group_name!r} has a non-string path")
            path = Path(relative)
            if path.is_absolute() or len(path.parts) != 1 or not path.name.startswith("test_"):
                raise pytest.UsageError(f"test group {group_name!r} has unsafe path {relative!r}")
            resolved = (TEST_ROOT / path).resolve()
            if resolved in declared:
                raise pytest.UsageError(f"test file {relative!r} belongs to multiple groups")
            declared.add(resolved)
            if not resolved.is_file():
                raise pytest.UsageError(
                    f"test group {group_name!r} names missing file {relative!r}"
                )
            classified[resolved] = normalized_markers

    discovered = {path.resolve() for path in TEST_ROOT.glob("test_*.py")}
    unclassified = sorted(path.name for path in discovered - set(classified))
    if unclassified:
        raise pytest.UsageError(
            "tests/test-groups.json does not classify: " + ", ".join(unclassified)
        )

    return classified


CLASSIFIED_TESTS = _load_group_manifest()


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Attach centralized release-gate markers to collected test modules."""

    for item in items:
        markers = CLASSIFIED_TESTS.get(Path(str(item.path)).resolve(), ())
        for marker in markers:
            item.add_marker(getattr(pytest.mark, marker))
