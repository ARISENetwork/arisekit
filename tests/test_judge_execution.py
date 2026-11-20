"""Offline protocol tests for pluggable blinded judge execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from arisekit.judge_execution import (
    BlindedJudgeResponse,
    execute_blinded_judges,
)
from arisekit.evaluation.noharm_judge_contract import canonical_noharm_panel_entry


def _sha_json(value) -> str:
    rendered = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _panel():
    return [
        {
            "id": f"judge-{index}",
            "model": f"offline/judge-{index}",
            "provider": "offline",
            "expected_provider_model": f"offline/judge-{index}",
            "family": f"judge-family-{index}",
            "settings": {"temperature": 0},
        }
        for index in (1, 2)
    ]


def _inputs(path: Path) -> Path:
    rows = []
    for index in (1, 2):
        response = f"Blinded clinical response {index}"
        rows.append(
            {
                "schema_version": "arisekit.noharm-parity-judge-input.v1",
                "opaque_id": "jh_" + str(index) * 64,
                "binding_digest": str(index + 2) * 64,
                "response_sha256": _sha_json(response),
                "case": {
                    "prompt": f"Blinded case {index}",
                    "rubric": {"options": [{"id": 1, "text": "Act"}]},
                    "guidance": {"spirit": "Match clinically equivalent actions."},
                },
                "response": response,
            }
        )
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


class OfflineAdapter:
    def __init__(self, panel_record, *, fail_once: bool = False):
        self.panel_record = panel_record
        self.fail_once = fail_once
        self.calls = []

    def __call__(self, call):
        self.calls.append(call)
        assert not hasattr(call, "arm")
        assert not hasattr(call, "model_id")
        assert not hasattr(call, "item_id")
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("offline interruption")
        return BlindedJudgeResponse(
            metrics={"F1_weighted": 0.8},
            provider=self.panel_record["provider"],
            model=self.panel_record["model"],
            provider_model=self.panel_record["expected_provider_model"],
            provider_response_ids=(f"response-{len(self.calls)}",),
            cost_usd=0.1,
        )


def test_blinded_execution_checkpoints_and_resumes_without_private_identity(
    tmp_path: Path,
) -> None:
    panel = _panel()
    source = _inputs(tmp_path / "judge-input.jsonl")
    output = tmp_path / "judged.jsonl"
    first_adapters = {
        panel[0]["id"]: OfflineAdapter(panel[0]),
        panel[1]["id"]: OfflineAdapter(panel[1], fail_once=True),
    }
    with pytest.raises(RuntimeError, match="offline interruption"):
        execute_blinded_judges(
            source,
            judge_panel=panel,
            judge_runtime_hash="a" * 64,
            adapters=first_adapters,
            adapter_ids={"judge-1": "offline:v1", "judge-2": "offline:v1"},
            output_path=output,
            max_cost_usd=1.0,
            max_calls=10,
        )
    assert len(output.read_text(encoding="utf-8").splitlines()) == 1

    resumed_adapters = {record["id"]: OfflineAdapter(record) for record in panel}
    summary = execute_blinded_judges(
        source,
        judge_panel=panel,
        judge_runtime_hash="a" * 64,
        adapters=resumed_adapters,
        adapter_ids={"judge-1": "offline:v1", "judge-2": "offline:v1"},
        output_path=output,
        max_cost_usd=1.0,
        max_calls=10,
    )
    assert summary.complete is True
    assert summary.expected == 4
    assert summary.completed == 4
    assert summary.skipped == 1
    assert summary.calls_made == 3
    assert summary.cost_usd == pytest.approx(0.4)
    assert sum(len(adapter.calls) for adapter in resumed_adapters.values()) == 3
    rows = [
        json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()
    ]
    assert all(row["schema_version"].endswith("judged-result.v1") for row in rows)
    assert all(row["judge_provenance"]["provider_response_ids"] for row in rows)

    again = execute_blinded_judges(
        source,
        judge_panel=panel,
        judge_runtime_hash="a" * 64,
        adapters=resumed_adapters,
        adapter_ids={"judge-1": "offline:v1", "judge-2": "offline:v1"},
        output_path=output,
        max_cost_usd=1.0,
        max_calls=10,
    )
    assert again.skipped == 4
    assert again.calls_made == 0


def test_blinded_execution_enforces_call_cap_and_provider_identity(
    tmp_path: Path,
) -> None:
    panel = _panel()
    source = _inputs(tmp_path / "judge-input.jsonl")
    adapters = {record["id"]: OfflineAdapter(record) for record in panel}
    limited = execute_blinded_judges(
        source,
        judge_panel=panel,
        judge_runtime_hash="b" * 64,
        adapters=adapters,
        adapter_ids={"judge-1": "offline:v1", "judge-2": "offline:v1"},
        output_path=tmp_path / "limited.jsonl",
        max_cost_usd=1.0,
        max_calls=2,
    )
    assert limited.complete is False
    assert limited.budget_exhausted is True
    assert limited.completed == 2

    class WrongProvider(OfflineAdapter):
        def __call__(self, call):
            produced = super().__call__(call)
            return BlindedJudgeResponse(
                metrics=produced.metrics,
                provider=produced.provider,
                model=produced.model,
                provider_model="unfrozen/provider-alias",
                provider_response_ids=produced.provider_response_ids,
                cost_usd=produced.cost_usd,
            )

    wrong = {
        panel[0]["id"]: WrongProvider(panel[0]),
        panel[1]["id"]: OfflineAdapter(panel[1]),
    }
    with pytest.raises(ValueError, match="unexpected provider_model"):
        execute_blinded_judges(
            source,
            judge_panel=panel,
            judge_runtime_hash="c" * 64,
            adapters=wrong,
            adapter_ids={"judge-1": "offline:v1", "judge-2": "offline:v1"},
            output_path=tmp_path / "wrong.jsonl",
            max_cost_usd=1.0,
            max_calls=10,
        )


def test_generic_per_record_executor_rejects_canonical_composite(
    tmp_path: Path,
) -> None:
    panel = [
        canonical_noharm_panel_entry(
            judge_assets_sha256="1" * 64,
            runtime_dependency_lock_sha256="2" * 64,
            match_prompt_sha256="3" * 64,
            review_prompt_sha256="4" * 64,
        )
    ]
    with pytest.raises(ValueError, match="cohort-pooled canonical batch"):
        execute_blinded_judges(
            _inputs(tmp_path / "judge-input.jsonl"),
            judge_panel=panel,
            judge_runtime_hash="5" * 64,
            adapters={"noharm-v2-canonical": OfflineAdapter(panel[0])},
            adapter_ids={"noharm-v2-canonical": "offline:v1"},
            output_path=tmp_path / "judged.jsonl",
            max_cost_usd=1.0,
            max_calls=10,
        )
