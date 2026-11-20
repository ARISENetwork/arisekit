"""Author, package and execute configurable Docker-backed FHIR evaluations."""
from __future__ import annotations

import copy
from dataclasses import dataclass
import json
import math
from pathlib import Path
import time
from typing import Any

from arisekit.agentic import AgentTurnOutput, run_agent
from arisekit.env.docker_fhir import (
    CATALOG, HAPI_IMAGE, HAPI_RELEASE, FHIR_VERSION, DockerFHIRServer,
    HTTPFHIREnvironment, canonical, digest, validate_policy, validate_seed,
)
from arisekit.authoring.fhir_generation import ConstraintPhase, ConstraintOperator
from arisekit.scorer import BaseScorer
from arisekit.sut import SystemUnderTest, SUTCheckpoint, SUTResponse
from arisekit.types import BenchmarkItem, Metric, Trajectory, Turn

BRIEF_SCHEMA = "arisekit.fhir-environment-brief.v1"
ENV_SCHEMA = "arisekit.fhir-docker-env.v1"
OUTCOME_SCHEMA = "arisekit.fhir-outcome.v1"
OPERATORS = ("exists", "not-exists", "count-equals", "equals")


def validate_brief(brief: dict) -> dict:
    brief = json.loads(canonical(brief))
    expected = {"schema_version", "id", "clinical_scope", "workflow", "evidence", "resources", "seed_bundle",
                "evaluation_criteria", "case_count", "limits", "data_classification"}
    if set(brief) != expected or brief["schema_version"] != BRIEF_SCHEMA:
        raise ValueError("unsupported FHIR brief fields or version")
    from arisekit.env.docker_fhir import ID
    if not isinstance(brief["id"], str) or not ID.fullmatch(brief["id"]):
        raise ValueError("brief id must be a portable FHIR id")
    for key in ("clinical_scope", "workflow", "evaluation_criteria"):
        if not isinstance(brief[key], str) or not brief[key].strip():
            raise ValueError(f"{key} is required")
    if not isinstance(brief["evidence"], dict) or not brief["evidence"] or any(
        not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not v.strip() for k, v in brief["evidence"].items()
    ):
        raise ValueError("evidence must map source ids to public/synthetic excerpts")
    if brief["data_classification"] not in ("public", "synthetic"):
        raise ValueError("this FHIR adapter supports public or synthetic charts")
    validate_policy(brief["resources"])
    validate_seed(brief["seed_bundle"], brief["resources"])
    if type(brief["case_count"]) is not int or not 1 <= brief["case_count"] <= 24:
        raise ValueError("case_count must be between 1 and 24")
    limits = brief["limits"]
    bounds = {"max_turns": 64, "max_tool_calls": 256, "attempt_seconds": 3600,
              "max_calls": 10000, "max_cost": 10000, "max_cost_per_call": 1000}
    if not isinstance(limits, dict) or set(limits) != set(bounds):
        raise ValueError("limits must include max_turns, max_tool_calls, attempt_seconds, max_calls, max_cost, max_cost_per_call")
    for key, upper in bounds.items():
        if type(limits[key]) not in (int, float) or not 0 < limits[key] <= upper:
            raise ValueError(f"{key} must be positive and at most {upper}")
    if any(type(limits[key]) is not int for key in ("max_turns", "max_tool_calls", "max_calls")):
        raise ValueError("turn and call limits must be integers")
    if limits["max_cost_per_call"] > limits["max_cost"]:
        raise ValueError("per-call cost cannot exceed the total bound")
    return brief


def generation_request(brief: dict) -> BenchmarkItem:
    brief = validate_brief(brief)
    example = {
        "name": "Short benchmark name", "task": "Clinical or operational task definition",
        "cases": [{"id": "case-1", "instruction": "Task with patient id and requested outcome; no answer leak",
                   "source_ids": list(brief["evidence"]),
                   "predicates": [{"phase": "terminal", "resource_type": "Task", "where": {"status": "requested"},
                                   "path": ".", "operator": "count-equals", "expected": 1}],
                   "answer_json": None,
                   "reference_actions": [{"name": "fhir_search", "arguments": {"resource_type": "Observation", "params": {"patient": "p1"}}}]}],
    }
    prompt = {"brief": brief, "output_contract": example, "instructions": [
        "Design novel runnable clinical/operational tasks from the frozen scope, workflow, evidence and evaluation criteria. Return JSON only, no executable code.",
        "Return exactly the top-level keys name, task and cases. Every case must contain all example fields. Every predicate needs phase, resource_type, where, path, operator and expected. Each reference_actions entry contains exactly name and arguments; put resource_type inside arguments for read/search/delete, never beside name. Do not echo output_contract or the brief.",
        "Each case uses exactly the provided seed_bundle. Do not invent or change seed resources. Use only allowed actions/resources. Instructions must identify the patient and request observable work; do not disclose reference answers or criteria that should remain hidden.",
        "Every source_ids entry must be an exact key from brief.evidence. The seed_bundle is tracked separately as chart provenance; do not add seed_bundle or chart resource IDs to source_ids.",
        "reference_actions is a deterministic executable positive control using fhir_read(resource_type,id), fhir_search(resource_type,params), fhir_create(resource), fhir_update(resource), fhir_delete(resource_type,id). Resources are FHIR R4 4.0.1. create omits id; update includes id. params values are strings; searches use actual FHIR parameters.",
        "Predicates use initial, terminal or delta phase. where maps dotted paths to exact values; * traverses arrays, e.g. code.coding.*.code. path selects a value using the same notation or '.' for the whole resource. Operators: exists, not-exists, count-equals, equals. count-equals counts selected resources. equals requires at least one selected resource and all selected values equal expected. delta selects resources created or changed since seed. All predicates use AND semantics.",
        "Read-only tasks must provide answer_json (a scalar, object or array); solvers must return that JSON value exactly. Write tasks need terminal/delta predicates that the initial state fails; answer_json can be null. The adapter derives the reference response from answer_json; do not repeat it as reference_answer. Do not use generated ids or server timestamps in predicates or answers.",
        "Vary the actual goals, resources and required actions; do not merely paraphrase tasks. Retain explicit source_ids. References are synthetic AI proposals, never expert approvals. If the requested task cannot be measured with this contract, return an error object naming the gap.",
    ]}
    return BenchmarkItem(id=brief["id"], prompt=canonical(prompt),
                         metadata={"candidate_kind": "docker-fhir", "fhir_brief": brief})


def _values(value, path):
    if path in ("", "."):
        return [value]
    parts = path.split(".")
    current = [value]
    for part in parts:
        next_values = []
        for child in current:
            if part == "*" and isinstance(child, list):
                next_values.extend(child)
            elif isinstance(child, dict) and part in child:
                next_values.append(child[part])
            elif isinstance(child, list) and part.isdecimal() and int(part) < len(child):
                next_values.append(child[int(part)])
        current = next_values
    return current


def _same_json(left, right):
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    if type(left) in (int, float) and type(right) in (int, float):
        return all(type(value) is int or math.isfinite(value) for value in (left, right)) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same_json(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def validate_condition(condition: dict, policy: dict):
    expected = {"schema_version", "seed_sha256", "predicates", "answer_json", "reference_actions", "reference_answer"}
    if not isinstance(condition, dict) or set(condition) != expected or condition["schema_version"] != OUTCOME_SCHEMA:
        raise ValueError("invalid FHIR outcome condition")
    if not isinstance(condition["predicates"], list) or not condition["predicates"] and condition["answer_json"] is None:
        raise ValueError("condition needs predicates or a JSON answer")
    for predicate in condition["predicates"]:
        if not isinstance(predicate, dict) or set(predicate) != {"phase", "resource_type", "where", "path", "operator", "expected"}:
            raise ValueError("invalid state predicate fields")
        ConstraintPhase(predicate["phase"])
        ConstraintOperator(predicate["operator"])
        if predicate["resource_type"] not in policy or predicate["operator"] not in OPERATORS:
            raise ValueError("unsupported predicate resource/operator")
        if not isinstance(predicate["where"], dict) or any(not isinstance(k, str) or not k for k in predicate["where"]):
            raise ValueError("predicate where must map dotted paths to values")
        if not isinstance(predicate["path"], str) or not predicate["path"]:
            raise ValueError("predicate path is required")
        if predicate["operator"] == "count-equals" and (type(predicate["expected"]) is not int or predicate["expected"] < 0):
            raise ValueError("count-equals expected must be a nonnegative integer")
    if not isinstance(condition["reference_actions"], list) or not condition["reference_actions"]:
        raise ValueError("executable reference_actions are required")
    if not isinstance(condition["reference_answer"], str):
        raise ValueError("reference_answer must be a string")
    catalog = {t.name: t for t in HTTPFHIREnvironment(None, _dummy_seed(policy), policy).tools()}
    from arisekit.package import _validate_tool_arguments
    for action in condition["reference_actions"]:
        if not isinstance(action, dict) or set(action) != {"name", "arguments"} or action["name"] not in catalog:
            raise ValueError("reference_actions entries must contain exactly name and arguments, with a selected fhir_ tool name; put resource_type inside arguments")
        _validate_tool_arguments(action["name"], action["arguments"], catalog[action["name"]].parameters, item_id="reference")
    canonical(condition)


def _dummy_seed(policy):
    return {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": {"resourceType": "Patient", "id": "p1"}}]}


def state_predicates(condition, initial, terminal):
    initial_index = {(r["resourceType"], r["id"]): r for r in initial}
    delta = [r for r in terminal if initial_index.get((r["resourceType"], r["id"])) != r]
    results = []
    for predicate in condition["predicates"]:
        state = {"initial": initial, "terminal": terminal, "delta": delta}[predicate["phase"]]
        selected = [r for r in state if r["resourceType"] == predicate["resource_type"] and all(
            any(_same_json(value, expected) for value in _values(r, path)) for path, expected in predicate["where"].items())]
        values = [v for r in selected for v in _values(r, predicate["path"])]
        operator, expected = predicate["operator"], predicate["expected"]
        results.append({"exists": bool(values), "not-exists": not values,
                        "count-equals": len(selected) == expected,
                        "equals": bool(values) and all(_same_json(v, expected) for v in values)}[operator])
    return results


def score_trajectory(item: BenchmarkItem, trajectory: Trajectory) -> dict:
    states = [t.content for t in trajectory.turns if t.role == "environment" and isinstance(t.content, dict)]
    if not states:
        return {"passed": False, "reason": "missing-environment-state"}
    state, condition = states[-1], item.ground_truth
    if state.get("seed_sha256") != condition["seed_sha256"] or not state.get("complete"):
        return {"passed": False, "reason": "unbound-or-incomplete-state"}
    initial, terminal = state["initial"], state["terminal"]
    if digest(initial) != state.get("initial_sha256") or digest(terminal) != state.get("terminal_sha256"):
        raise ValueError("retained FHIR state checksum mismatch")
    checks = state_predicates(condition, initial, terminal)
    answer_ok = True
    if condition["answer_json"] is not None:
        try:
            answer_ok = _same_json(json.loads(trajectory.final_response), condition["answer_json"])
        except (TypeError, ValueError):
            answer_ok = False
    initial_by_id = {(r["resourceType"], r["id"]): r for r in initial}
    terminal_by_id = {(r["resourceType"], r["id"]): r for r in terminal}
    permitted_seed_writes = set()
    permitted_creates = {}
    for action in condition["reference_actions"]:
        arguments = action["arguments"]
        if action["name"] == "fhir_update":
            resource = arguments["resource"]
            permitted_seed_writes.add((resource["resourceType"], resource["id"]))
        elif action["name"] == "fhir_delete":
            permitted_seed_writes.add((arguments["resource_type"], arguments["id"]))
        elif action["name"] == "fhir_create":
            rt = arguments["resource"]["resourceType"]
            permitted_creates[rt] = permitted_creates.get(rt, 0) + 1
    protected_unchanged = all(terminal_by_id.get(key) == value for key, value in initial_by_id.items() if key not in permitted_seed_writes)
    created = {}
    for key in terminal_by_id.keys() - initial_by_id.keys():
        created[key[0]] = created.get(key[0], 0) + 1
    created_within_plan = all(count <= permitted_creates.get(rt, 0) for rt, count in created.items())
    tool_errors = [t for t in trajectory.turns if t.role == "tool_result" and isinstance(t.content.get("result"), dict) and "error" in t.content["result"]]
    interacted = any(t.role == "tool_result" for t in trajectory.turns)
    return {"passed": all(checks) and answer_ok and protected_unchanged and created_within_plan and not state.get("policy_violations", 0) and not state.get("limit_exceeded", False) and interacted,
            "state_checks": checks, "answer_ok": answer_ok, "tool_errors": len(tool_errors), "interacted": interacted,
            "protected_seed_unchanged": protected_unchanged, "created_count_within_plan": created_within_plan}


class FHIROutcomeScorer(BaseScorer):
    rescore_safe = True

    def configuration(self):
        return {"kind": "fhir-outcome"}

    def score_item(self, item, responses):
        values = [0.0 if r.error else float(score_trajectory(item, r.response)["passed"]) for r in responses]
        return [Metric("pass_at_1", sum(values) / len(values) if values else 0.0, n=len(values))]


class _ReferenceClient:
    model = "stub/reference"

    def __init__(self, condition):
        self.condition = condition

    def __call__(self, messages, tools):
        completed = sum(m["role"] == "tool" for m in messages)
        actions = self.condition["reference_actions"]
        if completed < len(actions):
            return AgentTurnOutput(tool_calls=[{"id": f"reference-{completed}", **actions[completed]}])
        return AgentTurnOutput(text=self.condition["reference_answer"])


class DockerFHIRAgentSUT(SystemUnderTest):
    supports_turn_checkpoints = True
    supports_dispatch_accounting = True

    def __init__(self, model, binding, *, system_prompt=None, temperature=None, max_tokens=None):
        from arisekit.runtime.agent_clients import LiteLLMAgentClient
        self.binding, self.system_prompt = binding, system_prompt
        self.name = model if isinstance(model, str) else getattr(model, "model", "fhir-agent")
        self.model_route = self.name
        self.reference = model == "stub/reference"
        self.max_iters = binding.max_turns
        self.client = LiteLLMAgentClient(model, temperature=temperature, max_tokens=max_tokens,
                                        timeout=binding.limits["attempt_seconds"]) if isinstance(model, str) and model != "stub/reference" else (_ReferenceClient(None) if self.reference else model)
        self.tools = binding.tools

    def respond(self, item, **kwargs):
        return self.respond_checkpointed(item, trial=1, **kwargs)

    def respond_checkpointed(self, item, *, trial, resume_from=None, on_checkpoint=None,
                             system_prompt=None, temperature=None, max_tokens=None):
        bundle = self.binding.bundles[item.id]
        seed_hash = digest(bundle)
        if item.ground_truth["seed_sha256"] != seed_hash:
            raise ValueError("case seed differs from frozen outcome")
        trajectory = None
        saved = None
        if resume_from:
            trajectory = (Trajectory.from_dict(resume_from.response.to_dict()) if isinstance(resume_from.response, Trajectory)
                          else Trajectory.from_dict(resume_from.response))
            saved = next((t.content for t in reversed(trajectory.turns) if t.role == "environment"), None)
            if not saved or saved["seed_sha256"] != seed_hash:
                raise ValueError("checkpoint seed differs from package")
            if resume_from.complete:
                score_trajectory(item, trajectory)
                return self._response(trajectory)
        import os
        from arisekit.env.process_fhir import ProcessFHIRServer
        server_factory = ProcessFHIRServer if os.environ.get("ARISEKIT_FHIR_RUNTIME") == "process" else DockerFHIRServer
        with server_factory() as server:
            env = HTTPFHIREnvironment(server, bundle, self.binding.policy)
            if saved:
                if digest(saved["terminal"]) != saved["terminal_sha256"]:
                    raise ValueError("checkpoint state checksum mismatch")
                env.seed(saved["terminal"])
                env.counter = saved["allocator"]
                initial = saved["initial"]
                elapsed = saved["elapsed_seconds"]
            else:
                env.seed()
                initial = env.snapshot()
                elapsed = 0
            started = time.monotonic()
            policy_violations = saved.get("policy_violations", 0) if saved else 0
            limit_exceeded = saved.get("limit_exceeded", False) if saved else False
            calls = sum(t.role == "tool_result" for t in trajectory.turns) if trajectory else 0
            tools = env.tools()
            def bounded(fn):
                def call(**arguments):
                    nonlocal calls, policy_violations, limit_exceeded
                    calls += 1
                    if calls > self.binding.limits["max_tool_calls"]:
                        limit_exceeded = True
                        raise RuntimeError("FHIR tool-call limit reached")
                    if elapsed + time.monotonic() - started > self.binding.limits["attempt_seconds"]:
                        limit_exceeded = True
                        raise RuntimeError("FHIR attempt time limit reached")
                    try:
                        return fn(**arguments)
                    except PermissionError:
                        policy_violations += 1
                        raise
                return call
            for tool in tools:
                tool.fn = bounded(tool.fn)
            retained = None
            def checkpoint(current, complete):
                nonlocal retained
                terminal = env.snapshot()
                current.turns[:] = [t for t in current.turns if t.role != "environment"]
                current.turns.append(Turn(role="environment", content={
                    "schema_version": ENV_SCHEMA, "seed_sha256": seed_hash,
                    "initial": initial, "terminal": terminal, "initial_sha256": digest(initial),
                    "terminal_sha256": digest(terminal), "allocator": env.counter,
                    "image": HAPI_IMAGE, "image_id": server.image_id, "fhir_version": FHIR_VERSION,
                    "runtime": getattr(server, "runtime_identity", {"kind": "docker", "image_id": server.image_id}),
                    "complete": complete, "elapsed_seconds": elapsed + time.monotonic() - started,
                    "trial": trial, "policy_violations": policy_violations,
                    "limit_exceeded": limit_exceeded or elapsed + time.monotonic() - started > self.binding.limits["attempt_seconds"],
                }))
                retained = current
                if on_checkpoint:
                    on_checkpoint(SUTCheckpoint(response=current, sequence=len(current.turns), complete=complete,
                        tokens_in=current.total_tokens_in, tokens_out=current.total_tokens_out, cost=current.total_cost,
                        provider_calls=sum(t.role == "assistant" for t in current.turns)))
            client = _ReferenceClient(item.ground_truth) if self.reference else self.client
            def bounded_client(messages, selected_tools):
                if elapsed + time.monotonic() - started > self.binding.limits["attempt_seconds"]:
                    raise RuntimeError("FHIR attempt time limit reached")
                return client(messages, selected_tools)
            traj = run_agent(bounded_client, item, tools, max_iters=self.binding.max_turns,
                             system_prompt=self.system_prompt or system_prompt or "Complete the task using the authorized FHIR tools. Return the requested answer.",
                             initial_trajectory=trajectory, on_checkpoint=checkpoint)
            return self._response(retained if retained is not None else traj)

    @staticmethod
    def _response(traj):
        return SUTResponse(response=traj, tokens_in=traj.total_tokens_in, tokens_out=traj.total_tokens_out,
                           cost=traj.total_cost, provider_model=None, finish_reason="stop")


@dataclass
class DockerFHIRBinding:
    bundles: dict
    policy: dict
    limits: dict

    @property
    def max_turns(self):
        return self.limits["max_turns"]

    @property
    def tools(self):
        return HTTPFHIREnvironment(None, next(iter(self.bundles.values())), self.policy).tools()

    def build_sut(self, model, **kwargs):
        return DockerFHIRAgentSUT(model, self, **kwargs)


def binding_from_package(pkg):
    env = pkg.env
    if set(env) != {"schema_version", "environment", "resources", "limits", "case_bindings", "tool_catalog", "tools"}:
        raise ValueError("invalid Docker FHIR environment fields")
    if env["environment"] != environment_spec() or env["tool_catalog"] != CATALOG:
        raise ValueError("Docker FHIR image, version or tool catalog drift")
    brief = pkg.manifest.provenance["fhir_brief"]
    validate_brief(brief)
    if env["resources"] != brief["resources"] or env["limits"] != brief["limits"]:
        raise ValueError("environment differs from frozen brief")
    if set(env["case_bindings"]) != {item.id for item in pkg.items}:
        raise ValueError("FHIR bindings must cover every item exactly")
    available = {path.relative_to(pkg.root).as_posix(): path for path in pkg.cohort}
    if set(env["case_bindings"].values()) != set(available) or len(set(env["case_bindings"].values())) != len(pkg.items):
        raise ValueError("FHIR cohort must have one asset per item")
    bundles = {}
    for item in pkg.items:
        relative = env["case_bindings"][item.id]
        if relative != f"cohort/{item.id}.fhir.json":
            raise ValueError("unexpected cohort asset path")
        bundle = json.loads(available[relative].read_text())
        validate_seed(bundle, env["resources"])
        # Package Bundle ids identify cases; the frozen seed may have another id.
        expected_bundle = {**brief["seed_bundle"], "id": item.id}
        if bundle != expected_bundle or digest(bundle) != item.ground_truth["seed_sha256"]:
            raise ValueError("FHIR seed differs from frozen brief")
        validate_condition(item.ground_truth, env["resources"])
        bundles[item.id] = bundle
    binding = DockerFHIRBinding(bundles, env["resources"], env["limits"])
    if env["tools"] != tool_schemas(binding.tools):
        raise ValueError("Docker FHIR tool schema drift")
    return binding


def environment_spec():
    return {"kind": "fhir-r4-docker", "primitive": "arisekit.env.docker_fhir.DockerFHIRServer",
            "fhir_version": FHIR_VERSION, "image": HAPI_IMAGE, "release": HAPI_RELEASE,
            "isolation": "per-item-trial", "database": "ephemeral-h2"}


def tool_schemas(tools):
    return [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in tools]


def compile_candidate(request, payload):
    from arisekit.generation.autonomous_generation import CompiledCandidate
    from arisekit.package import BenchmarkManifest
    brief = validate_brief(request.metadata["fhir_brief"])
    if request.to_dict() != generation_request(brief).to_dict():
        raise ValueError("FHIR request differs from frozen brief")
    if not isinstance(payload, dict) or set(payload) != {"name", "task", "cases"}:
        raise ValueError("candidate must contain name, task and cases")
    if any(not isinstance(payload[k], str) or not payload[k].strip() for k in ("name", "task")):
        raise ValueError("candidate name and task are required")
    if not isinstance(payload["cases"], list) or len(payload["cases"]) != brief["case_count"]:
        raise ValueError("candidate count differs from brief")
    items, bundles, ids = [], [], set()
    from arisekit.env.docker_fhir import ID
    derived_reference_answers = []
    for index, row in enumerate(payload["cases"]):
        required = {"id", "instruction", "source_ids", "predicates", "answer_json", "reference_actions"}
        if not isinstance(row, dict):
            raise ValueError(f"FHIR candidate cases[{index}] must be an object")
        missing, extra = required - row.keys(), row.keys() - required - {"reference_answer"}
        if missing or extra:
            raise ValueError(f"unexpected FHIR candidate case fields at cases[{index}]; "
                             f"missing: {canonical(sorted(missing))}; unexpected: {canonical(sorted(extra))}")
        if not isinstance(row["id"], str) or not ID.fullmatch(row["id"]) or row["id"] in ids:
            raise ValueError("duplicate or invalid case id")
        ids.add(row["id"])
        if not isinstance(row["instruction"], str) or not row["instruction"].strip():
            raise ValueError("case instruction is required")
        if (not isinstance(row["source_ids"], list) or not row["source_ids"]
                or any(not isinstance(s, str) or s not in brief["evidence"] for s in row["source_ids"])):
            raise ValueError("case source ids must resolve to frozen evidence; allowed source_ids: "
                             + canonical(sorted(brief["evidence"]))
                             + ". seed_bundle is separate chart provenance, not an evidence source ID")
        bundle = {**copy.deepcopy(brief["seed_bundle"]), "id": row["id"]}
        reference_answer = row.get("reference_answer", canonical(row["answer_json"]) if row["answer_json"] is not None else "Done")
        if "reference_answer" not in row:
            derived_reference_answers.append(row["id"])
        elif row["answer_json"] is not None:
            try:
                matches = _same_json(json.loads(reference_answer), row["answer_json"])
            except (ValueError, TypeError):
                matches = False
            if not matches:
                raise ValueError(f"FHIR candidate cases[{index}].reference_answer differs from answer_json; "
                                 "omit reference_answer to derive its JSON representation")
        condition = {"schema_version": OUTCOME_SCHEMA, "seed_sha256": digest(bundle),
                     **{k: copy.deepcopy(row[k]) for k in ("predicates", "answer_json", "reference_actions")},
                     "reference_answer": reference_answer}
        validate_condition(condition, brief["resources"])
        if len(condition["reference_actions"]) >= brief["limits"]["max_turns"] or len(condition["reference_actions"]) > brief["limits"]["max_tool_calls"]:
            raise ValueError("reference actions do not fit execution limits")
        if condition["answer_json"] is None and all(state_predicates(condition,
            [e["resource"] for e in bundle["entry"]], [e["resource"] for e in bundle["entry"]])):
            raise ValueError("action outcome is already satisfied by initial state")
        answer = row["answer_json"]
        answer_type = "object" if isinstance(answer, dict) else "array" if isinstance(answer, list) else "boolean" if type(answer) is bool else "number" if type(answer) in (int, float) else "string"
        prompt = row["instruction"] + (f"\nReturn only a JSON {answer_type}." if answer is not None else "")
        items.append(BenchmarkItem(id=row["id"], prompt=prompt, ground_truth=condition,
                     metadata={"source_ids": row["source_ids"], "reference_origin": "synthetic", "clinical_scope": brief["clinical_scope"]}))
        bundles.append(bundle)
    binding = DockerFHIRBinding({i.id: b for i, b in zip(items, bundles)}, brief["resources"], brief["limits"])
    env = {"schema_version": ENV_SCHEMA, "environment": environment_spec(), "resources": brief["resources"],
           "limits": brief["limits"], "tool_catalog": CATALOG, "tools": tool_schemas(binding.tools),
           "case_bindings": {i.id: f"cohort/{i.id}.fhir.json" for i in items}}
    return CompiledCandidate(manifest=BenchmarkManifest(id=request.id, name=payload["name"], modality="agentic-fhir",
        scorer={"kind": "fhir-outcome"}, provenance={"fhir_brief": brief, "brief_sha256": digest(brief),
        "reference_origin": "synthetic", "task": payload["task"], "execution_status": "awaiting-docker-validation",
        "candidate_payload": copy.deepcopy(payload), "derived_reference_answer_case_ids": derived_reference_answers}), items=items, env=env, cohort_bundles=bundles)


def validation_controls(package, results, trials):
    """Check actual positive traces plus explicit derived null/mutation controls."""
    records = []
    for item in package.items:
        responses = [r for r in results.raw if r.id == item.id and not r.error]
        positives, negatives, hashes, extra_writes, unrelated_changes = [], [], [], [], []
        for result in responses:
            trajectory = result.response
            positives.append(score_trajectory(item, trajectory)["passed"])
            state = next(t.content for t in reversed(trajectory.turns) if t.role == "environment")
            hashes.append(state["terminal_sha256"])
            mutated = Trajectory.from_dict(copy.deepcopy(trajectory.to_dict()))
            if item.ground_truth["answer_json"] is not None:
                mutated.final_response = canonical({"__negative_control__": digest(item.ground_truth)})
            else:
                changed_state = next(t.content for t in reversed(mutated.turns) if t.role == "environment")
                changed_state["terminal"] = copy.deepcopy(changed_state["initial"])
                changed_state["terminal_sha256"] = digest(changed_state["terminal"])
            negatives.append(not score_trajectory(item, mutated)["passed"])
            original_state = state
            seed_keys = {(r["resourceType"], r["id"]) for r in original_state["initial"]}
            new_resources = [r for r in original_state["terminal"] if (r["resourceType"], r["id"]) not in seed_keys]
            if new_resources:
                extra = Trajectory.from_dict(copy.deepcopy(trajectory.to_dict()))
                extra_state = next(t.content for t in reversed(extra.turns) if t.role == "environment")
                duplicate = copy.deepcopy(new_resources[0]); duplicate["id"] = "negative-extra-resource"
                extra_state["terminal"].append(duplicate)
                extra_state["terminal_sha256"] = digest(extra_state["terminal"])
                extra_writes.append(not score_trajectory(item, extra)["passed"])
            permitted = {(a["arguments"]["resource"].get("resourceType"), a["arguments"]["resource"].get("id"))
                         for a in item.ground_truth["reference_actions"] if a["name"] == "fhir_update"}
            permitted.update((a["arguments"]["resource_type"], a["arguments"]["id"])
                             for a in item.ground_truth["reference_actions"] if a["name"] == "fhir_delete")
            protected = next((r for r in original_state["terminal"] if (r["resourceType"], r["id"]) in seed_keys - permitted), None)
            if protected:
                changed = Trajectory.from_dict(copy.deepcopy(trajectory.to_dict()))
                changed_state = next(t.content for t in reversed(changed.turns) if t.role == "environment")
                resource = next(r for r in changed_state["terminal"] if (r["resourceType"], r["id"]) == (protected["resourceType"], protected["id"]))
                resource["language"] = "en" if resource.get("language") == "fr" else "fr"
                changed_state["terminal_sha256"] = digest(changed_state["terminal"])
                unrelated_changes.append(not score_trajectory(item, changed)["passed"])

        records.append({"id": item.id, "expected_positive_trials": trials,
                        "observed_positive_trials": len(positives), "positive_passes": sum(positives),
                        "derived_negative_rejections": sum(negatives),
                        "null_without_interaction_rejected": not score_trajectory(item, Trajectory())["passed"],
                        "terminal_state_reproduced": len(hashes) == trials and len(set(hashes)) == 1,
                        "extra_write_controls": {"tested": len(extra_writes), "rejected": sum(extra_writes)},
                        "unrelated_change_controls": {"tested": len(unrelated_changes), "rejected": sum(unrelated_changes)}})
    passed = all(row["positive_passes"] == trials and row["derived_negative_rejections"] == trials
                 and row["null_without_interaction_rejected"] and row["terminal_state_reproduced"]
                 and all(row[key]["tested"] == row[key]["rejected"] for key in ("extra_write_controls", "unrelated_change_controls")) for row in records)
    return {"schema_version": "arisekit.fhir-software-controls.v1", "passed": passed, "items": records,
            "scope": "Executable synthetic positive plans on independent Docker attempts; derived wrong-answer/reset-state and null controls. This checks software behavior, not clinical reliability."}
