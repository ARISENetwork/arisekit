from __future__ import annotations

from pathlib import Path

import pytest

from arisekit.runtime.execution import (
    ExecutionJob,
    ExecutionTask,
    JobKind,
    ResumableExecutor,
)


def _job() -> ExecutionJob:
    return ExecutionJob(
        job_id="batch-1",
        kind=JobKind.ITEM_EMISSION,
        tasks=(
            ExecutionTask(id="case-1", payload={"prompt": "A"}),
            ExecutionTask(id="case-2", payload={"prompt": "B"}),
        ),
        input_artifacts={"shape-spec": "a" * 64},
        max_retries=2,
    )


def test_executor_checkpoints_retries_and_resumes(tmp_path: Path) -> None:
    calls: dict[str, int] = {}

    def handler(task: ExecutionTask):
        calls[task.id] = calls.get(task.id, 0) + 1
        if task.id == "case-1" and calls[task.id] == 1:
            raise RuntimeError("transient")
        return {"item_id": task.id, "written": True}

    executor = ResumableExecutor(tmp_path, threads=2)
    executor.register(JobKind.ITEM_EMISSION, handler)
    first = executor.run(_job())

    assert first.succeeded == 2
    assert first.failed == 0
    assert calls == {"case-1": 2, "case-2": 1}
    assert first.event_path.read_text(encoding="utf-8").count("\n") == 3

    second = executor.run(_job())
    assert second.skipped == 2
    assert calls == {"case-1": 2, "case-2": 1}


def test_executor_binds_job_id_to_exact_spec(tmp_path: Path) -> None:
    executor = ResumableExecutor(tmp_path)
    executor.register(JobKind.ITEM_EMISSION, lambda task: {"ok": True})
    executor.run(_job())
    changed = ExecutionJob(
        job_id="batch-1",
        kind=JobKind.ITEM_EMISSION,
        tasks=(ExecutionTask(id="other", payload={}),),
        input_artifacts={"shape-spec": "a" * 64},
    )
    with pytest.raises(ValueError, match="different execution spec"):
        executor.run(changed)


@pytest.mark.parametrize("kind", list(JobKind))
def test_all_operational_chains_share_the_same_executor(tmp_path: Path, kind: JobKind) -> None:
    job = ExecutionJob(
        job_id=f"job-{kind.value}",
        kind=kind,
        tasks=(ExecutionTask(id="task-1", payload={}),),
        input_artifacts={},
    )
    executor = ResumableExecutor(tmp_path)
    executor.register(kind, lambda task: {"kind": kind.value})
    assert executor.run(job).outputs["task-1"]["kind"] == kind.value


def test_job_can_bind_parent_lineage() -> None:
    parent = _job()
    child = ExecutionJob(
        job_id="return-1",
        kind=JobKind.ARTIFACT_RETURN,
        tasks=(ExecutionTask(id="deliver", payload={}),),
        input_artifacts={"item-bundle": "b" * 64},
        parent_job_digest=parent.digest,
    )
    assert child.to_dict()["parent_job_digest"] == parent.digest


def test_interrupted_job_resumes_without_repeating_checkpointed_tasks(
    tmp_path: Path,
) -> None:
    job = ExecutionJob(
        job_id="interrupt-1",
        kind=JobKind.ITEM_EMISSION,
        tasks=tuple(
            ExecutionTask(id=f"case-{index}", payload={"index": index})
            for index in range(1, 4)
        ),
        input_artifacts={"shape-spec": "c" * 64},
        max_retries=1,
    )
    calls: list[str] = []

    def interrupt(task: ExecutionTask):
        calls.append(task.id)
        if task.id == "case-2":
            raise KeyboardInterrupt("deliberate interruption")
        return {"id": task.id}

    executor = ResumableExecutor(tmp_path, threads=1)
    executor.register(JobKind.ITEM_EMISSION, interrupt)
    with pytest.raises(KeyboardInterrupt, match="deliberate interruption"):
        executor.run(job)

    status = executor.status(job)
    assert status.succeeded == 1
    assert status.pending == 2
    assert calls == ["case-1", "case-2"]

    executor.register(JobKind.ITEM_EMISSION, lambda task: {"id": task.id})
    resumed = executor.run(job)
    assert resumed.succeeded == 3
    assert resumed.skipped == 1
    assert list(resumed.outputs) == ["case-1", "case-2", "case-3"]
    assert executor.load(job.job_id).digest == job.digest
