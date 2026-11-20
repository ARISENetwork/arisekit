"""Generated ARISEKit benchmark factory."""

from pathlib import Path

from arisekit.benchmark import Benchmark
from arisekit.package import load_package
from arisekit.runner import RunnerConfig


HERE = Path(__file__).parent


def build() -> Benchmark:
    package = load_package(HERE / "package", verify_assets=True)
    return Benchmark.from_package(
        package,
        system_prompt='Return only the single reference label: A, B, or C.',
        runner_config=RunnerConfig(
        trials=1,
        threads=1,
        max_retries=1,
        retry_backoff=0.0,
        temperature=0.0,
        max_tokens=8,
        max_cost=1.0,
        max_cost_per_call=0.01,
        require_known_cost=True,
        max_calls=2,
        ),
    )
