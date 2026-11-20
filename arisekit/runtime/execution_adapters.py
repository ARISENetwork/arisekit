"""Operational adapters for the shared resumable execution substrate."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from arisekit.common.files import atomic_write
from arisekit.common.jsonio import strict_canonical_json, thaw_json
from arisekit.common.validate import sha256_hex as _digest, text
from arisekit.runtime.execution import (
    ExecutionJob,
    ExecutionSummary,
    ExecutionTask,
    JobKind,
    ResumableExecutor,
)


RECEIPT_SCHEMA_VERSION = "arisekit.execution-receipt.v1"
_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class OperationalExecution:
    summary: ExecutionSummary
    artifacts: tuple[Mapping[str, Any], ...]
    receipt_path: Path


def execute_job(
    root: str | Path,
    job: ExecutionJob,
    *,
    threads: int = 1,
) -> OperationalExecution:
    """Dispatch a job with the canonical adapters and materialize its receipt."""

    executor = ResumableExecutor(root, threads=threads)
    executor.register(job.kind, _handler_for(job.kind))
    summary = executor.run(job)
    artifacts: tuple[Mapping[str, Any], ...] = ()
    if summary.succeeded == len(job.tasks):
        if job.kind is JobKind.ITEM_EMISSION:
            artifacts = (_finalize_item_emission(executor.root, job, summary),)
        elif job.kind is JobKind.ARTIFACT_RETURN:
            artifacts = tuple(
                summary.outputs[task.id]
                for task in job.tasks
                if task.id in summary.outputs
            )
    receipt_path = _write_receipt(executor.root, job, summary, artifacts)
    return OperationalExecution(
        summary=summary,
        artifacts=artifacts,
        receipt_path=receipt_path,
    )


def load_receipt(root: str | Path, job_id: str) -> Mapping[str, Any] | None:
    """Read a job receipt when finalization has run."""

    path = Path(root) / job_id / "receipt.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load execution receipt: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ValueError("execution receipt must be a JSON object")
    if value.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise ValueError("execution receipt has an unsupported schema")
    return value


def _handler_for(kind: JobKind):
    if kind is JobKind.ITEM_EMISSION:
        return _emit_item
    if kind is JobKind.ARTIFACT_RETURN:
        return _return_artifact
    if kind is JobKind.SYNTHESIS:
        return lambda task: _json_service(task, operation="synthesis")
    if kind is JobKind.ANNOTATION:
        return lambda task: _json_service(task, operation="annotation")
    raise ValueError(f"unsupported execution job kind: {kind.value}")


def _emit_item(task: ExecutionTask) -> Mapping[str, Any]:
    _exact_fields(task.payload, {"item", "output_path"}, f"task {task.id} payload")
    item = task.payload["item"]
    if not isinstance(item, Mapping):
        raise ValueError(f"task {task.id} item must be an object")
    output_path = _safe_relative(task.payload["output_path"], "output_path")
    return {"item": _json_value(item), "output_path": output_path}


def _finalize_item_emission(
    root: Path,
    job: ExecutionJob,
    summary: ExecutionSummary,
) -> Mapping[str, Any]:
    output_paths = {
        str(summary.outputs[task.id]["output_path"])
        for task in job.tasks
    }
    if len(output_paths) != 1:
        raise ValueError("item-emission tasks must declare one shared output_path")
    relative = _safe_relative(output_paths.pop(), "output_path")
    job_root = root / job.job_id
    destination = job_root / relative
    payload = b"".join(
        (_canonical_json(summary.outputs[task.id]["item"]) + "\n").encode("utf-8")
        for task in job.tasks
    )
    _atomic_write(destination, payload)
    return _artifact(destination, path=relative, media_type="application/x-ndjson")


def _return_artifact(task: ExecutionTask) -> Mapping[str, Any]:
    _exact_fields(
        task.payload,
        {"source_path", "destination_path", "sha256"},
        f"task {task.id} payload",
    )
    source = Path(_text(task.payload["source_path"], "source_path")).expanduser()
    destination = Path(
        _text(task.payload["destination_path"], "destination_path")
    ).expanduser()
    expected = _digest(task.payload["sha256"], "sha256")
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"artifact-return source is missing or unsafe: {source}")
    payload = source.read_bytes()
    observed = hashlib.sha256(payload).hexdigest()
    if observed != expected:
        raise ValueError("artifact-return source digest does not match sha256")
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_file():
            raise ValueError(f"artifact-return destination is unsafe: {destination}")
        if destination.read_bytes() != payload:
            raise FileExistsError(
                f"artifact-return destination exists with different bytes: {destination}"
            )
    else:
        _atomic_write(destination, payload)
        try:
            shutil.copymode(source, destination)
        except OSError:
            pass
    return _artifact(
        destination,
        path=str(destination.resolve()),
        media_type="application/octet-stream",
    )


def _json_service(task: ExecutionTask, *, operation: str) -> Mapping[str, Any]:
    _exact_fields(
        task.payload,
        {"endpoint", "request", "token_env", "timeout_seconds"},
        f"task {task.id} payload",
    )
    endpoint = _text(task.payload["endpoint"], "endpoint")
    parsed = urllib.parse.urlsplit(endpoint)
    local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ValueError(f"{operation} endpoint must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{operation} endpoint cannot contain credentials")
    request_value = task.payload["request"]
    if not isinstance(request_value, Mapping):
        raise ValueError(f"{operation} request must be an object")
    token_env = task.payload["token_env"]
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "arisekit-execution/1",
    }
    if token_env is not None:
        name = _text(token_env, "token_env")
        if _ENV_RE.fullmatch(name) is None:
            raise ValueError("token_env must be an environment variable name")
        token = os.environ.get(name)
        if not token:
            raise ValueError(f"required service token environment variable is unset: {name}")
        headers["Authorization"] = f"Bearer {token}"
    timeout = task.payload["timeout_seconds"]
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
    ):
        raise ValueError("timeout_seconds must be a positive number")
    request = urllib.request.Request(
        endpoint,
        data=_canonical_json(request_value).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=float(timeout)) as response:
        payload = response.read()
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{operation} service returned invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{operation} service response must be an object")
    return {
        "operation": operation,
        "service_response": _json_value(value),
    }


def _write_receipt(
    root: Path,
    job: ExecutionJob,
    summary: ExecutionSummary,
    artifacts: tuple[Mapping[str, Any], ...],
) -> Path:
    status = "complete" if summary.succeeded == len(job.tasks) else "incomplete"
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "job_id": job.job_id,
        "job_digest": job.digest,
        "kind": job.kind.value,
        "status": status,
        "tasks": {
            "total": len(job.tasks),
            "succeeded": summary.succeeded,
            "failed": summary.failed,
            "resumed": summary.skipped,
        },
        "artifacts": list(artifacts),
    }
    path = root / job.job_id / "receipt.json"
    _atomic_write(path, (_canonical_json(receipt) + "\n").encode("utf-8"))
    return path


def _artifact(
    file_path: Path,
    *,
    path: str,
    media_type: str,
) -> Mapping[str, Any]:
    payload = file_path.read_bytes()
    return {
        "path": path,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
        "media_type": media_type,
    }


def _atomic_write(path: Path, payload: bytes) -> None:
    atomic_write(path, payload, make_parents=True)


def _canonical_json(value: Any) -> str:
    return strict_canonical_json(_thaw_json(value))


def _json_value(value: Any) -> Any:
    return json.loads(_canonical_json(value))


def _thaw_json(value: Any) -> Any:
    return thaw_json(value, copy_lists=True)


def _exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(
            f"{label} fields differ; missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def _safe_relative(value: Any, label: str) -> str:
    text = _text(value, label)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or "\\" in text or str(path) in {"", "."}:
        raise ValueError(f"{label} must be a safe relative POSIX path")
    return text


def _text(value: Any, label: str) -> str:
    return text(value, label, no_nul=True)


__all__ = [
    "OperationalExecution",
    "RECEIPT_SCHEMA_VERSION",
    "execute_job",
    "load_receipt",
]
