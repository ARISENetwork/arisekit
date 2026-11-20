from __future__ import annotations

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
from arisekit.authoring.content_inventory import (
    ContentFamilyBinding,
    ContentItemBinding,
    ReferenceSelectionInventory,
    canonical_family_content_sha256,
    canonical_item_content_sha256,
)
from arisekit.authoring.specialty import (
    AcuityAllocation,
    AcuityLevel,
    BenchmarkTrack,
    ConditionAllocation,
    ConditionFamily,
)
from arisekit.authoring.specialty_inventory import (
    AuthoredFamilyBinding,
    AuthoredItemBinding,
    SpecialtyCellBinding,
    SpecialtyCellInventory,
)
from arisekit.run_manifest import RunManifest
from arisekit.synthetic_parity import (
    ArmRole,
    BenchmarkArm,
    EndpointObservation,
    ModelIdentity,
    ParityDecisionRule,
    ParityVerdict,
    RUN_MANIFEST_ADAPTER_CODE_HASH_KEY,
    RUN_MANIFEST_EVALUATION_CONTRACT_HASH_KEY,
    RUN_MANIFEST_EXPECTED_PROVIDER_IDENTITY_KEY,
    SelectionBasis,
    SelectionManifest,
    SelectionPair,
    RUN_MANIFEST_ROUTE_FAMILY_KEY,
    RUN_MANIFEST_ROUTE_SNAPSHOT_KEY,
    RUN_MANIFEST_RUNTIME_CONFIG_HASH_KEY,
    RUN_MANIFEST_SELECTION_HASH_KEY,
    RUN_MANIFEST_SELECTION_PROTOCOL_HASH_KEY,
    SolverRunAdapterReceipt,
    SolverRunEvidence,
    SyntheticParityInput,
    SyntheticParityReport,
    VariantSlot,
    VariantSlotKind,
    analyze_synthetic_parity,
    canonical_solver_observation_subset_sha256,
    replay_synthetic_parity_report,
    spearman_rank_agreement,
    validate_cross_arm_content_isolation,
    validate_reference_selection_inventory,
    validate_synthetic_selection_inventory,
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


def _selection(
    *,
    basis: SelectionBasis = SelectionBasis.PREREGISTERED,
    uses_evaluated_outcomes: bool = False,
    outcome_blind: bool = True,
    committed_before_evaluation: bool = True,
    selection_fields: tuple[str, ...] = ("specialty", "sub_benchmark"),
    track: BenchmarkTrack = BenchmarkTrack.REPRESENTATIVE,
) -> SelectionManifest:
    pairs = []
    pair_index = 0
    for sub_benchmark in ("diagnosis", "management"):
        for _local_index in range(2):
            pair_index += 1
            pairs.append(
                SelectionPair(
                    pair_id=f"pair-{pair_index:02d}",
                    real_case_family_id=f"real-{pair_index:02d}",
                    synthetic_case_family_id=f"synthetic-{pair_index:02d}",
                    specialty="cardiology",
                    sub_benchmark=sub_benchmark,
                    track=track,
                    variant_slots=_noharm_slots(pair_index),
                    plan_cell_id=(f"cardiology--{track.value}--{sub_benchmark}"),
                )
            )
    return SelectionManifest(
        protocol_hash=_hash("selection-protocol"),
        pairing_code_hash=_hash("pairing-code"),
        real_selection_hash=_hash("real-selection"),
        synthetic_selection_hash=_hash("synthetic-selection"),
        selection_commit_hash=_hash("selection-commit"),
        basis=basis,
        selection_fields=selection_fields,
        outcome_blind=outcome_blind,
        committed_before_evaluation=committed_before_evaluation,
        uses_evaluated_outcomes=uses_evaluated_outcomes,
        pairs=tuple(pairs),
    )


def _noharm_slots(pair_index: int) -> tuple[VariantSlot, ...]:
    return tuple(
        VariantSlot(
            slot_id=("baseline" if slot_index == 0 else f"perturbation-{slot_index}"),
            kind=(
                VariantSlotKind.BASELINE
                if slot_index == 0
                else VariantSlotKind.PERTURBATION
            ),
            real_variant_id=f"real-{pair_index:02d}-variant-{slot_index}",
            synthetic_variant_id=f"synthetic-{pair_index:02d}-variant-{slot_index}",
        )
        for slot_index in range(5)
    )


def _route(route_id: str, family: str) -> ModelRoute:
    return ModelRoute(
        route_id=route_id,
        provider=f"provider-{route_id}",
        model=f"model-{route_id}",
        snapshot="2026-07-01",
        family=family,
        runtime_config_hash=_hash(f"runtime-{route_id}"),
    )


def _source_binding(
    model_count: int = 4,
    *,
    track: BenchmarkTrack = BenchmarkTrack.REPRESENTATIVE,
    family_count: int = 4,
) -> SpecialtySourcePlanBinding:
    route_ids = tuple(f"model-{index}" for index in range(model_count))
    return SpecialtySourcePlanBinding(
        allocator_archetype_id="noharm",
        specialty_id="cardiology",
        track=track,
        spec_sha256=_hash("specialty-spec"),
        plan_sha256=_hash("specialty-plan"),
        clinical_scope_sha256=_hash("clinical-scope"),
        clinical_lock_sha256=_hash("clinical-lock"),
        authorization_sha256s=(_hash("authorization"),),
        planned_cells=(
            SpecialtyPlanCellBinding(
                cell_id=f"cardiology--{track.value}--diagnosis",
                family_count=family_count // 2,
                cell_sha256=_hash(f"{track.value}-diagnosis-cell"),
            ),
            SpecialtyPlanCellBinding(
                cell_id=f"cardiology--{track.value}--management",
                family_count=family_count - family_count // 2,
                cell_sha256=_hash(f"{track.value}-management-cell"),
            ),
        ),
        cell_inventory_sha256=_hash("synthetic-manifest"),
        materialized_bundle_sha256=_hash("synthetic-content"),
        study_design_sha256=_hash("study-design"),
        model_route_ids=route_ids,
        model_repetitions=2,
    )


def _inventory_selection(
    *,
    track: BenchmarkTrack = BenchmarkTrack.REPRESENTATIVE,
) -> SelectionManifest:
    selection = _selection(track=track)
    return replace(
        selection,
        pairs=tuple(
            replace(
                pair,
                variant_slots=tuple(
                    VariantSlot(
                        slot_id=(
                            "baseline"
                            if slot_index == 0
                            else f"perturbation-{slot_index}"
                        ),
                        kind=(
                            VariantSlotKind.BASELINE
                            if slot_index == 0
                            else VariantSlotKind.PERTURBATION
                        ),
                        real_variant_id=(
                            pair.real_case_family_id
                            if slot_index == 0
                            else (f"{pair.real_case_family_id}-variant-{slot_index}")
                        ),
                        synthetic_variant_id=(
                            pair.synthetic_case_family_id
                            if slot_index == 0
                            else (
                                f"{pair.synthetic_case_family_id}"
                                f"-variant-{slot_index}"
                            )
                        ),
                    )
                    for slot_index in range(5)
                ),
            )
            for pair in selection.pairs
        ),
    )


def _synthetic_inventory(
    *,
    track: BenchmarkTrack = BenchmarkTrack.REPRESENTATIVE,
) -> SpecialtyCellInventory:
    def family(family_id: str) -> AuthoredFamilyBinding:
        authored_items = tuple(
            AuthoredItemBinding(
                item_id=item_id,
                canonical_content_sha256=canonical_item_content_sha256(
                    f"synthetic-presentation:{item_id}"
                ),
            )
            for item_id in (
                family_id,
                *(f"{family_id}-variant-{index}" for index in range(1, 11)),
            )
        )
        return AuthoredFamilyBinding(
            family_id=family_id,
            case_family_sha256=_hash(f"case-family-{family_id}"),
            canonical_content_sha256=canonical_family_content_sha256(
                [item.canonical_content_sha256 for item in authored_items]
            ),
            workflow_revision=_hash(f"workflow-{family_id}"),
            base_specialty="cardiology",
            condition_family=ConditionFamily.ACUTE_CORONARY_SYNDROME,
            acuity=AcuityLevel.ROUTINE,
            authored_items=authored_items,
        )

    def cell(label: str, family_ids: tuple[str, str]) -> SpecialtyCellBinding:
        return SpecialtyCellBinding(
            cell_id=f"cardiology--{track.value}--{label}",
            cell_sha256=_hash(f"{track.value}-{label}-cell"),
            specialty="cardiology",
            track=track,
            expected_family_count=2,
            authored_variants_per_family=11,
            condition_allocations=(
                ConditionAllocation(
                    ConditionFamily.ACUTE_CORONARY_SYNDROME,
                    2,
                ),
            ),
            acuity_allocations=tuple(
                AcuityAllocation(
                    level,
                    2 if level is AcuityLevel.ROUTINE else 0,
                )
                for level in AcuityLevel
            ),
            families=tuple(family(family_id) for family_id in family_ids),
        )

    return SpecialtyCellInventory(
        allocator_archetype_id="noharm",
        specialty="cardiology",
        track=track,
        spec_sha256=_hash("specialty-spec"),
        plan_sha256=_hash("specialty-plan"),
        blueprint_id="reviewed-blueprint",
        blueprint_version="1.0",
        blueprint_schema_version="arisekit.benchmark-blueprint.v1",
        blueprint_sha256=_hash("reviewed-blueprint"),
        blueprint_authoring_revision=_hash("blueprint-authoring"),
        blueprint_workflow_locked_revision=_hash("blueprint-workflow-lock"),
        export_manifest_sha256=_hash("synthetic-export-manifest"),
        export_bundle_sha256=_hash("synthetic-content"),
        exported_case_family_ids=tuple(
            f"synthetic-{index:02d}" for index in range(1, 5)
        ),
        cells=(
            cell("diagnosis", ("synthetic-01", "synthetic-02")),
            cell("management", ("synthetic-03", "synthetic-04")),
        ),
    )


def _reference_inventory(
    selection: SelectionManifest,
) -> ReferenceSelectionInventory:
    return ReferenceSelectionInventory(
        bundle_sha256=_hash("real-content"),
        source_manifest_sha256=_hash("upstream-source-manifest"),
        source_revision="real-release-v1",
        selection_protocol_sha256=selection.protocol_hash,
        selection_commit_sha256=selection.selection_commit_hash,
        families=tuple(
            (
                lambda items: ContentFamilyBinding(
                    family_id=pair.real_case_family_id,
                    family_content_sha256=canonical_family_content_sha256(
                        [item.content_sha256 for item in items]
                    ),
                    baseline_item_id=pair.real_case_family_id,
                    items=items,
                )
            )(
                tuple(
                    ContentItemBinding(
                        item_id=slot.real_variant_id,
                        content_sha256=canonical_item_content_sha256(
                            f"reference-presentation:{slot.real_variant_id}"
                        ),
                    )
                    for slot in pair.variant_slots
                )
            )
            for pair in selection.pairs
        ),
    )


def _program(
    model_count: int = 4,
    *,
    track: BenchmarkTrack = BenchmarkTrack.REPRESENTATIVE,
) -> SyntheticBenchmarkProgram:
    valid_count = model_count if model_count in {3, 4} else 3
    source_binding = _source_binding(valid_count, track=track)
    comparison = SyntheticComparison(
        comparison_id="noharm-cardiology",
        archetype_id=ArchetypeId.NOHARM,
        specialty_id="cardiology",
        reference=ReferenceBundleBinding(
            access_class=ReferenceAccessClass.PUBLIC,
            bundle_hash=_hash("real-content"),
            manifest_hash=_hash("real-manifest"),
            source_revision="real-release-v1",
            authority=ReferenceAuthority.UPSTREAM_RELEASE,
            authority_digest=_hash("upstream-authority"),
        ),
        synthetic=SyntheticBundleBinding(
            bundle_hash=_hash("synthetic-content"),
            manifest_hash=source_binding.cell_inventory_sha256,
            generation_lineage_hash=_hash("lineage"),
            clinical_review_hash=source_binding.clinical_lock_sha256,
            rights_review_hash=source_binding.authorization_set_sha256,
            generator=_route("generator", "generator-family"),
        ),
        endpoint_id="severity-weighted-f1-level",
        margin=ParityMargin(MarginUnit.ABSOLUTE_SCORE, 0.03),
        decision_rule_hash=_rule().digest,
        track=track,
        source_plan_binding=source_binding,
    )
    return SyntheticBenchmarkProgram(
        program_id="parity-program",
        registry=builtin_archetype_registry(),
        comparisons=(comparison,),
        solver_panel=tuple(
            _route(f"model-{index}", f"family-{index}") for index in range(valid_count)
        ),
        judge_panel=(_route("judge", "judge-family"),),
        program_review_hash=_hash("program-review"),
    )


def _program_bound_to_inventories(
    synthetic_inventory: SpecialtyCellInventory,
    reference_inventory: ReferenceSelectionInventory,
) -> SyntheticBenchmarkProgram:
    program = _program(track=synthetic_inventory.track)
    comparison = program.comparisons[0]
    source_binding = replace(
        comparison.source_plan_binding,
        cell_inventory_sha256=synthetic_inventory.inventory_sha256,
    )
    rebound_comparison = replace(
        comparison,
        reference=replace(
            comparison.reference,
            manifest_hash=reference_inventory.inventory_sha256,
        ),
        synthetic=replace(
            comparison.synthetic,
            manifest_hash=synthetic_inventory.inventory_sha256,
        ),
        source_plan_binding=source_binding,
    )
    return replace(program, comparisons=(rebound_comparison,))


def _bind_study_to_program(
    study: SyntheticParityInput,
    program: SyntheticBenchmarkProgram,
) -> SyntheticParityInput:
    evaluation_contract_hash = program.evaluation_contract_digest(study.comparison_id)
    arms = tuple(
        replace(arm, evaluation_contract_hash=evaluation_contract_hash)
        for arm in study.arms
    )
    return replace(
        study,
        program_hash=program.digest,
        evaluation_contract_hash=evaluation_contract_hash,
        arms=arms,
        run_evidence=_run_evidence(
            arms=arms,
            program=program,
            selection=study.selection,
            trials=study.trials,
            observations=study.observations,
        ),
    )


def _run_evidence(
    *,
    arms: tuple[BenchmarkArm, ...],
    program: SyntheticBenchmarkProgram,
    selection: SelectionManifest,
    trials: int,
    observations: tuple[EndpointObservation, ...],
) -> tuple[SolverRunEvidence, ...]:
    expected_response_count = (
        sum(len(pair.variant_slots) for pair in selection.pairs) * trials
    )
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
                trials=trials,
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


def _study(
    *,
    model_count: int = 4,
    synthetic_value=None,
    observations_transform=None,
    selection: SelectionManifest | None = None,
    track: BenchmarkTrack = BenchmarkTrack.REPRESENTATIVE,
) -> SyntheticParityInput:
    selection = selection or _selection(track=track)
    program = _program(model_count, track=track)
    comparison = program.comparisons[0]
    evaluation_contract_hash = program.evaluation_contract_digest(
        comparison.comparison_id
    )
    models = tuple(
        ModelIdentity(model_id=f"model-{index}", model_family=f"family-{index}")
        for index in range(model_count)
    )
    arms = (
        BenchmarkArm(
            role=ArmRole.REAL,
            arm_id="released-reference",
            benchmark_id="real-benchmark",
            benchmark_version="1.0",
            content_hash=_hash("real-content"),
            evaluation_contract_hash=evaluation_contract_hash,
            selection_protocol_hash=selection.protocol_hash,
            selection_manifest_hash=selection.real_selection_hash,
            source_revision="real-release-v1",
        ),
        BenchmarkArm(
            role=ArmRole.SYNTHETIC,
            arm_id="generated-candidate",
            benchmark_id="synthetic-benchmark",
            benchmark_version="candidate-1",
            content_hash=_hash("synthetic-content"),
            evaluation_contract_hash=evaluation_contract_hash,
            selection_protocol_hash=selection.protocol_hash,
            selection_manifest_hash=selection.synthetic_selection_hash,
            source_revision="generation-manifest-v1",
        ),
    )
    observations = []
    for pair_index, pair in enumerate(selection.pairs):
        for role in ArmRole:
            case_family_id = pair.case_family_id(role)
            for slot in pair.variant_slots:
                for model_index, model in enumerate(models):
                    real_value = 0.35 + 0.12 * model_index + 0.005 * pair_index
                    value = (
                        real_value
                        if role is ArmRole.REAL
                        else (
                            synthetic_value(
                                pair_index,
                                pair,
                                model_index,
                                model,
                                real_value,
                            )
                            if synthetic_value is not None
                            else real_value + 0.01
                        )
                    )
                    for trial in (1, 2):
                        observations.append(
                            EndpointObservation(
                                arm_role=role,
                                specialty=pair.specialty,
                                sub_benchmark=pair.sub_benchmark,
                                model_id=model.model_id,
                                model_family=model.model_family,
                                case_family_id=case_family_id,
                                variant_slot_id=slot.slot_id,
                                variant_id=slot.variant_id(role),
                                trial=trial,
                                endpoint="severity-weighted-f1-level",
                                value=value + (trial - 1) * 0.002,
                            )
                        )
    if observations_transform is not None:
        observations = observations_transform(observations)
    return SyntheticParityInput(
        study_id="parity-study-001",
        program_hash=program.digest,
        comparison_id=comparison.comparison_id,
        registry_hash=program.registry_digest,
        archetype_hash=program.registry.get(ArchetypeId.NOHARM).digest,
        evaluation_contract_hash=evaluation_contract_hash,
        decision_rule_hash=_rule().digest,
        benchmark_archetype="noharm",
        specialty="cardiology",
        track=track,
        endpoint="severity-weighted-f1-level",
        trials=2,
        arms=arms,
        model_panel=models,
        run_evidence=_run_evidence(
            arms=arms,
            program=program,
            selection=selection,
            trials=2,
            observations=tuple(observations),
        ),
        selection=selection,
        observations=tuple(observations),
        source_results_hash=_hash("raw-results"),
        extraction_code_hash=_hash("extraction-code"),
    )


def _rule(**overrides) -> ParityDecisionRule:
    values = {
        "per_model_delta_margin": 0.03,
        "absolute_difficulty_shift_margin": 0.03,
        "minimum_rank_agreement": 0.9,
        "minimum_discrimination_spread_ratio": 0.8,
        "maximum_discrimination_spread_ratio": 1.2,
        "confidence_level": 0.9,
        "bootstrap_draws": 250,
        "bootstrap_seed": 17,
        "minimum_case_family_pairs_per_scope": 2,
    }
    values.update(overrides)
    return ParityDecisionRule(**values)


def test_equivalent_study_reports_model_and_specialty_endpoints():
    study = _study()

    report = analyze_synthetic_parity(
        study,
        _rule(),
        program=_program(),
        analysis_code_hash=_hash("analysis-code"),
    )

    assert report.verdict is ParityVerdict.EQUIVALENT
    assert report.overall.verdict is ParityVerdict.EQUIVALENT
    assert len(report.overall.model_results) == 4
    assert all(
        result.delta.estimate == pytest.approx(0.01)
        for result in report.overall.model_results
    )
    assert report.overall.absolute_difficulty_shift.estimate == pytest.approx(0.01)
    assert report.overall.rank_order_agreement.estimate == pytest.approx(1.0)
    assert report.overall.discrimination_spread_ratio.estimate == pytest.approx(1.0)
    assert {result.specialty for result in report.specialty_results} == {"cardiology"}
    assert {
        (result.specialty, result.sub_benchmark)
        for result in report.sub_benchmark_results
    } == {
        ("cardiology", "diagnosis"),
        ("cardiology", "management"),
    }


def test_analysis_is_deterministic_under_input_order_changes():
    first = _study()
    reversed_study = _study(
        observations_transform=lambda observations: list(reversed(observations))
    )

    first_report = analyze_synthetic_parity(
        first,
        _rule(),
        program=_program(),
        analysis_code_hash=_hash("analysis-code"),
    )
    second_report = analyze_synthetic_parity(
        reversed_study,
        _rule(),
        program=_program(),
        analysis_code_hash=_hash("analysis-code"),
    )

    assert first.digest == reversed_study.digest
    assert first_report.digest == second_report.digest
    assert (
        first_report.overall.bootstrap_draws_hash
        == second_report.overall.bootstrap_draws_hash
    )


def test_rank_reversal_is_non_equivalent_and_localized_to_subgroups():
    def reversed_models(pair_index, pair, model_index, model, real_value):
        if pair.specialty == "cardiology" and pair.sub_benchmark == "diagnosis":
            return 0.35 + 0.12 * (3 - model_index) + 0.005 * pair_index
        return real_value + 0.01

    report = analyze_synthetic_parity(
        _study(synthetic_value=reversed_models),
        _rule(),
        program=_program(),
        analysis_code_hash=_hash("analysis-code"),
    )

    affected = next(
        result
        for result in report.sub_benchmark_results
        if result.specialty == "cardiology" and result.sub_benchmark == "diagnosis"
    )
    unaffected = next(
        result
        for result in report.sub_benchmark_results
        if result.specialty == "cardiology" and result.sub_benchmark == "management"
    )
    assert affected.verdict is ParityVerdict.NON_EQUIVALENT
    assert affected.rank_order_agreement.estimate == pytest.approx(-1.0)
    assert unaffected.verdict is ParityVerdict.EQUIVALENT
    assert report.verdict is report.overall.verdict
    assert report.verdict_scope == "overall-primary-diagnostics-nonterminal"


def test_overlapping_equivalence_boundaries_are_inconclusive():
    def alternating_shift(pair_index, pair, model_index, model, real_value):
        return real_value + (0.2 if pair_index % 2 else -0.2)

    report = analyze_synthetic_parity(
        _study(synthetic_value=alternating_shift),
        _rule(),
        program=_program(),
        analysis_code_hash=_hash("analysis-code"),
    )

    assert report.verdict is ParityVerdict.INCONCLUSIVE
    assert report.overall.model_results[0].delta.verdict is ParityVerdict.INCONCLUSIVE


def test_spearman_uses_average_ranks_for_ties_without_scipy():
    first = {"a": 1.0, "b": 2.0, "c": 2.0, "d": 4.0}

    assert spearman_rank_agreement(first, first) == pytest.approx(1.0)
    assert spearman_rank_agreement(
        first,
        {"a": 4.0, "b": 2.0, "c": 2.0, "d": 1.0},
    ) == pytest.approx(-1.0)
    with pytest.raises(ValueError, match="all-tied"):
        spearman_rank_agreement(
            {"a": 1.0, "b": 1.0, "c": 1.0},
            {"a": 1.0, "b": 2.0, "c": 3.0},
        )


@pytest.mark.parametrize("model_count", [2, 5])
def test_study_requires_exactly_three_or_four_models(model_count):
    study = _study(model_count=3)
    panel = tuple(
        ModelIdentity(
            model_id=f"invalid-model-{index}",
            model_family=f"invalid-family-{index}",
        )
        for index in range(model_count)
    )
    with pytest.raises(ValueError, match="exactly 3 or 4"):
        replace(study, model_panel=panel)


def test_study_requires_distinct_model_families():
    study = _study()
    panel = list(study.model_panel)
    panel[1] = replace(panel[1], model_family=panel[0].model_family)

    with pytest.raises(ValueError, match="distinct model families"):
        replace(study, model_panel=tuple(panel))


def test_missing_duplicate_and_unpaired_observations_fail_closed():
    with pytest.raises(ValueError, match="exact logical-slot"):
        _study(observations_transform=lambda observations: observations[:-1])

    with pytest.raises(ValueError, match="duplicate endpoint observation"):
        _study(
            observations_transform=lambda observations: [
                *observations,
                observations[0],
            ]
        )

    def unpair(observations):
        observations[0] = replace(observations[0], case_family_id="not-in-selection")
        return observations

    with pytest.raises(ValueError, match="not in the frozen paired selection"):
        _study(observations_transform=unpair)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_nonfinite_and_boolean_endpoint_values_are_rejected(value):
    with pytest.raises(ValueError, match="must be a finite number"):
        EndpointObservation(
            arm_role=ArmRole.REAL,
            specialty="cardiology",
            sub_benchmark="diagnosis",
            model_id="model-0",
            model_family="family-0",
            case_family_id="real-01",
            variant_slot_id="baseline",
            variant_id="real-01-variant-0",
            trial=1,
            endpoint="severity-weighted-f1-level",
            value=value,
        )


@pytest.mark.parametrize(
    "selection",
    [
        lambda: _selection(basis=SelectionBasis.EVALUATED_OUTCOMES),
        lambda: _selection(uses_evaluated_outcomes=True),
        lambda: _selection(outcome_blind=False),
        lambda: _selection(committed_before_evaluation=False),
    ],
)
def test_selection_leakage_and_post_evaluation_selection_are_rejected(selection):
    with pytest.raises(ValueError, match="selection"):
        selection()


def test_selection_cannot_name_the_evaluated_endpoint():
    selection = _selection(selection_fields=("specialty", "Severity Weighted F1 Level"))

    with pytest.raises(ValueError, match="evaluated endpoint"):
        _study(selection=selection)


def test_arm_panel_and_selection_contracts_must_match_exactly():
    study = _study()
    synthetic = next(arm for arm in study.arms if arm.role is ArmRole.SYNTHETIC)
    mismatched = replace(
        synthetic, evaluation_contract_hash=_hash("different-evaluation")
    )

    with pytest.raises(ValueError, match="exact evaluation contract"):
        replace(
            study,
            arms=tuple(
                mismatched if arm.role is ArmRole.SYNTHETIC else arm
                for arm in study.arms
            ),
        )


def test_input_rule_and_report_round_trip_with_tamper_detection():
    study = _study()
    rule = _rule()
    report = analyze_synthetic_parity(
        study,
        rule,
        program=_program(),
        analysis_code_hash=_hash("analysis-code"),
    )

    restored_study = SyntheticParityInput.from_json(study.canonical_json())
    restored_report = SyntheticParityReport.from_json(report.canonical_json())
    assert restored_study.digest == study.digest
    assert restored_report.digest == report.digest

    tampered_input = study.to_dict()
    tampered_input["observations"][0]["value"] += 0.2
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        SyntheticParityInput.from_dict(tampered_input)

    tampered_rule = rule.to_dict()
    tampered_rule["per_model_delta_margin"] = 0.5
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        ParityDecisionRule.from_dict(tampered_rule)

    tampered_report = report.to_dict()
    tampered_report["overall"]["verdict"] = "non-equivalent"
    payload = {
        key: value for key, value in tampered_report.items() if key != "artifact_hash"
    }
    tampered_report["artifact_hash"] = _canonical_hash(payload)
    with pytest.raises(ValueError, match="verdict was not derived"):
        SyntheticParityReport.from_dict(tampered_report)


def test_solver_run_evidence_rejects_stale_manifest_and_provider_identity() -> None:
    evidence = _study().run_evidence[0]

    with pytest.raises(ValueError, match="manifest digest is stale"):
        replace(evidence, run_manifest_digest=_hash("stale-manifest"))
    with pytest.raises(ValueError, match="predeclared expected identity"):
        replace(evidence, observed_provider_model_identity="unexpected-model")

    missing_identity = evidence.to_dict()
    del missing_identity["expected_provider_model_identity"]
    with pytest.raises(ValueError, match="fields are invalid"):
        SolverRunEvidence.from_dict(missing_identity)

    model_config = dict(evidence.run_manifest.model_config)
    del model_config[RUN_MANIFEST_EXPECTED_PROVIDER_IDENTITY_KEY]
    uncommitted_manifest = replace(
        evidence.run_manifest,
        model_config=model_config,
    )
    with pytest.raises(ValueError, match="not predeclared"):
        replace(
            evidence,
            run_manifest=uncommitted_manifest,
            run_manifest_digest=uncommitted_manifest.digest,
        )


def test_parity_input_requires_complete_arm_by_solver_run_evidence() -> None:
    study = _study()

    with pytest.raises(ValueError, match="2-arm-by-model-panel"):
        replace(study, run_evidence=study.run_evidence[:-1])

    first = study.run_evidence[0]
    wrong_role = ArmRole.SYNTHETIC if first.arm_role is ArmRole.REAL else ArmRole.REAL
    wrong_role_receipt = replace(first.adapter_receipt, arm_role=wrong_role)
    with pytest.raises(ValueError, match="2-arm-by-model-panel"):
        replace(
            study,
            run_evidence=(
                replace(
                    first,
                    arm_role=wrong_role,
                    adapter_receipt=wrong_role_receipt,
                    adapter_receipt_file_sha256=hashlib.sha256(
                        wrong_role_receipt.canonical_json().encode("utf-8")
                    ).hexdigest(),
                ),
            )
            + study.run_evidence[1:],
        )


def test_parity_input_rejects_run_evidence_response_count_mismatch() -> None:
    study = _study()
    first = study.run_evidence[0]
    wrong_count = first.expected_response_count + 1
    wrong_count_receipt = replace(
        first.adapter_receipt,
        observed_response_count=wrong_count,
    )
    mismatched = replace(
        first,
        expected_response_count=wrong_count,
        observed_response_count=wrong_count,
        adapter_receipt=wrong_count_receipt,
        adapter_receipt_file_sha256=hashlib.sha256(
            wrong_count_receipt.canonical_json().encode("utf-8")
        ).hexdigest(),
    )

    with pytest.raises(ValueError, match="selected arm workload"):
        replace(
            study,
            run_evidence=(mismatched,) + study.run_evidence[1:],
        )


def test_program_validation_rejects_self_consistent_relabelled_solver_route() -> None:
    study = _study()
    relabelled = []
    for evidence in study.run_evidence:
        if evidence.model_route.route_id != "model-0":
            relabelled.append(evidence)
            continue
        route = replace(
            evidence.model_route,
            provider="substituted-provider",
            model="substituted-model",
            snapshot="substituted-snapshot",
            runtime_config_hash=_hash("substituted-runtime"),
        )
        provider_identity = f"{route.provider}:{route.model}:{route.snapshot}"
        model_config = dict(evidence.run_manifest.model_config)
        model_config.update(
            {
                RUN_MANIFEST_ROUTE_SNAPSHOT_KEY: route.snapshot,
                RUN_MANIFEST_ROUTE_FAMILY_KEY: route.family,
                RUN_MANIFEST_RUNTIME_CONFIG_HASH_KEY: route.runtime_config_hash,
                RUN_MANIFEST_EXPECTED_PROVIDER_IDENTITY_KEY: provider_identity,
            }
        )
        manifest = replace(
            evidence.run_manifest,
            provider=route.provider,
            model=route.model,
            model_config=model_config,
        )
        relabelled_receipt = replace(
            evidence.adapter_receipt,
            run_manifest_digest=manifest.digest,
            observed_provider_model_identity=provider_identity,
        )
        relabelled.append(
            replace(
                evidence,
                model_route=route,
                run_manifest=manifest,
                run_manifest_digest=manifest.digest,
                run_manifest_file_sha256=hashlib.sha256(
                    manifest.canonical_json().encode("utf-8")
                ).hexdigest(),
                expected_provider_model_identity=provider_identity,
                observed_provider_model_identity=provider_identity,
                adapter_receipt=relabelled_receipt,
                adapter_receipt_file_sha256=hashlib.sha256(
                    relabelled_receipt.canonical_json().encode("utf-8")
                ).hexdigest(),
            )
        )
    substituted = replace(study, run_evidence=tuple(relabelled))

    with pytest.raises(ValueError, match="exact program provider/model/snapshot"):
        substituted.validate_against_program(_program())


@pytest.mark.parametrize("binding", ["adapter-code", "provider-identity"])
def test_cross_arm_run_evidence_requires_identical_runtime_bindings(
    binding: str,
) -> None:
    study = _study()
    changed = []
    for evidence in study.run_evidence:
        if (
            evidence.arm_role is not ArmRole.SYNTHETIC
            or evidence.model_route.route_id != "model-0"
        ):
            changed.append(evidence)
            continue
        model_config = dict(evidence.run_manifest.model_config)
        receipt_changes: dict[str, str] = {}
        evidence_changes: dict[str, str] = {}
        if binding == "adapter-code":
            adapter_code_sha256 = _hash("substituted-adapter-code")
            model_config[RUN_MANIFEST_ADAPTER_CODE_HASH_KEY] = adapter_code_sha256
            receipt_changes["adapter_code_sha256"] = adapter_code_sha256
        else:
            provider_identity = "substituted-provider-identity"
            model_config[RUN_MANIFEST_EXPECTED_PROVIDER_IDENTITY_KEY] = (
                provider_identity
            )
            receipt_changes["observed_provider_model_identity"] = provider_identity
            evidence_changes.update(
                {
                    "expected_provider_model_identity": provider_identity,
                    "observed_provider_model_identity": provider_identity,
                }
            )
        manifest = replace(evidence.run_manifest, model_config=model_config)
        receipt = replace(
            evidence.adapter_receipt,
            run_manifest_digest=manifest.digest,
            **receipt_changes,
        )
        changed.append(
            replace(
                evidence,
                run_manifest=manifest,
                run_manifest_digest=manifest.digest,
                run_manifest_file_sha256=hashlib.sha256(
                    manifest.canonical_json().encode("utf-8")
                ).hexdigest(),
                adapter_receipt=receipt,
                adapter_receipt_file_sha256=hashlib.sha256(
                    receipt.canonical_json().encode("utf-8")
                ).hexdigest(),
                **evidence_changes,
            )
        )

    with pytest.raises(ValueError, match="adapter identity/code.*provider model"):
        replace(study, run_evidence=tuple(changed))


def test_observation_relabelling_cannot_escape_adapter_receipt_binding() -> None:
    study = _study()
    relabelled = []
    for observation in study.observations:
        if observation.model_id == "model-0":
            relabelled.append(
                replace(
                    observation,
                    model_id="model-1",
                    model_family="family-1",
                )
            )
        elif observation.model_id == "model-1":
            relabelled.append(
                replace(
                    observation,
                    model_id="model-0",
                    model_family="family-0",
                )
            )
        else:
            relabelled.append(observation)

    with pytest.raises(ValueError, match="adapter receipt observation subset"):
        replace(study, observations=tuple(relabelled))


def test_report_replay_rejects_self_consistent_but_forged_estimates():
    study = _study()
    program = _program()
    report = analyze_synthetic_parity(
        study,
        _rule(),
        program=program,
        analysis_code_hash=_hash("analysis-code"),
    )
    original_measure = report.overall.absolute_difficulty_shift
    assert original_measure.estimate is not None
    assert original_measure.confidence_interval is not None
    forged_shift = 0.01
    forged = replace(
        report,
        overall=replace(
            report.overall,
            absolute_difficulty_shift=replace(
                original_measure,
                estimate=original_measure.estimate + forged_shift,
                confidence_interval=replace(
                    original_measure.confidence_interval,
                    lower=(original_measure.confidence_interval.lower + forged_shift),
                    upper=(original_measure.confidence_interval.upper + forged_shift),
                ),
            ),
        ),
    )

    with pytest.raises(ValueError, match="not exactly derived"):
        replay_synthetic_parity_report(study, forged, program=program)

    assert replay_synthetic_parity_report(study, report, program=program) == report


def test_v3_selection_pair_loader_requires_explicit_plan_cell_field():
    payload = _selection().pairs[0].to_dict()
    payload.pop("plan_cell_id")

    with pytest.raises(ValueError, match="missing plan_cell_id"):
        SelectionPair.from_dict(payload)


def test_report_binds_input_rule_code_and_source_results():
    study = _study()
    rule = _rule()
    code_hash = _hash("analysis-code")

    report = analyze_synthetic_parity(
        study,
        rule,
        program=_program(),
        analysis_code_hash=code_hash,
    )

    assert report.input_hash == study.digest
    assert report.source_results_hash == study.source_results_hash
    assert report.decision_rule_hash == rule.digest
    assert report.analysis_code_hash == code_hash
    assert report.decision_rule == rule
    assert report.artifact_hash_kind == "self-checksum-requires-external-byte-pin"


def test_analysis_requires_the_exact_program_comparison_and_solver_routes():
    study = _study()
    substituted = replace(_program(), program_review_hash=_hash("changed-review"))

    with pytest.raises(ValueError, match="program hash"):
        analyze_synthetic_parity(
            study,
            _rule(),
            program=substituted,
            analysis_code_hash=_hash("analysis-code"),
        )

    wrong_rule = _rule(per_model_delta_margin=0.02)
    with pytest.raises(ValueError, match="program-bound rule hash"):
        analyze_synthetic_parity(
            study,
            wrong_rule,
            program=_program(),
            analysis_code_hash=_hash("analysis-code"),
        )


def test_registered_profile_distance_fails_closed_until_estimand_is_implemented():
    base_program = _program()
    comparison = replace(
        base_program.comparisons[0],
        endpoint_id="centered-model-profile",
        margin=ParityMargin(MarginUnit.PROFILE_DISTANCE, 0.03),
    )
    program = replace(base_program, comparisons=(comparison,))
    contract_hash = program.evaluation_contract_digest(comparison.comparison_id)
    base_study = _study()
    arms = tuple(
        replace(arm, evaluation_contract_hash=contract_hash) for arm in base_study.arms
    )
    profile_observations = tuple(
        replace(observation, endpoint="centered-model-profile")
        for observation in base_study.observations
    )
    study = replace(
        base_study,
        program_hash=program.digest,
        evaluation_contract_hash=contract_hash,
        endpoint="centered-model-profile",
        arms=arms,
        run_evidence=_run_evidence(
            arms=arms,
            program=program,
            selection=base_study.selection,
            trials=base_study.trials,
            observations=profile_observations,
        ),
        observations=profile_observations,
    )

    with pytest.raises(ValueError, match="not implemented"):
        analyze_synthetic_parity(
            study,
            _rule(),
            program=program,
            analysis_code_hash=_hash("analysis-code"),
        )


def test_selection_pairs_cannot_mix_representative_and_stress_tracks():
    selection = _selection()
    mixed = replace(
        selection,
        pairs=(
            *selection.pairs[:-1],
            replace(selection.pairs[-1], track=BenchmarkTrack.STRESS),
        ),
    )

    with pytest.raises(ValueError, match="exact bound comparison track"):
        _study(selection=mixed)


def test_stress_report_is_diagnostic_only_and_cannot_set_terminal_verdict():
    def stress_failure(pair_index, pair, model_index, model, real_value):
        return real_value + 0.2

    stress_report = analyze_synthetic_parity(
        _study(
            track=BenchmarkTrack.STRESS,
            synthetic_value=stress_failure,
        ),
        _rule(),
        program=_program(track=BenchmarkTrack.STRESS),
        analysis_code_hash=_hash("analysis-code"),
    )
    representative_report = analyze_synthetic_parity(
        _study(),
        _rule(),
        program=_program(),
        analysis_code_hash=_hash("analysis-code"),
    )

    assert stress_report.track is BenchmarkTrack.STRESS
    assert stress_report.comparison_role == "diagnostic-only"
    assert stress_report.verdict_scope == "diagnostic-only-no-terminal-verdict"
    assert stress_report.terminal_verdict is None
    assert stress_report.verdict is ParityVerdict.NON_EQUIVALENT
    assert representative_report.comparison_role == "primary-terminal"
    assert representative_report.terminal_verdict is ParityVerdict.EQUIVALENT
    assert representative_report.verdict is ParityVerdict.EQUIVALENT
    restored = SyntheticParityReport.from_json(stress_report.canonical_json())
    assert restored.digest == stress_report.digest
    assert restored.terminal_verdict is None


def test_all_families_must_use_one_exact_variant_slot_pattern():
    selection = _selection()
    changed_pair = replace(
        selection.pairs[-1],
        variant_slots=selection.pairs[-1].variant_slots[:-1],
    )
    mixed = replace(
        selection,
        pairs=(*selection.pairs[:-1], changed_pair),
    )

    with pytest.raises(ValueError, match="same variant-slot"):
        _study(selection=mixed)


def test_noharm_requires_one_baseline_and_all_observations_name_exact_slots():
    selection = _selection()
    invalid = replace(
        selection,
        pairs=tuple(
            replace(
                pair,
                variant_slots=tuple(
                    replace(slot, kind=VariantSlotKind.PERTURBATION)
                    for slot in pair.variant_slots
                ),
            )
            for pair in selection.pairs
        ),
    )
    study = _study(selection=invalid)

    with pytest.raises(ValueError, match="exactly one baseline"):
        analyze_synthetic_parity(
            study,
            _rule(),
            program=_program(),
            analysis_code_hash=_hash("analysis-code"),
        )

    def wrong_variant(observations):
        observations[0] = replace(observations[0], variant_id="wrong-variant")
        return observations

    with pytest.raises(ValueError, match="role-specific frozen logical slot"):
        _study(observations_transform=wrong_variant)


@pytest.mark.parametrize("selected_count", [2, 11])
def test_noharm_parity_requires_the_canonical_k5_slot_manifest(selected_count):
    selection = _selection()
    resized = replace(
        selection,
        pairs=tuple(
            replace(
                pair,
                variant_slots=tuple(
                    VariantSlot(
                        slot_id=("baseline" if index == 0 else f"perturbation-{index}"),
                        kind=(
                            VariantSlotKind.BASELINE
                            if index == 0
                            else VariantSlotKind.PERTURBATION
                        ),
                        real_variant_id=f"{pair.real_case_family_id}-resized-{index}",
                        synthetic_variant_id=(
                            f"{pair.synthetic_case_family_id}-resized-{index}"
                        ),
                    )
                    for index in range(selected_count)
                ),
            )
            for pair in selection.pairs
        ),
    )
    study = _study(selection=resized)

    with pytest.raises(ValueError, match="canonical evaluated topology"):
        analyze_synthetic_parity(
            study,
            _rule(),
            program=_program(),
            analysis_code_hash=_hash("analysis-code"),
        )


def test_zero_real_spread_is_explicitly_non_estimable_and_inconclusive():
    def all_tied(observations):
        return [
            replace(
                observation,
                value=(0.5 if observation.arm_role is ArmRole.REAL else 0.51),
            )
            for observation in observations
        ]

    rule = _rule(minimum_rank_agreement=-1.0)
    program = replace(
        _program(),
        comparisons=(
            replace(
                _program().comparisons[0],
                decision_rule_hash=rule.digest,
            ),
        ),
    )
    study = _study(observations_transform=all_tied)
    contract_hash = program.evaluation_contract_digest(study.comparison_id)
    arms = tuple(
        replace(
            arm,
            evaluation_contract_hash=contract_hash,
        )
        for arm in study.arms
    )
    study = replace(
        study,
        program_hash=program.digest,
        evaluation_contract_hash=contract_hash,
        decision_rule_hash=rule.digest,
        arms=arms,
        run_evidence=_run_evidence(
            arms=arms,
            program=program,
            selection=study.selection,
            trials=study.trials,
            observations=study.observations,
        ),
    )
    report = analyze_synthetic_parity(
        study,
        rule,
        program=program,
        analysis_code_hash=_hash("analysis-code"),
    )

    spread = report.overall.discrimination_spread_ratio
    assert spread.estimate is None
    assert spread.confidence_interval is None
    assert spread.not_estimable_reason == (
        "real-arm-zero-model-spread-at-point-estimate"
    )
    assert spread.verdict is ParityVerdict.INCONCLUSIVE
    assert report.verdict is ParityVerdict.INCONCLUSIVE
    assert report.overall.model_results[0].delta.estimate == pytest.approx(0.01)


def test_source_plan_family_count_applies_before_any_scope_analysis():
    selection = _selection()
    undersized = replace(selection, pairs=selection.pairs[:-1])
    study = _study(selection=undersized)

    with pytest.raises(ValueError, match="source-plan binding"):
        analyze_synthetic_parity(
            study,
            _rule(),
            program=_program(),
            analysis_code_hash=_hash("analysis-code"),
        )


def test_source_plan_subset_requires_explicit_optimization_mode():
    selection = _selection()
    subset = replace(selection, pairs=selection.pairs[:2])
    study = _study(selection=subset)
    program = _program()

    with pytest.raises(ValueError, match="case-family count"):
        study.validate_against_program(program)

    study.validate_against_program(
        program,
        allow_source_plan_subset=True,
    )
    report = analyze_synthetic_parity(
        study,
        _rule(),
        program=program,
        analysis_code_hash=_hash("analysis-code"),
        allow_source_plan_subset=True,
    )
    assert (
        replay_synthetic_parity_report(
            study,
            report,
            program=program,
            allow_source_plan_subset=True,
        )
        == report
    )


def test_source_plan_requires_exact_per_cell_family_distribution():
    selection = _selection()
    wrong_distribution = replace(
        selection,
        pairs=tuple(
            replace(
                pair,
                plan_cell_id=(
                    "cardiology--representative--management"
                    if pair.pair_id == "pair-02"
                    else pair.plan_cell_id
                ),
            )
            for pair in selection.pairs
        ),
    )
    study = _study(selection=wrong_distribution)

    with pytest.raises(ValueError, match="distribution.*source-plan cell"):
        analyze_synthetic_parity(
            study,
            _rule(),
            program=_program(),
            analysis_code_hash=_hash("analysis-code"),
        )


def test_source_bound_selection_pairs_must_name_exact_plan_cells():
    selection = _selection()
    unbound = replace(
        selection,
        pairs=(
            replace(selection.pairs[0], plan_cell_id=None),
            *selection.pairs[1:],
        ),
    )
    study = _study(selection=unbound)

    with pytest.raises(ValueError, match="must name its exact specialty plan cell"):
        study.validate_against_program(_program())


def test_selection_inventory_validators_accept_exact_bound_membership():
    selection = _inventory_selection()
    synthetic_inventory = _synthetic_inventory()
    reference_inventory = _reference_inventory(selection)
    program = _program_bound_to_inventories(
        synthetic_inventory,
        reference_inventory,
    )
    study = _bind_study_to_program(
        _study(selection=selection),
        program,
    )

    source_binding = program.comparisons[0].source_plan_binding
    assert source_binding is not None
    source_binding.validate_inventory(synthetic_inventory)
    study.validate_against_program(program)
    validate_synthetic_selection_inventory(study, synthetic_inventory)
    validate_reference_selection_inventory(
        study,
        reference_inventory,
        program=program,
    )
    validate_cross_arm_content_isolation(
        reference_inventory,
        synthetic_inventory,
    )


def test_selection_inventory_validators_accept_only_program_bound_subsets():
    full_selection = _inventory_selection()
    synthetic_inventory = _synthetic_inventory()
    reference_inventory = _reference_inventory(full_selection)
    program = _program_bound_to_inventories(
        synthetic_inventory,
        reference_inventory,
    )
    subset_selection = replace(
        full_selection,
        pairs=full_selection.pairs[:2],
    )
    study = _bind_study_to_program(
        _study(selection=subset_selection),
        program,
    )

    validate_synthetic_selection_inventory(
        study,
        synthetic_inventory,
        program=program,
        require_exact_families=False,
    )
    validate_reference_selection_inventory(
        study,
        reference_inventory,
        program=program,
        require_exact_families=False,
    )

    with pytest.raises(ValueError, match="do not exactly match"):
        validate_synthetic_selection_inventory(study, synthetic_inventory)
    with pytest.raises(ValueError, match="do not exactly match"):
        validate_reference_selection_inventory(
            study,
            reference_inventory,
            program=program,
        )
    with pytest.raises(ValueError, match="requires the exact program-bound"):
        validate_synthetic_selection_inventory(
            study,
            synthetic_inventory,
            require_exact_families=False,
        )


def test_cross_arm_content_isolation_rejects_relabelled_item_copy():
    selection = _inventory_selection()
    reference_inventory = _reference_inventory(selection)
    synthetic_inventory = _synthetic_inventory()
    copied_hash = reference_inventory.families[0].items[0].content_sha256
    first_cell, *remaining_cells = synthetic_inventory.cells
    first_family, *remaining_families = first_cell.families
    copied_items = (
        replace(
            first_family.authored_items[0],
            canonical_content_sha256=copied_hash,
        ),
        *first_family.authored_items[1:],
    )
    copied_family = replace(
        first_family,
        canonical_content_sha256=canonical_family_content_sha256(
            [item.canonical_content_sha256 for item in copied_items]
        ),
        authored_items=copied_items,
    )
    copied_cell = replace(
        first_cell,
        families=(copied_family, *remaining_families),
    )
    relabelled_copy = replace(
        synthetic_inventory,
        cells=(copied_cell, *remaining_cells),
    )

    assert (
        reference_inventory.families[0].items[0].item_id
        != copied_family.authored_items[0].item_id
    )
    with pytest.raises(
        ValueError,
        match="overlap on canonical item content hashes",
    ):
        validate_cross_arm_content_isolation(
            reference_inventory,
            relabelled_copy,
        )


def test_cross_arm_content_isolation_rejects_relabelled_family_copy():
    synthetic_inventory = _synthetic_inventory()
    synthetic_family = synthetic_inventory.cells[0].families[0]
    reference_items = tuple(
        ContentItemBinding(
            item_id=f"reference-relabel-{index}",
            content_sha256=item.canonical_content_sha256,
        )
        for index, item in enumerate(synthetic_family.authored_items)
    )
    reference_inventory = ReferenceSelectionInventory(
        bundle_sha256=_hash("reference-relabel-bundle"),
        source_manifest_sha256=_hash("reference-relabel-manifest"),
        source_revision="reference-relabel-v1",
        selection_protocol_sha256=_hash("reference-relabel-protocol"),
        selection_commit_sha256=_hash("reference-relabel-commit"),
        families=(
            ContentFamilyBinding(
                family_id="reference-relabel-family",
                family_content_sha256=canonical_family_content_sha256(
                    [item.content_sha256 for item in reference_items]
                ),
                baseline_item_id=reference_items[0].item_id,
                items=reference_items,
            ),
        ),
    )

    assert reference_inventory.families[0].family_id != synthetic_family.family_id
    with pytest.raises(
        ValueError,
        match="overlap on canonical family content hashes",
    ):
        validate_cross_arm_content_isolation(
            reference_inventory,
            synthetic_inventory,
        )


def test_cross_arm_content_isolation_rejects_hashing_contract_mismatch():
    reference_inventory = _reference_inventory(_inventory_selection())
    object.__setattr__(
        reference_inventory,
        "content_hashing_contract_sha256",
        _hash("different-content-hashing-contract"),
    )

    with pytest.raises(
        ValueError,
        match="use different canonical content hashing contracts",
    ):
        validate_cross_arm_content_isolation(
            reference_inventory,
            _synthetic_inventory(),
        )


def test_synthetic_selection_inventory_rejects_wrong_family_membership():
    selection = _inventory_selection()
    wrong_family = replace(
        selection.pairs[0],
        synthetic_case_family_id="synthetic-outside-inventory",
    )
    study = _study(
        selection=replace(
            selection,
            pairs=(wrong_family, *selection.pairs[1:]),
        )
    )

    with pytest.raises(
        ValueError,
        match="synthetic families do not exactly match the inventory",
    ):
        validate_synthetic_selection_inventory(study, _synthetic_inventory())


def test_synthetic_selection_inventory_rejects_wrong_plan_cell():
    selection = _inventory_selection()
    first, second, third, fourth = selection.pairs
    swapped_cells = replace(
        selection,
        pairs=(
            replace(first, plan_cell_id=third.plan_cell_id),
            second,
            replace(third, plan_cell_id=first.plan_cell_id),
            fourth,
        ),
    )
    study = _study(selection=swapped_cells)

    with pytest.raises(ValueError, match="different inventory plan cell"):
        validate_synthetic_selection_inventory(study, _synthetic_inventory())


def test_synthetic_selection_inventory_rejects_unknown_variant():
    selection = _inventory_selection()
    first = selection.pairs[0]
    changed_slots = (
        first.variant_slots[0],
        replace(
            first.variant_slots[1],
            synthetic_variant_id="synthetic-01-uninventoried",
        ),
        *first.variant_slots[2:],
    )
    study = _study(
        selection=replace(
            selection,
            pairs=(
                replace(first, variant_slots=changed_slots),
                *selection.pairs[1:],
            ),
        )
    )

    with pytest.raises(ValueError, match="variants outside the inventory"):
        validate_synthetic_selection_inventory(study, _synthetic_inventory())


def test_synthetic_selection_inventory_rejects_wrong_baseline_slot():
    selection = _inventory_selection()
    first = selection.pairs[0]
    baseline, perturbation, *remaining = first.variant_slots
    swapped_slots = (
        replace(
            baseline,
            synthetic_variant_id=perturbation.synthetic_variant_id,
        ),
        replace(
            perturbation,
            synthetic_variant_id=baseline.synthetic_variant_id,
        ),
        *remaining,
    )
    study = _study(
        selection=replace(
            selection,
            pairs=(
                replace(first, variant_slots=swapped_slots),
                *selection.pairs[1:],
            ),
        )
    )

    with pytest.raises(ValueError, match="inventoried baseline"):
        validate_synthetic_selection_inventory(study, _synthetic_inventory())


def test_synthetic_selection_inventory_rejects_wrong_bundle():
    study = _study(selection=_inventory_selection())
    wrong_bundle = replace(
        _synthetic_inventory(),
        export_bundle_sha256=_hash("wrong-synthetic-bundle"),
    )

    with pytest.raises(
        ValueError,
        match="synthetic arm does not match the inventory bundle",
    ):
        validate_synthetic_selection_inventory(study, wrong_bundle)


def test_reference_selection_inventory_rejects_wrong_family_membership():
    selection = _inventory_selection()
    reference_inventory = _reference_inventory(selection)
    synthetic_inventory = _synthetic_inventory()
    program = _program_bound_to_inventories(
        synthetic_inventory,
        reference_inventory,
    )
    wrong_family = replace(
        selection.pairs[0],
        real_case_family_id="real-outside-inventory",
    )
    study = _bind_study_to_program(
        _study(
            selection=replace(
                selection,
                pairs=(wrong_family, *selection.pairs[1:]),
            )
        ),
        program,
    )

    with pytest.raises(
        ValueError,
        match="reference families do not exactly match the inventory",
    ):
        validate_reference_selection_inventory(
            study,
            reference_inventory,
            program=program,
        )


def test_reference_selection_inventory_rejects_unknown_variant():
    selection = _inventory_selection()
    reference_inventory = _reference_inventory(selection)
    program = _program_bound_to_inventories(
        _synthetic_inventory(),
        reference_inventory,
    )
    first = selection.pairs[0]
    changed_slots = (
        first.variant_slots[0],
        replace(
            first.variant_slots[1],
            real_variant_id="real-01-uninventoried",
        ),
        *first.variant_slots[2:],
    )
    study = _bind_study_to_program(
        _study(
            selection=replace(
                selection,
                pairs=(
                    replace(first, variant_slots=changed_slots),
                    *selection.pairs[1:],
                ),
            )
        ),
        program,
    )

    with pytest.raises(ValueError, match="variants outside the inventory"):
        validate_reference_selection_inventory(
            study,
            reference_inventory,
            program=program,
        )


def test_reference_selection_inventory_rejects_wrong_baseline_slot():
    selection = _inventory_selection()
    reference_inventory = _reference_inventory(selection)
    program = _program_bound_to_inventories(
        _synthetic_inventory(),
        reference_inventory,
    )
    first = selection.pairs[0]
    baseline, perturbation, *remaining = first.variant_slots
    swapped_slots = (
        replace(
            baseline,
            real_variant_id=perturbation.real_variant_id,
        ),
        replace(
            perturbation,
            real_variant_id=baseline.real_variant_id,
        ),
        *remaining,
    )
    study = _bind_study_to_program(
        _study(
            selection=replace(
                selection,
                pairs=(
                    replace(first, variant_slots=swapped_slots),
                    *selection.pairs[1:],
                ),
            )
        ),
        program,
    )

    with pytest.raises(ValueError, match="inventoried baseline"):
        validate_reference_selection_inventory(
            study,
            reference_inventory,
            program=program,
        )


def test_reference_selection_inventory_rejects_wrong_bundle():
    selection = _inventory_selection()
    wrong_bundle = replace(
        _reference_inventory(selection),
        bundle_sha256=_hash("wrong-reference-bundle"),
    )
    program = _program_bound_to_inventories(
        _synthetic_inventory(),
        wrong_bundle,
    )
    study = _bind_study_to_program(
        _study(selection=selection),
        program,
    )

    with pytest.raises(ValueError, match="does not match the program bundle"):
        validate_reference_selection_inventory(
            study,
            wrong_bundle,
            program=program,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selection_protocol_sha256", _hash("wrong-selection-protocol")),
        ("selection_commit_sha256", _hash("wrong-selection-commit")),
    ],
)
def test_reference_selection_inventory_rejects_wrong_frozen_selection_binding(
    field,
    value,
):
    selection = _inventory_selection()
    wrong_selection_binding = replace(
        _reference_inventory(selection),
        **{field: value},
    )
    program = _program_bound_to_inventories(
        _synthetic_inventory(),
        wrong_selection_binding,
    )
    study = _bind_study_to_program(
        _study(selection=selection),
        program,
    )

    with pytest.raises(ValueError, match="does not match the frozen selection"):
        validate_reference_selection_inventory(
            study,
            wrong_selection_binding,
            program=program,
        )


def test_registered_endpoint_range_applies_to_every_observation():
    study = _study(
        observations_transform=lambda observations: [
            replace(observation, value=999.0) if index == 0 else observation
            for index, observation in enumerate(observations)
        ]
    )

    with pytest.raises(ValueError, match="outside the registered endpoint range"):
        analyze_synthetic_parity(
            study,
            _rule(),
            program=_program(),
            analysis_code_hash=_hash("analysis-code"),
        )


def test_report_rule_bounds_cannot_be_rewritten_with_a_recomputed_checksum():
    report = analyze_synthetic_parity(
        _study(),
        _rule(),
        program=_program(),
        analysis_code_hash=_hash("analysis-code"),
    )
    tampered = report.to_dict()
    tampered_rule = dict(tampered["decision_rule"])
    tampered_rule["per_model_delta_margin"] = 0.5
    rule_payload = {
        key: value for key, value in tampered_rule.items() if key != "artifact_hash"
    }
    tampered_rule["artifact_hash"] = _canonical_hash(rule_payload)
    tampered["decision_rule"] = tampered_rule
    tampered["decision_rule_hash"] = tampered_rule["artifact_hash"]
    outer_payload = {
        key: value for key, value in tampered.items() if key != "artifact_hash"
    }
    tampered["artifact_hash"] = _canonical_hash(outer_payload)

    with pytest.raises(ValueError, match="acceptance bounds"):
        SyntheticParityReport.from_dict(tampered)


def test_public_json_loaders_reject_duplicate_keys():
    study = _study()
    duplicate_input = study.canonical_json().replace(
        '"study_id":"parity-study-001"',
        '"study_id":"other","study_id":"parity-study-001"',
        1,
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        SyntheticParityInput.from_json(duplicate_input)

    report = analyze_synthetic_parity(
        study,
        _rule(),
        program=_program(),
        analysis_code_hash=_hash("analysis-code"),
    )
    duplicate_report = report.canonical_json().replace(
        '"study_id":"parity-study-001"',
        '"study_id":"other","study_id":"parity-study-001"',
        1,
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        SyntheticParityReport.from_json(duplicate_report)
