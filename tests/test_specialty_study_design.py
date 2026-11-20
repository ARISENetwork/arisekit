"""Tests for the frozen specialty benchmark study-design contract."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from arisekit.authoring.specialty import (
    BenchmarkArchetype,
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
from arisekit.specialty_study_design import (
    DecisionMargin,
    EndpointKind,
    EndpointSpec,
    EvaluationConditionMatch,
    MarginUnit,
    MultiplicityMethod,
    MultiplicityPlan,
    PhysicianAssignment,
    PhysicianAssignmentManifest,
    PhysicianFamily,
    PhysicianFamilyManifest,
    PhysicianInclusionStrategy,
    PhysicianPlan,
    SampleSizeDesign,
    SampleSizeTier,
    SpecialtyStudyDesign,
)


def _hash(label: str) -> str:
    import hashlib

    return hashlib.sha256(label.encode()).hexdigest()


def _conditions(*, matched: bool = True) -> EvaluationConditionMatch:
    return EvaluationConditionMatch(
        specialty_matched=matched,
        time_matched=matched,
        interface_matched=matched,
        tools_matched=matched,
        retrieval_matched=matched,
        assistance_matched=matched,
        notes="The operations owner recorded each comparison condition.",
    )


def _margin(label: str, value: float = 0.05) -> DecisionMargin:
    return DecisionMargin(
        value=value,
        unit=MarginUnit.RATE_DIFFERENCE,
        justification=f"Clinical and statistical owners approved {label}.",
        clinical_approval_hash=_hash(f"{label}-clinical"),
        statistical_approval_hash=_hash(f"{label}-statistical"),
    )


def _endpoint_panel() -> tuple[EndpointSpec, ...]:
    return (
        EndpointSpec(
            endpoint_id="absolute-quality",
            kind=EndpointKind.ABSOLUTE_PERFORMANCE,
            metric="clinically acceptable response rate",
            estimand="Rate for each population variant separately.",
            primary=False,
            reports_each_variant=True,
        ),
        EndpointSpec(
            endpoint_id="invariant-discordance",
            kind=EndpointKind.PAIRED_RELATIONSHIP,
            relationship="invariant",
            metric="unjustified clinical-decision discordance",
            estimand="Within-family discordance rate.",
            primary=True,
            margin=_margin("invariant"),
        ),
        EndpointSpec(
            endpoint_id="correct-differentiation",
            kind=EndpointKind.PAIRED_RELATIONSHIP,
            relationship="differentiated",
            metric="correct differentiation rate",
            estimand="Within-family correct differentiation rate.",
            primary=True,
            margin=_margin("differentiated"),
        ),
        EndpointSpec(
            endpoint_id="safe-information-seeking",
            kind=EndpointKind.PAIRED_RELATIONSHIP,
            relationship="information-required",
            metric="safe information-seeking rate",
            estimand="Within-family rate of requesting essential information.",
            primary=True,
            margin=_margin("information"),
        ),
        EndpointSpec(
            endpoint_id="severe-error",
            kind=EndpointKind.SAFETY_GUARDRAIL,
            metric="severe-error rate by variant",
            estimand="Rate and upper confidence bound for each variant.",
            primary=False,
            margin=DecisionMargin(
                value=0.02,
                unit=MarginUnit.SAFETY_RATE,
                justification="Owners approved a prespecified safety threshold.",
                clinical_approval_hash=_hash("safety-clinical"),
                statistical_approval_hash=_hash("safety-statistical"),
            ),
            reports_each_variant=True,
            adjudicates_every_severe_error=True,
        ),
    )


def _physician_default() -> PhysicianPlan:
    return PhysicianPlan(
        strategy=PhysicianInclusionStrategy.DESCRIPTIVE_BASELINE,
        rationale="Use a descriptive physician baseline on representative cases.",
        target_physicians=16,
        representative_family_count=45,
        responses_per_variant=3,
        family_allocation_protocol_hash=_hash("physician-family-allocation-protocol"),
        family_allocation_seed_hash=_hash("physician-family-allocation-seed"),
        assignment_protocol_hash=_hash("physician-assignment-protocol"),
        assignment_seed_hash=_hash("physician-assignment-seed"),
        prohibits_companion_variant_exposure=True,
        evaluation_conditions=_conditions(),
        pilot_default=True,
    )


def _design() -> SpecialtyStudyDesign:
    endpoints = _endpoint_panel()
    return SpecialtyStudyDesign(
        design_id="paired-specialty-pilot",
        archetype_id="paired-specialty-equity",
        physician_plan=_physician_default(),
        endpoints=endpoints,
        sample_size=SampleSizeDesign(
            tier=SampleSizeTier.ILLUSTRATIVE_PILOT_DEFAULT,
            representative_families=108,
            stress_families=36,
            model_repetitions_per_variant=3,
            simulation_artifact_hash=_hash("sample-size-simulation"),
            assumption_manifest_hash=_hash("sample-size-assumptions"),
        ),
        multiplicity=MultiplicityPlan(
            method=MultiplicityMethod.DESCRIPTIVE_CI_ONLY,
            endpoint_ids=tuple(endpoint.endpoint_id for endpoint in endpoints),
            primary_endpoint_ids=tuple(
                endpoint.endpoint_id for endpoint in endpoints if endpoint.primary
            ),
            confirmatory_claims=False,
            nominal_alpha=None,
            ordering=(),
            rationale="This pilot reports confidence intervals without claims.",
        ),
        approved_parity_decision_rule_hash=_hash("parity-decision-rule"),
        clinical_approval_hash=_hash("design-clinical"),
        statistical_approval_hash=_hash("design-statistical"),
        operations_approval_hash=_hash("design-operations"),
    )


def _plan_for_design(
    design: SpecialtyStudyDesign,
    *,
    study_design_hash: str | None = None,
    archetype: BenchmarkArchetype = BenchmarkArchetype.PAIRED_SPECIALTY_EQUITY,
    representative_families: int = 108,
    stress_families: int = 36,
    repetitions: int = 3,
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
    spec = SpecialtyProgramSpec(
        program_id="cardiology-paired-pilot",
        clinical_scope=scope,
        clinical_lock=ClinicalLock(
            scope_sha256=scope.scope_sha256,
            clinician_name="Reviewing physician",
            clinician_credential="board-certified cardiologist",
            locked_at="2026-07-23T10:00:00Z",
            approval_reference="clinical-review://cardiology/001",
        ),
        data_authorizations=(
            DataAuthorization(
                id="cardiology-source",
                source_reference="inventory://cardiology-source",
                data_inventory_sha256=_hash("cardiology-inventory"),
                rights_basis=RightsBasis.INSTITUTION_AUTHORIZED,
                authorization_reference="governance://cardiology/001",
                authorization_artifact_sha256=_hash("cardiology-authorization"),
                authorized_by="Institutional data owner",
                authorized_at="2026-07-23T09:00:00Z",
                release_scope=ReleaseScope.RESTRICTED,
            ),
        ),
        study_design_hash=study_design_hash or design.digest,
        scale=ProgramScale.CUSTOM,
        model_ids=("model-a", "model-b", "model-c"),
        model_repetitions=repetitions,
        archetype=archetype,
        representative_family_target=representative_families,
        stress_family_target=stress_families,
    )
    return materialize_specialty_program(spec)


def test_paired_design_round_trip_and_digest_are_canonical() -> None:
    design = _design()
    loaded = SpecialtyStudyDesign.from_json(design.canonical_json)

    assert loaded == design
    assert loaded.digest == design.digest
    assert json.loads(design.canonical_json)["schema_version"].endswith(".v2")


def test_study_design_schema_and_decision_rule_approval_fail_closed() -> None:
    payload = _design().to_dict()
    payload["schema_version"] = "arisekit.specialty-study-design.v1"
    with pytest.raises(ValueError, match="schema_version"):
        SpecialtyStudyDesign.from_dict(payload)

    payload = _design().to_dict()
    del payload["approved_parity_decision_rule_hash"]
    with pytest.raises(ValueError, match="approved_parity_decision_rule_hash"):
        SpecialtyStudyDesign.from_dict(payload)


def test_study_design_validates_against_exact_materialized_plan() -> None:
    design = _design()

    design.validate_against_plan(_plan_for_design(design))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"study_design_hash": _hash("different-design")},
            "does not bind this study-design digest",
        ),
        (
            {"archetype": BenchmarkArchetype.NOHARM},
            "archetype does not match",
        ),
        (
            {"representative_families": 107},
            "representative family target does not match",
        ),
        (
            {"stress_families": 35},
            "stress family target does not match",
        ),
        (
            {"repetitions": 5},
            "model repetitions do not match",
        ),
    ],
)
def test_study_design_rejects_plan_contract_drift(
    kwargs: dict[str, object], message: str
) -> None:
    design = _design()

    with pytest.raises(ValueError, match=message):
        design.validate_against_plan(_plan_for_design(design, **kwargs))


@pytest.mark.parametrize(
    ("strategy", "kwargs"),
    [
        (
            PhysicianInclusionStrategy.MODEL_ONLY_FEASIBILITY,
            {
                "target_physicians": None,
                "representative_family_count": None,
                "responses_per_variant": None,
                "family_allocation_protocol_hash": None,
                "family_allocation_seed_hash": None,
                "assignment_protocol_hash": None,
                "assignment_seed_hash": None,
            },
        ),
        (
            PhysicianInclusionStrategy.CLINICIAN_EVALUATION_ONLY,
            {
                "target_physicians": 6,
                "representative_family_count": None,
                "responses_per_variant": None,
                "family_allocation_protocol_hash": None,
                "family_allocation_seed_hash": None,
                "assignment_protocol_hash": None,
                "assignment_seed_hash": None,
            },
        ),
        (
            PhysicianInclusionStrategy.DESCRIPTIVE_BASELINE,
            {
                "target_physicians": 12,
                "representative_family_count": 40,
                "responses_per_variant": 2,
                "family_allocation_protocol_hash": _hash(
                    "descriptive-allocation-protocol"
                ),
                "family_allocation_seed_hash": _hash("descriptive-allocation-seed"),
                "assignment_protocol_hash": _hash("descriptive-assignment-protocol"),
                "assignment_seed_hash": _hash("descriptive-assignment-seed"),
            },
        ),
        (
            PhysicianInclusionStrategy.FULL_HEAD_TO_HEAD,
            {
                "target_physicians": 12,
                "representative_family_count": 108,
                "responses_per_variant": 2,
                "family_allocation_protocol_hash": _hash(
                    "head-to-head-allocation-protocol"
                ),
                "family_allocation_seed_hash": _hash("head-to-head-allocation-seed"),
                "assignment_protocol_hash": _hash("head-to-head-assignment-protocol"),
                "assignment_seed_hash": _hash("head-to-head-assignment-seed"),
            },
        ),
        (
            PhysicianInclusionStrategy.ASSISTED_UNASSISTED_CROSSOVER,
            {
                "target_physicians": 12,
                "representative_family_count": 40,
                "responses_per_variant": 2,
                "family_allocation_protocol_hash": _hash(
                    "crossover-allocation-protocol"
                ),
                "family_allocation_seed_hash": _hash("crossover-allocation-seed"),
                "assignment_protocol_hash": _hash("crossover-assignment-protocol"),
                "assignment_seed_hash": _hash("crossover-assignment-seed"),
            },
        ),
    ],
)
def test_all_physician_strategies_serialize_distinctly(
    strategy: PhysicianInclusionStrategy, kwargs: dict
) -> None:
    plan = PhysicianPlan(
        strategy=strategy,
        rationale=f"Owners selected {strategy.value}.",
        prohibits_companion_variant_exposure=True,
        evaluation_conditions=_conditions(),
        **kwargs,
    )

    assert PhysicianPlan.from_dict(plan.to_dict()) == plan
    assert plan.to_dict()["strategy"] == strategy.value


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("target_physicians", 11, "between 12 and 20"),
        ("representative_family_count", 39, "40 to 50"),
        ("responses_per_variant", 4, "two or three"),
        ("prohibits_companion_variant_exposure", False, "must not see both"),
    ],
)
def test_descriptive_pilot_default_enforces_assignment_contract(
    field: str, value: object, message: str
) -> None:
    payload = _physician_default().to_dict()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        PhysicianPlan.from_dict(payload)


def test_head_to_head_requires_every_evaluation_condition_to_match() -> None:
    with pytest.raises(ValueError, match="all evaluation conditions"):
        PhysicianPlan(
            strategy=PhysicianInclusionStrategy.FULL_HEAD_TO_HEAD,
            rationale="Compare physicians and models under the same protocol.",
            target_physicians=12,
            representative_family_count=108,
            responses_per_variant=2,
            family_allocation_protocol_hash=_hash("allocation-protocol"),
            family_allocation_seed_hash=_hash("allocation-seed"),
            assignment_protocol_hash=_hash("assignment-protocol"),
            assignment_seed_hash=_hash("assignment-seed"),
            prohibits_companion_variant_exposure=True,
            evaluation_conditions=_conditions(matched=False),
        )


def _physician_answering_design() -> SpecialtyStudyDesign:
    return replace(
        _design(),
        design_id="paired-specialty-physician-assignment",
        physician_plan=replace(
            _physician_default(),
            target_physicians=4,
            representative_family_count=2,
            responses_per_variant=2,
            pilot_default=False,
        ),
    )


def _physician_family_manifest(
    study_design: SpecialtyStudyDesign,
    specialty_plan,
) -> PhysicianFamilyManifest:
    representative_cell = next(
        cell for cell in specialty_plan.cells if cell.track.value == "representative"
    )
    return PhysicianFamilyManifest(
        study_design_sha256=study_design.digest,
        plan_sha256=specialty_plan.plan_sha256,
        archetype_id=specialty_plan.spec.archetype.value,
        track="representative",
        families=tuple(
            PhysicianFamily(
                case_family_id=family,
                plan_cell_id=representative_cell.cell_id,
                variant_ids=(f"{family}-variant-a", f"{family}-variant-b"),
            )
            for family in ("family-1", "family-2")
        ),
    )


def _assignment_manifest(
    study_design: SpecialtyStudyDesign,
    specialty_plan,
    family_manifest: PhysicianFamilyManifest,
) -> PhysicianAssignmentManifest:
    return PhysicianAssignmentManifest(
        study_design_sha256=study_design.digest,
        plan_sha256=specialty_plan.plan_sha256,
        family_subset_manifest_hash=family_manifest.digest,
        responses_per_variant=2,
        assignments=tuple(
            PhysicianAssignment(
                physician_id=physician,
                case_family_id=family.case_family_id,
                variant_id=variant,
            )
            for family in family_manifest.families
            for variant, physicians in (
                (family.variant_ids[0], ("physician-1", "physician-2")),
                (family.variant_ids[1], ("physician-3", "physician-4")),
            )
            for physician in physicians
        ),
    )


def test_assignment_manifest_blocks_companion_exposure_and_binds_two_phases() -> None:
    study_design = _physician_answering_design()
    preregistered_design_digest = study_design.digest
    specialty_plan = _plan_for_design(study_design)
    family_manifest = _physician_family_manifest(study_design, specialty_plan)
    manifest = _assignment_manifest(study_design, specialty_plan, family_manifest)

    study_design.validate_physician_assignments(
        specialty_plan,
        family_manifest=family_manifest,
        assignment_manifest=manifest,
    )
    assert PhysicianAssignmentManifest.from_json(manifest.canonical_json) == manifest
    family_manifest.validate_against(study_design, specialty_plan)
    assert (
        PhysicianFamilyManifest.from_json(family_manifest.canonical_json)
        == family_manifest
    )
    assert "family_subset_manifest_hash" not in study_design.physician_plan.to_dict()
    assert "assignment_manifest_hash" not in study_design.physician_plan.to_dict()
    assert family_manifest.study_design_sha256 == study_design.digest
    assert manifest.study_design_sha256 == study_design.digest
    assert study_design.digest == preregistered_design_digest

    assignments = list(manifest.assignments)
    assignments[-1] = PhysicianAssignment(
        physician_id="physician-1",
        case_family_id=assignments[-1].case_family_id,
        variant_id=assignments[-1].variant_id,
    )
    with pytest.raises(ValueError, match="both variants"):
        PhysicianAssignmentManifest(
            study_design_sha256=study_design.digest,
            plan_sha256=specialty_plan.plan_sha256,
            family_subset_manifest_hash=manifest.family_subset_manifest_hash,
            responses_per_variant=2,
            assignments=tuple(assignments),
        )


def test_realized_physician_manifests_reject_stale_design_and_plan_hashes() -> None:
    study_design = _physician_answering_design()
    specialty_plan = _plan_for_design(study_design)
    family_manifest = _physician_family_manifest(study_design, specialty_plan)
    assignment_manifest = _assignment_manifest(
        study_design, specialty_plan, family_manifest
    )

    changed_design = replace(
        study_design,
        physician_plan=replace(
            study_design.physician_plan,
            family_allocation_seed_hash=_hash("changed-allocation-seed"),
        ),
    )
    changed_plan = _plan_for_design(changed_design)
    with pytest.raises(ValueError, match="does not bind the study design"):
        family_manifest.validate_against(changed_design, changed_plan)

    stale_family_plan = replace(
        family_manifest,
        plan_sha256=_hash("stale-specialty-plan"),
    )
    with pytest.raises(ValueError, match="does not bind the specialty plan"):
        stale_family_plan.validate_against(study_design, specialty_plan)

    stale_assignment_design = replace(
        assignment_manifest,
        study_design_sha256=_hash("stale-study-design"),
    )
    with pytest.raises(ValueError, match="does not bind the study design"):
        stale_assignment_design.validate_against(
            study_design,
            family_manifest=family_manifest,
            specialty_plan=specialty_plan,
        )

    stale_assignment_plan = replace(
        assignment_manifest,
        plan_sha256=_hash("stale-specialty-plan"),
    )
    with pytest.raises(ValueError, match="does not bind the specialty plan"):
        stale_assignment_plan.validate_against(
            study_design,
            family_manifest=family_manifest,
            specialty_plan=specialty_plan,
        )

    stale_assignment_family = replace(
        assignment_manifest,
        family_subset_manifest_hash=_hash("stale-family-manifest"),
    )
    with pytest.raises(ValueError, match="does not bind the family manifest"):
        stale_assignment_family.validate_against(
            study_design,
            family_manifest=family_manifest,
            specialty_plan=specialty_plan,
        )


def test_physician_artifact_schema_versions_fail_closed() -> None:
    study_design = _physician_answering_design()
    specialty_plan = _plan_for_design(study_design)
    family_manifest = _physician_family_manifest(study_design, specialty_plan)
    assignment_manifest = _assignment_manifest(
        study_design, specialty_plan, family_manifest
    )

    family_payload = family_manifest.to_dict()
    family_payload["schema_version"] = "arisekit.physician-family-manifest.v2"
    with pytest.raises(ValueError, match="unsupported physician family"):
        PhysicianFamilyManifest.from_dict(family_payload)

    assignment_payload = assignment_manifest.to_dict()
    assignment_payload["schema_version"] = "arisekit.physician-assignment-manifest.v0"
    with pytest.raises(ValueError, match="unsupported physician assignment"):
        PhysicianAssignmentManifest.from_dict(assignment_payload)

    old_plan_payload = study_design.physician_plan.to_dict()
    old_plan_payload["family_subset_manifest_hash"] = _hash("old-family-subset")
    old_plan_payload["assignment_manifest_hash"] = _hash("old-assignment")
    del old_plan_payload["family_allocation_protocol_hash"]
    del old_plan_payload["family_allocation_seed_hash"]
    del old_plan_payload["assignment_protocol_hash"]
    del old_plan_payload["assignment_seed_hash"]
    with pytest.raises(ValueError, match="physician plan fields are invalid"):
        PhysicianPlan.from_dict(old_plan_payload)


def test_assignment_manifest_rejects_unregistered_companion_variant() -> None:
    study_design = _physician_answering_design()
    specialty_plan = _plan_for_design(study_design)
    family_manifest = _physician_family_manifest(study_design, specialty_plan)
    manifest = _assignment_manifest(study_design, specialty_plan, family_manifest)
    assignments = tuple(
        PhysicianAssignment(
            physician_id=assignment.physician_id,
            case_family_id=assignment.case_family_id,
            variant_id=(
                "family-2-variant-c"
                if assignment.case_family_id == "family-2"
                and assignment.variant_id == "family-2-variant-b"
                else assignment.variant_id
            ),
        )
        for assignment in manifest.assignments
    )
    tampered = PhysicianAssignmentManifest(
        study_design_sha256=study_design.digest,
        plan_sha256=specialty_plan.plan_sha256,
        family_subset_manifest_hash=family_manifest.digest,
        responses_per_variant=2,
        assignments=assignments,
    )
    with pytest.raises(ValueError, match="authoritative companion"):
        tampered.validate_against(
            study_design,
            family_manifest=family_manifest,
            specialty_plan=specialty_plan,
        )


def test_physician_family_topology_tracks_allocator_archetype() -> None:
    design = replace(
        _design(),
        design_id="noharm-physician-topology",
        archetype_id="noharm",
    )
    plan = _plan_for_design(design, archetype=BenchmarkArchetype.NOHARM)
    representative_cell = next(
        cell for cell in plan.cells if cell.track.value == "representative"
    )
    family = PhysicianFamily(
        case_family_id="family-1",
        plan_cell_id=representative_cell.cell_id,
        variant_ids=tuple(f"family-1-slot-{index}" for index in range(5)),
    )
    manifest = PhysicianFamilyManifest(
        study_design_sha256=design.digest,
        plan_sha256=plan.plan_sha256,
        archetype_id="noharm",
        track="representative",
        families=(family,),
    )

    manifest.validate_against(design, plan)

    with pytest.raises(ValueError, match="require exactly 2"):
        PhysicianFamilyManifest(
            study_design_sha256=design.digest,
            plan_sha256=plan.plan_sha256,
            archetype_id="paired-specialty-equity",
            track="representative",
            families=(family,),
        )


@pytest.mark.parametrize(
    ("tier", "representative", "stress"),
    [
        (SampleSizeTier.FEASIBILITY, 30, 18),
        (SampleSizeTier.DESCRIPTIVE_PILOT, 108, 36),
        (SampleSizeTier.COMPARATIVE_STUDY, 400, 80),
        (SampleSizeTier.ILLUSTRATIVE_PILOT_DEFAULT, 108, 36),
        (SampleSizeTier.CUSTOM, 12, 6),
    ],
)
def test_sample_size_options_are_representable(
    tier: SampleSizeTier, representative: int, stress: int
) -> None:
    plan = SampleSizeDesign(
        tier=tier,
        representative_families=representative,
        stress_families=stress,
        model_repetitions_per_variant=3,
        simulation_artifact_hash=_hash(f"{tier.value}-simulation"),
        assumption_manifest_hash=_hash(f"{tier.value}-assumptions"),
    )

    assert SampleSizeDesign.from_dict(plan.to_dict()) == plan


def test_model_repetitions_do_not_replace_case_families() -> None:
    with pytest.raises(ValueError, match="do not replace"):
        SampleSizeDesign(
            tier=SampleSizeTier.CUSTOM,
            representative_families=12,
            stress_families=6,
            model_repetitions_per_variant=5,
            simulation_artifact_hash=_hash("simulation"),
            assumption_manifest_hash=_hash("assumptions"),
            repetitions_replace_families=True,
        )


@pytest.mark.parametrize("value", (1.01, float("inf"), float("nan")))
def test_rate_margins_reject_impossible_or_nonfinite_values(value: float) -> None:
    with pytest.raises(ValueError, match="margin|finite"):
        DecisionMargin(
            value=value,
            unit=MarginUnit.RATE_DIFFERENCE,
            justification="Owners approved this test margin.",
            clinical_approval_hash=_hash("rate-clinical"),
            statistical_approval_hash=_hash("rate-statistical"),
        )


def test_illustrative_pilot_requires_three_model_repetitions() -> None:
    with pytest.raises(ValueError, match="requires three"):
        SampleSizeDesign(
            tier=SampleSizeTier.ILLUSTRATIVE_PILOT_DEFAULT,
            representative_families=108,
            stress_families=36,
            model_repetitions_per_variant=1,
            simulation_artifact_hash=_hash("illustrative-simulation"),
            assumption_manifest_hash=_hash("illustrative-assumptions"),
        )


def test_paired_endpoint_panel_requires_absolute_and_safety_endpoints() -> None:
    design = _design()
    without_absolute = tuple(
        endpoint
        for endpoint in design.endpoints
        if endpoint.kind is not EndpointKind.ABSOLUTE_PERFORMANCE
    )
    multiplicity = MultiplicityPlan(
        method=MultiplicityMethod.DESCRIPTIVE_CI_ONLY,
        endpoint_ids=tuple(endpoint.endpoint_id for endpoint in without_absolute),
        primary_endpoint_ids=tuple(
            endpoint.endpoint_id for endpoint in without_absolute if endpoint.primary
        ),
        confirmatory_claims=False,
        nominal_alpha=None,
        ordering=(),
        rationale="Descriptive only.",
    )

    with pytest.raises(ValueError, match="absolute performance"):
        SpecialtyStudyDesign(
            design_id=design.design_id,
            archetype_id=design.archetype_id,
            physician_plan=design.physician_plan,
            endpoints=without_absolute,
            sample_size=design.sample_size,
            multiplicity=multiplicity,
            approved_parity_decision_rule_hash=(
                design.approved_parity_decision_rule_hash
            ),
            clinical_approval_hash=design.clinical_approval_hash,
            statistical_approval_hash=design.statistical_approval_hash,
            operations_approval_hash=design.operations_approval_hash,
        )


def test_paired_safety_guardrail_must_report_each_variant() -> None:
    payload = _design().to_dict()
    safety = next(
        endpoint
        for endpoint in payload["endpoints"]
        if endpoint["kind"] == EndpointKind.SAFETY_GUARDRAIL.value
    )
    safety["reports_each_variant"] = False

    with pytest.raises(ValueError, match="by-variant severe-error"):
        SpecialtyStudyDesign.from_dict(payload)


def test_paired_primary_relationships_require_approved_margins() -> None:
    payload = _design().to_dict()
    paired = next(
        endpoint
        for endpoint in payload["endpoints"]
        if endpoint["kind"] == EndpointKind.PAIRED_RELATIONSHIP.value
    )
    paired["margin"] = None

    with pytest.raises(ValueError, match="owner-approved margins"):
        SpecialtyStudyDesign.from_dict(payload)


def test_plan_binding_rejects_physician_subset_larger_than_sample() -> None:
    endpoints = _endpoint_panel()
    design = SpecialtyStudyDesign(
        design_id="undersized-physician-study",
        archetype_id="paired-specialty-equity",
        physician_plan=_physician_default(),
        endpoints=endpoints,
        sample_size=SampleSizeDesign(
            tier=SampleSizeTier.CUSTOM,
            representative_families=12,
            stress_families=6,
            model_repetitions_per_variant=3,
            simulation_artifact_hash=_hash("undersized-simulation"),
            assumption_manifest_hash=_hash("undersized-assumptions"),
        ),
        multiplicity=MultiplicityPlan(
            method=MultiplicityMethod.DESCRIPTIVE_CI_ONLY,
            endpoint_ids=tuple(endpoint.endpoint_id for endpoint in endpoints),
            primary_endpoint_ids=tuple(
                endpoint.endpoint_id for endpoint in endpoints if endpoint.primary
            ),
            confirmatory_claims=False,
            nominal_alpha=None,
            ordering=(),
            rationale="This pilot reports confidence intervals without claims.",
        ),
        approved_parity_decision_rule_hash=_hash("undersized-parity-decision-rule"),
        clinical_approval_hash=_hash("undersized-clinical"),
        statistical_approval_hash=_hash("undersized-statistical"),
        operations_approval_hash=_hash("undersized-operations"),
    )

    with pytest.raises(ValueError, match="physician representative family subset"):
        design.validate_against_plan(
            _plan_for_design(
                design,
                representative_families=12,
                stress_families=6,
            )
        )


def test_study_design_cross_checks_registered_comparison_semantics() -> None:
    design = _design()

    design.validate_comparison(
        allocator_archetype_id="paired-specialty-equity",
        registry_archetype_id="paired-equity",
        endpoint_id="invariant-unjustified-discordance",
        margin_unit="rate-difference",
        margin_value=0.05,
        decision_rule_hash=design.approved_parity_decision_rule_hash,
        track="representative",
    )
    design.validate_comparison(
        allocator_archetype_id="paired-specialty-equity",
        registry_archetype_id="paired-equity",
        endpoint_id="severe-error-rate",
        margin_unit="rate-difference",
        margin_value=0.02,
        decision_rule_hash=design.approved_parity_decision_rule_hash,
        track="stress",
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"registry_archetype_id": "noharm"},
            "registry archetype",
        ),
        (
            {"endpoint_id": "invented-endpoint"},
            "not supported",
        ),
        (
            {"margin_unit": "absolute-score"},
            "margin unit",
        ),
        (
            {"margin_value": 0.10},
            "margin value",
        ),
        (
            {"decision_rule_hash": _hash("unapproved-decision-rule")},
            "approved parity decision rule",
        ),
        (
            {
                "endpoint_id": "severe-error-rate",
                "margin_value": 0.02,
            },
            "not an approved primary",
        ),
    ],
)
def test_study_design_rejects_unapproved_comparison_semantics(
    kwargs: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "allocator_archetype_id": "paired-specialty-equity",
        "registry_archetype_id": "paired-equity",
        "endpoint_id": "invariant-unjustified-discordance",
        "margin_unit": "rate-difference",
        "margin_value": 0.05,
        "decision_rule_hash": _design().approved_parity_decision_rule_hash,
        "track": "representative",
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        _design().validate_comparison(**values)


def test_hierarchical_multiplicity_is_distinct_and_ordered() -> None:
    plan = MultiplicityPlan(
        method=MultiplicityMethod.HIERARCHICAL,
        endpoint_ids=("global", "specialty-a", "specialty-b"),
        primary_endpoint_ids=("global", "specialty-a", "specialty-b"),
        confirmatory_claims=True,
        nominal_alpha=0.05,
        ordering=("global", "specialty-a", "specialty-b"),
        rationale="Test the global endpoint before specialty endpoints.",
    )

    assert plan.to_dict()["method"] == "hierarchical"


def test_exploratory_fdr_supports_secondary_endpoint_family() -> None:
    plan = MultiplicityPlan(
        method=MultiplicityMethod.FALSE_DISCOVERY_RATE,
        endpoint_ids=("specialty-a", "specialty-b"),
        primary_endpoint_ids=(),
        confirmatory_claims=False,
        nominal_alpha=0.10,
        ordering=(),
        rationale="Control false discoveries across exploratory secondaries.",
    )

    assert plan.to_dict()["method"] == "false-discovery-rate"
    assert plan.primary_endpoint_ids == ()


@pytest.mark.parametrize(
    "field",
    ("endpoint_ids", "primary_endpoint_ids", "ordering"),
)
def test_multiplicity_loader_rejects_string_instead_of_array(field: str) -> None:
    payload = _design().multiplicity.to_dict()
    payload[field] = "not-an-array"

    with pytest.raises(ValueError, match="must be a sequence"):
        MultiplicityPlan.from_dict(payload)


def test_duplicate_json_keys_fail_closed() -> None:
    payload = _design().canonical_json
    tampered = payload.replace(
        '"design_id":"paired-specialty-pilot"',
        '"design_id":"paired-specialty-pilot","design_id":"other"',
    )

    with pytest.raises(ValueError, match="duplicate JSON key"):
        SpecialtyStudyDesign.from_json(tampered)
