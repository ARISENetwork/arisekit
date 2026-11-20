"""Self-contained nonclinical fixtures for public toolkit tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.e2e.project import Project

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"

def synthetic_table() -> dict:
    return json.loads((SYNTHETIC / "table.json").read_text())

def tagged_synthetic_table() -> dict[str, Any]:
    table = synthetic_table()
    for decision in table["decisions"]:
        for row in decision["recommendations"]:
            row["tags"] = ["none"]
    return table

def seed_case(root: Path, *, with_table: bool = True) -> None:
    Project(root).import_case("Syn002", SYNTHETIC)
    if not with_table:
        return
    Project(root).artifact("Syn002", "run1").parent.mkdir(parents=True, exist_ok=True)
    Project(root).artifact("Syn002", "run1").write_text(json.dumps(synthetic_table()))
    Project(root).artifact("Syn002", "run1", "status.json").write_text('{"status":"pass"}')
