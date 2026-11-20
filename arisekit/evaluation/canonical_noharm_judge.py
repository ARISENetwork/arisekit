"""Blinded cohort adapter for the released staged NOHARM v2 judge.

This adapter receives only the judge-facing JSONL. It assigns new internal
case identifiers, executes all unfinished rows as one released NOHARM cohort,
and writes the same strict judged-result checkpoint consumed by the parity
handoff verifier.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import math
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from arisekit.common.files import existing_file as _existing_file, write_private_once
from arisekit.common.jsonio import strict_json_object
from arisekit.common.validate import number, positive_int as _positive_int, sha256_hex as _sha256, text
from arisekit.judge_execution import (
    JUDGE_EXECUTION_SCHEMA,
    BlindedJudgeCall,
    BlindedJudgeResponse,
    JudgeExecutionSummary,
    _canonical_json,
    _load_existing_results,
    _load_judge_inputs,
    _result_row,
    _write_new_or_identical,
)
from arisekit.judge_handoff import normalize_judge_panel
from arisekit.evaluation.noharm_judge_contract import (
    CANONICAL_MATCH_MODEL,
    CANONICAL_REVIEW_MODEL,
    canonical_noharm_settings,
    is_canonical_noharm_panel,
    validate_canonical_noharm_assets,
)
from arisekit.run_manifest import sha256_digest

try:
    from noharm_reference import (
        NoHarmReferenceBundle,
        is_judge_dependency_manifest,
    )
except ModuleNotFoundError:  # Repository source layout.
    from benchmarks.noharm_reference import (  # type: ignore[no-redef]
        NoHarmReferenceBundle,
        is_judge_dependency_manifest,
    )


CANONICAL_ADAPTER_ID = "arisekit.canonical-noharm-v2-batch.v1"
_EXECUTION_SPEC_SCHEMA = "arisekit.noharm-parity-judge-execution-spec.v1"
_LEDGER_SCHEMA = "arisekit.noharm-v2-provider-job.v1"
OPEN30_CANARY_SCHEMA = "arisekit.noharm-open30-provider-canary.v1"
OPEN30_JUDGE_MANIFEST_SCHEMA = "arisekit.noharm-open30-judge-manifest.v1"


@dataclass(frozen=True)
class _InternalCase:
    internal_id: str
    source: Mapping[str, Any]
    rubric: dict[str, Any]
    guidance: Any


def execute_open30_judge_canary(
    *,
    stage: str,
    reference_bundle_path: str | Path,
    output_path: str | Path,
    execute_live: bool,
    caller: Any | None = None,
) -> dict[str, Any]:
    """Run one provider-identity canary for a pinned canonical judge stage."""
    if not execute_live:
        raise ValueError("judge canary requires the explicit --execute-live flag")
    bundle = NoHarmReferenceBundle(reference_bundle_path)
    settings = _canonical_settings_from_bundle(bundle)
    pipeline = settings["canonical_pipeline"]
    stages = {record["stage"]: record for record in pipeline["stages"]}
    if stage not in stages:
        raise ValueError("judge canary stage must be match or review")
    configured = stages[stage]
    if caller is None:
        if not os.environ.get("GEMINI_API_KEY"):
            raise RuntimeError(
                "GEMINI_API_KEY is not present in the process environment"
            )
        observed_model, response_id = _call_gemini_canary(configured["model"])
    else:
        result = caller(configured["model"], stage)
        if (
            isinstance(result, (str, bytes))
            or not isinstance(result, Sequence)
            or len(result) != 2
        ):
            raise ValueError(
                "judge canary caller must return observed model and response id"
            )
        observed_model = _text(result[0], "canary observed model")
        response_id = _text(result[1], "canary response id")
    if observed_model != configured["expected_provider_model"]:
        raise ValueError(
            f"judge {stage} canary returned unexpected model {observed_model!r}"
        )
    runtime_sha256 = _stage_runtime_sha256(
        bundle,
        settings=settings,
        stage=configured,
    )
    payload = {
        "schema_version": OPEN30_CANARY_SCHEMA,
        "kind": "judge",
        "stage": stage,
        "provider": configured["provider"],
        "expected_provider_model": configured["expected_provider_model"],
        "observed_provider_model": observed_model,
        "status": "passed",
        "response_id_sha256": hashlib.sha256(response_id.encode("utf-8")).hexdigest(),
        "runtime_sha256": runtime_sha256,
    }
    _write_json_create_once(_output_path(output_path), payload)
    return payload


def build_open30_judge_manifest(
    *,
    pilot_path: str | Path,
    reference_bundle_path: str | Path,
    campaign_summary_path: str | Path,
    candidate_bundle_manifest_path: str | Path,
    match_canary_path: str | Path,
    review_canary_path: str | Path,
    response_count: int,
    conversion_judge_ids: Sequence[str],
    output_path: str | Path,
) -> dict[str, Any]:
    """Verify stage canaries and build the decision evaluator's judge manifest."""
    pilot_file = _existing_file(pilot_path, "pilot configuration")
    reference_bundle = NoHarmReferenceBundle(reference_bundle_path)
    campaign_file = _existing_file(campaign_summary_path, "campaign summary")
    bundle_file = _existing_file(
        candidate_bundle_manifest_path,
        "candidate bundle manifest",
    )
    pilot = _load_json_object(pilot_file)
    campaign = _load_json_object(campaign_file)
    bundle_manifest = _load_json_object(bundle_file)
    if campaign.get("complete") is not True:
        raise ValueError("judge manifest requires a complete campaign")
    count = _positive_int(response_count, "response_count")
    if count != 3600:
        raise ValueError("NOHARM open-30 judge manifest requires 3,600 responses")
    if _campaign_response_count(campaign) != count:
        raise ValueError("campaign response count does not match the judge manifest")
    configured_judge = pilot.get("canonical_judge")
    if not isinstance(configured_judge, Mapping):
        raise ValueError("pilot has no canonical_judge contract")
    configured_stages = configured_judge.get("stages")
    if not isinstance(configured_stages, list):
        raise ValueError("pilot canonical_judge stages must be a list")
    configured_by_name = {
        _text(record.get("stage"), "pilot judge stage"): record
        for record in configured_stages
        if isinstance(record, Mapping)
    }
    if set(configured_by_name) != {"match", "review"}:
        raise ValueError("pilot canonical_judge must contain match and review")
    settings = _canonical_settings_from_bundle(reference_bundle)
    canonical_by_name = {
        record["stage"]: record for record in settings["canonical_pipeline"]["stages"]
    }
    if configured_by_name != canonical_by_name:
        raise ValueError(
            "pilot canonical_judge stages conflict with the reference bundle contract"
        )
    stage_paths = {
        "match": _existing_file(match_canary_path, "match canary"),
        "review": _existing_file(review_canary_path, "review canary"),
    }
    stage_records: list[dict[str, Any]] = []
    stage_references: list[dict[str, Any]] = []
    for stage in ("match", "review"):
        path = stage_paths[stage]
        canary = _load_json_object(path)
        _validate_open30_canary(
            canary,
            stage=stage,
            configured=configured_by_name[stage],
            expected_runtime_sha256=_stage_runtime_sha256(
                reference_bundle,
                settings=settings,
                stage=canonical_by_name[stage],
            ),
        )
        stage_records.append(canary)
        stage_references.append(
            {
                "stage": stage,
                "canary": {
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                },
            }
        )
    judge_contract = bundle_manifest.get("judge_contract")
    if not isinstance(judge_contract, Mapping):
        raise ValueError("candidate bundle manifest has no judge_contract")
    ids = tuple(_text(value, "conversion judge id") for value in conversion_judge_ids)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("conversion judge ids must be non-empty and unique")
    if ids != ("noharm-v2-canonical",):
        raise ValueError(
            "canonical NOHARM conversion must use only noharm-v2-canonical"
        )
    payload = {
        "schema_version": OPEN30_JUDGE_MANIFEST_SCHEMA,
        "pilot_configuration_sha256": hashlib.sha256(
            pilot_file.read_bytes()
        ).hexdigest(),
        "campaign_summary_sha256": hashlib.sha256(
            campaign_file.read_bytes()
        ).hexdigest(),
        "candidate_bundle_manifest_sha256": hashlib.sha256(
            bundle_file.read_bytes()
        ).hexdigest(),
        "canonical_judge_sha256": sha256_digest(configured_judge),
        "judge_contract_digest": _sha256(
            judge_contract.get("digest"),
            "candidate judge contract digest",
        ),
        "complete": True,
        "response_count": count,
        "conversion_judge_ids": list(ids),
        "stages": stage_references,
        "judge_runtime_sha256": sha256_digest(
            sorted(stage_records, key=lambda record: record["stage"])
        ),
    }
    _write_json_create_once(_output_path(output_path), payload)
    return payload


def execute_canonical_noharm_judge(
    judge_input_path: str | Path,
    *,
    judge_execution_spec_path: str | Path,
    reference_bundle_path: str | Path,
    cache_root: str | Path,
    output_path: str | Path,
    max_cost_usd: float,
    max_calls: int,
    execute_live: bool,
    judge_module: Any | None = None,
) -> JudgeExecutionSummary:
    """Run the exact canonical match/review cohort with checkpoint/resume."""
    if not execute_live:
        raise ValueError(
            "canonical NOHARM judge execution requires the explicit "
            "--execute-live flag"
        )
    input_path = _existing_file(judge_input_path, "judge input")
    spec_path = _existing_file(judge_execution_spec_path, "judge execution spec")
    bundle = NoHarmReferenceBundle(reference_bundle_path)
    cache = _directory_path(cache_root, "judge cache")
    output = _output_path(output_path)
    if output in {input_path, spec_path}:
        raise ValueError("judge output must differ from judge input and execution spec")
    if _paths_overlap(cache, bundle.root):
        raise ValueError("judge cache must be path-disjoint from the reference bundle")
    if output == bundle.root or bundle.root in output.parents:
        raise ValueError("judge output must not be written into the reference bundle")
    if output == cache or cache in output.parents:
        raise ValueError("strict judge output must be outside the released-stage cache")
    if cache in input_path.parents or cache in spec_path.parents:
        raise ValueError("judge cache must not contain frozen judge inputs")
    budget = _positive_number(max_cost_usd, "max_cost_usd")
    call_cap = _positive_int(max_calls, "max_calls")

    input_bytes = input_path.read_bytes()
    input_rows = _load_judge_inputs(input_bytes, input_path)
    input_sha256 = hashlib.sha256(input_bytes).hexdigest()
    spec = _load_json_object(spec_path)
    if set(spec) != {
        "schema_version",
        "judge_input_sha256",
        "judge_panel",
        "judge_runtime_hash",
    }:
        raise ValueError("judge execution spec fields do not match its schema")
    if spec["schema_version"] != _EXECUTION_SPEC_SCHEMA:
        raise ValueError("unsupported judge execution spec schema")
    if spec["judge_input_sha256"] != input_sha256:
        raise ValueError("judge input does not match the execution spec")
    panel_value = spec["judge_panel"]
    if not isinstance(panel_value, list):
        raise ValueError("judge execution spec judge_panel must be a list")
    panel = normalize_judge_panel(panel_value)
    if not is_canonical_noharm_panel(panel):
        raise ValueError(
            "canonical NOHARM execution requires the one-entry staged contract"
        )
    runtime_hash = _sha256(spec["judge_runtime_hash"], "judge runtime hash")
    if _judge_runtime_digest(bundle) != runtime_hash:
        raise ValueError(
            "reference bundle judge runtime does not match the execution spec"
        )
    _validate_bundle_contract(panel, bundle)

    panel_record = panel[0]
    adapter_code_hash = sha256_digest(
        {
            "adapter_source_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "adapter_id": CANONICAL_ADAPTER_ID,
            "judge_runtime_hash": runtime_hash,
            "pipeline_sha256": panel_record["settings"]["canonical_pipeline_sha256"],
        }
    )
    execution_manifest = {
        "schema_version": JUDGE_EXECUTION_SCHEMA,
        "judge_input_sha256": input_sha256,
        "judge_panel": list(panel),
        "judge_runtime_hash": runtime_hash,
        "adapters": {
            panel_record["id"]: {
                "adapter_id": CANONICAL_ADAPTER_ID,
                "code_sha256": adapter_code_hash,
            }
        },
        "max_cost_usd": budget,
        "max_calls": call_cap,
    }
    manifest_bytes = (_canonical_json(execution_manifest) + "\n").encode("utf-8")
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = output.with_name(output.name + ".execution.json")
    _write_new_or_identical(manifest_path, manifest_bytes)

    input_by_id = {row["opaque_id"]: row for row in input_rows}
    panel_by_id = {panel_record["id"]: panel_record}
    existing = _load_existing_results(
        output,
        input_by_id=input_by_id,
        panel_by_id=panel_by_id,
        judge_runtime_hash=runtime_hash,
        execution_digest=manifest_digest,
    )
    expected = {(row["opaque_id"], panel_record["id"]) for row in input_rows}
    if set(existing) - expected:
        raise ValueError("judge checkpoint contains identities outside the input")
    spent_before = sum(
        float(row["judge_provenance"]["cost_usd"]) for row in existing.values()
    )
    if spent_before > budget:
        raise ValueError("existing judge checkpoint exceeds its cost ceiling")
    if len(existing) == len(expected):
        return JudgeExecutionSummary(
            output_path=output,
            manifest_path=manifest_path,
            manifest_digest=manifest_digest,
            expected=len(expected),
            completed=len(existing),
            skipped=len(existing),
            calls_made=0,
            cost_usd=spent_before,
            complete=True,
            budget_exhausted=False,
        )

    internal = tuple(
        case
        for case in _internal_cases(input_rows)
        if (case.source["opaque_id"], panel_record["id"]) not in existing
    )
    cache.mkdir(parents=True, exist_ok=True)
    ledger_path = cache / "provider-jobs.jsonl"
    ledger = _load_job_ledger(
        ledger_path,
        input_sha256=input_sha256,
        pipeline_sha256=panel_record["settings"]["canonical_pipeline_sha256"],
    )
    if sum(int(record["item_count"]) for record in ledger) > call_cap:
        raise ValueError("provider job ledger already exceeds the call ceiling")

    module = (
        judge_module
        if judge_module is not None
        else _load_released_judge_module(bundle.root / "judge")
    )
    if judge_module is None and not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY is not present in the process environment")
    judged_path = cache / "canonical-judged.jsonl"
    stage_jobs, summary = _run_released_pipeline(
        module,
        cases=internal,
        bundle=bundle,
        cache=cache,
        judged_path=judged_path,
        ledger_path=ledger_path,
        ledger=ledger,
        input_sha256=input_sha256,
        pipeline_sha256=panel_record["settings"]["canonical_pipeline_sha256"],
        max_calls=call_cap,
    )
    ledger_calls = sum(int(record["item_count"]) for record in stage_jobs)
    total_calls = _summary_calls(summary, default=ledger_calls)
    total_cost = _summary_cost(summary)
    if total_calls > call_cap:
        raise ValueError("canonical NOHARM judge exceeded its call ceiling")
    if total_calls and total_cost <= 0:
        raise ValueError(
            "canonical NOHARM judge cost is unknown; refusing to bypass "
            "the cost ceiling"
        )
    if total_cost > budget:
        raise ValueError("canonical NOHARM judge exceeded its cost ceiling")
    provider_ids = _provider_ids(stage_jobs, summary)
    judged = _load_released_results(judged_path, internal)
    if set(judged) != {case.internal_id for case in internal}:
        raise ValueError(
            "released NOHARM judge did not return exact unfinished coverage"
        )

    remaining_cost = total_cost - spent_before
    if remaining_cost < -1e-9:
        raise ValueError(
            "existing judged-result cost exceeds released pipeline provenance"
        )
    per_row_cost = max(0.0, remaining_cost) / len(internal)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        for case in internal:
            source = case.source
            call = BlindedJudgeCall(
                judge_id=panel_record["id"],
                judge_config=panel_record,
                opaque_id=str(source["opaque_id"]),
                binding_digest=str(source["binding_digest"]),
                response_sha256=str(source["response_sha256"]),
                case=dict(source["case"]),
                response=source["response"],
                max_cost_usd_remaining=budget,
            )
            response = BlindedJudgeResponse(
                metrics=judged[case.internal_id],
                provider=panel_record["provider"],
                model=panel_record["model"],
                provider_model=panel_record["expected_provider_model"],
                provider_response_ids=provider_ids,
                cost_usd=per_row_cost,
            )
            result = _result_row(
                call,
                response,
                expected=panel_record,
                judge_runtime_hash=runtime_hash,
                execution_digest=manifest_digest,
            )
            handle.write(_canonical_json(result) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            existing[(call.opaque_id, call.judge_id)] = result

    complete = set(existing) == expected
    return JudgeExecutionSummary(
        output_path=output,
        manifest_path=manifest_path,
        manifest_digest=manifest_digest,
        expected=len(expected),
        completed=len(existing),
        skipped=len(expected) - len(internal),
        calls_made=total_calls,
        cost_usd=total_cost,
        complete=complete,
        budget_exhausted=not complete,
    )


def _run_released_pipeline(
    module: Any,
    *,
    cases: Sequence[_InternalCase],
    bundle: NoHarmReferenceBundle,
    cache: Path,
    judged_path: Path,
    ledger_path: Path,
    ledger: list[dict[str, Any]],
    input_sha256: str,
    pipeline_sha256: str,
    max_calls: int,
) -> tuple[list[dict[str, Any]], Any]:
    responses = [
        {
            "id": case.internal_id,
            "trial": 1,
            "response": case.source["response"],
        }
        for case in cases
    ]
    rubrics = {case.internal_id: case.rubric for case in cases}
    private_assets = cache / "blinded-assets"
    rubric_dir = private_assets / "rubrics"
    guidance_dir = private_assets / "guidance"
    rubric_dir.mkdir(parents=True, exist_ok=True)
    guidance_dir.mkdir(parents=True, exist_ok=True)
    for case in cases:
        _write_private_json(rubric_dir / f"{case.internal_id}.json", case.rubric)
        _write_private_json(guidance_dir / f"{case.internal_id}.yaml", case.guidance)

    judge_config = module.JudgeConfig(
        cache_root=cache / "released-cache",
        match_judge=CANONICAL_MATCH_MODEL,
        match_prompt=bundle.root / "judge" / "prompts" / "extract_match.md",
        severity_judge=None,
        review_judge=CANONICAL_REVIEW_MODEL,
        review_prompt=(bundle.root / "judge" / "prompts" / "global_match_review.md"),
        triage_path=None,
        triage_judge=None,
        rubric_dir=rubric_dir,
        mode="batch",
    )
    instrumentation = _BatchInstrumentation(
        module=module,
        ledger_path=ledger_path,
        ledger=ledger,
        input_sha256=input_sha256,
        pipeline_sha256=pipeline_sha256,
        max_calls=max_calls,
    )
    instrumentation.install(guidance_dir)
    try:
        summary = module.judge_responses(
            model_name="blinded-cohort",
            responses=responses,
            rubrics=rubrics,
            config=judge_config,
            judged_path=judged_path,
        )
    finally:
        instrumentation.restore()
    combined = _load_job_ledger(
        ledger_path,
        input_sha256=input_sha256,
        pipeline_sha256=pipeline_sha256,
    )
    return combined, summary


class _BatchInstrumentation:
    def __init__(
        self,
        *,
        module: Any,
        ledger_path: Path,
        ledger: list[dict[str, Any]],
        input_sha256: str,
        pipeline_sha256: str,
        max_calls: int,
    ):
        self.module = module
        self.ledger_path = ledger_path
        self.ledger = ledger
        self.input_sha256 = input_sha256
        self.pipeline_sha256 = pipeline_sha256
        self.max_calls = max_calls
        self.batch_runner: Any | None = None
        self.match_helpers: Any | None = None
        self.original_submit: Any | None = None
        self.original_guidance: Any | None = None
        self.current_stage = "unknown"

    def install(self, guidance_dir: Path) -> None:
        name = getattr(self.module, "__name__", "")
        try:
            self.batch_runner = importlib.import_module(f"{name}.batch_runner")
            self.match_helpers = importlib.import_module(f"{name}.stages.match_helpers")
        except (ImportError, AttributeError):
            return
        self.original_submit = self.batch_runner.submit_batch
        self.original_guidance = self.match_helpers.GUIDANCE_DIR
        self.match_helpers.GUIDANCE_DIR = guidance_dir

        def tracked_submit(model_id, items, schema, **kwargs):
            prior_calls = sum(int(record["item_count"]) for record in self.ledger)
            if prior_calls + len(items) > self.max_calls:
                raise ValueError("canonical NOHARM judge would exceed its call ceiling")
            job_id = self.original_submit(model_id, items, schema, **kwargs)
            record = {
                "schema_version": _LEDGER_SCHEMA,
                "input_sha256": self.input_sha256,
                "pipeline_sha256": self.pipeline_sha256,
                "stage": self.current_stage,
                "provider": "gemini",
                "requested_model": model_id,
                "provider_job_id": str(job_id),
                "item_count": len(items),
            }
            _append_job(self.ledger_path, record)
            self.ledger.append(record)
            return job_id

        original_resumable = self.batch_runner._resumable_batch_call

        def tracked_resumable(**kwargs):
            previous = self.current_stage
            self.current_stage = str(kwargs.get("stage", "unknown"))
            try:
                return original_resumable(**kwargs)
            finally:
                self.current_stage = previous

        self.batch_runner.submit_batch = tracked_submit
        self.batch_runner._resumable_batch_call = tracked_resumable
        self.original_resumable = original_resumable

    def restore(self) -> None:
        if self.batch_runner is not None and self.original_submit is not None:
            self.batch_runner.submit_batch = self.original_submit
            self.batch_runner._resumable_batch_call = self.original_resumable
        if self.match_helpers is not None and self.original_guidance is not None:
            self.match_helpers.GUIDANCE_DIR = self.original_guidance


def _internal_cases(rows: Sequence[Mapping[str, Any]]) -> tuple[_InternalCase, ...]:
    cases: list[_InternalCase] = []
    for index, row in enumerate(rows, start=1):
        case_value = row["case"]
        if not isinstance(case_value, Mapping):
            raise ValueError("blinded judge case must be an object")
        rubric_value = case_value.get("rubric")
        if not isinstance(rubric_value, Mapping):
            raise ValueError("blinded judge case rubric must be an object")
        internal_id = f"Opaque{index:06d}"
        rubric = _detached_json_object(rubric_value)
        rubric["id"] = internal_id
        presentation = rubric.get("case")
        if not isinstance(presentation, dict):
            presentation = {}
            rubric["case"] = presentation
        if not isinstance(presentation.get("presentation"), str):
            prompt = case_value.get("prompt")
            presentation["presentation"] = (
                prompt if isinstance(prompt, str) else _canonical_json(prompt)
            )
        guidance = case_value.get("guidance")
        cases.append(
            _InternalCase(
                internal_id=internal_id,
                source=row,
                rubric=rubric,
                guidance=guidance if isinstance(guidance, Mapping) else {},
            )
        )
    return tuple(cases)


def _load_released_results(
    path: Path,
    cases: Sequence[_InternalCase],
) -> dict[str, dict[str, float]]:
    if not path.is_file():
        raise ValueError("released NOHARM judge produced no judged artifact")
    allowed = {case.internal_id for case in cases}
    rows: dict[str, dict[str, float]] = {}
    for line_number, line in enumerate(path.read_bytes().splitlines(), start=1):
        if not line.strip():
            continue
        record = _load_released_json_bytes(line, f"{path}:{line_number}")
        internal_id = record.get("id")
        if internal_id not in allowed or internal_id in rows:
            raise ValueError(
                f"{path}:{line_number} has an unknown or duplicate internal id"
            )
        if record.get("trial", 1) != 1:
            raise ValueError(f"{path}:{line_number} changed the internal trial")
        metrics = record.get("metrics")
        if not isinstance(metrics, Mapping):
            raise ValueError(f"{path}:{line_number} has no canonical metrics")
        finite = {
            str(name): float(value)
            for name, value in metrics.items()
            if (
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(float(value))
            )
        }
        if not finite:
            raise ValueError(f"{path}:{line_number} has no finite metrics")
        rows[str(internal_id)] = finite
    return rows


def _summary_cost(summary: Any) -> float:
    stages = (
        summary.get("stages")
        if isinstance(summary, Mapping)
        else getattr(summary, "stages", None)
    )
    if not isinstance(stages, Mapping):
        raise ValueError("released NOHARM judge summary has no stage cost records")
    total = 0.0
    for label, stage in stages.items():
        cost = (
            stage.get("cost")
            if isinstance(stage, Mapping)
            else getattr(stage, "cost", None)
        )
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(float(cost))
            or float(cost) < 0
        ):
            raise ValueError(f"released NOHARM stage {label!r} has invalid cost")
        total += float(cost)
    return total


def _summary_calls(summary: Any, *, default: int) -> int:
    supplied = (
        summary.get("provider_call_count")
        if isinstance(summary, Mapping)
        else getattr(summary, "provider_call_count", None)
    )
    if supplied is None:
        return default
    return _positive_int(supplied, "released NOHARM provider_call_count")


def _provider_ids(
    ledger: Sequence[Mapping[str, Any]],
    summary: Any,
) -> tuple[str, ...]:
    supplied = (
        summary.get("provider_job_ids")
        if isinstance(summary, Mapping)
        else getattr(summary, "provider_job_ids", None)
    )
    values: list[str] = []
    if isinstance(supplied, Mapping):
        for stage, identifiers in sorted(supplied.items()):
            if isinstance(identifiers, (str, bytes)) or not isinstance(
                identifiers,
                Sequence,
            ):
                raise ValueError("provider job ids must be stage-indexed sequences")
            values.extend(f"{stage}:{identifier}" for identifier in identifiers)
    for record in ledger:
        values.append(f"{record['stage']}:{record['provider_job_id']}")
    normalized = tuple(
        dict.fromkeys(_text(value, "provider job id") for value in values)
    )
    if not normalized:
        raise ValueError(
            "canonical NOHARM execution produced no provider job provenance"
        )
    return normalized


def _load_job_ledger(
    path: Path,
    *,
    input_sha256: str,
    pipeline_sha256: str,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise ValueError("provider job ledger must be a regular file")
    records: list[dict[str, Any]] = []
    identities: set[str] = set()
    for line_number, line in enumerate(path.read_bytes().splitlines(), start=1):
        if not line.strip():
            continue
        record = _load_json_bytes(line, f"{path}:{line_number}")
        if set(record) != {
            "schema_version",
            "input_sha256",
            "pipeline_sha256",
            "stage",
            "provider",
            "requested_model",
            "provider_job_id",
            "item_count",
        }:
            raise ValueError(f"{path}:{line_number} provider ledger fields differ")
        if (
            record["schema_version"] != _LEDGER_SCHEMA
            or record["input_sha256"] != input_sha256
            or record["pipeline_sha256"] != pipeline_sha256
            or record["provider"] != "gemini"
        ):
            raise ValueError(f"{path}:{line_number} provider ledger binding changed")
        job_id = _text(record["provider_job_id"], "provider job id")
        if job_id in identities:
            raise ValueError(f"{path}:{line_number} duplicates a provider job")
        identities.add(job_id)
        _positive_int(record["item_count"], "provider job item_count")
        _text(record["stage"], "provider job stage")
        _text(record["requested_model"], "provider requested model")
        records.append(record)
    return records


def _append_job(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_canonical_json(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _validate_bundle_contract(
    panel: Sequence[Mapping[str, Any]],
    bundle: NoHarmReferenceBundle,
) -> None:
    assets = dict(bundle.hashes.assets)
    validate_canonical_noharm_assets(
        panel,
        judge_assets_sha256=bundle.hashes.judge_sha256,
        runtime_dependency_lock_sha256=(bundle.hashes.runtime_dependency_lock_sha256),
        match_prompt_sha256=assets["judge/prompts/extract_match.md"],
        review_prompt_sha256=assets["judge/prompts/global_match_review.md"],
    )


def _campaign_response_count(campaign: Mapping[str, Any]) -> int:
    coverage = campaign.get("coverage")
    if isinstance(coverage, Mapping):
        value = coverage.get("responses")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    cells = campaign.get("cells")
    if not isinstance(cells, list) or not cells:
        raise ValueError("campaign summary has no response coverage")
    total = 0
    for index, cell in enumerate(cells, start=1):
        if not isinstance(cell, Mapping):
            raise ValueError(f"campaign cell {index} must be an object")
        value = cell.get("responses", cell.get("calls_total"))
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"campaign cell {index} has invalid response coverage")
        total += value
    return total


def _canonical_settings_from_bundle(
    bundle: NoHarmReferenceBundle,
) -> dict[str, Any]:
    assets = dict(bundle.hashes.assets)
    return canonical_noharm_settings(
        judge_assets_sha256=bundle.hashes.judge_sha256,
        runtime_dependency_lock_sha256=(bundle.hashes.runtime_dependency_lock_sha256),
        match_prompt_sha256=assets["judge/prompts/extract_match.md"],
        review_prompt_sha256=assets["judge/prompts/global_match_review.md"],
    )


def _stage_runtime_sha256(
    bundle: NoHarmReferenceBundle,
    *,
    settings: Mapping[str, Any],
    stage: Mapping[str, Any],
) -> str:
    return sha256_digest(
        {
            "adapter_source_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "judge_runtime_sha256": _judge_runtime_digest(bundle),
            "pipeline_sha256": settings["canonical_pipeline_sha256"],
            "stage": dict(stage),
        }
    )


def _judge_runtime_digest(bundle: NoHarmReferenceBundle) -> str:
    selected = {
        name: digest
        for name, digest in bundle.hashes.assets.items()
        if name.startswith("judge/")
        and name != "judge/pins.json"
        and not is_judge_dependency_manifest(name)
    }
    if not selected:
        raise ValueError("bundle has no pinned judge runtime assets")
    return sha256_digest(
        {
            "assets": selected,
            "runtime_dependency_lock_sha256": (
                bundle.hashes.runtime_dependency_lock_sha256
            ),
        }
    )


def _load_released_judge_module(judge_root: Path) -> ModuleType:
    init_path = judge_root / "__init__.py"
    if not init_path.is_file():
        raise FileNotFoundError(f"released NOHARM judge not found: {init_path}")
    package_name = (
        "_arisekit_noharm_judge_"
        + hashlib.sha256(str(judge_root).encode("utf-8")).hexdigest()[:16]
    )
    existing = sys.modules.get(package_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        package_name,
        init_path,
        submodule_search_locations=[str(judge_root)],
    )
    if spec is None or spec.loader is None:
        raise ValueError("cannot load released NOHARM judge module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(package_name, None)
        raise
    return module


def _call_gemini_canary(model: str) -> tuple[str, str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model=model.removeprefix("gemini/"),
        contents='Return exactly {"ok": true}.',
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            },
            temperature=0.0,
            max_output_tokens=64,
        ),
    )
    observed = _text(
        getattr(response, "model_version", None),
        "provider-returned model",
    )
    response_id = _text(
        getattr(response, "response_id", None),
        "provider response id",
    )
    return observed, response_id


def _validate_open30_canary(
    value: Mapping[str, Any],
    *,
    stage: str,
    configured: Mapping[str, Any],
    expected_runtime_sha256: str,
) -> None:
    expected_keys = {
        "schema_version",
        "kind",
        "stage",
        "provider",
        "expected_provider_model",
        "observed_provider_model",
        "status",
        "response_id_sha256",
        "runtime_sha256",
    }
    if set(value) != expected_keys:
        raise ValueError(f"judge {stage} canary fields differ from its schema")
    expected = {
        "schema_version": OPEN30_CANARY_SCHEMA,
        "kind": "judge",
        "stage": stage,
        "provider": configured.get("provider"),
        "expected_provider_model": configured.get("expected_provider_model"),
        "observed_provider_model": configured.get("expected_provider_model"),
        "status": "passed",
    }
    for field, required in expected.items():
        if value.get(field) != required:
            raise ValueError(f"judge {stage} canary {field} is not verified")
    _sha256(value["response_id_sha256"], "canary response id hash")
    runtime = _sha256(value["runtime_sha256"], "canary runtime hash")
    if runtime != expected_runtime_sha256:
        raise ValueError(f"judge {stage} canary runtime does not match the bundle")


def _write_json_create_once(path: Path, payload: Mapping[str, Any]) -> None:
    write_private_once(path, (_canonical_json(payload) + "\n").encode("utf-8"), make_parents=True)


def _write_private_json(path: Path, value: Any) -> None:
    write_private_once(path, (_canonical_json(value) + "\n").encode("utf-8"))


def _detached_json_object(value: Mapping[str, Any]) -> dict[str, Any]:
    detached = json.loads(_canonical_json(value))
    if not isinstance(detached, dict):
        raise ValueError("rubric must be an object")
    return detached


def _load_json_object(path: Path) -> dict[str, Any]:
    return _load_json_bytes(path.read_bytes(), str(path))


def _load_json_bytes(content: bytes, source: str) -> dict[str, Any]:
    return strict_json_object(content, source, allow_bytes=True, allow_duplicate_keys=True)


def _load_released_json_bytes(content: bytes, source: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{source} is not valid released judge JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{source} must contain a JSON object")
    return value


def _directory_path(value: str | Path, label: str) -> Path:
    supplied = Path(value).expanduser()
    if supplied.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    path = supplied.resolve()
    if path.exists() and not path.is_dir():
        raise ValueError(f"{label} must be a directory")
    return path


def _output_path(value: str | Path) -> Path:
    supplied = Path(value).expanduser()
    if supplied.is_symlink():
        raise ValueError("judge output must not be a symlink")
    return supplied.resolve()


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _text(value: Any, label: str) -> str:
    return text(value, label, strip=True)


def _positive_number(value: Any, name: str) -> float:
    return number(value, name, exclusive_minimum=0)


__all__ = [
    "CANONICAL_ADAPTER_ID",
    "OPEN30_CANARY_SCHEMA",
    "OPEN30_JUDGE_MANIFEST_SCHEMA",
    "build_open30_judge_manifest",
    "execute_canonical_noharm_judge",
    "execute_open30_judge_canary",
]
