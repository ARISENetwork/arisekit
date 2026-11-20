"""Cluster-aware analysis for generated-versus-reference benchmark studies."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from statistics import fmean
from typing import Iterable

from arisekit.common.stats import quantile


@dataclass(frozen=True)
class ParityObservation:
    """One scalar metric from a response trial in a benchmark arm."""

    arm: str
    model: str
    specialty: str
    base_case: str
    variant: str
    trial: int
    metric: str
    value: float

    def validate(self) -> None:
        missing = [
            name
            for name in ("arm", "model", "specialty", "base_case", "variant", "metric")
            if not str(getattr(self, name)).strip()
        ]
        if missing:
            raise ValueError(f"parity observation is missing: {', '.join(missing)}")
        if isinstance(self.trial, bool) or not isinstance(self.trial, int) or self.trial < 1:
            raise ValueError("trial must be a positive integer")
        if (
            isinstance(self.value, bool)
            or not isinstance(self.value, (int, float))
            or not math.isfinite(self.value)
        ):
            raise ValueError("value must be finite")


@dataclass(frozen=True)
class CaseEstimate:
    """A metric averaged over trials within variants, then over variants."""

    arm: str
    model: str
    specialty: str
    base_case: str
    value: float
    variants: int
    observations: int
    trial_counts: tuple[int, ...] = ()
    variant_trials: tuple[tuple[str, tuple[int, ...]], ...] = ()


@dataclass(frozen=True)
class EquivalenceEndpoint:
    estimate: float
    lower: float | None
    upper: float | None
    margin: float
    passed: bool | None


@dataclass(frozen=True)
class ParityReport:
    """Primary parity endpoints and equally specialty-weighted model scores."""

    metric: str
    reference_arm: str
    generated_arm: str
    models: tuple[str, ...]
    scores: dict[str, dict[str, float]]
    level: EquivalenceEndpoint
    profile_rmse: EquivalenceEndpoint
    bootstrap_draws: int
    seed: int

    @property
    def passed(self) -> bool | None:
        if self.level.passed is None or self.profile_rmse.passed is None:
            return None
        return self.level.passed and self.profile_rmse.passed


def aggregate_case_estimates(
    observations: Iterable[ParityObservation],
    *,
    metric: str,
) -> list[CaseEstimate]:
    """Respect the NOHARM nesting order when reducing repeated observations."""

    trial_groups: dict[tuple[str, str, str, str, str], list[float]] = defaultdict(list)
    trial_ids: dict[tuple[str, str, str, str, str], set[int]] = defaultdict(set)
    observation_counts: dict[tuple[str, str, str, str], int] = defaultdict(int)
    seen: set[tuple[str, str, str, str, str, int, str]] = set()
    base_specialties: dict[tuple[str, str, str], str] = {}

    for observation in observations:
        observation.validate()
        if observation.metric != metric:
            continue
        identity = (
            observation.arm,
            observation.model,
            observation.specialty,
            observation.base_case,
            observation.variant,
            observation.trial,
            observation.metric,
        )
        if identity in seen:
            raise ValueError(
                "duplicate parity observation for "
                f"{observation.arm}/{observation.model}/{observation.variant}/"
                f"trial-{observation.trial}/{observation.metric}"
            )
        seen.add(identity)
        base_key = (observation.arm, observation.model, observation.base_case)
        previous_specialty = base_specialties.setdefault(base_key, observation.specialty)
        if previous_specialty != observation.specialty:
            raise ValueError(
                f"base case {observation.base_case!r} has conflicting specialties"
            )
        variant_key = (
            observation.arm,
            observation.model,
            observation.specialty,
            observation.base_case,
            observation.variant,
        )
        trial_groups[variant_key].append(observation.value)
        trial_ids[variant_key].add(observation.trial)
        observation_counts[variant_key[:4]] += 1

    if not trial_groups:
        raise ValueError(f"no observations found for metric {metric!r}")

    case_groups: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    case_trial_counts: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    case_variant_trials: dict[
        tuple[str, str, str, str], list[tuple[str, tuple[int, ...]]]
    ] = defaultdict(list)
    for variant_key, values in trial_groups.items():
        observed_trials = tuple(sorted(trial_ids[variant_key]))
        if observed_trials != tuple(range(1, len(observed_trials) + 1)):
            raise ValueError(
                f"variant {variant_key[-1]!r} must contain contiguous trials starting at 1"
            )
        case_groups[variant_key[:4]].append(fmean(values))
        case_trial_counts[variant_key[:4]].append(len(observed_trials))
        case_variant_trials[variant_key[:4]].append(
            (
                _variant_role(variant_key[3], variant_key[4]),
                observed_trials,
            )
        )

    estimates = [
        CaseEstimate(
            arm=key[0],
            model=key[1],
            specialty=key[2],
            base_case=key[3],
            value=fmean(values),
            variants=len(values),
            observations=observation_counts[key],
            trial_counts=tuple(sorted(case_trial_counts[key])),
            variant_trials=tuple(sorted(case_variant_trials[key])),
        )
        for key, values in case_groups.items()
    ]
    return sorted(
        estimates,
        key=lambda estimate: (
            estimate.arm,
            estimate.model,
            estimate.specialty,
            estimate.base_case,
        ),
    )


def model_scores(estimates: Iterable[CaseEstimate]) -> dict[str, dict[str, float]]:
    """Average bases within specialty and weight observed specialties equally."""

    cells: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for estimate in estimates:
        cells[(estimate.arm, estimate.model, estimate.specialty)].append(estimate.value)

    specialties: dict[tuple[str, str], list[float]] = defaultdict(list)
    for (arm, model, _specialty), values in cells.items():
        specialties[(arm, model)].append(fmean(values))

    scores: dict[str, dict[str, float]] = defaultdict(dict)
    for (arm, model), values in specialties.items():
        scores[arm][model] = fmean(values)
    return {arm: dict(model_values) for arm, model_values in scores.items()}


def compare_parity(
    observations: Iterable[ParityObservation],
    *,
    metric: str,
    reference_arm: str,
    generated_arm: str,
    level_margin: float = 0.05,
    profile_margin: float = 0.05,
    bootstrap_draws: int = 10_000,
    level_confidence: float = 0.90,
    profile_confidence: float = 0.95,
    seed: int = 17,
) -> ParityReport:
    """Compare benchmark arms with specialty-stratified base-case resampling."""

    if level_margin <= 0 or profile_margin <= 0:
        raise ValueError("equivalence margins must be positive")
    if bootstrap_draws < 0:
        raise ValueError("bootstrap_draws cannot be negative")
    for confidence in (level_confidence, profile_confidence):
        if not 0 < confidence < 1:
            raise ValueError("confidence values must be between 0 and 1")

    estimates = aggregate_case_estimates(observations, metric=metric)
    arm_shapes: dict[
        str,
        set[tuple[int, int, tuple[int, ...], tuple[tuple[str, tuple[int, ...]], ...]]],
    ] = defaultdict(set)
    base_coverage: dict[
        tuple[str, str, str], dict[str, tuple[tuple[str, tuple[int, ...]], ...]]
    ] = defaultdict(dict)
    for estimate in estimates:
        arm_shapes[estimate.arm].add(
            (
                estimate.variants,
                estimate.observations,
                estimate.trial_counts,
                estimate.variant_trials,
            )
        )
        base_key = (estimate.arm, estimate.specialty, estimate.base_case)
        base_coverage[base_key][estimate.model] = estimate.variant_trials
    for (arm, _specialty, base_case), model_coverage in base_coverage.items():
        if len(set(model_coverage.values())) != 1:
            raise ValueError(
                f"arm {arm!r} base {base_case!r} has inconsistent exact variant/trial coverage"
            )
    for arm, shapes in arm_shapes.items():
        if len(shapes) != 1:
            raise ValueError(f"arm {arm!r} has inconsistent variant or trial coverage")
    by_arm = _case_matrix(estimates)
    if reference_arm not in by_arm:
        raise ValueError(f"unknown reference arm {reference_arm!r}")
    if generated_arm not in by_arm:
        raise ValueError(f"unknown generated arm {generated_arm!r}")
    if arm_shapes[reference_arm] != arm_shapes[generated_arm]:
        raise ValueError("benchmark arms must use the same variant and trial coverage")
    reference_strata = {
        specialty: len(bases) for specialty, bases in by_arm[reference_arm].items()
    }
    generated_strata = {
        specialty: len(bases) for specialty, bases in by_arm[generated_arm].items()
    }
    if reference_strata != generated_strata:
        raise ValueError(
            "benchmark arms must use the same specialty strata and base-case counts"
        )

    reference_scores = _scores_from_matrix(by_arm[reference_arm])
    generated_scores = _scores_from_matrix(by_arm[generated_arm])
    models = tuple(sorted(set(reference_scores) & set(generated_scores)))
    if len(models) < 2:
        raise ValueError("parity comparison needs at least two models shared by both arms")
    if set(reference_scores) != set(generated_scores):
        raise ValueError("benchmark arms must contain the same model panel")

    level = _level_difference(reference_scores, generated_scores, models)
    profile = _centered_rmse(reference_scores, generated_scores, models)

    level_draws: list[float] = []
    profile_draws: list[float] = []
    if bootstrap_draws:
        rng = random.Random(seed)
        for _ in range(bootstrap_draws):
            reference_draw = _resample_scores(by_arm[reference_arm], rng)
            generated_draw = _resample_scores(by_arm[generated_arm], rng)
            level_draws.append(_level_difference(reference_draw, generated_draw, models))
            profile_draws.append(_centered_rmse(reference_draw, generated_draw, models))

    level_lower, level_upper = _two_sided_interval(level_draws, level_confidence)
    profile_upper = _upper_bound(profile_draws, profile_confidence)

    return ParityReport(
        metric=metric,
        reference_arm=reference_arm,
        generated_arm=generated_arm,
        models=models,
        scores={
            reference_arm: reference_scores,
            generated_arm: generated_scores,
        },
        level=EquivalenceEndpoint(
            estimate=level,
            lower=level_lower,
            upper=level_upper,
            margin=level_margin,
            passed=(
                level_lower >= -level_margin and level_upper <= level_margin
                if level_lower is not None and level_upper is not None
                else None
            ),
        ),
        profile_rmse=EquivalenceEndpoint(
            estimate=profile,
            lower=0.0 if profile_upper is not None else None,
            upper=profile_upper,
            margin=profile_margin,
            passed=profile_upper <= profile_margin if profile_upper is not None else None,
        ),
        bootstrap_draws=bootstrap_draws,
        seed=seed,
    )


def _case_matrix(
    estimates: Iterable[CaseEstimate],
) -> dict[str, dict[str, dict[str, dict[str, float]]]]:
    matrix: dict[str, dict[str, dict[str, dict[str, float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(dict))
    )
    for estimate in estimates:
        base = matrix[estimate.arm][estimate.specialty][estimate.base_case]
        if estimate.model in base:
            raise ValueError(
                f"duplicate case estimate for {estimate.arm}/{estimate.base_case}/{estimate.model}"
            )
        base[estimate.model] = estimate.value

    normalized = {
        arm: {
            specialty: {base_case: dict(values) for base_case, values in bases.items()}
            for specialty, bases in specialties.items()
        }
        for arm, specialties in matrix.items()
    }
    for arm, specialties in normalized.items():
        model_sets = {
            frozenset(values)
            for bases in specialties.values()
            for values in bases.values()
        }
        if len(model_sets) != 1:
            raise ValueError(f"arm {arm!r} has an incomplete model-by-base matrix")
    return normalized


def _scores_from_matrix(
    specialties: dict[str, dict[str, dict[str, float]]],
) -> dict[str, float]:
    if not specialties:
        raise ValueError("an arm must contain at least one specialty")
    model_names = sorted(next(iter(next(iter(specialties.values())).values())))
    specialty_scores: dict[str, list[float]] = {model: [] for model in model_names}
    for bases in specialties.values():
        for model in model_names:
            specialty_scores[model].append(fmean(base[model] for base in bases.values()))
    return {model: fmean(values) for model, values in specialty_scores.items()}


def _resample_scores(
    specialties: dict[str, dict[str, dict[str, float]]],
    rng: random.Random,
) -> dict[str, float]:
    model_names = sorted(next(iter(next(iter(specialties.values())).values())))
    specialty_scores: dict[str, list[float]] = {model: [] for model in model_names}
    for bases in specialties.values():
        base_ids = list(bases)
        sampled_ids = rng.choices(base_ids, k=len(base_ids))
        for model in model_names:
            specialty_scores[model].append(fmean(bases[base_id][model] for base_id in sampled_ids))
    return {model: fmean(values) for model, values in specialty_scores.items()}


def _level_difference(
    reference: dict[str, float],
    generated: dict[str, float],
    models: tuple[str, ...],
) -> float:
    return fmean(generated[model] - reference[model] for model in models)


def _centered_rmse(
    reference: dict[str, float],
    generated: dict[str, float],
    models: tuple[str, ...],
) -> float:
    reference_mean = fmean(reference[model] for model in models)
    generated_mean = fmean(generated[model] for model in models)
    squared = [
        ((generated[model] - generated_mean) - (reference[model] - reference_mean)) ** 2
        for model in models
    ]
    return math.sqrt(fmean(squared))


def _two_sided_interval(values: list[float], confidence: float) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    alpha = (1.0 - confidence) / 2.0
    return _quantile(values, alpha), _quantile(values, 1.0 - alpha)


def _upper_bound(values: list[float], confidence: float) -> float | None:
    return _quantile(values, confidence) if values else None


def _quantile(values: list[float], probability: float) -> float:
    return quantile(sorted(values), probability)


def _variant_role(base_case: str, variant: str) -> str:
    """Normalize arm-specific case IDs into comparable variant roles."""
    if variant == base_case or variant.casefold() in {"base", "baseline"}:
        return "baseline"
    prefix = f"{base_case}-"
    if variant.startswith(prefix):
        suffix = variant[len(prefix) :]
        if suffix.isdigit():
            return f"perturbation-{int(suffix)}"
    return variant


__all__ = [
    "CaseEstimate",
    "EquivalenceEndpoint",
    "ParityObservation",
    "ParityReport",
    "aggregate_case_estimates",
    "compare_parity",
    "model_scores",
]
