"""Verify the immutable code snapshot of the earlier judge rules and scorer without accessing noharm-science."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SNAPSHOT = Path(__file__).resolve().parents[1] / "vendor/noharm-science/d734383670f0"
COMMIT = "d734383670f0e8251f46fc3e800038f2a46db0d6"
PAYLOAD = {
    "tools/score_rubric.py",
    "tools/score_text_rubric.py",
    "tools/score_text_rubric_v2.py",
    "experiments/profiles/text-rubric-v2/judge/schema.json",
    "experiments/analyses/20261025-v34-e2e/judge-j2/prompt.md",
    "experiments/analyses/20261025-v34-e2e/judge-j2/rules.md",
    "experiments/analyses/20261025-v34-e2e/judge-j2/schema.json",
}


def check() -> dict[str, Any]:
    provenance = json.loads((SNAPSHOT / "PROVENANCE.json").read_text())
    assert provenance["commit"] == COMMIT
    assert provenance["status"] == "draft"
    assert provenance["physician_review"] == "pending"
    assert provenance["read_only"] is True
    expected = provenance["sha256"]
    assert set(expected) == PAYLOAD, "Only judge/scorer code and required schemas belong in this snapshot"
    actual: set[str] = set()
    for path in SNAPSHOT.rglob("*"):
        if "holdout" in str(path).lower():
            raise ValueError("Excluded path encountered; verification stopped")
        if path.is_symlink():
            raise ValueError("Snapshot must not contain symlinks")
        if path.is_file():
            actual.add(path.relative_to(SNAPSHOT).as_posix())
    assert actual == {*expected, "PROVENANCE.json"}, "Snapshot inventory differs from provenance"
    for name, digest in expected.items():
        assert hashlib.sha256((SNAPSHOT / name).read_bytes()).hexdigest() == digest, f"Snapshot bytes differ: {name}"

    # Use a fresh process so the historical toolkit's tools namespace cannot shadow this snapshot.
    sys.path.insert(0, str(SNAPSHOT))
    from tools import score_text_rubric_v2 as scorer

    assert scorer.ROOT == SNAPSHOT, "Imported the wrong scorer snapshot"
    assert (scorer.PROFILE_DIR / "judge/schema.json").is_file()
    for name in ("validate", "project_for_judge", "judgment_errors", "rubric_sha256", "score_case_s2"):
        assert callable(getattr(scorer, name)), f"Scorer helper missing: {name}"
    judge = SNAPSHOT / "experiments/analyses/20261025-v34-e2e/judge-j2"
    assert "J2.2" in (judge / "rules.md").read_text()
    schema = json.loads((judge / "schema.json").read_text())
    assert schema == json.loads((scorer.PROFILE_DIR / "judge/schema.json").read_text())
    template = (judge / "prompt.md").read_text()
    for name in ("judge_rules", "schema", "case", "table", "response"):
        assert "{{" + name + "}}" in template, f"Judge placeholder missing: {name}"

    return {"commit": COMMIT, "files_verified": len(expected), "scorer_imported": True,
            "case_rubrics_included": False,
            "judge_schema_matches_profile": True, "status": provenance["status"]}


if __name__ == "__main__":
    report = check()
    print(json.dumps(report, indent=2))
