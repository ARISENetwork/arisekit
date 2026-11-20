"""Verify the immutable current-grading code snapshot (current judge rules and scorer) without accessing noharm-science."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

KIT = Path(__file__).resolve().parents[1]
SNAPSHOT = KIT / "vendor/noharm-science/c4c8091c4"
COMMIT = "c4c8091c486bd18fb83e76860c49f8d4b1666993"
PAYLOAD = {
    "tools/score_rubric.py",
    "tools/score_text_rubric.py",
    "tools/score_text_rubric_v2.py",
    "tools/score_text_rubric_f1.py",
    "experiments/profiles/text-rubric-v2/judge/schema.json",
    "experiments/freeze/pipeline-v1/config.json",
    "experiments/freeze/pipeline-v1/manifest.json",
    "experiments/freeze/pipeline-v1/judge/prompt.md",
    "experiments/freeze/pipeline-v1/judge/rules.md",
    "experiments/freeze/pipeline-v1/review/second.md",
    "experiments/freeze/pipeline-v1/review/severe3.md",
    "experiments/freeze/pipeline-v2/manifest.json",
}
MANIFESTS = ("experiments/freeze/pipeline-v1/manifest.json", "experiments/freeze/pipeline-v2/manifest.json")


def check() -> dict[str, Any]:
    provenance = json.loads((SNAPSHOT / "PROVENANCE.json").read_text())
    assert provenance["commit"] == COMMIT
    assert provenance["status"] == "draft"
    assert provenance["physician_review"] == "pending"
    assert provenance["read_only"] is True
    expected = provenance["sha256"]
    assert set(expected) == PAYLOAD, "Only scorer code, judge/review prompts, and grading setup manifests belong in this snapshot"
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

    matched = 0
    for manifest_name in MANIFESTS:
        listed = json.loads((SNAPSHOT / manifest_name).read_text())["sha256"]
        # Other keys are globs over case rubrics or files outside this snapshot.
        for name in sorted(PAYLOAD & set(listed)):
            if expected[name] != listed[name]:
                raise ValueError(f"Snapshot bytes differ from upstream manifest {manifest_name}: {name}")
            matched += 1

    # Use a fresh process so the toolkit's tools namespace cannot shadow this snapshot.
    sys.path.insert(0, str(KIT))
    from pipeline.e2e import noharm_p2_loader

    mods = noharm_p2_loader.load()
    assert mods.v2.ROOT == SNAPSHOT, "Imported the wrong scorer snapshot"
    assert mods.f1.v2 is mods.v2
    for name in ("validate", "project_for_judge", "judgment_errors", "rubric_sha256", "score_case_three"):
        assert callable(getattr(mods.v2, name)), f"Scorer helper missing: {name}"
    assert callable(mods.f1.three), "F1 helper missing: three"
    schema = json.loads((SNAPSHOT / "experiments/profiles/text-rubric-v2/judge/schema.json").read_text())
    assert schema == json.loads((mods.v2.PROFILE_DIR / "judge/schema.json").read_text())
    template = (SNAPSHOT / "experiments/freeze/pipeline-v1/judge/prompt.md").read_text()
    for name in ("judge_rules", "case", "table", "response"):
        assert "{{" + name + "}}" in template, f"Judge placeholder missing: {name}"

    return {"commit": COMMIT, "files_verified": len(expected), "manifest_entries_matched": matched,
            "scorer_imported": True, "case_rubrics_included": False, "status": provenance["status"]}


if __name__ == "__main__":
    print(json.dumps(check(), indent=2))
