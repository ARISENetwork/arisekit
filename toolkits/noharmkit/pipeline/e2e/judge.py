"""Judge stage: map each response onto the rubric. The judge never sees scores or harm fields."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from pipeline.backends import (
    API_BACKENDS,
    JUDGE_DEFAULT_EFFORT,
    REASONING_EFFORT_BACKENDS,
    canonical_backend,
    default_workers,
)
from pipeline.e2e.project import Pair, Project, passed, record_pair, sanitize_model
from pipeline.e2e.records import Item, JudgmentBindings, JudgmentReceipt, ResponseRecord
from pipeline.e2e.rubric import Rubric, Table
from pipeline.e2e import pipeline_v2_slots, text_v2, text_v2_runtime
from pipeline.skillrun import call_json, run_skill, skill_file, skill_prompt
from tools.score_answer_table import appropriate_rows
from arisekit.common.files import check_destination
from arisekit.common.hashing import sha256
from arisekit.common.jsonio import read_json, read_jsonl
from arisekit.common.llm import prompt_sha256
from arisekit.common.logs import log
from arisekit.common.schemas import nullable, omit_null_fields, schema_errors, schema_sha256, strict_schema

SKILL = "judge-answer-table"
# The versioned judge rules, kept apart from the contract so editing the contract never changes the judge's
# prompt; only a judge experiment updates this file.
RULES = skill_file(SKILL, "rules.md")
# Appended to the prompt when the provider enforces a strict schema (direct OpenAI).
FORMAT_INSTRUCTIONS = """
Provider output format: the supplied strict schema lists every Decision ID.
Use null for an unaddressed Decision and for unused optional fields. These null
fields are omitted before canonical validation and scoring. Do not invent mappings
to fill a field. Each evidence string must be one continuous verbatim span from
the response. For separated passages, copy the full span including intervening
text. Never concatenate disconnected excerpts or insert ellipses.
""".strip()


def judge_errors(out: dict[str, Any], table: Table, response: str, case_context: str = "",
                 adapter: ModuleType | None = None) -> list[str]:
    if text_v2.is_text_v2(table):
        adapter = adapter or text_v2_runtime.for_table(table)
        return adapter.scorer.judgment_errors(table, out, response, case_context)
    body = " ".join(response.split())  # whitespace-insensitive, so line breaks never break a quote
    decisions = {d["id"]: d for d in table["decisions"]}
    errors: list[str] = []

    def quoted(where: str, evidence: str) -> None:
        if " ".join(evidence.split()) not in body:
            errors.append(f"{where}: evidence not in the response: {evidence[:80]!r}")

    for did, dout in out["decisions"].items():
        if did not in decisions:
            errors.append(f"unknown Decision {did}")
            continue
        d = decisions[did]
        appropriate = {r["id"]: r for r in appropriate_rows(d)}
        row_ids = {r["id"] for r in d["recommendations"]}
        for rec in dout.get("recommended", []):
            if rec["rowId"] not in row_ids:
                errors.append(f"{did}: row {rec['rowId']} is not in this Decision")
                continue
            quoted(f"{did} {rec['rowId']}", rec["evidence"])
            row = appropriate.get(rec["rowId"])
            if row is None:
                continue
            if row.get("parts") and "partsPresent" not in rec:
                errors.append(f"{did} {rec['rowId']}: recommendation has parts; partsPresent is required")
            extra = set(rec.get("partsPresent", [])) - set(row.get("parts", []))
            if extra:
                errors.append(f"{did} {rec['rowId']}: partsPresent not in the recommendation: {sorted(extra)}")
        for i, u in enumerate(dout.get("unmatched", [])):
            quoted(f"{did} unmatched {i}", u["evidence"])
    for i, o in enumerate(out["offRubric"]):
        quoted(f"offRubric {i}", o["evidence"])
    return errors


def provider_schema(table: Table, adapter: ModuleType | None = None) -> dict[str, Any]:
    """The canonical judge schema in strict mode, its Decision map closed to this rubric's IDs."""
    if text_v2.is_text_v2(table):
        adapter = adapter or text_v2_runtime.for_table(table)
        return adapter.provider_schema(table)
    canonical = read_json(skill_file(SKILL, "schema.json"))
    decision = strict_schema(canonical["properties"]["decisions"]["additionalProperties"])
    schema = strict_schema(canonical)
    ids = [d["id"] for d in table["decisions"]]
    schema["properties"]["decisions"] = {
        "type": "object", "properties": {key: nullable(decision) for key in ids},
        "required": ids, "additionalProperties": False,
    }
    return schema


def rubric_labels(project: Project, case_ids: list[str], rubric: str) -> dict[str, str]:
    """The rubric label each case is judged against: `rubric` itself, except in a current-grading project, where
    every case uses its shared rubric and the first judging run records `rubric` as the project's base."""
    if getattr(text_v2_runtime.for_project(project), "FREEZE", None) != "pipeline-v2":
        return dict.fromkeys(case_ids, rubric)
    pipeline_v2_slots.prepare_base_rubric(project, case_ids, rubric, record=True)
    return {case_id: pipeline_v2_slots.shared_label(project, case_id) for case_id in case_ids}


def judge_problems(caseset: Path, written: list[Path]) -> list[str]:
    """Declared case/model/trial pairs that lack a response or a passing judgment from this invocation.

    ``judge`` still returns paths, including failure receipts; CLI callers use this to signal failure.
    """
    project = Project(caseset)
    expected = project.expected()
    receipts = {path.stem for path in written}
    models = project.model_names()
    problems = [] if models else ["provenance.json lists no response models"]
    problems += [f"{model}: judgment receipt for an undeclared response model" for model in sorted(receipts - set(models))]
    for model in models:
        problems += project.responses(model)[1]
        if gap := project.response_gap(model):
            problems.append(gap)
        if model not in receipts:
            problems.append(f"{model}: no judgment receipt from this invocation")
            continue
        judgments, invalid = project.passed_judgments(model)
        problems += invalid
        if missing := sorted(expected - set(judgments)):
            problems.append(f"{model}: no passing judgment for {missing}")
    return problems


@dataclass
class Judge:
    """One judge invocation: route, rubrics, and the request and receipt for each response."""
    project: Project
    rubric: str
    backend: str
    model: str
    reasoning_effort: str | None
    timeout: int | None
    items: dict[str, Item]
    tables: dict[str, dict[str, Any]]
    schemas: dict[str, dict[str, Any]] = field(init=False)
    canonical_schema: dict[str, Any] = field(init=False)
    call_kwargs: dict[str, Any] = field(init=False)
    adapter: ModuleType = field(init=False)
    labels: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.adapter = text_v2_runtime.for_project(self.project)
        self.provider_schema = getattr(self.adapter, "PROVIDER_SCHEMA", True)
        self.schemas = {base: provider_schema(table, self.adapter) for base, table in self.tables.items()
                        if self.provider_schema
                        and (self.backend == "openai" or self.backend == "openrouter" and text_v2.is_text_v2(table))}
        self.canonical_schema = read_json(skill_file(SKILL, "schema.json"))
        self.call_kwargs = {"reasoning_effort": self.reasoning_effort} if self.backend in REASONING_EFFORT_BACKENDS else {}
        if self.timeout is not None:
            self.call_kwargs["timeout"] = self.timeout

    def case_id(self, r: ResponseRecord) -> str:
        """The rubric's case. Equal to the item ID today; legacy perturbation variants map to their base case."""
        return self.items[r["id"]]["metadata"]["base_id"]

    def variables(self, r: ResponseRecord) -> dict[str, str]:
        base = self.case_id(r)
        if text_v2.is_text_v2(self.tables[base]):
            return self.adapter.variables(self.tables[base], self.project.case(base)["presentation"], r["response"])
        return {"case": self.project.case(base)["presentation"],
                "table": json.dumps(Rubric(self.tables[base]).for_judge(), indent=1),
                "response": r["response"], "judge_rules": RULES.read_text(encoding="utf-8")}

    def prompt(self, r: ResponseRecord, suffix: str = "") -> tuple[str, str]:
        if text_v2.is_text_v2(self.tables[self.case_id(r)]):
            return self.adapter.prompt(self.variables(r), self.adapter.FORMAT_INSTRUCTIONS if suffix else "")
        return skill_prompt(SKILL, self.variables(r), suffix)

    def canonical_for(self, r: ResponseRecord) -> dict[str, Any]:
        return self.adapter.canonical_schema() if text_v2.is_text_v2(self.tables[self.case_id(r)]) else self.canonical_schema

    def check(self, r: ResponseRecord, out: dict[str, Any]) -> list[str]:
        return judge_errors(out, self.tables[self.case_id(r)], r["response"],
                            self.project.case(self.case_id(r))["presentation"], self.adapter)

    def bindings(self, r: ResponseRecord) -> JudgmentBindings:
        base = self.case_id(r)
        return self.project.judgment_bindings(base, self.labels.get(base, self.rubric), self.tables[base],
                                              r["response"])

    def resume_problem(self, receipt: JudgmentReceipt, r: ResponseRecord) -> str | None:
        """Why a saved receipt cannot be kept on resume (direct OpenAI), or None. It must come from the same
        inputs, prompt, schema, and route, have a final status, and a pass must still pass every check."""
        config = {"backend": self.backend, "model": self.model,
                  "prompt_sha256": prompt_sha256(*self.prompt(r, FORMAT_INSTRUCTIONS))}
        provenance = receipt.get("provenance", {})
        # The codex and OpenRouter transports never record the effort they were given.
        if "reasoning_effort" in provenance:
            config["reasoning_effort"] = self.reasoning_effort
        if self.provider_schema:
            config |= {"json_schema_enforced": True, "json_schema_sha256": schema_sha256(self.schemas[self.case_id(r)])}
        if (any(receipt.get(key) != value for key, value in self.bindings(r).items())
                or any(provenance.get(key) != value for key, value in config.items())):
            return "resume receipt has changed inputs or configuration"
        if receipt.get("status") not in {"pass", "failed"}:
            return "resume receipt has unresolved status"
        if receipt["status"] == "pass" and (
                not passed(receipt) or schema_errors(self.canonical_for(r), receipt["judge"])
                or self.check(r, receipt["judge"])):
            return "resume receipt no longer passes evidence checks"
        return None

    def call(self, out: Path, r: ResponseRecord) -> JudgmentReceipt:
        base = self.case_id(r)
        table = self.tables[base]
        variables = self.variables(r)
        if text_v2.is_text_v2(table):
            strict = self.provider_schema and self.backend in {"openai", "openrouter"}
            system, prompt = self.prompt(r, FORMAT_INSTRUCTIONS if strict else "")
            outcome = call_json(self.backend, self.model, system, prompt, self.canonical_for(r),
                                check=lambda o: self.check(r, o), reject_duplicate_keys=True,
                                provenance={"profile": self.adapter.scorer.PROFILE,
                                            "judge": getattr(self.adapter, "JUDGE", "J1"),
                                            "toolingSourceCommit": self.adapter.SOURCE_COMMIT},
                                **({"json_schema": self.schemas[base], "normalize_output": omit_null_fields}
                                   if strict else {"normalize_output": self.adapter.restamp(table)}
                                   if hasattr(self.adapter, "restamp") else {}), **self.call_kwargs)
        else:
            outcome = run_skill(SKILL, variables, self.backend, self.model,
                            check=lambda o: judge_errors(o, table, r["response"]),
                            **({"json_schema": self.schemas[base], "prompt_suffix": FORMAT_INSTRUCTIONS,
                                "normalize_output": omit_null_fields} if self.backend == "openai" else {}),
                            **self.call_kwargs)
        response_id, trial = record_pair(r)
        log(f"judge {out.stem} {response_id} t{trial} {outcome.status}")
        provenance = {**outcome.provenance, "judge_model": sanitize_model(self.model),
                      **({"request_timeout_s": self.timeout} if self.timeout is not None else {})}
        return {"id": response_id, "trial": trial, **self.bindings(r), "status": outcome.status,
                "judge": outcome.output, "errors": outcome.errors, "raw": outcome.raw, "provenance": provenance}


def judge(caseset: Path, rubric: str, backend: str, model: str,
          reasoning_effort: str | None = JUDGE_DEFAULT_EFFORT, workers: int | None = None,
          resume: bool = False, timeout: int | None = None) -> list[Path]:
    backend = canonical_backend(backend)
    if workers is None:
        workers = default_workers(backend)
    project = Project(caseset)
    if timeout is None and backend in API_BACKENDS:
        timeout = getattr(text_v2_runtime.for_project(project), "JUDGE_TIMEOUT", 120)
    # Everything below is checked before any paid call: trials, case IDs, storage paths, and every response.
    project.expected()  # raises for an invalid trial count or a repeated case ID
    items = {i["id"]: i for i in project.items()}
    response_files = project.response_files()
    outputs = [project.judgments_path(path.stem) for path in response_files]
    if (existing := [str(path) for path in outputs if path.exists() or path.is_symlink()]) and not resume:
        raise ValueError(f"judgment receipts already exist: {existing}; preserve existing evidence and use a new project/run")
    for path in [*response_files, *outputs]:
        check_destination(project.root, path)
    ready_by_file, problems = {}, []
    for path in response_files:
        ready_by_file[path], found = project.responses(path.stem)
        problems += found
    if problems:
        raise ValueError("; ".join(problems))
    cases = dict.fromkeys(item["metadata"]["base_id"] for item in items.values())  # first-seen order, no repeats
    labels = rubric_labels(project, list(cases), rubric)
    tables = {base: project.table(base, labels[base]) for base in cases}
    job = Judge(project, rubric, backend, model, reasoning_effort, timeout, items, tables, labels=labels)

    # Resume (direct OpenAI): keep saved receipts that still hold up; judge only the rest.
    resumed: dict[Path, str] = {}  # receipt -> its digest when read, so a change during the calls is caught
    completed: dict[Path, set[Pair]] = {}
    for resp_file, out in zip(response_files, outputs):
        completed[out] = set()
        if not out.exists():
            continue
        resumed[out] = sha256(out.read_bytes())
        responses = ready_by_file[resp_file]
        for receipt in read_jsonl(out):
            pair = record_pair(receipt)
            if pair in completed[out] or pair not in responses:
                raise ValueError(f"resume receipt has duplicate or unexpected identity: {out} {pair}")
            if problem := job.resume_problem(receipt, responses[pair]):
                raise ValueError(f"{problem}: {out} {pair}")
            completed[out].add(pair)
    jobs = [(out, r) for resp_file, out in zip(response_files, outputs)
            for pair, r in ready_by_file[resp_file].items() if pair not in completed[out]]

    with ExitStack() as stack:
        receipts = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(job.call, out, record): out for out, record in jobs}
            for future in as_completed(futures):
                out = futures[future]
                if out not in receipts:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    if out in resumed and sha256(out.read_bytes()) != resumed[out]:
                        raise ValueError(f"resume receipt changed during calls: {out}")
                    # Resume appends to its own receipts; a fresh run never replaces another writer's file.
                    receipts[out] = stack.enter_context(out.open("a" if out in resumed else "x"))
                receipts[out].write(json.dumps(future.result()) + "\n")
                receipts[out].flush()
        for out in outputs:
            if not out.exists():
                out.parent.mkdir(parents=True, exist_ok=True)
                stack.enter_context(out.open("x"))
    return outputs
