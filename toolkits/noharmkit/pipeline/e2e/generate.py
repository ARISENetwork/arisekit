"""Generate stage: blind answer tables from the case and the expert answer."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from pipeline.answer_table_checks import TESTING, TREATMENT, table_errors
from pipeline.backends import REASONING_EFFORT_BACKENDS, Route, canonical_backend
from pipeline.e2e import committee as committee_module
from pipeline.e2e.constants import SKILLS_ROOT
from pipeline.e2e.project import Project
from pipeline.e2e.records import Case
from pipeline.skillrun import SkillOutcome, run_skill, skill_file, skill_prompt
from arisekit.common.files import check_destination
from arisekit.common.hashing import json_sha256, sha256
from arisekit.common.jsonio import read_json
from arisekit.common.logs import log
from arisekit.common.schemas import schema_errors

SKILL = "generate-answer-table"
# Freeze model input separately from human-facing implementation/status guidance.
CONTRACT = SKILLS_ROOT / SKILL / "contract-v1.md"
# Public authoring guidance included in model input.
GUIDE = SKILLS_ROOT / SKILL / "conversion-guide.md"


@dataclass
class Generation:
    """One case's generate stage: shared inputs, resume checks, and the files of each run."""
    project: Project
    case_id: str
    backend: str
    model: str
    committee: list[Route] | None
    backend_kwargs: dict[str, Any]
    case: Case = field(init=False)
    variables: dict[str, str] = field(init=False)
    identity: str = field(init=False)
    skill_name = SKILL
    native_format = "answer-table"

    def table_hash(self, record: Any) -> str:
        return json_sha256(record)

    def __post_init__(self) -> None:
        self.case = self.project.case(self.case_id)
        errors = self.case.get("errors", "")
        # Keys are the prompt template's placeholders; the dict is also part of the resume identity.
        self.variables = {"case_id": self.case_id, "case": self.case["presentation"],
                          "expert": self.case["recommendations"],
                          "errors": errors if isinstance(errors, str) else json.dumps(errors, ensure_ascii=False),
                          "contract": CONTRACT.read_text(), "guide": GUIDE.read_text()}
        self.identity = self._identity()

    def _identity(self) -> str:
        """Bind resume to inputs and skill bytes without altering any model prompt."""
        def skill_bytes(name: str) -> dict[str, str]:
            return {file: sha256(skill_file(name, file).read_bytes())
                    for file in ("system.md", "prompt.md", "schema.json")}

        identity = {"version": 1, "case_id": self.case_id, "case": self.case, "backend": self.backend,
                    "model": self.model, "variables": self.variables, "skill": skill_bytes(SKILL),
                    "prompt": skill_prompt(SKILL, self.variables)[1],
                    "committee": self.committee}
        if (reasoning_effort := self.backend_kwargs.get("reasoning_effort")) is not None:
            identity["reasoning_effort"] = reasoning_effort
        if self.committee is not None:
            identity["rating_skill"] = skill_bytes(committee_module.SKILL)
            identity["harm_scale"] = committee_module.harm_scale_text()
            # The rating schema and table projection are generated in this module.
            identity["rating_code"] = sha256(Path(committee_module.__file__).read_bytes())
        return json_sha256(identity)

    def check(self, record: Any) -> list[str]:
        """The generation gate: a valid table for this case, with both standard decisions and tagged recommendations."""
        if record.get("caseId") != self.case_id:
            return [f"caseId is {record.get('caseId')!r}, expected {self.case_id!r}"]
        errors = table_errors(record)
        if errors:
            return errors
        questions = {decision["question"] for decision in record["decisions"]}
        missing = [f"{self.case_id}: missing standard Decision {question!r}"
                   for question in (TESTING, TREATMENT) if question not in questions]
        untagged = [f"{row['id']}: new recommendations must include descriptive action tags "
                    "(use None for explicit no-action advice)"
                    for decision in record["decisions"] for row in decision["recommendations"] if not row.get("tags")]
        return missing + untagged

    def path(self, run: int, suffix: str = "json") -> Path:
        return self.project.artifact(self.case_id, f"run{run}", suffix)

    def check_storage(self, run: int) -> None:
        """Refuse a redirected run file or history folder before any call or move, so evidence stays in the project."""
        for path in self.project.rubric_files(self.case_id, f"run{run}"):
            check_destination(self.project.root, path)
        check_destination(self.project.root, self.project.history_dir(self.case_id, f"run{run}"), directory=True)

    def resumable(self, run: int) -> bool:
        """True for a saved pass from the same inputs whose table is unchanged on disk and still passes the gate.
        A pass that no longer holds stops the stage, touching nothing."""
        if not self.path(run, "status.json").exists():
            return False
        status = self.project.status(self.case_id, f"run{run}")
        if status["status"] != "pass":
            return False
        try:
            if status.get("generation_sha256") != self.identity:
                raise ValueError("missing or changed generation identity")
            table = read_json(self.path(run))
            if status.get("table_sha256") != self.table_hash(table):
                raise ValueError("missing or changed table binding")
            if errors := schema_errors(read_json(skill_file(self.skill_name, "schema.json")), table) or self.check(table):
                raise ValueError("; ".join(errors))
        except Exception as error:  # noqa: BLE001 a missing or unreadable table also refuses resume
            raise ValueError(f"Cannot resume {self.case_id} run{run}: {error}. Saved evidence was preserved.") from error
        return True

    def preserve_attempt(self, run: int) -> None:
        """Move opaque failed-attempt files aside before creating replacement evidence."""
        saved = [path for path in self.project.rubric_files(self.case_id, f"run{run}") if path.exists()]
        if not saved:
            return
        folder = self.project.history_dir(self.case_id, f"run{run}") / uuid4().hex
        folder.mkdir(parents=True, exist_ok=False)
        for path in saved:
            path.rename(folder / path.name)
        log(f"generate {self.case_id} run{run} preserved prior attempt at {folder}")

    def with_committee(self, run: int, draft: SkillOutcome) -> SkillOutcome:
        """Committee medians replace the draft's harms; the gate then validates the merged table."""
        if draft.status != "pass":
            return draft
        try:
            rated = committee_module.rate_table(self.case, draft.output, self.committee)
            draft_sha = json_sha256(draft.output)
            merged = committee_module.merge(draft.output, rated) if rated["status"] == "pass" else None
            # The viewer hides ratings unless they match the table on disk: the merged one when there is one.
            self.project.write_new(self.path(run, "ratings.json"), {
                "draft_sha256": draft_sha, "table_sha256": draft_sha if merged is None else json_sha256(merged), **rated})
            if merged is None:
                return SkillOutcome("failed", draft.output, draft.raw, rated["errors"], draft.provenance)
            errors = self.check(merged)
        except Exception as e:  # noqa: BLE001 recorded as a failed run, like skillrun's check errors
            return SkillOutcome("failed", draft.output, draft.raw, [f"committee: {type(e).__name__}: {e}"],
                                draft.provenance)
        return SkillOutcome("failed" if errors else "pass", merged, draft.raw, errors, draft.provenance)

    def write(self, run: int, outcome: SkillOutcome) -> None:
        if outcome.output is not None:
            self.project.write_new(self.path(run), outcome.output)
        if outcome.raw is not None:
            self.project.write_new(self.path(run, "raw.txt"), outcome.raw)
        self.project.write_new(self.path(run, "status.json"), {
            "status": outcome.status, "errors": outcome.errors, "provenance": outcome.provenance,
            "generation_sha256": self.identity,
            "table_sha256": self.table_hash(outcome.output) if outcome.output is not None else None})

    def run(self, run: int) -> str:
        log(f"generate {self.case_id} run{run} start ({self.backend}/{self.model})")
        if self.committee is None:
            outcome = run_skill(self.skill_name, self.variables, self.backend, self.model, check=self.check, **self.backend_kwargs)
        else:
            draft = run_skill(self.skill_name, self.variables, self.backend, self.model, **self.backend_kwargs)
            outcome = self.with_committee(run, draft)
        self.write(run, outcome)
        log(f"generate {self.case_id} run{run} {outcome.status} ({len(outcome.errors)} errors)")
        return outcome.status


def make_generation(project: Project, case_id: str, backend: str, model: str,
                    committee: list[Route] | None, backend_kwargs: dict[str, Any],
                    rubric_format: str = "text-v2") -> Generation:
    if rubric_format == "answer-table":
        return Generation(project, case_id, backend, model, committee, backend_kwargs)
    if rubric_format == "text-v2":
        from pipeline.e2e.generate_text_v2 import TextV2Generation
        return TextV2Generation(project, case_id, backend, model, committee, backend_kwargs)
    raise ValueError("rubric format must be text-v2 or answer-table")


def generate(caseset: Path, case_id: str, runs: int, backend: str, model: str, workers: int = 3,
             committee: list[Route] | None = None,
             reasoning_effort: str | None = None, rubric_format: str = "answer-table",
             start_run: int = 1) -> list[str]:
    if type(start_run) is not int or start_run < 1:
        raise ValueError("start_run must be a positive integer")
    backend = canonical_backend(backend)
    backend_kwargs = ({"reasoning_effort": reasoning_effort}
                      if backend in REASONING_EFFORT_BACKENDS and reasoning_effort is not None else {})
    gen = make_generation(Project(caseset), case_id, backend, model, committee, backend_kwargs, rubric_format)
    slots = range(start_run, start_run + runs)
    # Check every slot's storage and saved pass before any new call, move, or write, even when earlier slots are missing.
    for run in slots:
        gen.check_storage(run)
    passed = {run for run in slots if gen.resumable(run)}
    todo = [run for run in slots if run not in passed]
    for run in todo:
        gen.preserve_attempt(run)
    for run in sorted(passed):
        log(f"generate {case_id} run{run} already passed; skipped")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fresh = dict(zip(todo, pool.map(gen.run, todo)))
    return [fresh.get(k, "pass") for k in slots]
