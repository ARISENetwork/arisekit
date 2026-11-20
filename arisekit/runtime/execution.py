"""One resumable execution substrate for ARISEKit operational chains.

Skills own decisions and write specifications.  This module owns the common
mechanics for synthetic generation, item emission, annotation execution, and
artifact return: dispatch, retry, append-only checkpoints, resume, lineage,
and JSON outputs.  Operation-specific handlers remain explicit callables.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from arisekit.common.files import atomic_write as _atomic_write
from arisekit.common.jsonio import (
    canonical_json as _canonical_json,
    freeze_json,
    strict_json_object,
    thaw_json as _thaw_json,
)
from arisekit.common.records import CanonicalPropertyRecord
from arisekit.common.validate import exact_fields, identifier, text as _text


SCHEMA_VERSION = "arisekit.execution-job.v1"
EVENT_SCHEMA_VERSION = "arisekit.execution-event.v1"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class JobKind(str, Enum):
    SYNTHESIS = "synthesis"
    ITEM_EMISSION = "item-emission"
    ANNOTATION = "annotation"
    ARTIFACT_RETURN = "artifact-return"


@dataclass(frozen=True)
class ExecutionTask:
    id: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        _identifier(self.id, "task.id")
        object.__setattr__(self, "payload", _freeze_json(self.payload, "task.payload"))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "payload": _thaw_json(self.payload)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionTask":
        _fields(data, {"id", "payload"}, "task")
        if not isinstance(data["payload"], Mapping):
            raise ValueError("task.payload must be an object")
        return cls(id=data["id"], payload=data["payload"])


@dataclass(frozen=True)
class ExecutionJob(CanonicalPropertyRecord):
    job_id: str
    kind: JobKind
    tasks: tuple[ExecutionTask, ...]
    input_artifacts: Mapping[str, str]
    parent_job_digest: str | None = None
    max_retries: int = 3
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION!r}")
        _identifier(self.job_id, "job_id")
        if not isinstance(self.kind, JobKind):
            try:
                object.__setattr__(self, "kind", JobKind(self.kind))
            except ValueError as exc:
                raise ValueError("kind is not a supported execution operation") from exc
        tasks = tuple(self.tasks)
        if not tasks:
            raise ValueError("tasks must not be empty")
        task_ids = [task.id for task in tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("tasks contain duplicate ids")
        object.__setattr__(self, "tasks", tasks)
        if (
            isinstance(self.max_retries, bool)
            or not isinstance(self.max_retries, int)
            or self.max_retries < 0
        ):
            raise ValueError("max_retries must be a non-negative integer")
        if self.parent_job_digest is not None and (
            not isinstance(self.parent_job_digest, str)
            or _SHA256_RE.fullmatch(self.parent_job_digest) is None
        ):
            raise ValueError("parent_job_digest must be a SHA-256 digest")
        artifacts: dict[str, str] = {}
        for name, digest in self.input_artifacts.items():
            key = _identifier(name, "input artifact name")
            if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
                raise ValueError(f"input artifact {key!r} must have a SHA-256 digest")
            artifacts[key] = digest
        object.__setattr__(
            self,
            "input_artifacts",
            MappingProxyType(dict(sorted(artifacts.items()))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "kind": self.kind.value,
            "tasks": [task.to_dict() for task in self.tasks],
            "input_artifacts": dict(self.input_artifacts),
            "parent_job_digest": self.parent_job_digest,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionJob":
        fields = {
            "schema_version",
            "job_id",
            "kind",
            "tasks",
            "input_artifacts",
            "parent_job_digest",
            "max_retries",
        }
        _fields(data, fields, "execution job")
        raw_tasks = data["tasks"]
        if not isinstance(raw_tasks, list):
            raise ValueError("tasks must be a list")
        inputs = data["input_artifacts"]
        if not isinstance(inputs, Mapping):
            raise ValueError("input_artifacts must be an object")
        return cls(
            schema_version=data["schema_version"],
            job_id=data["job_id"],
            kind=JobKind(data["kind"]),
            tasks=tuple(
                ExecutionTask.from_dict(task) if isinstance(task, Mapping) else _bad_task()
                for task in raw_tasks
            ),
            input_artifacts=inputs,
            parent_job_digest=data["parent_job_digest"],
            max_retries=data["max_retries"],
        )


@dataclass(frozen=True)
class ExecutionEvent:
    job_digest: str
    task_id: str
    attempt: int
    status: str
    output: Mapping[str, Any] | None = None
    output_sha256: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    schema_version: str = EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVENT_SCHEMA_VERSION:
            raise ValueError(f"event schema_version must be {EVENT_SCHEMA_VERSION!r}")
        if not isinstance(self.job_digest, str) or _SHA256_RE.fullmatch(self.job_digest) is None:
            raise ValueError("event job_digest must be a SHA-256 digest")
        _identifier(self.task_id, "event.task_id")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 1:
            raise ValueError("event.attempt must be a positive integer")
        if self.status not in {"succeeded", "failed"}:
            raise ValueError("event.status must be succeeded or failed")
        if self.status == "succeeded":
            if not isinstance(self.output, Mapping) or self.output_sha256 is None:
                raise ValueError("successful event requires output and output_sha256")
            frozen = _freeze_json(self.output, "event.output")
            object.__setattr__(self, "output", frozen)
            expected = hashlib.sha256(
                _canonical_json(_thaw_json(frozen)).encode("utf-8")
            ).hexdigest()
            if self.output_sha256 != expected:
                raise ValueError("event output_sha256 does not match output")
            if self.error_type is not None or self.error_message is not None:
                raise ValueError("successful event cannot contain error fields")
        else:
            if self.output is not None or self.output_sha256 is not None:
                raise ValueError("failed event cannot contain output")
            _text(self.error_type, "event.error_type")
            _text(self.error_message, "event.error_message")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_digest": self.job_digest,
            "task_id": self.task_id,
            "attempt": self.attempt,
            "status": self.status,
            "output": _thaw_json(self.output),
            "output_sha256": self.output_sha256,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionEvent":
        fields = {
            "schema_version",
            "job_digest",
            "task_id",
            "attempt",
            "status",
            "output",
            "output_sha256",
            "error_type",
            "error_message",
        }
        _fields(data, fields, "execution event")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True)
class ExecutionSummary:
    job_id: str
    kind: JobKind
    succeeded: int
    failed: int
    skipped: int
    event_path: Path
    outputs: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class ExecutionStatus:
    job_id: str
    job_digest: str
    kind: JobKind
    total: int
    succeeded: int
    retryable: int
    exhausted: int
    pending: int
    event_path: Path
    outputs: Mapping[str, Mapping[str, Any]]

    @property
    def complete(self) -> bool:
        return self.succeeded == self.total


ExecutionHandler = Callable[[ExecutionTask], Mapping[str, Any]]


class ResumableExecutor:
    """File-backed executor with append-only per-task checkpoints."""

    def __init__(self, root: str | Path, *, threads: int = 1):
        if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
            raise ValueError("threads must be a positive integer")
        self.root = Path(root)
        self.threads = threads
        self._handlers: dict[JobKind, ExecutionHandler] = {}

    def register(self, kind: JobKind, handler: ExecutionHandler) -> None:
        if not isinstance(kind, JobKind):
            kind = JobKind(kind)
        if not callable(handler):
            raise TypeError("execution handler must be callable")
        self._handlers[kind] = handler

    def run(self, job: ExecutionJob) -> ExecutionSummary:
        handler = self._handlers.get(job.kind)
        if handler is None:
            raise ValueError(f"no execution handler is registered for {job.kind.value!r}")
        job_root = self.root / job.job_id
        job_root.mkdir(parents=True, exist_ok=True)
        spec_path = job_root / "job.json"
        events_path = job_root / "events.jsonl"
        self._bind_job(spec_path, job)
        events = _load_events(events_path, job)
        completed = {
            task_id: event
            for task_id, event in events.items()
            if event.status == "succeeded"
        }
        pending = [
            task
            for task in job.tasks
            if task.id not in completed
            and (
                task.id not in events
                or events[task.id].attempt < job.max_retries + 1
            )
        ]
        lock = threading.Lock()

        def dispatch(task: ExecutionTask) -> ExecutionEvent:
            prior_attempt = events.get(task.id).attempt if task.id in events else 0
            last: ExecutionEvent | None = None
            for attempt in range(prior_attempt + 1, job.max_retries + 2):
                try:
                    raw_output = handler(task)
                    if not isinstance(raw_output, Mapping):
                        raise TypeError("execution handler must return a JSON object")
                    output = _thaw_json(_freeze_json(raw_output, "handler output"))
                    digest = hashlib.sha256(
                        _canonical_json(output).encode("utf-8")
                    ).hexdigest()
                    event = ExecutionEvent(
                        job_digest=job.digest,
                        task_id=task.id,
                        attempt=attempt,
                        status="succeeded",
                        output=output,
                        output_sha256=digest,
                    )
                except Exception as exc:  # noqa: BLE001
                    event = ExecutionEvent(
                        job_digest=job.digest,
                        task_id=task.id,
                        attempt=attempt,
                        status="failed",
                        error_type=type(exc).__name__,
                        error_message=str(exc) or type(exc).__name__,
                    )
                with lock:
                    _append_event(events_path, event)
                last = event
                if event.status == "succeeded":
                    return event
            assert last is not None
            return last

        new_events: dict[str, ExecutionEvent] = {}
        if self.threads == 1 or len(pending) <= 1:
            for task in pending:
                new_events[task.id] = dispatch(task)
        else:
            with ThreadPoolExecutor(max_workers=self.threads) as pool:
                futures = {pool.submit(dispatch, task): task.id for task in pending}
                for future in as_completed(futures):
                    new_events[futures[future]] = future.result()

        latest = {**events, **new_events}
        outputs = {
            task_id: event.output
            for task_id, event in latest.items()
            if event.status == "succeeded" and event.output is not None
        }
        return ExecutionSummary(
            job_id=job.job_id,
            kind=job.kind,
            succeeded=len(outputs),
            failed=sum(event.status == "failed" for event in latest.values()),
            skipped=len(completed),
            event_path=events_path,
            outputs=MappingProxyType(dict(sorted(outputs.items()))),
        )

    def load(self, job_id: str) -> ExecutionJob:
        """Load the immutable job specification bound under ``job_id``."""

        _identifier(job_id, "job_id")
        return load_execution_job(self.root / job_id / "job.json")

    def status(self, job: ExecutionJob) -> ExecutionStatus:
        """Inspect checkpoint state without dispatching or changing any files."""

        spec_path = self.root / job.job_id / "job.json"
        if not spec_path.is_file():
            raise ValueError(f"execution job is not submitted: {job.job_id}")
        stored = load_execution_job(spec_path)
        if stored.digest != job.digest:
            raise ValueError("job_id is bound to a different execution spec")
        event_path = spec_path.with_name("events.jsonl")
        events = _load_events(event_path, job)
        succeeded = 0
        retryable = 0
        exhausted = 0
        outputs: dict[str, Mapping[str, Any]] = {}
        for task in job.tasks:
            event = events.get(task.id)
            if event is None:
                continue
            if event.status == "succeeded":
                succeeded += 1
                assert event.output is not None
                outputs[task.id] = event.output
            elif event.attempt < job.max_retries + 1:
                retryable += 1
            else:
                exhausted += 1
        return ExecutionStatus(
            job_id=job.job_id,
            job_digest=job.digest,
            kind=job.kind,
            total=len(job.tasks),
            succeeded=succeeded,
            retryable=retryable,
            exhausted=exhausted,
            pending=len(job.tasks) - succeeded - retryable - exhausted,
            event_path=event_path,
            outputs=MappingProxyType(dict(sorted(outputs.items()))),
        )

    def _bind_job(self, path: Path, job: ExecutionJob) -> None:
        if path.exists():
            try:
                stored = load_execution_job(path)
            except (OSError, UnicodeError, ValueError) as exc:
                raise ValueError(f"cannot resume malformed execution job: {exc}") from exc
            if stored.digest != job.digest:
                raise ValueError("job_id is already bound to a different execution spec")
            return
        _atomic_write(path, (job.canonical_json + "\n").encode("utf-8"))


def _load_events(path: Path, job: ExecutionJob) -> dict[str, ExecutionEvent]:
    if not path.exists():
        return {}
    task_ids = {task.id for task in job.tasks}
    latest: dict[str, ExecutionEvent] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"malformed execution event line {line_number}") from exc
            if not isinstance(value, Mapping):
                raise ValueError(f"execution event line {line_number} is not an object")
            event = ExecutionEvent.from_dict(value)
            if event.job_digest != job.digest:
                raise ValueError("execution journal contains a different job digest")
            if event.task_id not in task_ids:
                raise ValueError("execution journal contains an unknown task id")
            previous = latest.get(event.task_id)
            if previous is not None and event.attempt <= previous.attempt:
                raise ValueError("execution journal attempts are not strictly increasing")
            latest[event.task_id] = event
    return latest


def _append_event(path: Path, event: ExecutionEvent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(_canonical_json(event.to_dict()) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_execution_job(path: str | Path) -> ExecutionJob:
    """Strictly load an execution job from canonical JSON."""

    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot load execution job: {exc}") from exc
    return ExecutionJob.from_dict(strict_json_object(text, "execution job"))


def _freeze_json(value: Any, path: str) -> Any:
    return freeze_json(value, path, sort_keys=True)


def _identifier(value: Any, label: str) -> str:
    return identifier(value, label, _ID_RE)


def _fields(data: Any, expected: set[str], label: str) -> None:
    exact_fields(data, expected, label, kind=None)


def _bad_task() -> ExecutionTask:
    raise ValueError("every task must be an object")


__all__ = [
    "EVENT_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "ExecutionEvent",
    "ExecutionJob",
    "ExecutionStatus",
    "ExecutionSummary",
    "ExecutionTask",
    "JobKind",
    "ResumableExecutor",
    "load_execution_job",
]
