"""noharm view: port check, links, environment, and no launch over a busy port."""
from __future__ import annotations

import os
import socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any

import pytest
from cases import each_case

from pipeline.e2e import view


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_serve_prints_links_and_launches_over_the_projects_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    app = tmp_path / "app"
    next_bin = app / "node_modules" / ".bin" / "next"
    next_bin.parent.mkdir(parents=True)
    next_bin.touch()
    projects = tmp_path / "projects"
    projects.mkdir()
    calls = []
    port = _free_port()
    monkeypatch.setenv("NOHARM_DEV", "1")
    monkeypatch.setattr(view, "APP_ROOT", app)
    monkeypatch.setattr(view.subprocess, "call", lambda cmd, cwd, env: calls.append((cmd, cwd, env)) or 0)
    assert view.serve(projects, port) == 0
    assert calls[0][0] == ["npm", "run", "build:portable"]
    cmd, cwd, env = calls[1]
    assert cmd == [str(next_bin), "dev", "--hostname", "127.0.0.1", "--port", str(port)] and cwd == app
    assert env["NOHARM_PROJECTS"] == str(projects.resolve()) and env["NOHARM_DEV_ORIGINS"] == "localhost"
    base = {key: value for key, value in os.environ.items() if key != "NOHARM_DEV"}
    assert env == {**base, "NOHARM_PROJECTS": str(projects.resolve()), "NOHARM_CASESETS": str(projects.resolve()),
                   "NOHARM_DEV_ORIGINS": "localhost"}
    assert "NOHARM_DEV" not in env
    assert capsys.readouterr().out == f"http://localhost:{port}/\n"


@contextmanager
def _busy_port() -> Iterator[int]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        yield s.getsockname()[1]


def test_serve_refuses_without_launching(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    cases: list[dict[str, Any]] = [
        {"label": "missing app dependencies", "app_root": True, "folder": "", "err": "npm ci",
         "port": lambda: nullcontext(_free_port())},
        {"label": "busy port", "app_root": False, "folder": "", "err": "in use", "port": _busy_port},
        {"label": "missing folder", "app_root": False, "folder": "nope", "err": None,
         "port": lambda: nullcontext(_free_port())},
    ]

    def run(case: dict[str, Any]) -> None:
        root = tmp_path / case["label"].replace(" ", "-")
        root.mkdir()
        capsys.readouterr()
        port_context: Callable[[], Any] = case["port"]
        with pytest.MonkeyPatch.context() as mp:
            if case["app_root"]:
                mp.setattr(view, "APP_ROOT", root)
            mp.setattr(view.subprocess, "call", lambda *a, **k: pytest.fail(f"launched with {case['label']}"))
            with port_context() as port:
                assert view.serve(root / case["folder"], port) == 1
        if case["err"] is not None:
            assert case["err"] in capsys.readouterr().err

    each_case(cases, lambda c: c["label"], run)
