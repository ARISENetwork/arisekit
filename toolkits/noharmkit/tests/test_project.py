"""Project storage: creation, case import, trial counts, and rubric selection."""
from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from cases import each_case

from pipeline.e2e.project import Project
from tools import noharm
from arisekit.common.jsonio import read_jsonl

ITEM = {"id": "Syn002", "prompt": "P?", "metadata": {
    "base_id": "Syn002", "perturb_id": None, "category": "baseline", "candidate_id": None, "open": False}}


@pytest.fixture
def cases_dir(tmp_path: Path) -> Path:
    d = tmp_path / "cases"
    d.mkdir()
    (d / "Syn002.json").write_text(json.dumps({"presentation": "P?", "recommendations": "R."}))
    return d


def cli(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    monkeypatch.setattr(noharm, "load_env", lambda: None)
    monkeypatch.setattr(sys, "argv", ["noharm", *argv])
    noharm.main()


def test_create_writes_empty_project_and_refuses_existing(tmp_path: Path) -> None:
    root = tmp_path / "new-project"
    project = Project.create(root, trials=3)
    assert (root / "cases").is_dir() and read_jsonl(root / "items.jsonl") == []
    provenance = project.provenance()
    assert provenance["caseset_name"] == "new-project" and provenance["cases"] == []
    assert provenance["created_at"] and project.trials() == 3
    before = project.provenance_path.read_bytes()
    with pytest.raises(FileExistsError):
        Project.create(root)
    assert project.provenance_path.read_bytes() == before


@pytest.mark.parametrize("value", [0, True, 1.0, "2"])
def test_invalid_trial_counts_are_rejected(tmp_path: Path, value: object) -> None:
    Project(tmp_path).update_provenance(trials=value)
    with pytest.raises(ValueError, match="positive integer"):
        Project(tmp_path).trials()


def test_trials_default_to_one_and_invalid_cli_count_creates_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert Project(tmp_path).trials() == 1
    root = tmp_path / "not-created"
    with pytest.raises(SystemExit) as exc:
        cli(monkeypatch, "create", str(root), "--trials", "0")
    assert exc.value.code == 2 and not root.exists()


def test_import_writes_once_and_refuses_changes(tmp_path: Path, cases_dir: Path) -> None:
    project = Project(tmp_path / "set")
    project.import_case("Syn002", cases_dir)
    assert project.case("Syn002")["recommendations"] == "R."
    assert project.items() == [ITEM]  # the solution never reaches model inputs
    assert project.provenance()["cases"] == ["Syn002"]
    paths = [project.root / "cases/Syn002.json", project.items_path, project.provenance_path]
    before = [path.read_bytes() for path in paths]
    project.import_case("Syn002", cases_dir)  # idempotent
    assert [path.read_bytes() for path in paths] == before
    (cases_dir / "Syn002.json").write_text(json.dumps({"presentation": "Changed", "recommendations": "R."}))
    with pytest.raises(ValueError, match="new project/run"):
        project.import_case("Syn002", cases_dir)
    assert [path.read_bytes() for path in paths] == before


@pytest.mark.parametrize("item_flag,source_flag", [("--item", "--inputs-dir"), ("--case", "--cases-dir")])
def test_cli_import_flag_aliases(tmp_path: Path, cases_dir: Path, monkeypatch: pytest.MonkeyPatch,
                                 item_flag: str, source_flag: str) -> None:
    root = tmp_path / "benchmark"
    Project.create(root)
    cli(monkeypatch, "import", str(root), item_flag, "Syn002", source_flag, str(cases_dir))
    assert Project(root).items() == [ITEM]


def _invalid_field(field: str, value: object) -> Callable[[Path, Path], tuple[Path, str, Callable[[], bool]]]:
    def setup(base: Path, cases_dir: Path) -> tuple[Path, str, Callable[[], bool]]:
        source = cases_dir / "Syn002.json"
        source.write_text(json.dumps({**json.loads(source.read_text()), field: value}))
        return base / "set", "Syn002", lambda: not (base / "set").exists()
    return setup


def _source_symlink(base: Path, cases_dir: Path) -> tuple[Path, str, Callable[[], bool]]:
    outside = base / "outside.json"
    outside.write_text(json.dumps({"presentation": "P?", "recommendations": "R."}))
    (cases_dir / "Other.json").symlink_to(outside)
    return base / "set", "Other", lambda: not (base / "set").exists()


def _redirected(name: str) -> Callable[[Path, Path], tuple[Path, str, Callable[[], bool]]]:
    def setup(base: Path, cases_dir: Path) -> tuple[Path, str, Callable[[], bool]]:
        root = base / "set"
        root.mkdir()
        outside = base / "outside.json"
        outside.write_text("unchanged")
        (root / name).symlink_to(outside)
        return root, "Syn002", lambda: outside.read_text() == "unchanged" and not (root / "cases").exists()
    return setup


ImportRefusal = tuple[str, Callable[[Path, Path], tuple[Path, str, Callable[[], bool]]], str]


def test_import_refused_before_writes(tmp_path: Path) -> None:
    cases: list[ImportRefusal] = [
        ("presentation null", _invalid_field("presentation", None), "nonempty text"),
        ("presentation blank", _invalid_field("presentation", " "), "nonempty text"),
        ("recommendations empty", _invalid_field("recommendations", ""), "nonempty text"),
        ("recommendations list", _invalid_field("recommendations", ["R."]), "nonempty text"),
        ("source symlink leaves the folder", _source_symlink, "leaves"),
        ("items.jsonl redirected", _redirected("items.jsonl"), "leaves the selected project"),
        ("provenance.json redirected", _redirected("provenance.json"), "leaves the selected project"),
    ]

    def run(case: ImportRefusal) -> None:
        label, setup, match = case
        base = tmp_path / label.replace(" ", "-")
        cases_dir = base / "cases"
        cases_dir.mkdir(parents=True)
        (cases_dir / "Syn002.json").write_text(json.dumps({"presentation": "P?", "recommendations": "R."}))
        root, case_id, unchanged = setup(base, cases_dir)
        with pytest.raises(ValueError, match=match):
            Project(root).import_case(case_id, cases_dir)
        assert unchanged()

    each_case(cases, lambda c: c[0], run)


def _save_table(project: Project, label: str, status: str) -> None:
    path = project.artifact("Syn002", label)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = {"caseId": "Syn002"}
    path.write_text(json.dumps(table if label.startswith("run") else {
        "record": table, "basedOn": {"version": "run1", "sha256": "x"}, "reviewer": "dw",
        "timing": {}, "savedAt": "2026-09-28T00:00:00Z"}))
    project.artifact("Syn002", label, "status.json").write_text(json.dumps({"status": status, "errors": []}))


@pytest.mark.parametrize("label", ["run1", "reviewed-dw"])
def test_table_loads_passing_and_refuses_failed(tmp_path: Path, label: str) -> None:
    project = Project(tmp_path)
    _save_table(project, label, "pass")
    assert project.table("Syn002", label) == {"caseId": "Syn002"}
    _save_table(project, label, "failed")
    with pytest.raises(ValueError, match=f"{label} failed validation"):
        project.table("Syn002", label)
