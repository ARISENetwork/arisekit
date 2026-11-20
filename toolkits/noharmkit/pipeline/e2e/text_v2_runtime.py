"""Select an explicit prospective judge/scorer pin; unpinned projects remain legacy."""
from __future__ import annotations

import re
from types import ModuleType
from typing import TYPE_CHECKING, Any

from pipeline.e2e import noharm_p2_loader, text_v2

if TYPE_CHECKING:
    from pipeline.e2e.project import Project

CURRENT_COMMIT = "d734383670f0e8251f46fc3e800038f2a46db0d6"
PIPELINE_V2_COMMIT = noharm_p2_loader.SOURCE_COMMIT
PIN = "judge_scoring_source_commit"
# The pinned validator appends upstream decision numbers in parentheses to its messages.
DECISION_REF = re.compile(r" ?\(D\d{3}(?:, D\d{3})*\)")


class BoundRubric(dict[str, Any]):
    """Carry project runtime context without changing the serialized rubric or shared executor."""

    def __init__(self, record: dict[str, Any], adapter: ModuleType) -> None:
        super().__init__(record)
        self.judge_scoring_source_commit = adapter.SOURCE_COMMIT


def for_table(table: dict[str, Any]) -> ModuleType:
    return for_commit(table.judge_scoring_source_commit) if isinstance(table, BoundRubric) else text_v2


def for_project(project: Project) -> ModuleType:
    commit = project.provenance().get(PIN, text_v2.SOURCE_COMMIT)
    return for_commit(commit)


def for_commit(commit: str) -> ModuleType:
    if commit == text_v2.SOURCE_COMMIT:
        return text_v2
    if commit == CURRENT_COMMIT:
        from pipeline.e2e import text_v2_j22
        return text_v2_j22
    if commit == PIPELINE_V2_COMMIT:
        from pipeline.e2e import pipeline_v2
        return pipeline_v2
    raise ValueError(f"Unsupported text rubric judge/scorer source commit: {commit!r}; existing files were preserved")


def bindings(project: Project) -> dict[str, str]:
    adapter = for_project(project)
    return {} if adapter is text_v2 else adapter.bindings()


def readable(message: str) -> str:
    """A validator message for people: upstream decision numbers removed. Stored records keep the original."""
    return DECISION_REF.sub("", message)
