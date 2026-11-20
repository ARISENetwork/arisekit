"""Buyer-side comparative evaluation (DECIDE).

Run one identical rubric/case suite across several vendors or models and reduce
their per-criterion metrics into a ranked scorecard: per-criterion means with
confidence intervals, pairwise CI-overlap significance flags, and a weighted
composite. Pure and LLM-free; the output is decision-support evidence a human
owner interprets, not a certified recommendation.
"""

from __future__ import annotations

from arisekit.compare.scorecard import Cell, Scorecard, comparative_scorecard

__all__ = ["comparative_scorecard", "Scorecard", "Cell"]
