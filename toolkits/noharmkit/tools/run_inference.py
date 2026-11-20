"""Run model inference over a project's items.jsonl.

Records match the production run.py contract: {id, trial, response,
runtime, usage}; failures add "error". Resume verifies the model and assembled
prompt fingerprint before skipping successful (id, trial) pairs.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import backends
from pipeline.backends import resolve_route
from pipeline.e2e.project import Project, sanitize_model
from pipeline.e2e.response_prompts import UNPROMPTED_SHA256, load_prompts, set_id, set_prompt, set_template
from tools.cli import load_env, positive_int
from arisekit.common.hashing import json_sha256, sha256
from arisekit.common.jsonio import append_jsonl, read_jsonl
from arisekit.common.llm import LiteLLMBase


def assemble_prompt(template: str, item_prompt: str) -> str:
    tmpl = template.strip()
    return f"{tmpl}\n\n{item_prompt}" if tmpl else item_prompt


class InferenceClient(LiteLLMBase):
    """The `api` route: one user message per call, with litellm's own retry defaults."""
    disable_provider_retries = False

    def __call__(self, prompt: str):
        t0 = time.time()
        resp = self._complete([{"role": "user", "content": prompt}], temperature=None, max_tokens=None)
        usage = resp.usage.model_dump() if resp.usage else None
        return resp.choices[0].message.content, int(time.time() - t0), usage


def litellm_completion(model: str) -> InferenceClient:
    import litellm  # noqa: F401  # a missing litellm fails here, before any response record is written

    return InferenceClient(model, timeout=300)


def inference_route(model: str, backend: str = "api", reasoning_effort: str | None = None) -> dict:
    """Resolve a route once and retain its effective request configuration."""
    if backend == "api":
        if reasoning_effort is not None:
            raise ValueError("--reasoning-effort requires codex or openrouter")
        return {"backend": "api", "model": model, "kwargs": {}}
    canonical, resolved, kwargs = resolve_route(backend, model, reasoning_effort)
    if reasoning_effort is not None and canonical not in {"codex", "openrouter"}:
        raise ValueError("--reasoning-effort requires codex or openrouter")
    return {"backend": canonical, "model": resolved, "kwargs": kwargs}


def input_binding(model: str, prompt: str, *, backend: str = "api",
                  reasoning_effort: str | None = None) -> str:
    """Keep legacy API bindings intact; bind transport and configuration on new routes."""
    return route_binding(model, prompt, inference_route(model, backend, reasoning_effort))


def route_binding(model: str, prompt: str, route: dict) -> str:
    """The input binding for an already-resolved route, as stored on each response row."""
    value = {"version": 1, "model": model, "messages": [{"role": "user", "content": prompt}]}
    if route["backend"] != "api":
        value.update(version=2, route=route)
    return json_sha256(value, ensure_ascii=False)


def preflight(caseset: Path, model: str, items: list[dict], template: str,
              trials: int, *, backend: str = "api",
              reasoning_effort: str | None = None,
              set_name: str | None = None) -> tuple[Path, set[tuple[str, int]]]:
    """Read and validate all successful receipts before any request or write. The response set
    (set_name, or the model) names the file and declared route; the model builds the request."""
    name = set_name or model
    route = inference_route(model, backend, reasoning_effort)
    declared = Project(caseset).provenance().get("inference", {}).get("model_routes", {}).get(name)
    if declared is not None and declared != route:
        raise ValueError(f"{name}: changed inference route; preserve it and use a new project/run")
    prompts = {item["id"]: assemble_prompt(template, item["prompt"]) for item in items}
    if not prompts or len(prompts) != len(items):
        raise ValueError("items must be nonempty with unique IDs")
    out = Project(caseset).responses_path(sanitize_model(name))
    done = set()
    for row in read_jsonl(out) if out.exists() else []:
        prior_route = row.get("route", inference_route(model))
        if prior_route != route:
            raise ValueError(f"{out}: changed inference route; preserve it and use a new project/run")
        if "error" in row or not row.get("response"):
            continue
        key = (row["id"], row.get("trial", 1))
        if (key[0] not in prompts or type(key[1]) is not int or not 1 <= key[1] <= trials
                or not isinstance(row["response"], str) or not row["response"].strip()
                or row.get("input_sha256") != input_binding(
                    model, prompts[key[0]], backend=backend, reasoning_effort=reasoning_effort)):
            raise ValueError(f"{out}: successful response {key} has unknown or changed input binding; "
                             "preserve it and use a new project/run")
        if key in done:
            raise ValueError(f"{out}: duplicate successful response for {key}")
        done.add(key)
    return out, done


def run_model(caseset: Path, model: str, items: list[dict], template: str,
              trials: int | None = None, completion_fn=None, *, backend: str = "api",
              reasoning_effort: str | None = None,
              on_checkpoint: Callable[[Path], None] | None = None,
              set_name: str | None = None) -> Path:
    trials = Project(caseset).trials() if trials is None else trials
    route = inference_route(model, backend, reasoning_effort)
    out, done = preflight(caseset, model, items, template, trials,
                          backend=backend, reasoning_effort=reasoning_effort, set_name=set_name)
    prompted = set_prompt(Project(caseset), set_name) if set_name else None
    call = completion_fn or (litellm_completion(model) if backend == "api" else None)
    for item in items:
        for trial in range(1, trials + 1):
            if (item["id"], trial) in done:
                continue
            prompt = assemble_prompt(template, item["prompt"])
            binding = input_binding(model, prompt, backend=backend, reasoning_effort=reasoning_effort)
            receipt = {"id": item["id"], "trial": trial, "input_sha256": binding, "model": model}
            if prompted is not None:
                receipt.update(responseSet=set_name, prompt={"id": prompted["id"], "sha256": prompted["sha256"]})
            if route["backend"] != "api":
                receipt["route"] = route
            try:
                if call is not None:
                    response, runtime, usage = call(prompt)
                else:
                    result = backends.call(route["backend"], route["model"], "", prompt,
                                           timeout=300, **route["kwargs"])
                    receipt["provider_provenance"] = result.provenance
                    response = result.text
                    runtime = result.provenance.get("runtime_s")
                    usage = result.provenance.get("usage")
                if not isinstance(response, str) or not response.strip():
                    raise ValueError("provider returned empty or non-text response")
                receipt.update(response=response, runtime=runtime, usage=usage)
            except Exception as e:  # noqa: BLE001 - retain provider failures for explicit retry
                receipt.update(response=None, error=str(e), runtime=None, usage=None)
                if getattr(e, "raw", None) is not None:
                    receipt["provider_raw"] = e.raw
            append_jsonl(out, receipt)
            if on_checkpoint is not None:
                on_checkpoint(out)
            print(f"[{set_name or model}] {item['id']} trial {trial}", file=sys.stderr)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--model", action="append", required=True)
    ap.add_argument("--backend", choices=("api", "claude", "subscription", "codex", "openrouter"),
                    default="api", help="api uses LiteLLM; claude/codex use subscriptions")
    ap.add_argument("--reasoning-effort", help="optional Codex/OpenRouter reasoning effort")
    ap.add_argument("--prompt-file", type=Path, default=None)
    ap.add_argument("--prompt", help="collect with a saved prompt (name or ID) into its own response sets")
    ap.add_argument("--trials", type=positive_int, help="project trial count; defaults to its stored declaration or 1")
    args = ap.parse_args()
    load_env()

    if args.prompt is not None and args.prompt_file is not None:
        ap.error("--prompt cannot be combined with --prompt-file")
    project = Project(args.project)
    if args.prompt is not None and project.provenance().get("inference", {}).get(
            "template_sha256", UNPROMPTED_SHA256) != UNPROMPTED_SHA256:
        ap.error("This project was collected with --prompt-file; add prompts in a new project.")
    if args.prompt_file is not None and project.provenance().get("inference", {}).get("set_prompts"):
        ap.error("This project collects with saved prompts; use --prompt-file in a new project.")
    items = project.items()
    template = args.prompt_file.read_text() if args.prompt_file else ""
    models = sorted(set(args.model))
    try:
        saved = None
        if args.prompt is not None:
            prompts = load_prompts(project)
            saved = prompts.get(args.prompt) or next(
                (prompt for prompt in prompts.values() if prompt["name"] == args.prompt), None)
            if saved is None:
                raise ValueError(f"prompt {args.prompt!r} is not saved in {project.root / 'prompts.json'}")
        sets = {set_id(model, saved["id"] if saved else None): model for model in models}
        declared = project.trials()
        trials = declared if args.trials is None else args.trials
        if trials != declared and any(file.stat().st_size for file in project.response_files()):
            raise ValueError("trial count cannot change after collection records exist; "
                             "preserve them and create a new project/run")
        provenance = project.provenance()
        prior_models = provenance.get("models", [])
        inference = provenance.get("inference", {})
        routes = dict(inference.get("model_routes", {}))
        recorded = dict(inference.get("set_prompts", {}))
        declared_models = sorted(set(prior_models) | set(sets))
        if len({sanitize_model(model) for model in declared_models}) != len(declared_models):
            raise ValueError("model IDs collide after filename normalization")
        templates, model_routes = {}, {}
        # Each declared set is checked against its own prompt, never the current run's.
        for name in declared_models:
            if name in sets:
                model = sets[name]
                route = inference_route(model, args.backend, args.reasoning_effort)
                templates[name] = template if saved is None else saved["text"]
                if name in recorded and set_template(project, name, template) != templates[name]:
                    raise ValueError(f"{name}: response set was collected with a different prompt")
            else:
                model = routes[name]["model"] if name in recorded else name
                route = routes.get(name, inference_route(model))
                templates[name] = set_template(project, name, template)
            # Prompted and unprompted sets of a model differ only in the prompt.
            if model_routes.setdefault(model, route) != route:
                raise ValueError(f"{model}: every response set of a model must use the same route and "
                                 "reasoning effort; preserve it and use a new project/run")
            preflight(args.project, model, items, templates[name], trials, backend=route["backend"],
                      reasoning_effort=route["kwargs"].get("reasoning_effort"), set_name=name)
            routes[name] = route
        if saved is not None:
            recorded.update({name: {"id": saved["id"], "name": saved["name"], "sha256": saved["sha256"]}
                             for name in sets})
    except ValueError as exc:
        ap.error(str(exc))
    # Record expectations before dispatch so interrupted runs remain visibly incomplete.
    project.update_provenance(models=declared_models, trials=trials,
                      inference={**inference,
                                 "binding_version": 2 if any(r["backend"] != "api" for r in routes.values()) else 1,
                                 "model_routes": routes, "timeout_seconds": 300,
                                 "template_sha256": sha256(template),
                                 **({"set_prompts": recorded} if recorded else {})})
    missing = False
    expected = project.expected()
    for name, model in sets.items():
        run_model(args.project, model, items, templates[name], trials,
                  backend=args.backend, reasoning_effort=args.reasoning_effort, set_name=name)
        _, done = preflight(args.project, model, items, templates[name], trials,
                            backend=args.backend, reasoning_effort=args.reasoning_effort, set_name=name)
        if gaps := expected - done:
            missing = True
            print(f"[{name}] unresolved item/trial pairs: {sorted(gaps)}", file=sys.stderr)
    if missing:
        sys.exit(1)


if __name__ == "__main__":
    main()
