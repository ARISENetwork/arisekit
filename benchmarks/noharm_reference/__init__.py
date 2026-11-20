"""Read-only compatibility adapter for the public NOHARM release bundle."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORT_MODULE_BY_NAME = {
    "AggregateComparison": "adapter",
    "AggregateMetric": "adapter",
    "BUNDLE_SCHEMA_VERSION": "export",
    "ENGINEERING_BUNDLE_MANIFEST_SCHEMA_VERSION": "engineering",
    "ENGINEERING_BUNDLE_STATUS": "engineering",
    "ENGINEERING_CANDIDATE_SCHEMA_VERSION": "engineering",
    "ENGINEERING_CANDIDATE_STATUS": "engineering",
    "ENGINEERING_CLAIM_SCOPE": "engineering",
    "ENGINEERING_PROVENANCE_SCHEMA_VERSION": "engineering",
    "GENERATION_LINEAGE_SCHEMA_VERSION": "export",
    "GenerationLineage": "export",
    "MetricDelta": "adapter",
    "NoHarmAssetHashes": "adapter",
    "NoHarmBundleError": "adapter",
    "NoHarmCompatibleBundle": "export",
    "NoHarmCompatibleBundleError": "export",
    "NoHarmEngineeringBundle": "engineering",
    "NoHarmEngineeringBundleError": "engineering",
    "NoHarmExportError": "export",
    "NoHarmReferenceBundle": "adapter",
    "NoHarmSelection": "adapter",
    "PinnedNoHarmAssets": "export",
    "automated_systems_for_candidate": "engineering",
    "compare_aggregate_metrics": "adapter",
    "dependency_lock_sha256": "adapter",
    "export_noharm_bundle": "export",
    "is_judge_dependency_manifest": "adapter",
    "load_aggregate_csv": "adapter",
    "replay_judged_aggregates": "adapter",
}

__all__ = [
    "AggregateComparison",
    "AggregateMetric",
    "BUNDLE_SCHEMA_VERSION",
    "ENGINEERING_BUNDLE_MANIFEST_SCHEMA_VERSION",
    "ENGINEERING_BUNDLE_STATUS",
    "ENGINEERING_CANDIDATE_SCHEMA_VERSION",
    "ENGINEERING_CANDIDATE_STATUS",
    "ENGINEERING_CLAIM_SCOPE",
    "ENGINEERING_PROVENANCE_SCHEMA_VERSION",
    "GENERATION_LINEAGE_SCHEMA_VERSION",
    "GenerationLineage",
    "MetricDelta",
    "NoHarmAssetHashes",
    "NoHarmBundleError",
    "NoHarmCompatibleBundle",
    "NoHarmCompatibleBundleError",
    "NoHarmEngineeringBundle",
    "NoHarmEngineeringBundleError",
    "NoHarmExportError",
    "NoHarmReferenceBundle",
    "NoHarmSelection",
    "PinnedNoHarmAssets",
    "compare_aggregate_metrics",
    "automated_systems_for_candidate",
    "dependency_lock_sha256",
    "export_noharm_bundle",
    "load_aggregate_csv",
    "is_judge_dependency_manifest",
    "replay_judged_aggregates",
]


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULE_BY_NAME.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{module_name}", __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
