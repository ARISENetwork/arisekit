from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace

import pytest

from arisekit.archetype import (
    ARCHETYPE_SCHEMA_VERSION,
    CLINICAL_VALIDITY_STATUS,
    PROGRAM_SCHEMA_VERSION,
    REGISTRY_SCHEMA_VERSION,
    STRUCTURAL_CLAIM_SCOPE,
    ApplicabilityEvidence,
    ArchetypeId,
    BenchmarkArchetype,
    BenchmarkArchetypeRegistry,
    ExecutionMode,
    JudgePolicy,
    MarginUnit,
    ModelRoute,
    ParityMargin,
    ReferenceAccessClass,
    ReferenceAuthority,
    ReferenceBundleBinding,
    SpecialtySupport,
    SpecialtyPlanCellBinding,
    SpecialtySourcePlanBinding,
    SyntheticBenchmarkProgram,
    SyntheticBundleBinding,
    SyntheticComparison,
    VariantSelectionPolicy,
    builtin_archetype_registry,
    registry_archetype_id_for_specialty,
)
from arisekit.authoring.specialty import (
    BenchmarkArchetype as SpecialtyAllocatorArchetype,
    BenchmarkTrack,
    ClinicalLock,
    ClinicalScope,
    ConditionFamily,
    ConditionSelection,
    DataAuthorization,
    ProgramScale,
    ReleaseScope,
    RepresentativeSelectionPolicy,
    RightsBasis,
    SamplingProtocol,
    Specialty,
    SpecialtyProfile,
    SpecialtyProgramSpec,
    StressSelectionPolicy,
    materialize_specialty_program,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _route(route_id: str, family: str) -> ModelRoute:
    return ModelRoute(
        route_id=route_id,
        provider=f"provider-{route_id}",
        model=f"model-{route_id}",
        snapshot="2026-07-01",
        family=family,
        runtime_config_hash=_hash(f"runtime-{route_id}"),
    )


def _reference(
    *,
    access_class: ReferenceAccessClass = ReferenceAccessClass.PUBLIC,
) -> ReferenceBundleBinding:
    private = access_class is not ReferenceAccessClass.PUBLIC
    return ReferenceBundleBinding(
        access_class=access_class,
        bundle_hash=_hash(f"reference-{access_class.value}"),
        manifest_hash=_hash(f"reference-manifest-{access_class.value}"),
        source_revision="upstream-v1",
        authority=(
            ReferenceAuthority.DATA_OWNER_AUTHORIZATION
            if private
            else ReferenceAuthority.UPSTREAM_RELEASE
        ),
        authority_digest=_hash(f"authority-{access_class.value}"),
        private_use_authorization_digest=(
            _hash(f"private-use-{access_class.value}") if private else None
        ),
    )


def _synthetic(
    *,
    generator: ModelRoute | None = None,
    suffix: str = "a",
    source_binding: SpecialtySourcePlanBinding | None = None,
) -> SyntheticBundleBinding:
    binding = source_binding or _source_binding()
    return SyntheticBundleBinding(
        bundle_hash=_hash(f"synthetic-{suffix}"),
        manifest_hash=binding.cell_inventory_sha256,
        generation_lineage_hash=_hash(f"lineage-{suffix}"),
        clinical_review_hash=binding.clinical_lock_sha256,
        rights_review_hash=binding.authorization_set_sha256,
        generator=generator or _route("generator", "generator-family"),
    )


def _source_binding(
    *,
    archetype: ArchetypeId = ArchetypeId.NOHARM,
    specialty: str = "cardiology",
    track: BenchmarkTrack = BenchmarkTrack.REPRESENTATIVE,
    route_ids: tuple[str, ...] = ("solver-a", "solver-b", "solver-c"),
    repetitions: int = 3,
    family_count: int = 6,
) -> SpecialtySourcePlanBinding:
    allocator_id = (
        "paired-specialty-equity"
        if archetype is ArchetypeId.PAIRED_EQUITY
        else "noharm"
    )
    return SpecialtySourcePlanBinding(
        allocator_archetype_id=allocator_id,
        specialty_id=specialty,
        track=track,
        spec_sha256=_hash("specialty-spec"),
        plan_sha256=_hash("specialty-plan"),
        clinical_scope_sha256=_hash("clinical-scope"),
        clinical_lock_sha256=_hash("clinical-lock"),
        authorization_sha256s=(
            _hash("authorization-b"),
            _hash("authorization-a"),
        ),
        planned_cells=(
            SpecialtyPlanCellBinding(
                cell_id=f"{specialty}--{track.value}--cell-a",
                family_count=family_count,
                cell_sha256=_hash("planned-cell-a"),
            ),
        ),
        cell_inventory_sha256=_hash("synthetic-cell-inventory"),
        materialized_bundle_sha256=_hash("synthetic-a"),
        study_design_sha256=_hash("study-design"),
        model_route_ids=route_ids,
        model_repetitions=repetitions,
    )


def _comparison(
    *,
    archetype: ArchetypeId = ArchetypeId.NOHARM,
    specialty: str = "cardiology",
    endpoint_id: str = "severity-weighted-f1-level",
    margin_unit: MarginUnit = MarginUnit.ABSOLUTE_SCORE,
    evidence: tuple[ApplicabilityEvidence, ...] = (),
    reference: ReferenceBundleBinding | None = None,
    synthetic: SyntheticBundleBinding | None = None,
    comparison_id: str = "noharm-cardiology",
) -> SyntheticComparison:
    source_binding = (
        _source_binding(archetype=archetype, specialty=specialty)
        if archetype in {ArchetypeId.NOHARM, ArchetypeId.PAIRED_EQUITY}
        else None
    )
    return SyntheticComparison(
        comparison_id=comparison_id,
        archetype_id=archetype,
        specialty_id=specialty,
        reference=reference or _reference(),
        synthetic=synthetic or _synthetic(source_binding=source_binding),
        endpoint_id=endpoint_id,
        margin=ParityMargin(unit=margin_unit, value=0.05),
        decision_rule_hash=_hash("decision-rule"),
        track=BenchmarkTrack.REPRESENTATIVE,
        source_plan_binding=source_binding,
        applicability_evidence=evidence,
    )


def _program(
    comparison: SyntheticComparison | None = None,
    *,
    solvers: tuple[ModelRoute, ...] | None = None,
    judges: tuple[ModelRoute, ...] | None = None,
) -> SyntheticBenchmarkProgram:
    return SyntheticBenchmarkProgram(
        program_id="synthetic-parity-pilot",
        registry=builtin_archetype_registry(),
        comparisons=(comparison or _comparison(),),
        solver_panel=solvers
        or (
            _route("solver-a", "solver-family-a"),
            _route("solver-b", "solver-family-b"),
            _route("solver-c", "solver-family-c"),
        ),
        judge_panel=(
            judges if judges is not None else (_route("judge-a", "judge-family"),)
        ),
        program_review_hash=_hash("program-review"),
    )


def _specialty_plan(
    *,
    allocator_archetype: SpecialtyAllocatorArchetype = (
        SpecialtyAllocatorArchetype.NOHARM
    ),
):
    scope = ClinicalScope(
        profile=SpecialtyProfile.CUSTOM,
        specialties=(Specialty.CARDIOLOGY,),
        condition_selections=(
            ConditionSelection(
                specialty=Specialty.CARDIOLOGY,
                common_condition=ConditionFamily.HEART_FAILURE,
                high_harm_condition=ConditionFamily.ACUTE_CORONARY_SYNDROME,
            ),
        ),
        sampling=SamplingProtocol(),
        representative_selection=RepresentativeSelectionPolicy(),
        stress_selection=StressSelectionPolicy(),
    )
    authorization = DataAuthorization(
        id="approved-source",
        source_reference="inventory://approved-source",
        data_inventory_sha256=_hash("source-inventory"),
        rights_basis=RightsBasis.INSTITUTION_AUTHORIZED,
        authorization_reference="governance://approval/001",
        authorization_artifact_sha256=_hash("authorization-artifact"),
        authorized_by="Institutional data owner",
        authorized_at="2026-07-23T09:00:00Z",
        release_scope=ReleaseScope.RESTRICTED,
    )
    spec = SpecialtyProgramSpec(
        program_id="cardiology-plan",
        clinical_scope=scope,
        clinical_lock=ClinicalLock(
            scope_sha256=scope.scope_sha256,
            clinician_name="Reviewing cardiologist",
            clinician_credential="board-certified cardiologist",
            locked_at="2026-07-23T10:00:00Z",
            approval_reference="clinical-review://scope-lock/001",
        ),
        data_authorizations=(authorization,),
        study_design_hash=_hash("external-study-design"),
        scale=ProgramScale.SMOKE,
        archetype=allocator_archetype,
        model_ids=("solver-a", "solver-b", "solver-c"),
        model_repetitions=3,
    )
    return materialize_specialty_program(spec)


def test_builtin_registry_covers_initial_archetypes_and_specialties() -> None:
    registry = builtin_archetype_registry()

    assert registry.schema_version == REGISTRY_SCHEMA_VERSION
    assert {value.value for value in ArchetypeId} == {
        "noharm",
        "sct",
        "medagentbench",
        "rexrank",
        "cpc",
        "paired-equity",
    }
    assert {item.archetype_id for item in registry.archetypes} == set(ArchetypeId)
    assert len(registry.specialties) == 14
    assert "obstetrics-gynecology" in registry.specialties
    assert "primary-internal-medicine" in registry.specialties
    assert all(
        archetype.schema_version == ARCHETYPE_SCHEMA_VERSION
        and {item.specialty_id for item in archetype.applicability}
        == set(registry.specialties)
        for archetype in registry.archetypes
    )


def test_archetype_contracts_preserve_distinct_evaluation_shapes() -> None:
    registry = builtin_archetype_registry()

    noharm = registry.get(ArchetypeId.NOHARM)
    assert noharm.topology.fixed_variants_per_family == 11
    assert (
        noharm.topology.variant_selection_policy
        is VariantSelectionPolicy.BASELINE_PLUS_PERTURBATION_SUBSET
    )
    assert noharm.topology.canonical_evaluated_variants_per_family == 5
    assert noharm.scorer_judge.judge_policy is JudgePolicy.REQUIRED
    assert noharm.scorer_judge.aggregation_unit == "base-case"

    sct = registry.get(ArchetypeId.SCT)
    assert sct.scorer_judge.judge_policy is JudgePolicy.NONE
    assert sct.scorer_judge.item_score_fields == ("concordance",)

    agentic = registry.get(ArchetypeId.MEDAGENTBENCH)
    assert agentic.topology.execution_mode is ExecutionMode.AGENTIC
    assert agentic.topology.requires_checkpoint_per_turn
    assert all(
        item.support is SpecialtySupport.CONDITIONAL for item in agentic.applicability
    )

    multimodal = registry.get(ArchetypeId.REXRANK)
    assert multimodal.topology.execution_mode is ExecutionMode.MULTIMODAL
    assert multimodal.specialty("psychiatry").support is SpecialtySupport.UNSUPPORTED

    equity = registry.get(ArchetypeId.PAIRED_EQUITY)
    assert equity.topology.fixed_variants_per_family == 2
    assert equity.topology.variant_selection_policy is VariantSelectionPolicy.FIXED
    assert {item.endpoint_id for item in equity.parity_endpoints} >= {
        "invariant-unjustified-discordance",
        "differentiated-correct-rate",
        "information-seeking-rate",
        "severe-error-rate",
    }

    assert registry_archetype_id_for_specialty("noharm") is ArchetypeId.NOHARM
    assert (
        registry_archetype_id_for_specialty("paired-specialty-equity")
        is ArchetypeId.PAIRED_EQUITY
    )


def test_archetype_and_registry_round_trip_are_digest_stable() -> None:
    registry = builtin_archetype_registry()
    forward = BenchmarkArchetypeRegistry.from_dict(registry.to_dict())

    assert forward == registry
    assert forward.digest == registry.digest
    assert len(forward.digest) == 64
    for archetype in registry.archetypes:
        round_trip = BenchmarkArchetype.from_dict(archetype.to_dict())
        assert round_trip == archetype
        assert round_trip.digest == archetype.digest


def test_program_pins_inputs_and_produces_deterministic_comparison_cells() -> None:
    program = _program()

    assert program.schema_version == PROGRAM_SCHEMA_VERSION
    assert len(program.comparison_cells) == 3
    assert len({cell.cell_id for cell in program.comparison_cells}) == 3
    assert all(
        cell.reference_bundle_hash == _comparison().reference.bundle_hash
        and cell.synthetic_bundle_hash == _comparison().synthetic.bundle_hash
        and cell.endpoint_id == "severity-weighted-f1-level"
        for cell in program.comparison_cells
    )
    assert program.comparison_cells == _program().comparison_cells
    assert program.to_dict()["claim_scope"] == STRUCTURAL_CLAIM_SCOPE
    assert program.to_dict()["clinical_validity_status"] == CLINICAL_VALIDITY_STATUS

    round_trip = SyntheticBenchmarkProgram.from_dict(
        program.to_dict(),
        registry=builtin_archetype_registry(),
    )
    assert round_trip.to_dict() == program.to_dict()
    assert round_trip.digest == program.digest


def test_specialty_source_binding_is_derived_from_one_exact_plan_slice() -> None:
    plan = _specialty_plan()
    binding = SpecialtySourcePlanBinding._from_specialty_plan_evidence(
        plan,
        specialty=Specialty.CARDIOLOGY,
        track=BenchmarkTrack.REPRESENTATIVE,
        cell_inventory_sha256=_hash("materialized-cell-inventory"),
        materialized_bundle_sha256=_hash("materialized-bundle"),
        study_design_sha256=plan.spec.study_design_hash,
    )

    assert binding.spec_sha256 == plan.spec.spec_sha256
    assert binding.plan_sha256 == plan.plan_sha256
    assert binding.clinical_scope_sha256 == plan.spec.clinical_scope.scope_sha256
    assert binding.clinical_lock_sha256 == plan.spec.clinical_lock.lock_sha256
    assert binding.authorization_sha256s == tuple(
        sorted(
            authorization.authorization_sha256
            for authorization in plan.spec.data_authorizations
        )
    )
    assert binding.registry_archetype_id is ArchetypeId.NOHARM
    assert binding.specialty_id == "cardiology"
    assert binding.track is BenchmarkTrack.REPRESENTATIVE
    assert binding.planned_family_count == sum(
        cell.family_count
        for cell in plan.cells
        if cell.specialty is Specialty.CARDIOLOGY
        and cell.track is BenchmarkTrack.REPRESENTATIVE
    )
    assert binding.model_route_ids == plan.spec.model_ids
    assert binding.model_repetitions == plan.spec.model_repetitions
    assert SpecialtySourcePlanBinding.from_dict(binding.to_dict()) == binding

    stale_design = _hash("stale-study-design")
    with pytest.raises(ValueError, match="study design hash is stale"):
        SpecialtySourcePlanBinding._from_specialty_plan_evidence(
            plan,
            specialty=Specialty.CARDIOLOGY,
            track=BenchmarkTrack.REPRESENTATIVE,
            cell_inventory_sha256=_hash("materialized-cell-inventory"),
            materialized_bundle_sha256=_hash("materialized-bundle"),
            study_design_sha256=stale_design,
        )


def test_specialty_source_binding_rejects_rehashed_derived_field_tampering() -> None:
    plan = _specialty_plan()
    binding = SpecialtySourcePlanBinding._from_specialty_plan_evidence(
        plan,
        specialty=Specialty.CARDIOLOGY,
        track=BenchmarkTrack.REPRESENTATIVE,
        cell_inventory_sha256=_hash("materialized-cell-inventory"),
        materialized_bundle_sha256=_hash("materialized-bundle"),
        study_design_sha256=plan.spec.study_design_hash,
    )
    payload = copy.deepcopy(binding.to_dict())
    payload["planned_family_count"] += 1
    unsigned = {key: value for key, value in payload.items() if key != "binding_sha256"}
    payload["binding_sha256"] = _canonical_hash(unsigned)

    with pytest.raises(ValueError, match="not canonically derived"):
        SpecialtySourcePlanBinding.from_dict(payload)


def test_source_bound_program_rejects_stale_plan_and_bundle_links() -> None:
    plan = _specialty_plan()
    binding = SpecialtySourcePlanBinding._from_specialty_plan_evidence(
        plan,
        specialty=Specialty.CARDIOLOGY,
        track=BenchmarkTrack.REPRESENTATIVE,
        cell_inventory_sha256=_hash("materialized-cell-inventory"),
        materialized_bundle_sha256=_hash("synthetic-a"),
        study_design_sha256=plan.spec.study_design_hash,
    )
    comparison = replace(
        _comparison(),
        source_plan_binding=binding,
        synthetic=_synthetic(source_binding=binding),
    )
    assert _program(comparison).comparison_cells

    wrong_routes = replace(
        binding,
        model_route_ids=("other-a", "other-b", "other-c"),
    )
    with pytest.raises(ValueError, match="model route IDs"):
        _program(
            replace(
                comparison,
                source_plan_binding=wrong_routes,
                synthetic=_synthetic(source_binding=wrong_routes),
            )
        )

    stale_links = (
        (
            replace(
                comparison.synthetic,
                clinical_review_hash=_hash("stale-clinical-lock"),
            ),
            "clinical review",
        ),
        (
            replace(
                comparison.synthetic,
                rights_review_hash=_hash("stale-authorizations"),
            ),
            "rights review",
        ),
        (
            replace(
                comparison.synthetic,
                manifest_hash=_hash("stale-cell-inventory"),
            ),
            "synthetic manifest",
        ),
    )
    for synthetic, message in stale_links:
        with pytest.raises(ValueError, match=message):
            _program(replace(comparison, synthetic=synthetic))


def test_source_bound_comparison_rejects_missing_or_wrong_plan_identity() -> None:
    with pytest.raises(ValueError, match="require a SpecialtySourcePlanBinding"):
        replace(_comparison(), source_plan_binding=None)

    wrong_specialty = _source_binding(specialty="neurology")
    with pytest.raises(ValueError, match="comparison specialty"):
        replace(_comparison(), source_plan_binding=wrong_specialty)

    wrong_allocator = _source_binding(archetype=ArchetypeId.PAIRED_EQUITY)
    with pytest.raises(ValueError, match="allocator archetype"):
        replace(_comparison(), source_plan_binding=wrong_allocator)


def test_representative_and_stress_use_separate_comparisons() -> None:
    plan = _specialty_plan()
    representative = SpecialtySourcePlanBinding._from_specialty_plan_evidence(
        plan,
        specialty=Specialty.CARDIOLOGY,
        track=BenchmarkTrack.REPRESENTATIVE,
        cell_inventory_sha256=_hash("representative-inventory"),
        materialized_bundle_sha256=_hash("synthetic-representative"),
        study_design_sha256=plan.spec.study_design_hash,
    )
    stress = SpecialtySourcePlanBinding._from_specialty_plan_evidence(
        plan,
        specialty=Specialty.CARDIOLOGY,
        track=BenchmarkTrack.STRESS,
        cell_inventory_sha256=_hash("stress-inventory"),
        materialized_bundle_sha256=_hash("synthetic-stress"),
        study_design_sha256=plan.spec.study_design_hash,
    )
    primary_comparison = replace(
        _comparison(),
        source_plan_binding=representative,
        synthetic=_synthetic(source_binding=representative, suffix="representative"),
    )
    stress_comparison = replace(
        primary_comparison,
        comparison_id="noharm-cardiology-stress",
        track=BenchmarkTrack.STRESS,
        source_plan_binding=stress,
        synthetic=_synthetic(source_binding=stress, suffix="stress"),
    )
    program = SyntheticBenchmarkProgram(
        program_id="two-track-program",
        registry=builtin_archetype_registry(),
        comparisons=(primary_comparison, stress_comparison),
        solver_panel=(
            _route("solver-a", "solver-family-a"),
            _route("solver-b", "solver-family-b"),
            _route("solver-c", "solver-family-c"),
        ),
        judge_panel=(_route("judge-a", "judge-family"),),
        program_review_hash=_hash("two-track-review"),
    )

    assert {comparison.track for comparison in program.comparisons} == {
        BenchmarkTrack.REPRESENTATIVE,
        BenchmarkTrack.STRESS,
    }


def test_cell_id_changes_when_a_load_bearing_bundle_changes() -> None:
    original = _program()
    changed_binding = replace(
        original.comparisons[0].source_plan_binding,
        cell_inventory_sha256=_hash("synthetic-cell-inventory-changed"),
        materialized_bundle_sha256=_hash("synthetic-changed"),
    )
    changed_synthetic = replace(
        _synthetic(suffix="changed"),
        manifest_hash=changed_binding.cell_inventory_sha256,
        clinical_review_hash=changed_binding.clinical_lock_sha256,
        rights_review_hash=changed_binding.authorization_set_sha256,
    )
    changed_comparison = replace(
        original.comparisons[0],
        synthetic=changed_synthetic,
        source_plan_binding=changed_binding,
    )
    changed = _program(changed_comparison)

    assert changed.comparison_cells[0].cell_id != original.comparison_cells[0].cell_id
    assert changed.digest != original.digest


def test_program_rejects_unsupported_specialty_archetype_pair() -> None:
    comparison = _comparison(
        archetype=ArchetypeId.REXRANK,
        specialty="psychiatry",
        endpoint_id="report-quality-level",
        comparison_id="rexrank-psychiatry",
    )
    with pytest.raises(ValueError, match="unsupported specialty/archetype pair"):
        _program(comparison)


def test_conditional_pair_requires_exact_hash_bound_evidence() -> None:
    missing = _comparison(
        archetype=ArchetypeId.MEDAGENTBENCH,
        endpoint_id="task-success-rate",
        margin_unit=MarginUnit.RATE_DIFFERENCE,
        comparison_id="agentic-cardiology",
    )
    with pytest.raises(ValueError, match="must exactly match"):
        _program(missing, judges=())

    evidence = tuple(
        ApplicabilityEvidence(requirement_id=value, evidence_hash=_hash(value))
        for value in ("executable-tool-sandbox", "state-transition-oracle")
    )
    complete = replace(missing, applicability_evidence=evidence)
    assert _program(complete, judges=()).comparison_cells

    extra = replace(
        complete,
        applicability_evidence=complete.applicability_evidence
        + (
            ApplicabilityEvidence(
                requirement_id="unrequested-evidence",
                evidence_hash=_hash("extra"),
            ),
        ),
    )
    with pytest.raises(ValueError, match="must exactly match"):
        _program(extra, judges=())


def test_private_reference_requires_data_owner_authorization_digest() -> None:
    with pytest.raises(ValueError, match="requires authorization digest"):
        ReferenceBundleBinding(
            access_class=ReferenceAccessClass.PRIVATE,
            bundle_hash=_hash("private-bundle"),
            manifest_hash=_hash("private-manifest"),
            source_revision="private-v1",
            authority=ReferenceAuthority.DATA_OWNER_AUTHORIZATION,
            authority_digest=_hash("authority"),
        )

    with pytest.raises(ValueError, match="requires data-owner authority"):
        replace(
            _reference(access_class=ReferenceAccessClass.RESTRICTED),
            authority=ReferenceAuthority.UPSTREAM_RELEASE,
        )

    private = _reference(access_class=ReferenceAccessClass.PRIVATE)
    assert private.private_use_authorization_digest is not None


def test_reference_rejects_self_declared_or_unpinned_identity() -> None:
    payload = _reference().to_dict()
    payload["authority"] = "self-declared"
    with pytest.raises(ValueError, match="reference authority must be one of"):
        ReferenceBundleBinding.from_dict(payload)

    payload = _reference().to_dict()
    payload["bundle_hash"] = "unpinned"
    with pytest.raises(ValueError, match="SHA-256"):
        ReferenceBundleBinding.from_dict(payload)


def test_structural_emulation_cannot_claim_clinical_validity() -> None:
    with pytest.raises(ValueError, match="structural emulation"):
        replace(_comparison(), clinical_validity_status="clinically-validated")
    with pytest.raises(ValueError, match="structural parity research only"):
        replace(_comparison(), claim_scope="clinically-equivalent")


@pytest.mark.parametrize(
    ("synthetic", "solvers", "judges", "message"),
    (
        (
            _synthetic(
                generator=_route("generator", "solver-family-a"),
            ),
            None,
            None,
            "generator/solver",
        ),
        (
            _synthetic(
                generator=_route("generator", "judge-family"),
            ),
            None,
            None,
            "generator/judge",
        ),
        (
            None,
            None,
            (_route("judge-a", "solver-family-b"),),
            "solver/judge",
        ),
    ),
)
def test_program_rejects_generator_solver_judge_family_overlap(
    synthetic: SyntheticBundleBinding | None,
    solvers: tuple[ModelRoute, ...] | None,
    judges: tuple[ModelRoute, ...] | None,
    message: str,
) -> None:
    comparison = _comparison(synthetic=synthetic) if synthetic is not None else None
    with pytest.raises(ValueError, match=message):
        _program(comparison, solvers=solvers, judges=judges)


@pytest.mark.parametrize("count", (2, 5))
def test_program_requires_three_or_four_distinct_solver_families(count: int) -> None:
    solvers = tuple(
        _route(f"solver-{index}", f"solver-family-{index}") for index in range(count)
    )
    with pytest.raises(ValueError, match="solver_panel"):
        _program(solvers=solvers)

    repeated = (
        _route("solver-a", "same-family"),
        _route("solver-b", "same-family"),
        _route("solver-c", "other-family"),
    )
    with pytest.raises(ValueError, match="solver families"):
        _program(solvers=repeated)


def test_judge_contract_is_enforced_by_selected_archetypes() -> None:
    with pytest.raises(ValueError, match="requires a pinned judge panel"):
        _program(judges=())

    sct = _comparison(
        archetype=ArchetypeId.SCT,
        endpoint_id="expert-concordance-level",
        comparison_id="sct-cardiology",
    )
    with pytest.raises(ValueError, match="judge-free archetypes"):
        _program(sct)
    assert _program(sct, judges=()).comparison_cells


def test_mixed_program_omits_judges_from_judge_free_comparisons() -> None:
    noharm = _comparison()
    sct = _comparison(
        archetype=ArchetypeId.SCT,
        endpoint_id="expert-concordance-level",
        comparison_id="sct-cardiology",
    )
    program = SyntheticBenchmarkProgram(
        program_id="mixed-archetype-pilot",
        registry=builtin_archetype_registry(),
        comparisons=(noharm, sct),
        solver_panel=(
            _route("solver-a", "solver-family-a"),
            _route("solver-b", "solver-family-b"),
            _route("solver-c", "solver-family-c"),
        ),
        judge_panel=(_route("judge-a", "judge-family"),),
        program_review_hash=_hash("mixed-program-review"),
    )

    assert len(program.judge_panel_for(noharm.comparison_id)) == 1
    assert program.judge_panel_for(sct.comparison_id) == ()
    assert program.evaluation_contract_payload(sct.comparison_id)["judge_panel"] == []


def test_endpoint_and_margin_must_come_from_selected_archetype() -> None:
    with pytest.raises(ValueError, match="is not supported"):
        _program(replace(_comparison(), endpoint_id="invented-endpoint"))

    with pytest.raises(ValueError, match="margin unit"):
        _program(
            replace(
                _comparison(),
                margin=ParityMargin(MarginUnit.RATE_DIFFERENCE, 0.05),
            )
        )

    with pytest.raises(ValueError, match="smaller than the endpoint range"):
        _program(
            replace(
                _comparison(),
                margin=ParityMargin(MarginUnit.ABSOLUTE_SCORE, 1.0),
            )
        )


def test_program_loader_rejects_registry_or_cell_tampering() -> None:
    program = _program()
    payload = copy.deepcopy(program.to_dict())
    payload["registry_digest"] = _hash("another-registry")
    with pytest.raises(ValueError, match="registry digest"):
        SyntheticBenchmarkProgram.from_dict(
            payload,
            registry=builtin_archetype_registry(),
        )

    payload = copy.deepcopy(program.to_dict())
    payload["comparison_cells"][0]["endpoint_id"] = "tampered"
    with pytest.raises(ValueError, match="comparison cells"):
        SyntheticBenchmarkProgram.from_dict(
            payload,
            registry=builtin_archetype_registry(),
        )


def test_strict_loaders_reject_unknown_fields() -> None:
    payload = builtin_archetype_registry().to_dict()
    payload["extra"] = "not accepted"
    with pytest.raises(ValueError, match="fields are invalid"):
        BenchmarkArchetypeRegistry.from_dict(payload)

    payload = _program().to_dict()
    payload["extra"] = "not accepted"
    with pytest.raises(ValueError, match="fields are invalid"):
        SyntheticBenchmarkProgram.from_dict(
            payload,
            registry=builtin_archetype_registry(),
        )
