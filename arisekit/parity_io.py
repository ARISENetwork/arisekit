"""Offline conversion between judged NOHARM JSONL and parity observations.

Canonical judged files contain one row per case variant, response trial, and
judge. Parity analysis treats the response trial as the repeated observation,
so multiple judges for that trial are averaged before emitting a
``ParityObservation``. The contributing judge names remain available in the
returned batch audit metadata and never become extra statistical observations.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any

from arisekit.parity import ParityObservation


_CANONICAL_SPECIALTIES = {
    "all": "Allergy",
    "card": "Cardiology",
    "derm": "Dermatology",
    "endo": "Endocrinology",
    "gi": "Gastroenterology",
    "heme": "Hematology",
    "id": "Infectious Disease",
    "nephro": "Nephrology",
    "neuro": "Neurology",
    "pulm": "Pulmonology",
}
_SPECIALTY_ALIASES = {
    **_CANONICAL_SPECIALTIES,
    **{name.casefold(): name for name in _CANONICAL_SPECIALTIES.values()},
}
_CANONICAL_BASE_RE = re.compile(r"^(?P<prefix>[A-Za-z]+)\d{3}$")
_VARIANT_SUFFIX_RE = re.compile(r"^(?P<base>.+)-(?P<suffix>\d+)$")
_OBSERVATION_FIELDS = (
    "arm",
    "model",
    "specialty",
    "base_case",
    "variant",
    "trial",
    "metric",
    "value",
)


@dataclass(frozen=True)
class JudgeNesting:
    """Judges collapsed within one response-trial observation."""

    arm: str
    model: str
    specialty: str
    base_case: str
    variant: str
    trial: int
    judges: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "judges", tuple(self.judges))
        if not self.judges:
            raise ValueError("judge nesting requires at least one judge")
        if len(set(self.judges)) != len(self.judges):
            raise ValueError("judge nesting names must be unique")


@dataclass(frozen=True)
class JudgedParityBatch:
    """Converted observations plus the non-statistical judge audit layer."""

    observations: tuple[ParityObservation, ...]
    judge_nesting: tuple[JudgeNesting, ...]
    rows_read: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "observations", tuple(self.observations))
        object.__setattr__(self, "judge_nesting", tuple(self.judge_nesting))
        if self.rows_read < 0:
            raise ValueError("rows_read cannot be negative")


@dataclass(frozen=True)
class _JudgedRow:
    line_number: int
    specialty: str
    base_case: str
    variant: str
    trial: int
    judge: str
    metrics: Mapping[str, float]


def load_judged_batch(
    path: str | Path,
    *,
    arm: str,
    model: str,
    metrics: Iterable[str] | None = None,
    expected_judges: Iterable[str] | None = None,
) -> JudgedParityBatch:
    """Load canonical judged JSONL and collapse judges within response trials.

    ``arm`` and ``model`` are supplied by the campaign caller because canonical
    judged rows do not reliably contain either. When a row does declare one,
    conflicting values are rejected.
    """
    source = Path(path)
    records: list[tuple[int, Mapping[str, Any]]] = []
    with source.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{source}:{line_number} is not valid JSON: {exc}") from exc
            if not isinstance(payload, Mapping):
                raise ValueError(f"{source}:{line_number} must contain a JSON object")
            records.append((line_number, payload))
    return observations_from_judged_records(
        records,
        arm=arm,
        model=model,
        metrics=metrics,
        expected_judges=expected_judges,
        source=str(source),
    )


def load_judged_observations(
    path: str | Path,
    *,
    arm: str,
    model: str,
    metrics: Iterable[str] | None = None,
    expected_judges: Iterable[str] | None = None,
) -> tuple[ParityObservation, ...]:
    """Convenience wrapper returning only parity-analysis observations."""
    return load_judged_batch(
        path,
        arm=arm,
        model=model,
        metrics=metrics,
        expected_judges=expected_judges,
    ).observations


def observations_from_judged_records(
    records: Iterable[Mapping[str, Any] | tuple[int, Mapping[str, Any]]],
    *,
    arm: str,
    model: str,
    metrics: Iterable[str] | None = None,
    expected_judges: Iterable[str] | None = None,
    source: str = "<records>",
) -> JudgedParityBatch:
    """Convert parsed judged records, retaining explicit source line numbers."""
    arm = _required_string(arm, "arm")
    model = _required_string(model, "model")
    metric_filter = _metric_filter(metrics)
    expected_panel = _judge_filter(expected_judges)

    parsed: list[_JudgedRow] = []
    for fallback_line, record in enumerate(records, start=1):
        if isinstance(record, tuple):
            if len(record) != 2:
                raise ValueError("judged record tuple must be (line_number, object)")
            line_number, payload = record
        else:
            line_number, payload = fallback_line, record
        if isinstance(line_number, bool) or not isinstance(line_number, int) or line_number < 1:
            raise ValueError("judged record line numbers must be positive integers")
        if not isinstance(payload, Mapping):
            raise ValueError(f"{source}:{line_number} must contain a JSON object")
        parsed.append(
            _parse_judged_row(
                payload,
                line_number=line_number,
                source=source,
                arm=arm,
                model=model,
                metric_filter=metric_filter,
            )
        )

    if not parsed:
        raise ValueError(f"{source} contains no judged records")

    raw_identities: set[tuple[str, str, int, str]] = set()
    metric_values: dict[tuple[str, str, str, int, str], list[float]] = defaultdict(list)
    nesting: dict[tuple[str, str, str, int], set[str]] = defaultdict(set)
    variant_identity: dict[str, tuple[str, str]] = {}

    for row in parsed:
        raw_identity = (row.base_case, row.variant, row.trial, row.judge)
        if raw_identity in raw_identities:
            raise ValueError(
                f"{source}:{row.line_number} duplicates judged identity "
                f"{row.variant}/trial-{row.trial}/judge-{row.judge}"
            )
        raw_identities.add(raw_identity)

        identity = (row.base_case, row.specialty)
        previous = variant_identity.setdefault(row.variant, identity)
        if previous != identity:
            raise ValueError(
                f"{source}:{row.line_number} mixes case identity for variant {row.variant!r}"
            )

        trial_key = (row.specialty, row.base_case, row.variant, row.trial)
        nesting[trial_key].add(row.judge)
        for metric, value in row.metrics.items():
            metric_values[trial_key + (metric,)].append(value)

    observed_panels = {
        tuple(sorted(judges)) for judges in nesting.values()
    }
    if len(observed_panels) != 1:
        raise ValueError(
            f"{source} has an incomplete or inconsistent judge panel across response trials"
        )
    observed_panel = next(iter(observed_panels))
    if expected_panel is not None and observed_panel != expected_panel:
        raise ValueError(
            f"{source} judge panel {observed_panel!r} does not match "
            f"the expected panel {expected_panel!r}"
        )

    observations: list[ParityObservation] = []
    for key in sorted(metric_values):
        specialty, base_case, variant, trial, metric = key
        observation = ParityObservation(
            arm=arm,
            model=model,
            specialty=specialty,
            base_case=base_case,
            variant=variant,
            trial=trial,
            metric=metric,
            value=fmean(metric_values[key]),
        )
        observation.validate()
        observations.append(observation)

    if not observations:
        selected = ", ".join(metric_filter or ()) or "finite numeric metrics"
        raise ValueError(f"{source} contains no usable {selected}")
    _validate_observations(observations, source=source)

    judge_nesting = tuple(
        JudgeNesting(
            arm=arm,
            model=model,
            specialty=key[0],
            base_case=key[1],
            variant=key[2],
            trial=key[3],
            judges=tuple(sorted(judges)),
        )
        for key, judges in sorted(nesting.items())
    )
    return JudgedParityBatch(
        observations=tuple(observations),
        judge_nesting=judge_nesting,
        rows_read=len(parsed),
    )


def convert_judged_jsonl(
    judged_path: str | Path,
    observations_path: str | Path,
    *,
    arm: str,
    model: str,
    metrics: Iterable[str] | None = None,
    expected_judges: Iterable[str] | None = None,
) -> Path:
    """Convert a judged artifact directly to study-compatible JSONL."""
    observations = load_judged_observations(
        judged_path,
        arm=arm,
        model=model,
        metrics=metrics,
        expected_judges=expected_judges,
    )
    return write_observations_jsonl(observations_path, observations)


def write_observations_jsonl(
    path: str | Path,
    observations: Iterable[ParityObservation],
) -> Path:
    """Write deterministic JSONL accepted by ``run_study.py analyze``."""
    target = Path(path)
    normalized = tuple(observations)
    _validate_observations(normalized, source=str(target))
    ordered = sorted(normalized, key=_observation_identity)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for observation in ordered:
            handle.write(
                json.dumps(
                    _observation_dict(observation),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            )
    return target


def load_observations_jsonl(path: str | Path) -> tuple[ParityObservation, ...]:
    """Load and validate study-compatible parity-observation JSONL."""
    source = Path(path)
    observations: list[ParityObservation] = []
    with source.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{source}:{line_number} is not valid JSON: {exc}") from exc
            observations.append(
                _observation_from_dict(payload, source=str(source), line_number=line_number)
            )
    if not observations:
        raise ValueError(f"{source} contains no parity observations")
    _validate_observations(observations, source=str(source))
    return tuple(observations)


def _parse_judged_row(
    payload: Mapping[str, Any],
    *,
    line_number: int,
    source: str,
    arm: str,
    model: str,
    metric_filter: tuple[str, ...] | None,
) -> _JudgedRow:
    context = f"{source}:{line_number}"
    metadata_value = payload.get("metadata", {})
    if metadata_value is None:
        metadata: Mapping[str, Any] = {}
    elif isinstance(metadata_value, Mapping):
        metadata = metadata_value
    else:
        raise ValueError(f"{context} metadata must be an object or null")

    _check_supplied_identity(payload, metadata, "arm", arm, context)
    _check_supplied_identity(payload, metadata, "model", model, context)

    item_id = _consistent_string(
        (("id", payload.get("id")), ("case_id", payload.get("case_id"))),
        context=context,
        name="case id",
        required=True,
    )
    assert item_id is not None
    base_case, suffix = _split_variant_id(item_id)

    explicit_base = _consistent_string(
        (
            ("base_id", payload.get("base_id")),
            ("base_case", payload.get("base_case")),
            ("metadata.base_id", metadata.get("base_id")),
            ("metadata.base_case", metadata.get("base_case")),
        ),
        context=context,
        name="base case",
        required=False,
    )
    if explicit_base is not None and explicit_base != base_case:
        raise ValueError(
            f"{context} mixes case identity: id {item_id!r} derives base "
            f"{base_case!r}, but metadata declares {explicit_base!r}"
        )

    explicit_variant = _consistent_string(
        (
            ("variant_id", payload.get("variant_id")),
            ("variant", payload.get("variant")),
            ("metadata.variant_id", metadata.get("variant_id")),
            ("metadata.variant", metadata.get("variant")),
        ),
        context=context,
        name="variant",
        required=False,
    )
    if explicit_variant is not None and explicit_variant != item_id:
        raise ValueError(
            f"{context} mixes case identity: id {item_id!r} and variant "
            f"{explicit_variant!r} differ"
        )

    perturb_id = _consistent_perturb_id(payload, metadata, context=context)
    if perturb_id is not None:
        expected = suffix if suffix is not None else -1
        if perturb_id != expected:
            raise ValueError(
                f"{context} mixes case identity: variant suffix is {expected}, "
                f"but perturb_id is {perturb_id}"
            )

    specialty = _resolve_specialty(payload, metadata, base_case, context=context)
    trial = payload.get("trial")
    if isinstance(trial, bool) or not isinstance(trial, int) or trial < 1:
        raise ValueError(f"{context} trial must be a positive integer")
    judge = _required_string(payload.get("judge"), f"{context} judge")

    metrics_value = payload.get("metrics")
    if not isinstance(metrics_value, Mapping):
        raise ValueError(f"{context} metrics must be an object")
    extracted = _extract_metrics(
        metrics_value,
        selected=metric_filter,
        context=context,
    )
    return _JudgedRow(
        line_number=line_number,
        specialty=specialty,
        base_case=base_case,
        variant=item_id,
        trial=trial,
        judge=judge,
        metrics=extracted,
    )


def _extract_metrics(
    metrics: Mapping[str, Any],
    *,
    selected: tuple[str, ...] | None,
    context: str,
) -> dict[str, float]:
    names = selected if selected is not None else tuple(sorted(metrics))
    extracted: dict[str, float] = {}
    for name in names:
        if name not in metrics:
            if selected is not None:
                raise ValueError(f"{context} is missing requested metric {name!r}")
            continue
        value = metrics[name]
        if value is None:
            if selected is not None:
                raise ValueError(f"{context} requested metric {name!r} is null")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{context} metric {name!r} must be numeric or null")
        numeric = float(value)
        if not math.isfinite(numeric):
            if selected is not None:
                raise ValueError(f"{context} requested metric {name!r} is not finite")
            continue
        extracted[name] = numeric
    if selected is not None and len(extracted) != len(selected):
        raise ValueError(f"{context} does not contain all requested metrics")
    return extracted


def _resolve_specialty(
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
    base_case: str,
    *,
    context: str,
) -> str:
    explicit = _consistent_string(
        (
            ("specialty", payload.get("specialty")),
            ("metadata.specialty", metadata.get("specialty")),
        ),
        context=context,
        name="specialty",
        required=False,
        normalizer=_normalize_specialty,
    )
    match = _CANONICAL_BASE_RE.fullmatch(base_case)
    derived = None
    if match is not None:
        derived = _CANONICAL_SPECIALTIES.get(match.group("prefix").casefold())
    if explicit is not None and derived is not None and explicit != derived:
        raise ValueError(
            f"{context} specialty {explicit!r} conflicts with canonical base "
            f"{base_case!r} ({derived!r})"
        )
    if explicit is not None:
        return explicit
    if derived is not None:
        return derived
    raise ValueError(
        f"{context} cannot derive specialty from base {base_case!r}; "
        "provide explicit specialty metadata"
    )


def resolve_case_specialty(
    base_case: str,
    metadata: Mapping[str, Any] | None = None,
) -> str:
    """Resolve a canonical prefix or explicit generated-case specialty.

    This is the shared preflight rule used before paid inference and again
    when judged rows are converted. Keeping one resolver prevents an arm from
    passing campaign selection with strata that later fail parity analysis.
    """
    base_case = _required_string(base_case, "base case")
    if metadata is None:
        supplied: Mapping[str, Any] = {}
    elif isinstance(metadata, Mapping):
        supplied = metadata
    else:
        raise ValueError("metadata must be an object or null")
    return _resolve_specialty(
        {},
        supplied,
        base_case,
        context=f"base case {base_case!r}",
    )


def _split_variant_id(item_id: str) -> tuple[str, int | None]:
    match = _VARIANT_SUFFIX_RE.fullmatch(item_id)
    if match is None:
        return item_id, None
    base = match.group("base")
    if not base.strip():
        raise ValueError(f"invalid variant id {item_id!r}")
    return base, int(match.group("suffix"))


def _consistent_perturb_id(
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
    *,
    context: str,
) -> int | None:
    present: list[tuple[str, int]] = []
    for label, value in (
        ("perturb_id", payload.get("perturb_id")),
        ("metadata.perturb_id", metadata.get("perturb_id")),
    ):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < -1:
            raise ValueError(f"{context} {label} must be an integer at least -1 or null")
        present.append((label, value))
    if not present:
        return None
    values = {value for _, value in present}
    if len(values) != 1:
        raise ValueError(f"{context} has conflicting perturb_id values")
    return present[0][1]


def _consistent_string(
    candidates: Sequence[tuple[str, Any]],
    *,
    context: str,
    name: str,
    required: bool,
    normalizer: Any = None,
) -> str | None:
    present: list[tuple[str, str]] = []
    for label, value in candidates:
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{context} {label} must be a non-empty string or null")
        normalized = value.strip()
        if normalizer is not None:
            normalized = normalizer(normalized)
        present.append((label, normalized))
    if not present:
        if required:
            raise ValueError(f"{context} is missing {name}")
        return None
    values = {value for _, value in present}
    if len(values) != 1:
        labels = ", ".join(label for label, _ in present)
        raise ValueError(f"{context} has conflicting {name} across {labels}")
    return present[0][1]


def _check_supplied_identity(
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
    name: str,
    supplied: str,
    context: str,
) -> None:
    embedded = _consistent_string(
        ((name, payload.get(name)), (f"metadata.{name}", metadata.get(name))),
        context=context,
        name=name,
        required=False,
    )
    if embedded is not None and embedded != supplied:
        raise ValueError(
            f"{context} embedded {name} {embedded!r} conflicts with caller-supplied {supplied!r}"
        )


def _normalize_specialty(value: str) -> str:
    return _SPECIALTY_ALIASES.get(value.casefold(), value)


def _metric_filter(metrics: Iterable[str] | None) -> tuple[str, ...] | None:
    if metrics is None:
        return None
    normalized = tuple(_required_string(metric, "metric name") for metric in metrics)
    if not normalized:
        raise ValueError("metrics must contain at least one metric name")
    if len(set(normalized)) != len(normalized):
        raise ValueError("metric names must be unique")
    return tuple(sorted(normalized))


def _judge_filter(judges: Iterable[str] | None) -> tuple[str, ...] | None:
    if judges is None:
        return None
    normalized = tuple(_required_string(judge, "judge name") for judge in judges)
    if not normalized:
        raise ValueError("expected_judges must contain at least one judge name")
    if len(set(normalized)) != len(normalized):
        raise ValueError("expected judge names must be unique")
    return tuple(sorted(normalized))


def _observation_dict(observation: ParityObservation) -> dict[str, Any]:
    return {
        "arm": observation.arm,
        "model": observation.model,
        "specialty": observation.specialty,
        "base_case": observation.base_case,
        "variant": observation.variant,
        "trial": observation.trial,
        "metric": observation.metric,
        "value": observation.value,
    }


def _observation_from_dict(
    payload: Any,
    *,
    source: str,
    line_number: int,
) -> ParityObservation:
    context = f"{source}:{line_number}"
    if not isinstance(payload, Mapping):
        raise ValueError(f"{context} must contain a JSON object")
    fields = set(payload)
    expected = set(_OBSERVATION_FIELDS)
    if fields != expected:
        missing = sorted(expected - fields)
        extra = sorted(fields - expected)
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unexpected {', '.join(extra)}")
        raise ValueError(f"{context} has invalid observation fields: {'; '.join(details)}")
    string_values = {
        name: _required_string(payload[name], f"{context} {name}")
        for name in _OBSERVATION_FIELDS[:5] + ("metric",)
    }
    trial = payload["trial"]
    if isinstance(trial, bool) or not isinstance(trial, int) or trial < 1:
        raise ValueError(f"{context} trial must be a positive integer")
    value = payload["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} value must be numeric")
    observation = ParityObservation(
        arm=string_values["arm"],
        model=string_values["model"],
        specialty=string_values["specialty"],
        base_case=string_values["base_case"],
        variant=string_values["variant"],
        trial=trial,
        metric=string_values["metric"],
        value=float(value),
    )
    observation.validate()
    return observation


def _validate_observations(
    observations: Iterable[ParityObservation],
    *,
    source: str,
) -> None:
    identities: set[tuple[str, str, str, str, str, int, str]] = set()
    variants: dict[tuple[str, str, str], tuple[str, str]] = {}
    bases: dict[tuple[str, str, str], str] = {}
    for observation in observations:
        if not isinstance(observation, ParityObservation):
            raise ValueError(f"{source} contains a non-ParityObservation value")
        observation.validate()
        if isinstance(observation.trial, bool):
            raise ValueError(f"{source} observation trial must be an integer, not bool")
        if isinstance(observation.value, bool):
            raise ValueError(f"{source} observation value must be numeric, not bool")
        identity = _observation_identity(observation)
        if identity in identities:
            raise ValueError(
                f"{source} duplicates observation identity "
                f"{observation.arm}/{observation.model}/{observation.variant}/"
                f"trial-{observation.trial}/{observation.metric}"
            )
        identities.add(identity)

        variant_key = (observation.arm, observation.model, observation.variant)
        case_identity = (observation.base_case, observation.specialty)
        previous_case = variants.setdefault(variant_key, case_identity)
        if previous_case != case_identity:
            raise ValueError(
                f"{source} mixes base or specialty identity for variant {observation.variant!r}"
            )
        base_key = (observation.arm, observation.model, observation.base_case)
        previous_specialty = bases.setdefault(base_key, observation.specialty)
        if previous_specialty != observation.specialty:
            raise ValueError(
                f"{source} mixes specialty identity for base {observation.base_case!r}"
            )


def _observation_identity(
    observation: ParityObservation,
) -> tuple[str, str, str, str, str, int, str]:
    return (
        observation.arm,
        observation.model,
        observation.specialty,
        observation.base_case,
        observation.variant,
        observation.trial,
        observation.metric,
    )


def _required_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


__all__ = [
    "JudgeNesting",
    "JudgedParityBatch",
    "convert_judged_jsonl",
    "load_judged_batch",
    "load_judged_observations",
    "load_observations_jsonl",
    "observations_from_judged_records",
    "resolve_case_specialty",
    "write_observations_jsonl",
]
