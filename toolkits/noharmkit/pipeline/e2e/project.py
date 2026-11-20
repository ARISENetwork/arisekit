"""Project storage: layout, cases, generated tables, rubric choice, provenance, and trials."""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.e2e.constants import KIT_ROOT
from pipeline.e2e.records import (Case, Item, JudgmentBindings, JudgmentReceipt, Provenance, ResponseRecord,
                                  RunStatus)
from pipeline.e2e.rubric import Table
from arisekit.common.files import check_destination
from arisekit.common.hashing import json_sha256, sha256
from arisekit.common.jsonio import json_text, read_json, read_jsonl
from arisekit.common.logs import now_iso

# Name rules: kind -> (pattern, description), checked on user input by tools/cli.py. The app mirrors these in app/lib (project-create.ts,
# clinician-review.ts REVIEWER_ID_PATTERN, caseset/paths.ts).
NAMES = {
    "case id": (r"[A-Za-z0-9_]+", "letters, digits, or underscores, with no hyphens"),
    "project name": (r"[a-z0-9][a-z0-9-]{0,63}", "1-64 lowercase letters, digits, or hyphens"),
    "reviewer": (r"[a-z0-9][a-z0-9-]{1,31}", "2-32 lowercase letters, digits, or hyphens"),
    "rating tag": (r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", "1-64 letters, digits, underscores, or hyphens"),
}
RUN_LABEL = re.compile(r"^run([1-9]\d*)$")
REVIEWED_LABEL = re.compile(rf"^reviewed-({NAMES['reviewer'][0]})$")


def projects_root(base_dir: Path | None = None, environ: Mapping[str, str] | None = None) -> Path:
    """Where projects live: NOHARM_PROJECTS (or the legacy NOHARM_CASESETS) if set, relative to the kit; otherwise
    projects/, falling back to a legacy casesets/ folder when only that one exists."""
    env = os.environ if environ is None else environ
    base = KIT_ROOT if base_dir is None else base_dir
    if configured := env.get("NOHARM_PROJECTS") or env.get("NOHARM_CASESETS"):
        return (base / configured).resolve()
    projects, legacy = base / "projects", base / "casesets"
    return (projects if projects.is_dir() or not legacy.is_dir() else legacy).resolve()


def sanitize_model(model_id: str) -> str:
    return re.sub(r"[/:]", "-", model_id)


Pair = tuple[str, int]


def record_pair(record: dict[str, Any]) -> Pair:
    """A response or judgment record's (case id, trial) identity; records without a trial are trial 1.
    A malformed identity raises ValueError, so it never becomes a coverage key."""
    case_id, trial = record.get("id"), record.get("trial", 1)
    if not isinstance(case_id, str) or not case_id:
        raise ValueError(f"record id must be a nonempty string, got {case_id!r}")
    if type(trial) is not int or trial < 1:  # bool is an int subclass, so check the exact type
        raise ValueError(f"record trial must be a positive integer, got {trial!r}")
    return case_id, trial


def _by_pair(records: list[Any], kind: str) -> tuple[dict[Pair, Any], list[str]]:
    """Records keyed by (case id, trial). Invalid identities and pairs that appear more than once are left out
    and reported, so conflicting records never silently collapse into one."""
    keyed, problems = [], []
    for record in records:
        try:
            keyed.append((record_pair(record), record))
        except ValueError as error:
            problems.append(f"invalid {kind} identity: {error}")
    counts = Counter(pair for pair, _ in keyed)
    if duplicates := sorted(pair for pair, count in counts.items() if count > 1):
        problems.append(f"duplicate {kind} for {duplicates}")
    return {pair: record for pair, record in keyed if counts[pair] == 1}, problems


def passed(receipt: dict[str, Any]) -> bool:
    """A judgment that can be scored: status pass, a judgment present, and no recorded errors."""
    return receipt.get("status") == "pass" and receipt.get("judge") is not None and not receipt.get("errors")


def _case_file(root: Path, folder: str, case_id: str, suffix: str = ".json") -> Path:
    path = root / folder / f"{case_id}{suffix}"
    check_destination(root, path)
    return path


def _read_source_case(path: Path, case_id: str) -> Case:
    """A supplied case file: a task (presentation) and solution (recommendations), both nonempty text."""
    case = read_json(path)
    if not isinstance(case, dict) or any(not isinstance(case.get(key), str) or not case[key].strip()
                                         for key in ("presentation", "recommendations")):
        raise ValueError(f"{case_id}: presentation and recommendations must be nonempty text")
    return case


def _item(case_id: str, case: Case) -> Item:
    """The items.jsonl row for a case: the task sent to evaluated models (metadata kept for stored projects)."""
    return {"id": case_id, "prompt": case["presentation"], "metadata": {
        "base_id": case_id, "perturb_id": None, "category": "baseline", "candidate_id": None, "open": False}}


@dataclass(frozen=True)
class Project:
    """A benchmark project folder and the files inside it."""
    root: Path

    # Layout
    @property
    def name(self) -> str:
        return self.root.name

    @property
    def items_path(self) -> Path:
        return self.root / "items.jsonl"

    @property
    def provenance_path(self) -> Path:
        return self.root / "provenance.json"

    @property
    def results(self) -> Path:
        return self.root / "results"

    @property
    def report_path(self) -> Path:
        return self.results / "report.md"

    def artifact(self, case_id: str, label: str, suffix: str = "json") -> Path:
        """answer-tables/<case>.<label>.<suffix>, e.g. label run1 or reviewed-dw, suffix status.json or raw.txt."""
        return _case_file(self.root, "answer-tables", case_id, f".{label}.{suffix}")

    def rubric_files(self, case_id: str, label: str) -> list[Path]:
        """Every file one generated rubric run can leave: table, status, committee ratings, raw model text."""
        return [self.artifact(case_id, label, suffix) for suffix in ("json", "status.json", "ratings.json", "raw.txt")]

    def history_dir(self, case_id: str, label: str) -> Path:
        """Where replaced failed attempts of a generated rubric are kept."""
        return self.root / "answer-tables" / "history" / f"{case_id}.{label}"

    def responses_path(self, name: str) -> Path:
        return self.results / "responses" / f"{name}.jsonl"

    def judgments_path(self, name: str) -> Path:
        return self.results / "judge" / f"{name}.jsonl"

    def scored_path(self, name: str) -> Path:
        return self.results / f"{name}_scored.jsonl"

    def rating_path(self, tag: str, case_id: str, label: str, rep: int) -> Path:
        return self.results / "ratings" / tag / f"{case_id}.{label}-rep{rep}.json"

    # Creating and importing
    @classmethod
    def create(cls, root: Path, trials: int = 1) -> Project:
        """Create an empty benchmark without replacing an existing project."""
        project = cls(root)
        root.mkdir(parents=True, exist_ok=False)
        (root / "cases").mkdir()
        project.items_path.write_text("")
        from pipeline.e2e.text_v2_runtime import PIPELINE_V2_COMMIT
        project.update_provenance(caseset_name=project.name, cases=[], trials=trials, created_at=now_iso(),
                                  judge_scoring_source_commit=PIPELINE_V2_COMMIT)
        return project

    def import_case(self, case_id: str, cases_dir: Path) -> None:
        """Copy one supplied case in and list its task as an item. Re-importing the same case does nothing;
        a changed case is refused so earlier results keep their inputs."""
        source = _case_file(cases_dir, "", case_id)
        target = _case_file(self.root, "cases", case_id)
        case = _read_source_case(source, case_id)
        check_destination(self.root, self.items_path)
        check_destination(self.root, self.provenance_path)
        items = self.items() if self.items_path.exists() else []
        item = _item(case_id, case)
        listed = [i for i in items if i["id"] == case_id]
        case_changed = target.exists() and read_json(target) != case
        if case_changed or (listed and listed != [item]):
            raise ValueError(f"{case_id}: changed imported item; preserve existing evidence and use a new project/run")
        if target.exists() and listed:
            return  # already imported
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json_text(case))
        if not listed:
            items.append(item)
        self.items_path.write_text("".join(json.dumps(i) + "\n" for i in items))
        source_folder = cases_dir.relative_to(KIT_ROOT) if cases_dir.is_relative_to(KIT_ROOT) else cases_dir
        self.update_provenance(caseset_name=self.name, cases=sorted(i["id"] for i in items), case_source=str(source_folder))

    # Provenance
    def provenance(self) -> Provenance:
        return read_json(self.provenance_path) if self.provenance_path.exists() else {}

    def update_provenance(self, **fields: Any) -> None:
        prov = self.provenance()
        prov.update(fields)
        prov["updated_at"] = now_iso()
        self.provenance_path.write_text(json_text(prov))

    def trials(self) -> int:
        """The declared trial count; older projects without one default to 1."""
        trials = self.provenance().get("trials", 1)
        if type(trials) is not int or trials < 1:  # bool is an int subclass, so check the exact type
            raise ValueError(f"project trials must be a positive integer, got {trials!r}")
        return trials

    def model_names(self) -> list[str]:
        """Declared response models as file names, in declaration order."""
        return [sanitize_model(model) for model in self.provenance().get("models", [])]

    # Cases and items
    def case(self, case_id: str) -> Case:
        return read_json(_case_file(self.root, "cases", case_id))

    def items(self) -> list[Item]:
        """items.jsonl rows. A repeated case ID raises ValueError, since every stage keys its work by case ID."""
        items = read_jsonl(self.items_path)
        counts = Counter(item["id"] for item in items)
        if duplicates := sorted(case_id for case_id, count in counts.items() if count > 1):
            raise ValueError(f"items.jsonl lists case IDs more than once: {duplicates}")
        return items

    def expected(self) -> set[Pair]:
        """Every declared (case id, trial) pair; raises ValueError for an invalid trial count or repeated case ID."""
        trials = self.trials()
        return {(item["id"], trial) for item in self.items() for trial in range(1, trials + 1)}

    # Rubrics
    def status(self, case_id: str, label: str) -> RunStatus:
        return read_json(self.artifact(case_id, label, "status.json"))

    def table(self, case_id: str, rubric: str) -> Table:
        """A rubric by label, only if its status file says pass."""
        if self.status(case_id, rubric)["status"] != "pass":
            raise ValueError(f"{case_id} {rubric} failed validation; see {self.artifact(case_id, rubric, 'status.json')}")
        table = read_json(self.artifact(case_id, rubric))
        # Reviewed rubrics are saved by the app with review provenance around the table.
        table = table["record"] if rubric.startswith("reviewed-") else table
        from pipeline.e2e import text_v2
        table = text_v2.unwrap(table)
        if text_v2.is_text_v2(table):
            if table["caseId"] != case_id:
                raise ValueError(f"{case_id} {rubric}: rubric case identity does not match")
            from pipeline.e2e.text_v2_runtime import BoundRubric, for_project, readable
            adapter = for_project(self)
            if errors := adapter.scoring_errors(table):
                raise ValueError("; ".join(map(readable, errors)))
            if adapter is not text_v2:
                table = BoundRubric(table, adapter)
        return table

    # Responses and judgments
    def response_files(self) -> list[Path]:
        return sorted((self.results / "responses").glob("*.jsonl"))

    def responses(self, name: str) -> tuple[dict[Pair, ResponseRecord], list[str]]:
        """Collected responses (text, no recorded error) by declared (case id, trial), and the problems that keep
        records out: non-text, an invalid identity, an undeclared pair, or a pair collected more than once."""
        path = self.responses_path(name)
        ready = [r for r in (read_jsonl(path) if path.is_file() else []) if r.get("response") and "error" not in r]
        problems = [f"invalid response for {r.get('id')!r}: expected text" for r in ready
                    if not isinstance(r["response"], str)]
        responses, invalid = _by_pair([r for r in ready if isinstance(r["response"], str)], "response")
        problems += invalid
        if extra := sorted(set(responses) - self.expected()):
            problems.append(f"unexpected response for {extra}")
        return {pair: r for pair, r in responses.items() if pair not in extra}, [f"{name}: {p}" for p in problems]

    def response_gap(self, name: str) -> str | None:
        """The coverage problem for declared case/trial pairs with no response, if any."""
        missing = sorted(self.expected() - set(self.responses(name)[0]))
        return f"{name}: no response for {missing}" if missing else None

    def judgments(self, name: str) -> list[JudgmentReceipt]:
        path = self.judgments_path(name)
        return read_jsonl(path) if path.is_file() else []

    def passed_judgments(self, name: str) -> tuple[dict[Pair, JudgmentReceipt], list[str]]:
        """Passing judgments by declared (case id, trial), and the problems that keep records out: a failed or
        unresolved judgment, an invalid identity, an undeclared pair, or a pair judged more than once."""
        receipts = self.judgments(name)
        problems = [f"failed or unresolved judgment for {r.get('id')!r} trial {r.get('trial', 1)!r}"
                    for r in receipts if not passed(r)]
        # Pairs are counted over every status-pass receipt, so one carrying errors still conflicts with a clean one.
        judgments, invalid = _by_pair([r for r in receipts if r.get("status") == "pass"], "judgment")
        problems += invalid
        if extra := sorted(set(judgments) - self.expected()):
            problems.append(f"unexpected judgment for {extra}")
        return ({pair: j for pair, j in judgments.items() if pair not in extra and passed(j)},
                [f"{name}: {p}" for p in problems])

    def judgment_bindings(self, case_id: str, rubric: str, table: Table, response: str) -> JudgmentBindings:
        """What a judgment is bound to: judge records it, and score requires it unchanged."""
        from pipeline.e2e import text_v2
        from pipeline.e2e import text_v2_runtime
        native = text_v2.is_text_v2(table)
        rubric_hash = text_v2_runtime.for_project(self).scorer.rubric_sha256(table) if native else json_sha256(table)
        adapter = text_v2_runtime.for_project(self)
        text_hash = {}
        if native and getattr(adapter, "FREEZE", None) == "pipeline-v2":
            from pipeline.e2e import pipeline_v2_slots
            text_hash = {"rubric_text_sha256": pipeline_v2_slots.text_sha256(table)}
        return {"caseId": case_id, "rubric": rubric, "rubric_sha256": rubric_hash,
                "response_sha256": sha256(response),
                "case_presentation_sha256": sha256(self.case(case_id)["presentation"]),
                **text_hash, **(text_v2_runtime.bindings(self) if native else {})}

    # Writing evidence
    def new_ratings(self, tag: str, case_id: str, label: str, repeats: int) -> list[Path]:
        """Receipt paths for `repeats` new ratings of one rubric; refuses a tag already used for it."""
        paths = [self.rating_path(tag, case_id, label, rep) for rep in range(1, repeats + 1)]
        for path in paths:  # before any call: a redirected folder or receipt would put evidence outside the project
            check_destination(self.root, path)
            check_destination(self.root, path.with_suffix(".receipts"), directory=True)
            check_destination(self.root, path.with_suffix(".md"))
        if existing := [q.name for p in paths for q in (p, p.with_suffix(".receipts"), p.with_suffix(".md")) if q.exists()]:
            raise FileExistsError(f"ratings already exist in {paths[0].parent}: {existing}; use a new --tag")
        paths[0].parent.mkdir(parents=True, exist_ok=True)
        return paths

    def write_new(self, path: Path, value: Any) -> None:
        """Create a file (JSON unless value is text) without replacing evidence created by another writer."""
        check_destination(self.root, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as receipt:
            receipt.write(value if isinstance(value, str) else json_text(value))
