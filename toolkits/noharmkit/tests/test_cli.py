"""Command-line argument types: user input is rejected once, at the boundary."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from cases import each_case
from conftest import seed_case, synthetic_table
from test_e2e_score import synthetic_project

from pipeline.e2e.constants import KIT_ROOT
from pipeline.e2e import committee as cm
from pipeline.e2e import judge as judging
from pipeline.e2e.project import Project
from pipeline.skillrun import SkillOutcome
from tools import cli, noharm
from arisekit.common.hashing import json_sha256


def test_argument_types(tmp_path: Path) -> None:
    bad_case_ids = ["", "Syn002-1", "../Syn002", "/Syn002", "a/b", "a\\b", ".", "Syn002\n"]
    bad_labels = ["corpus", "latest", "run0", "run1\n", "reviewed-../x", "reviewed-D", "reviewed-",
                  "reviewed-dw\n", "reviewed-a", "reviewed-" + "a" * 33]
    cases: list[tuple[Callable[[str], object], str, object, str | None]] = [
        *[(cli.new_project, f"/tmp/{name}", None, "project name")
          for name in ["Bad Name", "../", "_hidden", "A", "x" * 65]],
        *[(cli.case_id, value, None, "case id") for value in bad_case_ids],
        (cli.case_id, "Ex001", None, "reserved Ex prefix"), (cli.case_id, "ExSynthetic", None, "reserved Ex prefix"),
        *[(cli.rubric_label, label, None, "rubric must be") for label in bad_labels],
        (cli.new_project, "projects/my-benchmark", Path("projects/my-benchmark"), None),
        (cli.case_id, "Case_001", "Case_001", None),
        (cli.rubric_label, "run1", "run1", None), (cli.rubric_label, "reviewed-dw", "reviewed-dw", None),
        (cli.rating_tag, "rand-quick", "rand-quick", None), (cli.positive_int, "3", 3, None),
    ]

    def run(case: tuple[Callable[[str], object], str, object, str | None]) -> None:
        convert, value, want, error = case
        if error is None:
            assert convert(value) == want
        else:
            with pytest.raises(argparse.ArgumentTypeError, match=error):
                convert(value)

    each_case(cases, lambda c: f"{c[0].__name__} {c[1]!r}", run)


def test_cli_rejects_before_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                 capsys: pytest.CaptureFixture[str]) -> None:
    cases: list[dict[str, Any]] = [
        {"label": "snapshot into its own folder", "argv": lambda root: ["snapshot", str(root), str(root / "backup")],
         "err": None, "absent": lambda root: [root / "backup"]},
        {"label": "judge codex with resume",
         "argv": lambda root: ["judge", str(root), "--backend", "codex", "--model", "gpt-6.1-sol", "--resume"],
         "err": None, "absent": lambda root: [root / "backup"]},
        {"label": "score has no trials option", "argv": lambda root: ["score", "unused", "--trials", "0"],
         "err": "unrecognized arguments: --trials 0", "absent": lambda root: []},
        {"label": "import without a case source", "argv": lambda root: ["import", str(root / "project"), "--case", "Syn002"],
         "err": "--cases-dir", "absent": lambda root: [root / "project"]},
        {"label": "public view has no dev flag", "argv": lambda root: ["view", "--dev"],
         "err": "unrecognized arguments: --dev", "absent": lambda root: []},
    ]
    monkeypatch.setattr(noharm, "load_env", lambda: None)

    def run(case: dict[str, Any]) -> None:
        root = tmp_path / case["label"].replace(" ", "-")
        root.mkdir()
        capsys.readouterr()
        monkeypatch.setattr(sys, "argv", ["noharm", *case["argv"](root)])
        with pytest.raises(SystemExit) as error:
            noharm.main()
        assert error.value.code == 2
        if case["err"] is not None:
            assert case["err"] in capsys.readouterr().err
        for path in case["absent"](root):
            assert not path.exists()

    each_case(cases, lambda c: c["label"], run)












def test_stage_cli_prints_receipts_and_exits_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    cases: list[dict[str, Any]] = [
        {"label": "judge pass", "stage": "judge", "failed": False},
        {"label": "judge failed", "stage": "judge", "failed": True},
        {"label": "rate failed", "stage": "rate", "status": "failed", "errors": ["committee quorum not met"]},
        {"label": "rate unresolved", "stage": "rate", "status": "unresolved", "errors": []},
        {"label": "rate pass with errors", "stage": "rate", "status": "pass", "errors": ["unresolved error"]},
    ]
    monkeypatch.setattr(noharm, "load_env", lambda: None)

    def run(case: dict[str, Any]) -> None:
        root = tmp_path / case["label"].replace(" ", "-")
        root.mkdir()
        capsys.readouterr()
        with pytest.MonkeyPatch.context() as mp:
            if case["stage"] == "judge":
                failed = case["failed"]
                _, record = synthetic_project(root)
                path = root / "results" / "judge" / "m.jsonl"
                if failed:
                    path.write_text(json.dumps({**record, "status": "fail", "errors": ["synthetic failure"]}) + "\n")
                mp.setattr(judging, "judge", lambda *args: [path])
                mp.setattr(sys, "argv", ["noharm", "judge", str(root)])
            else:
                failed = True
                seed_case(root)
                path = root / "rating.json"
                path.write_text(json.dumps({"status": case["status"], "errors": case["errors"],
                                            "raw": "Retained evidence"}))
                mp.setattr(cm, "rate", lambda *args: [path])
                mp.setattr(sys, "argv", ["noharm", "rate", str(root), "--case", "Syn002",
                                         "--rubric", "run1", "--backend", "claude"])
            before = path.read_bytes()
            if failed:
                with pytest.raises(SystemExit) as exc:
                    noharm.main()
                assert exc.value.code == 1
            else:
                noharm.main()
        captured = capsys.readouterr()
        assert str(path) in captured.out
        assert bool(captured.err) == failed
        if case["stage"] == "rate":
            assert "rate: failed or unresolved" in captured.err
        assert path.read_bytes() == before

    each_case(cases, lambda c: c["label"], run)


@pytest.mark.parametrize("flag", ["--rubric", "--table"])
def test_rating_cli_primary_name_and_legacy_alias_preserve_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str,
) -> None:
    seed_case(tmp_path)
    source = Project(tmp_path).artifact("Syn002", "run1")
    before = source.read_bytes()
    table = synthetic_table()
    output = {
        "usualCare": {"harm": "mild", "reason": "Synthetic rating"},
        "decisions": {d["id"]: {"harm": "mild", "reason": "Synthetic rating"}
                      for d in cm.rated_decisions(table)},
    }
    calls = []

    def offline_rating(name: str, *args: object, **kwargs: object) -> SkillOutcome:
        calls.append(name)
        return SkillOutcome("pass", output, json.dumps(output), [], {"backend": "offline"})

    monkeypatch.setattr(cm, "run_skill", offline_rating)
    monkeypatch.setattr(noharm, "load_env", lambda: None)
    committee = KIT_ROOT / "skills/rate-harm/committee.single-opus.json"
    monkeypatch.setattr(sys, "argv", ["noharm", "rate", str(tmp_path), "--case", "Syn002",
                                    flag, "run1", "--repeats", "1", "--committee", str(committee)])
    noharm.main()
    receipt = json.loads((tmp_path / "results/ratings/committee/Syn002.run1-rep1.json").read_text())
    assert calls == [cm.SKILL]
    assert receipt["status"] == "pass" and receipt["table"] == "run1"
    assert receipt["table_sha256"] == json_sha256(table)
    assert source.read_bytes() == before
