from __future__ import annotations

import hashlib
import importlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType

import pytest
from cases import each_case

from pipeline.e2e import noharm_j22_loader as loader
from tools.noharm_science import score_text_rubric_v2 as legacy


def _inventory(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def test_concurrent_snapshot_import_preserves_legacy_namespace_and_payload() -> None:
    tools = importlib.import_module("tools")
    before_modules = {name: value for name, value in sys.modules.items()
                      if name == "tools" or name.startswith("tools.")}
    before_path = list(sys.path)
    before_files = _inventory(loader.ROOT)
    with ThreadPoolExecutor(max_workers=8) as workers:
        modules = list(workers.map(lambda _: loader.load_scorer(), range(24)))
    scorer = modules[0]
    assert isinstance(scorer, ModuleType)
    assert all(module is scorer for module in modules)
    assert scorer is not legacy
    assert scorer.ROOT == loader.ROOT
    assert scorer.PROFILE_DIR == loader.ROOT / "experiments/profiles/text-rubric-v2"
    assert scorer.legacy is scorer.v1.legacy
    assert scorer.legacy is not legacy.legacy
    assert importlib.import_module("tools") is tools
    assert sys.path == before_path
    assert {name: value for name, value in sys.modules.items()
            if name == "tools" or name.startswith("tools.")} == before_modules
    assert _inventory(loader.ROOT) == before_files
    assert not any(path.name == "__pycache__" for path in loader.ROOT.rglob("*"))
    assert legacy.ROOT != scorer.ROOT
    assert legacy.score_case_s2 is not scorer.score_case_s2


def test_payload_hash_is_verified_before_loading() -> None:
    cases = [
        ("tools/score_text_rubric_v2.py", "snapshot hash differs: tools/score_text_rubric_v2.py"),
        ("experiments/analyses/20261025-v34-e2e/judge-j2/rules.md", "snapshot hash differs: .*rules.md"),
    ]
    original = Path.read_bytes

    def run(case: tuple[str, str]) -> None:
        relative, match = case
        target = loader.ROOT / relative

        def changed(path: Path) -> bytes:
            data = original(path)
            return data + b"\n" if path == target else data

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(loader, "_SCORER", None)
            mp.setattr(Path, "read_bytes", changed)
            with pytest.raises(ValueError, match=match):
                loader.load_scorer()

    each_case(cases, lambda c: c[0], run)


def test_snapshot_contains_only_declared_source_files() -> None:
    manifest = json.loads((loader.ROOT / "PROVENANCE.json").read_text())
    assert manifest["commit"] == loader.SOURCE_COMMIT
    assert set(manifest["sha256"]) == loader.PAYLOAD
    assert set(_inventory(loader.ROOT)) == loader.PAYLOAD | {"PROVENANCE.json"}
