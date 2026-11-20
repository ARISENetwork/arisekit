"""Portable benchmark blueprints preserve clinical review dependencies."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from arisekit.authoring.blueprint import (
    AggregationContract,
    AuthoredText,
    BaseCase,
    BenchmarkBlueprint,
    CANONICAL_NOHARM_PERTURBATIONS_PER_BASE,
    CaseFamily,
    CaseVariant,
    GuidanceContract,
    JudgeContract,
    JudgmentState,
    NamedHash,
    OptionGuidance,
    ResponseContract,
    RubricGroup,
    RubricOption,
    SpecialistConsultRule,
    SourceRecord,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _draft(value: str) -> AuthoredText:
    return AuthoredText.draft(value, authored_by="model:generator-v1")


def _draft_family() -> CaseFamily:
    base = BaseCase(
        presentation=_draft("A patient has a severe treatment reaction."),
        reference_recommendations=_draft("Hold treatment pending specialist review."),
        specialty="Allergy",
        source_ids=("source-1",),
    )
    options = (
        RubricOption(
            id="o1",
            action=_draft("Continue treatment without evaluation"),
            category="Medication",
            score=1,
            harm_of_inaction=True,
            harm_abstraction="Failure to respond to a severe reaction",
            abstraction_type="harm",
            source_ids=("source-1",),
        ),
        RubricOption(
            id="o2",
            action=_draft("Hold the next treatment dose"),
            category="Medication",
            score=9,
            source_ids=("source-1",),
            best_in_group=True,
        ),
        RubricOption(
            id="o3",
            action=_draft("Arrange urgent specialist review"),
            category="Follow-up",
            score=8,
            depends_on=("o2",),
            source_ids=("source-1",),
        ),
    )
    return CaseFamily(
        id="allergy-001",
        base_case=base,
        rubric_options=options,
        rubric_groups=(
            RubricGroup(
                id="management",
                name="Immediate management",
                option_ids=("o1", "o2"),
                pick_count=1,
            ),
        ),
        specialist_consults=(
            SpecialistConsultRule(
                consult_type="specialist",
                specialty="Allergy",
                urgency="Urgent",
                option_id="o3",
                harm_type="omission",
                harm_severity="Moderate",
            ),
        ),
    )


def _complete_family_from_draft(
    family: CaseFamily,
    *,
    variant_count: int,
) -> CaseFamily:
    family = family.submit_clinical_review(
        actor="editor", at="2026-07-22T10:00:00Z"
    )
    family = family.lock_clinical(
        clinician="clinician-1", at="2026-07-22T11:00:00Z"
    )
    revision = family.clinical_revision
    variants = tuple(
        CaseVariant(
            id=f"{family.id}-{index}",
            presentation=_draft(
                f"Variant {index} preserves the severe treatment reaction."
            ),
            category="age" if index == 0 else "controlled-perturbation",
            changed_dimensions=("age" if index == 0 else f"dimension-{index}",),
            upstream_revision=revision,
        ).attest(
            clinician="clinician-1",
            at="2026-07-22T12:00:00Z",
            rationale="The controlled change does not alter required management.",
            source_ids=("source-1",),
        )
        for index in range(variant_count)
    )
    guidance = GuidanceContract(
        upstream_revision=revision,
        version="1",
        spirit=_draft("Recognize the need to pause treatment and obtain review."),
        watchouts=(_draft("A conditional future pause is not a present hold."),),
        option_rules=(
            OptionGuidance(
                option_id="o2",
                matching=_draft("Match an explicit pause before the next dose."),
                disqualifiers=(_draft("Do not match continue-with-monitoring alone."),),
                aliases=(
                    AuthoredText.draft(
                        "pause the next dose",
                        authored_by="model:generator-v1",
                        evidence_refs=("source-1",),
                    ),
                ),
                gates=(
                    AuthoredText.draft(
                        "The response must recommend pausing before treatment resumes.",
                        authored_by="model:generator-v1",
                        evidence_refs=("source-1",),
                    ),
                ),
            ),
        ),
        source_ids=("source-1",),
    ).lock(clinician="clinician-1", at="2026-07-22T12:00:00Z")
    family = family.set_derivatives(
        variants=variants,
        guidance=guidance,
        actor="editor",
        at="2026-07-22T12:30:00Z",
    )
    return family.complete_workflow(
        clinician="clinician-1", at="2026-07-22T13:00:00Z"
    )


def _complete_family() -> CaseFamily:
    return _complete_family_from_draft(_draft_family(), variant_count=1)


def _judge() -> JudgeContract:
    return JudgeContract(
        id="noharm-judge",
        version="v2",
        stages=("match", "group", "review", "apply"),
        prompt_hashes=(NamedHash("match", _hash("match prompt")),),
        schema_hashes=(NamedHash("judged", _hash("judged schema")),),
        settings={"match_model": "judge-a", "effort": "minimal"},
    )


def _blueprint(family: CaseFamily) -> BenchmarkBlueprint:
    return BenchmarkBlueprint(
        id="allergy-noharm",
        name="Allergy NOHARM-style benchmark",
        version="0.1.0",
        specialty="Allergy",
        response_contract=ResponseContract(
            system_prompt="Respond as the consulting specialist.",
            instructions="Give a short assessment and numbered recommendations.",
            required_sections=("assessment", "recommendations"),
            max_words=200,
        ),
        judge_contract=_judge(),
        aggregation_contract=AggregationContract(
            primary_metric="f1_weighted",
            base_unit="base_case",
            variant_reduction="mean",
            trial_reduction="mean",
            bootstrap_method="cluster",
            bootstrap_iterations=2000,
            weighting={"severity": True},
        ),
        sources=(
            SourceRecord(
                id="source-1",
                title="Clinical source",
                locator="institution:source-1",
                rights_basis="institution_authorized",
                rights_note="Use is recorded under the local benchmark protocol.",
                recorded_by="editor",
                recorded_at="2026-07-22T09:00:00Z",
                content_hash=_hash("source"),
                release_scope="public",
                release_authorization_hash=_hash("source-release"),
                release_authorized_by="data-owner",
                release_authorized_at="2026-07-22T09:30:00Z",
            ),
        ),
        case_families=(family,),
    )


def test_blueprint_round_trip_and_digest_are_deterministic() -> None:
    family = _complete_family()
    evaluation_contract_hash = _blueprint(family).evaluation_contract_hash
    judgment = JudgmentState(
        input_revision=family.workflow_revision,
        judge_contract_hash=_judge().digest,
        evaluation_contract_hash=evaluation_contract_hash,
        status="complete",
        recorded_at="2026-07-22T14:00:00Z",
        artifacts=(NamedHash("judged-jsonl", _hash("artifact")),),
    )
    family = family.record_judgment(judgment)
    blueprint = _blueprint(family).submit_case_review(
        actor="editor", at="2026-07-22T15:00:00Z"
    )
    blueprint = blueprint.complete_workflow(
        actor="editor", at="2026-07-22T16:00:00Z"
    )

    restored = BenchmarkBlueprint.from_dict(blueprint.to_dict())

    assert restored.canonical_json() == blueprint.canonical_json()
    assert restored.digest == blueprint.digest
    restored_option = restored.case_families[0].rubric_options[0]
    assert restored_option.score == 1
    assert restored_option.harm_of_inaction is True
    assert restored_option.abstraction == "Failure to respond to a severe reaction"
    assert restored.case_families[0].rubric_options[1].best_in_group is True
    assert restored.case_families[0].rubric_options[2].depends_on == ("o2",)
    consult = restored.case_families[0].specialist_consults[0]
    assert consult.option_id == "o3"
    assert consult.harm_type == "omission"
    assert consult.harm_severity == "Moderate"
    guidance_rule = restored.case_families[0].guidance.option_rules[0]
    assert [item.value for item in guidance_rule.aliases] == [
        "pause the next dose"
    ]
    assert [item.value for item in guidance_rule.gates] == [
        "The response must recommend pausing before treatment resumes."
    ]
    assert guidance_rule.aliases[0].status == "clinician_locked"
    assert guidance_rule.gates[0].evidence_refs == ("source-1",)
    assert restored.review_stage == "workflow_complete"


def test_editing_locked_clinical_state_invalidates_all_dependents() -> None:
    family = _complete_family()
    evaluation_contract_hash = _blueprint(family).evaluation_contract_hash
    family = family.record_judgment(
        JudgmentState(
            input_revision=family.workflow_revision,
            judge_contract_hash=_judge().digest,
            evaluation_contract_hash=evaluation_contract_hash,
            status="complete",
            recorded_at="2026-07-22T14:00:00Z",
        )
    )
    old_revision = family.clinical_revision
    edited_base = replace(
        family.base_case,
        presentation=family.base_case.presentation.edit(
            "A patient has a severe delayed treatment reaction.",
            authored_by="clinician-1",
        ),
    )

    edited = family.edit_clinical(
        actor="clinician-1",
        at="2026-07-23T09:00:00Z",
        base_case=edited_base,
    )

    assert edited.clinical_revision != old_revision
    assert edited.review.stage == "draft"
    assert edited.review.invalidation_reason is not None
    assert edited.variants == ()
    assert edited.guidance is None
    assert edited.judgment_state is None
    assert edited.base_case.presentation.status == "draft"
    assert all(option.action.status == "draft" for option in edited.rubric_options)


def test_completed_blueprint_rejects_stale_response_or_judge_contracts() -> None:
    blueprint = _blueprint(_complete_family()).submit_case_review(
        actor="editor",
        at="2026-07-22T15:00:00Z",
    ).complete_workflow(
        actor="editor",
        at="2026-07-22T16:00:00Z",
    )

    with pytest.raises(ValueError, match="workflow lock is stale"):
        replace(
            blueprint,
            response_contract=replace(
                blueprint.response_contract,
                instructions="Changed after review.",
            ),
        )
    with pytest.raises(ValueError, match="workflow lock is stale"):
        replace(
            blueprint,
            judge_contract=replace(blueprint.judge_contract, version="v3"),
        )

    family = _complete_family()
    draft_blueprint = _blueprint(family)
    judged_family = family.record_judgment(
        JudgmentState(
            input_revision=family.workflow_revision,
            judge_contract_hash=draft_blueprint.judge_contract.digest,
            evaluation_contract_hash=draft_blueprint.evaluation_contract_hash,
            status="complete",
            recorded_at="2026-07-22T14:00:00Z",
        )
    )
    judged_blueprint = _blueprint(judged_family)
    with pytest.raises(ValueError, match="stale evaluation contract"):
        replace(
            judged_blueprint,
            response_contract=replace(
                judged_blueprint.response_contract,
                instructions="Changed after judging.",
            ),
        )


def test_lock_and_attestation_metadata_cannot_be_forged_independently() -> None:
    family = _complete_family()
    forged_base = replace(
        family.base_case,
        presentation=replace(
            family.base_case.presentation,
            locked_by="different-clinician",
        ),
    )
    with pytest.raises(ValueError, match="clinical field locks"):
        replace(family, base_case=forged_base)

    variant = family.variants[0]
    with pytest.raises(ValueError, match="attestation actor and time"):
        replace(
            variant,
            presentation=replace(
                variant.presentation,
                locked_at="2026-07-23T00:00:00Z",
            ),
        )


def test_stale_direct_reconstruction_is_rejected() -> None:
    family = _complete_family()
    edited_base = replace(
        family.base_case,
        presentation=family.base_case.presentation.edit(
            "The treatment reaction now occurred two weeks later.",
            authored_by="clinician-1",
        ),
    )

    with pytest.raises(ValueError, match="variant .* is stale"):
        replace(family, base_case=edited_base)


def test_authorship_and_clinical_lock_are_explicit() -> None:
    field = _draft("AI-proposed clinical action")
    assert field.origin == "ai_draft"
    assert field.status == "draft"

    locked = field.lock(clinician="clinician-1", at="2026-07-22T11:00:00Z")
    assert locked.origin == "ai_draft"
    assert locked.status == "clinician_locked"
    assert locked.locked_by == "clinician-1"

    edited = locked.edit("Clinician revision", authored_by="clinician-1")
    assert edited.origin == "human_draft"
    assert edited.status == "draft"
    assert edited.locked_by is None


def test_option_guidance_aliases_and_gates_are_locked_and_backward_compatible() -> None:
    legacy_payload = {
        "option_id": "o2",
        "matching": _draft("Match the action.").to_dict(),
        "disqualifiers": [_draft("Do not match a hypothetical action.").to_dict()],
    }
    legacy = OptionGuidance.from_dict(legacy_payload)

    assert legacy.aliases == ()
    assert legacy.gates == ()
    assert legacy.to_dict() == legacy_payload
    assert legacy.semantic_dict() == {
        "option_id": "o2",
        "matching": "Match the action.",
        "disqualifiers": ["Do not match a hypothetical action."],
    }

    guidance = OptionGuidance(
        option_id="o2",
        matching=_draft("Match the action."),
        aliases=(_draft("perform the action"),),
        gates=(
            _draft("The response must commit to the action."),
            _draft("A hypothetical plan does not pass."),
        ),
    )
    assert not guidance.is_locked

    locked = guidance.lock(
        clinician="clinician-1",
        at="2026-07-22T11:00:00Z",
    )
    assert locked.is_locked
    assert all(
        item.status == "clinician_locked"
        for item in (*locked.aliases, *locked.gates)
    )
    assert locked.semantic_dict()["aliases"] == ["perform the action"]
    assert locked.semantic_dict()["gates"] == [
        "The response must commit to the action.",
        "A hypothetical plan does not pass.",
    ]
    assert OptionGuidance.from_dict(locked.to_dict()) == locked


def test_guidance_alias_and_gate_sources_are_collected_and_required() -> None:
    family = _draft_family().lock_clinical(
        clinician="clinician-1",
        at="2026-07-22T11:00:00Z",
    )
    rule = OptionGuidance(
        option_id="o2",
        matching=_draft("Match the action."),
        aliases=(
            AuthoredText.draft(
                "perform the action",
                authored_by="model:generator-v1",
                evidence_refs=("alias-source",),
            ),
        ),
        gates=(
            AuthoredText.draft(
                "The response must commit to the action.",
                authored_by="model:generator-v1",
                evidence_refs=("gate-source",),
            ),
        ),
    )
    guidance = GuidanceContract(
        upstream_revision=family.clinical_revision,
        version="1",
        spirit=_draft("Reward the clinically indicated action."),
        option_rules=(rule,),
    ).lock(
        clinician="clinician-1",
        at="2026-07-22T12:00:00Z",
    )
    family = family.set_derivatives(
        variants=(),
        guidance=guidance,
        actor="editor",
        at="2026-07-22T12:30:00Z",
    )

    assert {"alias-source", "gate-source"} <= family.source_ids()
    changed_alias = guidance.option_rules[0].aliases[0].edit(
        "carry out the action",
        authored_by="clinician-1",
    ).lock(
        clinician="clinician-1",
        at="2026-07-22T12:00:00Z",
    )
    changed_rule = replace(
        guidance.option_rules[0],
        aliases=(changed_alias,),
    )
    changed_family = replace(
        family,
        guidance=replace(guidance, option_rules=(changed_rule,)),
    )
    assert changed_family.workflow_revision != family.workflow_revision

    with pytest.raises(ValueError, match="unknown sources"):
        _blueprint(family)

    with pytest.raises(ValueError, match="require evidence_refs"):
        GuidanceContract(
            upstream_revision=family.clinical_revision,
            version="1",
            spirit=_draft("Reward the clinically indicated action."),
            option_rules=(
                OptionGuidance(
                    option_id="o2",
                    matching=_draft("Match the action."),
                    aliases=(_draft("perform the action"),),
                ),
            ),
        )


def test_structural_validation_rejects_invalid_rubric_and_sources() -> None:
    with pytest.raises(ValueError, match="1 through 9"):
        replace(_draft_family().rubric_options[0], score=10)

    bad_dependency = replace(
        _draft_family().rubric_options[1], depends_on=("missing",)
    )
    with pytest.raises(ValueError, match="unknown dependencies"):
        replace(
            _draft_family(),
            rubric_options=(
                _draft_family().rubric_options[0],
                bad_dependency,
                _draft_family().rubric_options[2],
            ),
        )

    cyclic_options = (
        replace(_draft_family().rubric_options[0], depends_on=("o2",)),
        replace(_draft_family().rubric_options[1], depends_on=("o1",)),
        _draft_family().rubric_options[2],
    )
    with pytest.raises(ValueError, match="must not contain a cycle"):
        replace(_draft_family(), rubric_options=cyclic_options)

    bad_source_family = replace(
        _draft_family(),
        base_case=replace(_draft_family().base_case, source_ids=("unknown",)),
    )
    with pytest.raises(ValueError, match="unknown sources"):
        _blueprint(bad_source_family)


def test_complete_noharm_blueprint_requires_source_lineage() -> None:
    complete = _blueprint(_complete_family()).submit_case_review(
        actor="editor", at="2026-07-22T15:00:00Z"
    )
    complete = complete.complete_workflow(
        actor="editor", at="2026-07-22T16:00:00Z"
    )

    with pytest.raises(ValueError, match="source ledger"):
        replace(complete, sources=())


def test_workflow_completion_requires_attestation_and_locked_guidance() -> None:
    family = _draft_family().lock_clinical(
        clinician="clinician-1", at="2026-07-22T11:00:00Z"
    )
    variant = CaseVariant(
        id="unreviewed",
        presentation=_draft("A superficially changed case."),
        category="timeline",
        changed_dimensions=("timeline",),
        upstream_revision=family.clinical_revision,
    )
    guidance = GuidanceContract(
        upstream_revision=family.clinical_revision,
        version="1",
        spirit=_draft("Draft guidance"),
    )
    family = family.set_derivatives(
        variants=(variant,),
        guidance=guidance,
        actor="editor",
        at="2026-07-22T12:00:00Z",
    )

    with pytest.raises(ValueError, match="variant to be attested"):
        family.complete_workflow(
            clinician="clinician-1", at="2026-07-22T13:00:00Z"
        )


def test_rubric_option_preserves_general_abstraction_and_legacy_alias() -> None:
    legacy = RubricOption(
        id="legacy",
        action=_draft("Avoid an unsafe action"),
        category="Medication",
        score=2,
        harm_abstraction="Unsafe treatment",
        abstraction_type="harm",
    )
    modern = RubricOption(
        id="legacy",
        action=_draft("Avoid an unsafe action"),
        category="Medication",
        score=2,
        abstraction="Unsafe treatment",
        abstraction_type="harm",
    )

    assert legacy.abstraction == "Unsafe treatment"
    assert modern.harm_abstraction == "Unsafe treatment"
    assert legacy.to_dict() == modern.to_dict()
    assert RubricOption.from_dict(modern.to_dict()) == modern

    with pytest.raises(ValueError, match="disagree"):
        replace(
            modern,
            abstraction="Different label",
            harm_abstraction="Unsafe treatment",
        )


def test_alternative_abstraction_linkage_and_best_in_group_are_validated() -> None:
    group = RubricGroup(
        id="dose-choice",
        name="Dose choice",
        option_ids=("dose-a", "dose-b"),
        pick_count=1,
        pick_rule="min",
    )
    dose_a = RubricOption(
        id="dose-a",
        action=_draft("Use dose A"),
        category="Medication",
        score=8,
        abstraction="Dose choice",
        abstraction_type="alternative",
        best_in_group=True,
    )
    dose_b = RubricOption(
        id="dose-b",
        action=_draft("Use dose B"),
        category="Medication",
        score=8,
        abstraction="Dose choice",
        abstraction_type="alternative",
    )
    family = _draft_family()
    linked = replace(
        family,
        rubric_options=family.rubric_options + (dose_a, dose_b),
        rubric_groups=family.rubric_groups + (group,),
    )

    restored = CaseFamily.from_dict(linked.to_dict())
    assert restored.rubric_options[-2].best_in_group is True
    assert restored.rubric_options[-2].abstraction == "Dose choice"
    assert restored.rubric_options[-2].harm_abstraction is None
    assert restored.rubric_groups[-1].pick_rule == "min"

    unlinked = replace(
        dose_a,
        abstraction="Missing group",
        harm_abstraction="Missing group",
    )
    with pytest.raises(ValueError, match="unknown abstraction group"):
        replace(
            family,
            rubric_options=family.rubric_options + (unlinked,),
        )

    wrong_membership = replace(
        group,
        option_ids=("dose-b",),
    )
    with pytest.raises(ValueError, match="not one of its options"):
        replace(
            family,
            rubric_options=family.rubric_options + (dose_a, dose_b),
            rubric_groups=family.rubric_groups + (wrong_membership,),
        )


def test_specialist_consult_accepts_canonical_shape_and_validates_links() -> None:
    canonical = SpecialistConsultRule.from_dict(
        {
            "type": "emergency",
            "specialty": None,
            "urgency": "Urgent",
            "optionId": "o1",
            "harm": {"type": "commission", "severity": "Severe"},
        }
    )
    assert canonical.consult_type == "emergency"
    assert canonical.specialty is None
    assert canonical.harm_type == "commission"
    assert CaseFamily.from_dict(
        replace(_draft_family(), specialist_consults=(canonical,)).to_dict()
    ).specialist_consults == (canonical,)

    unknown = replace(canonical, option_id="missing")
    with pytest.raises(ValueError, match="unknown option"):
        replace(_draft_family(), specialist_consults=(unknown,))

    wrong_severity = replace(
        _draft_family().specialist_consults[0], harm_severity="Severe"
    )
    with pytest.raises(ValueError, match="imply 'Moderate'"):
        replace(_draft_family(), specialist_consults=(wrong_severity,))

    wrong_zone = replace(
        _draft_family().specialist_consults[0], harm_type="commission"
    )
    with pytest.raises(ValueError, match="commission-harm score zone 1-3"):
        replace(_draft_family(), specialist_consults=(wrong_zone,))

    with pytest.raises(ValueError, match="specialty must be null"):
        replace(canonical, specialty="Emergency medicine")
    with pytest.raises(ValueError, match="urgency must be Urgent"):
        replace(canonical, urgency="Routine")


def test_response_contract_can_deliver_canonical_user_message_preamble() -> None:
    contract = ResponseContract(
        system_prompt=None,
        instructions="Canonical NOHARM response instructions",
        required_sections=("assessment", "recommendations"),
        max_words=200,
        instruction_delivery="user_message_preamble",
    )

    system_prompt, user_prompt = contract.render_prompts("Clinical case text")
    assert system_prompt is None
    assert user_prompt == (
        "Canonical NOHARM response instructions\n\nClinical case text"
    )
    assert ResponseContract.from_dict(contract.to_dict()) == contract

    legacy = ResponseContract.from_dict(
        {
            "system_prompt": "Specialist role",
            "instructions": "Number the recommendations",
        }
    )
    assert legacy.instruction_delivery == "system_message"
    assert legacy.render_prompts("Case") == (
        "Specialist role\n\nNumber the recommendations",
        "Case",
    )


def test_strict_noharm_topology_is_deferred_until_blueprint_completion() -> None:
    partial = replace(_blueprint(_draft_family()), strict_noharm_topology=True)
    assert (
        partial.expected_variants_per_base
        == CANONICAL_NOHARM_PERTURBATIONS_PER_BASE
    )
    assert partial.review_stage == "draft"

    short = replace(_blueprint(_complete_family()), strict_noharm_topology=True)
    short = short.submit_case_review(actor="editor", at="2026-07-22T15:00:00Z")
    with pytest.raises(ValueError, match="requires exactly 10 variants; found 1"):
        short.complete_workflow(actor="editor", at="2026-07-22T16:00:00Z")

    full_family = _complete_family_from_draft(
        _draft_family(),
        variant_count=CANONICAL_NOHARM_PERTURBATIONS_PER_BASE,
    )
    full = replace(_blueprint(full_family), strict_noharm_topology=True)
    full = full.submit_case_review(actor="editor", at="2026-07-22T15:00:00Z")
    full = full.complete_workflow(actor="editor", at="2026-07-22T16:00:00Z")
    restored = BenchmarkBlueprint.from_dict(full.to_dict())

    assert restored.review_stage == "workflow_complete"
    assert restored.strict_noharm_topology is True
    assert restored.expected_variants_per_base == 10
    assert restored.digest == full.digest


def test_strict_noharm_topology_requires_one_harm_of_inaction_per_case() -> None:
    family = _draft_family()
    second_inaction = replace(
        family.rubric_options[1],
        score=2,
        harm_of_inaction=True,
        abstraction="Second harm of inaction",
        harm_abstraction="Second harm of inaction",
        abstraction_type="harm",
    )
    family = replace(
        family,
        rubric_options=(
            family.rubric_options[0],
            second_inaction,
            family.rubric_options[2],
        ),
    )
    family = _complete_family_from_draft(
        family,
        variant_count=CANONICAL_NOHARM_PERTURBATIONS_PER_BASE,
    )
    blueprint = replace(_blueprint(family), strict_noharm_topology=True)
    blueprint = blueprint.submit_case_review(
        actor="editor", at="2026-07-22T15:00:00Z"
    )

    with pytest.raises(ValueError, match="exactly one harm-of-inaction option"):
        blueprint.complete_workflow(actor="editor", at="2026-07-22T16:00:00Z")


def test_noncanonical_topology_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="requires exactly 10 variants"):
        replace(
            _blueprint(_draft_family()),
            strict_noharm_topology=True,
            expected_variants_per_base=5,
        )
    with pytest.raises(ValueError, match="positive integer or null"):
        replace(_blueprint(_draft_family()), expected_variants_per_base=0)
