"""Deterministic matching, sealed analysis, and stress-package materialization."""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from arisekit.common.hashing import canonical_sha256 as _digest
from arisekit.common.records import CanonicalRecord
from arisekit.common.stats import mean as _mean, percentile_interval, quantile
from arisekit.common.validate import exact_fields as _fields, number, sha256_hex, text
from arisekit.package import BenchmarkManifest, write_package
from arisekit.analysis.stress import (
    FeatureDistance,
    MatchedCohortManifest,
    MatchedPair,
    MatchingControl,
    MetricDirection,
    ModelSnapshot,
    StressBenchmarkSpec,
    StressLifecycle,
    StressValidationRecord,
)
from arisekit.types import BenchmarkItem


BOOTSTRAP_SCHEMA_VERSION = "arisekit.stress-bootstrap.v1"
ANALYSIS_SCHEMA_VERSION = "arisekit.stress-validation-analysis.v1"


@dataclass(frozen=True)
class StressFeatureRow:
    """Approved item identity and numeric features used for matching."""

    item_hash: str
    features: Mapping[str, float]

    def __post_init__(self) -> None:
        _hash("item_hash", self.item_hash)
        if not isinstance(self.features, Mapping) or not self.features:
            raise ValueError("stress matching features must be a non-empty object")
        normalized: dict[str, float] = {}
        for name, value in self.features.items():
            _text("feature name", name)
            normalized[name] = _finite(f"feature {name}", value)
        object.__setattr__(
            self,
            "features",
            MappingProxyType(dict(sorted(normalized.items()))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"item_hash": self.item_hash, "features": dict(self.features)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StressFeatureRow":
        _fields(data, {"item_hash", "features"}, "stress feature row")
        return cls(item_hash=data["item_hash"], features=data["features"])


def match_stress_cohorts(
    selected: Sequence[StressFeatureRow],
    control_pool: Sequence[StressFeatureRow],
    *,
    matching_controls: Sequence[MatchingControl],
) -> MatchedCohortManifest:
    """Match exact selected members to controls under every frozen caliper.

    The matcher is deterministic nearest-neighbor matching. It processes the
    selected item with the fewest eligible controls first, then resolves equal
    distances by control hash. The resulting manifest records every distance,
    assignment, caliper, reuse count, and exact cohort member.
    """

    selected_rows = _feature_rows("selected", selected)
    control_rows = _feature_rows("control_pool", control_pool)
    controls = tuple(matching_controls)
    if not controls or not all(
        isinstance(value, MatchingControl) for value in controls
    ):
        raise ValueError("matching_controls must contain MatchingControl values")
    controls_per_selected = {value.controls_per_selected for value in controls}
    if len(controls_per_selected) != 1:
        raise ValueError("matching controls must agree on controls_per_selected")
    required_per_selected = next(iter(controls_per_selected))
    maximum_reuse = min(value.maximum_control_reuse for value in controls)
    calipers = _calipers(controls)
    required_features = tuple(sorted(calipers))

    selected_hashes = {row.item_hash for row in selected_rows}
    control_hashes = {row.item_hash for row in control_rows}
    if (
        any(value.require_disjoint for value in controls)
        and selected_hashes & control_hashes
    ):
        raise ValueError("matching rule requires disjoint selected and control pools")
    for row in (*selected_rows, *control_rows):
        missing = sorted(set(required_features) - set(row.features))
        if missing:
            raise ValueError(
                f"stress item {row.item_hash} lacks matching features: {', '.join(missing)}"
            )

    eligible: dict[str, list[tuple[float, str, tuple[FeatureDistance, ...]]]] = {}
    for selected_row in selected_rows:
        candidates: list[tuple[float, str, tuple[FeatureDistance, ...]]] = []
        for control_row in control_rows:
            if selected_row.item_hash == control_row.item_hash:
                continue
            distances = tuple(
                FeatureDistance(
                    feature,
                    abs(selected_row.features[feature] - control_row.features[feature]),
                )
                for feature in required_features
            )
            if any(
                distance.value > calipers[distance.feature] for distance in distances
            ):
                continue
            normalized_distance = sum(
                (
                    distance.value / calipers[distance.feature]
                    if calipers[distance.feature] > 0
                    else 0.0
                )
                for distance in distances
            )
            candidates.append((normalized_distance, control_row.item_hash, distances))
        candidates.sort(key=lambda value: (value[0], value[1]))
        if len(candidates) < required_per_selected:
            raise ValueError(
                f"selected item {selected_row.item_hash} has fewer than "
                f"{required_per_selected} controls inside all calipers"
            )
        eligible[selected_row.item_hash] = candidates

    processing_order = sorted(
        selected_rows,
        key=lambda row: (len(eligible[row.item_hash]), row.item_hash),
    )
    reuse: Counter[str] = Counter()
    pairs: list[MatchedPair] = []
    for selected_row in processing_order:
        chosen = 0
        for _distance, control_hash, distances in eligible[selected_row.item_hash]:
            if reuse[control_hash] >= maximum_reuse:
                continue
            pairs.append(
                MatchedPair(
                    selected_item_hash=selected_row.item_hash,
                    control_item_hash=control_hash,
                    distances=distances,
                )
            )
            reuse[control_hash] += 1
            chosen += 1
            if chosen == required_per_selected:
                break
        if chosen != required_per_selected:
            raise ValueError(
                "deterministic matching exhausted control reuse capacity for "
                f"{selected_row.item_hash}"
            )

    return MatchedCohortManifest.create(
        selected_item_hashes=tuple(row.item_hash for row in selected_rows),
        control_item_hashes=tuple(sorted(reuse)),
        pairs=tuple(pairs),
        matching_controls=controls,
    )


def model_snapshot_key(snapshot: ModelSnapshot) -> str:
    """Return the unambiguous key used in stress score rows."""

    if not isinstance(snapshot, ModelSnapshot):
        raise ValueError("snapshot must be ModelSnapshot")
    return f"{snapshot.family}/{snapshot.model}@{snapshot.snapshot}"


@dataclass(frozen=True)
class StressItemScore:
    """One sealed item's target score and every comparison-model score."""

    item_hash: str
    target_score: float
    panel_scores: Mapping[str, float]

    def __post_init__(self) -> None:
        _hash("item_hash", self.item_hash)
        object.__setattr__(
            self, "target_score", _finite("target_score", self.target_score)
        )
        if not isinstance(self.panel_scores, Mapping) or not self.panel_scores:
            raise ValueError("panel_scores must be a non-empty object")
        normalized: dict[str, float] = {}
        for model, value in self.panel_scores.items():
            _text("panel score model", model)
            normalized[model] = _finite(f"panel score {model}", value)
        object.__setattr__(
            self,
            "panel_scores",
            MappingProxyType(dict(sorted(normalized.items()))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_hash": self.item_hash,
            "target_score": self.target_score,
            "panel_scores": dict(self.panel_scores),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StressItemScore":
        _fields(
            data,
            {"item_hash", "target_score", "panel_scores"},
            "stress item score",
        )
        return cls(
            item_hash=data["item_hash"],
            target_score=data["target_score"],
            panel_scores=data["panel_scores"],
        )


@dataclass(frozen=True)
class StressScoreTable(CanonicalRecord):
    """Hash-bound item-level results for the sealed validation cohort."""

    metric: str
    target: ModelSnapshot
    comparison_panel: tuple[ModelSnapshot, ...]
    sealed_validation_split_hash: str
    judge_panel_hash: str
    source_results_hash: str
    rows: tuple[StressItemScore, ...]

    def __post_init__(self) -> None:
        _text("metric", self.metric)
        if not isinstance(self.target, ModelSnapshot):
            raise ValueError("target must be ModelSnapshot")
        panel = tuple(self.comparison_panel)
        if not panel or not all(isinstance(value, ModelSnapshot) for value in panel):
            raise ValueError("comparison_panel must contain ModelSnapshot values")
        panel = tuple(sorted(panel, key=model_snapshot_key))
        keys = tuple(model_snapshot_key(value) for value in panel)
        if len(set(keys)) != len(keys):
            raise ValueError("comparison_panel snapshots must be unique")
        object.__setattr__(self, "comparison_panel", panel)
        for name in (
            "sealed_validation_split_hash",
            "judge_panel_hash",
            "source_results_hash",
        ):
            _hash(name, getattr(self, name))
        rows = tuple(self.rows)
        if not rows or not all(isinstance(row, StressItemScore) for row in rows):
            raise ValueError("stress score table must contain rows")
        if len({row.item_hash for row in rows}) != len(rows):
            raise ValueError("stress score table contains duplicate item hashes")
        expected_models = set(keys)
        for row in rows:
            if set(row.panel_scores) != expected_models:
                raise ValueError(
                    f"stress score row {row.item_hash} does not contain the exact panel"
                )
        object.__setattr__(
            self, "rows", tuple(sorted(rows, key=lambda row: row.item_hash))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "target": self.target.to_dict(),
            "comparison_panel": [value.to_dict() for value in self.comparison_panel],
            "sealed_validation_split_hash": self.sealed_validation_split_hash,
            "judge_panel_hash": self.judge_panel_hash,
            "source_results_hash": self.source_results_hash,
            "rows": [row.to_dict() for row in self.rows],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StressScoreTable":
        fields = {
            "metric",
            "target",
            "comparison_panel",
            "sealed_validation_split_hash",
            "judge_panel_hash",
            "source_results_hash",
            "rows",
        }
        _fields(data, fields, "stress score table")
        return cls(
            metric=data["metric"],
            target=ModelSnapshot.from_dict(data["target"]),
            comparison_panel=tuple(
                ModelSnapshot.from_dict(value) for value in data["comparison_panel"]
            ),
            sealed_validation_split_hash=data["sealed_validation_split_hash"],
            judge_panel_hash=data["judge_panel_hash"],
            source_results_hash=data["source_results_hash"],
            rows=tuple(StressItemScore.from_dict(value) for value in data["rows"]),
        )


@dataclass(frozen=True)
class StressBootstrapArtifact(CanonicalRecord):
    """Reproducible bootstrap commitment retained beside the validation record."""

    seed: int
    draw_count: int
    confidence_level: float
    matched_cohort_hash: str
    score_table_hash: str
    analysis_code_hash: str
    target_lift_ci: tuple[float, float]
    target_specificity_ci: tuple[float, float]
    target_lift_draws_hash: str
    target_specificity_draws_hash: str
    schema_version: str = BOOTSTRAP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("bootstrap seed must be an integer")
        if (
            isinstance(self.draw_count, bool)
            or not isinstance(self.draw_count, int)
            or self.draw_count < 1
        ):
            raise ValueError("bootstrap draw_count must be positive")
        if not 0.0 < _finite("confidence_level", self.confidence_level) < 1.0:
            raise ValueError("confidence_level must be between zero and one")
        for name in (
            "matched_cohort_hash",
            "score_table_hash",
            "analysis_code_hash",
            "target_lift_draws_hash",
            "target_specificity_draws_hash",
        ):
            _hash(name, getattr(self, name))
        for name in ("target_lift_ci", "target_specificity_ci"):
            interval = getattr(self, name)
            if len(interval) != 2:
                raise ValueError(f"{name} must contain two bounds")
            lower, upper = (_finite(name, value) for value in interval)
            if lower > upper:
                raise ValueError(f"{name} lower bound exceeds upper bound")
            object.__setattr__(self, name, (lower, upper))
        if self.schema_version != BOOTSTRAP_SCHEMA_VERSION:
            raise ValueError("unsupported stress bootstrap schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "seed": self.seed,
            "draw_count": self.draw_count,
            "confidence_level": self.confidence_level,
            "matched_cohort_hash": self.matched_cohort_hash,
            "score_table_hash": self.score_table_hash,
            "analysis_code_hash": self.analysis_code_hash,
            "target_lift_ci": list(self.target_lift_ci),
            "target_specificity_ci": list(self.target_specificity_ci),
            "target_lift_draws_hash": self.target_lift_draws_hash,
            "target_specificity_draws_hash": self.target_specificity_draws_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StressBootstrapArtifact":
        fields = {
            "schema_version",
            "seed",
            "draw_count",
            "confidence_level",
            "matched_cohort_hash",
            "score_table_hash",
            "analysis_code_hash",
            "target_lift_ci",
            "target_specificity_ci",
            "target_lift_draws_hash",
            "target_specificity_draws_hash",
        }
        _fields(data, fields, "stress bootstrap artifact")
        return cls(
            seed=data["seed"],
            draw_count=data["draw_count"],
            confidence_level=data["confidence_level"],
            matched_cohort_hash=data["matched_cohort_hash"],
            score_table_hash=data["score_table_hash"],
            analysis_code_hash=data["analysis_code_hash"],
            target_lift_ci=tuple(data["target_lift_ci"]),
            target_specificity_ci=tuple(data["target_specificity_ci"]),
            target_lift_draws_hash=data["target_lift_draws_hash"],
            target_specificity_draws_hash=data["target_specificity_draws_hash"],
            schema_version=data["schema_version"],
        )


@dataclass(frozen=True)
class StressValidationAnalysis(CanonicalRecord):
    record: StressValidationRecord
    bootstrap: StressBootstrapArtifact
    schema_version: str = ANALYSIS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.record, StressValidationRecord):
            raise ValueError("record must be StressValidationRecord")
        if not isinstance(self.bootstrap, StressBootstrapArtifact):
            raise ValueError("bootstrap must be StressBootstrapArtifact")
        if self.record.confidence_interval_artifact_hash != self.bootstrap.digest:
            raise ValueError("validation record does not bind the bootstrap artifact")
        if self.record.matched_cohort.digest != self.bootstrap.matched_cohort_hash:
            raise ValueError("bootstrap artifact does not bind the validation cohort")
        if self.record.comparison_panel_results_hash != self.bootstrap.score_table_hash:
            raise ValueError("bootstrap artifact does not bind the validation scores")
        if self.schema_version != ANALYSIS_SCHEMA_VERSION:
            raise ValueError("unsupported stress validation analysis schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record": self.record.to_dict(),
            "bootstrap": self.bootstrap.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StressValidationAnalysis":
        _fields(
            data,
            {"schema_version", "record", "bootstrap"},
            "stress validation analysis",
        )
        return cls(
            record=StressValidationRecord.from_dict(data["record"]),
            bootstrap=StressBootstrapArtifact.from_dict(data["bootstrap"]),
            schema_version=data["schema_version"],
        )


def analyze_stress_validation(
    spec: StressBenchmarkSpec,
    matched_cohort: MatchedCohortManifest,
    score_table: StressScoreTable,
    *,
    seed: int,
    analysis_code_hash: str,
) -> StressValidationAnalysis:
    """Compute the sealed target-lift and specificity record from item scores."""

    if (
        not isinstance(spec, StressBenchmarkSpec)
        or spec.lifecycle is not StressLifecycle.FROZEN
    ):
        raise ValueError("stress validation analysis requires a frozen spec")
    if not isinstance(matched_cohort, MatchedCohortManifest):
        raise ValueError("matched_cohort must be MatchedCohortManifest")
    if not isinstance(score_table, StressScoreTable):
        raise ValueError("score_table must be StressScoreTable")
    _hash("analysis_code_hash", analysis_code_hash)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("bootstrap seed must be an integer")
    matched_cohort.validate_against(spec.matching_controls)
    matched_items = set(matched_cohort.selected_item_hashes) | set(
        matched_cohort.control_item_hashes
    )
    if matched_items != set(spec.sealed_validation_cohort.item_hashes):
        raise ValueError("matched cohort must exactly partition the sealed cohort")
    if matched_cohort.diagnostics.maximum_control_reuse != 1:
        raise ValueError("paired case-cluster bootstrap requires unreused controls")
    if score_table.metric != spec.validation_rule.metric:
        raise ValueError("score table metric does not match the frozen rule")
    if score_table.target != spec.target:
        raise ValueError("score table target does not match the frozen target")
    if score_table.comparison_panel != spec.acquisition_panel:
        raise ValueError("score table comparison panel does not match the frozen panel")
    if score_table.sealed_validation_split_hash != spec.sealed_validation_split_hash:
        raise ValueError("score table does not bind the sealed validation split")
    if score_table.judge_panel_hash != spec.judge_hash:
        raise ValueError("score table does not bind the frozen judge panel")
    rows = {row.item_hash: row for row in score_table.rows}
    if set(rows) != matched_items:
        raise ValueError("score table must contain exactly every matched sealed item")

    selected = tuple(matched_cohort.selected_item_hashes)
    controls = tuple(matched_cohort.control_item_hashes)
    target_selected_mean = _mean(rows[item].target_score for item in selected)
    target_control_mean = _mean(rows[item].target_score for item in controls)
    panel_selected_mean = _mean(_panel_mean(rows[item]) for item in selected)
    panel_control_mean = _mean(_panel_mean(rows[item]) for item in controls)
    direction = spec.validation_rule.metric_direction
    point_target_lift = _failure_lift(
        target_selected_mean,
        target_control_mean,
        direction,
    )
    point_specificity = point_target_lift - _failure_lift(
        panel_selected_mean,
        panel_control_mean,
        direction,
    )

    controls_by_selected: dict[str, list[str]] = defaultdict(list)
    for pair in matched_cohort.pairs:
        controls_by_selected[pair.selected_item_hash].append(pair.control_item_hash)
    clusters = tuple(
        (item, tuple(sorted(controls_by_selected[item]))) for item in selected
    )
    rng = random.Random(seed)
    target_draws: list[float] = []
    specificity_draws: list[float] = []
    for _ in range(spec.validation_rule.confidence_interval_draw_count):
        sampled = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        sampled_selected = [item for item, _ in sampled]
        sampled_controls = [control for _, group in sampled for control in group]
        target_lift = _failure_lift(
            _mean(rows[item].target_score for item in sampled_selected),
            _mean(rows[item].target_score for item in sampled_controls),
            direction,
        )
        panel_lift = _failure_lift(
            _mean(_panel_mean(rows[item]) for item in sampled_selected),
            _mean(_panel_mean(rows[item]) for item in sampled_controls),
            direction,
        )
        target_draws.append(target_lift)
        specificity_draws.append(target_lift - panel_lift)

    confidence = spec.validation_rule.required_confidence_level
    target_ci = _percentile_interval(target_draws, confidence, point_target_lift)
    specificity_ci = _percentile_interval(
        specificity_draws,
        confidence,
        point_specificity,
    )
    bootstrap = StressBootstrapArtifact(
        seed=seed,
        draw_count=len(target_draws),
        confidence_level=confidence,
        matched_cohort_hash=matched_cohort.digest,
        score_table_hash=score_table.digest,
        analysis_code_hash=analysis_code_hash,
        target_lift_ci=target_ci,
        target_specificity_ci=specificity_ci,
        target_lift_draws_hash=_digest(target_draws),
        target_specificity_draws_hash=_digest(specificity_draws),
    )
    analysis_hash = _digest(
        {
            "analysis_code_hash": analysis_code_hash,
            "bootstrap_hash": bootstrap.digest,
            "matched_cohort_hash": matched_cohort.digest,
            "score_table_hash": score_table.digest,
            "spec_digest": spec.acquisition_digest,
        }
    )
    record = StressValidationRecord(
        spec_digest=spec.acquisition_digest,
        sealed_validation_split_hash=spec.sealed_validation_split_hash,
        target=spec.target,
        comparison_panel_hash=spec.acquisition_panel_hash,
        comparison_panel_results_hash=score_table.digest,
        judge_panel_hash=spec.judge_hash,
        decision_rule=spec.validation_rule,
        matched_cohort=matched_cohort,
        metric=score_table.metric,
        metric_direction=direction,
        selected_n=len(selected),
        control_n=len(controls),
        target_selected_mean=target_selected_mean,
        target_control_mean=target_control_mean,
        panel_selected_mean=panel_selected_mean,
        panel_control_mean=panel_control_mean,
        target_lift_ci=target_ci,
        target_specificity_ci=specificity_ci,
        confidence_level=confidence,
        confidence_interval_artifact_hash=bootstrap.digest,
        analysis_hash=analysis_hash,
    )
    return StressValidationAnalysis(record=record, bootstrap=bootstrap)


def materialize_validated_stress_package(
    path: str | Path,
    *,
    spec: StressBenchmarkSpec,
    validation_record: StressValidationRecord,
    bootstrap_artifact: StressBootstrapArtifact,
    manifest: BenchmarkManifest,
    items: Iterable[BenchmarkItem],
    readme: str | None = None,
) -> Path:
    """Write a target-only regression package from a validated stress result."""

    if spec.lifecycle is not StressLifecycle.VALIDATED:
        raise ValueError("only a validated stress spec can be materialized")
    validation_record.validate_against(spec)
    if not isinstance(bootstrap_artifact, StressBootstrapArtifact):
        raise ValueError("bootstrap_artifact must be StressBootstrapArtifact")
    if validation_record.confidence_interval_artifact_hash != bootstrap_artifact.digest:
        raise ValueError("validation record does not bind the bootstrap artifact")
    if (
        bootstrap_artifact.matched_cohort_hash
        != validation_record.matched_cohort.digest
    ):
        raise ValueError(
            "bootstrap artifact does not bind the validated matched cohort"
        )
    if (
        bootstrap_artifact.score_table_hash
        != validation_record.comparison_panel_results_hash
    ):
        raise ValueError("bootstrap artifact does not bind the validated score table")
    materialized = tuple(items)
    if not materialized or not all(
        isinstance(item, BenchmarkItem) for item in materialized
    ):
        raise ValueError("stress package items must contain BenchmarkItem values")
    by_hash: dict[str, BenchmarkItem] = {}
    for item in materialized:
        item_hash = item.metadata.get("item_hash")
        _hash(f"item {item.id} metadata.item_hash", item_hash)
        if item_hash in by_hash:
            raise ValueError("stress package contains duplicate item_hash values")
        by_hash[item_hash] = item
    expected = set(validation_record.matched_cohort.selected_item_hashes)
    if set(by_hash) != expected:
        raise ValueError(
            "stress package must contain exactly the validated selected cohort"
        )

    manifest.validate()
    provenance = dict(manifest.provenance)
    bindings = {
        "stress_claim_scope": spec.claim_scope,
        "stress_spec_digest": spec.digest,
        "stress_validation_digest": validation_record.digest,
        "target_model": spec.target.to_dict(),
        "deployment_scope": "target-snapshot-regression-only",
    }
    conflicts = [
        key
        for key, value in bindings.items()
        if key in provenance and provenance[key] != value
    ]
    if conflicts:
        raise ValueError(
            "benchmark manifest has conflicting stress provenance: "
            + ", ".join(sorted(conflicts))
        )
    provenance.update(bindings)
    bound_manifest = BenchmarkManifest(
        id=manifest.id,
        name=manifest.name,
        version=manifest.version,
        modality=manifest.modality,
        scorer=dict(manifest.scorer),
        mast_compatible=manifest.mast_compatible,
        provenance=provenance,
    )
    package_readme = readme or (
        "This is a validated target-snapshot regression benchmark. It is not "
        "a general leaderboard benchmark and does not establish MAST admission.\n"
    )
    return write_package(
        path,
        manifest=bound_manifest,
        items=tuple(by_hash[item_hash] for item_hash in sorted(by_hash)),
        readme=package_readme,
        stress_spec=spec.to_dict(),
        stress_validation=validation_record.to_dict(),
        stress_bootstrap=bootstrap_artifact.to_dict(),
        write_asset_manifest=True,
    )


def _feature_rows(
    name: str, rows: Sequence[StressFeatureRow]
) -> tuple[StressFeatureRow, ...]:
    values = tuple(rows)
    if not values or not all(isinstance(row, StressFeatureRow) for row in values):
        raise ValueError(f"{name} must contain StressFeatureRow values")
    if len({row.item_hash for row in values}) != len(values):
        raise ValueError(f"{name} contains duplicate item hashes")
    return tuple(sorted(values, key=lambda row: row.item_hash))


def _calipers(controls: Sequence[MatchingControl]) -> dict[str, float]:
    result: dict[str, float] = {}
    for control in controls:
        if control.maximum_distance is None:
            raise ValueError("every matching control requires maximum_distance")
        for feature in control.features:
            prior = result.get(feature)
            if prior is not None and not math.isclose(
                prior,
                control.maximum_distance,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError(
                    f"matching feature {feature!r} has conflicting calipers"
                )
            result[feature] = control.maximum_distance
    return result


def _panel_mean(row: StressItemScore) -> float:
    return _mean(row.panel_scores.values())


def _failure_lift(selected: float, control: float, direction: MetricDirection) -> float:
    value = selected - control
    return -value if direction is MetricDirection.LOWER_IS_FAILURE else value


def _percentile_interval(draws: Sequence[float], confidence: float, point_estimate: float) -> tuple[float, float]:
    return percentile_interval(draws, confidence, point_estimate, quantile_fn=_quantile)


def _quantile(ordered: Sequence[float], probability: float) -> float:
    return ordered[0] if len(ordered) == 1 else quantile(ordered, probability, weighted=True)


def _finite(name: str, value: Any) -> float:
    return number(value, name)


def _hash(name: str, value: Any) -> str:
    return sha256_hex(value, name)


def _text(name: str, value: Any) -> str:
    return text(value, name)


__all__ = [
    "StressBootstrapArtifact",
    "StressFeatureRow",
    "StressItemScore",
    "StressScoreTable",
    "StressValidationAnalysis",
    "analyze_stress_validation",
    "match_stress_cohorts",
    "materialize_validated_stress_package",
    "model_snapshot_key",
]
