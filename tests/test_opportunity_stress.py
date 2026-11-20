"""Portable opportunity and target-stress contracts reject scope leakage."""

from __future__ import annotations

import hashlib
import json

import pytest

from arisekit.package import BenchmarkManifest, load_package
from arisekit.authoring.opportunity import (
    ClinicalNeedOwnership,
    ConstructCoordinates,
    EvidenceAccessClass,
    EvidenceBoundary,
    FingerprintStatisticDirection,
    FingerprintSignalValidation,
    NeedReviewStatus,
    OpportunityEvidence,
    OpportunitySignal,
    OpportunityTrack,
    PilotTargets,
    PortfolioOpportunity,
    ResultCell,
)
from arisekit.analysis.stress import (
    AcquisitionEvidence,
    AcquisitionInputSplit,
    AcquisitionLineage,
    CohortManifest,
    CohortRole,
    ConfidenceIntervalMethod,
    ConfidenceIntervalRule,
    FeatureDistance,
    JudgePanel,
    JudgePanelMember,
    MatchedCohortManifest,
    MatchedPair,
    MatchingControl,
    MetricDirection,
    ModelSnapshot,
    MultiplicityMethod,
    MultiplicityRule,
    ResidualSignalRole,
    ResidualSignalValidation,
    SampleSizeRule,
    StressBenchmarkSpec,
    StressLifecycle,
    StressValidationRecord,
    StressValidationVerdict,
    ValidationDecisionRule,
    ValidationEstimand,
    ValidationResamplingUnit,
)
from arisekit.analysis.stress_analysis import (
    StressFeatureRow,
    StressItemScore,
    StressScoreTable,
    StressValidationAnalysis,
    analyze_stress_validation,
    match_stress_cohorts,
    materialize_validated_stress_package,
    model_snapshot_key,
)
from arisekit.types import BenchmarkItem


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _coordinates(*, reverse: bool = False) -> ConstructCoordinates:
    cognitive_items = [("harm_safety", 0.6), ("management", 0.4)]
    if reverse:
        cognitive_items.reverse()
    return ConstructCoordinates(
        cognitive=dict(cognitive_items),
        domain={"general_medicine": 1.0},
        modality={"text": 1.0},
        task_format="free_text",
        scoring_method="llm_judge_rubric",
        ground_truth_source="physician_rubric",
        ground_truth_reliability=0.8,
        specialty_breadth="broad",
        realism="vignette",
        harm_sensitivity="high",
        scale_items=330,
        source_origin="mast-private-1/analysis/benchmark_geometry/constructs.yaml",
        coding_confidence="high",
    )


def _opportunity(
    signal: OpportunitySignal = OpportunitySignal.COVERAGE_GAP,
    *,
    reverse_coordinates: bool = False,
    missing: tuple[ResultCell, ...] = (),
) -> PortfolioOpportunity:
    benchmark_design = signal is OpportunitySignal.COVERAGE_GAP
    maintenance = signal in (OpportunitySignal.REDUNDANCY, OpportunitySignal.SATURATION)
    return PortfolioOpportunity(
        id="portfolio-opportunity-001",
        signal=signal,
        evidence=OpportunityEvidence(
            portfolio_snapshot_hash=_hash("portfolio"),
            construct_schema_hash=_hash("construct-schema"),
            result_matrix_hash=_hash("result-matrix"),
            analysis_code_hash=_hash("analysis-code"),
            signal_evidence_hash=_hash("signal-evidence"),
            source_revision="commit-abc123",
            signal_validation=(
                FingerprintSignalValidation(
                    difficulty_ability_baseline_hash=_hash("difficulty-ability"),
                    residual_analysis_hash=_hash("residual-analysis"),
                    permutation_null_hash=_hash("permutation-null"),
                    discovery_split_hash=_hash("fingerprint-discovery"),
                    heldout_split_hash=_hash("fingerprint-heldout"),
                    statistic_direction=(
                        FingerprintStatisticDirection.GREATER_OR_EQUAL
                    ),
                    discovery_threshold=0.3,
                    heldout_threshold=0.25,
                    maximum_permutation_p_value=0.05,
                    permutation_draws=1000,
                    observed_statistic=0.42,
                    permutation_p_value=0.01,
                    heldout_statistic=0.31,
                )
                if signal is not OpportunitySignal.MISSING_RESULT_CELLS
                else None
            ),
        ),
        evidence_boundary=EvidenceBoundary(
            access_class=EvidenceAccessClass.PRIVATE_SANITIZED,
            released_artifact_hash=_hash("signal-evidence"),
            private_source_hash=_hash("private-source"),
            sanitization_code_hash=_hash("sanitization-code"),
            reviewed_by="portfolio-data-owner",
            reviewed_at="2026-07-22T10:00:00Z",
        ),
        construct_coordinates=(
            _coordinates(reverse=reverse_coordinates)
            if benchmark_design or maintenance
            else None
        ),
        clinical_need=(
            ClinicalNeedOwnership(
                need_statement="Assess unsafe omissions in outpatient treatment plans.",
                clinical_owner="Dr Clinical Owner",
                owner_role="specialty lead",
                intended_users=("benchmark reviewers", "clinical researchers"),
                review_status=NeedReviewStatus.CLINICIAN_ATTESTED,
                attestation_hash=_hash("need-attestation"),
            )
            if benchmark_design
            else None
        ),
        pilot_targets=(
            PilotTargets(
                item_count=30,
                model_count=8,
                trials_per_item=3,
                primary_metrics=("weighted_f1", "harm_rate"),
                minimum_headroom=0.2,
                minimum_tier_count=3,
            )
            if benchmark_design
            else None
        ),
        maintenance_action=(
            "retire or merge the redundant benchmark" if maintenance else None
        ),
        collection_protocol_hash=(
            _hash("result-collection-protocol")
            if signal is OpportunitySignal.MISSING_RESULT_CELLS
            else None
        ),
        missing_result_cells=missing,
    )


def test_portfolio_opportunity_round_trips_and_serializes_deterministically():
    first = _opportunity()
    reordered = _opportunity(reverse_coordinates=True)

    assert first.track is OpportunityTrack.BENCHMARK_DESIGN
    assert first.canonical_json() == reordered.canonical_json()
    assert first.digest == reordered.digest
    restored = PortfolioOpportunity.from_dict(first.to_dict())
    assert restored.to_dict() == first.to_dict()
    assert restored.digest == first.digest

    with pytest.raises(TypeError):
        first.construct_coordinates.cognitive["calibration"] = 0.1


def test_missing_result_cells_are_a_distinct_collection_track():
    cell = ResultCell("scin", "model-x", "balanced_accuracy")
    missing = _opportunity(
        OpportunitySignal.MISSING_RESULT_CELLS,
        missing=(cell,),
    )
    assert missing.track is OpportunityTrack.RESULT_COLLECTION
    assert missing.to_dict()["track"] == "result-collection"

    with pytest.raises(ValueError, match="require missing cells"):
        _opportunity(OpportunitySignal.MISSING_RESULT_CELLS)
    with pytest.raises(ValueError, match="portfolio-maintenance opportunities"):
        _opportunity(OpportunitySignal.SATURATION, missing=(cell,))

    maintenance = _opportunity(OpportunitySignal.SATURATION)
    assert maintenance.track is OpportunityTrack.PORTFOLIO_MAINTENANCE
    assert maintenance.clinical_need is None
    assert maintenance.pilot_targets is None

    tampered = missing.to_dict()
    tampered["track"] = "benchmark-design"
    with pytest.raises(ValueError, match="track"):
        PortfolioOpportunity.from_dict(tampered)


def test_conceptual_signal_must_pass_its_frozen_confirmation_rule():
    payload = _opportunity().to_dict()
    payload["evidence"]["signal_validation"]["heldout_statistic"] = 0.1
    payload["evidence"]["signal_validation"]["confirmed"] = False

    with pytest.raises(ValueError, match="pass its frozen rule"):
        PortfolioOpportunity.from_dict(payload)


def _object_hash(value: object) -> str:
    rendered = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _matching(label: str, feature: str, *, disjoint: bool = False) -> MatchingControl:
    return MatchingControl(
        method="nearest-neighbor-with-caliper",
        features=(feature,),
        reference_pool_hash=_hash(f"pool:{label}"),
        controls_per_selected=1,
        maximum_distance=0.1,
        require_disjoint=disjoint,
        maximum_control_reuse=1,
    )


def _validation_rule(*, minimum_n: int = 2) -> ValidationDecisionRule:
    return ValidationDecisionRule(
        metric="weighted_f1",
        metric_direction=MetricDirection.LOWER_IS_FAILURE,
        estimand=ValidationEstimand.TARGET_SPECIFICITY_FAILURE_LIFT,
        validated_target_lift_minimum=0.10,
        validated_specificity_minimum=0.10,
        invalid_target_lift_maximum=0.0,
        invalid_specificity_maximum=0.0,
        nominal_confidence_level=0.95,
        confidence_interval_rule=ConfidenceIntervalRule.TWO_SIDED_SEPARATION,
        confidence_interval_method=(ConfidenceIntervalMethod.PAIRED_CLUSTER_BOOTSTRAP),
        confidence_interval_draw_count=10_000,
        resampling_unit=ValidationResamplingUnit.CASE_CLUSTER,
        sample_size=SampleSizeRule(
            minimum_selected_n=minimum_n,
            minimum_control_n=minimum_n,
            require_equal_groups=True,
        ),
        multiplicity=MultiplicityRule(
            method=MultiplicityMethod.NONE,
            hypothesis_count=1,
            hypothesis_family_hash=_hash("primary-validation-family"),
        ),
    )


def _stress(
    *, validation_rule: ValidationDecisionRule | None = None
) -> StressBenchmarkSpec:
    discovery = CohortManifest(
        CohortRole.DISCOVERY,
        (_hash("discovery:1"), _hash("discovery:2")),
    )
    calibration = CohortManifest(
        CohortRole.CALIBRATION,
        (_hash("calibration:1"), _hash("calibration:2")),
    )
    sealed = CohortManifest(
        CohortRole.SEALED_VALIDATION,
        (
            _hash("sealed:selected:1"),
            _hash("sealed:selected:2"),
            _hash("sealed:control:1"),
            _hash("sealed:control:2"),
        ),
    )
    discovery_signal = ResidualSignalValidation(
        role=ResidualSignalRole.DISCOVERY,
        cohort_hash=discovery.digest,
        difficulty_baseline_comparison_hash=_hash("discovery:difficulty-baseline"),
        ability_baseline_comparison_hash=_hash("discovery:ability-baseline"),
        residualization_code_hash=_hash("residualization-code"),
        residual_signal_hash=_hash("discovery:residual-signal"),
        permutation_null_hash=_hash("discovery:permutation-null"),
        observed_residual_statistic=0.31,
        permutation_draw_count=999,
        permutation_exceedance_count=9,
        tail_probability=0.01,
    )
    confirmation_signal = ResidualSignalValidation(
        role=ResidualSignalRole.HELDOUT_CONFIRMATION,
        cohort_hash=calibration.digest,
        difficulty_baseline_comparison_hash=_hash("confirmation:difficulty-baseline"),
        ability_baseline_comparison_hash=_hash("confirmation:ability-baseline"),
        residualization_code_hash=_hash("residualization-code"),
        residual_signal_hash=_hash("confirmation:residual-signal"),
        permutation_null_hash=_hash("confirmation:permutation-null"),
        observed_residual_statistic=0.24,
        permutation_draw_count=999,
        permutation_exceedance_count=19,
        tail_probability=0.02,
    )
    evidence = AcquisitionEvidence(
        discovery=discovery_signal,
        heldout_confirmation=confirmation_signal,
        selection_policy_hash=_hash("stress-selection-policy"),
        heldout_statistic_minimum=0.20,
        heldout_tail_probability_maximum=0.05,
    )
    acquisition_evidence_hash = evidence.digest
    lineage = AcquisitionLineage(
        discovery=discovery,
        calibration=calibration,
        evidence=evidence,
    )
    panel = (
        ModelSnapshot("panel-a", "family-a", "2026-06-01"),
        ModelSnapshot("panel-b", "family-b", "2026-06-15"),
    )
    judges = JudgePanel(
        members=(
            JudgePanelMember(
                id="judge-a",
                snapshot=ModelSnapshot("judge-a-model", "judge-family-a", "2026-06-01"),
                role="clinical-correctness",
                configuration_hash=_hash("judge-a-config"),
            ),
            JudgePanelMember(
                id="judge-b",
                snapshot=ModelSnapshot("judge-b-model", "judge-family-b", "2026-06-15"),
                role="harm-review",
                configuration_hash=_hash("judge-b-config"),
            ),
        ),
        aggregation_method="predeclared-majority-with-adjudication",
        panel_configuration_hash=_hash("judge-panel-config"),
    )
    return StressBenchmarkSpec(
        id="stress-gpt-snapshot-001",
        target=ModelSnapshot("target-model", "target-family", "2026-07-01"),
        acquisition_panel=panel,
        excluded_lineages=("target-family", "target-family-mini"),
        acquisition_panel_hash=_object_hash([member.to_dict() for member in panel]),
        acquisition_lineage=lineage,
        sealed_validation_cohort=sealed,
        discovery_split_hash=discovery.digest,
        calibration_split_hash=calibration.digest,
        sealed_validation_split_hash=sealed.digest,
        acquisition_evidence_hash=acquisition_evidence_hash,
        acquisition_input_splits=(
            AcquisitionInputSplit.DISCOVERY,
            AcquisitionInputSplit.CALIBRATION,
        ),
        residualization_method="two-way item-and-model residual",
        acquisition_method="target residual cofailure enrichment",
        difficulty_matching=_matching("difficulty", "baseline_difficulty"),
        source_matching=_matching("source", "source_origin"),
        case_matching=_matching("case", "case_cluster", disjoint=True),
        prompt_hash=_hash("prompt"),
        rubric_hash=_hash("rubric"),
        judge_panel=judges,
        judge_hash=judges.digest,
        validation_rule=validation_rule or _validation_rule(),
        source_revision="commit-def456",
        lifecycle=StressLifecycle.FROZEN,
    )


def test_stress_spec_round_trips_with_target_specific_scope():
    spec = _stress()

    assert spec.claim_scope == "target-specific-stress-only"
    restored = StressBenchmarkSpec.from_dict(spec.to_dict())
    assert restored.to_dict() == spec.to_dict()
    assert restored.canonical_json() == spec.canonical_json()
    assert restored.digest == spec.digest


def test_stress_spec_blocks_validation_leakage_and_lineage_overlap():
    payload = _stress().to_dict()
    payload["acquisition_input_splits"] = ["sealed-validation"]
    with pytest.raises(ValueError):
        StressBenchmarkSpec.from_dict(payload)

    payload = _stress().to_dict()
    payload["validation_outcomes"] = {"stress_control_delta": 0.3}
    with pytest.raises(ValueError, match="unknown=.*validation_outcomes"):
        StressBenchmarkSpec.from_dict(payload)

    payload = _stress().to_dict()
    payload["acquisition_lineage"]["discovery"]["item_hashes"][0] = payload[
        "sealed_validation_cohort"
    ]["item_hashes"][0]
    payload["discovery_split_hash"] = CohortManifest.from_dict(
        payload["acquisition_lineage"]["discovery"]
    ).digest
    payload["acquisition_lineage"]["evidence"]["discovery"]["cohort_hash"] = payload[
        "discovery_split_hash"
    ]
    payload["acquisition_evidence_hash"] = AcquisitionEvidence.from_dict(
        payload["acquisition_lineage"]["evidence"]
    ).digest
    with pytest.raises(ValueError, match="sealed validation cases"):
        StressBenchmarkSpec.from_dict(payload)

    payload = _stress().to_dict()
    payload["lifecycle"] = StressLifecycle.VALIDATED.value
    payload["validation_record_hash"] = _hash("unverified-validation")
    with pytest.raises(ValueError, match="bound validation_record"):
        StressBenchmarkSpec.from_dict(payload)
    with pytest.raises(ValueError, match="verified validation record"):
        StressBenchmarkSpec(
            **{
                **_stress().__dict__,
                "lifecycle": StressLifecycle.VALIDATED,
                "validation_record_hash": _hash("unverified-validation"),
            }
        )

    payload = _stress().to_dict()
    payload["validation_record_hash"] = payload["acquisition_evidence_hash"]
    payload["lifecycle"] = StressLifecycle.INVALID.value
    with pytest.raises(ValueError, match="bound validation_record"):
        StressBenchmarkSpec.from_dict(payload)

    payload = _stress().to_dict()
    payload["acquisition_panel"][0]["family"] = "target-family"
    tampered_panel = sorted(
        (ModelSnapshot.from_dict(member) for member in payload["acquisition_panel"]),
        key=lambda member: (member.family, member.model, member.snapshot),
    )
    payload["acquisition_panel_hash"] = _object_hash(
        [member.to_dict() for member in tampered_panel]
    )
    with pytest.raises(ValueError, match="excluded model lineages"):
        StressBenchmarkSpec.from_dict(payload)

    payload = _stress().to_dict()
    payload["judge_panel"]["members"][0]["configuration_hash"] = _hash(
        "tampered-judge-config"
    )
    with pytest.raises(ValueError, match="judge_hash"):
        StressBenchmarkSpec.from_dict(payload)

    payload = _stress().to_dict()
    payload["acquisition_lineage"]["evidence"]["discovery"]["tail_probability"] = 0.02
    with pytest.raises(ValueError, match="finite-sample permutation"):
        StressBenchmarkSpec.from_dict(payload)

    payload = _stress().to_dict()
    payload["acquisition_lineage"]["evidence"]["heldout_confirmation"][
        "cohort_hash"
    ] = payload["discovery_split_hash"]
    with pytest.raises(ValueError, match="cohorts must differ"):
        StressBenchmarkSpec.from_dict(payload)

    payload = _stress().to_dict()
    payload["acquisition_lineage"]["evidence"]["heldout_confirmation"][
        "observed_residual_statistic"
    ] = 0.19
    with pytest.raises(ValueError, match="preregistered minimum"):
        StressBenchmarkSpec.from_dict(payload)

    payload = _stress().to_dict()
    payload["acquisition_evidence_hash"] = _hash("opaque-unsupported-claim")
    with pytest.raises(ValueError, match="acquisition_evidence_hash"):
        StressBenchmarkSpec.from_dict(payload)


def _matched_cohort(spec: StressBenchmarkSpec) -> MatchedCohortManifest:
    selected = (_hash("sealed:selected:1"), _hash("sealed:selected:2"))
    controls = (_hash("sealed:control:1"), _hash("sealed:control:2"))
    pairs = tuple(
        MatchedPair(
            selected_item_hash=selected[index],
            control_item_hash=controls[index],
            distances=(
                FeatureDistance("baseline_difficulty", 0.04 + index * 0.01),
                FeatureDistance("source_origin", 0.0),
                FeatureDistance("case_cluster", 0.0),
            ),
        )
        for index in range(2)
    )
    return MatchedCohortManifest.create(
        selected_item_hashes=selected,
        control_item_hashes=controls,
        pairs=pairs,
        matching_controls=spec.matching_controls,
    )


def _validation_record(
    spec: StressBenchmarkSpec,
    *,
    target_selected_mean: float = 0.42,
    target_control_mean: float = 0.70,
    panel_selected_mean: float = 0.65,
    panel_control_mean: float = 0.70,
    target_lift_ci: tuple[float, float] = (0.18, 0.37),
    target_specificity_ci: tuple[float, float] = (0.15, 0.31),
) -> StressValidationRecord:
    return StressValidationRecord(
        spec_digest=spec.acquisition_digest,
        sealed_validation_split_hash=spec.sealed_validation_split_hash,
        target=spec.target,
        comparison_panel_hash=spec.acquisition_panel_hash,
        comparison_panel_results_hash=_hash("comparison-panel-results"),
        judge_panel_hash=spec.judge_hash,
        decision_rule=spec.validation_rule,
        matched_cohort=_matched_cohort(spec),
        metric="weighted_f1",
        metric_direction=MetricDirection.LOWER_IS_FAILURE,
        selected_n=2,
        control_n=2,
        target_selected_mean=target_selected_mean,
        target_control_mean=target_control_mean,
        panel_selected_mean=panel_selected_mean,
        panel_control_mean=panel_control_mean,
        target_lift_ci=target_lift_ci,
        target_specificity_ci=target_specificity_ci,
        confidence_level=spec.validation_rule.required_confidence_level,
        confidence_interval_artifact_hash=_hash("validation-confidence-intervals"),
        analysis_hash=_hash("validation-analysis"),
    )


def test_sealed_stress_validation_is_derived_and_binds_to_spec():
    frozen = _stress()
    record = _validation_record(frozen)
    validated = frozen.finalize_validation(record)

    assert record.target_failure_lift == pytest.approx(0.28)
    assert record.panel_failure_lift == pytest.approx(0.05)
    assert record.target_specificity_lift == pytest.approx(0.23)
    assert record.verdict is StressValidationVerdict.VALIDATED
    assert validated.lifecycle is StressLifecycle.VALIDATED
    assert StressValidationRecord.from_dict(record.to_dict()).digest == record.digest
    record.validate_against(validated)

    with pytest.raises(ValueError, match="bound validation_record"):
        StressBenchmarkSpec.from_dict(validated.to_dict())
    restored = StressBenchmarkSpec.from_dict(
        validated.to_dict(), validation_record=record
    )
    assert restored.digest == validated.digest
    with pytest.raises(ValueError, match="verified validation record"):
        StressBenchmarkSpec(
            **{
                **validated.__dict__,
                "lifecycle": StressLifecycle.INVALID,
            }
        )
    with pytest.raises(ValueError, match="verified validation record"):
        StressBenchmarkSpec(
            **{
                **validated.__dict__,
                "source_revision": "forged-source-revision",
            }
        )

    tampered = record.to_dict()
    tampered["verdict"] = StressValidationVerdict.INVALID.value
    with pytest.raises(ValueError, match="verdict"):
        StressValidationRecord.from_dict(tampered)

    wrong_target = record.to_dict()
    wrong_target["target"]["snapshot"] = "different-snapshot"
    with pytest.raises(ValueError, match="target does not match"):
        StressValidationRecord.from_dict(wrong_target).validate_against(validated)


def test_validation_rule_derives_invalid_and_inconclusive_lifecycles():
    frozen = _stress()
    inconclusive_record = _validation_record(
        frozen,
        target_specificity_ci=(0.05, 0.31),
    )
    assert inconclusive_record.verdict is StressValidationVerdict.INCONCLUSIVE
    assert (
        frozen.finalize_validation(inconclusive_record).lifecycle
        is StressLifecycle.INCONCLUSIVE
    )

    invalid_record = _validation_record(
        frozen,
        target_selected_mean=0.67,
        target_control_mean=0.70,
        panel_selected_mean=0.65,
        panel_control_mean=0.70,
        target_lift_ci=(0.0, 0.08),
        target_specificity_ci=(-0.08, 0.0),
    )
    assert invalid_record.target_specificity_lift == pytest.approx(-0.02)
    assert invalid_record.verdict is StressValidationVerdict.INVALID
    assert (
        frozen.finalize_validation(invalid_record).lifecycle is StressLifecycle.INVALID
    )

    underpowered = _stress(validation_rule=_validation_rule(minimum_n=3))
    underpowered_record = _validation_record(underpowered)
    assert underpowered_record.verdict is StressValidationVerdict.INCONCLUSIVE


def test_specificity_alone_cannot_validate_an_easier_target_set():
    frozen = _stress()
    record = _validation_record(
        frozen,
        target_selected_mean=0.75,
        target_control_mean=0.70,
        panel_selected_mean=0.95,
        panel_control_mean=0.70,
        target_lift_ci=(-0.10, 0.0),
        target_specificity_ci=(0.12, 0.28),
    )

    assert record.target_failure_lift == pytest.approx(-0.05)
    assert record.target_specificity_lift == pytest.approx(0.20)
    assert record.verdict is StressValidationVerdict.INVALID


def test_matched_cohort_diagnostics_and_multiplicity_fail_closed():
    spec = _stress()
    cohort = _matched_cohort(spec)
    assert cohort.diagnostics.selected_count == 2
    assert cohort.diagnostics.control_count == 2
    assert cohort.diagnostics.selected_control_disjoint
    assert cohort.diagnostics.maximum_control_reuse == 1
    assert cohort.diagnostics.unmatched_selected_count == 0

    tampered = cohort.to_dict()
    tampered["diagnostics"]["maximum_control_reuse"] = 2
    with pytest.raises(ValueError, match="not reproducible"):
        MatchedCohortManifest.from_dict(tampered)

    selected = cohort.selected_item_hashes
    controls = cohort.control_item_hashes
    first_pair = cohort.pairs[0]
    excessive_distance_pairs = (
        MatchedPair(
            selected_item_hash=first_pair.selected_item_hash,
            control_item_hash=first_pair.control_item_hash,
            distances=(
                FeatureDistance("baseline_difficulty", 0.2),
                FeatureDistance("source_origin", 0.0),
                FeatureDistance("case_cluster", 0.0),
            ),
        ),
        cohort.pairs[1],
    )
    with pytest.raises(ValueError, match="exceeds caliper"):
        MatchedCohortManifest.create(
            selected_item_hashes=selected,
            control_item_hashes=controls,
            pairs=excessive_distance_pairs,
            matching_controls=spec.matching_controls,
        )

    bonferroni = ValidationDecisionRule(
        metric="weighted_f1",
        metric_direction=MetricDirection.LOWER_IS_FAILURE,
        estimand=ValidationEstimand.TARGET_SPECIFICITY_FAILURE_LIFT,
        validated_target_lift_minimum=0.10,
        validated_specificity_minimum=0.10,
        invalid_target_lift_maximum=0.0,
        invalid_specificity_maximum=0.0,
        nominal_confidence_level=0.95,
        confidence_interval_rule=ConfidenceIntervalRule.TWO_SIDED_SEPARATION,
        confidence_interval_method=(ConfidenceIntervalMethod.PAIRED_CLUSTER_BOOTSTRAP),
        confidence_interval_draw_count=10_000,
        resampling_unit=ValidationResamplingUnit.CASE_CLUSTER,
        sample_size=SampleSizeRule(2, 2, True),
        multiplicity=MultiplicityRule(
            MultiplicityMethod.BONFERRONI,
            2,
            _hash("two-hypothesis-validation-family"),
        ),
    )
    assert bonferroni.required_confidence_level == pytest.approx(0.975)
    bonferroni_spec = _stress(validation_rule=bonferroni)
    with pytest.raises(ValueError, match="confidence_level"):
        StressValidationRecord(
            **{
                **_validation_record(bonferroni_spec).__dict__,
                "confidence_level": 0.95,
            }
        )


def test_stress_matcher_builds_exact_deterministic_caliper_manifest():
    spec = _stress()
    selected_hashes = (_hash("sealed:selected:1"), _hash("sealed:selected:2"))
    control_hashes = (_hash("sealed:control:1"), _hash("sealed:control:2"))
    selected = (
        StressFeatureRow(
            selected_hashes[0],
            {"baseline_difficulty": 0.20, "source_origin": 0.0, "case_cluster": 0.0},
        ),
        StressFeatureRow(
            selected_hashes[1],
            {"baseline_difficulty": 0.80, "source_origin": 1.0, "case_cluster": 1.0},
        ),
    )
    controls = (
        StressFeatureRow(
            control_hashes[1],
            {"baseline_difficulty": 0.84, "source_origin": 1.0, "case_cluster": 1.0},
        ),
        StressFeatureRow(
            control_hashes[0],
            {"baseline_difficulty": 0.23, "source_origin": 0.0, "case_cluster": 0.0},
        ),
    )

    first = match_stress_cohorts(
        selected,
        controls,
        matching_controls=spec.matching_controls,
    )
    second = match_stress_cohorts(
        tuple(reversed(selected)),
        tuple(reversed(controls)),
        matching_controls=spec.matching_controls,
    )

    assert first.to_dict() == second.to_dict()
    assert first.digest == second.digest
    assert {
        (pair.selected_item_hash, pair.control_item_hash) for pair in first.pairs
    } == set(zip(selected_hashes, control_hashes, strict=True))


def _computed_stress_analysis():
    rule_payload = _validation_rule().to_dict()
    rule_payload["confidence_interval_draw_count"] = 250
    spec = _stress(validation_rule=ValidationDecisionRule.from_dict(rule_payload))
    matched = _matched_cohort(spec)
    panel_keys = [model_snapshot_key(model) for model in spec.acquisition_panel]
    scores = {
        _hash("sealed:selected:1"): (0.40, (0.65, 0.66)),
        _hash("sealed:selected:2"): (0.45, (0.70, 0.71)),
        _hash("sealed:control:1"): (0.70, (0.70, 0.71)),
        _hash("sealed:control:2"): (0.75, (0.75, 0.76)),
    }
    table = StressScoreTable(
        metric="weighted_f1",
        target=spec.target,
        comparison_panel=spec.acquisition_panel,
        sealed_validation_split_hash=spec.sealed_validation_split_hash,
        judge_panel_hash=spec.judge_hash,
        source_results_hash=_hash("sealed-item-level-results"),
        rows=tuple(
            StressItemScore(
                item_hash=item_hash,
                target_score=values[0],
                panel_scores=dict(zip(panel_keys, values[1], strict=True)),
            )
            for item_hash, values in scores.items()
        ),
    )
    analysis = analyze_stress_validation(
        spec,
        matched,
        table,
        seed=481516,
        analysis_code_hash=_hash("stress-analysis-code"),
    )
    return spec, analysis


def test_stress_analysis_computes_bound_cluster_bootstrap_from_item_scores():
    spec, analysis = _computed_stress_analysis()
    repeated = _computed_stress_analysis()[1]

    assert analysis.to_dict() == repeated.to_dict()
    assert analysis.record.target_failure_lift == pytest.approx(0.30)
    assert analysis.record.panel_failure_lift == pytest.approx(0.05)
    assert analysis.record.target_specificity_lift == pytest.approx(0.25)
    assert analysis.record.verdict is StressValidationVerdict.VALIDATED
    assert analysis.bootstrap.draw_count == 250
    assert (
        analysis.record.confidence_interval_artifact_hash == analysis.bootstrap.digest
    )
    assert (
        spec.finalize_validation(analysis.record).lifecycle is StressLifecycle.VALIDATED
    )
    restored = StressValidationAnalysis.from_dict(analysis.to_dict())
    assert restored.to_dict() == analysis.to_dict()
    assert restored.digest == analysis.digest


def test_only_validated_selected_stress_items_materialize_as_regression_package(
    tmp_path,
):
    frozen, analysis = _computed_stress_analysis()
    validated = frozen.finalize_validation(analysis.record)
    selected = analysis.record.matched_cohort.selected_item_hashes
    items = tuple(
        BenchmarkItem(
            id=f"stress-{index}",
            prompt=f"Approved stress prompt {index}",
            ground_truth=f"answer-{index}",
            metadata={"item_hash": item_hash},
        )
        for index, item_hash in enumerate(selected, start=1)
    )
    output = materialize_validated_stress_package(
        tmp_path / "stress-package",
        spec=validated,
        validation_record=analysis.record,
        bootstrap_artifact=analysis.bootstrap,
        manifest=BenchmarkManifest(
            id="target-stress-regression",
            name="Target stress regression",
            scorer={"kind": "exact-match"},
        ),
        items=items,
    )

    package = load_package(output, verify_assets=True)
    assert len(package.items) == 2
    assert package.stress_spec["lifecycle"] == "validated"
    assert package.stress_validation["schema_version"].endswith(".v2")
    assert package.stress_bootstrap["schema_version"].endswith(".v1")
    assert package.manifest.provenance["deployment_scope"] == (
        "target-snapshot-regression-only"
    )

    with pytest.raises(ValueError, match="only a validated"):
        materialize_validated_stress_package(
            tmp_path / "blocked-package",
            spec=frozen,
            validation_record=analysis.record,
            bootstrap_artifact=analysis.bootstrap,
            manifest=BenchmarkManifest("blocked", "Blocked"),
            items=items,
        )
