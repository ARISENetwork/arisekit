"""Primary generation-study contracts are available from the package root."""

from arisekit import (
    AcquisitionEvidence,
    AcquisitionLineage,
    AnalysisReadiness,
    ArchetypeId,
    AuthoredItemBinding,
    BenchmarkBlueprint,
    BenchmarkArchetypeRegistry,
    CampaignArm,
    CampaignModel,
    CampaignResult,
    CampaignSpec,
    CellResultValidator,
    ContentFamilyBinding,
    ContentItemBinding,
    CaseFamily,
    ClinicalReviewReadiness,
    CohortManifest,
    FingerprintStatisticDirection,
    JudgePanel,
    MatchedCohortManifest,
    PackageAsset,
    PackageAssetManifest,
    PackageVerificationError,
    ParityObservation,
    ParityReport,
    ParityReadinessRecord,
    PhysicianFamily,
    PhysicianFamilyManifest,
    PortfolioActionQueue,
    PortfolioOpportunity,
    RunManifest,
    ReferenceSelectionInventory,
    SolverRunAdapterReceipt,
    SolverRunEvidence,
    SourceSimilarityReadiness,
    SpecialtyCellInventory,
    SpecialtySourcePlanBinding,
    SpecialtyStudyDesign,
    SpecialtyProgramSpec,
    SyntheticBenchmarkProgram,
    SyntheticParityInput,
    SyntheticProgramReport,
    VariantSelectionPolicy,
    VariantSlot,
    ResidualSignalValidation,
    StressBenchmarkSpec,
    StressValidationRecord,
    ValidationDecisionRule,
    analyze_stress_validation,
    analyze_synthetic_parity,
    aggregate_synthetic_program_reports,
    builtin_archetype_registry,
    canonical_family_content_sha256,
    canonical_item_content_sha256,
    compare_parity,
    load_portfolio_action_queue,
    match_stress_cohorts,
    materialize_validated_stress_package,
    replay_synthetic_parity_report,
    run_campaign,
    validate_cross_arm_content_isolation,
    validate_cross_track_inventory_isolation,
    validate_synthetic_selection_inventory,
    validate_reference_selection_inventory,
)


def test_generation_study_api_is_importable() -> None:
    symbols = (
        AcquisitionEvidence,
        AcquisitionLineage,
        AnalysisReadiness,
        ArchetypeId,
        AuthoredItemBinding,
        BenchmarkBlueprint,
        BenchmarkArchetypeRegistry,
        CampaignArm,
        CampaignModel,
        CampaignResult,
        CampaignSpec,
        CellResultValidator,
        ContentFamilyBinding,
        ContentItemBinding,
        CaseFamily,
        ClinicalReviewReadiness,
        CohortManifest,
        FingerprintStatisticDirection,
        JudgePanel,
        MatchedCohortManifest,
        PackageAsset,
        PackageAssetManifest,
        PackageVerificationError,
        ParityObservation,
        ParityReport,
        ParityReadinessRecord,
        PhysicianFamily,
        PhysicianFamilyManifest,
        PortfolioActionQueue,
        PortfolioOpportunity,
        RunManifest,
        ReferenceSelectionInventory,
        SolverRunAdapterReceipt,
        SolverRunEvidence,
        SourceSimilarityReadiness,
        SpecialtyCellInventory,
        SpecialtySourcePlanBinding,
        SpecialtyStudyDesign,
        SpecialtyProgramSpec,
        SyntheticBenchmarkProgram,
        SyntheticParityInput,
        SyntheticProgramReport,
        VariantSelectionPolicy,
        VariantSlot,
        ResidualSignalValidation,
        StressBenchmarkSpec,
        StressValidationRecord,
        ValidationDecisionRule,
        analyze_stress_validation,
        analyze_synthetic_parity,
        aggregate_synthetic_program_reports,
        builtin_archetype_registry,
        canonical_family_content_sha256,
        canonical_item_content_sha256,
        compare_parity,
        load_portfolio_action_queue,
        match_stress_cohorts,
        materialize_validated_stress_package,
        replay_synthetic_parity_report,
        run_campaign,
        validate_cross_arm_content_isolation,
        validate_cross_track_inventory_isolation,
        validate_synthetic_selection_inventory,
        validate_reference_selection_inventory,
    )
    assert all(symbol is not None for symbol in symbols)


def test_shipped_and_internal_code_imports_existing_arisekit_modules() -> None:
    import ast
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    offenders = []
    for directory in ("arisekit", "benchmarks/noharm_reference", "internal"):
        for path in sorted((root / directory).rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(), str(path))):
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules = [node.module]
                elif isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                else:
                    continue
                for module in modules:
                    if module.split(".")[0] == "arisekit" and importlib.util.find_spec(module) is None:
                        offenders.append(f"{path.relative_to(root)}:{node.lineno} {module}")
    assert offenders == []
