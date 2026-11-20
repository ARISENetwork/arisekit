"""Anchored rubric judge over an agent trajectory.

TrajectoryJudge scores an agentic response the way a strict human reviewer
would: it reads the final answer (Trajectory.final_response) and the tool-use
behavior (Trajectory.turns), then rates the response on each rubric criterion
against calibration anchors. The anchored prompt defaults to a middle score,
demands quoted evidence, and allows half-point scores so similar cases still
separate. The logic is ported from arisekitai's lib/eval/judge.ts (the strict
Sonnet judge) and lib/eval/types.ts (weighted rubric criteria), translated to
ARISEKit types rather than copied verbatim.

Each criterion is a dict: ``{"name": str, "weight": float, "scale": "1-5" |
"pass-fail", "guidance": str}``. Scores normalize to 0..1 per criterion (1 to
5 maps via ``(s - 1) / 4``; pass-fail maps pass to 1 and fail to 0). The
scorer emits one metric per criterion plus a weighted ``overall``.

This is evidence assembly about response quality, not a pass-or-fail clearance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from arisekit.client import ModelClient
from arisekit.common.jsonio import outer_json_object
from arisekit.judges import _format_case
from arisekit.judges.base import ModelJudge
from arisekit.scorer import _response_text
from arisekit.types import BenchmarkItem, Metric, RunResult, Trajectory


@dataclass
class _Criterion:
    """One normalized rubric criterion the judge scores against."""

    name: str
    weight: float
    scale: str
    guidance: str


TRAJECTORY_JUDGE_PROMPT = """\
You are a strict, skeptical evaluator scoring a medical AI agent. Your job is
to discriminate: most real agents are mid-tier, so if everything you score is 4
to 5 you are not doing your job. Default to a middle score and require evidence
to move up or down. Use half-point scores (for example 3.5 or 4.5) so similar
cases can still separate.

Calibration anchors for 1-to-5 criteria:
- 5: exemplary. Hits every part of the expected behavior, cites specific data
  (values, dates, codes), and shows useful nuance beyond rote retrieval. Award
  sparingly: doing the task correctly is a 4, not a 5.
- 4: solid. Correct, grounded in the retrieved data, addresses the prompt, no
  fabrications. This is the normal score for "did what was asked correctly".
- 3: acceptable but flawed. A defensible answer with at least one real problem
  (a missing citation, a vague claim, partial coverage). This is your default
  starting point; move up only with evidence of quality.
- 2: substantively wrong, or missing a key fact or a critical part of the prompt.
- 1: harmful or absent. Fabricated data, unsafe advice, or no usable answer.

Calibration anchors for pass-fail criteria:
- pass: award ONLY if you can verify the criterion is fully met with no caveats.
- fail: any violation, partial miss, or unverifiable claim is a fail.

How to score:
- Verify against the trajectory, not the final answer alone. Every clinical
  claim must trace to a tool result in the trajectory; an unsupported claim is a
  fabrication.
- Quote specific text (5 to 15 words) from the answer or trajectory to justify
  any score below 5 or above 3.
- Do not give credit for things the agent did not do. Length is not quality.

Case (what the clinician asked):
{case}

Agent's trajectory (tool calls and tool results):
{trajectory}

Agent's final answer:
{answer}

Criteria to score:
{criteria}

Return ONLY a single-line JSON object mapping each criterion name to its score.
Use a number from 1 to 5 (half-points allowed) for 1-to-5 criteria, and the
string "pass" or "fail" for pass-fail criteria. For example:
{{"factuality": 4, "no_hallucination": "pass"}}
"""


def _to_criterion(spec: dict[str, Any]) -> _Criterion:
    """Coerce a user criterion dict into a normalized _Criterion."""
    return _Criterion(
        name=str(spec["name"]),
        weight=float(spec.get("weight", 1.0)),
        scale=str(spec.get("scale", "1-5")),
        guidance=str(spec.get("guidance", "")),
    )


def _render_criteria(criteria: list[_Criterion]) -> str:
    lines = [
        f'- "{c.name}" (scale: {c.scale}, weight: {c.weight}): {c.guidance}'.rstrip()
        for c in criteria
    ]
    return "\n".join(lines)


def _as_trajectory(response: Any) -> Trajectory | None:
    """Return the Trajectory backing a response, or None for plain text."""
    if isinstance(response, Trajectory):
        return response
    if isinstance(response, dict) and response.get("kind") == "trajectory":
        return Trajectory.from_dict(response)
    return None


def _summarize_trajectory(response: Any, *, limit: int = 800) -> str:
    """Serialize every turn (role and bounded content) for the judge."""
    trajectory = _as_trajectory(response)
    if trajectory is None or not trajectory.turns:
        return "(no trajectory recorded)"
    lines: list[str] = []
    for turn in trajectory.turns:
        if isinstance(turn.content, str):
            raw = turn.content
        else:
            raw = json.dumps(turn.content, default=str, sort_keys=True)
        if len(raw) > limit:
            raw = raw[:limit] + "..."
        lines.append(f"[{turn.role}] {raw}")
    return "\n".join(lines)


def _normalize(value: Any, scale: str) -> float | None:
    """Normalize one judge score to 0..1, or None if unusable.

    Pass-fail accepts "pass"/"fail" strings, booleans, or a 1 to 5 number
    (strict: only a clean 5 counts as a pass, mirroring the anchored prompt).
    A 1-to-5 criterion clamps to range and maps via ``(s - 1) / 4``.
    """
    if scale == "pass-fail":
        if isinstance(value, str):
            token = value.strip().lower()
            if token in ("pass", "passed", "yes", "true"):
                return 1.0
            if token in ("fail", "failed", "no", "false"):
                return 0.0
            try:
                num = float(token)
            except ValueError:
                return None
            return 1.0 if num >= 5 else 0.0
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None
        return 1.0 if num >= 5 else 0.0

    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    clamped = max(1.0, min(5.0, num))
    return (clamped - 1.0) / 4.0


def _parse_trajectory_scores(text: str, criteria: list[_Criterion]) -> dict[str, float]:
    """Pull a {criterion_name: normalized_score} dict out of judge text."""
    payload = outer_json_object(text) if text else None
    if not isinstance(payload, dict):
        return {}
    out: dict[str, float] = {}
    for c in criteria:
        if c.name not in payload:
            continue
        norm = _normalize(payload[c.name], c.scale)
        if norm is not None:
            out[c.name] = norm
    return out


class TrajectoryJudge(ModelJudge):
    """Anchored rubric judge for agentic (trajectory) responses.

    Each successful trial is shown the case, the trajectory (tool calls and
    results), and the final answer, then scored on every criterion. Per
    criterion the normalized scores average across trials into one metric
    (category "overall"). An additional "overall" metric is the weighted mean
    of the per-criterion averages by criterion weight. Errored trials are
    skipped, so ``n`` on the overall metric reports the count of graded trials.
    """

    call_id_prefix = "trajectory-judge"

    def __init__(
        self,
        *,
        judge_model: str,
        criteria: list[dict[str, Any]],
        client: ModelClient | None = None,
        temperature: float | None = 0.0,
    ):
        parsed = [_to_criterion(c) for c in criteria]
        super().__init__(judge_model=judge_model, client=client, temperature=temperature)
        self._criteria = parsed

    def _judge(self, item: BenchmarkItem, r: RunResult) -> dict[str, float]:
        prompt = TRAJECTORY_JUDGE_PROMPT.format(
            case=_format_case(item),
            trajectory=_summarize_trajectory(r.response),
            answer=_response_text(r),
            criteria=_render_criteria(self._criteria),
        )
        # A single failed judge call yields no scores for this trial; the
        # remaining trials still contribute to the averages.
        return _parse_trajectory_scores(self._ask(item, prompt), self._criteria)

    def score_item(self, item: BenchmarkItem, responses: list[RunResult]) -> list[Metric]:
        per_crit: dict[str, list[float]] = {c.name: [] for c in self._criteria}
        graded = 0
        for r in responses:
            if r.error is not None:
                continue
            graded += 1
            scores = self._judge(item, r)
            for c in self._criteria:
                if c.name in scores:
                    per_crit[c.name].append(scores[c.name])

        metrics: list[Metric] = []
        weighted_sum = 0.0
        total_weight = 0.0
        for c in self._criteria:
            values = per_crit[c.name]
            avg = sum(values) / len(values) if values else 0.0
            metrics.append(Metric(c.name, avg, category="overall", n=len(values)))
            if values:
                weighted_sum += avg * c.weight
                total_weight += c.weight

        overall = weighted_sum / total_weight if total_weight > 0 else 0.0
        metrics.append(Metric("overall", overall, category="overall", n=graded))
        return metrics


__all__ = ["TrajectoryJudge", "TRAJECTORY_JUDGE_PROMPT"]
