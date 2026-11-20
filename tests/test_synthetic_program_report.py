from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace

import pytest

from arisekit.archetype import (
    ArchetypeId,
    MarginUnit,
    ModelRoute,
    ParityMargin,
    ReferenceAccessClass,
    ReferenceAuthority,
    ReferenceBundleBinding,
    SpecialtyPlanCellBinding,
    SpecialtySourcePlanBinding,
    SyntheticBenchmarkProgram,
    SyntheticBundleBinding,
    SyntheticComparison,
    builtin_archetype_registry,
)
from arisekit.authoring.specialty import BenchmarkTrack
from arisekit.run_manifest import RunManifest
from arisekit.synthetic_parity import (
    ArmRole,
    BenchmarkArm,
    EndpointObservation,
    ModelIdentity,
    ParityDecisionRule,
    ParityVerdict,
    REPRESENTATIVE_VERDICT_SCOPE,
    RUN_MANIFEST_ADAPTER_CODE_HASH_KEY,
    RUN_MANIFEST_EVALUATION_CONTRACT_HASH_KEY,
    RUN_MANIFEST_EXPECTED_PROVIDER_IDENTITY_KEY,
    RUN_MANIFEST_ROUTE_FAMILY_KEY,
    RUN_MANIFEST_ROUTE_SNAPSHOT_KEY,
    RUN_MANIFEST_RUNTIME_CONFIG_HASH_KEY,
    RUN_MANIFEST_SELECTION_HASH_KEY,
    RUN_MANIFEST_SELECTION_PROTOCOL_HASH_KEY,
    STRESS_VERDICT_SCOPE,
    ScopeParityResult,
    SelectionBasis,
    SelectionManifest,
    SelectionPair,
    SolverRunAdapterReceipt,
    SolverRunEvidence,
    SyntheticParityInput,
    SyntheticParityReport,
    VariantSlot,
    VariantSlotKind,
    analyze_synthetic_parity,
    canonical_solver_observation_subset_sha256,
)
from arisekit.analysis.synthetic_program_report import (
    NO_MULTIPLICITY_CLAIM_STATUS,
    NO_OMNIBUS_VERDICT_STATUS,
    REPRESENTATIVE_COUNT_STATUS,
    STRESS_RESULT_STATUS,
    SyntheticProgramReport,
    aggregate_synthetic_program_reports,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _route(route_id: str, family: str) -> ModelRoute:
    return ModelRoute(
        route_id=route_id,
        provider=f"provider-{route_id}",
        model=f"model-{route_id}",
        snapshot="2026-07-01",
        family=family,
        runtime_config_hash=_hash(f"runtime-{route_id}"),
    )


def _rule() -> ParityDecisionRule:
    return ParityDecisionRule(
        per_model_delta_margin=0.05,
        absolute_difficulty_shift_margin=0.05,
        minimum_rank_agreement=0.90,
        minimum_discrimination_spread_ratio=0.80,
        maximum_discrimination_spread_ratio=1.20,
        confidence_level=0.95,
        bootstrap_draws=20,
        bootstrap_seed=17,
        minimum_case_family_pairs_per_scope=2,
    )


def _source_binding(label: str, track: BenchmarkTrack) -> SpecialtySourcePlanBinding:
    return SpecialtySourcePlanBinding(
        allocator_archetype_id="paired-specialty-equity",
        specialty_id="cardiology",
        track=track,
        spec_sha256=_hash(f"{label}-spec"),
        plan_sha256=_hash(f"{label}-plan"),
        clinical_scope_sha256=_hash(f"{label}-scope"),
        clinical_lock_sha256=_hash(f"{label}-clinical-lock"),
        authorization_sha256s=(_hash(f"{label}-authorization"),),
        planned_cells=(
            SpecialtyPlanCellBinding(
                cell_id=f"cardiology--{track.value}--invariant",
                family_count=2,
                cell_sha256=_hash(f"{label}-cell"),
            ),
        ),
        cell_inventory_sha256=_hash(f"{label}-synthetic-manifest"),
        materialized_bundle_sha256=_hash(f"{label}-synthetic"),
        study_design_sha256=_hash(f"{label}-study-design"),
        model_route_ids=("solver-0", "solver-1", "solver-2"),
        model_repetitions=1,
    )


def _comparison(
    label: str,
    track: BenchmarkTrack,
    rule: ParityDecisionRule,
) -> SyntheticComparison:
    binding = _source_binding(label, track)
    return SyntheticComparison(
        comparison_id=f"paired-{label}",
        archetype_id=ArchetypeId.PAIRED_EQUITY,
        specialty_id="cardiology",
        reference=ReferenceBundleBinding(
            access_class=ReferenceAccessClass.PUBLIC,
            bundle_hash=_hash(f"{label}-reference"),
            manifest_hash=_hash(f"{label}-reference-manifest"),
            source_revision=f"release-{label}",
            authority=ReferenceAuthority.UPSTREAM_RELEASE,
            authority_digest=_hash(f"{label}-upstream-authority"),
        ),
        synthetic=SyntheticBundleBinding(
            bundle_hash=_hash(f"{label}-synthetic"),
            manifest_hash=binding.cell_inventory_sha256,
            generation_lineage_hash=_hash(f"{label}-lineage"),
            clinical_review_hash=binding.clinical_lock_sha256,
            rights_review_hash=binding.authorization_set_sha256,
            generator=_route(f"generator-{label}", f"generator-family-{label}"),
        ),
        endpoint_id="invariant-unjustified-discordance",
        margin=ParityMargin(MarginUnit.RATE_DIFFERENCE, 0.05),
        decision_rule_hash=rule.digest,
        track=track,
        source_plan_binding=binding,
    )


def _program() -> tuple[SyntheticBenchmarkProgram, ParityDecisionRule]:
    rule = _rule()
    program = SyntheticBenchmarkProgram(
        program_id="repeated-parity-program",
        registry=builtin_archetype_registry(),
        comparisons=(
            _comparison("representative", BenchmarkTrack.REPRESENTATIVE, rule),
            _comparison("stress", BenchmarkTrack.STRESS, rule),
        ),
        solver_panel=(
            _route("solver-0", "solver-family-0"),
            _route("solver-1", "solver-family-1"),
            _route("solver-2", "solver-family-2"),
        ),
        judge_panel=(_route("judge", "judge-family"),),
        program_review_hash=_hash("program-review"),
    )
    return program, rule


def _selection(
    label: str,
    track: BenchmarkTrack,
) -> SelectionManifest:
    binding = _source_binding(label, track)
    plan_cell_ids = tuple(
        cell.cell_id for cell in binding.planned_cells for _ in range(cell.family_count)
    )
    pairs = tuple(
        SelectionPair(
            pair_id=f"{label}-pair-{index}",
            real_case_family_id=f"{label}-real-family-{index}",
            synthetic_case_family_id=f"{label}-synthetic-family-{index}",
            specialty="cardiology",
            sub_benchmark="invariant",
            track=track,
            plan_cell_id=plan_cell_ids[index - 1],
            variant_slots=tuple(
                VariantSlot(
                    slot_id=f"variant-{slot}",
                    kind=VariantSlotKind.VARIANT,
                    real_variant_id=f"{label}-real-{index}-{slot}",
                    synthetic_variant_id=f"{label}-synthetic-{index}-{slot}",
                )
                for slot in (1, 2)
            ),
        )
        for index in (1, 2)
    )
    return SelectionManifest(
        protocol_hash=_hash(f"{label}-selection-protocol"),
        pairing_code_hash=_hash(f"{label}-pairing-code"),
        real_selection_hash=_hash(f"{label}-real-selection"),
        synthetic_selection_hash=_hash(f"{label}-synthetic-selection"),
        selection_commit_hash=_hash(f"{label}-selection-commit"),
        basis=SelectionBasis.PREREGISTERED,
        selection_fields=("specialty", "sub_benchmark"),
        outcome_blind=True,
        committed_before_evaluation=True,
        uses_evaluated_outcomes=False,
        pairs=pairs,
    )


def _run_evidence(
    *,
    arms: tuple[BenchmarkArm, ...],
    program: SyntheticBenchmarkProgram,
    selection: SelectionManifest,
    observations: tuple[EndpointObservation, ...],
) -> tuple[SolverRunEvidence, ...]:
    expected_response_count = sum(len(pair.variant_slots) for pair in selection.pairs)
    values = []
    for arm in arms:
        for route in program.solver_panel:
            provider_identity = f"{route.provider}:{route.model}:{route.snapshot}"
            adapter_code_sha256 = _hash("solver-run-adapter-code")
            manifest = RunManifest(
                benchmark_arm=arm.arm_id,
                benchmark_content_hash=arm.content_hash,
                prompt_hash=_hash("prompt-contract"),
                code_hash=_hash("runner-code"),
                judge_hash=_hash("judge-contract"),
                model=route.model,
                provider=route.provider,
                trials=1,
                selection={
                    RUN_MANIFEST_SELECTION_HASH_KEY: arm.selection_manifest_hash,
                    RUN_MANIFEST_SELECTION_PROTOCOL_HASH_KEY: (
                        arm.selection_protocol_hash
                    ),
                    RUN_MANIFEST_EVALUATION_CONTRACT_HASH_KEY: (
                        arm.evaluation_contract_hash
                    ),
                },
                source_revision=arm.source_revision,
                model_config={
                    RUN_MANIFEST_ROUTE_SNAPSHOT_KEY: route.snapshot,
                    RUN_MANIFEST_ROUTE_FAMILY_KEY: route.family,
                    RUN_MANIFEST_RUNTIME_CONFIG_HASH_KEY: (route.runtime_config_hash),
                    RUN_MANIFEST_EXPECTED_PROVIDER_IDENTITY_KEY: (provider_identity),
                    RUN_MANIFEST_ADAPTER_CODE_HASH_KEY: adapter_code_sha256,
                },
            )
            checkpoint_payload = (
                f"checkpoint-export|{selection.selection_commit_hash}|"
                f"{arm.role.value}|{route.route_id}"
            ).encode("utf-8")
            checkpoint_sha256 = hashlib.sha256(checkpoint_payload).hexdigest()
            adapter_receipt = SolverRunAdapterReceipt(
                arm_role=arm.role,
                arm_id=arm.arm_id,
                model_route_id=route.route_id,
                run_manifest_digest=manifest.digest,
                checkpoint_export_sha256=checkpoint_sha256,
                adapter_id="fixture-solver-run-adapter",
                adapter_code_sha256=adapter_code_sha256,
                observed_provider_model_identity=provider_identity,
                observed_response_count=expected_response_count,
                observation_subset_sha256=(
                    canonical_solver_observation_subset_sha256(
                        observations,
                        arm_role=arm.role,
                        model_id=route.route_id,
                    )
                ),
            )
            values.append(
                SolverRunEvidence(
                    arm_role=arm.role,
                    arm_id=arm.arm_id,
                    model_route=route,
                    run_manifest=manifest,
                    run_manifest_digest=manifest.digest,
                    run_manifest_file_sha256=hashlib.sha256(
                        manifest.canonical_json().encode("utf-8")
                    ).hexdigest(),
                    expected_provider_model_identity=provider_identity,
                    observed_provider_model_identity=provider_identity,
                    raw_identity_checkpoint_sha256=checkpoint_sha256,
                    expected_response_count=expected_response_count,
                    observed_response_count=expected_response_count,
                    adapter_receipt=adapter_receipt,
                    adapter_receipt_file_sha256=hashlib.sha256(
                        adapter_receipt.canonical_json().encode("utf-8")
                    ).hexdigest(),
                )
            )
    return tuple(values)


def _evidence_pair(
    program: SyntheticBenchmarkProgram,
    rule: ParityDecisionRule,
    comparison_id: str,
) -> tuple[SyntheticParityInput, SyntheticParityReport]:
    comparison = program.comparison(comparison_id)
    label = (
        "representative"
        if comparison.track is BenchmarkTrack.REPRESENTATIVE
        else "stress"
    )
    selection = _selection(label, comparison.track)
    contract_hash = program.evaluation_contract_digest(comparison_id)
    arms = (
        BenchmarkArm(
            role=ArmRole.REAL,
            arm_id=f"{label}-real-arm",
            benchmark_id=f"{label}-real-benchmark",
            benchmark_version="1",
            content_hash=comparison.reference.bundle_hash,
            evaluation_contract_hash=contract_hash,
            selection_protocol_hash=selection.protocol_hash,
            selection_manifest_hash=selection.real_selection_hash,
            source_revision=comparison.reference.source_revision,
        ),
        BenchmarkArm(
            role=ArmRole.SYNTHETIC,
            arm_id=f"{label}-synthetic-arm",
            benchmark_id=f"{label}-synthetic-benchmark",
            benchmark_version="1",
            content_hash=comparison.synthetic.bundle_hash,
            evaluation_contract_hash=contract_hash,
            selection_protocol_hash=selection.protocol_hash,
            selection_manifest_hash=selection.synthetic_selection_hash,
            source_revision=f"{label}-generation",
        ),
    )
    models = tuple(
        ModelIdentity(model_id=route.route_id, model_family=route.family)
        for route in program.solver_panel
    )
    observations = []
    for pair_index, pair in enumerate(selection.pairs):
        for role in ArmRole:
            for slot_index, slot in enumerate(pair.variant_slots):
                for model_index, model in enumerate(models):
                    base = 0.20 + 0.25 * model_index
                    value = base + 0.01 * pair_index + 0.005 * slot_index
                    if role is ArmRole.SYNTHETIC:
                        value += 0.005
                    observations.append(
                        EndpointObservation(
                            arm_role=role,
                            specialty="cardiology",
                            sub_benchmark="invariant",
                            model_id=model.model_id,
                            model_family=model.model_family,
                            case_family_id=pair.case_family_id(role),
                            variant_slot_id=slot.slot_id,
                            variant_id=slot.variant_id(role),
                            trial=1,
                            endpoint=comparison.endpoint_id,
                            value=value,
                        )
                    )
    study = SyntheticParityInput(
        study_id=f"{label}-study",
        program_hash=program.digest,
        comparison_id=comparison_id,
        registry_hash=program.registry_digest,
        archetype_hash=program.registry.get(comparison.archetype_id).digest,
        evaluation_contract_hash=contract_hash,
        decision_rule_hash=rule.digest,
        benchmark_archetype=ArchetypeId(comparison.archetype_id).value,
        specialty=comparison.specialty_id,
        track=comparison.track,
        endpoint=comparison.endpoint_id,
        trials=1,
        arms=arms,
        model_panel=models,
        run_evidence=_run_evidence(
            arms=arms,
            program=program,
            selection=selection,
            observations=tuple(observations),
        ),
        selection=selection,
        observations=tuple(observations),
        source_results_hash=_hash(f"{label}-source-results"),
        extraction_code_hash=_hash(f"{label}-extraction-code"),
    )
    report = analyze_synthetic_parity(
        study,
        rule,
        program=program,
        analysis_code_hash=_hash("analysis-code"),
    )
    return study, report


@pytest.fixture()
def aggregate_fixture() -> tuple[
    SyntheticBenchmarkProgram,
    tuple[SyntheticParityInput, SyntheticParityInput],
    tuple[SyntheticParityReport, SyntheticParityReport],
]:
    program, rule = _program()
    evidence_pairs = tuple(
        _evidence_pair(program, rule, comparison.comparison_id)
        for comparison in program.comparisons
    )
    return (
        program,
        tuple(pair[0] for pair in evidence_pairs),
        tuple(pair[1] for pair in evidence_pairs),
    )


def _rehash_artifact(data: dict[str, object]) -> None:
    data["artifact_hash"] = _canonical_hash(
        {key: value for key, value in data.items() if key != "artifact_hash"}
    )


def test_program_report_round_trip_preserves_hashes_and_track_semantics(
    aggregate_fixture,
) -> None:
    program, inputs, reports = aggregate_fixture
    evidence_pairs = tuple(zip(inputs, reports, strict=True))
    result = aggregate_synthetic_program_reports(
        program,
        tuple(reversed(evidence_pairs)),
    )

    assert tuple(result.report_hashes) == tuple(
        comparison.comparison_id for comparison in program.comparisons
    )
    assert dict(result.report_hashes) == {
        report.comparison_id: report.digest for report in reports
    }
    assert dict(result.representative_verdict_counts) == {
        ParityVerdict.EQUIVALENT.value: 1,
        ParityVerdict.NON_EQUIVALENT.value: 0,
        ParityVerdict.INCONCLUSIVE.value: 0,
    }
    assert result.representative_report_count == 1
    assert result.stress_diagnostic_count == 1
    assert result.program_verdict is None
    assert result.multiplicity_claim is None

    data = result.to_dict()
    assert data["representative_count_status"] == REPRESENTATIVE_COUNT_STATUS
    assert data["stress_result_status"] == STRESS_RESULT_STATUS
    assert data["program_verdict_status"] == NO_OMNIBUS_VERDICT_STATUS
    assert data["multiplicity_claim_status"] == NO_MULTIPLICITY_CLAIM_STATUS
    assert data["comparison_reports"][0]["terminal_verdict"] == "equivalent"
    assert data["comparison_reports"][1]["terminal_verdict"] is None
    assert data["comparison_reports"][1]["overall_diagnostic_verdict"] == "equivalent"

    loaded = SyntheticProgramReport.from_json(
        result.canonical_json(),
        program=program,
    )
    assert loaded.to_dict() == result.to_dict()
    assert loaded.digest == result.digest


def test_public_aggregation_requires_exact_input_report_pairs(
    aggregate_fixture,
) -> None:
    program, inputs, reports = aggregate_fixture

    with pytest.raises(ValueError, match="two-item"):
        aggregate_synthetic_program_reports(program, reports)
    with pytest.raises(ValueError, match="input digest does not match"):
        aggregate_synthetic_program_reports(
            program,
            (
                (inputs[1], reports[0]),
                (inputs[0], reports[1]),
            ),
        )


def test_public_aggregation_replays_each_report_before_completion(
    aggregate_fixture,
) -> None:
    program, inputs, reports = aggregate_fixture
    forged = replace(
        reports[0],
        source_results_hash=_hash("structurally-valid-forged-source-results"),
    )

    structural_only = SyntheticProgramReport(
        program=program,
        reports=(forged, reports[1]),
    )
    assert structural_only.reports[0].source_results_hash == forged.source_results_hash

    with pytest.raises(ValueError, match="not exactly derived"):
        aggregate_synthetic_program_reports(
            program,
            (
                (inputs[0], forged),
                (inputs[1], reports[1]),
            ),
        )


def test_input_order_does_not_change_canonical_artifact(
    aggregate_fixture,
) -> None:
    program, _inputs, reports = aggregate_fixture
    forward = SyntheticProgramReport(program=program, reports=reports)
    reverse = SyntheticProgramReport(program=program, reports=tuple(reversed(reports)))

    assert forward.canonical_json() == reverse.canonical_json()
    assert forward.digest == reverse.digest


def test_requires_complete_nonduplicate_comparison_coverage(
    aggregate_fixture,
) -> None:
    program, _inputs, reports = aggregate_fixture

    with pytest.raises(ValueError, match="coverage"):
        SyntheticProgramReport(program=program, reports=(reports[0],))
    with pytest.raises(ValueError, match="duplicate comparison"):
        SyntheticProgramReport(
            program=program,
            reports=(reports[0], reports[0], reports[1]),
        )
    unknown = replace(reports[0], comparison_id="unknown-comparison")
    with pytest.raises(ValueError, match="coverage"):
        SyntheticProgramReport(
            program=program,
            reports=(unknown, reports[1]),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("program_hash", _hash("wrong-program"), "program hash"),
        ("registry_hash", _hash("wrong-registry"), "registry hash"),
        ("archetype_hash", _hash("wrong-archetype"), "archetype hash"),
        (
            "evaluation_contract_hash",
            _hash("wrong-contract"),
            "evaluation contract hash",
        ),
        ("benchmark_archetype", "noharm", "benchmark archetype"),
        ("endpoint", "severe-error-rate", "endpoint"),
    ),
)
def test_rejects_stale_report_bindings(
    aggregate_fixture,
    field: str,
    value: str,
    message: str,
) -> None:
    program, _inputs, reports = aggregate_fixture
    stale = replace(reports[0], **{field: value})

    with pytest.raises(ValueError, match=message):
        SyntheticProgramReport(program=program, reports=(stale, reports[1]))


def _remap_scope_model(
    scope: ScopeParityResult,
    *,
    model_id: str,
    model_family: str,
) -> ScopeParityResult:
    first, *rest = scope.model_results
    return replace(
        scope,
        model_results=(
            replace(first, model_id=model_id, model_family=model_family),
            *rest,
        ),
    )


def test_rejects_an_internally_valid_but_different_solver_panel(
    aggregate_fixture,
) -> None:
    program, _inputs, reports = aggregate_fixture
    source = reports[0]
    changed = replace(
        source,
        model_panel=(
            ModelIdentity("other-solver", "other-family"),
            *source.model_panel[1:],
        ),
        overall=_remap_scope_model(
            source.overall,
            model_id="other-solver",
            model_family="other-family",
        ),
        specialty_results=tuple(
            _remap_scope_model(
                scope,
                model_id="other-solver",
                model_family="other-family",
            )
            for scope in source.specialty_results
        ),
        sub_benchmark_results=tuple(
            _remap_scope_model(
                scope,
                model_id="other-solver",
                model_family="other-family",
            )
            for scope in source.sub_benchmark_results
        ),
    )

    with pytest.raises(ValueError, match="model panel"):
        SyntheticProgramReport(program=program, reports=(changed, reports[1]))


def test_rejects_specialty_track_and_decision_rule_mismatches(
    aggregate_fixture,
) -> None:
    program, _inputs, reports = aggregate_fixture
    source = reports[0]
    wrong_specialty = replace(
        source,
        specialty="neurology",
        specialty_results=tuple(
            replace(scope, specialty="neurology") for scope in source.specialty_results
        ),
        sub_benchmark_results=tuple(
            replace(scope, specialty="neurology")
            for scope in source.sub_benchmark_results
        ),
    )
    with pytest.raises(ValueError, match="specialty"):
        SyntheticProgramReport(
            program=program,
            reports=(wrong_specialty, reports[1]),
        )

    wrong_track = replace(
        source,
        track=BenchmarkTrack.STRESS,
        verdict_scope=STRESS_VERDICT_SCOPE,
    )
    with pytest.raises(ValueError, match="track"):
        SyntheticProgramReport(program=program, reports=(wrong_track, reports[1]))

    other_rule = replace(source.decision_rule, per_model_delta_margin=0.06)

    def update_rule_bounds(scope: ScopeParityResult) -> ScopeParityResult:
        return replace(
            scope,
            model_results=tuple(
                replace(
                    result,
                    delta=replace(
                        result.delta,
                        acceptable_lower=-0.06,
                        acceptable_upper=0.06,
                    ),
                )
                for result in scope.model_results
            ),
        )

    wrong_rule = replace(
        source,
        decision_rule=other_rule,
        decision_rule_hash=other_rule.digest,
        overall=update_rule_bounds(source.overall),
        specialty_results=tuple(
            update_rule_bounds(scope) for scope in source.specialty_results
        ),
        sub_benchmark_results=tuple(
            update_rule_bounds(scope) for scope in source.sub_benchmark_results
        ),
    )
    with pytest.raises(ValueError, match="decision rule hash"):
        SyntheticProgramReport(program=program, reports=(wrong_rule, reports[1]))


def test_loading_requires_the_exact_program(aggregate_fixture) -> None:
    program, _inputs, reports = aggregate_fixture
    artifact = SyntheticProgramReport(program=program, reports=reports)
    wrong_program = replace(
        program,
        program_review_hash=_hash("different-program-review"),
    )

    with pytest.raises(ValueError, match="hash does not match supplied program"):
        SyntheticProgramReport.from_json(
            artifact.canonical_json(),
            program=wrong_program,
        )


def test_loading_rejects_duplicate_json_keys(aggregate_fixture) -> None:
    program, _inputs, reports = aggregate_fixture
    payload = SyntheticProgramReport(program=program, reports=reports).canonical_json()
    duplicate = payload.replace(
        '"schema_version":',
        '"schema_version":"duplicate","schema_version":',
        1,
    )

    with pytest.raises(ValueError, match="duplicate JSON key"):
        SyntheticProgramReport.from_json(duplicate, program=program)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("representative_report_count", 99),
        (
            "representative_verdict_counts",
            {
                "equivalent": 0,
                "non-equivalent": 1,
                "inconclusive": 0,
            },
        ),
        ("program_verdict", "equivalent"),
        ("multiplicity_claim", "holm-adjusted"),
    ),
)
def test_loading_rejects_rehashed_nonderived_claims(
    aggregate_fixture,
    field: str,
    value: object,
) -> None:
    program, _inputs, reports = aggregate_fixture
    data = copy.deepcopy(
        SyntheticProgramReport(program=program, reports=reports).to_dict()
    )
    data[field] = value
    _rehash_artifact(data)

    with pytest.raises(ValueError, match="stale or non-derived"):
        SyntheticProgramReport.from_dict(data, program=program)


def test_loading_rejects_rehashed_report_hash_substitution(
    aggregate_fixture,
) -> None:
    program, _inputs, reports = aggregate_fixture
    data = copy.deepcopy(
        SyntheticProgramReport(program=program, reports=reports).to_dict()
    )
    data["comparison_reports"][0]["report_hash"] = _hash("substituted-report")
    _rehash_artifact(data)

    with pytest.raises(ValueError, match="parity report hash mismatch"):
        SyntheticProgramReport.from_dict(data, program=program)


def test_representative_verdict_scope_remains_terminal(
    aggregate_fixture,
) -> None:
    program, _inputs, reports = aggregate_fixture
    representative, stress = reports

    assert representative.verdict_scope == REPRESENTATIVE_VERDICT_SCOPE
    assert representative.terminal_verdict is ParityVerdict.EQUIVALENT
    assert stress.verdict_scope == STRESS_VERDICT_SCOPE
    assert stress.terminal_verdict is None

    artifact = SyntheticProgramReport(program=program, reports=reports)
    assert sum(artifact.representative_verdict_counts.values()) == 1
