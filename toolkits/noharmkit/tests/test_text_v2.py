import json
from pathlib import Path

import pytest
from conftest import seed_case

from pipeline.e2e.import_rubric import import_rubric
from pipeline.e2e.project import Project

FIXTURES = Path(__file__).parent / "fixtures/text-v2/rubric-text-v2-parity.json"
EXAMPLES = {row["name"]: row for row in json.loads(FIXTURES.read_text())["cases"]}


@pytest.fixture
def project(tmp_path: Path) -> Project:
    seed_case(tmp_path, with_table=False)
    return Project(tmp_path)


def write_source(project: Project, name: str) -> Path:
    path = project.root / "rubric.json"
    path.write_text(json.dumps({**EXAMPLES[name]["case"], "caseId": "Syn002"}))
    return path


@pytest.mark.parametrize("example,status", [
    ("no counseling criterion is valid (D160)", "pass"),
    ("draft nulls and unresolved notes", "draft"),
    ("valid synthetic case", "draft"),  # Legacy counseling requires migration before scoring.
])
def test_import_records_scoring_status(project: Project, example: str, status: str) -> None:
    source = write_source(project, example)
    import_rubric(project, "Syn002", source)
    receipt = json.loads(project.artifact("Syn002", "run1", "status.json").read_text())
    assert receipt["status"] == status
    assert receipt["authority"] == "imported"
    assert receipt["warnings"] == EXAMPLES[example]["draft"]["warnings"]
    errors = list(EXAMPLES[example]["scoring"]["errors"])
    if status == "draft":
        errors.append("Scoring needs the current rubric format; rebuild the legacy counseling criterion first")
    assert receipt["scoringErrors"] == errors
    assert json.loads(project.artifact("Syn002", "run1").read_text()) == json.loads(source.read_text())


def test_invalid_rubric_import_leaves_no_artifacts(project: Project) -> None:
    source = write_source(project, "unknown kind")
    with pytest.raises(ValueError, match="kind must be one of"):
        import_rubric(project, "Syn002", source)
    assert not project.artifact("Syn002", "run1").parent.exists()
