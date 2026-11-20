"""Strict contract for the released cohort-pooled NOHARM v2 judge.

The canonical judge is one staged pipeline, not a panel of independent
judges. Its match and review routes are therefore represented by one composite
panel entry whose settings bind the exact pipeline and released assets.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping, Sequence
from typing import Any

from arisekit.common.hashing import strict_canonical_sha256 as sha256_json
from arisekit.common.validate import sha256_hex as _sha256


CANONICAL_NOHARM_CONTRACT_SCHEMA = "arisekit.noharm-v2-judge-contract.v1"
CANONICAL_NOHARM_CONTRACT_ID = "noharm-v2-cohort-pooled-match-review"
CANONICAL_NOHARM_JUDGE_ID = "noharm-v2-canonical"
CANONICAL_NOHARM_COMPOSITE_MODEL = "noharm-v2/cohort-pooled-match-review"
CANONICAL_NOHARM_FAMILY = "google-gemini"
CANONICAL_NOHARM_PROVIDER = "gemini"
CANONICAL_MATCH_MODEL = "gemini/gemini-3-flash-preview"
CANONICAL_MATCH_PROVIDER_MODEL = "gemini-3-flash-preview"
CANONICAL_REVIEW_MODEL = "gemini/gemini-3.5-flash"
CANONICAL_REVIEW_PROVIDER_MODEL = "gemini-3.5-flash"

_SETTINGS_KEYS = {"canonical_pipeline", "canonical_pipeline_sha256"}
_PIPELINE_KEYS = {
    "schema_version",
    "contract_id",
    "judge_version",
    "execution_mode",
    "stages",
    "disabled_stages",
    "judge_assets_sha256",
    "runtime_dependency_lock_sha256",
    "match_prompt_sha256",
    "review_prompt_sha256",
}
_STAGE_KEYS = {
    "stage",
    "provider",
    "model",
    "expected_provider_model",
}


def canonical_noharm_settings(
    *,
    judge_assets_sha256: str,
    runtime_dependency_lock_sha256: str,
    match_prompt_sha256: str,
    review_prompt_sha256: str,
) -> dict[str, Any]:
    """Build hash-bound settings for the exact released v2 match/review path."""
    pipeline = {
        "schema_version": CANONICAL_NOHARM_CONTRACT_SCHEMA,
        "contract_id": CANONICAL_NOHARM_CONTRACT_ID,
        "judge_version": "v2",
        "execution_mode": "cohort-pooled-batch",
        "stages": [
            {
                "stage": "match",
                "provider": CANONICAL_NOHARM_PROVIDER,
                "model": CANONICAL_MATCH_MODEL,
                "expected_provider_model": CANONICAL_MATCH_PROVIDER_MODEL,
            },
            {
                "stage": "review",
                "provider": CANONICAL_NOHARM_PROVIDER,
                "model": CANONICAL_REVIEW_MODEL,
                "expected_provider_model": CANONICAL_REVIEW_PROVIDER_MODEL,
            },
        ],
        "disabled_stages": ["severity", "triage"],
        "judge_assets_sha256": _sha256(
            judge_assets_sha256,
            "judge_assets_sha256",
        ),
        "runtime_dependency_lock_sha256": _sha256(
            runtime_dependency_lock_sha256,
            "runtime_dependency_lock_sha256",
        ),
        "match_prompt_sha256": _sha256(
            match_prompt_sha256,
            "match_prompt_sha256",
        ),
        "review_prompt_sha256": _sha256(
            review_prompt_sha256,
            "review_prompt_sha256",
        ),
    }
    return {
        "canonical_pipeline": pipeline,
        "canonical_pipeline_sha256": sha256_json(pipeline),
    }


def canonical_noharm_panel_entry(
    *,
    judge_assets_sha256: str,
    runtime_dependency_lock_sha256: str,
    match_prompt_sha256: str,
    review_prompt_sha256: str,
) -> dict[str, Any]:
    """Build the one allowed composite panel entry."""
    return {
        "id": CANONICAL_NOHARM_JUDGE_ID,
        "model": CANONICAL_NOHARM_COMPOSITE_MODEL,
        "provider": CANONICAL_NOHARM_PROVIDER,
        "expected_provider_model": CANONICAL_NOHARM_COMPOSITE_MODEL,
        "family": CANONICAL_NOHARM_FAMILY,
        "settings": canonical_noharm_settings(
            judge_assets_sha256=judge_assets_sha256,
            runtime_dependency_lock_sha256=runtime_dependency_lock_sha256,
            match_prompt_sha256=match_prompt_sha256,
            review_prompt_sha256=review_prompt_sha256,
        ),
    }


def validate_canonical_noharm_panel_entry(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and detach one canonical composite panel entry."""
    expected_top = {
        "id": CANONICAL_NOHARM_JUDGE_ID,
        "model": CANONICAL_NOHARM_COMPOSITE_MODEL,
        "provider": CANONICAL_NOHARM_PROVIDER,
        "expected_provider_model": CANONICAL_NOHARM_COMPOSITE_MODEL,
        "family": CANONICAL_NOHARM_FAMILY,
    }
    for field, expected in expected_top.items():
        if value.get(field) != expected:
            raise ValueError(f"canonical NOHARM judge {field} must be {expected!r}")
    settings = value.get("settings")
    if not isinstance(settings, Mapping) or set(settings) != _SETTINGS_KEYS:
        raise ValueError(
            "canonical NOHARM judge settings must contain only "
            "canonical_pipeline and canonical_pipeline_sha256"
        )
    pipeline = settings["canonical_pipeline"]
    if not isinstance(pipeline, Mapping) or set(pipeline) != _PIPELINE_KEYS:
        raise ValueError("canonical NOHARM pipeline fields differ from its contract")
    if pipeline["schema_version"] != CANONICAL_NOHARM_CONTRACT_SCHEMA:
        raise ValueError("canonical NOHARM pipeline schema is unsupported")
    if pipeline["contract_id"] != CANONICAL_NOHARM_CONTRACT_ID:
        raise ValueError("canonical NOHARM pipeline contract id is invalid")
    if pipeline["judge_version"] != "v2":
        raise ValueError("canonical NOHARM judge version must be v2")
    if pipeline["execution_mode"] != "cohort-pooled-batch":
        raise ValueError("canonical NOHARM judge must use cohort-pooled batch mode")
    if pipeline["disabled_stages"] != ["severity", "triage"]:
        raise ValueError("canonical NOHARM severity and triage stages must be disabled")
    stages = pipeline["stages"]
    expected_stages = [
        {
            "stage": "match",
            "provider": CANONICAL_NOHARM_PROVIDER,
            "model": CANONICAL_MATCH_MODEL,
            "expected_provider_model": CANONICAL_MATCH_PROVIDER_MODEL,
        },
        {
            "stage": "review",
            "provider": CANONICAL_NOHARM_PROVIDER,
            "model": CANONICAL_REVIEW_MODEL,
            "expected_provider_model": CANONICAL_REVIEW_PROVIDER_MODEL,
        },
    ]
    if (
        not isinstance(stages, Sequence)
        or isinstance(stages, (str, bytes))
        or list(stages) != expected_stages
    ):
        raise ValueError("canonical NOHARM stages or route pins are invalid")
    for stage in stages:
        if not isinstance(stage, Mapping) or set(stage) != _STAGE_KEYS:
            raise ValueError("canonical NOHARM stage fields differ from the contract")
    for field in (
        "judge_assets_sha256",
        "runtime_dependency_lock_sha256",
        "match_prompt_sha256",
        "review_prompt_sha256",
    ):
        _sha256(pipeline[field], f"canonical NOHARM {field}")
    declared = _sha256(
        settings["canonical_pipeline_sha256"],
        "canonical NOHARM pipeline hash",
    )
    actual = sha256_json(dict(pipeline))
    if not hmac.compare_digest(declared, actual):
        raise ValueError("canonical NOHARM pipeline hash does not match its contract")
    return {
        **expected_top,
        "settings": {
            "canonical_pipeline": dict(pipeline),
            "canonical_pipeline_sha256": declared,
        },
    }


def is_canonical_noharm_panel(
    panel: Sequence[Mapping[str, Any]],
) -> bool:
    """Return whether a normalized panel is the one-entry canonical contract."""
    if len(panel) != 1:
        return False
    try:
        validate_canonical_noharm_panel_entry(panel[0])
    except (TypeError, ValueError):
        return False
    return True


def canonical_noharm_pipeline(
    panel: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Return the validated pipeline payload for a canonical panel."""
    if len(panel) != 1:
        raise ValueError("canonical NOHARM judge panel must contain one entry")
    normalized = validate_canonical_noharm_panel_entry(panel[0])
    return normalized["settings"]["canonical_pipeline"]


def validate_canonical_noharm_assets(
    panel: Sequence[Mapping[str, Any]],
    *,
    judge_assets_sha256: str,
    runtime_dependency_lock_sha256: str,
    match_prompt_sha256: str,
    review_prompt_sha256: str,
) -> None:
    """Bind a canonical panel to the exact validated bundle assets."""
    pipeline = canonical_noharm_pipeline(panel)
    expected = {
        "judge_assets_sha256": _sha256(
            judge_assets_sha256,
            "judge_assets_sha256",
        ),
        "runtime_dependency_lock_sha256": _sha256(
            runtime_dependency_lock_sha256,
            "runtime_dependency_lock_sha256",
        ),
        "match_prompt_sha256": _sha256(
            match_prompt_sha256,
            "match_prompt_sha256",
        ),
        "review_prompt_sha256": _sha256(
            review_prompt_sha256,
            "review_prompt_sha256",
        ),
    }
    for field, digest in expected.items():
        if not hmac.compare_digest(str(pipeline[field]), digest):
            raise ValueError(
                f"canonical NOHARM pipeline {field} conflicts with the bundle"
            )


__all__ = [
    "CANONICAL_MATCH_MODEL",
    "CANONICAL_MATCH_PROVIDER_MODEL",
    "CANONICAL_NOHARM_COMPOSITE_MODEL",
    "CANONICAL_NOHARM_CONTRACT_ID",
    "CANONICAL_NOHARM_CONTRACT_SCHEMA",
    "CANONICAL_NOHARM_FAMILY",
    "CANONICAL_NOHARM_JUDGE_ID",
    "CANONICAL_NOHARM_PROVIDER",
    "CANONICAL_REVIEW_MODEL",
    "CANONICAL_REVIEW_PROVIDER_MODEL",
    "canonical_noharm_panel_entry",
    "canonical_noharm_pipeline",
    "canonical_noharm_settings",
    "is_canonical_noharm_panel",
    "sha256_json",
    "validate_canonical_noharm_assets",
    "validate_canonical_noharm_panel_entry",
]
