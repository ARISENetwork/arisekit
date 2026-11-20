"""Red-team tooling: adversarial case mutation plus safety scorers.

A clinician turns their own cases into attack variants with `mutate`,
runs them through the ordinary Benchmark/runner, and grades the responses
with the safety scorers here. The whole flow assembles evidence for a
human owner to interpret; it never issues a pass/fail clearance.
"""

from __future__ import annotations

from arisekit.redteam.mutations import (
    STRATEGIES,
    AttackStrategy,
    mutate,
    register_strategy,
)
from arisekit.redteam.scorers import (
    HarmfulComplianceScorer,
    RefusalAppropriatenessScorer,
    RefusalScorer,
    is_refusal,
)

__all__ = [
    "mutate",
    "AttackStrategy",
    "STRATEGIES",
    "register_strategy",
    "is_refusal",
    "RefusalScorer",
    "RefusalAppropriatenessScorer",
    "HarmfulComplianceScorer",
]
