"""Explicit original-task MedAgentBench binding; never infer a scorer from its name."""
from __future__ import annotations

import contextlib
import ast
import hashlib
import importlib
import importlib.util
import io
import json
import math
import re
from pathlib import Path
import sys
import uuid
from types import ModuleType, SimpleNamespace
from urllib.parse import urlparse

from arisekit.env.docker_fhir import DockerFHIRServer, digest, stable_resource
from arisekit.scorer import BaseScorer
from arisekit.sut import SystemUnderTest, SUTCheckpoint, SUTResponse
from arisekit.types import BenchmarkItem, Metric, Tool, Trajectory, Turn

NATIVE_IMAGE = "jyxsu6/medagentbench@sha256:3fb83d7ed71c5476f9eb6212bd440a909ef7505922bbc757dc488a8fc0701966"
TASK_FILE = "src/MedAgentBench/data/medagentbench/test_data_v2.json"
SCORER_FILE = "src/medagentbenchevals/refsol.py"
TASK_SHA = "b6e89b2ef82f1bef27c5778a644a8a66c7b25738bbd6a48d03ab3e5182df6ca8"
SCORER_SHA = "792bd2ed1d17e2d78df4242f741667be4c7ea0161d061c3de107982a3b1d7cc3"
FAMILIES = ("patient-identification", "age", "record-blood-pressure", "latest-magnesium",
    "magnesium-replacement", "average-glucose", "latest-glucose", "orthopedic-referral",
    "potassium-replacement", "latest-hba1c")
TOOL_MODULES = ("patient_search", "vitals_search", "observation_search", "medication_request_search",
    "medication_request_create", "service_request_create", "vitals_create",
    "procedure_search", "condition_search", "calculator", "finish")


def validate_calculator(expression):
    tree = ast.parse(expression, mode="eval")
    nodes = list(ast.walk(tree))
    if len(expression) > 2000 or len(nodes) > 128:
        raise ValueError("Calculator expression exceeds its execution bound")
    allowed = (ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Attribute, ast.Call, ast.keyword,
        ast.List, ast.Tuple, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
        ast.Mod, ast.Pow, ast.USub, ast.UAdd)
    attributes = {"date", "datetime", "timedelta", "timezone", "utc", "today", "now", "utcnow", "fromisoformat",
        "strptime", "fromtimestamp", "timestamp", "year", "month", "day", "days", "seconds", "microseconds",
        "total_seconds", "hour", "minute", "second", "ceil", "floor", "sqrt", "log", "log10", "log2", "exp",
        "fabs", "fsum", "prod", "pow", "pi", "e", "tau", "sin", "cos", "tan", "asin", "acos", "atan",
        "atan2", "degrees", "radians", "hypot", "copysign", "fmod", "remainder", "trunc"}
    for node in nodes:
        if not isinstance(node, allowed):
            raise ValueError("Calculator supports numeric arithmetic and approved math/date operations")
        if isinstance(node, ast.Name) and node.id not in {"math", "datetime", "Decimal", "sum"}:
            raise ValueError("Calculator name is unavailable")
        if isinstance(node, ast.Attribute) and node.attr not in attributes:
            raise ValueError("Calculator private attributes are unavailable" if node.attr.startswith("_") else "Calculator attribute is unavailable")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id not in {"sum", "Decimal"}:
            raise ValueError("Calculator function is unavailable")
        if isinstance(node, ast.keyword) and node.arg is None:
            raise ValueError("Calculator keyword expansion is unavailable")
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                if len(node.value) > 256:
                    raise ValueError("Calculator string is too long")
            elif type(node.value) not in (int, float) or not math.isfinite(node.value) or abs(node.value) > 1e12:
                raise ValueError("Calculator literal is outside its numeric bound")
        if isinstance(node, ast.BinOp):
            if any(isinstance(child, (ast.List, ast.Tuple)) or isinstance(child, ast.Constant) and isinstance(child.value, str)
                   for child in (node.left, node.right)):
                raise ValueError("Calculator sequence arithmetic is unavailable")
            if isinstance(node.op, ast.Pow):
                try:
                    exponent = ast.literal_eval(node.right)
                except (ValueError, TypeError):
                    raise ValueError("Calculator exponent must be a bounded literal") from None
                if type(exponent) not in (int, float) or abs(exponent) > 12 or any(
                    isinstance(child, ast.BinOp) and isinstance(child.op, ast.Pow)
                    for branch in (node.left, node.right) for child in ast.walk(branch)):
                    raise ValueError("Calculator exponent exceeds its execution bound")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_resource(resource):
    value = stable_resource(resource)
    # This image adds a new request-local fragment source to every POST. Native
    # create schemas cannot supply meta; URL provenance remains meaningful.
    meta = value.get("meta", {})
    if re.fullmatch(r"#[A-Za-z0-9]{16}", meta.get("source", "")):
        meta.pop("source")
    if not meta:
        value.pop("meta", None)
    return value


def native_wire_payload(payload):
    wire = json.loads(json.dumps(payload))
    if wire.get("resourceType") == "MedicationRequest":
        for dosage in wire.get("dosageInstruction", []):
            if isinstance(dosage.get("route"), str):
                dosage["route"] = {"text": dosage["route"]}
    if wire.get("resourceType") == "ServiceRequest" and isinstance(wire.get("note"), dict):
        wire["note"] = [wire["note"]]
    return wire


def native_state_digest(state):
    return digest({"writes": state["writes"], "history": state["history"], "wire_requests": state.get("wire_requests", [])})


def audit(source):
    source = Path(source).resolve()
    if sha(source / TASK_FILE) != TASK_SHA or sha(source / SCORER_FILE) != SCORER_SHA:
        raise ValueError("This source/scorer pair is not the audited original-v2 release; qualify a prospective profile")
    tasks = json.loads((source / TASK_FILE).read_text())
    expected = {f"task{category}_{index}" for category in range(1, 11) for index in range(1, 31)}
    if len(tasks) != 300 or {row["id"] for row in tasks} != expected:
        raise ValueError("Original-v2 must contain exactly 30 cases in each of ten families")
    paths = [source / TASK_FILE, source / SCORER_FILE, source / "src/medagentbenchevals/utils.py",
        source / "src/prompts/system.txt", source / "src/tool/base.py", source.parent / "fhir_isolation.py"]
    paths += [source / f"src/tool/{name}.py" for name in TOOL_MODULES]
    paths += [path for path in (source / "src/tool/__init__.py", source / "src/medagentbenchevals/__init__.py") if path.exists()]
    files = {(str(path.relative_to(source)) if path.is_relative_to(source) else "../fhir_isolation.py"): sha(path) for path in paths}
    return {"schema_version": "arisekit.medagent-native-binding.v1", "profile": "original-v2",
        "image": NATIVE_IMAGE, "files": files, "families": [
            {"category": index, "name": family, "cases": 30, "scorer": f"refsol.task{index}"}
            for index, family in enumerate(FAMILIES, 1)], "cases": 300,
        "default_wrapper_compatible": False,
        "default_wrapper_issue": "src/evals.py imports new_refsol, which implements different tasks in all ten categories",
        "agent": "ARISEKit tool loop with original native tools, system prompt and task message; not the original provider-specific agent",
        "adapter_sha256": sha(Path(__file__)), "calculator": "Bounded numeric arithmetic and approved math/date operations; reflection, general Python and unbounded expressions unavailable",
        "wire_normalization": {"MedicationRequest.dosageInstruction.route": "legacy string to CodeableConcept.text",
            "ServiceRequest.note": "legacy object to Annotation array; logical tool payload and submitted body retained separately"}}


def freeze(source, output):
    value = audit(source)
    output = Path(output)
    value["binding_sha256"] = digest(value)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and json.loads(output.read_text()) != value:
        raise ValueError("The binding file already contains a different release")
    output.write_text(json.dumps(value, indent=2) + "\n")
    return value


def verify(source, binding):
    expected = audit(source)
    if binding.get("binding_sha256") != digest(expected) or {k: v for k, v in binding.items() if k != "binding_sha256"} != expected:
        raise ValueError("Native source, tools, scorer, prompt or isolation adapter drifted from its binding")


def package_namespace(source):
    name = "_arisekit_native_" + uuid.uuid4().hex
    package = ModuleType(name)
    package.__path__ = [str(Path(source) / "src")]
    sys.modules[name] = package
    return name


def discard_namespace(name):
    for key in list(sys.modules):
        if key == name or key.startswith(name + "."):
            sys.modules.pop(key, None)


class NativeTransport:
    def __init__(self, base, history=None, writes=None):
        import requests
        self.session = requests.Session()
        self.base = base.rstrip("/")
        self.history = history if history is not None else []
        self.writes = writes if writes is not None else []
        self.wire_requests = []

    def request(self, method, url, **kwargs):
        parsed, base = urlparse(url), urlparse(self.base)
        if parsed.scheme != base.scheme or parsed.netloc != base.netloc or not parsed.path.startswith(base.path + "/"):
            raise ValueError("Native FHIR transport must stay on the isolated server")
        kwargs["timeout"] = 30
        kwargs["allow_redirects"] = False
        kwargs["headers"] = {**(kwargs.get("headers") or {}), "Cache-Control": "no-cache"}
        if method == "POST":
            logical = json.loads(json.dumps(kwargs.get("json")))
            self.history.append({"role": "agent", "content": f"POST {url}\n" + json.dumps(logical)})
            kwargs["json"] = native_wire_payload(logical)
        result = self.session.request(method, url, **kwargs)
        if method == "POST":
            self.wire_requests.append({"method": method, "url": url, "logical_tool_payload": logical,
                "submitted_fhir_payload": kwargs["json"], "status_code": result.status_code})
        result.raise_for_status()
        if 300 <= result.status_code < 400:
            raise ValueError("Native FHIR redirects are not allowed")
        if len(result.content) > 16 * 1024 * 1024:
            raise ValueError("Native FHIR response exceeds 16 MiB")
        if method == "POST":
            self.history.append({"role": "agent", "content": "POST request accepted"})
            self.writes.append(native_resource(result.json()))
        return result

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


def native_tools(source, transport):
    namespace = package_namespace(source)
    try:
        return _native_tools_in_namespace(namespace, transport)
    finally:
        # Tool closures retain their own globals; the import registry must not
        # share a transport across attempts or retain every attempt's models.
        discard_namespace(namespace)


def _native_tools_in_namespace(namespace, transport):
    tools = []
    for name in TOOL_MODULES:
        module = importlib.import_module(f"{namespace}.tool.{name}")
        if hasattr(module, "requests"):
            module.requests = transport
        original = module.create() if name in {"calculator", "finish"} else module.create(transport.base)
        schema = original.json_schema()
        def call(_original=original, **arguments):
            if _original.name == "calculator":
                validate_calculator(arguments["expression"])
            result = _original(_original.input_schema(**arguments))
            if _original.name == "calculator":
                from decimal import Decimal
                if isinstance(result, Decimal):
                    result = float(result)
                if type(result) not in (int, float) or not math.isfinite(result):
                    raise ValueError("Calculator must return a finite number")
            return result
        tools.append(Tool(original.name, original.description, schema["parameters"], call))
    return tools


def evaluate_native(source, task, trajectory, base):
    namespace = package_namespace(source)
    try:
        return _evaluate_in_namespace(namespace, task, trajectory, base)
    finally:
        discard_namespace(namespace)


def _evaluate_in_namespace(namespace, task, trajectory, base):
    module = importlib.import_module(f"{namespace}.medagentbenchevals.refsol")
    utils = importlib.import_module(f"{namespace}.medagentbenchevals.utils")
    utils.requests = NativeTransport(base)
    state = next((turn.content for turn in reversed(trajectory.turns) if turn.role == "native_environment"), None)
    if not state or not state["complete"]:
        raise ValueError("Native scoring requires a completed retained attempt")
    if state["state_sha256"] != native_state_digest(state):
        raise ValueError("Native outcome evidence checksum differs")
    result = SimpleNamespace(result=json.dumps(trajectory.final_response) if not isinstance(trajectory.final_response, str) else trajectory.final_response,
        history=[SimpleNamespace(**entry) for entry in state["history"]])
    function = getattr(module, task["id"].split("_")[0])
    with contextlib.redirect_stdout(io.StringIO()):
        return bool(function(task, result, base.rstrip("/") + "/"))


class NativeMedAgentSUT(SystemUnderTest):
    supports_turn_checkpoints = True
    supports_dispatch_accounting = True

    def __init__(self, source, binding, model, *, max_turns=8):
        from arisekit.runtime.agent_clients import LiteLLMAgentClient
        self.source = Path(source).resolve()
        verify(self.source, binding)
        self.binding = binding
        self.name = model
        self.model_route = model
        self.client = LiteLLMAgentClient(model, temperature=0, max_tokens=4096, timeout=120)
        self.tasks = {task["id"]: task for task in json.loads((self.source / TASK_FILE).read_text())}
        self.max_turns = max_turns
        self.system_prompt = (self.source / "src/prompts/system.txt").read_text()
        self.tools = native_tools(self.source, NativeTransport("http://127.0.0.1:1/fhir"))

    def respond(self, item, **kwargs):
        return self.respond_checkpointed(item, trial=1, **kwargs)

    def respond_checkpointed(self, item, *, trial, resume_from=None, on_checkpoint=None, **kwargs):
        from arisekit.agentic import run_agent
        verify(self.source, self.binding)
        if resume_from and resume_from.complete:
            trajectory = resume_from.response
            if not isinstance(trajectory, Trajectory):
                trajectory = Trajectory.from_dict(trajectory)
            return SUTResponse(response=trajectory, cost=trajectory.total_cost,
                tokens_in=trajectory.total_tokens_in, tokens_out=trajectory.total_tokens_out)
        spec = importlib.util.spec_from_file_location("_arisekit_native_isolation", self.source.parent / "fhir_isolation.py")
        isolation = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = isolation
        spec.loader.exec_module(isolation)
        image_id = isolation.inspect_image_id(NATIVE_IMAGE)
        saved, trajectory = None, None
        if resume_from:
            trajectory = resume_from.response if isinstance(resume_from.response, Trajectory) else Trajectory.from_dict(resume_from.response)
            saved = next((turn.content for turn in reversed(trajectory.turns) if turn.role == "native_environment"), None)
            if not saved or saved["binding_sha256"] != self.binding["binding_sha256"]:
                raise ValueError("Native checkpoint belongs to another release")
        with isolation.DockerFHIRServer(image=NATIVE_IMAGE, expected_image_id=image_id, startup_timeout=300) as container:
            server = DockerFHIRServer()
            server.base_url = container.api_base
            transport = NativeTransport(container.api_base)
            if saved:
                if saved["state_sha256"] != native_state_digest(saved):
                    raise ValueError("Native recovery evidence checksum differs")
                for resource in saved["writes"]:
                    # This image forbids client-assigned numeric IDs. Recreate writes in
                    # order and require its clean baseline to reproduce every identity.
                    payload = {key: value for key, value in resource.items() if key != "id"}
                    restored = server.request("POST", resource["resourceType"], payload)
                    if restored["id"] != resource["id"] or native_resource(restored) != native_resource(resource):
                        raise ValueError("Native clean baseline did not reproduce a retained write")
                transport.writes = [native_resource(resource) for resource in saved["writes"]]
                transport.wire_requests = saved.get("wire_requests", [])
                # The scorer compares exact URLs, so restored attempts rebind only the old local origin.
                transport.history = [{**entry, "content": entry["content"].replace(saved["base_url"], container.api_base)} for entry in saved["history"]]
            tools = native_tools(self.source, transport)
            retained = None
            def checkpoint(current, complete):
                nonlocal retained
                if complete and current.turns and current.turns[-1].role == "tool_result" and current.turns[-1].content.get("name") == "finish":
                    transport.history.append({"role": "agent", "content": "finish(" + json.dumps(current.final_response) + ")"})
                current.turns[:] = [turn for turn in current.turns if turn.role != "native_environment"]
                state = {"binding_sha256": self.binding["binding_sha256"], "image_id": image_id,
                    "base_url": container.api_base, "writes": transport.writes, "history": transport.history,
                    "wire_requests": transport.wire_requests, "restored_from_base_url": saved["base_url"] if saved else None,
                    "complete": complete}
                state["state_sha256"] = native_state_digest(state)
                current.turns.append(Turn("native_environment", json.loads(json.dumps(state))))
                retained = current
                if on_checkpoint:
                    on_checkpoint(SUTCheckpoint(response=current, sequence=len(current.turns), complete=False,
                        cost=current.total_cost, tokens_in=current.total_tokens_in, tokens_out=current.total_tokens_out,
                        provider_calls=sum(turn.role == "assistant" for turn in current.turns)))
            trajectory = run_agent(self.client, item, tools, max_iters=self.max_turns, system_prompt=self.system_prompt,
                initial_trajectory=trajectory, on_checkpoint=checkpoint, terminal_tool="finish")
            trajectory = retained or trajectory
            finished = any(turn.role == "tool_result" and turn.content.get("name") == "finish"
                and not isinstance(turn.content.get("result"), dict) for turn in trajectory.turns)
            passed = finished and evaluate_native(self.source, self.tasks[item.id], trajectory, container.api_base)
            trajectory.turns.append(Turn("native_verdict", {"binding_sha256": self.binding["binding_sha256"], "passed": passed}))
            if on_checkpoint:
                on_checkpoint(SUTCheckpoint(response=trajectory, sequence=len(trajectory.turns), complete=True,
                    cost=trajectory.total_cost, tokens_in=trajectory.total_tokens_in, tokens_out=trajectory.total_tokens_out))
            return SUTResponse(response=trajectory, cost=trajectory.total_cost,
                tokens_in=trajectory.total_tokens_in, tokens_out=trajectory.total_tokens_out)


class NativeMedAgentScorer(BaseScorer):
    def __init__(self, binding_sha256):
        self.binding_sha256 = binding_sha256

    def configuration(self):
        return {"kind": "native-medagent-original-v2", "binding_sha256": self.binding_sha256}

    def score_item(self, item, responses):
        values = []
        for row in responses:
            if row.error:
                values.append(0.0)
                continue
            trajectory = row.response if isinstance(row.response, Trajectory) else Trajectory.from_dict(row.response)
            verdict = next((turn.content for turn in reversed(trajectory.turns) if turn.role == "native_verdict"), None)
            if not verdict or verdict["binding_sha256"] != self.binding_sha256 or type(verdict["passed"]) is not bool:
                raise ValueError("Native score has no matching frozen scorer verdict")
            values.append(float(verdict["passed"]))
        return [Metric("native_pass_at_1", sum(values) / len(values), n=len(values))] if values else []
