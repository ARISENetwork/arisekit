from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from pipeline.e2e import noharm_p2_loader


def test_judge_scorer_snapshot_hashes_import_and_no_case_data() -> None:
    toolkit = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-I", "-B", str(toolkit / "tools/check_noharm_science_vendor.py")],
        check=True, capture_output=True, text=True,
    )
    report = json.loads(completed.stdout)
    assert report["files_verified"] == 7
    assert report["case_rubrics_included"] is False
    assert report["scorer_imported"] is True
    assert report["judge_schema_matches_profile"] is True
    assert report["status"] == "draft"


def test_payload_matches_manifests_in_isolated_process() -> None:
    toolkit = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-I", "-B", str(toolkit / "tools/check_noharm_science_vendor_p2.py")],
        check=True, capture_output=True, text=True,
    )
    report = json.loads(completed.stdout)
    assert report["commit"].startswith("c4c8091c4")
    assert report["manifest_entries_matched"] == 11  # 9 listed by the earlier grading manifest, 2 by the current grading manifest
    assert report["case_rubrics_included"] is False


def test_loader_isolates_modules() -> None:
    mods = noharm_p2_loader.load()
    assert mods.v2.ROOT == noharm_p2_loader.ROOT
    assert mods.f1.v2 is mods.v2
    assert callable(mods.v2.score_case_three) and callable(mods.f1.three)
    from tools.noharm_science import score_text_rubric_v2 as legacy
    assert legacy is not mods.v2
    assert noharm_p2_loader.load() is mods
