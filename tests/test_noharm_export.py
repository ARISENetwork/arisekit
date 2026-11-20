"""End-to-end contracts for reviewed blueprint NOHARM exports."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

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
    OptionGuidance,
    ResponseContract,
    RubricGroup,
    RubricOption,
    SourceRecord,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS_ROOT = REPO_ROOT / "benchmarks"
if str(BENCHMARKS_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS_ROOT))

from noharm_reference import (  # noqa: E402
    GenerationLineage,
    NoHarmBundleError,
    NoHarmReferenceBundle,
)
from noharm_reference.export import (  # noqa: E402
    NoHarmCompatibleBundle,
    NoHarmCompatibleBundleError,
    NoHarmExportError,
    PinnedNoHarmAssets,
    export_noharm_bundle,
)


def _hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _hash_text(value: str) -> str:
    return _hash_bytes(value.encode("utf-8"))


def _draft(value: str) -> AuthoredText:
    return AuthoredText.draft(value, authored_by="model:fixture")


def _completed_family(base_id: str) -> CaseFamily:
    family = CaseFamily(
        id=base_id,
        base_case=BaseCase(
            presentation=_draft(f"Baseline presentation for {base_id}."),
            reference_recommendations=_draft(
                f"Reference recommendations for {base_id}."
            ),
            specialty="Allergy",
            source_ids=("source-private",),
        ),
        rubric_options=(
            RubricOption(
                id="1",
                action=_draft("Continue without addressing the urgent finding."),
                category="Counseling",
                score=1,
                harm_of_inaction=True,
                abstraction="Harm of inaction",
                abstraction_type="harm",
                source_ids=("source-private",),
            ),
            RubricOption(
                id="2",
                action=_draft("Arrange the preferred specialist action."),
                category="Follow-up",
                score=9,
                abstraction="action-choice",
                abstraction_type="alternative",
                best_in_group=True,
                source_ids=("source-private",),
            ),
            RubricOption(
                id="3",
                action=_draft("Arrange the acceptable alternative action."),
                category="Follow-up",
                score=8,
                abstraction="Action choice",
                abstraction_type="alternative",
                source_ids=("source-private",),
            ),
        ),
        rubric_groups=(
            RubricGroup(
                id="action-choice",
                name="Action choice",
                option_ids=("2", "3"),
                pick_count=1,
                pick_rule="exact",
            ),
        ),
    )
    family = family.submit_clinical_review(
        actor="editor",
        at="2026-07-22T10:00:00Z",
    )
    family = family.lock_clinical(
        clinician="clinician-1",
        at="2026-07-22T11:00:00Z",
    )
    revision = family.clinical_revision
    variants = tuple(
        CaseVariant(
            id=f"{base_id}-{index}",
            presentation=_draft(f"Perturbed presentation {index} for {base_id}."),
            category=f"Dimension {index}",
            changed_dimensions=(f"dimension-{index}",),
            upstream_revision=revision,
            description=f"Controlled change {index}",
        ).attest(
            clinician="clinician-1",
            at="2026-07-22T12:00:00Z",
            rationale="The controlled change preserves the clinical target.",
            source_ids=("source-private",),
        )
        for index in range(10)
    )
    guidance = GuidanceContract(
        upstream_revision=revision,
        version="1",
        spirit=_draft("Reward explicit recognition of the preferred action."),
        watchouts=(_draft("Do not treat vague monitoring as the action."),),
        option_rules=(
            OptionGuidance(
                option_id="2",
                matching=_draft("Match a clear plan for the preferred action."),
                disqualifiers=(_draft("Do not match a hypothetical plan."),),
                aliases=(
                    AuthoredText.draft(
                        "preferred specialist action",
                        authored_by="model:fixture",
                        evidence_refs=("source-private",),
                    ),
                    AuthoredText.draft(
                        "first-line specialist action",
                        authored_by="model:fixture",
                        evidence_refs=("source-private",),
                    ),
                ),
                gates=(
                    AuthoredText.draft(
                        "The response must commit to arranging the action.",
                        authored_by="model:fixture",
                        evidence_refs=("source-private",),
                    ),
                ),
            ),
        ),
        source_ids=("source-private",),
    ).lock(
        clinician="clinician-1",
        at="2026-07-22T12:00:00Z",
    )
    family = family.set_derivatives(
        variants=variants,
        guidance=guidance,
        actor="editor",
        at="2026-07-22T12:30:00Z",
    )
    return family.complete_workflow(
        clinician="clinician-1",
        at="2026-07-22T13:00:00Z",
    )


def _completed_blueprint() -> BenchmarkBlueprint:
    judge_prompt = b"Extract and match actions."
    judge_schema = b'{"type":"object"}'
    blueprint = BenchmarkBlueprint(
        id="private-allergy-noharm",
        name="Private allergy NOHARM-compatible benchmark",
        version="0.1.0",
        specialty="Allergy",
        response_contract=ResponseContract(
            system_prompt=None,
            instructions="Canonical generated response instructions.",
            instruction_delivery="user_message_preamble",
        ),
        judge_contract=JudgeContract(
            id="noharm-compatible-judge",
            version="v1",
            stages=("extract", "match"),
            prompt_hashes=(
                NamedHash(
                    "extract_match",
                    _hash_bytes(judge_prompt),
                ),
            ),
            schema_hashes=(
                NamedHash(
                    "judged",
                    _hash_bytes(judge_schema),
                ),
            ),
            settings={"match_model": "pinned-judge-route"},
            runtime_dependency_lock_sha256=_hash_text(
                "pinned-runtime-dependencies-v1"
            ),
        ),
        aggregation_contract=AggregationContract(
            primary_metric="F1_weighted",
            base_unit="base_case",
            variant_reduction="mean",
            trial_reduction="mean",
            bootstrap_method="cluster",
            bootstrap_iterations=1000,
        ),
        sources=(
            SourceRecord(
                id="source-private",
                title="Authorized private clinical source",
                locator="institution:private-source",
                rights_basis="institution_authorized",
                rights_note="Use is limited to the authorized private benchmark.",
                recorded_by="editor",
                recorded_at="2026-07-22T09:00:00Z",
                content_hash=_hash_text("private source"),
                release_scope="public",
                release_authorization_hash=_hash_text("source release"),
                release_authorized_by="data-owner",
                release_authorized_at="2026-07-22T09:30:00Z",
            ),
        ),
        case_families=(
            _completed_family("Gen003"),
            _completed_family("Gen001"),
            _completed_family("Gen002"),
        ),
        expected_variants_per_base=10,
        strict_noharm_topology=True,
    )
    blueprint = blueprint.submit_case_review(
        actor="editor",
        at="2026-07-22T15:00:00Z",
    )
    return blueprint.complete_workflow(
        actor="editor",
        at="2026-07-22T16:00:00Z",
    )


def _lineage(
    *,
    family: str = "generator-family",
    returned_model: str = "provider-g/generator-snapshot",
    response_ids: tuple[str, ...] = ("generation-response-1",),
) -> GenerationLineage:
    return GenerationLineage(
        provider="provider-g",
        requested_model="provider-g/generator-route",
        returned_model=returned_model,
        family=family,
        response_ids=response_ids,
        generation_manifest_sha256=_hash_text("generation-manifest"),
        generation_code_sha256=_hash_text("generation-code"),
        generation_input_sha256=_hash_text("generation-input"),
        generated_at="2026-07-22T12:00:00Z",
    )


def _assets(
    *,
    source_revision: str = "fixture-revision-1",
    generation_lineage: GenerationLineage | None = None,
) -> PinnedNoHarmAssets:
    response_prompt = b"Canonical generated response instructions."
    return PinnedNoHarmAssets(
        response_prompt=response_prompt,
        response_prompt_sha256=_hash_bytes(response_prompt),
        source_revision=source_revision,
        runtime_dependency_lock_sha256=_hash_text(
            "pinned-runtime-dependencies-v1"
        ),
        generation_lineage=generation_lineage or _lineage(),
        judge_assets={
            "config.py": b'MATCH_MODEL = "pinned-judge-route"\n',
            "prompts/extract_match.md": b"Extract and match actions.",
            "schemas/judged.schema.json": b'{"type":"object"}',
        },
    )


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_exports_three_reviewed_families_end_to_end(tmp_path: Path):
    output = tmp_path / "generated-noharm"
    bundle = export_noharm_bundle(
        _completed_blueprint(),
        output,
        assets=_assets(),
        access_classification="private",
        expected_base_cases=3,
    )

    assert isinstance(bundle, NoHarmCompatibleBundle)
    assert bundle.base_ids == ("Gen001", "Gen002", "Gen003")
    assert bundle.base_case_count == 3
    assert bundle.row_count == 33
    assert [item.id for item in bundle.select(k=5, base_limit=1)] == [
        "Gen001",
        "Gen001-0",
        "Gen001-1",
        "Gen001-2",
        "Gen001-3",
    ]
    explicit = bundle.selection(k=2, base_ids=["Gen003", "Gen001"])
    assert explicit.base_ids == ("Gen001", "Gen003")
    assert explicit.item_ids == (
        "Gen001",
        "Gen001-0",
        "Gen003",
        "Gen003-0",
    )
    assert bundle.manifest["selection"]["default"] == bundle.selection(5).to_dict()
    assert bundle.manifest["topology"]["rows"] == 33
    assert bundle.manifest["access"]["classification"] == "private"
    dependency_lock = _hash_text("pinned-runtime-dependencies-v1")
    assert bundle.manifest["judge_contract"][
        "runtime_dependency_lock_sha256"
    ] == dependency_lock
    assert bundle.hashes.runtime_dependency_lock_sha256 == dependency_lock
    pins = json.loads((output / "judge" / "pins.json").read_text())
    assert pins["judge_contract"]["runtime_dependency_lock_sha256"] == dependency_lock
    assert not (output / "requirements.txt").exists()
    assert not (output / "judge" / "pyproject.toml").exists()
    lineage_path = output / "provenance" / "generation-lineage.json"
    lineage_payload = json.loads(lineage_path.read_text())
    assert lineage_payload == _lineage().to_dict()
    assert bundle.generation_lineage == _lineage()
    assert bundle.manifest["generation_lineage"] == _lineage().manifest_identity
    assert bundle.manifest["generation_lineage"]["path"] == (
        "provenance/generation-lineage.json"
    )
    assert not (output / "provenance" / "generation-input.json").exists()

    rows = _jsonl(output / "dataset" / "items.jsonl")
    assert "open" not in rows[0]["metadata"]
    assert rows[0]["metadata"]["access_classification"] == "private"
    assert rows[0]["metadata"]["specialty"] == "Allergy"
    assert rows[10]["metadata"]["specialty"] == "Allergy"
    assert rows[0]["metadata"]["source_rights"] == {
        "source-private": "institution_authorized"
    }
    assert len(list((output / "dataset" / "rubrics").glob("*.json"))) == 3
    assert len(list((output / "dataset" / "perturbations").glob("*.json"))) == 33
    assert len(list((output / "guidance").glob("*.yaml"))) == 3
    rubric = json.loads(
        (output / "dataset" / "rubrics" / "Gen001.json").read_text()
    )
    assert rubric["open"] is False
    assert rubric["abstractionGroups"] == [
        {"name": "Action choice", "pickCount": 1, "pickType": "exact"}
    ]
    assert rubric["options"][1]["bestInGroup"] is True
    guidance = json.loads(
        (output / "guidance" / "Gen001.yaml").read_text()
    )
    assert set(guidance["options"]) == {"2"}
    assert guidance["options"]["2"]["aliases"] == [
        "preferred specialist action",
        "first-line specialist action",
    ]
    assert guidance["options"]["2"]["gates"] == [
        "The response must commit to arranging the action."
    ]
    restored_guidance = bundle.blueprint.case_families[0].guidance
    assert restored_guidance is not None
    restored_rule = restored_guidance.option_rules[0]
    assert restored_rule.is_locked
    assert [item.value for item in restored_rule.aliases] == [
        "preferred specialist action",
        "first-line specialist action",
    ]
    assert restored_rule.gates[0].evidence_refs == ("source-private",)
    assert bundle.rubric_for("Gen001-9")["id"] == "Gen001"
    assert len(bundle.hashes.bundle_sha256) == 64

    with pytest.raises(NoHarmBundleError, match="must contain 330 rows"):
        NoHarmReferenceBundle(output)


def test_generation_lineage_is_strict_and_round_trips() -> None:
    lineage = _lineage(response_ids=("response-2", "response-1"))
    assert GenerationLineage.from_dict(lineage.to_dict()) == lineage
    assert len(lineage.digest) == 64

    malformed = lineage.to_dict()
    malformed["unexpected"] = "field"
    with pytest.raises(NoHarmExportError, match="fields do not match"):
        GenerationLineage.from_dict(malformed)

    with pytest.raises(NoHarmExportError, match="must be distinct"):
        replace(lineage, response_ids=("response-1", "response-1"))
    with pytest.raises(NoHarmExportError, match="lowercase SHA-256"):
        replace(lineage, generation_input_sha256="not-a-hash")
    with pytest.raises(NoHarmExportError, match="RFC 3339"):
        replace(lineage, generated_at="2026-07-22")


def test_generation_lineage_changes_bundle_identity_only(tmp_path: Path) -> None:
    first = export_noharm_bundle(
        _completed_blueprint(),
        tmp_path / "lineage-a",
        assets=_assets(generation_lineage=_lineage(returned_model="snapshot-a")),
        access_classification="private",
    )
    second = export_noharm_bundle(
        _completed_blueprint(),
        tmp_path / "lineage-b",
        assets=_assets(generation_lineage=_lineage(returned_model="snapshot-b")),
        access_classification="private",
    )

    assert first.hashes.content_sha256 == second.hashes.content_sha256
    assert first.hashes.data_sha256 == second.hashes.data_sha256
    assert first.hashes.judge_sha256 == second.hashes.judge_sha256
    assert first.hashes.bundle_sha256 != second.hashes.bundle_sha256


def test_export_is_deterministic_idempotent_and_stale_safe(tmp_path: Path):
    blueprint = _completed_blueprint()
    first_path = tmp_path / "first"
    second_path = tmp_path / "second"

    first = export_noharm_bundle(
        blueprint,
        first_path,
        assets=_assets(),
        access_classification="restricted",
    )
    again = export_noharm_bundle(
        blueprint,
        first_path,
        assets=_assets(),
        access_classification="restricted",
    )
    second = export_noharm_bundle(
        blueprint,
        second_path,
        assets=_assets(),
        access_classification="restricted",
    )

    assert first.hashes.bundle_sha256 == again.hashes.bundle_sha256
    assert (
        (first_path / "bundle-manifest.json").read_bytes()
        == (second_path / "bundle-manifest.json").read_bytes()
    )
    manifest_before = (first_path / "bundle-manifest.json").read_bytes()
    with pytest.raises(FileExistsError, match="different content"):
        export_noharm_bundle(
            blueprint,
            first_path,
            assets=_assets(source_revision="fixture-revision-2"),
            access_classification="restricted",
        )
    assert (first_path / "bundle-manifest.json").read_bytes() == manifest_before
    assert second.base_ids == first.base_ids


def test_export_refuses_unreviewed_or_noncanonical_inputs(tmp_path: Path):
    completed = _completed_blueprint()
    draft = replace(
        completed,
        review_stage="case_review",
        workflow_locked_revision=None,
    )
    with pytest.raises(NoHarmExportError, match="workflow_complete"):
        export_noharm_bundle(
            draft,
            tmp_path / "draft",
            assets=_assets(),
            access_classification="private",
        )

    original_family = completed.case_families[0]
    assert original_family.guidance is not None
    short_family = original_family.set_derivatives(
        variants=original_family.variants[:-1],
        guidance=original_family.guidance,
        actor="editor",
        at="2026-07-23T10:00:00Z",
    ).complete_workflow(
        clinician="clinician-1",
        at="2026-07-23T10:30:00Z",
    )
    non_strict = completed.with_case_family(
        short_family,
        actor="editor",
        at="2026-07-23T11:00:00Z",
    )
    non_strict = replace(
        non_strict,
        expected_variants_per_base=None,
        strict_noharm_topology=False,
    )
    non_strict = non_strict.submit_case_review(
        actor="editor",
        at="2026-07-23T11:30:00Z",
    ).complete_workflow(
        actor="editor",
        at="2026-07-23T12:00:00Z",
    )
    with pytest.raises(NoHarmExportError, match="requires exactly 10 variants"):
        export_noharm_bundle(
            non_strict,
            tmp_path / "short",
            assets=_assets(),
            access_classification="private",
        )

    with pytest.raises(NoHarmExportError, match="access_classification"):
        export_noharm_bundle(
            completed,
            tmp_path / "undeclared-access",
            assets=_assets(),
            access_classification="",
        )

    with pytest.raises(
        NoHarmExportError,
        match="runtime dependency lock does not match",
    ):
        export_noharm_bundle(
            completed,
            tmp_path / "mismatched-runtime-lock",
            assets=replace(
                _assets(),
                runtime_dependency_lock_sha256=_hash_text(
                    "different-runtime-dependencies"
                ),
            ),
            access_classification="private",
        )

    unknown_source = replace(
        completed.sources[0],
        rights_basis="unknown",
        release_scope=None,
        release_authorization_hash=None,
        release_authorized_by=None,
        release_authorized_at=None,
    )
    unknown_rights = replace(
        completed,
        sources=(unknown_source,),
        review_stage="case_review",
        workflow_locked_revision=None,
    ).complete_workflow(actor="editor", at="2026-07-23T12:30:00Z")
    with pytest.raises(NoHarmExportError, match="unknown rights"):
        export_noharm_bundle(
            unknown_rights,
            tmp_path / "unknown-rights",
            assets=_assets(),
            access_classification="private",
        )

    private_source = replace(completed.sources[0], release_scope="private")
    private_only = replace(
        completed,
        sources=(private_source,),
        review_stage="case_review",
        workflow_locked_revision=None,
    ).complete_workflow(actor="editor", at="2026-07-23T12:45:00Z")
    with pytest.raises(NoHarmExportError, match="not public"):
        export_noharm_bundle(
            private_only,
            tmp_path / "scope-escalation",
            assets=_assets(),
            access_classification="public",
        )

    mismatched_prompt = replace(
        completed,
        response_contract=replace(
            completed.response_contract,
            instructions="Different response instructions.",
        ),
        review_stage="case_review",
        workflow_locked_revision=None,
    ).complete_workflow(
        actor="editor",
        at="2026-07-23T13:00:00Z",
    )
    with pytest.raises(NoHarmExportError, match="does not match the blueprint"):
        export_noharm_bundle(
            mismatched_prompt,
            tmp_path / "mismatched-prompt",
            assets=_assets(),
            access_classification="private",
        )


def test_compatible_validator_detects_tampering(tmp_path: Path):
    output = tmp_path / "generated-noharm"
    export_noharm_bundle(
        _completed_blueprint(),
        output,
        assets=_assets(),
        access_classification="private",
    )
    rubric_path = output / "dataset" / "rubrics" / "Gen001.json"
    rubric = json.loads(rubric_path.read_text())
    rubric["options"][0]["score"] = 9
    rubric_path.write_text(json.dumps(rubric), encoding="utf-8")

    with pytest.raises(
        NoHarmCompatibleBundleError,
        match="manifest asset bytes do not match inventory",
    ):
        NoHarmCompatibleBundle(output)


def test_compatible_validator_rejects_lineage_manifest_tampering(
    tmp_path: Path,
) -> None:
    output = tmp_path / "generated-noharm"
    export_noharm_bundle(
        _completed_blueprint(),
        output,
        assets=_assets(),
        access_classification="private",
    )
    manifest_path = output / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["generation_lineage"]["family"] = "tampered-family"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        NoHarmCompatibleBundleError,
        match="generation lineage does not match provenance",
    ):
        NoHarmCompatibleBundle(output)
