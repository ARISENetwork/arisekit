from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from arisekit.runtime.execution import ExecutionJob, ExecutionTask, JobKind
from arisekit.runtime.execution_adapters import execute_job, load_receipt


def test_item_emission_writes_deterministic_resumable_jsonl(tmp_path: Path) -> None:
    job = ExecutionJob(
        job_id="emit-1",
        kind=JobKind.ITEM_EMISSION,
        tasks=(
            ExecutionTask(
                id="item-b",
                payload={
                    "item": {"id": "b", "prompt": "B"},
                    "output_path": "artifacts/items.jsonl",
                },
            ),
            ExecutionTask(
                id="item-a",
                payload={
                    "item": {"id": "a", "prompt": "A"},
                    "output_path": "artifacts/items.jsonl",
                },
            ),
        ),
        input_artifacts={"shape-spec": "a" * 64},
    )

    first = execute_job(tmp_path, job, threads=2)
    output = tmp_path / job.job_id / "artifacts" / "items.jsonl"
    assert output.read_text(encoding="utf-8") == (
        '{"id":"b","prompt":"B"}\n'
        '{"id":"a","prompt":"A"}\n'
    )
    assert first.artifacts[0]["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    receipt = load_receipt(tmp_path, job.job_id)
    assert receipt is not None
    assert receipt["status"] == "complete"

    second = execute_job(tmp_path, job)
    assert second.summary.skipped == 2
    assert output.read_text(encoding="utf-8").count("\n") == 2


def test_artifact_return_is_digest_bound_and_refuses_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"artifact")
    destination = tmp_path / "returned" / "artifact.bin"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    job = ExecutionJob(
        job_id="return-1",
        kind=JobKind.ARTIFACT_RETURN,
        tasks=(
            ExecutionTask(
                id="deliver",
                payload={
                    "source_path": str(source),
                    "destination_path": str(destination),
                    "sha256": digest,
                },
            ),
        ),
        input_artifacts={"artifact": digest},
    )

    result = execute_job(tmp_path / "jobs", job)
    assert destination.read_bytes() == b"artifact"
    assert result.artifacts[0]["sha256"] == digest
    assert execute_job(tmp_path / "jobs", job).summary.skipped == 1

    destination.write_bytes(b"changed")
    changed_job = ExecutionJob(
        job_id="return-2",
        kind=JobKind.ARTIFACT_RETURN,
        tasks=job.tasks,
        input_artifacts=job.input_artifacts,
        max_retries=0,
    )
    failed = execute_job(tmp_path / "jobs", changed_job)
    assert failed.summary.failed == 1
    assert destination.read_bytes() == b"changed"


@pytest.mark.parametrize("kind", [JobKind.SYNTHESIS, JobKind.ANNOTATION])
def test_external_json_service_adapters(kind: JobKind, tmp_path: Path) -> None:
    received: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers["Content-Length"])
            received.append(json.loads(self.rfile.read(length)))
            body = json.dumps({"accepted": True, "path": self.path}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        job = ExecutionJob(
            job_id=f"service-{kind.value}",
            kind=kind,
            tasks=(
                ExecutionTask(
                    id="task-1",
                    payload={
                        "endpoint": f"http://127.0.0.1:{server.server_port}/tasks",
                        "request": {"item_id": "case-1"},
                        "token_env": None,
                        "timeout_seconds": 2,
                    },
                ),
            ),
            input_artifacts={},
            max_retries=0,
        )
        result = execute_job(tmp_path, job)
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert result.summary.succeeded == 1
    assert received == [{"item_id": "case-1"}]
    assert result.summary.outputs["task-1"]["operation"] == kind.value
