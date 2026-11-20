"""Specialty cell inventories bind reviewed content to exact plan cells."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace

import pytest

from arisekit.authoring.blueprint import (
    AggregationContract,
    AuthoredText,
    BaseCase,
    BenchmarkBlueprint,
    CaseFamily,
    CaseVariant,
    GuidanceContract,
    JudgeContract,
    NamedHash,
    ResponseContract,
    RubricOption,
    SourceRecord,
)
from arisekit.archetype import SpecialtySourcePlanBinding
from arisekit.authoring.content_inventory import (
    CANONICAL_CONTENT_HASHING_CONTRACT_SHA256,
    canonical_family_content_sha256,
    canonical_item_content_sha256,
)
from arisekit.authoring.specialty import (
    AcuityLevel,
    BenchmarkArchetype,
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
    StressMode,
    StressSelectionPolicy,
    materialize_specialty_program,
)
from arisekit.authoring.specialty_inventory import (
    ALLOCATION_BASIS,
    SPECIALTY_CELL_INVENTORY_SCHEMA_VERSION,
    AuthoredItemBinding,
    SpecialtyCellBinding,
    SpecialtyCellInventory,
    validate_cross_track_inventory_isolation,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _draft(value: str) -> AuthoredText:
    return AuthoredText.draft(value, authored_by="model:test-fixture")


def _plan(
    archetype: BenchmarkArchetype = BenchmarkArchetype.NOHARM,
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
        stress_modes=(StressMode.UNJUSTIFIED_DEMOGRAPHIC_CHANGE,),
    )
    spec = SpecialtyProgramSpec(
        program_id=f"cardiology-{archetype.value}",
        clinical_scope=scope,
        clinical_lock=ClinicalLock(
            scope_sha256=scope.scope_sha256,
            clinician_name="Reviewing cardiologist",
            clinician_credential="board-certified cardiologist",
            locked_at="2026-07-24T10:00:00Z",
            approval_reference="clinical-review://cardiology/scope/1",
        ),
        data_authorizations=(
            DataAuthorization(
                id="cardiology-source-authorization",
                source_reference="inventory://cardiology/source",
                data_inventory_sha256=_hash("cardiology-source-inventory"),
                rights_basis=RightsBasis.INSTITUTION_AUTHORIZED,
                authorization_reference="governance://cardiology/approval/1",
                authorization_artifact_sha256=_hash("cardiology-source-authorization"),
                authorized_by="Institutional data owner",
                authorized_at="2026-07-24T09:00:00Z",
                release_scope=ReleaseScope.RESTRICTED,
            ),
        ),
        study_design_hash=_hash("cardiology-study-design"),
        scale=ProgramScale.CUSTOM,
        model_ids=("solver-a",),
        model_repetitions=1,
        archetype=archetype,
        representative_family_target=3,
        stress_family_target=1,
    )
    return materialize_specialty_program(spec)


def _completed_family(
    base_id: str,
    derivatives: int,
    *,
    specialty: str = "cardiology",
    content_token: str | None = None,
) -> CaseFamily:
    token = content_token or base_id
    family = CaseFamily(
        id=base_id,
        base_case=BaseCase(
            presentation=_draft(f"Reviewed cardiology case {token}."),
            reference_recommendations=_draft(f"Reviewed recommendation for {token}."),
            specialty=specialty,
            source_ids=("source-cardiology",),
        ),
        rubric_options=(
            RubricOption(
                id="1",
                action=_draft("Take the clinically reviewed action."),
                category="management",
                score=1,
                harm_of_inaction=True,
                abstraction="harm-of-inaction",
                abstraction_type="harm",
                source_ids=("source-cardiology",),
            ),
        ),
    )
    family = family.submit_clinical_review(
        actor="clinical-editor",
        at="2026-07-24T11:00:00Z",
    )
    family = family.lock_clinical(
        clinician="cardiologist-1",
        at="2026-07-24T12:00:00Z",
    )
    variants = tuple(
        CaseVariant(
            id=f"{base_id}-{index}",
            presentation=_draft(f"Reviewed variant {index} for {token}."),
            category=f"controlled-change-{index}",
            changed_dimensions=(f"dimension-{index}",),
            upstream_revision=family.clinical_revision,
        ).attest(
            clinician="cardiologist-1",
            at="2026-07-24T13:00:00Z",
            rationale="The controlled change preserves the reviewed target.",
            source_ids=("source-cardiology",),
        )
        for index in range(derivatives)
    )
    guidance = GuidanceContract(
        upstream_revision=family.clinical_revision,
        version="1",
        spirit=_draft("Apply the reviewed rubric exactly."),
        source_ids=("source-cardiology",),
    ).lock(
        clinician="cardiologist-1",
        at="2026-07-24T13:00:00Z",
    )
    family = family.set_derivatives(
        variants=variants,
        guidance=guidance,
        actor="clinical-editor",
        at="2026-07-24T13:30:00Z",
    )
    return family.complete_workflow(
        clinician="cardiologist-1",
        at="2026-07-24T14:00:00Z",
    )


def _blueprint(
    archetype: BenchmarkArchetype = BenchmarkArchetype.NOHARM,
    *,
    blueprint_specialty: str = "cardiology",
    family_specialty: str = "cardiology",
    family_ids: tuple[str, ...] = ("Car001", "Car002", "Car003"),
    content_tokens: tuple[str, ...] | None = None,
) -> BenchmarkBlueprint:
    derivatives = 10 if archetype is BenchmarkArchetype.NOHARM else 1
    tokens = content_tokens or family_ids
    assert len(tokens) == len(family_ids)
    prompt = b"judge prompt"
    schema = b'{"type":"object"}'
    blueprint = BenchmarkBlueprint(
        id=f"cardiology-{archetype.value}-blueprint",
        name=f"Cardiology {archetype.value} benchmark",
        version="1.0.0",
        specialty=blueprint_specialty,
        response_contract=ResponseContract(
            system_prompt=None,
            instructions="Answer the reviewed cardiology case.",
            instruction_delivery="user_message_preamble",
        ),
        judge_contract=JudgeContract(
            id="reviewed-judge",
            version="1",
            stages=("extract",),
            prompt_hashes=(NamedHash("prompt", hashlib.sha256(prompt).hexdigest()),),
            schema_hashes=(NamedHash("schema", hashlib.sha256(schema).hexdigest()),),
            settings={"route": "pinned-judge"},
            runtime_dependency_lock_sha256=_hash("judge-runtime"),
        ),
        aggregation_contract=AggregationContract(
            primary_metric="score",
            base_unit="case_family",
            variant_reduction="mean",
            trial_reduction="mean",
            bootstrap_method="cluster",
            bootstrap_iterations=1000,
        ),
        sources=(
            SourceRecord(
                id="source-cardiology",
                title="Authorized cardiology source",
                locator="institution://cardiology/source",
                rights_basis="institution_authorized",
                rights_note="Restricted benchmark authoring use.",
                recorded_by="data-owner",
                recorded_at="2026-07-24T09:00:00Z",
            ),
        ),
        case_families=tuple(
            _completed_family(
                base_id,
                derivatives,
                specialty=family_specialty,
                content_token=token,
            )
            for base_id, token in zip(family_ids, tokens, strict=True)
        ),
        expected_variants_per_base=derivatives,
        strict_noharm_topology=archetype is BenchmarkArchetype.NOHARM,
    )
    blueprint = blueprint.submit_case_review(
        actor="clinical-editor",
        at="2026-07-24T15:00:00Z",
    )
    return blueprint.complete_workflow(
        actor="clinical-editor",
        at="2026-07-24T16:00:00Z",
    )


def _mapping(plan) -> dict[str, str]:
    cells = sorted(
        (
            cell
            for cell in plan.cells
            if cell.specialty is Specialty.CARDIOLOGY
            and cell.track is BenchmarkTrack.REPRESENTATIVE
        ),
        key=lambda cell: cell.cell_id,
    )
    assert [cell.family_count for cell in cells] == [1, 1, 1]
    return {
        family_id: cell.cell_id
        for family_id, cell in zip(
            ("Car001", "Car002", "Car003"),
            cells,
            strict=True,
        )
    }


def _mapping_for_track(
    plan,
    track: BenchmarkTrack,
    family_ids: tuple[str, ...],
) -> dict[str, str]:
    selected_cells = sorted(
        (
            cell
            for cell in plan.cells
            if cell.specialty is Specialty.CARDIOLOGY and cell.track is track
        ),
        key=lambda cell: cell.cell_id,
    )
    cell_ids = tuple(
        cell.cell_id for cell in selected_cells for _ in range(cell.family_count)
    )
    assert len(family_ids) == len(cell_ids)
    return dict(zip(sorted(family_ids), cell_ids, strict=True))


def _reviewed_allocations(
    plan,
    family_to_cell: dict[str, str],
) -> tuple[dict[str, ConditionFamily], dict[str, AcuityLevel]]:
    conditions: dict[str, ConditionFamily] = {}
    acuities: dict[str, AcuityLevel] = {}
    for cell in plan.cells:
        family_ids = sorted(
            family_id
            for family_id, cell_id in family_to_cell.items()
            if cell_id == cell.cell_id
        )
        if not family_ids:
            continue
        condition_values = tuple(
            allocation.condition_family
            for allocation in cell.condition_allocations
            for _ in range(allocation.family_count)
        )
        acuity_values = tuple(
            allocation.acuity
            for allocation in cell.acuity_allocations
            for _ in range(allocation.family_count)
        )
        assert len(family_ids) == len(condition_values) == len(acuity_values)
        conditions.update(zip(family_ids, condition_values, strict=True))
        acuities.update(zip(family_ids, acuity_values, strict=True))
    return conditions, acuities


def _allocation_kwargs(plan, mapping: dict[str, str]) -> dict[str, object]:
    conditions, acuities = _reviewed_allocations(plan, mapping)
    return {
        "family_to_condition_family": conditions,
        "family_to_acuity": acuities,
    }


def _inventory(
    archetype: BenchmarkArchetype = BenchmarkArchetype.NOHARM,
) -> tuple[SpecialtyCellInventory, object, BenchmarkBlueprint]:
    plan = _plan(archetype)
    blueprint = _blueprint(archetype)
    mapping = _mapping(plan)
    inventory = SpecialtyCellInventory.from_reviewed_blueprint(
        plan,
        blueprint,
        specialty=Specialty.CARDIOLOGY,
        track=BenchmarkTrack.REPRESENTATIVE,
        family_to_cell=mapping,
        **_allocation_kwargs(plan, mapping),
        export_manifest_sha256=_hash("export-manifest"),
        export_bundle_sha256=_hash("export-bundle"),
        exported_case_family_ids=("Car001", "Car002", "Car003"),
    )
    return inventory, plan, blueprint


def _track_inventory(
    plan,
    *,
    track: BenchmarkTrack,
    family_ids: tuple[str, ...],
    content_tokens: tuple[str, ...] | None = None,
) -> SpecialtyCellInventory:
    blueprint = _blueprint(
        plan.spec.archetype,
        family_ids=family_ids,
        content_tokens=content_tokens,
    )
    mapping = _mapping_for_track(plan, track, family_ids)
    return SpecialtyCellInventory.from_reviewed_blueprint(
        plan,
        blueprint,
        specialty=Specialty.CARDIOLOGY,
        track=track,
        family_to_cell=mapping,
        **_allocation_kwargs(plan, mapping),
        export_manifest_sha256=_hash(f"{track.value}-{'-'.join(family_ids)}-manifest"),
        export_bundle_sha256=_hash(f"{track.value}-{'-'.join(family_ids)}-bundle"),
        exported_case_family_ids=tuple(sorted(family_ids)),
    )


def test_inventory_binds_exact_plan_blueprint_export_cells_and_topology() -> None:
    inventory, plan, blueprint = _inventory()

    assert inventory.schema_version == SPECIALTY_CELL_INVENTORY_SCHEMA_VERSION
    assert inventory.allocation_basis == ALLOCATION_BASIS
    assert inventory.spec_sha256 == plan.spec.spec_sha256
    assert inventory.plan_sha256 == plan.plan_sha256
    assert inventory.blueprint_sha256 == blueprint.digest
    assert inventory.blueprint_authoring_revision == blueprint.authoring_revision
    assert inventory.export_manifest_sha256 == _hash("export-manifest")
    assert inventory.export_bundle_sha256 == _hash("export-bundle")
    assert (
        inventory.content_hashing_contract_sha256
        == CANONICAL_CONTENT_HASHING_CONTRACT_SHA256
    )
    assert inventory.family_count == 3
    assert inventory.authored_variants_per_family == 11
    assert inventory.authored_variant_count == 33
    assert inventory.family_to_cell == _mapping(plan)
    expected_conditions, expected_acuities = _reviewed_allocations(
        plan,
        _mapping(plan),
    )
    assert inventory.family_to_condition_family == expected_conditions
    assert inventory.family_to_acuity == expected_acuities
    assert all(cell.expected_family_count == 1 for cell in inventory.cells)
    for cell in inventory.cells:
        expected_cell = next(
            item for item in plan.cells if item.cell_id == cell.cell_id
        )
        assert cell.condition_allocations == expected_cell.condition_allocations
        assert cell.acuity_allocations == expected_cell.acuity_allocations
        assert cell.condition_family_histogram == {
            item.condition_family.value: item.family_count
            for item in expected_cell.condition_allocations
        }
        assert cell.acuity_histogram == {
            item.acuity.value: item.family_count
            for item in expected_cell.acuity_allocations
        }
        assert all(
            family.condition_family
            in {
                allocation.condition_family
                for allocation in expected_cell.condition_allocations
            }
            for family in cell.families
        )
        for family in cell.families:
            assert len(family.authored_items) == 11
            assert family.authored_items[0].item_id == family.family_id
            blueprint_family = next(
                item for item in blueprint.case_families if item.id == family.family_id
            )
            assert family.authored_items[0].canonical_content_sha256 == (
                canonical_item_content_sha256(
                    blueprint_family.base_case.presentation.value
                )
            )
    inventory.validate_against(plan, blueprint)

    binding = SpecialtySourcePlanBinding.from_specialty_inventory(
        plan,
        inventory,
        study_design_sha256=plan.spec.study_design_hash,
    )
    assert binding.cell_inventory_sha256 == inventory.inventory_sha256
    assert binding.planned_family_count == inventory.family_count


def test_plan_slice_validation_rejects_stale_plan_identity() -> None:
    inventory, plan, _ = _inventory()
    stale = replace(inventory, plan_sha256=_hash("stale-plan"))

    with pytest.raises(ValueError, match="stale plan digest"):
        stale.validate_plan_slice(plan)

    with pytest.raises(ValueError, match="stale plan digest"):
        SpecialtySourcePlanBinding.from_specialty_inventory(
            plan,
            stale,
            study_design_sha256=plan.spec.study_design_hash,
        )


def test_plan_slice_validation_rejects_stale_cell_allocations() -> None:
    inventory, plan, _ = _inventory()
    first, second, third = inventory.cells
    reassigned_family = replace(
        first.families[0],
        condition_family=second.condition_allocations[0].condition_family,
    )
    stale_cell = replace(
        first,
        condition_allocations=second.condition_allocations,
        families=(reassigned_family,),
    )
    stale = replace(inventory, cells=(stale_cell, second, third))

    with pytest.raises(ValueError, match="stale condition allocations"):
        stale.validate_plan_slice(plan)


@pytest.mark.parametrize(
    "archetype, expected_variants",
    [
        (BenchmarkArchetype.NOHARM, 11),
        (BenchmarkArchetype.PAIRED_SPECIALTY_EQUITY, 2),
    ],
)
def test_inventory_supports_exact_noharm_and_paired_topology(
    archetype: BenchmarkArchetype,
    expected_variants: int,
) -> None:
    inventory, plan, blueprint = _inventory(archetype)
    assert inventory.authored_variants_per_family == expected_variants
    assert all(
        family.authored_variant_count == expected_variants
        for cell in inventory.cells
        for family in cell.families
    )
    inventory.validate_against(plan, blueprint)


def test_constructor_rejects_missing_extra_duplicate_and_wrong_cell_counts() -> None:
    plan = _plan()
    blueprint = _blueprint()
    kwargs = {
        "specialty": Specialty.CARDIOLOGY,
        "track": BenchmarkTrack.REPRESENTATIVE,
        **_allocation_kwargs(plan, _mapping(plan)),
        "export_manifest_sha256": _hash("manifest"),
        "export_bundle_sha256": _hash("bundle"),
        "exported_case_family_ids": ("Car001", "Car002", "Car003"),
    }
    mapping = _mapping(plan)

    with pytest.raises(ValueError, match="exactly cover"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            plan,
            blueprint,
            family_to_cell={
                key: value for key, value in mapping.items() if key != "Car003"
            },
            **kwargs,
        )
    with pytest.raises(ValueError, match="exactly cover"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            plan,
            blueprint,
            family_to_cell={**mapping, "Car999": next(iter(mapping.values()))},
            **kwargs,
        )
    with pytest.raises(ValueError, match="duplicate family-to-cell"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            plan,
            blueprint,
            family_to_cell=(
                ("Car001", mapping["Car001"]),
                ("Car001", mapping["Car002"]),
                ("Car002", mapping["Car002"]),
                ("Car003", mapping["Car003"]),
            ),
            **kwargs,
        )
    collapsed = {family_id: mapping["Car001"] for family_id in mapping}
    with pytest.raises(ValueError, match="requires exactly"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            plan,
            blueprint,
            family_to_cell=collapsed,
            **kwargs,
        )


def test_constructor_requires_exact_reviewed_condition_and_acuity_assignments() -> None:
    plan = _plan()
    blueprint = _blueprint()
    mapping = _mapping(plan)
    conditions, acuities = _reviewed_allocations(plan, mapping)
    common = {
        "plan": plan,
        "blueprint": blueprint,
        "specialty": Specialty.CARDIOLOGY,
        "track": BenchmarkTrack.REPRESENTATIVE,
        "family_to_cell": mapping,
        "export_manifest_sha256": _hash("manifest"),
        "export_bundle_sha256": _hash("bundle"),
        "exported_case_family_ids": ("Car001", "Car002", "Car003"),
    }

    with pytest.raises(ValueError, match="condition-family.*exactly cover"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            **common,
            family_to_condition_family={
                family_id: value
                for family_id, value in conditions.items()
                if family_id != "Car003"
            },
            family_to_acuity=acuities,
        )

    wrong_conditions = dict(conditions)
    wrong_conditions["Car001"] = ConditionFamily.HEART_FAILURE
    with pytest.raises(ValueError, match="exact condition allocation"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            **common,
            family_to_condition_family=wrong_conditions,
            family_to_acuity=acuities,
        )

    wrong_acuities = dict(acuities)
    wrong_acuities["Car001"] = AcuityLevel.ROUTINE
    with pytest.raises(ValueError, match="exact acuity allocation"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            **common,
            family_to_condition_family=conditions,
            family_to_acuity=wrong_acuities,
        )

    with pytest.raises(ValueError, match="invalid value"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            **common,
            family_to_condition_family=conditions,
            family_to_acuity={**acuities, "Car001": "not-an-acuity"},
        )


def test_constructor_rejects_export_family_set_and_wrong_plan_slice() -> None:
    plan = _plan()
    blueprint = _blueprint()
    common = {
        "plan": plan,
        "blueprint": blueprint,
        "specialty": Specialty.CARDIOLOGY,
        "track": BenchmarkTrack.REPRESENTATIVE,
        "family_to_cell": _mapping(plan),
        **_allocation_kwargs(plan, _mapping(plan)),
        "export_manifest_sha256": _hash("manifest"),
        "export_bundle_sha256": _hash("bundle"),
    }
    with pytest.raises(ValueError, match="exported case-family set"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            **common,
            exported_case_family_ids=("Car001", "Car002"),
        )
    with pytest.raises(ValueError, match="duplicates"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            **common,
            exported_case_family_ids=("Car001", "Car002", "Car002"),
        )
    with pytest.raises(ValueError, match="outside the exact plan slice"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            **{
                **common,
                "family_to_cell": {
                    **_mapping(plan),
                    "Car003": next(
                        cell.cell_id
                        for cell in plan.cells
                        if cell.track is BenchmarkTrack.STRESS
                    ),
                },
            },
            exported_case_family_ids=("Car001", "Car002", "Car003"),
        )


def test_constructor_requires_specialty_content_and_review_proof() -> None:
    plan = _plan()
    blueprint = _blueprint()
    common = {
        "plan": plan,
        "specialty": Specialty.CARDIOLOGY,
        "track": BenchmarkTrack.REPRESENTATIVE,
        "family_to_cell": _mapping(plan),
        **_allocation_kwargs(plan, _mapping(plan)),
        "export_manifest_sha256": _hash("manifest"),
        "export_bundle_sha256": _hash("bundle"),
        "exported_case_family_ids": ("Car001", "Car002", "Car003"),
    }
    with pytest.raises(ValueError, match="blueprint specialty"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            blueprint=_blueprint(blueprint_specialty="neurology"),
            **common,
        )
    with pytest.raises(ValueError, match="specialty does not match"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            blueprint=_blueprint(family_specialty="neurology"),
            **common,
        )
    with pytest.raises(ValueError, match="workflow_complete"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            blueprint=replace(
                blueprint,
                review_stage="draft",
                workflow_locked_revision=None,
                review_events=(),
            ),
            **common,
        )


def test_constructor_fails_closed_when_blueprint_cannot_prove_topology() -> None:
    noharm_plan = _plan(BenchmarkArchetype.NOHARM)
    paired_blueprint = _blueprint(BenchmarkArchetype.PAIRED_SPECIALTY_EQUITY)
    noharm_mapping = _mapping(noharm_plan)
    with pytest.raises(ValueError, match="cannot prove the plan topology"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            noharm_plan,
            paired_blueprint,
            specialty=Specialty.CARDIOLOGY,
            track=BenchmarkTrack.REPRESENTATIVE,
            family_to_cell=noharm_mapping,
            **_allocation_kwargs(noharm_plan, noharm_mapping),
            export_manifest_sha256=_hash("manifest"),
            export_bundle_sha256=_hash("bundle"),
            exported_case_family_ids=("Car001", "Car002", "Car003"),
        )

    noharm_blueprint = _blueprint(BenchmarkArchetype.NOHARM)
    non_strict = replace(
        noharm_blueprint,
        strict_noharm_topology=False,
        review_stage="draft",
        workflow_locked_revision=None,
        review_events=(),
    )
    non_strict = non_strict.submit_case_review(
        actor="clinical-editor", at="2026-07-24T17:00:00Z"
    ).complete_workflow(actor="clinical-editor", at="2026-07-24T18:00:00Z")
    with pytest.raises(ValueError, match="strict-NOHARM"):
        SpecialtyCellInventory.from_reviewed_blueprint(
            noharm_plan,
            non_strict,
            specialty=Specialty.CARDIOLOGY,
            track=BenchmarkTrack.REPRESENTATIVE,
            family_to_cell=noharm_mapping,
            **_allocation_kwargs(noharm_plan, noharm_mapping),
            export_manifest_sha256=_hash("manifest"),
            export_bundle_sha256=_hash("bundle"),
            exported_case_family_ids=("Car001", "Car002", "Car003"),
        )


def test_inventory_roundtrip_is_canonical_and_rejects_tampering() -> None:
    inventory, _, _ = _inventory()
    restored = SpecialtyCellInventory.from_json(inventory.canonical_json)
    assert restored == inventory
    assert restored.digest == inventory.inventory_sha256
    assert inventory.canonical_json == json.dumps(
        inventory.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )

    tampered = copy.deepcopy(inventory.to_dict())
    tampered["export"]["bundle_sha256"] = _hash("different-bundle")
    with pytest.raises(ValueError, match="hash mismatch"):
        SpecialtyCellInventory.from_dict(tampered)

    duplicate = inventory.canonical_json.replace(
        '"schema_version":"arisekit.specialty-cell-inventory.v3"',
        '"schema_version":"first","schema_version":"second"',
        1,
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        SpecialtyCellInventory.from_json(duplicate)

    nonfinite = inventory.canonical_json.replace(
        '"family_count":3',
        '"family_count":1e309',
        1,
    )
    with pytest.raises(ValueError, match="non-finite JSON number"):
        SpecialtyCellInventory.from_json(nonfinite)

    allocation_tamper = copy.deepcopy(inventory.to_dict())
    allocation_tamper["cells"][0]["families"][0]["acuity"] = "routine"
    with pytest.raises(ValueError, match="acuity assignments"):
        SpecialtyCellInventory.from_dict(allocation_tamper)

    histogram_tamper = copy.deepcopy(inventory.to_dict())
    histogram_tamper["cells"][0]["acuity_histogram"]["routine"] = 99
    with pytest.raises(ValueError, match="acuity_histogram"):
        SpecialtyCellInventory.from_dict(histogram_tamper)

    noncanonical_nested = copy.deepcopy(inventory.to_dict())
    noncanonical_nested["cells"][0]["families"][0][
        "condition_family"
    ] = "acute coronary syndrome"
    with pytest.raises(ValueError, match="not canonical"):
        SpecialtyCellInventory.from_dict(noncanonical_nested)


def test_explicit_assignment_changes_inventory_identity_without_outcome_inputs() -> (
    None
):
    inventory, plan, blueprint = _inventory()
    swapped = dict(_mapping(plan))
    swapped["Car001"], swapped["Car002"] = swapped["Car002"], swapped["Car001"]
    other = SpecialtyCellInventory.from_reviewed_blueprint(
        plan,
        blueprint,
        specialty=Specialty.CARDIOLOGY,
        track=BenchmarkTrack.REPRESENTATIVE,
        family_to_cell=swapped,
        **_allocation_kwargs(plan, swapped),
        export_manifest_sha256=inventory.export_manifest_sha256,
        export_bundle_sha256=inventory.export_bundle_sha256,
        exported_case_family_ids=inventory.exported_case_family_ids,
    )

    assert other.family_to_cell == swapped
    assert other.inventory_sha256 != inventory.inventory_sha256


def test_direct_duplicate_family_assignment_is_rejected() -> None:
    inventory, _, _ = _inventory()
    first, second, third = inventory.cells
    second_acuity = next(
        item.acuity for item in second.acuity_allocations if item.family_count
    )
    repeated_family = replace(
        first.families[0],
        condition_family=second.condition_allocations[0].condition_family,
        acuity=second_acuity,
    )
    duplicated = SpecialtyCellBinding(
        cell_id=second.cell_id,
        cell_sha256=second.cell_sha256,
        specialty=second.specialty,
        track=second.track,
        expected_family_count=1,
        authored_variants_per_family=second.authored_variants_per_family,
        condition_allocations=second.condition_allocations,
        acuity_allocations=second.acuity_allocations,
        families=(repeated_family,),
    )
    with pytest.raises(ValueError, match="more than one plan cell"):
        replace(inventory, cells=(first, duplicated, third))


def test_cross_track_isolation_accepts_distinct_reviewed_inventories() -> None:
    representative, plan, _ = _inventory()
    stress = _track_inventory(
        plan,
        track=BenchmarkTrack.STRESS,
        family_ids=("Str001",),
    )

    assert (
        representative.cells[0].families[0].canonical_content_sha256
        != stress.cells[0].families[0].canonical_content_sha256
    )
    assert validate_cross_track_inventory_isolation((representative, stress)) is None


def test_cross_track_isolation_rejects_family_id_overlap() -> None:
    representative, plan, _ = _inventory()
    stress = _track_inventory(
        plan,
        track=BenchmarkTrack.STRESS,
        family_ids=("Car001",),
        content_tokens=("stress-distinct-content",),
    )

    with pytest.raises(ValueError, match="overlap on family IDs"):
        validate_cross_track_inventory_isolation((representative, stress))


def test_cross_track_isolation_rejects_authored_item_id_overlap() -> None:
    representative, plan, _ = _inventory()
    stress = _track_inventory(
        plan,
        track=BenchmarkTrack.STRESS,
        family_ids=("Str001",),
    )
    stress_cell = stress.cells[0]
    stress_family = stress_cell.families[0]
    representative_item_id = representative.cells[0].families[0].authored_item_ids[1]
    authored_items = (
        stress_family.authored_items[0],
        AuthoredItemBinding(
            item_id=representative_item_id,
            canonical_content_sha256=stress_family.authored_items[
                1
            ].canonical_content_sha256,
        ),
        *stress_family.authored_items[2:],
    )
    overlapping_family = replace(
        stress_family,
        authored_items=authored_items,
    )
    overlapping_cell = replace(stress_cell, families=(overlapping_family,))
    overlapping_stress = replace(stress, cells=(overlapping_cell,))

    with pytest.raises(ValueError, match="overlap on authored item IDs"):
        validate_cross_track_inventory_isolation((representative, overlapping_stress))


def test_cross_track_isolation_rejects_reidentified_canonical_content() -> None:
    representative, plan, _ = _inventory()
    stress = _track_inventory(
        plan,
        track=BenchmarkTrack.STRESS,
        family_ids=("Str001",),
        content_tokens=("Car001",),
    )
    representative_hashes = {
        family.canonical_content_sha256
        for cell in representative.cells
        for family in cell.families
    }
    stress_hashes = {
        family.canonical_content_sha256
        for cell in stress.cells
        for family in cell.families
    }
    assert representative_hashes & stress_hashes

    with pytest.raises(ValueError, match="overlap on canonical content hashes"):
        validate_cross_track_inventory_isolation((representative, stress))


def test_cross_track_isolation_rejects_one_relabelled_authored_item() -> None:
    representative, plan, _ = _inventory()
    stress = _track_inventory(
        plan,
        track=BenchmarkTrack.STRESS,
        family_ids=("Str001",),
    )
    copied_hash = (
        representative.cells[0].families[0].authored_items[1].canonical_content_sha256
    )
    stress_cell = stress.cells[0]
    stress_family = stress_cell.families[0]
    copied_items = (
        stress_family.authored_items[0],
        replace(
            stress_family.authored_items[1],
            canonical_content_sha256=copied_hash,
        ),
        *stress_family.authored_items[2:],
    )
    copied_family = replace(
        stress_family,
        canonical_content_sha256=canonical_family_content_sha256(
            [item.canonical_content_sha256 for item in copied_items]
        ),
        authored_items=copied_items,
    )
    copied_stress = replace(
        stress,
        cells=(replace(stress_cell, families=(copied_family,)),),
    )

    assert copied_family.authored_items[1].item_id.startswith("Str001")
    with pytest.raises(ValueError, match="canonical item content hashes"):
        validate_cross_track_inventory_isolation((representative, copied_stress))


def test_cross_track_isolation_rejects_ambiguous_collection() -> None:
    representative, _, _ = _inventory()

    with pytest.raises(ValueError, match="duplicate program/specialty/track"):
        validate_cross_track_inventory_isolation((representative, representative))
    with pytest.raises(ValueError, match="must contain"):
        validate_cross_track_inventory_isolation((representative, object()))
    with pytest.raises(ValueError, match="must be a sequence"):
        validate_cross_track_inventory_isolation(None)  # type: ignore[arg-type]
