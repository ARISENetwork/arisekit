"""Project roots remain usable across the public naming migration."""
from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from cases import each_case

from pipeline.e2e import view
from pipeline.e2e.project import projects_root
from tools import noharm

RootCase = tuple[str, list[str], list[str], Callable[[Path], dict[str, str]], Callable[[Path], Path]]


def test_projects_root(tmp_path: Path) -> None:
    cases: list[RootCase] = [
        ("no folders", [], [], lambda base: {}, lambda base: base / "projects"),
        ("legacy casesets folder", ["casesets"], [], lambda base: {}, lambda base: base / "casesets"),
        ("projects folder", ["projects"], [], lambda base: {}, lambda base: base / "projects"),
        ("both folders", ["projects", "casesets"], [], lambda base: {}, lambda base: base / "projects"),
        ("legacy variable wins over folders", ["projects"], [],
         lambda base: {"NOHARM_CASESETS": str(base / "old-root")}, lambda base: base / "old-root"),
        ("projects variable wins over legacy variable", ["projects"], [],
         lambda base: {"NOHARM_PROJECTS": str(base / "new-root"), "NOHARM_CASESETS": str(base / "old-root")},
         lambda base: base / "new-root"),
        ("projects file does not hide legacy storage", ["casesets"], ["projects"], lambda base: {},
         lambda base: base / "casesets"),
        ("relative NOHARM_PROJECTS", [], [], lambda base: {"NOHARM_PROJECTS": "custom-projects"},
         lambda base: base / "custom-projects"),
        ("relative NOHARM_CASESETS", [], [], lambda base: {"NOHARM_CASESETS": "custom-projects"},
         lambda base: base / "custom-projects"),
    ]

    def run(case: RootCase) -> None:
        label, folders, files, env, expected = case
        base = tmp_path / label.replace(" ", "-")
        base.mkdir()
        for folder in folders:
            (base / folder).mkdir()
        for name in files:
            (base / name).write_text("unrelated file")
        assert projects_root(base, env(base)) == expected(base)

    each_case(cases, lambda c: c[0], run)


@pytest.mark.parametrize("explicit", [False, True])
def test_cli_view_resolves_root_and_keeps_explicit_path_authoritative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, explicit: bool,
) -> None:
    configured = tmp_path / "configured"
    selected = tmp_path / "selected"
    monkeypatch.setenv("NOHARM_PROJECTS", str(configured))
    monkeypatch.setenv("NOHARM_CASESETS", str(tmp_path / "legacy"))
    monkeypatch.setattr(noharm, "load_env", lambda: None)
    calls: list[Path] = []
    monkeypatch.setattr(view, "serve", lambda root, port: calls.append(root) or 0)
    monkeypatch.setattr(sys, "argv", ["noharm", "view", *([str(selected)] if explicit else [])])
    with pytest.raises(SystemExit) as exc:
        noharm.main()
    assert exc.value.code == 0
    assert calls == [selected if explicit else configured]


def test_explicit_view_path_overrides_inherited_root_configuration(tmp_path: Path) -> None:
    env = view.view_env(tmp_path, ["localhost"], {
        "NOHARM_PROJECTS": "/wrong/new", "NOHARM_CASESETS": "/wrong/old", "NOHARM_DEV": "1",
    })
    assert env["NOHARM_PROJECTS"] == env["NOHARM_CASESETS"] == str(tmp_path.resolve())
    assert "NOHARM_DEV" not in env
