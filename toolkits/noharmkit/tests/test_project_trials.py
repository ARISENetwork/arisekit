"""Response collection honors the project trial count."""
from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from cases import each_case

from pipeline.e2e.project import Project
from tools import run_inference


def project_with_item(tmp_path: Path, trials: int) -> Path:
    project=tmp_path / "collected"
    Project.create(project, trials=trials)
    (project / "items.jsonl").write_text(json.dumps({"id":"Test001", "prompt":"Synthetic task"}) + "\n")
    return project


def collect(project: Path, model: str, monkeypatch: pytest.MonkeyPatch, trials: int | None = None) -> None:
    monkeypatch.setattr(run_inference, "load_env", lambda: None)
    monkeypatch.setattr(sys, "argv", ["run_inference", str(project), "--model", model,
        *([] if trials is None else ["--trials", str(trials)])])
    run_inference.main()


def _answer(model: str) -> object:
    return lambda prompt: ("answer", 0, {})


def _count_changed_after_collection(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_inference, "litellm_completion", _answer)
    collect(project, "m", monkeypatch, trials=2)
    assert Project(project).trials() == 2


def _failure_record(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt = project / "results/responses/m.jsonl"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"id":"Test001","trial":1,"response":null,"error":"synthetic"}\n')


def _duplicate_successes(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_inference, "litellm_completion", _answer)
    collect(project, "m", monkeypatch)
    receipt = project / "results/responses/m.jsonl"
    receipt.write_text(receipt.read_text() + receipt.read_text().splitlines()[0] + "\n")


TrialRefusal = tuple[str, int, Callable[[Path, pytest.MonkeyPatch], None], int | None, int]


def test_collection_refusals_before_client(tmp_path: Path) -> None:
    cases: list[TrialRefusal] = [
        ("count changed after collection", 1, _count_changed_after_collection, 3, 2),
        ("failure record locks the count", 2, _failure_record, 1, 2),
        ("duplicate successes", 2, _duplicate_successes, None, 2),
    ]

    def run(case: TrialRefusal) -> None:
        label, declared, setup, refused, trials = case
        base = tmp_path / label.replace(" ", "-")
        base.mkdir()
        project = project_with_item(base, declared)
        with pytest.MonkeyPatch.context() as mp:
            setup(project, mp)
            receipt = project / "results/responses/m.jsonl"
            before = receipt.read_bytes()
            provenance = (project / "provenance.json").read_bytes()
            mp.setattr(run_inference, "litellm_completion", lambda model: pytest.fail("constructed client"))
            with pytest.raises(SystemExit) as exc:
                collect(project, "m", mp, trials=refused)
        assert exc.value.code == 2
        assert receipt.read_bytes() == before and (project / "provenance.json").read_bytes() == provenance
        assert Project(project).trials() == trials

    each_case(cases, lambda c: c[0], run)


def test_collecting_another_model_keeps_existing_expectations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project=project_with_item(tmp_path, 2)
    monkeypatch.setattr(run_inference, "litellm_completion", lambda model: lambda prompt: ("answer",0,{}))
    collect(project, "first", monkeypatch)
    before=(project / "results/responses/first.jsonl").read_bytes()
    collect(project, "second", monkeypatch)
    provenance=json.loads((project / "provenance.json").read_text())
    assert provenance["models"]==["first","second"] and provenance["trials"]==2
    assert (project / "results/responses/first.jsonl").read_bytes()==before
