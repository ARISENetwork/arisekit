"""Minimal reference benchmark.

5 fixed-answer general-knowledge items. Demonstrates the dataset +
scorer + run loop end-to-end with no external dependencies beyond
the model client. The exact_match scorer ignores case and surrounding
whitespace so the eval is tolerant of a model that says "Paris." vs
"paris".
"""

from pathlib import Path

from arisekit import Benchmark, Dataset, exact_match
from arisekit.runner import RunnerConfig

HERE = Path(__file__).parent


def build() -> Benchmark:
    dataset = Dataset.from_jsonl(
        HERE / "dataset.jsonl",
        system_prompt=(
            "You answer trivia questions tersely. Respond with only the "
            "literal answer — no preamble, no punctuation, no explanation."
        ),
        name="demo",
    )
    return Benchmark(
        name="demo",
        dataset=dataset,
        scorer=exact_match(),
        runner_config=RunnerConfig(trials=1, threads=2, max_retries=2),
    )
