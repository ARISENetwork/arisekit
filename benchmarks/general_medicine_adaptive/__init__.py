"""Build the General Medicine Adaptive Consult-10 engineering pilot."""

from __future__ import annotations

from pathlib import Path

from arisekit import Benchmark, Dataset
from arisekit.runner import RunnerConfig

from .environment import patient_tools
from .scorer import AdaptiveConsultScorer
from .validation import assert_valid_items


HERE = Path(__file__).parent


def build() -> Benchmark:
    system_prompt = (HERE / "prompts" / "system.txt").read_text(encoding="utf-8")
    dataset = Dataset.from_jsonl(
        HERE / "data" / "items.synthetic.v1.jsonl",
        system_prompt=system_prompt,
        name="general-medicine-adaptive",
    )
    assert_valid_items(dataset)
    return Benchmark(
        name="general-medicine-adaptive",
        dataset=dataset,
        scorer=AdaptiveConsultScorer(),
        tools=patient_tools(dataset),
        max_turns=8,
        runner_config=RunnerConfig(
            trials=1,
            threads=1,
            max_retries=2,
            temperature=0.0,
        ),
    )


__all__ = ["build"]
