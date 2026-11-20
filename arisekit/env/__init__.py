"""Environment primitives for agentic ARISEKit benchmarks.

An environment is the world an agent acts on: a stateful sandbox the run
loop reads from and writes to across a trajectory. The first primitive is
a copy-on-write in-memory FHIR R4 store plus a small tool catalog over it,
so a benchmark can hand an agent a patient chart and grade the tool-use
path it takes.

    from arisekit.env import FHIREnvironment, fhir_tools
    env = FHIREnvironment.from_cohort_dir("cohorts/diabetes")
    tools = fhir_tools(env)
"""

from __future__ import annotations

from arisekit.env.fhir import FHIREnvironment, fhir_tools

__all__ = ["FHIREnvironment", "fhir_tools"]
