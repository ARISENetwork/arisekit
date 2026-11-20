"""CLI bookkeeping includes both legacy and manifested run layouts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import arisekit.cli as cli
from arisekit.cli import cmd_cost, cmd_eval


def _checkpoint(
    path: Path,
    cost: float,
    *,
    item_id: str | None = None,
    trial: int | None = None,
    append: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"metadata": {"cost": cost}}
    if item_id is not None:
        payload["id"] = item_id
    if trial is not None:
        payload["trial"] = trial
    with path.open("a" if append else "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def test_cost_discovers_manifest_namespaced_checkpoints(tmp_path: Path, capsys):
    _checkpoint(tmp_path / "raw" / "legacy" / "model.jsonl", 0.25)
    _checkpoint(
        tmp_path / "raw" / "noharm" / ("a" * 64) / "model.jsonl",
        0.75,
    )

    assert cmd_cost(argparse.Namespace(results_dir=str(tmp_path))) == 0

    output = capsys.readouterr().out
    assert "legacy/model: $0.2500" in output
    assert f"noharm/{'a' * 64}/model: $0.7500" in output
    assert "total: $1.0000" in output


def test_cost_counts_only_latest_final_row_per_item_trial(tmp_path: Path, capsys):
    path = tmp_path / "raw" / "agentic" / "model.jsonl"
    _checkpoint(path, 0.20, item_id="case-1", trial=1)
    _checkpoint(path, 0.35, item_id="case-1", trial=1, append=True)
    _checkpoint(path, 0.40, item_id="case-1", trial=2, append=True)
    _checkpoint(path, 0.50, item_id="case-2", trial=1, append=True)

    assert cmd_cost(argparse.Namespace(results_dir=str(tmp_path))) == 0

    output = capsys.readouterr().out
    assert "agentic/model: $1.2500" in output
    assert "total: $1.2500" in output


def test_cost_ignores_sibling_turn_journal(tmp_path: Path, capsys):
    final_path = tmp_path / "raw" / "agentic" / "model.jsonl"
    turn_path = tmp_path / "raw" / "agentic" / "model.turns.jsonl"
    _checkpoint(final_path, 0.75, item_id="case-1", trial=1)
    _checkpoint(turn_path, 0.25, item_id="case-1", trial=1)
    _checkpoint(turn_path, 0.50, item_id="case-1", trial=1, append=True)

    assert cmd_cost(argparse.Namespace(results_dir=str(tmp_path))) == 0

    output = capsys.readouterr().out
    assert "agentic/model: $0.7500" in output
    assert "model.turns" not in output
    assert "total: $0.7500" in output


def test_eval_enables_automatic_manifest(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    captured: dict[str, object] = {}

    class FakeBenchmark:
        def run(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                benchmark="fixture",
                model="provider/model",
                summary=SimpleNamespace(
                    completed=1,
                    errored=0,
                    skipped=0,
                    cost_total=0.0,
                    output_path=tmp_path / "raw.jsonl",
                    manifest_digest="a" * 64,
                ),
                metrics=[],
            )

    monkeypatch.setattr(cli, "_load_benchmark", lambda name, root: FakeBenchmark())
    args = argparse.Namespace(
        benchmarks_dir=str(tmp_path),
        results_dir=str(tmp_path),
        name="fixture",
        model="provider/model",
        trials=2,
        threads=3,
        limit=4,
        bootstrap=0,
    )

    assert cmd_eval(args) == 0

    assert captured["auto_manifest"] is True
    assert captured["model"] == "provider/model"
    assert "manifest: " + "a" * 64 in capsys.readouterr().out
