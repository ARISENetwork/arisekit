"""Loopback workspace for one reviewed package and its local run evidence."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import mimetypes
import os
import secrets
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from arisekit.runtime.rescore import load_responses
from arisekit.authoring.iteration import build_iteration_review
from arisekit.run_inspection import load_and_verify_run_inspection
from arisekit.runnable import (
    authorize_run_request, load_manifest, record_smoke_test, verify_assets,
)
from arisekit.scaffold import BenchmarkScaffoldSpec, check_benchmark, load_scaffolded_benchmark
from arisekit.package import load_package
from arisekit.analysis.sweep import sweep_spec_from_package


def _file(root: Path, relative: str) -> Path:
    candidate = root / relative
    if (Path(relative).is_absolute() or ".." in Path(relative).parts or "\\" in relative
            or any(part.is_symlink() for part in [candidate, *candidate.parents])):
        raise ValueError("Workspace evidence paths must be relative and must not use symlinks")
    path = candidate.resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Workspace evidence is missing or outside its selected directory")
    if path.stat().st_size > 25 * 1024 * 1024:
        raise ValueError("This workspace supports evidence files up to 25 MiB")
    return path


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _azure_missing():
    missing = [name for name in ("AZURE_API_BASE", "AZURE_API_VERSION") if not os.environ.get(name)]
    if not (os.environ.get("AZURE_API_KEY") or os.environ.get("AZURE_AD_TOKEN")):
        missing.append("AZURE_API_KEY or AZURE_AD_TOKEN")
    return missing


def _check_runtime(models):
    if any(model.startswith("azure/") for model in models) and _azure_missing():
        raise ValueError("Configure the worker environment: " + ", ".join(_azure_missing()))


def _verify_summary(bundle, captured, scores):
    summary = bundle["summary"]
    errored = sum(row.error is not None for row in captured.responses)
    if summary["completed"] != len(captured.responses) - errored or summary["errored"] != errored:
        raise ValueError("Result counts do not match the checkpoint")
    for flag in ("cost_unknown", "budget_exhausted", "cost_bound_exceeded", "call_budget_exhausted"):
        if summary[flag] is not any(row.metadata.get(flag) is True for row in captured.responses):
            raise ValueError("Result accounting flags do not match the checkpoint")
    cost = sum(float(row.metadata.get("cost", 0) or 0) for row in captured.responses)
    if not math.isclose(summary["cost_total"], cost, abs_tol=1e-9):
        raise ValueError("Result cost does not match the checkpoint")
    with scores.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != len(bundle["metrics"]):
        raise ValueError("Result metrics do not match the score table")
    for row, metric in zip(rows, bundle["metrics"]):
        if (row["benchmark"] != bundle["benchmark"] or row["model"] != bundle["model"]
                or row["category"] != metric["category"] or row["metric"] != metric["name"]
                or (int(row["n"]) if row["n"] else None) != metric["n"]
                or not math.isclose(float(row["value"]), metric["value"], abs_tol=0.00000051)
                or (row["ci"] == "") != (metric["ci"] is None)
                or (row["ci"] and not math.isclose(float(row["ci"]), metric["ci"], abs_tol=0.00000051))):
            raise ValueError("Result metrics do not match the score table")


class ResultsWorkspace:
    def __init__(self, benchmark: Path, authoring: Path, results: Path, *, worker: str = "local"):
        if worker not in {"local", "azure"}:
            raise ValueError("Worker must be local or azure")
        self.worker = worker
        self.benchmark = benchmark.resolve()
        self.authoring = authoring.resolve()
        self.results = results.resolve()
        self.lock = threading.Lock()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.active: str | None = None
        self.snapshot()
        history = self.results / "workspace-operations" / self.benchmark.name
        for path in sorted(history.glob("*.json"))[-100:]:
            entry = _json(_file(history, path.name))
            if entry.get("status") in {"complete", "failed"}:
                self.jobs[entry["id"]] = entry
        self.jobs = dict(sorted(self.jobs.items(), key=lambda entry: entry[1].get("started_at", "")))

    def _load(self):
        runnable = load_manifest(_file(self.benchmark, "runnable-benchmark.json"))
        verify_assets(self.benchmark, runnable)
        report = check_benchmark(self.benchmark)
        if not report.compatible:
            raise ValueError("Imported package failed structural verification")
        spec_path = _file(self.authoring, "benchmark-build-spec.json")
        digest = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        if digest != runnable.build_spec_sha256:
            raise ValueError("The selected plan does not match this benchmark's build-spec digest")
        spec = BenchmarkScaffoldSpec.from_json(spec_path)
        if spec.data_governance.classification not in {"synthetic", "public"} or spec.data_governance.release_posture != "public":
            raise ValueError("This workspace supports public or synthetic packages only")
        if any(getattr(runnable.smoke_test, key) != getattr(spec.smoke_test, key) for key in ("model", "limit", "trials")):
            raise ValueError("Package smoke request differs from the originating plan")
        bench = load_scaffolded_benchmark(self.benchmark)
        return runnable, spec, bench

    def _runs(self, runnable, bench):
        smoke = None
        paths = list((self.results / "run-results" / bench.name).glob("**/run-results.json"))
        if runnable.smoke_test.result_bundle_path:
            smoke = _file(self.results, runnable.smoke_test.result_bundle_path)
            if hashlib.sha256(smoke.read_bytes()).hexdigest() != runnable.smoke_test.result_bundle_sha256:
                raise ValueError("Smoke evidence digest changed")
            paths.append(smoke)
        runs = []
        for path in sorted(set(paths)):
            path = _file(self.results, path.relative_to(self.results).as_posix())
            candidate = _json(path)
            for key in ("raw_checkpoint", "scores"):
                _file(self.results, candidate[key]["path"])
            bundle = load_and_verify_run_inspection(path, results_root=self.results)
            if bundle["benchmark"] != bench.name:
                raise ValueError("Result belongs to a different benchmark")
            checkpoint = _file(self.results, bundle["raw_checkpoint"]["path"])
            _file(self.results, (checkpoint.parent / "run-manifest.json").relative_to(self.results).as_posix())
            captured = load_responses(checkpoint, benchmark=bench)
            if captured.run_manifest is None or captured.run_manifest_digest != bundle["run_manifest_digest"] or captured.model != bundle["model"]:
                raise ValueError("Result does not match its run manifest")
            if path == smoke:
                planned = runnable.smoke_test
                if (captured.model != planned.model or captured.expected_trials != planned.trials
                        or captured.run_manifest.selection.get("limit") != planned.limit
                        or captured.run_manifest_digest != planned.run_manifest_digest
                        or bundle["summary"]["completed"] != planned.completed
                        or bundle["summary"]["errored"] != planned.errored
                        or (runnable.readiness == "ready" and captured.missing_trials)):
                    raise ValueError("Smoke evidence does not satisfy the originating plan")
            _verify_summary(bundle, captured, _file(self.results, bundle["scores"]["path"]))
            items = {item.id: item for item in captured.items}
            cases = []
            for row in captured.responses:
                item = items[row.id]
                metrics = []
                if row.error is None and bench.scorer.rescore_safe is True:
                    metrics = [metric.to_dict() for metric in bench.scorer.score_item(item, [row])]
                if row.error is not None:
                    outcome = "error"
                elif metrics and all(metric["value"] == 1 for metric in metrics):
                    outcome = "passed"
                elif metrics and any(metric["value"] == 0 for metric in metrics):
                    outcome = "failed"
                else:
                    outcome = "scored" if metrics else "unscored"
                cases.append({
                    "id": row.id, "trial": row.trial, "prompt": item.prompt,
                    "expected": item.ground_truth, "response": row.to_dict()["response"],
                    "error": row.error, "metadata": row.metadata, "outcome": outcome, "metrics": metrics,
                })
            for item_id, trial in captured.missing_trials:
                item = items[item_id]
                cases.append({"id": item_id, "trial": trial, "prompt": item.prompt,
                              "expected": item.ground_truth, "response": None, "error": None,
                              "metadata": {}, "outcome": "missing", "metrics": []})
            run = {
                "id": path.relative_to(self.results).as_posix(),
                "kind": "smoke" if path.parent.name == "smoke-evidence" else "latest",
                "bundle": bundle, "cases": cases,
                "expected_count": len(captured.selected_item_ids) * captured.expected_trials,
                "missing_count": len(captured.missing_trials),
                "manifest": captured.run_manifest.to_dict(),
            }
            run["iteration_review"] = build_iteration_review(run)
            runs.append(run)
        return runs

    def snapshot(self):
        runnable, spec, bench = self._load()
        artifacts = []
        for artifact in spec.to_dict()["artifacts"]:
            path = _file(self.authoring, artifact["path"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                raise ValueError("Planning artifact digest changed")
            artifacts.append({**artifact, "text": path.read_bytes().decode("utf-8")})
        return {
            "name": spec.benchmark.name, "slug": bench.name,
            "readiness": runnable.readiness, "build_spec_sha256": runnable.build_spec_sha256,
            "plan": spec.to_dict(), "artifacts": artifacts,
            "items": [item.to_dict() for item in bench.dataset],
            "runs": self._runs(runnable, bench),
            "routes": spec.to_dict()["first_sweep"],
            "runner": spec.to_dict()["runner"],
            "operations": list(self.jobs.values()),
            "smoke_test": runnable.smoke_test.to_dict(),
            "worker": {"kind": self.worker, "azure_missing": _azure_missing()},
        }

    def execute(self, operation: str, request: dict[str, Any]):
        self.snapshot()
        runnable, spec, bench = self._load()
        routes = [row["model"] for row in spec.to_dict()["first_sweep"]]
        if operation == "smoke":
            if set(request) != {"confirm_paid"} or request["confirm_paid"] is not True:
                raise ValueError("Review and explicitly start the planned smoke run")
            planned = spec.smoke_test
            if runnable.readiness != "awaiting_smoke_test":
                raise ValueError("The planned smoke run has already been recorded; inspect its readiness")
            authorize_run_request(runnable, model=planned.model, limit=planned.limit, trials=planned.trials)
            _check_runtime([planned.model])
            result = bench.run(model=planned.model, limit=planned.limit, trials=planned.trials,
                               threads=spec.runner.threads, results_dir=self.results, auto_manifest=True)
            captured = load_responses(Path(result.summary.output_path), benchmark=bench)
            if captured.missing_trials:
                raise ValueError("Smoke run is incomplete; inspect missing trials and run again to resume")
            updated = record_smoke_test(self.benchmark / "runnable-benchmark.json", root=self.results,
                                       result_bundle_path=result.bundle_path,
                                       run_manifest_digest=result.summary.manifest_digest,
                                       completed=result.summary.completed, errored=result.summary.errored)
            return {"readiness": updated.readiness, "smoke_test": updated.smoke_test.to_dict()}
        if operation == "preview":
            if set(request) != {"model"} or request["model"] not in routes:
                raise ValueError("Choose a model from the reviewed plan")
            preview = bench.preview_cost(request["model"], limit=spec.smoke_test.limit)
            destination = self.results / "cost-previews" / f"{preview.digest}.json"
            preview.write(destination)
            return preview.to_dict()
        if operation == "rescore":
            if set(request) != {"run_id"}:
                raise ValueError("Choose a retained run to re-score")
            runs = self._runs(runnable, bench)
            run = next((row for row in runs if row["id"] == request["run_id"]), None)
            if run is None:
                raise ValueError("The selected run is unavailable")
            checkpoint = _file(self.results, run["bundle"]["raw_checkpoint"]["path"])
            revision = bench.rescore(checkpoint, results_dir=self.results)
            return _json(revision.receipt_path)
        if operation == "sweep":
            if set(request) != {"models", "confirm_paid"} or request["confirm_paid"] is not True:
                raise ValueError("Review and explicitly start the sweep")
            models = request["models"]
            if not isinstance(models, list) or not models or any(not isinstance(m, str) or m not in routes for m in models) or len(models) != len(set(models)):
                raise ValueError("Choose distinct models from the reviewed plan")
            if runnable.readiness != "ready":
                raise ValueError("The package must pass its planned smoke run first")
            _check_runtime(models)
            # Bounds come from the imported plan, not browser-supplied overrides.
            package = load_package(self.benchmark / "package", verify_assets=True)
            sweep = sweep_spec_from_package(
                package, models=models, limit=spec.smoke_test.limit,
                threads=spec.runner.threads, max_cost=spec.runner.max_cost,
                max_calls=spec.runner.max_calls,
            )
            result = bench.run_many(sweep, results_dir=self.results)
            return _json(result.receipt_path)
        raise ValueError("Unsupported workspace operation")

    def submit(self, operation: str, payload: dict[str, Any]):
        if operation not in {"preview", "rescore", "sweep", "smoke"}:
            raise ValueError("Unsupported workspace operation")
        with self.lock:
            if self.active is not None:
                raise ValueError("An operation is already running; wait for it to finish")
            if len(self.jobs) >= 100:
                self.jobs.pop(next(iter(self.jobs)))
            identifier = secrets.token_hex(12)
            job = {"id": identifier, "operation": operation, "status": "running", "started_at": datetime.now(timezone.utc).isoformat()}
            self.jobs[identifier] = job
            self.active = identifier

        def work():
            try:
                result = self.execute(operation, payload)
                updated = {**job, "status": "complete", "result": result}
                if operation == "smoke" and result.get("readiness") != "ready":
                    updated["status"] = "failed"
                    updated["error"] = "The planned smoke run failed. Inspect its case outcomes."
                if operation == "sweep" and any(cell.get("status") != "succeeded" for cell in result.get("cells", [])):
                    updated["status"] = "failed"
                    updated["error"] = "Some sweep routes did not succeed. Inspect the retained cell outcomes."
            except Exception as exc:
                # Provider exceptions can embed credentials or request bodies.
                # Expose structural errors only; never return raw provider errors.
                message = str(exc) if type(exc) is ValueError else "Operation failed. Check the runtime and retained result receipts."
                updated = {**job, "status": "failed", "error": message}
            try:
                destination = self.results / "workspace-operations" / self.benchmark.name / f"{identifier}.json"
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(".tmp")
                temporary.write_text(json.dumps(updated, indent=2, allow_nan=False) + "\n", encoding="utf-8")
                temporary.replace(destination)
            except OSError:
                updated = {**updated, "status": "failed", "error": "Could not persist the operation history. Inspect engine receipts before retrying."}
            with self.lock:
                self.jobs[identifier] = updated
                self.active = None

        threading.Thread(target=work, daemon=True).start()
        return identifier


def make_server(workspace: ResultsWorkspace, ui: Path, port: int = 8765):
    token = secrets.token_urlsafe(32)
    ui = ui.resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, value):
            encoded = json.dumps(value, allow_nan=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(encoded)

        def authorized(self):
            expected_host = f"127.0.0.1:{self.server.server_port}"
            return (
                self.headers.get("Host") == expected_host
                and self.headers.get("Origin", f"http://{expected_host}") == f"http://{expected_host}"
                and secrets.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}")
            )

        def do_GET(self):
            route = urlsplit(self.path).path
            if route.startswith("/api/workspace"):
                if not self.authorized():
                    return self.reply(403, {"error": "Open the workspace using its launch URL"})
                try:
                    if route == "/api/workspace":
                        if workspace.active is not None:
                            return self.reply(409, {"error": "An operation is running"})
                        return self.reply(200, workspace.snapshot())
                    if route == "/api/workspace/export":
                        if workspace.active is not None:
                            return self.reply(409, {"error": "Wait for the operation before exporting"})
                        from arisekit.workspace_bundle import export_bundle
                        return self.reply(200, export_bundle(workspace))
                    if route == "/api/workspace/jobs":
                        return self.reply(200, list(workspace.jobs.values()))
                    return self.reply(404, {"error": "Unknown workspace resource"})
                except (ValueError, OSError, KeyError, TypeError):
                    return self.reply(422, {"error": "Evidence verification failed. Reopen the matching plan, package, and results."})
            if not route.startswith("/benchmark/"):
                return self.reply(404, {"error": "Not found"})
            try:
                relative = route.removeprefix("/benchmark/")
                path = _file(ui, relative if relative.startswith("assets/") else "index.html")
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(path.read_bytes())
            except ValueError:
                self.reply(404, {"error": "Build the benchmark UI before opening the workspace"})

        def do_POST(self):
            if not self.authorized():
                return self.reply(403, {"error": "Open the workspace using its launch URL"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 8192 or self.headers.get("Content-Type") != "application/json":
                    raise ValueError("Expected a small JSON operation request")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Expected an operation object")
                route = urlsplit(self.path).path
                if not route.startswith("/api/workspace/"):
                    raise ValueError("Unsupported operation")
                operation = route.removeprefix("/api/workspace/")
                return self.reply(202, {"id": workspace.submit(operation, payload)})
            except (ValueError, TypeError) as exc:
                self.reply(400, {"error": str(exc)})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return server, f"http://127.0.0.1:{server.server_port}/benchmark/workspace#token={token}"


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--authoring", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--ui", type=Path, default=Path(__file__).with_name("workspace_ui"))
    parser.add_argument("--worker", choices=["local", "azure"], default="local")
    parser.add_argument("--export", type=Path, help="Write a portable result bundle and SHA-256 receipt, then exit")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    workspace = ResultsWorkspace(args.benchmark, args.authoring, args.results, worker=args.worker)
    if args.export:
        from arisekit.workspace_bundle import export_bundle
        bundle = export_bundle(workspace)
        args.export.write_text(bundle["text"], encoding="utf-8")
        args.export.with_suffix(args.export.suffix + ".sha256").write_text(bundle["sha256"] + "\n", encoding="ascii")
        print(f"Result bundle: {args.export}\nSHA-256: {bundle['sha256']}")
        return
    server, url = make_server(workspace, args.ui, args.port)
    print(f"Open results workspace: {url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
