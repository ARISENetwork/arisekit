"""Scorers turn (item, [run_result_per_trial]) into a list of Metrics.

Subclass BaseScorer for anything specialized (NOHARM rubric panels,
SCT concordance, MedAgent pass@1). Built-in factories cover the small
cases: exact match, substring, choice/regex, numeric tolerance.

Scorers compose via compose_scorers — each subscorer runs on the same
inputs and contributes its metrics to the combined output.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arisekit.common.jsonio import canonical_json as _canonical_json
from arisekit.common.stats import mean
from arisekit.types import BenchmarkItem, Metric, RunResult


SCORER_IDENTITY_SCHEMA_VERSION = "arisekit.scorer-identity.v1"


@dataclass(frozen=True)
class ScorerIdentity:
    """Content identity for a scorer that is safe to replay offline."""

    qualified_name: str
    source_sha256: str
    configuration: dict[str, Any]
    schema_version: str = SCORER_IDENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCORER_IDENTITY_SCHEMA_VERSION:
            raise ValueError("unsupported scorer identity schema")
        if not isinstance(self.qualified_name, str) or not self.qualified_name:
            raise ValueError("scorer qualified name must be non-empty")
        if (
            not isinstance(self.source_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.source_sha256) is None
        ):
            raise ValueError("scorer source_sha256 must be a lowercase SHA-256")
        if not isinstance(self.configuration, Mapping):
            raise ValueError("scorer configuration must be a JSON object")
        object.__setattr__(
            self,
            "configuration",
            _json_object(self.configuration, "scorer configuration"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "qualified_name": self.qualified_name,
            "source_sha256": self.source_sha256,
            "configuration": json.loads(_canonical_json(self.configuration)),
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()


class BaseScorer(ABC):
    """Score the run results for one item against its ground truth.

    `responses` always contains every successful trial for one item.
    Implementations should average or otherwise reduce across trials
    and return one Metric per dimension being measured.
    """

    # Persistent re-scoring is opt-in. Custom scorers must assert that their
    # result is a deterministic function of the captured item and responses.
    rescore_safe: bool | None = None

    @abstractmethod
    def score_item(
        self,
        item: BenchmarkItem,
        responses: list[RunResult],
    ) -> list[Metric]:
        ...

    # Convenience: scorers that need to look at the dataset's system
    # prompt can override this; default is a no-op.
    def configure(self, *, system_prompt: str | None = None) -> None:  # noqa: B027
        return None

    def configuration(self) -> Mapping[str, Any]:
        """Return all material scorer settings for persistent identity.

        The default deliberately refuses to guess from ``vars(self)`` because
        scorer objects can retain clients, credentials, or other unstable
        process state. A custom deterministic scorer can opt in by setting
        ``rescore_safe = True`` and returning a JSON object here.
        """

        raise NotImplementedError(
            "persistent re-scoring requires an explicit JSON configuration()"
        )


class DeferredScorer(BaseScorer):
    """Persist responses for a separate staged scorer without fabricating metrics."""

    rescore_safe = True

    def score_item(self, item: BenchmarkItem, responses: list[RunResult]) -> list[Metric]:
        return []

    def configuration(self) -> Mapping[str, Any]:
        return {"kind": "deferred"}


# --- composition -----------------------------------------------------


class _ComposedScorer(BaseScorer):
    def __init__(self, scorers: list[BaseScorer]):
        self._scorers = scorers

    def score_item(
        self,
        item: BenchmarkItem,
        responses: list[RunResult],
    ) -> list[Metric]:
        merged: list[Metric] = []
        for scorer in self._scorers:
            merged.extend(scorer.score_item(item, responses))
        return merged

    def configure(self, *, system_prompt: str | None = None) -> None:
        for s in self._scorers:
            s.configure(system_prompt=system_prompt)

    @property
    def rescore_safe(self) -> bool:
        return all(s.rescore_safe is True for s in self._scorers)

    def configuration(self) -> Mapping[str, Any]:
        return {
            "kind": "composed",
            "scorers": [identify_scorer(s).to_dict() for s in self._scorers],
        }


def compose_scorers(*scorers: BaseScorer) -> BaseScorer:
    """Run multiple scorers on the same inputs and concatenate metrics."""
    if not scorers:
        raise ValueError("compose_scorers requires at least one scorer")
    return _ComposedScorer(list(scorers))


# --- built-in scorers ------------------------------------------------


def _response_text(r: RunResult) -> str:
    """Pull a usable text answer out of a RunResult.

    Strings come through verbatim. Trajectories use their final_response.
    Anything else is repr-ed so the user at least sees something rather
    than silently scoring zero against a dict.
    """
    from arisekit.types import Trajectory

    value = r.response
    if isinstance(value, Trajectory):
        value = value.final_response
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _mean(values: list[float]) -> float:
    return mean(values, empty=0.0)


class ExactMatchScorer(BaseScorer):
    rescore_safe = True

    def __init__(self, *, case_sensitive: bool = False, strip: bool = True, name: str = "accuracy"):
        self.case_sensitive = case_sensitive
        self.strip = strip
        self.name = name

    def score_item(self, item: BenchmarkItem, responses: list[RunResult]) -> list[Metric]:
        gt = item.ground_truth
        if gt is None:
            return [Metric(self.name, 0.0, n=0)]
        gt_str = str(gt)
        if self.strip:
            gt_str = gt_str.strip()
        if not self.case_sensitive:
            gt_str = gt_str.lower()

        per_trial: list[float] = []
        for r in responses:
            if r.error is not None:
                per_trial.append(0.0)
                continue
            text = _response_text(r)
            if self.strip:
                text = text.strip()
            if not self.case_sensitive:
                text = text.lower()
            per_trial.append(1.0 if text == gt_str else 0.0)
        return [Metric(self.name, _mean(per_trial), n=len(per_trial))]

    def configuration(self) -> Mapping[str, Any]:
        return {
            "kind": "exact-match",
            "case_sensitive": self.case_sensitive,
            "strip": self.strip,
            "name": self.name,
        }


class ContainsScorer(BaseScorer):
    rescore_safe = True

    def __init__(self, *, case_sensitive: bool = False, name: str = "contains"):
        self.case_sensitive = case_sensitive
        self.name = name

    def score_item(self, item: BenchmarkItem, responses: list[RunResult]) -> list[Metric]:
        gt = item.ground_truth
        if gt is None:
            return [Metric(self.name, 0.0, n=0)]
        targets = gt if isinstance(gt, list) else [gt]
        targets_str = [str(t) if self.case_sensitive else str(t).lower() for t in targets]

        per_trial: list[float] = []
        for r in responses:
            if r.error is not None:
                per_trial.append(0.0)
                continue
            text = _response_text(r)
            if not self.case_sensitive:
                text = text.lower()
            per_trial.append(1.0 if any(t in text for t in targets_str) else 0.0)
        return [Metric(self.name, _mean(per_trial), n=len(per_trial))]

    def configuration(self) -> Mapping[str, Any]:
        return {
            "kind": "contains",
            "case_sensitive": self.case_sensitive,
            "name": self.name,
        }


class RegexScorer(BaseScorer):
    rescore_safe = True

    def __init__(self, pattern: str | re.Pattern[str], *, name: str = "regex_match"):
        self._re = re.compile(pattern) if isinstance(pattern, str) else pattern
        self.name = name

    def score_item(self, item: BenchmarkItem, responses: list[RunResult]) -> list[Metric]:
        per_trial: list[float] = []
        for r in responses:
            if r.error is not None:
                per_trial.append(0.0)
                continue
            text = _response_text(r)
            per_trial.append(1.0 if self._re.search(text) else 0.0)
        return [Metric(self.name, _mean(per_trial), n=len(per_trial))]

    def configuration(self) -> Mapping[str, Any]:
        return {
            "kind": "regex",
            "pattern": self._re.pattern,
            "flags": self._re.flags,
            "name": self.name,
        }


class ChoiceScorer(BaseScorer):
    """For MCQ-style items. Looks for the ground-truth letter/option.

    Ground truth should be the canonical option string (e.g. "A" or
    "Pneumonia"). The first occurrence in the response wins.
    """

    rescore_safe = True

    def __init__(
        self,
        choices: list[str] | None = None,
        *,
        case_sensitive: bool = False,
        name: str = "accuracy",
    ):
        self.choices = choices
        self.case_sensitive = case_sensitive
        self.name = name

    def score_item(self, item: BenchmarkItem, responses: list[RunResult]) -> list[Metric]:
        gt = item.ground_truth
        if gt is None:
            return [Metric(self.name, 0.0, n=0)]
        gt_str = str(gt) if self.case_sensitive else str(gt).lower()
        choices = self.choices or [str(gt)]
        choices_norm = [c if self.case_sensitive else c.lower() for c in choices]

        per_trial: list[float] = []
        for r in responses:
            if r.error is not None:
                per_trial.append(0.0)
                continue
            text = _response_text(r)
            text = text if self.case_sensitive else text.lower()
            # First choice token to appear in the response is the model's pick.
            picks = [(text.find(c), c) for c in choices_norm if c and c in text]
            picks = [p for p in picks if p[0] >= 0]
            if not picks:
                per_trial.append(0.0)
                continue
            picks.sort()
            chosen = picks[0][1]
            per_trial.append(1.0 if chosen == gt_str else 0.0)
        return [Metric(self.name, _mean(per_trial), n=len(per_trial))]

    def configuration(self) -> Mapping[str, Any]:
        return {
            "kind": "choice",
            "choices": list(self.choices) if self.choices is not None else None,
            "case_sensitive": self.case_sensitive,
            "name": self.name,
        }


# A minus is often typed as U+2212 or as a dash, which neither `-?` nor float()
# accepts, so U+2212 followed by 2 would score as 2. Minus signs and hyphens
# (U+2212, U+FE63, U+FF0D, U+2010, U+2011) are read as "-" everywhere, like the
# ASCII hyphen. Figure, en and em dashes (U+2012-U+2014) are read as "-" only
# when they start a number, not after a letter, digit or underscore, so "T",
# en dash, "2" still reads as 2.
_MINUS_SIGNS = str.maketrans(dict.fromkeys("\u2212\ufe63\uff0d\u2010\u2011", "-"))
_DASH_BEFORE_NUMBER = re.compile(r"(?<!\w)[\u2012\u2013\u2014](?=\d)")


def _ascii_minus(text: str) -> str:
    return _DASH_BEFORE_NUMBER.sub("-", text.translate(_MINUS_SIGNS))


class NumericScorer(BaseScorer):
    """Score numeric answers with absolute or relative tolerance."""

    _num_re = re.compile(r"-?\d+(?:\.\d+)?")
    rescore_safe = True

    def __init__(
        self,
        *,
        atol: float = 0.0,
        rtol: float = 0.0,
        name: str = "numeric_match",
    ):
        self.atol = atol
        self.rtol = rtol
        self.name = name

    def score_item(self, item: BenchmarkItem, responses: list[RunResult]) -> list[Metric]:
        gt = item.ground_truth
        if gt is None:
            return [Metric(self.name, 0.0, n=0)]
        if isinstance(gt, str):
            gt = _ascii_minus(gt)
        try:
            gt_val = float(gt)
        except (TypeError, ValueError):
            return [Metric(self.name, 0.0, n=0)]

        per_trial: list[float] = []
        for r in responses:
            if r.error is not None:
                per_trial.append(0.0)
                continue
            text = _ascii_minus(_response_text(r))
            match = self._num_re.search(text)
            if not match:
                per_trial.append(0.0)
                continue
            try:
                val = float(match.group(0))
            except ValueError:
                per_trial.append(0.0)
                continue
            tol = max(self.atol, self.rtol * abs(gt_val))
            per_trial.append(1.0 if abs(val - gt_val) <= tol else 0.0)
        return [Metric(self.name, _mean(per_trial), n=len(per_trial))]

    def configuration(self) -> Mapping[str, Any]:
        return {
            "kind": "numeric",
            "atol": self.atol,
            "rtol": self.rtol,
            "name": self.name,
        }


def identify_scorer(scorer: BaseScorer) -> ScorerIdentity:
    """Return a secret-free identity for deterministic offline re-scoring.

    Provider-backed judges and custom scorers are rejected unless they opt in
    explicitly. This prevents a re-score command from silently making paid
    calls or hashing client objects and credentials as configuration.
    """

    if not isinstance(scorer, BaseScorer):
        raise TypeError("scorer must be a BaseScorer")
    if scorer.rescore_safe is not True:
        raise ValueError(
            "persistent re-scoring requires a deterministic scorer with "
            "rescore_safe = True; paid judge scorers need a separate cached "
            "judge adapter"
        )
    try:
        configuration = scorer.configuration()
    except NotImplementedError as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(configuration, Mapping):
        raise ValueError("scorer configuration() must return a JSON object")
    detached = _json_object(configuration, "scorer configuration")

    target = type(scorer)
    try:
        source_path = inspect.getsourcefile(target)
    except TypeError:
        source_path = None
    if source_path is not None and Path(source_path).is_file():
        source = Path(source_path).read_bytes()
    else:
        try:
            source = inspect.getsource(target).encode("utf-8")
        except (OSError, TypeError) as exc:
            raise ValueError("scorer source cannot be identified deterministically") from exc
    return ScorerIdentity(
        qualified_name=f"{target.__module__}.{target.__qualname__}",
        source_sha256=hashlib.sha256(source).hexdigest(),
        configuration=detached,
    )


def _json_object(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    try:
        encoded = _canonical_json(dict(value))
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain only finite JSON values: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{label} must be a JSON object")
    return decoded


# --- public factory aliases -----------------------------------------


def exact_match(**kwargs: Any) -> BaseScorer:
    return ExactMatchScorer(**kwargs)


def contains(**kwargs: Any) -> BaseScorer:
    return ContainsScorer(**kwargs)


def regex_match(pattern: str | re.Pattern[str], **kwargs: Any) -> BaseScorer:
    return RegexScorer(pattern, **kwargs)


def choice(choices: list[str] | None = None, **kwargs: Any) -> BaseScorer:
    return ChoiceScorer(choices=choices, **kwargs)


def numeric(**kwargs: Any) -> BaseScorer:
    return NumericScorer(**kwargs)


def deferred() -> BaseScorer:
    """Create an inference-only scorer for externally judged benchmarks."""
    return DeferredScorer()
