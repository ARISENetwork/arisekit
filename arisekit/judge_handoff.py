"""Blinded, hash-bound handoff between NOHARM inference and external judging.

The judge-facing file contains no benchmark arm, solver model, provider,
filesystem path, or case identifier. A separately protected reidentification
map commits every opaque record to the campaign artifacts and raw response that
created it. Strict conversion rechecks those commitments before restoring
analysis identities.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from arisekit.common.files import existing_file
from arisekit.common.hashing import strict_canonical_sha256 as _sha256_json
from arisekit.common.jsonio import strict_canonical_json as _canonical_json, strict_json_object
from arisekit.common.validate import sha256_hex as _require_sha256
from arisekit.egress import ProviderDisclosureAuthorization
from arisekit.evaluation.noharm_judge_contract import (
    validate_canonical_noharm_panel_entry,
)
from arisekit.run_manifest import RunManifest


JUDGE_INPUT_SCHEMA = "arisekit.noharm-parity-judge-input.v1"
JUDGED_RESULT_SCHEMA = "arisekit.noharm-parity-judged-result.v1"
REIDENTIFICATION_SCHEMA = "arisekit.noharm-parity-reidentification.v1"
BINDING_SCHEMA = "arisekit.noharm-parity-judge-binding.v1"

_OPAQUE_RE = re.compile(r"^jh_[0-9a-f]{64}$")
_MAP_KEYS = {
    "schema_version",
    "campaign_id",
    "seed",
    "expected_judges",
    "judge_panel",
    "judge_panel_sha256",
    "campaign_config",
    "campaign_summary",
    "judge_input",
    "records_digest",
    "records",
}
_MAP_RECORD_KEYS = {
    "opaque_id",
    "binding_digest",
    "campaign_cell_id",
    "arm",
    "model",
    "provider",
    "system_model",
    "item_id",
    "base_case",
    "specialty",
    "trial",
    "raw_checkpoint_path",
    "raw_checkpoint_sha256",
    "raw_line_number",
    "raw_response_sha256",
    "run_manifest_path",
    "run_manifest_sha256",
    "run_manifest_digest",
    "benchmark_content_hash",
    "prompt_hash",
    "judge_hash",
    "judge_panel_sha256",
    "case_payload_sha256",
    "judge_input_record_sha256",
}
_BINDING_FIELDS = (
    "campaign_cell_id",
    "arm",
    "model",
    "provider",
    "system_model",
    "item_id",
    "base_case",
    "specialty",
    "trial",
    "raw_checkpoint_path",
    "raw_checkpoint_sha256",
    "raw_line_number",
    "raw_response_sha256",
    "run_manifest_path",
    "run_manifest_sha256",
    "run_manifest_digest",
    "benchmark_content_hash",
    "prompt_hash",
    "judge_hash",
    "judge_panel_sha256",
    "case_payload_sha256",
)
_JUDGE_INPUT_KEYS = {
    "schema_version",
    "opaque_id",
    "binding_digest",
    "response_sha256",
    "case",
    "response",
}
_CASE_KEYS = {"prompt", "rubric", "guidance"}
_JUDGED_RESULT_KEYS = {
    "schema_version",
    "opaque_id",
    "binding_digest",
    "response_sha256",
    "judge",
    "judge_execution_digest",
    "judge_provenance",
    "metrics",
}
_JUDGE_PROVENANCE_KEYS = {
    "provider",
    "model",
    "provider_model",
    "settings_sha256",
    "judge_runtime_hash",
    "provider_response_ids",
    "cost_usd",
}
_NOHARM_METRICS = {
    "F1_raw",
    "F1_binary",
    "F1_weighted",
    "Precision_raw",
    "Precision_binary",
    "Precision_weighted",
    "Recall_raw",
    "Recall_binary",
    "Recall_weighted",
    "Accuracy",
    "Accuracy_binary",
    "Severe_rate",
    "Moderate_rate",
    "Mild_rate",
    "Triage",
}


@dataclass(frozen=True)
class JudgeCaseMaterial:
    """Private case material used to build one blinded judge record."""

    item_id: str
    base_case: str
    specialty: str
    prompt: Any
    rubric: Mapping[str, Any]
    guidance: str | None = None

    def validate(self) -> None:
        _required_string(self.item_id, "case item_id")
        _required_string(self.base_case, "case base_case")
        _required_string(self.specialty, "case specialty")
        if not isinstance(self.rubric, Mapping):
            raise ValueError(f"case {self.item_id!r} rubric must be an object")
        _canonical_json(self.prompt)
        _canonical_json(self.rubric)
        if self.guidance is not None and not isinstance(self.guidance, str):
            raise ValueError(f"case {self.item_id!r} guidance must be text or null")


@dataclass(frozen=True)
class JudgeCheckpointSource:
    """One completed arm-model checkpoint and its selected case catalog."""

    arm: str
    model: str
    checkpoint_path: Path
    cases: Sequence[JudgeCaseMaterial]
    benchmark_content_hash: str
    prompt_hash: str
    judge_hash: str


@dataclass(frozen=True)
class PreparedJudgeHandoff:
    judge_input_path: Path
    reidentification_map_path: Path
    records: int
    judge_input_sha256: str
    reidentification_map_sha256: str
    expected_judges: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": "strict-bound",
            "judge_input_path": str(self.judge_input_path),
            "reidentification_map_path": str(self.reidentification_map_path),
            "records": self.records,
            "judge_input_sha256": self.judge_input_sha256,
            "reidentification_map_sha256": self.reidentification_map_sha256,
            "expected_judges": list(self.expected_judges),
        }


@dataclass(frozen=True)
class ReidentifiedJudgedRecord:
    source: Path
    line_number: int
    arm: str
    model: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class VerifiedJudgeHandoff:
    records: tuple[ReidentifiedJudgedRecord, ...]
    expected_judges: tuple[str, ...]
    judged_inputs: tuple[tuple[Path, str, int], ...]
    campaign_config_path: Path
    campaign_config_sha256: str
    campaign_summary_path: Path
    campaign_summary_sha256: str
    reidentification_map_path: Path
    reidentification_map_sha256: str
    judge_input_path: Path
    judge_input_sha256: str
    judge_executions: tuple[tuple[Path, str], ...]
    protected_paths: tuple[Path, ...]


def prepare_blinded_judge_handoff(
    sources: Sequence[JudgeCheckpointSource],
    *,
    campaign_config_path: str | Path,
    campaign_summary_path: str | Path,
    judge_input_path: str | Path,
    reidentification_map_path: str | Path,
    seed: int,
    expected_judges: Sequence[str],
) -> PreparedJudgeHandoff:
    """Create deterministic seed-randomized judge JSONL and a private map."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("judge handoff seed must be an integer")
    judges = _judge_panel(expected_judges)
    config_path = _existing_file(campaign_config_path, "campaign config")
    summary_path = _existing_file(campaign_summary_path, "campaign summary")
    output = _output_path(judge_input_path, "judge input")
    map_output = _output_path(reidentification_map_path, "reidentification map")
    if output == map_output:
        raise ValueError("judge input and reidentification map paths must differ")

    config_bytes = config_path.read_bytes()
    summary_bytes = summary_path.read_bytes()
    config = _load_json_object(config_bytes, source=str(config_path))
    summary = _load_json_object(summary_bytes, source=str(summary_path))
    contract = _campaign_contract(config)
    if judges != contract["judge_ids"]:
        raise ValueError(
            "expected judge names must exactly match the manifest-frozen "
            "campaign judge_panel order"
        )
    judge_panel_sha256 = contract["judge_panel_hash"]
    summary_cells = _campaign_summary_cells(summary, contract)
    normalized_sources = _normalize_sources(sources, contract, summary_cells)

    protected = {config_path, summary_path}
    for source in normalized_sources:
        protected.add(source.checkpoint_path)
        protected.add(source.checkpoint_path.parent / "run-manifest.json")
    if output in protected or map_output in protected:
        raise ValueError(
            "handoff outputs cannot overwrite campaign or checkpoint artifacts"
        )

    draft_records: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    common_judge_hash: str | None = None
    common_prompt_hash: str | None = None
    for source in normalized_sources:
        cell = summary_cells[(source.arm, source.model)]
        manifest_path = source.checkpoint_path.parent / "run-manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        manifest = _manifest_from_bytes(manifest_bytes, manifest_path)
        _validate_source_manifest(source, cell, manifest, contract)
        if manifest.judge_hash is None:
            raise ValueError(f"{manifest_path} does not freeze a judge hash")
        if common_judge_hash is None:
            common_judge_hash = manifest.judge_hash
        elif manifest.judge_hash != common_judge_hash:
            raise ValueError("all parity cells must use one exact judge hash")
        if common_prompt_hash is None:
            common_prompt_hash = manifest.prompt_hash
        elif manifest.prompt_hash != common_prompt_hash:
            raise ValueError("all parity cells must use one exact response prompt hash")

        checkpoint_bytes = source.checkpoint_path.read_bytes()
        checkpoint_sha256 = _sha256_bytes(checkpoint_bytes)
        checkpoint_rows = _checkpoint_latest_rows(
            checkpoint_bytes,
            source=source.checkpoint_path,
        )
        cases = {case.item_id: case for case in source.cases}
        expected_identities = {
            (item_id, trial)
            for item_id in cases
            for trial in range(1, manifest.trials + 1)
        }
        if set(checkpoint_rows) != expected_identities:
            missing = sorted(expected_identities - set(checkpoint_rows))
            extra = sorted(set(checkpoint_rows) - expected_identities)
            raise ValueError(
                f"{source.checkpoint_path} checkpoint coverage differs from the "
                f"manifest selection; missing={missing}, extra={extra}"
            )

        for (item_id, trial), (line_number, raw) in sorted(checkpoint_rows.items()):
            _validate_raw_result(
                raw,
                source=source.checkpoint_path,
                line_number=line_number,
                manifest_digest=manifest.digest,
                item_id=item_id,
                trial=trial,
            )
            response = raw["response"]
            response_sha256 = _sha256_json(response)
            case = cases[item_id]
            case_payload = _blinded_case_payload(case, response=response)
            case_payload_sha256 = _sha256_json(case_payload)
            base_record = {
                "campaign_cell_id": _required_string(cell["id"], "campaign cell id"),
                "arm": source.arm,
                "model": source.model,
                "provider": contract["models"][source.model]["provider"],
                "system_model": contract["models"][source.model]["system_model"],
                "item_id": item_id,
                "base_case": case.base_case,
                "specialty": case.specialty,
                "trial": trial,
                "raw_checkpoint_path": str(source.checkpoint_path),
                "raw_checkpoint_sha256": checkpoint_sha256,
                "raw_line_number": line_number,
                "raw_response_sha256": response_sha256,
                "run_manifest_path": str(manifest_path),
                "run_manifest_sha256": _sha256_bytes(manifest_bytes),
                "run_manifest_digest": manifest.digest,
                "benchmark_content_hash": manifest.benchmark_content_hash,
                "prompt_hash": manifest.prompt_hash,
                "judge_hash": manifest.judge_hash,
                "judge_panel_sha256": judge_panel_sha256,
                "case_payload_sha256": case_payload_sha256,
            }
            identity_digest = _sha256_json(
                {
                    "schema_version": BINDING_SCHEMA,
                    **base_record,
                }
            )
            opaque_id = "jh_" + _sha256_text(
                f"{REIDENTIFICATION_SCHEMA}\0{seed}\0{identity_digest}"
            )
            binding_digest = _binding_digest(opaque_id, base_record)
            judge_row = {
                "schema_version": JUDGE_INPUT_SCHEMA,
                "opaque_id": opaque_id,
                "binding_digest": binding_digest,
                "response_sha256": response_sha256,
                "case": case_payload["case"],
                "response": response,
            }
            map_record = {
                "opaque_id": opaque_id,
                "binding_digest": binding_digest,
                **base_record,
                "judge_input_record_sha256": _sha256_json(judge_row),
            }
            order_key = _sha256_text(
                f"{REIDENTIFICATION_SCHEMA}\0order\0{seed}\0{opaque_id}"
            )
            draft_records.append((order_key, judge_row, map_record))

    if not draft_records:
        raise ValueError("judge handoff requires at least one response record")
    opaque_ids = [record[2]["opaque_id"] for record in draft_records]
    if len(set(opaque_ids)) != len(opaque_ids):
        raise ValueError("opaque judge identifiers collided")

    ordered = sorted(draft_records, key=lambda row: row[0])
    judge_rows = [row[1] for row in ordered]
    map_records = [row[2] for row in ordered]
    judge_input_bytes = _jsonl_bytes(judge_rows)
    judge_input_sha256 = _sha256_bytes(judge_input_bytes)
    map_payload = {
        "schema_version": REIDENTIFICATION_SCHEMA,
        "campaign_id": contract["campaign_id"],
        "seed": seed,
        "expected_judges": list(judges),
        "judge_panel": list(contract["judge_panel"]),
        "judge_panel_sha256": judge_panel_sha256,
        "campaign_config": {
            "path": str(config_path),
            "sha256": _sha256_bytes(config_bytes),
        },
        "campaign_summary": {
            "path": str(summary_path),
            "sha256": _sha256_bytes(summary_bytes),
        },
        "judge_input": {
            "path": str(output),
            "sha256": judge_input_sha256,
        },
        "records_digest": _sha256_json(map_records),
        "records": map_records,
    }
    map_bytes = (_canonical_json(map_payload) + "\n").encode("utf-8")
    _write_idempotent(output, judge_input_bytes)
    _write_idempotent(map_output, map_bytes)
    return PreparedJudgeHandoff(
        judge_input_path=output,
        reidentification_map_path=map_output,
        records=len(judge_rows),
        judge_input_sha256=judge_input_sha256,
        reidentification_map_sha256=_sha256_bytes(map_bytes),
        expected_judges=judges,
    )


def verify_bound_judged_results(
    judged_paths: Sequence[str | Path],
    *,
    reidentification_map_path: str | Path,
) -> VerifiedJudgeHandoff:
    """Verify a strict judged handoff and restore private analysis identities."""
    map_path = _existing_file(reidentification_map_path, "reidentification map")
    map_bytes = map_path.read_bytes()
    payload = _load_json_object(map_bytes, source=str(map_path))
    _exact_keys(payload, _MAP_KEYS, str(map_path))
    if payload["schema_version"] != REIDENTIFICATION_SCHEMA:
        raise ValueError(f"{map_path} has an unsupported reidentification schema")
    seed = payload["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError(f"{map_path} seed must be an integer")
    judges = _judge_panel(payload["expected_judges"])
    panel_value = payload["judge_panel"]
    if not isinstance(panel_value, list):
        raise ValueError(f"{map_path} judge_panel must be a list")
    panel = _normalize_judge_panel(panel_value)
    panel_by_id = {record["id"]: record for record in panel}
    panel_hash = _require_sha256(payload["judge_panel_sha256"], "judge panel hash")
    if judges != tuple(record["id"] for record in panel):
        raise ValueError(f"{map_path} expected_judges conflicts with judge_panel")
    if not hmac.compare_digest(panel_hash, _sha256_json(list(panel))):
        raise ValueError(f"{map_path} judge panel hash does not match judge_panel")

    config_path, config_bytes = _verify_artifact(
        payload["campaign_config"], "campaign config"
    )
    summary_path, summary_bytes = _verify_artifact(
        payload["campaign_summary"],
        "campaign summary",
    )
    judge_input_path, judge_input_bytes = _verify_artifact(
        payload["judge_input"],
        "judge input",
    )
    config = _load_json_object(config_bytes, source=str(config_path))
    summary = _load_json_object(summary_bytes, source=str(summary_path))
    contract = _campaign_contract(config)
    if panel != contract["judge_panel"]:
        raise ValueError(f"{map_path} judge panel conflicts with its frozen config")
    if panel_hash != contract["judge_panel_hash"]:
        raise ValueError(
            f"{map_path} judge panel digest conflicts with its frozen config"
        )
    if payload["campaign_id"] != contract["campaign_id"]:
        raise ValueError(f"{map_path} campaign id conflicts with its frozen config")
    summary_cells = _campaign_summary_cells(summary, contract)

    records_value = payload["records"]
    if not isinstance(records_value, list) or not records_value:
        raise ValueError(f"{map_path} records must be a non-empty list")
    records: dict[str, Mapping[str, Any]] = {}
    for index, record in enumerate(records_value, start=1):
        if not isinstance(record, Mapping):
            raise ValueError(f"{map_path} record {index} must be an object")
        _exact_keys(record, _MAP_RECORD_KEYS, f"{map_path} record {index}")
        _validate_map_record(
            record,
            seed=seed,
            panel_hash=panel_hash,
            contract=contract,
            summary_cells=summary_cells,
            context=f"{map_path} record {index}",
        )
        opaque_id = str(record["opaque_id"])
        if opaque_id in records:
            raise ValueError(f"{map_path} duplicates opaque id {opaque_id}")
        records[opaque_id] = record
    declared_records_digest = _require_sha256(
        payload["records_digest"],
        "records digest",
    )
    if not hmac.compare_digest(declared_records_digest, _sha256_json(records_value)):
        raise ValueError(f"{map_path} records digest does not match its records")

    _verify_judge_input(judge_input_bytes, judge_input_path, records)
    _verify_private_sources(records_value, contract=contract)

    paths = _judged_paths(judged_paths)
    protected = {
        map_path,
        config_path,
        summary_path,
        judge_input_path,
    }
    for record in records_value:
        protected.add(Path(str(record["raw_checkpoint_path"])).resolve())
        protected.add(Path(str(record["run_manifest_path"])).resolve())
    overlap = set(paths) & protected
    if overlap:
        raise ValueError(
            "judged result inputs cannot reuse protected handoff artifacts: "
            + ", ".join(str(path) for path in sorted(overlap))
        )

    seen: set[tuple[str, str]] = set()
    restored: list[ReidentifiedJudgedRecord] = []
    judged_audit: list[tuple[Path, str, int]] = []
    execution_audit: list[tuple[Path, str]] = []
    for path in paths:
        execution_path, execution_digest = _verify_judge_execution_manifest(
            path,
            judge_input_sha256=_sha256_bytes(judge_input_bytes),
            judge_panel=panel,
            judge_runtime_hash=str(records_value[0]["judge_hash"]),
        )
        protected.add(execution_path)
        execution_audit.append((execution_path, execution_digest))
        source_bytes = path.read_bytes()
        row_count = 0
        for line_number, raw_line in enumerate(source_bytes.splitlines(), start=1):
            if not raw_line.strip():
                continue
            row_count += 1
            result = _load_json_object(
                raw_line,
                source=f"{path}:{line_number}",
            )
            _exact_keys(result, _JUDGED_RESULT_KEYS, f"{path}:{line_number}")
            if result["schema_version"] != JUDGED_RESULT_SCHEMA:
                raise ValueError(
                    f"{path}:{line_number} has an unsupported judged schema"
                )
            opaque_id = _required_string(
                result["opaque_id"],
                f"{path}:{line_number} opaque_id",
            )
            record = records.get(opaque_id)
            if record is None:
                raise ValueError(
                    f"{path}:{line_number} is not linked to the handoff map"
                )
            _matching_hash(
                result["binding_digest"],
                record["binding_digest"],
                f"{path}:{line_number} binding digest",
            )
            _matching_hash(
                result["response_sha256"],
                record["raw_response_sha256"],
                f"{path}:{line_number} response hash",
            )
            judge = _required_string(result["judge"], f"{path}:{line_number} judge")
            _matching_hash(
                result["judge_execution_digest"],
                execution_digest,
                f"{path}:{line_number} judge execution digest",
            )
            if judge not in judges:
                raise ValueError(
                    f"{path}:{line_number} judge {judge!r} is outside the frozen panel"
                )
            _validate_judge_provenance(
                result["judge_provenance"],
                expected=panel_by_id[judge],
                judge_runtime_hash=str(record["judge_hash"]),
                context=f"{path}:{line_number}",
            )
            identity = (opaque_id, judge)
            if identity in seen:
                raise ValueError(
                    f"{path}:{line_number} duplicates opaque response/judge {identity}"
                )
            seen.add(identity)
            metrics = result["metrics"]
            _validate_noharm_metrics(metrics, context=f"{path}:{line_number}")
            canonical = {
                "id": record["item_id"],
                "arm": record["arm"],
                "model": record["model"],
                "specialty": record["specialty"],
                "base_case": record["base_case"],
                "variant": record["item_id"],
                "trial": record["trial"],
                "judge": judge,
                "metrics": dict(metrics),
            }
            restored.append(
                ReidentifiedJudgedRecord(
                    source=path,
                    line_number=line_number,
                    arm=str(record["arm"]),
                    model=str(record["model"]),
                    payload=canonical,
                )
            )
        judged_audit.append((path, _sha256_bytes(source_bytes), row_count))

    expected = {(opaque_id, judge) for opaque_id in records for judge in judges}
    if seen != expected:
        missing = sorted(expected - seen)
        extra = sorted(seen - expected)
        raise ValueError(
            "strict judged results do not cover the exact frozen response/judge "
            f"panel; missing={missing}, extra={extra}"
        )
    return VerifiedJudgeHandoff(
        records=tuple(restored),
        expected_judges=judges,
        judged_inputs=tuple(judged_audit),
        campaign_config_path=config_path,
        campaign_config_sha256=_sha256_bytes(config_bytes),
        campaign_summary_path=summary_path,
        campaign_summary_sha256=_sha256_bytes(summary_bytes),
        reidentification_map_path=map_path,
        reidentification_map_sha256=_sha256_bytes(map_bytes),
        judge_input_path=judge_input_path,
        judge_input_sha256=_sha256_bytes(judge_input_bytes),
        judge_executions=tuple(execution_audit),
        protected_paths=tuple(sorted(protected)),
    )


def _normalize_sources(
    sources: Sequence[JudgeCheckpointSource],
    contract: Mapping[str, Any],
    summary_cells: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[JudgeCheckpointSource, ...]:
    if isinstance(sources, (str, bytes)) or not sources:
        raise ValueError("judge handoff requires completed campaign sources")
    normalized: list[JudgeCheckpointSource] = []
    coordinates: set[tuple[str, str]] = set()
    for source in sources:
        if not isinstance(source, JudgeCheckpointSource):
            raise ValueError(
                "judge handoff sources must be JudgeCheckpointSource values"
            )
        arm = _required_string(source.arm, "source arm")
        model = _required_string(source.model, "source model")
        coordinate = (arm, model)
        if coordinate in coordinates:
            raise ValueError(f"duplicate judge handoff source for {arm}/{model}")
        if coordinate not in summary_cells:
            raise ValueError(
                f"judge handoff source {arm}/{model} is outside the campaign"
            )
        checkpoint = _existing_file(source.checkpoint_path, "raw checkpoint")
        expected_output = Path(str(summary_cells[coordinate]["output_path"])).resolve()
        if checkpoint != expected_output:
            raise ValueError(
                f"source {arm}/{model} checkpoint does not match campaign summary"
            )
        cases = tuple(source.cases)
        if not cases:
            raise ValueError(f"source {arm}/{model} has no selected cases")
        case_ids: set[str] = set()
        for case in cases:
            if not isinstance(case, JudgeCaseMaterial):
                raise ValueError(f"source {arm}/{model} has invalid case material")
            case.validate()
            if case.item_id in case_ids:
                raise ValueError(f"source {arm}/{model} duplicates case {case.item_id}")
            case_ids.add(case.item_id)
        coordinates.add(coordinate)
        normalized.append(
            JudgeCheckpointSource(
                arm=arm,
                model=model,
                checkpoint_path=checkpoint,
                cases=cases,
                benchmark_content_hash=_require_sha256(
                    source.benchmark_content_hash,
                    f"source {arm}/{model} benchmark content hash",
                ),
                prompt_hash=_require_sha256(
                    source.prompt_hash,
                    f"source {arm}/{model} prompt hash",
                ),
                judge_hash=_require_sha256(
                    source.judge_hash,
                    f"source {arm}/{model} judge hash",
                ),
            )
        )
    expected_coordinates = set(summary_cells)
    if coordinates != expected_coordinates:
        missing = sorted(expected_coordinates - coordinates)
        raise ValueError(f"judge handoff is missing campaign cells: {missing}")
    return tuple(sorted(normalized, key=lambda row: (row.arm, row.model)))


def _validate_source_manifest(
    source: JudgeCheckpointSource,
    cell: Mapping[str, Any],
    manifest: RunManifest,
    contract: Mapping[str, Any],
) -> None:
    expected_model = contract["models"][source.model]
    if manifest.digest != cell["manifest_digest"]:
        raise ValueError(
            f"{source.checkpoint_path} manifest digest conflicts with campaign summary"
        )
    if manifest.benchmark_arm != source.arm:
        raise ValueError(f"{source.checkpoint_path} manifest arm is not {source.arm!r}")
    if manifest.model != expected_model["system_model"]:
        raise ValueError(f"{source.checkpoint_path} manifest solver route changed")
    if manifest.provider != expected_model["provider"]:
        raise ValueError(f"{source.checkpoint_path} manifest provider changed")
    if manifest.benchmark_content_hash != source.benchmark_content_hash:
        raise ValueError(
            f"{source.checkpoint_path} bundle content changed after inference"
        )
    if manifest.prompt_hash != source.prompt_hash:
        raise ValueError(
            f"{source.checkpoint_path} response prompt changed after inference"
        )
    if manifest.judge_hash != source.judge_hash:
        raise ValueError(
            f"{source.checkpoint_path} judge runtime changed after inference"
        )
    _validate_bundle_hash_fields(
        manifest.selection,
        contract,
        context=f"{source.checkpoint_path} manifest selection",
    )
    _validate_disclosure_fields(
        manifest.selection,
        contract,
        context=f"{source.checkpoint_path} manifest selection",
    )
    _validate_campaign_scope_fields(
        manifest.selection,
        contract,
        context=f"{source.checkpoint_path} manifest selection",
    )
    manifest_panel, manifest_panel_hash = _manifest_judge_panel(manifest)
    if manifest_panel != contract["judge_panel"]:
        raise ValueError(
            f"{source.checkpoint_path} manifest judge panel conflicts with campaign config"
        )
    if manifest_panel_hash != contract["judge_panel_hash"]:
        raise ValueError(f"{source.checkpoint_path} manifest judge panel hash changed")
    arm_selection = _manifest_arm_selection(manifest, source.arm)
    item_ids = arm_selection.get("item_ids")
    expected_ids = [case.item_id for case in source.cases]
    if not isinstance(item_ids, (list, tuple)) or list(item_ids) != expected_ids:
        raise ValueError(
            f"{source.checkpoint_path} manifest must bind the exact selected item_ids"
        )
    expected_bases = list(dict.fromkeys(case.base_case for case in source.cases))
    base_ids = arm_selection.get("base_ids")
    if not isinstance(base_ids, (list, tuple)) or list(base_ids) != expected_bases:
        raise ValueError(
            f"{source.checkpoint_path} manifest must bind the exact selected base_ids"
        )
    if arm_selection.get("policy") != "baseline-plus-first-perturbations":
        raise ValueError(f"{source.checkpoint_path} manifest selection policy changed")


def _manifest_arm_selection(
    manifest: RunManifest,
    arm: str,
) -> Mapping[str, Any]:
    arm_selections = manifest.selection.get("arms")
    if not isinstance(arm_selections, Mapping):
        raise ValueError("run manifest selection must contain exact per-arm selections")
    arm_selection = arm_selections.get(arm)
    if not isinstance(arm_selection, Mapping):
        raise ValueError(f"run manifest selection has no exact record for arm {arm!r}")
    if manifest.selection.get("k") != arm_selection.get("k"):
        raise ValueError(
            f"run manifest arm {arm!r} k conflicts with campaign selection"
        )
    if manifest.selection.get("policy") != arm_selection.get("policy"):
        raise ValueError(
            f"run manifest arm {arm!r} policy conflicts with campaign selection"
        )
    return arm_selection


def _manifest_judge_panel(
    manifest: RunManifest,
) -> tuple[tuple[dict[str, Any], ...], str]:
    panel_value = manifest.selection.get("judge_panel")
    if not isinstance(panel_value, (list, tuple)):
        raise ValueError("run manifest selection must contain its frozen judge_panel")
    panel = _normalize_judge_panel(panel_value)
    declared_hash = _require_sha256(
        manifest.selection.get("judge_panel_hash"),
        "run manifest judge_panel_hash",
    )
    actual_hash = _sha256_json(list(panel))
    if not hmac.compare_digest(declared_hash, actual_hash):
        raise ValueError("run manifest judge_panel_hash does not match judge_panel")
    return panel, declared_hash


def _checkpoint_latest_rows(
    content: bytes,
    *,
    source: Path,
) -> dict[tuple[str, int], tuple[int, Mapping[str, Any]]]:
    latest: dict[tuple[str, int], tuple[int, Mapping[str, Any]]] = {}
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        if not raw_line.strip():
            continue
        payload = _load_json_object(raw_line, source=f"{source}:{line_number}")
        item_id = _required_string(payload.get("id"), f"{source}:{line_number} id")
        trial = payload.get("trial")
        if isinstance(trial, bool) or not isinstance(trial, int) or trial < 1:
            raise ValueError(f"{source}:{line_number} trial must be a positive integer")
        latest[(item_id, trial)] = (line_number, payload)
    if not latest:
        raise ValueError(f"{source} contains no checkpoint records")
    return latest


def _validate_raw_result(
    payload: Mapping[str, Any],
    *,
    source: Path,
    line_number: int,
    manifest_digest: str,
    item_id: str,
    trial: int,
) -> None:
    context = f"{source}:{line_number}"
    if payload.get("id") != item_id or payload.get("trial") != trial:
        raise ValueError(f"{context} checkpoint identity changed")
    if payload.get("error") is not None:
        raise ValueError(f"{context} is an errored response and cannot be judged")
    if "response" not in payload or payload["response"] is None:
        raise ValueError(f"{context} has no response to judge")
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError(f"{context} metadata must be an object")
    if metadata.get("run_manifest_digest") != manifest_digest:
        raise ValueError(f"{context} is not bound to its run manifest")
    _canonical_json(payload["response"])


def _blinded_case_payload(case: JudgeCaseMaterial, *, response: Any) -> dict[str, Any]:
    identifiers = tuple(sorted({case.item_id, case.base_case}, key=len, reverse=True))
    rubric = _redact_identifiers(
        _rubric_projection(case.rubric),
        identifiers,
    )
    prompt = _redact_identifiers(case.prompt, identifiers)
    guidance = _redact_identifiers(
        _guidance_projection(case.guidance),
        identifiers,
    )
    return {
        "case": {
            "prompt": prompt,
            "rubric": rubric,
            "guidance": guidance,
        },
        "response": response,
    }


def _rubric_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    excluded = {
        "access_classification",
        "open",
        "release_scope",
        "source_rights",
    }

    def project(child: Any) -> Any:
        if isinstance(child, Mapping):
            return {
                str(key): project(nested)
                for key, nested in sorted(child.items(), key=lambda row: str(row[0]))
                if str(key).casefold().replace("-", "_") not in excluded
            }
        if isinstance(child, (list, tuple)):
            return [project(nested) for nested in child]
        if child is None or isinstance(child, (str, bool, int)):
            return child
        if isinstance(child, float):
            if not math.isfinite(child):
                raise ValueError("case rubric contains a non-finite number")
            return child
        raise ValueError(f"case rubric contains unsupported {type(child).__name__}")

    projected = project(value)
    assert isinstance(projected, dict)
    return projected


def _guidance_projection(value: str | None) -> Any:
    if value is None:
        return None
    try:
        parsed = yaml.safe_load(value)
    except yaml.YAMLError as exc:
        raise ValueError(f"case guidance is not valid YAML or JSON: {exc}") from exc
    excluded = {
        "access_classification",
        "case_id",
        "clinical_revision",
        "source_revision",
    }

    def project(child: Any) -> Any:
        if isinstance(child, Mapping):
            return {
                str(key): project(nested)
                for key, nested in sorted(child.items(), key=lambda row: str(row[0]))
                if str(key).casefold().replace("-", "_") not in excluded
            }
        if isinstance(child, (list, tuple)):
            return [project(nested) for nested in child]
        if child is None or isinstance(child, (str, bool, int)):
            return child
        if isinstance(child, float):
            if not math.isfinite(child):
                raise ValueError("case guidance contains a non-finite number")
            return child
        raise ValueError(f"case guidance contains unsupported {type(child).__name__}")

    return project(parsed)


def _redact_identifiers(value: Any, identifiers: Sequence[str]) -> Any:
    if isinstance(value, str):
        redacted = value
        for identifier in identifiers:
            redacted = redacted.replace(identifier, "[case]")
        return redacted
    if isinstance(value, Mapping):
        rendered: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("judge case material contains a non-string object key")
            redacted_key = _redact_identifiers(key, identifiers)
            if redacted_key in rendered:
                raise ValueError(
                    "case identifier redaction creates duplicate object keys"
                )
            rendered[redacted_key] = _redact_identifiers(child, identifiers)
        return rendered
    if isinstance(value, (list, tuple)):
        return [_redact_identifiers(child, identifiers) for child in value]
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("judge case material contains a non-finite float")
        return value
    raise ValueError(f"judge case material contains unsupported {type(value).__name__}")


def _verify_judge_input(
    content: bytes,
    path: Path,
    records: Mapping[str, Mapping[str, Any]],
) -> None:
    seen: list[str] = []
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        if not raw_line.strip():
            continue
        row = _load_json_object(raw_line, source=f"{path}:{line_number}")
        _exact_keys(row, _JUDGE_INPUT_KEYS, f"{path}:{line_number}")
        if row["schema_version"] != JUDGE_INPUT_SCHEMA:
            raise ValueError(
                f"{path}:{line_number} has an unsupported judge-input schema"
            )
        opaque_id = _required_string(
            row["opaque_id"], f"{path}:{line_number} opaque_id"
        )
        record = records.get(opaque_id)
        if record is None:
            raise ValueError(f"{path}:{line_number} is absent from the private map")
        _matching_hash(
            row["binding_digest"],
            record["binding_digest"],
            f"{path}:{line_number} binding digest",
        )
        _matching_hash(
            row["response_sha256"],
            record["raw_response_sha256"],
            f"{path}:{line_number} response hash",
        )
        _exact_keys(row["case"], _CASE_KEYS, f"{path}:{line_number} case")
        if not hmac.compare_digest(
            _sha256_json({"case": row["case"], "response": row["response"]}),
            str(record["case_payload_sha256"]),
        ):
            raise ValueError(f"{path}:{line_number} case/response payload was altered")
        if not hmac.compare_digest(
            _sha256_json(row),
            str(record["judge_input_record_sha256"]),
        ):
            raise ValueError(f"{path}:{line_number} judge-input record was altered")
        seen.append(opaque_id)
    if seen != list(records):
        raise ValueError(
            f"{path} record order or coverage conflicts with the private map"
        )


def _validate_map_record(
    record: Mapping[str, Any],
    *,
    seed: int,
    panel_hash: str,
    contract: Mapping[str, Any],
    summary_cells: Mapping[tuple[str, str], Mapping[str, Any]],
    context: str,
) -> None:
    opaque_id = _required_string(record["opaque_id"], f"{context} opaque_id")
    if _OPAQUE_RE.fullmatch(opaque_id) is None:
        raise ValueError(f"{context} opaque_id is malformed")
    for name in (
        "binding_digest",
        "raw_checkpoint_sha256",
        "raw_response_sha256",
        "run_manifest_sha256",
        "run_manifest_digest",
        "benchmark_content_hash",
        "prompt_hash",
        "judge_hash",
        "judge_panel_sha256",
        "case_payload_sha256",
        "judge_input_record_sha256",
    ):
        _require_sha256(record[name], f"{context} {name}")
    if not hmac.compare_digest(str(record["judge_panel_sha256"]), panel_hash):
        raise ValueError(f"{context} judge panel hash changed")
    arm = _required_string(record["arm"], f"{context} arm")
    model = _required_string(record["model"], f"{context} model")
    coordinate = (arm, model)
    cell = summary_cells.get(coordinate)
    if cell is None:
        raise ValueError(f"{context} arm/model is outside the campaign")
    if record["campaign_cell_id"] != cell["id"]:
        raise ValueError(f"{context} campaign cell id changed")
    if record["raw_checkpoint_path"] != cell["output_path"]:
        raise ValueError(f"{context} checkpoint path conflicts with campaign summary")
    if record["run_manifest_digest"] != cell["manifest_digest"]:
        raise ValueError(f"{context} manifest digest conflicts with campaign summary")
    model_contract = contract["models"][model]
    if record["provider"] != model_contract["provider"]:
        raise ValueError(f"{context} provider conflicts with campaign config")
    if record["system_model"] != model_contract["system_model"]:
        raise ValueError(f"{context} solver route conflicts with campaign config")
    _required_string(record["item_id"], f"{context} item_id")
    _required_string(record["base_case"], f"{context} base_case")
    _required_string(record["specialty"], f"{context} specialty")
    for name in ("trial", "raw_line_number"):
        value = record[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{context} {name} must be a positive integer")
    base_record = {name: record[name] for name in _BINDING_FIELDS}
    identity_digest = _sha256_json({"schema_version": BINDING_SCHEMA, **base_record})
    expected_opaque = "jh_" + _sha256_text(
        f"{REIDENTIFICATION_SCHEMA}\0{seed}\0{identity_digest}"
    )
    if not hmac.compare_digest(opaque_id, expected_opaque):
        raise ValueError(f"{context} opaque id does not match its frozen identity")
    expected_binding = _binding_digest(opaque_id, base_record)
    if not hmac.compare_digest(str(record["binding_digest"]), expected_binding):
        raise ValueError(f"{context} binding digest does not match its frozen identity")


def _verify_private_sources(
    records: Sequence[Mapping[str, Any]],
    *,
    contract: Mapping[str, Any],
) -> None:
    by_checkpoint: dict[Path, list[Mapping[str, Any]]] = defaultdict(list)
    by_manifest: dict[Path, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        by_checkpoint[Path(str(record["raw_checkpoint_path"])).resolve()].append(record)
        by_manifest[Path(str(record["run_manifest_path"])).resolve()].append(record)

    manifests: dict[Path, RunManifest] = {}
    for path, linked in by_manifest.items():
        content = _existing_file(path, "run manifest").read_bytes()
        expected_bytes = {str(row["run_manifest_sha256"]) for row in linked}
        expected_digests = {str(row["run_manifest_digest"]) for row in linked}
        if len(expected_bytes) != 1 or len(expected_digests) != 1:
            raise ValueError(f"{path} has inconsistent map commitments")
        _matching_hash(
            _sha256_bytes(content), next(iter(expected_bytes)), f"{path} bytes"
        )
        manifest = _manifest_from_bytes(content, path)
        if manifest.digest != next(iter(expected_digests)):
            raise ValueError(f"{path} canonical digest changed")
        if manifest.judge_hash is None:
            raise ValueError(f"{path} does not freeze a judge hash")
        _validate_disclosure_fields(
            manifest.selection,
            contract,
            context=f"{path} manifest selection",
        )
        _validate_bundle_hash_fields(
            manifest.selection,
            contract,
            context=f"{path} manifest selection",
        )
        _panel, panel_hash = _manifest_judge_panel(manifest)
        linked_panel_hashes = {str(row["judge_panel_sha256"]) for row in linked}
        if linked_panel_hashes != {panel_hash}:
            raise ValueError(f"{path} judge panel conflicts with the handoff map")
        manifests[path] = manifest
    if len({manifest.judge_hash for manifest in manifests.values()}) != 1:
        raise ValueError("strict handoff manifests do not share one judge hash")
    if len({manifest.prompt_hash for manifest in manifests.values()}) != 1:
        raise ValueError(
            "strict handoff manifests do not share one response prompt hash"
        )

    for path, linked in by_checkpoint.items():
        content = _existing_file(path, "raw checkpoint").read_bytes()
        expected_hashes = {str(row["raw_checkpoint_sha256"]) for row in linked}
        if len(expected_hashes) != 1:
            raise ValueError(f"{path} has inconsistent checkpoint commitments")
        _matching_hash(
            _sha256_bytes(content),
            next(iter(expected_hashes)),
            f"raw checkpoint {path} bytes",
        )
        lines = content.splitlines()
        identities: set[tuple[str, int]] = set()
        for record in linked:
            line_number = int(record["raw_line_number"])
            if line_number > len(lines):
                raise ValueError(f"{path}:{line_number} no longer exists")
            raw = _load_json_object(
                lines[line_number - 1], source=f"{path}:{line_number}"
            )
            item_id = str(record["item_id"])
            trial = int(record["trial"])
            manifest_path = Path(str(record["run_manifest_path"])).resolve()
            manifest = manifests[manifest_path]
            _validate_raw_result(
                raw,
                source=path,
                line_number=line_number,
                manifest_digest=manifest.digest,
                item_id=item_id,
                trial=trial,
            )
            _matching_hash(
                _sha256_json(raw["response"]),
                record["raw_response_sha256"],
                f"{path}:{line_number} response",
            )
            if manifest.benchmark_content_hash != record["benchmark_content_hash"]:
                raise ValueError(f"{path}:{line_number} benchmark content hash changed")
            if manifest.prompt_hash != record["prompt_hash"]:
                raise ValueError(f"{path}:{line_number} response prompt hash changed")
            if manifest.judge_hash != record["judge_hash"]:
                raise ValueError(f"{path}:{line_number} judge hash changed")
            if manifest.benchmark_arm != record["arm"]:
                raise ValueError(f"{path}:{line_number} benchmark arm changed")
            if manifest.model != record["system_model"]:
                raise ValueError(f"{path}:{line_number} solver route changed")
            if manifest.provider != record["provider"]:
                raise ValueError(f"{path}:{line_number} provider changed")
            arm_selection = _manifest_arm_selection(manifest, str(record["arm"]))
            item_ids = arm_selection.get("item_ids")
            if not isinstance(item_ids, (list, tuple)) or item_id not in item_ids:
                raise ValueError(
                    f"{path}:{line_number} item is outside manifest selection"
                )
            if not 1 <= trial <= manifest.trials:
                raise ValueError(f"{path}:{line_number} trial is outside the manifest")
            identity = (item_id, trial)
            if identity in identities:
                raise ValueError(f"{path} map duplicates raw response {identity}")
            identities.add(identity)


def _campaign_contract(config: Mapping[str, Any]) -> dict[str, Any]:
    campaign_id = _required_string(config.get("id"), "campaign id")
    campaign_mode = config.get("campaign_mode", "clinical-parity")
    if campaign_mode not in {"clinical-parity", "engineering-preliminary"}:
        raise ValueError("campaign config has an unsupported campaign_mode")
    engineering_preliminary = campaign_mode == "engineering-preliminary"
    arms_value = config.get("arms")
    models_value = config.get("models")
    judge_panel_value = config.get("judge_panel")
    if not isinstance(arms_value, list) or len(arms_value) != 2:
        raise ValueError("strict parity handoff requires exactly two campaign arms")
    if not isinstance(models_value, list) or not (
        1 <= len(models_value) <= 4
        if engineering_preliminary
        else 3 <= len(models_value) <= 4
    ):
        if engineering_preliminary:
            raise ValueError(
                "engineering judge handoff requires one to four campaign models"
            )
        raise ValueError(
            "strict parity handoff requires three or four campaign models"
        )
    if not isinstance(judge_panel_value, list):
        raise ValueError("strict parity handoff requires a frozen judge_panel")
    judge_panel = _normalize_judge_panel(judge_panel_value)
    arms: set[str] = set()
    arm_kinds: dict[str, str] = {}
    expected_bundle_hashes: dict[str, str] = {}
    for index, row in enumerate(arms_value, start=1):
        if not isinstance(row, Mapping):
            raise ValueError(f"campaign arm {index} must be an object")
        arm = _required_string(row.get("id"), f"campaign arm {index} id")
        if arm in arms:
            raise ValueError(f"duplicate campaign arm {arm!r}")
        kind = _required_string(row.get("kind"), f"campaign arm {index} kind")
        allowed_kinds = (
            {"reference", "engineering-generated"}
            if engineering_preliminary
            else {"reference", "generated"}
        )
        if kind not in allowed_kinds or kind in arm_kinds.values():
            raise ValueError(
                f"{campaign_mode} judge handoff has an invalid arm topology"
            )
        arms.add(arm)
        arm_kinds[arm] = kind
        expected_bundle_hashes[arm] = _require_sha256(
            row.get("expected_bundle_hash"),
            f"campaign arm {arm!r} expected_bundle_hash",
        )
    expected_kinds = (
        {"reference", "engineering-generated"}
        if engineering_preliminary
        else {"reference", "generated"}
    )
    if set(arm_kinds.values()) != expected_kinds:
        raise ValueError(
            f"{campaign_mode} judge handoff has an invalid arm topology"
        )
    generated_kind = (
        "engineering-generated" if engineering_preliminary else "generated"
    )
    generated_arm = next(
        arm for arm, kind in arm_kinds.items() if kind == generated_kind
    )
    readiness = config.get("readiness")
    if engineering_preliminary:
        if "readiness" in config or "readiness_artifacts" in config:
            raise ValueError(
                "engineering judge handoff must not contain clinical readiness"
            )
    elif (
        not isinstance(readiness, Mapping)
        or readiness.get("generated_bundle_hash")
        != expected_bundle_hashes[generated_arm]
    ):
        raise ValueError(
            "campaign readiness does not bind the generated expected_bundle_hash"
        )
    models: dict[str, dict[str, str]] = {}
    for index, row in enumerate(models_value, start=1):
        if not isinstance(row, Mapping):
            raise ValueError(f"campaign model {index} must be an object")
        model = _required_string(row.get("id"), f"campaign model {index} id")
        if model in models:
            raise ValueError(f"duplicate campaign model {model!r}")
        models[model] = {
            "provider": _required_string(
                row.get("provider"),
                f"campaign model {model!r} provider",
            ),
            "system_model": _required_string(
                row.get("model"),
                f"campaign model {model!r} route",
            ),
        }
    disclosure_value = config.get("provider_disclosure_authorization")
    disclosure: ProviderDisclosureAuthorization | None = None
    if disclosure_value is not None:
        if not isinstance(disclosure_value, Mapping):
            raise ValueError(
                "provider_disclosure_authorization must be an object or null"
            )
        disclosure = ProviderDisclosureAuthorization.from_dict(disclosure_value)
        if (
            not engineering_preliminary
            and isinstance(readiness, Mapping)
            and readiness.get("generated_bundle_hash")
            != disclosure.generated_bundle_hash
        ):
            raise ValueError(
                "provider-disclosure authorization does not bind the readiness bundle"
            )
        if (
            engineering_preliminary
            and expected_bundle_hashes[generated_arm]
            != disclosure.generated_bundle_hash
        ):
            raise ValueError(
                "provider-disclosure authorization does not bind the engineering bundle"
            )
        disclosure.validate_against(
            generated_bundle_hash=disclosure.generated_bundle_hash,
            access_classification=disclosure.access_classification,
            solver_providers=tuple({record["provider"] for record in models.values()}),
            judge_providers=tuple({record["provider"] for record in judge_panel}),
        )
    return {
        "campaign_id": campaign_id,
        "campaign_mode": campaign_mode,
        "engineering_preliminary": engineering_preliminary,
        "arms": arms,
        "expected_bundle_hashes": dict(sorted(expected_bundle_hashes.items())),
        "models": models,
        "judge_panel": judge_panel,
        "judge_ids": tuple(record["id"] for record in judge_panel),
        "judge_panel_hash": _sha256_json(list(judge_panel)),
        "generated_access_classification": (
            disclosure.access_classification if disclosure is not None else "public"
        ),
        "provider_disclosure_authorization": (
            disclosure.to_dict() if disclosure is not None else None
        ),
        "provider_disclosure_authorization_hash": (
            disclosure.digest if disclosure is not None else None
        ),
    }


def _campaign_summary_cells(
    summary: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    if summary.get("campaign") != contract["campaign_id"]:
        raise ValueError("campaign summary id conflicts with campaign config")
    if contract["engineering_preliminary"]:
        if (
            summary.get("campaign_mode") != "engineering-preliminary"
            or summary.get("claim_scope")
            != "synthetic-engineering-only-not-clinical-validation"
            or summary.get("release_eligible") is not False
            or summary.get("clinical_review_status") != "not_started"
        ):
            raise ValueError(
                "engineering campaign summary lost its non-clinical claim scope"
            )
    if summary.get("complete") is not True:
        raise ValueError("strict judge handoff requires a complete campaign")
    if summary.get("partial") not in (None, 0) or summary.get("failed") not in (
        None,
        0,
    ):
        raise ValueError("strict judge handoff rejects partial or failed campaigns")
    summary_panel = summary.get("judge_panel")
    if not isinstance(summary_panel, list):
        raise ValueError("campaign summary does not freeze its judge panel")
    if _normalize_judge_panel(summary_panel) != contract["judge_panel"]:
        raise ValueError("campaign summary judge panel conflicts with campaign config")
    summary_panel_hash = _require_sha256(
        summary.get("judge_panel_hash"),
        "campaign summary judge panel hash",
    )
    if not hmac.compare_digest(summary_panel_hash, contract["judge_panel_hash"]):
        raise ValueError(
            "campaign summary judge panel hash conflicts with campaign config"
        )
    _validate_disclosure_fields(
        summary,
        contract,
        context="campaign summary",
    )
    _validate_bundle_hash_fields(
        summary,
        contract,
        context="campaign summary",
    )
    cells_value = summary.get("cells")
    if not isinstance(cells_value, list):
        raise ValueError("campaign summary cells must be a list")
    cells: dict[tuple[str, str], Mapping[str, Any]] = {}
    for index, cell in enumerate(cells_value, start=1):
        if not isinstance(cell, Mapping):
            raise ValueError(f"campaign summary cell {index} must be an object")
        arm = _required_string(cell.get("arm"), f"campaign summary cell {index} arm")
        model = _required_string(
            cell.get("model"), f"campaign summary cell {index} model"
        )
        coordinate = (arm, model)
        if coordinate in cells:
            raise ValueError(f"campaign summary duplicates cell {coordinate}")
        if arm not in contract["arms"] or model not in contract["models"]:
            raise ValueError(f"campaign summary cell {coordinate} is outside config")
        if cell.get("status") != "succeeded":
            raise ValueError(f"campaign summary cell {coordinate} did not succeed")
        output_path = _existing_file(cell.get("output_path"), "campaign cell output")
        manifest_digest = _require_sha256(
            cell.get("manifest_digest"),
            f"campaign summary cell {coordinate} manifest digest",
        )
        cells[coordinate] = {
            **dict(cell),
            "id": _required_string(cell.get("id"), f"campaign summary cell {index} id"),
            "output_path": str(output_path),
            "manifest_digest": manifest_digest,
        }
    expected = {
        (arm, model) for arm in contract["arms"] for model in contract["models"]
    }
    if set(cells) != expected:
        raise ValueError(
            "campaign summary does not contain the exact configured arm-model panel"
        )
    return cells


def _validate_disclosure_fields(
    payload: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    context: str,
) -> None:
    for field in (
        "generated_access_classification",
        "provider_disclosure_authorization",
        "provider_disclosure_authorization_hash",
    ):
        if payload.get(field) != contract[field]:
            raise ValueError(f"{context} {field} conflicts with campaign config")


def _validate_campaign_scope_fields(
    payload: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    context: str,
) -> None:
    if not contract["engineering_preliminary"]:
        return
    expected = {
        "campaign_mode": "engineering-preliminary",
        "claim_scope": "synthetic-engineering-only-not-clinical-validation",
        "release_eligible": False,
        "clinical_review_status": "not_started",
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise ValueError(f"{context} {field} lost its engineering-only scope")


def _validate_bundle_hash_fields(
    payload: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    context: str,
) -> None:
    expected = contract["expected_bundle_hashes"]
    for field in ("expected_bundle_hashes", "bundle_hashes"):
        value = payload.get(field)
        if not isinstance(value, Mapping) or set(value) != set(expected):
            raise ValueError(
                f"{context} {field} does not contain the exact campaign arms"
            )
        normalized = {
            arm: _require_sha256(
                value[arm],
                f"{context} {field}.{arm}",
            )
            for arm in sorted(value)
        }
        if normalized != expected:
            raise ValueError(
                f"{context} {field} conflicts with campaign expected bundle hashes"
            )


def _manifest_from_bytes(content: bytes, path: Path) -> RunManifest:
    payload = _load_json_object(content, source=str(path))
    try:
        return RunManifest.from_dict(payload)
    except ValueError as exc:
        raise ValueError(f"{path} is not a valid run manifest: {exc}") from exc


def _normalize_judge_panel(values: Sequence[Any]) -> tuple[dict[str, Any], ...]:
    if isinstance(values, (str, bytes)) or not 1 <= len(values) <= 3:
        raise ValueError(
            "judge_panel must contain two or three pinned judges, or one "
            "canonical NOHARM composite judge"
        )
    allowed = {
        "id",
        "model",
        "provider",
        "expected_provider_model",
        "family",
        "settings",
    }
    panel: list[dict[str, Any]] = []
    ids: set[str] = set()
    families: set[str] = set()
    routes: set[tuple[str, str]] = set()
    for index, value in enumerate(values, start=1):
        if not isinstance(value, Mapping):
            raise ValueError(f"judge_panel entry {index} must be an object")
        if set(value) != allowed:
            missing = sorted(allowed - set(value))
            extra = sorted(set(value) - allowed)
            raise ValueError(
                f"judge_panel entry {index} fields differ; "
                f"missing={missing}, extra={extra}"
            )
        judge_id = _required_string(value["id"], f"judge_panel entry {index} id")
        model = _required_string(value["model"], f"judge_panel {judge_id} model")
        provider = _required_string(
            value["provider"],
            f"judge_panel {judge_id} provider",
        )
        expected_provider_model = _required_string(
            value["expected_provider_model"],
            f"judge_panel {judge_id} expected_provider_model",
        )
        family = _required_string(
            value["family"],
            f"judge_panel {judge_id} family",
        )
        settings = value["settings"]
        if not isinstance(settings, Mapping):
            raise ValueError(f"judge_panel {judge_id} settings must be an object")
        normalized_settings = _detach_json_object(settings)
        _canonical_json(normalized_settings)
        route = (provider, model)
        if judge_id in ids:
            raise ValueError(f"duplicate judge_panel id {judge_id!r}")
        if family.casefold() in families:
            raise ValueError(f"duplicate judge_panel family {family!r}")
        if route in routes:
            raise ValueError(f"duplicate judge_panel route {provider}/{model}")
        ids.add(judge_id)
        families.add(family.casefold())
        routes.add(route)
        panel.append(
            {
                "id": judge_id,
                "model": model,
                "provider": provider,
                "expected_provider_model": expected_provider_model,
                "family": family,
                "settings": normalized_settings,
            }
        )
    normalized = tuple(panel)
    if len(normalized) == 1:
        return (validate_canonical_noharm_panel_entry(normalized[0]),)
    return normalized


def normalize_judge_panel(
    values: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Validate a generic independent panel or canonical NOHARM composite."""
    return _normalize_judge_panel(values)


def _detach_json_object(value: Mapping[str, Any]) -> dict[str, Any]:
    def detach(child: Any) -> Any:
        if isinstance(child, Mapping):
            return {str(key): detach(nested) for key, nested in child.items()}
        if isinstance(child, Sequence) and not isinstance(child, (str, bytes)):
            return [detach(nested) for nested in child]
        return child

    detached = detach(value)
    assert isinstance(detached, dict)
    return detached


def _validate_judge_provenance(
    value: Any,
    *,
    expected: Mapping[str, Any],
    judge_runtime_hash: str,
    context: str,
) -> None:
    _exact_keys(value, _JUDGE_PROVENANCE_KEYS, f"{context} judge_provenance")
    for name in ("provider", "model", "provider_model"):
        actual = _required_string(
            value[name],
            f"{context} judge_provenance.{name}",
        )
        expected_name = "expected_provider_model" if name == "provider_model" else name
        if actual != expected[expected_name]:
            raise ValueError(
                f"{context} judge_provenance.{name} conflicts with the frozen panel"
            )
    _matching_hash(
        value["settings_sha256"],
        _sha256_json(expected["settings"]),
        f"{context} judge settings",
    )
    _matching_hash(
        value["judge_runtime_hash"],
        judge_runtime_hash,
        f"{context} judge runtime",
    )
    response_ids = value["provider_response_ids"]
    if isinstance(response_ids, (str, bytes)) or not isinstance(response_ids, list):
        raise ValueError(
            f"{context} judge_provenance.provider_response_ids must be a non-empty list"
        )
    normalized_ids = tuple(
        _required_string(
            response_id,
            f"{context} judge provider response id",
        )
        for response_id in response_ids
    )
    if not normalized_ids or len(set(normalized_ids)) != len(normalized_ids):
        raise ValueError(
            f"{context} judge provider response ids must be non-empty and unique"
        )
    cost = value["cost_usd"]
    if (
        isinstance(cost, bool)
        or not isinstance(cost, (int, float))
        or not math.isfinite(cost)
        or cost < 0
    ):
        raise ValueError(f"{context} judge cost_usd must be finite and non-negative")


def _validate_noharm_metrics(value: Any, *, context: str) -> None:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{context} metrics must be a non-empty object")
    unknown = sorted(set(value) - _NOHARM_METRICS)
    if unknown:
        raise ValueError(
            f"{context} contains non-canonical NOHARM metrics: {', '.join(unknown)}"
        )
    for name, supplied in value.items():
        if isinstance(supplied, bool) or not isinstance(supplied, (int, float)):
            raise ValueError(f"{context} metric {name!r} must be numeric")
        numeric = float(supplied)
        if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
            raise ValueError(
                f"{context} metric {name!r} must be finite and between 0 and 1"
            )


def validate_noharm_metrics(value: Any, *, context: str) -> None:
    """Validate strict canonical NOHARM metric names and unit-interval values."""
    _validate_noharm_metrics(value, context=context)


def _judge_panel(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not values:
        raise ValueError("expected judge panel must contain at least one judge")
    judges = tuple(_required_string(value, "judge panel entry") for value in values)
    if len(set(judges)) != len(judges):
        raise ValueError("expected judge panel must contain unique names")
    return judges


def _judged_paths(values: Sequence[str | Path]) -> tuple[Path, ...]:
    if isinstance(values, (str, bytes)) or not values:
        raise ValueError("strict conversion requires at least one judged result file")
    paths = tuple(_existing_file(value, "judged result") for value in values)
    if len(set(paths)) != len(paths):
        raise ValueError("judged result files must be unique")
    return tuple(sorted(paths))


def _binding_digest(opaque_id: str, record: Mapping[str, Any]) -> str:
    return _sha256_json(
        {
            "schema_version": BINDING_SCHEMA,
            "opaque_id": opaque_id,
            **{name: record[name] for name in _BINDING_FIELDS},
        }
    )


def _verify_artifact(value: Any, label: str) -> tuple[Path, bytes]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} commitment must be an object")
    _exact_keys(value, {"path", "sha256"}, f"{label} commitment")
    path = _existing_file(value["path"], label)
    content = path.read_bytes()
    _matching_hash(_sha256_bytes(content), value["sha256"], f"{label} bytes")
    return path, content


def _verify_judge_execution_manifest(
    judged_path: Path,
    *,
    judge_input_sha256: str,
    judge_panel: Sequence[Mapping[str, Any]],
    judge_runtime_hash: str,
) -> tuple[Path, str]:
    path = _existing_file(
        judged_path.with_name(judged_path.name + ".execution.json"),
        "judge execution manifest",
    )
    content = path.read_bytes()
    payload = _load_json_object(content, source=str(path))
    expected_keys = {
        "schema_version",
        "judge_input_sha256",
        "judge_panel",
        "judge_runtime_hash",
        "adapters",
        "max_cost_usd",
        "max_calls",
    }
    _exact_keys(payload, expected_keys, str(path))
    if payload["schema_version"] != "arisekit.noharm-parity-judge-execution.v1":
        raise ValueError(f"{path} has an unsupported judge execution schema")
    _matching_hash(
        payload["judge_input_sha256"],
        judge_input_sha256,
        f"{path} judge input",
    )
    panel_value = payload["judge_panel"]
    if not isinstance(panel_value, list):
        raise ValueError(f"{path} judge_panel must be a list")
    if _normalize_judge_panel(panel_value) != tuple(judge_panel):
        raise ValueError(f"{path} judge panel conflicts with the handoff")
    _matching_hash(
        payload["judge_runtime_hash"],
        judge_runtime_hash,
        f"{path} judge runtime",
    )
    adapters = payload["adapters"]
    expected_judges = {record["id"] for record in judge_panel}
    if not isinstance(adapters, Mapping) or set(adapters) != expected_judges:
        raise ValueError(f"{path} adapters do not match the frozen judge panel")
    for judge_id, record in adapters.items():
        _exact_keys(
            record,
            {"adapter_id", "code_sha256"},
            f"{path} adapter {judge_id}",
        )
        _required_string(record["adapter_id"], f"{path} adapter {judge_id} id")
        _require_sha256(
            record["code_sha256"],
            f"{path} adapter {judge_id} code hash",
        )
    max_cost = payload["max_cost_usd"]
    if (
        isinstance(max_cost, bool)
        or not isinstance(max_cost, (int, float))
        or not math.isfinite(max_cost)
        or max_cost <= 0
    ):
        raise ValueError(f"{path} max_cost_usd must be finite and positive")
    max_calls = payload["max_calls"]
    if isinstance(max_calls, bool) or not isinstance(max_calls, int) or max_calls < 1:
        raise ValueError(f"{path} max_calls must be positive")
    return path, _sha256_bytes(content)


def _matching_hash(actual: Any, expected: Any, label: str) -> None:
    actual_hash = _require_sha256(actual, f"{label} actual hash")
    expected_hash = _require_sha256(expected, f"{label} expected hash")
    if not hmac.compare_digest(actual_hash, expected_hash):
        raise ValueError(f"{label} does not match its frozen commitment")


def _required_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _existing_file(value: Any, label: str) -> Path:
    return existing_file(value, label, check_type=True)


def _output_path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise ValueError(f"{label} path must be a filesystem path")
    supplied = Path(value).expanduser()
    if supplied.is_symlink():
        raise ValueError(f"{label} output must not be a symlink")
    return supplied.resolve()


def _exact_keys(value: Any, expected: set[str], context: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"{context} fields differ; missing={missing}, extra={extra}")


def _load_json_object(content: bytes, *, source: str) -> dict[str, Any]:
    return strict_json_object(content, source, allow_bytes=True, allow_duplicate_keys=True)


def _jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join((_canonical_json(row) + "\n").encode("utf-8") for row in rows)


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_idempotent(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink():
            raise ValueError(f"refusing to replace symlink output {path}")
        if path.read_bytes() == content:
            return
        raise ValueError(f"refusing to overwrite non-identical handoff artifact {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != content:
                raise ValueError(
                    f"refusing to overwrite concurrent handoff artifact {path}"
                )
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "JUDGED_RESULT_SCHEMA",
    "JUDGE_INPUT_SCHEMA",
    "REIDENTIFICATION_SCHEMA",
    "JudgeCaseMaterial",
    "JudgeCheckpointSource",
    "PreparedJudgeHandoff",
    "ReidentifiedJudgedRecord",
    "VerifiedJudgeHandoff",
    "prepare_blinded_judge_handoff",
    "normalize_judge_panel",
    "validate_noharm_metrics",
    "verify_bound_judged_results",
]
