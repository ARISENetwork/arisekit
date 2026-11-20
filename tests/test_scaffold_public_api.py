"""The deterministic scaffold contract is available from the package root."""

import arisekit

from arisekit import (
    AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION,
    AGENTIC_FHIR_ENV_SCHEMA_VERSION,
    AGENTIC_FHIR_ENVIRONMENT,
    AGENTIC_PASS_CONDITION_SCHEMA_VERSION,
    BUILD_SPEC_SCHEMA_VERSION,
    FHIR_TOOL_CATALOG_VERSION,
    IMAGE_ATTACHMENTS_SCHEMA_VERSION,
    MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION,
    SUPPORTED_BUILD_SPEC_SCHEMA_VERSIONS,
    AgenticFHIRBinding,
    AgenticFHIRSpec,
    AgenticPassCondition,
    BenchmarkScaffoldSpec,
    ImageAttachmentAssetSpec,
    MultimodalImageBinding,
    MultimodalImageSpec,
    MultimodalImageSUT,
    CompatibilityReport,
    ProviderDisclosureAuthorization,
    ProviderDisclosureRequirement,
    RequiredToolCall,
    ScaffoldReceipt,
    RunnableBenchmarkManifest,
    agentic_fhir_binding_from_package,
    check_benchmark,
    generated_bundle_hash,
    load_scaffolded_benchmark,
    multimodal_image_binding_from_package,
    scaffold_benchmark,
)


def test_scaffold_api_is_importable() -> None:
    assert BUILD_SPEC_SCHEMA_VERSION == "arisekit.benchmark-build-spec.v1"
    assert (
        AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION
        == "arisekit.benchmark-build-spec.v2"
    )
    assert MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION == "arisekit.benchmark-build-spec.v3"
    assert SUPPORTED_BUILD_SPEC_SCHEMA_VERSIONS == {
        BUILD_SPEC_SCHEMA_VERSION,
        AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION,
        MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION,
    }
    assert AGENTIC_FHIR_ENV_SCHEMA_VERSION == "arisekit.agentic-fhir-env.v1"
    assert AGENTIC_FHIR_ENVIRONMENT["isolation"] == "per-item-trial"
    assert FHIR_TOOL_CATALOG_VERSION == "arisekit.fhir-tools.v1"
    assert IMAGE_ATTACHMENTS_SCHEMA_VERSION == "arisekit.image-attachments.v1"
    assert AGENTIC_PASS_CONDITION_SCHEMA_VERSION == "arisekit.agentic-pass-condition.v1"
    assert AgenticFHIRBinding is not None
    assert AgenticFHIRSpec is not None
    assert AgenticPassCondition is not None
    assert RequiredToolCall is not None
    assert callable(agentic_fhir_binding_from_package)
    assert callable(multimodal_image_binding_from_package)
    assert ImageAttachmentAssetSpec is not None
    assert MultimodalImageBinding is not None
    assert MultimodalImageSpec is not None
    assert MultimodalImageSUT is not None
    assert BenchmarkScaffoldSpec is not None
    assert CompatibilityReport is not None
    assert ProviderDisclosureAuthorization is not None
    assert ProviderDisclosureRequirement is not None
    assert ScaffoldReceipt is not None
    assert RunnableBenchmarkManifest is not None
    assert callable(scaffold_benchmark)
    assert callable(check_benchmark)
    assert callable(generated_bundle_hash)
    assert callable(load_scaffolded_benchmark)
    assert {
        "BUILD_SPEC_SCHEMA_VERSION",
        "AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION",
        "MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION",
        "SUPPORTED_BUILD_SPEC_SCHEMA_VERSIONS",
        "AGENTIC_FHIR_ENV_SCHEMA_VERSION",
        "AGENTIC_FHIR_ENVIRONMENT",
        "FHIR_TOOL_CATALOG_VERSION",
        "IMAGE_ATTACHMENTS_SCHEMA_VERSION",
        "AGENTIC_PASS_CONDITION_SCHEMA_VERSION",
        "AgenticFHIRBinding",
        "AgenticFHIRSpec",
        "ImageAttachmentAssetSpec",
        "MultimodalImageBinding",
        "MultimodalImageSpec",
        "MultimodalImageSUT",
        "AgenticPassCondition",
        "RequiredToolCall",
        "agentic_fhir_binding_from_package",
        "multimodal_image_binding_from_package",
        "BenchmarkScaffoldSpec",
        "CompatibilityIssue",
        "CompatibilityReport",
        "ProviderDisclosureAuthorization",
        "ProviderDisclosureRequirement",
        "ScaffoldError",
        "ScaffoldLibraryGapError",
        "ScaffoldReceipt",
        "ScaffoldSpecError",
        "check_benchmark",
        "generated_bundle_hash",
        "load_scaffolded_benchmark",
        "scaffold_benchmark",
        "RUNNABLE_MANIFEST_SCHEMA_VERSION",
        "RunnableBenchmarkManifest",
        "load_runnable_manifest",
    }.issubset(arisekit.__all__)
    RequiredToolCall,
    agentic_fhir_binding_from_package,
