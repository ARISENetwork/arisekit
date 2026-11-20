"""Command-line entry points.

    arisekit eval <name> --model X [--trials N] [--threads N] [--limit N]
    arisekit new-benchmark --spec benchmark-build-spec.json
    arisekit check-benchmark <name-or-path>
    arisekit jobs submit <execution-job.json>
    arisekit jobs status <job-id>
    arisekit jobs resume <job-id>
    arisekit rescore <name> --checkpoint results/raw/...jsonl
    arisekit cost-preview <name> --model X
    arisekit sweep <name> [--model X ...]
    arisekit compile
    arisekit cost

`eval` discovers a benchmark from `benchmarks/<name>/`. The benchmark
directory must expose a callable `build()` (in dataset.py, scorer.py,
or __init__.py) that returns an `arisekit.Benchmark`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shlex
import sys
from pathlib import Path

from arisekit.benchmark import Benchmark
from arisekit.cli_verbs import cmd_compare, cmd_monitor, cmd_report
from arisekit.common.jsonio import strict_json_object
from arisekit.authoring.compiler import compile_results, composite_scores


def _load_benchmark(name: str, benchmarks_dir: Path) -> Benchmark:
    """Import `benchmarks/<name>/build.py` (or __init__.py) and call build()."""
    bench_dir = benchmarks_dir / name
    if not bench_dir.is_dir():
        raise SystemExit(f"benchmark not found: {bench_dir}")

    if (bench_dir / "package" / "benchmark.json").is_file():
        from arisekit.scaffold import load_scaffolded_benchmark

        try:
            return load_scaffolded_benchmark(bench_dir)
        except (OSError, ValueError) as exc:
            raise SystemExit(
                f"could not safely load scaffolded benchmark {bench_dir}: {exc}"
            ) from exc

    for filename in ("build.py", "__init__.py"):
        path = bench_dir / filename
        if path.exists():
            spec = importlib.util.spec_from_file_location(f"benchmarks.{name}", path)
            if spec is None or spec.loader is None:
                raise SystemExit(f"could not load spec for {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            if not hasattr(module, "build"):
                continue
            bench = module.build()
            if not isinstance(bench, Benchmark):
                raise SystemExit(
                    f"{path}::build() must return an arisekit.Benchmark"
                )
            return bench

    raise SystemExit(
        f"no build() found in {bench_dir}/build.py or __init__.py"
    )


def cmd_provider_check(args: argparse.Namespace) -> int:
    from arisekit.providers import check_connection, load_profile
    try:
        report = check_connection(load_profile(args.profile), live=args.live, check_tools=not args.text_only)
    except (OSError, ValueError, TypeError) as exc:
        print(f"invalid provider profile: {exc}")
        return 2
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["ready"] or (not args.live and report["checks"]["configuration"]["status"] == "passed") else 2


def cmd_eval(args: argparse.Namespace) -> int:
    try:
        provider_authorization = _load_provider_authorization(
            getattr(args, "provider_authorization", None)
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"cannot load provider authorization: {exc}")
        return 2
    benchmarks_dir = Path(args.benchmarks_dir)
    results_dir = Path(args.results_dir)
    bench = _load_benchmark(args.name, benchmarks_dir)
    runnable_path = benchmarks_dir / args.name / "runnable-benchmark.json"
    runnable_mode: str | None = None
    if runnable_path.is_file():
        from arisekit.runnable import (
            authorize_run_request,
            load_manifest as load_runnable_manifest,
            verify_assets as verify_runnable_assets,
        )

        try:
            runnable = load_runnable_manifest(runnable_path)
            verify_runnable_assets(runnable_path.parent, runnable)
            runnable_mode = authorize_run_request(
                runnable,
                model=args.model,
                limit=args.limit,
                trials=(
                    args.trials
                    if args.trials is not None
                    else bench.runner_config.trials
                ),
            )
        except (OSError, UnicodeError, ValueError) as exc:
            print(f"cannot run benchmark: {exc}")
            return 2
    try:
        profile = None
        if getattr(args, "provider_profile", None):
            from arisekit.providers import load_profile
            profile = load_profile(args.provider_profile)
        results = bench.run(
            model=args.model,
            trials=args.trials,
            threads=args.threads,
            limit=args.limit,
            results_dir=results_dir,
            bootstrap=args.bootstrap,
            auto_manifest=True,
            provider_authorization=provider_authorization,
            provider_profile=profile,
        )
    except ValueError as exc:
        print(f"cannot run benchmark: {exc}")
        return 2
    if runnable_mode == "smoke":
        from arisekit.runnable import record_smoke_test

        if getattr(results, "bundle_path", None) is None:
            print("cannot record smoke test: run result bundle was not written")
            return 2
        try:
            updated = record_smoke_test(
                runnable_path,
                root=results_dir,
                result_bundle_path=results.bundle_path,
                run_manifest_digest=results.summary.manifest_digest,
                completed=results.summary.completed,
                errored=results.summary.errored,
            )
        except (OSError, UnicodeError, ValueError) as exc:
            print(f"cannot record smoke test: {exc}")
            return 2
        print(f"runnable readiness: {updated.readiness}")
    print(f"benchmark: {results.benchmark}")
    print(f"model: {results.model}")
    print(f"completed={results.summary.completed} "
          f"errored={results.summary.errored} "
          f"skipped={results.summary.skipped} "
          f"cost=${results.summary.cost_total:.4f}")
    print(f"raw: {results.summary.output_path}")
    if results.summary.manifest_digest is not None:
        print(f"manifest: {results.summary.manifest_digest}")
    if getattr(results, "bundle_path", None) is not None:
        print(f"result bundle: {results.bundle_path}")
    if getattr(results, "report_path", None) is not None:
        print(f"run results: {results.report_path}")
    print("metrics:")
    for m in results.metrics:
        ci = f" ±{m.ci:.4f}" if m.ci is not None else ""
        print(f"  {m.category}/{m.name}: {m.value:.4f}{ci}  (n={m.n})")
    return 0


def cmd_compile(args: argparse.Namespace) -> int:
    try:
        out = compile_results(
            args.results_dir,
            manifest_digests=getattr(args, "manifest_digest", None),
        )
    except ValueError as exc:
        print(f"cannot compile scores: {exc}")
        return 2
    print(f"wrote {out}")
    composites = composite_scores(args.results_dir)
    if composites:
        print("composite (mean of overall metrics):")
        for model, value in sorted(composites.items(), key=lambda x: -x[1]):
            print(f"  {model}: {value:.4f}")
    return 0


def cmd_cost(args: argparse.Namespace) -> int:
    """Sum the latest final-response cost for each checkpointed trial."""
    raw_root = Path(args.results_dir) / "raw"
    total = 0.0
    by_model: dict[str, float] = {}
    if raw_root.exists():
        for path in sorted(raw_root.rglob("*.jsonl")):
            if _is_turn_journal(path):
                continue
            keyed: dict[tuple[str, int], float] = {}
            legacy = 0.0
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cost = float(
                        (payload.get("metadata") or {}).get("cost", 0.0) or 0.0
                    )
                    item_id = payload.get("id")
                    trial = payload.get("trial")
                    if isinstance(item_id, str) and isinstance(trial, int):
                        keyed[(item_id, trial)] = cost
                    else:
                        # Checkpoints written before keyed RunResult rows remain
                        # readable and retain their original additive behavior.
                        legacy += cost
            sub = legacy + sum(keyed.values())
            label = path.relative_to(raw_root).with_suffix("").as_posix()
            by_model[label] = sub
            total += sub
    for label, value in sorted(by_model.items()):
        print(f"  {label}: ${value:.4f}")
    print(f"total: ${total:.4f}")
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    """Create a deterministic scoring revision over one retained checkpoint."""

    bench = _load_benchmark(args.name, Path(args.benchmarks_dir))
    try:
        revision = bench.rescore(
            args.checkpoint,
            baseline=args.baseline,
            primary_metric=args.primary_metric,
            bootstrap=args.bootstrap,
            seed=args.seed,
            results_dir=Path(args.results_dir),
            model=args.model,
            expected_trials=args.expected_trials,
        )
    except (OSError, TypeError, UnicodeError, ValueError) as exc:
        print(f"cannot re-score benchmark: {exc}")
        return 2
    print(f"benchmark: {revision.benchmark}")
    print(f"model: {revision.model}")
    print(f"revision: {revision.revision_digest}")
    print(f"receipt: {revision.receipt_path}")
    print(f"item scores: {revision.item_scores_path}")
    print(f"scores: {revision.scores_path}")
    if revision.diff is not None:
        print(
            "changes: "
            f"improved={revision.diff.improved} "
            f"regressed={revision.diff.regressed} "
            f"unchanged={revision.diff.unchanged} "
            f"added={revision.diff.added} "
            f"removed={revision.diff.removed}"
        )
        print(f"diff: {revision.diff_path}")
        print(f"report: {revision.report_path}")
    if revision.missing_trials:
        print(f"coverage: partial ({len(revision.missing_trials)} missing trials)")
    else:
        print("coverage: complete")
    return 0


def cmd_cost_preview(args: argparse.Namespace) -> int:
    """Write a deterministic no-dispatch cost preview for one model route."""

    from arisekit.runtime.cost_preview import PricingSnapshot

    input_rate = args.input_usd_per_million
    output_rate = args.output_usd_per_million
    if (input_rate is None) != (output_rate is None):
        print(
            "cannot preview cost: explicit pricing requires both input and "
            "output USD-per-million-token rates"
        )
        return 2
    pricing = None
    if input_rate is not None:
        try:
            pricing = PricingSnapshot.explicit(
                args.model,
                input_usd_per_million_tokens=input_rate,
                output_usd_per_million_tokens=output_rate,
                max_output_tokens=args.max_tokens,
                provider=args.pricing_provider,
            )
        except (TypeError, ValueError) as exc:
            print(f"cannot preview cost: {exc}")
            return 2

    bench = _load_benchmark(args.name, Path(args.benchmarks_dir))
    try:
        preview = bench.preview_cost(
            args.model,
            trials=args.trials,
            limit=args.limit,
            max_tokens=args.max_tokens,
            pricing=pricing,
        )
        output = (
            Path(args.output)
            if args.output is not None
            else Path(args.results_dir)
            / "cost-previews"
            / f"{preview.digest}.json"
        )
        preview.write(output)
    except (OSError, TypeError, UnicodeError, ValueError) as exc:
        print(f"cannot preview cost: {exc}")
        return 2

    payload = preview.to_dict()
    cost = payload["cost"]
    budget = payload["budget"]
    print(f"benchmark: {payload['benchmark']['name']}")
    print(f"model: {payload['run']['model_route']}")
    print(f"nominal upper bound: {cost['nominal_upper_bound_usd']}")
    print(f"retry upper bound: {cost['retry_upper_bound_usd']}")
    print(f"budget: {budget['status']}")
    print(f"ready for paid run: {'yes' if preview.ready_for_paid_run else 'no'}")
    if preview.blocker_codes:
        print("blockers: " + ", ".join(preview.blocker_codes))
    print(f"receipt: {output}")
    return 0 if preview.ready_for_paid_run else 1


def cmd_sweep(args: argparse.Namespace) -> int:
    """Run one benchmark over an ordered list of reviewed model routes."""

    from arisekit.analysis.sweep import (
        BenchmarkSweepSpec,
        SweepModel,
        run_benchmark_sweep,
        sweep_spec_from_package,
    )

    benchmarks_dir = Path(args.benchmarks_dir)
    bench_dir = benchmarks_dir / args.name
    package_path = bench_dir / "package"
    is_scaffolded = (package_path / "benchmark.json").is_file()
    try:
        providers = _parse_assignments(args.provider, "provider")
        raw_model_trials = _parse_assignments(
            getattr(args, "model_trials", None),
            "model trials",
        )
        model_trials: dict[str, int] = {}
        for model, raw_trials in raw_model_trials.items():
            try:
                parsed_trials = int(raw_trials)
            except ValueError as exc:
                raise ValueError(
                    f"model trials for {model!r} must be a positive integer"
                ) from exc
            if parsed_trials < 1:
                raise ValueError(
                    f"model trials for {model!r} must be a positive integer"
                )
            model_trials[model] = parsed_trials
        authorization_paths = _parse_assignments(
            args.provider_authorization,
            "provider authorization",
        )
        authorizations = {
            model: _load_provider_authorization(path)
            for model, path in authorization_paths.items()
        }
        if is_scaffolded:
            if args.trials is not None or model_trials:
                raise ValueError(
                    "scaffolded package sweeps use the per-model trial counts "
                    "frozen in first_sweep"
                )
            if providers:
                raise ValueError(
                    "scaffolded package sweeps use the providers frozen in first_sweep"
                )
            runnable_path = bench_dir / "runnable-benchmark.json"
            if not runnable_path.is_file():
                raise ValueError(
                    "scaffolded benchmark is missing runnable-benchmark.json"
                )
            from arisekit.runnable import load_manifest, verify_assets

            runnable = load_manifest(runnable_path)
            verify_assets(bench_dir, runnable)
            if runnable.readiness != "ready":
                raise ValueError(
                    "scaffolded benchmark must pass its exact smoke test before a sweep"
                )
            package = _load_runtime_package(package_path)
            bench = _load_benchmark(args.name, benchmarks_dir)
            spec = sweep_spec_from_package(
                package,
                models=args.model,
                threads=args.threads,
                limit=args.limit,
                bootstrap=args.bootstrap,
                bootstrap_seed=args.seed,
                max_cost=args.max_cost,
                max_calls=args.max_calls,
                cost_preview_digest=args.cost_preview_digest,
            )
        else:
            bench = _load_benchmark(args.name, benchmarks_dir)
            if not args.model:
                raise ValueError(
                    "Python benchmark sweeps require at least one --model route"
                )
            extras = sorted(set(providers) - set(args.model))
            if extras:
                raise ValueError(
                    "providers include unselected model routes: " + ", ".join(extras)
                )
            if args.trials is not None and model_trials:
                raise ValueError(
                    "--trials and --model-trials cannot be combined"
                )
            if model_trials:
                extras = sorted(set(model_trials) - set(args.model))
                missing = sorted(set(args.model) - set(model_trials))
                if extras or missing:
                    details = []
                    if missing:
                        details.append("missing " + ", ".join(missing))
                    if extras:
                        details.append("unselected " + ", ".join(extras))
                    raise ValueError(
                        "--model-trials must exactly cover selected routes ("
                        + "; ".join(details)
                        + ")"
                    )
            else:
                trial_count = (
                    bench.runner_config.trials
                    if args.trials is None
                    else args.trials
                )
                model_trials = {model: trial_count for model in args.model}
            planned = tuple(
                SweepModel(
                    model=model,
                    provider=providers.get(
                        model,
                        "stub" if model == "stub/reference" else "litellm",
                    ),
                    trials=model_trials[model],
                )
                for model in args.model
            )
            spec = BenchmarkSweepSpec(
                benchmark=bench.name,
                models=planned,
                allowed_model_routes=bench.allowed_model_routes,
                threads=(
                    bench.runner_config.threads
                    if args.threads is None
                    else args.threads
                ),
                limit=args.limit,
                bootstrap=args.bootstrap,
                bootstrap_seed=args.seed,
                max_cost=args.max_cost,
                max_calls=args.max_calls,
                cost_preview_digest=args.cost_preview_digest,
            )
        results = run_benchmark_sweep(
            bench,
            spec,
            results_dir=Path(args.results_dir),
            provider_authorizations=authorizations,
        )
    except (OSError, TypeError, UnicodeError, ValueError) as exc:
        print(f"cannot run benchmark sweep: {exc}")
        return 2

    print(f"benchmark: {results.spec.benchmark}")
    print(f"sweep: {results.execution_digest}")
    print(
        f"succeeded={results.succeeded} partial={results.partial} "
        f"failed={results.failed} not-run={results.not_run} "
        f"cost=${results.cost:.4f} calls={results.calls_total}"
    )
    print(f"receipt: {results.receipt_path}")
    print(f"scores: {results.scores_path}")
    print(f"report: {results.report_path}")
    return 0 if results.complete else 1


def _parse_assignments(values: list[str] | None, label: str) -> dict[str, str]:
    """Parse repeatable ``MODEL=VALUE`` CLI assignments without ambiguity."""

    result: dict[str, str] = {}
    for raw in values or []:
        key, separator, value = raw.partition("=")
        if not separator or not key.strip() or not value.strip():
            raise ValueError(f"{label} must use non-empty MODEL=VALUE form")
        key = key.strip()
        value = value.strip()
        if key in result:
            raise ValueError(f"duplicate {label} for model route {key!r}")
        result[key] = value
    return result


def _is_turn_journal(path: Path) -> bool:
    """Return whether a JSONL file is a sibling partial-turn journal."""
    return path.name.endswith(".turns.jsonl")


def cmd_run_package(args: argparse.Namespace) -> int:
    """Run a Benchmark Package against a model."""
    try:
        provider_authorization = _load_provider_authorization(
            getattr(args, "provider_authorization", None)
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"cannot load provider authorization: {exc}")
        return 2
    try:
        pkg = _load_runtime_package(args.package)
    except (KeyError, OSError, TypeError, UnicodeError, ValueError) as exc:
        print(f"cannot load package: {exc}")
        return 2
    try:
        bench = Benchmark.from_package(pkg)
    except ValueError as exc:
        print(f"cannot auto-build this package from the CLI: {exc}")
        return 2
    try:
        results = bench.run(
            model=args.model,
            trials=args.trials,
            threads=args.threads,
            limit=args.limit,
            results_dir=Path(args.results_dir),
            bootstrap=args.bootstrap,
            auto_manifest=True,
            provider_authorization=provider_authorization,
        )
    except ValueError as exc:
        print(f"cannot run package: {exc}")
        return 2
    print(f"benchmark: {results.benchmark}")
    print(f"model: {results.model}")
    print(f"completed={results.summary.completed} "
          f"errored={results.summary.errored} "
          f"skipped={results.summary.skipped} "
          f"cost=${results.summary.cost_total:.4f}")
    print(f"raw: {results.summary.output_path}")
    if results.summary.manifest_digest is not None:
        print(f"manifest: {results.summary.manifest_digest}")
    print("metrics:")
    for m in results.metrics:
        ci = f" ±{m.ci:.4f}" if m.ci is not None else ""
        print(f"  {m.category}/{m.name}: {m.value:.4f}{ci}  (n={m.n})")
    return 0


def _read_prompt(spec: str | None) -> str | None:
    """A system-prompt argument: literal text, or @path to read a file."""
    if not spec:
        return None
    if spec.startswith("@"):
        return Path(spec[1:]).read_text(encoding="utf-8")
    return spec


def _load_provider_authorization(spec: str | None):
    """Load an exact, duplicate-key-free provider authorization object."""

    from arisekit.egress import ProviderDisclosureAuthorization

    if spec is None:
        return None

    path = Path(spec).expanduser()
    payload = strict_json_object(path.read_text(encoding="utf-8"), "provider authorization")
    return ProviderDisclosureAuthorization.from_dict(payload)


def _load_runtime_package(path: str | Path):
    """Load a CLI package with strict assets when its policy requires them.

    Packages created before asset manifests remain runnable. Packages that
    carry an asset manifest, declare the generated build-spec contract, or
    declare non-public data are verified before ``load_package`` reads any
    runtime cohort files.
    """

    from arisekit.package import ASSET_MANIFEST_FILENAME, load_package

    root = Path(path)
    asset_manifest = root / ASSET_MANIFEST_FILENAME
    verify_assets = _path_entry_exists(asset_manifest)
    if not verify_assets:
        verify_assets = _manifest_requires_strict_package_assets(root)
    package = load_package(path, verify_assets=verify_assets)
    if verify_assets:
        return package

    if (
        _provenance_requires_strict_package_assets(package.manifest.provenance)
        or _manifest_requires_strict_package_assets(root)
        or _path_entry_exists(asset_manifest)
    ):
        return load_package(path, verify_assets=True)
    return package


def _path_entry_exists(path: Path) -> bool:
    """Return whether a directory entry exists, including a broken symlink."""

    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _manifest_requires_strict_package_assets(root: Path) -> bool:
    """Inspect only benchmark.json to choose strict loading before cohort I/O."""

    if root.is_symlink():
        return True
    manifest_path = root / "benchmark.json"
    if manifest_path.is_symlink():
        return True
    if not manifest_path.is_file():
        return False

    payload = strict_json_object(manifest_path.read_text(encoding="utf-8"), "benchmark manifest")
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        return False
    return _provenance_requires_strict_package_assets(provenance)


def _provenance_requires_strict_package_assets(
    provenance: dict[str, object],
) -> bool:
    """Fail closed for generated markers and non-public data policy."""

    if "build_spec" in provenance or "generated_build_sha256" in provenance:
        return True
    governance = provenance.get("data_governance")
    if not isinstance(governance, dict):
        return False
    release_posture = governance.get("release_posture")
    classification = governance.get("classification")
    return (
        isinstance(release_posture, str)
        and release_posture != "public"
    ) or (
        isinstance(classification, str)
        and classification not in {"public", "synthetic"}
    )


def cmd_run_tool(args: argparse.Namespace) -> int:
    """Run a tool-using agent (a System Under Test) against a package cohort."""
    from arisekit.agentic import PassAtOneScorer
    from arisekit.env import FHIREnvironment, fhir_tools
    from arisekit.scaffold import AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION
    from arisekit.sut import SystemUnderTest

    try:
        provider_authorization = _load_provider_authorization(
            getattr(args, "provider_authorization", None)
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"cannot load provider authorization: {exc}")
        return 2
    try:
        pkg = _load_runtime_package(args.package)
    except (KeyError, OSError, TypeError, UnicodeError, ValueError) as exc:
        print(f"cannot load package: {exc}")
        return 2
    if not pkg.cohort:
        print("run-tool needs a package with a cohort/ of FHIR bundles (agentic modality)")
        return 2

    manifest = getattr(pkg, "manifest", None)
    provenance = getattr(manifest, "provenance", {})
    build_spec = provenance.get("build_spec") if isinstance(provenance, dict) else None
    is_agentic_v2 = (
        isinstance(build_spec, dict)
        and build_spec.get("schema_version")
        == AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION
    )
    if is_agentic_v2:
        if args.system_prompt is not None or args.max_iters is not None:
            print(
                "cannot run tool benchmark: build-spec v2 binds the system "
                "prompt and max turns in the package"
            )
            return 2
        try:
            bench = Benchmark.from_package(pkg)
            results = bench.run(
                model=args.model,
                trials=args.trials,
                threads=args.threads,
                limit=args.limit,
                results_dir=Path(args.results_dir),
                provider_authorization=provider_authorization,
            )
        except ValueError as exc:
            print(f"cannot run tool benchmark: {exc}")
            return 2
        return _print_tool_results(results)

    try:
        bundles = [
            json.loads(Path(p).read_text(encoding="utf-8"))
            for p in pkg.cohort
        ]
        tools = fhir_tools(FHIREnvironment(bundles))
    except (KeyError, OSError, TypeError, UnicodeError, ValueError) as exc:
        print(f"cannot load package cohort: {exc}")
        return 2
    sut = SystemUnderTest.from_agent(
        args.model,
        tools,
        system_prompt=_read_prompt(args.system_prompt),
        max_iters=args.max_iters if args.max_iters is not None else 8,
    )
    try:
        bench = Benchmark.from_package(pkg, scorer=PassAtOneScorer())
        results = bench.run(
            sut,
            trials=args.trials,
            threads=args.threads,
            limit=args.limit,
            results_dir=Path(args.results_dir),
            provider_authorization=provider_authorization,
        )
    except ValueError as exc:
        print(f"cannot run tool benchmark: {exc}")
        return 2
    return _print_tool_results(results)


def _print_tool_results(results: object) -> int:
    print(f"benchmark: {results.benchmark}")
    print(f"tool (SUT): {results.model}")
    print(f"completed={results.summary.completed} "
          f"errored={results.summary.errored} "
          f"skipped={results.summary.skipped} "
          f"cost=${results.summary.cost_total:.4f}")
    print("metrics:")
    for m in results.metrics:
        ci = f" ±{m.ci:.4f}" if m.ci is not None else ""
        print(f"  {m.category}/{m.name}: {m.value:.4f}{ci}  (n={m.n})")
    return 0


def cmd_new_benchmark(args: argparse.Namespace) -> int:
    """Materialize a reviewed build sidecar without running inference."""
    from arisekit.scaffold import (
        BenchmarkScaffoldSpec,
        ScaffoldError,
        scaffold_benchmark,
    )

    try:
        spec = BenchmarkScaffoldSpec.from_json(args.spec)
        receipt = scaffold_benchmark(
            spec,
            output_root=Path(args.benchmarks_dir),
        )
    except (OSError, ScaffoldError) as exc:
        print(f"cannot scaffold benchmark: {exc}")
        return 2

    print(f"wrote benchmark: {receipt.root}")
    print(f"items: {receipt.item_count}")
    print(f"build spec: {receipt.spec_sha256}")
    print(f"runnable manifest: {receipt.root / 'runnable-benchmark.json'}")
    print(
        "provider authorization bundle hash: "
        f"{receipt.package_manifest_sha256}"
    )
    print(f"tree: {receipt.tree_sha256}")
    common = [
        "arisekit",
        "--benchmarks-dir",
        str(Path(args.benchmarks_dir)),
        "--results-dir",
        str(Path(args.results_dir)),
    ]
    print(
        "check: "
        + shlex.join(
            [
                *common,
                "check-benchmark",
                receipt.slug,
                "--verify-linked-provenance",
            ]
        )
    )
    smoke_command = [
        *common,
        "eval",
        receipt.slug,
        "--model",
        spec.smoke_test.model,
        "--limit",
        str(spec.smoke_test.limit),
        "--trials",
        str(spec.smoke_test.trials),
    ]
    governance = getattr(spec, "data_governance", None)
    if getattr(governance, "release_posture", "public") != "public":
        smoke_command.extend(
            ["--provider-authorization", "provider-disclosure.json"]
        )
    print("smoke: " + shlex.join(smoke_command))
    return 0


def cmd_check_benchmark(args: argparse.Namespace) -> int:
    """Verify a generated scaffold without executing its build module."""
    from arisekit.scaffold import check_benchmark

    raw = Path(args.target).expanduser()
    target = (
        raw
        if raw.is_absolute() or raw.is_dir() or len(raw.parts) > 1
        else Path(args.benchmarks_dir) / raw
    )
    report = check_benchmark(
        target,
        verify_linked_provenance=args.verify_linked_provenance,
    )
    if not report.compatible:
        print(f"benchmark is not structurally compatible: {target}")
        for issue in report.issues:
            suffix = f" ({issue.path})" if issue.path else ""
            print(f"  {issue.code}: {issue.message}{suffix}")
        print(report.claim_boundary)
        return 2

    print(f"benchmark: {report.benchmark_name}")
    print(f"items: {report.item_count}")
    print(f"compatible: yes")
    print(report.claim_boundary)
    return 0


def cmd_public_benchmark(args: argparse.Namespace) -> int:
    """Inspect or launch one checked-in public-benchmark adapter."""

    if args.name != "noharm":
        print(f"public benchmark adapter not found: {args.name}")
        return 2

    try:
        try:
            from noharm_reference import NoHarmReferenceBundle
            from noharm_reference.runtime import (
                build_public_command,
                execute_public_command,
                inspection_lines,
            )
        except ModuleNotFoundError as exc:
            if exc.name != "noharm_reference":
                raise
            from benchmarks.noharm_reference import NoHarmReferenceBundle
            from benchmarks.noharm_reference.runtime import (
                build_public_command,
                execute_public_command,
                inspection_lines,
            )

        if args.action == "inspect":
            bundle = NoHarmReferenceBundle(args.source)
            for line in inspection_lines(bundle):
                print(line)
            source = str(bundle.root)
            prefix = [
                "arisekit",
                "public-benchmark",
                "noharm",
                "--source",
                source,
            ]
            print("run help: " + shlex.join([*prefix, "run", "--", "--help"]))
            print(
                "score help: "
                + shlex.join([*prefix, "score", "--", "--help"])
            )
            return 0

        command = build_public_command(
            args.source,
            action=args.action,
            upstream_args=args.upstream_args,
        )
        print(f"public benchmark: {args.name}", flush=True)
        print(f"bundle sha256: {command.bundle_sha256}", flush=True)
        print(f"command: {command.display}", flush=True)
        if args.dry_run:
            print("dry run: upstream command was not executed")
            return 0
        return execute_public_command(command)
    except (OSError, TypeError, UnicodeError, ValueError) as exc:
        print(f"cannot use public benchmark: {exc}")
        return 2


def _run_operational_job(job, args: argparse.Namespace) -> int:
    from arisekit.runtime.execution_adapters import execute_job

    execution = execute_job(
        Path(args.jobs_dir),
        job,
        threads=args.threads,
    )
    summary = execution.summary
    print(f"job: {summary.job_id}")
    print(f"kind: {summary.kind.value}")
    print(
        f"succeeded={summary.succeeded} failed={summary.failed} "
        f"resumed={summary.skipped}"
    )
    print(f"events: {summary.event_path}")
    print(f"receipt: {execution.receipt_path}")
    for artifact in execution.artifacts:
        print(f"artifact: {artifact['path']} sha256={artifact['sha256']}")
    return 0 if summary.succeeded == len(job.tasks) else 1


def cmd_jobs_submit(args: argparse.Namespace) -> int:
    """Bind and dispatch a new immutable execution job specification."""

    from arisekit.runtime.execution import load_execution_job

    try:
        job = load_execution_job(args.spec)
        return _run_operational_job(job, args)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"cannot submit execution job: {exc}")
        return 2


def cmd_jobs_resume(args: argparse.Namespace) -> int:
    """Resume the unfinished tasks of a previously submitted job."""

    from arisekit.runtime.execution import ResumableExecutor

    try:
        job = ResumableExecutor(Path(args.jobs_dir)).load(args.job_id)
        return _run_operational_job(job, args)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"cannot resume execution job: {exc}")
        return 2


def cmd_jobs_status(args: argparse.Namespace) -> int:
    """Inspect a job without dispatching tasks or changing artifacts."""

    from arisekit.runtime.execution import ResumableExecutor
    from arisekit.runtime.execution_adapters import load_receipt

    try:
        executor = ResumableExecutor(Path(args.jobs_dir))
        job = executor.load(args.job_id)
        status = executor.status(job)
        receipt = load_receipt(args.jobs_dir, job.job_id)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"cannot inspect execution job: {exc}")
        return 2
    finalized = receipt is not None and receipt.get("status") == "complete"
    state = "complete" if status.complete and finalized else "incomplete"
    print(f"job: {status.job_id}")
    print(f"digest: {status.job_digest}")
    print(f"kind: {status.kind.value}")
    print(f"status: {state}")
    print(
        f"total={status.total} succeeded={status.succeeded} "
        f"retryable={status.retryable} exhausted={status.exhausted} "
        f"pending={status.pending}"
    )
    print(f"events: {status.event_path}")
    if receipt is not None:
        for artifact in receipt.get("artifacts", ()):  # type: ignore[union-attr]
            if isinstance(artifact, dict):
                print(f"artifact: {artifact.get('path')} sha256={artifact.get('sha256')}")
    return 0


def cmd_distribution(args: argparse.Namespace) -> int:
    from arisekit.runtime.distribution import (
        export_benchmark, import_benchmark, verify_distribution,
    )

    try:
        if args.command == "export-benchmark":
            archive = export_benchmark(
                args.source, args.output, description=args.description,
                dependencies=args.dependency, python_requires=args.python_requires,
            )
            import hashlib
            print(json.dumps({
                "archive": str(archive),
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            }, indent=2))
        elif args.command == "import-benchmark":
            receipt = import_benchmark(
                args.archive, args.destination, expected_sha256=args.sha256,
            )
            print(json.dumps(receipt.to_dict(), indent=2))
        else:
            receipt = verify_distribution(args.distribution)
            if args.command == "describe-benchmark":
                print((receipt.root / "BENCHMARK.md").read_text(encoding="utf-8"), end="")
            else:
                print(json.dumps(receipt.to_dict(), indent=2))
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"cannot {args.command}: {exc}", file=sys.stderr)
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arisekit")
    parser.add_argument(
        "--benchmarks-dir",
        default="benchmarks",
        help="directory containing per-benchmark folders (default: benchmarks)",
    )
    parser.add_argument(
        "--results-dir",
        default="results",
        help="directory for raw + scores + compiled outputs (default: results)",
    )
    parser.add_argument(
        "--jobs-dir",
        default="jobs",
        help="directory for resumable execution jobs (default: jobs)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    from arisekit.fhir.fhir_cli import add_parser as add_fhir_parser
    add_fhir_parser(sub)

    p_export = sub.add_parser("export-benchmark", help="create a versioned benchmark ZIP and MAST handoff")
    p_export.add_argument("source", help="package or generated scaffold directory")
    p_export.add_argument("--output", required=True, help="new archive path outside the source directory")
    p_export.add_argument("--description", help="benchmark purpose (defaults to scaffold description)")
    p_export.add_argument("--dependency", action="append", default=[], help="declared Python requirement; repeatable")
    p_export.add_argument("--python-requires", default=">=3.10")
    p_export.set_defaults(func=cmd_distribution)

    p_import = sub.add_parser("import-benchmark", help="verify and extract a benchmark without executing code")
    p_import.add_argument("archive")
    p_import.add_argument("--destination", required=True, help="new release directory")
    p_import.add_argument("--sha256", help="expected archive digest supplied by its author")
    p_import.set_defaults(func=cmd_distribution)

    for command, help_text in (
        ("verify-benchmark", "verify a release's assets and installed dependencies"),
        ("describe-benchmark", "show a verified release's benchmark description"),
    ):
        p_distribution = sub.add_parser(command, help=help_text)
        p_distribution.add_argument("distribution", help="extracted release directory")
        p_distribution.set_defaults(func=cmd_distribution)

    p_eval = sub.add_parser("eval", help="run a benchmark against a model")
    p_eval.add_argument("name", help="benchmark name (matches benchmarks/<name>/)")
    p_eval.add_argument("--model", required=True, help="model id (litellm format)")
    p_eval.add_argument(
        "--trials",
        type=int,
        default=None,
        help="override the benchmark's configured trial count",
    )
    p_eval.add_argument(
        "--threads",
        type=int,
        default=None,
        help="override the benchmark's configured worker count",
    )
    p_eval.add_argument("--limit", type=int, default=None,
                        help="cap the number of items (for smoke tests)")
    p_eval.add_argument("--bootstrap", type=int, default=0,
                        help="bootstrap iterations for CI (0 = normal approx)")
    p_eval.add_argument(
        "--provider-authorization",
        default=None,
        help="strict provider-disclosure authorization JSON for non-public data",
    )
    p_eval.add_argument("--provider-profile", help="versioned provider profile JSON")
    p_eval.set_defaults(func=cmd_eval)
    p_provider = sub.add_parser("check-provider", help="check provider configuration; --live sends up to two synthetic requests")
    p_provider.add_argument("profile")
    p_provider.add_argument("--live", action="store_true")
    p_provider.add_argument("--text-only", action="store_true")
    p_provider.set_defaults(func=cmd_provider_check)

    p_compile = sub.add_parser("compile", help="compile per-benchmark CSVs into compiled.csv")
    p_compile.add_argument(
        "--manifest-digest",
        action="append",
        default=None,
        help=(
            "include a manifested score run by digest; repeat for multiple "
            "benchmarks or models"
        ),
    )
    p_compile.set_defaults(func=cmd_compile)

    p_cost = sub.add_parser("cost", help="sum cost across all raw checkpoints")
    p_cost.set_defaults(func=cmd_cost)

    p_rescore = sub.add_parser(
        "rescore",
        help="apply the current deterministic scorer to a retained checkpoint",
    )
    p_rescore.add_argument(
        "name", help="benchmark name (matches benchmarks/<name>/)"
    )
    p_rescore.add_argument(
        "--checkpoint",
        required=True,
        help="exact final-response JSONL checkpoint to score",
    )
    p_rescore.add_argument(
        "--baseline",
        default=None,
        help="prior scoring-revision.json to compare",
    )
    p_rescore.add_argument(
        "--primary-metric",
        default=None,
        help="category/name metric used to count item changes",
    )
    p_rescore.add_argument(
        "--model",
        default=None,
        help="model identity for a legacy checkpoint without a run manifest",
    )
    p_rescore.add_argument(
        "--expected-trials",
        type=int,
        default=None,
        help="trial count for a legacy checkpoint without a run manifest",
    )
    p_rescore.add_argument(
        "--bootstrap",
        type=int,
        default=0,
        help="deterministic bootstrap iterations for confidence intervals",
    )
    p_rescore.add_argument(
        "--seed",
        type=int,
        default=0,
        help="bootstrap seed (default: 0)",
    )
    p_rescore.set_defaults(func=cmd_rescore)

    p_preview = sub.add_parser(
        "cost-preview",
        help="write a deterministic no-dispatch cost estimate",
    )
    p_preview.add_argument(
        "name", help="benchmark name (matches benchmarks/<name>/)"
    )
    p_preview.add_argument("--model", required=True, help="reviewed model route")
    p_preview.add_argument("--trials", type=int, default=None)
    p_preview.add_argument("--limit", type=int, default=None)
    p_preview.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="explicit output-token upper bound",
    )
    p_preview.add_argument(
        "--input-usd-per-million",
        default=None,
        help="explicit input USD per million tokens (requires output rate)",
    )
    p_preview.add_argument(
        "--output-usd-per-million",
        default=None,
        help="explicit output USD per million tokens (requires input rate)",
    )
    p_preview.add_argument(
        "--pricing-provider",
        default=None,
        help="provider label recorded with explicit pricing",
    )
    p_preview.add_argument(
        "--output",
        default=None,
        help="receipt path (default: results/cost-previews/<digest>.json)",
    )
    p_preview.set_defaults(func=cmd_cost_preview)

    p_sweep = sub.add_parser(
        "sweep",
        help="run one benchmark over an ordered reviewed model list",
    )
    p_sweep.add_argument(
        "name", help="benchmark name (matches benchmarks/<name>/)"
    )
    p_sweep.add_argument(
        "--model",
        action="append",
        default=None,
        help=(
            "model route; repeat to order/select routes (package default: first_sweep)"
        ),
    )
    p_sweep.add_argument(
        "--provider",
        action="append",
        default=None,
        metavar="MODEL=PROVIDER",
        help="descriptive provider binding for a Python benchmark",
    )
    p_sweep.add_argument(
        "--provider-authorization",
        action="append",
        default=None,
        metavar="MODEL=JSON",
        help="per-route provider-disclosure authorization; repeat as needed",
    )
    p_sweep.add_argument(
        "--trials",
        type=int,
        default=None,
        help="shared trial count for a Python benchmark",
    )
    p_sweep.add_argument(
        "--model-trials",
        action="append",
        default=None,
        metavar="MODEL=TRIALS",
        help="per-model trial count for a Python benchmark; repeat for every route",
    )
    p_sweep.add_argument("--threads", type=int, default=None)
    p_sweep.add_argument("--limit", type=int, default=None)
    p_sweep.add_argument("--bootstrap", type=int, default=0)
    p_sweep.add_argument("--seed", type=int, default=0)
    p_sweep.add_argument("--max-cost", type=float, default=None)
    p_sweep.add_argument("--max-calls", type=int, default=None)
    p_sweep.add_argument(
        "--cost-preview-digest",
        default=None,
        help="optional CUJ 10 preview digest recorded as provenance",
    )
    p_sweep.set_defaults(func=cmd_sweep)

    p_new = sub.add_parser(
        "new-benchmark",
        aliases=["scaffold"],
        help="materialize a reviewed benchmark build specification",
    )
    p_new.add_argument(
        "--spec",
        required=True,
        help="path to benchmark-build-spec.json",
    )
    p_new.set_defaults(func=cmd_new_benchmark)

    p_check = sub.add_parser(
        "check-benchmark",
        aliases=["validate-benchmark"],
        help="offline structural check for a generated benchmark",
    )
    p_check.add_argument("target", help="benchmark slug or directory path")
    p_check.add_argument(
        "--verify-linked-provenance",
        action="store_true",
        help="also re-hash source and planning files from the authoring workspace",
    )
    p_check.set_defaults(func=cmd_check_benchmark)

    p_public = sub.add_parser(
        "public-benchmark",
        help="inspect or launch a checked-in public-benchmark adapter",
    )
    public_sub = p_public.add_subparsers(
        dest="name",
        required=True,
    )
    p_noharm = public_sub.add_parser(
        "noharm",
        help="validated launcher for the official First Do NOHARM public kit",
    )
    p_noharm.add_argument(
        "--source",
        required=True,
        help="local root of the official public benchmark release",
    )
    p_noharm.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print the upstream command without executing it",
    )
    p_noharm.add_argument(
        "action",
        choices=("inspect", "run", "score"),
        help="inspect the release or invoke its official entry point",
    )
    p_noharm.add_argument(
        "upstream_args",
        nargs=argparse.REMAINDER,
        help="literal arguments after -- for the official run.py or score.py",
    )
    p_noharm.set_defaults(func=cmd_public_benchmark)

    p_jobs = sub.add_parser(
        "jobs",
        help="submit, inspect, or resume shared execution jobs",
    )
    jobs_sub = p_jobs.add_subparsers(dest="jobs_command", required=True)
    p_jobs_submit = jobs_sub.add_parser(
        "submit",
        help="bind and dispatch an execution-job JSON specification",
    )
    p_jobs_submit.add_argument("spec", help="path to execution-job JSON")
    p_jobs_submit.add_argument("--threads", type=int, default=1)
    p_jobs_submit.set_defaults(func=cmd_jobs_submit)

    p_jobs_status = jobs_sub.add_parser(
        "status",
        help="inspect a submitted job without dispatching work",
    )
    p_jobs_status.add_argument("job_id", help="immutable execution job id")
    p_jobs_status.set_defaults(func=cmd_jobs_status)

    p_jobs_resume = jobs_sub.add_parser(
        "resume",
        help="resume unfinished work from append-only checkpoints",
    )
    p_jobs_resume.add_argument("job_id", help="immutable execution job id")
    p_jobs_resume.add_argument("--threads", type=int, default=1)
    p_jobs_resume.set_defaults(func=cmd_jobs_resume)

    p_run_pkg = sub.add_parser("run-package", help="run a Benchmark Package against a model")
    p_run_pkg.add_argument("package", help="path to a benchmark package directory")
    p_run_pkg.add_argument("--model", required=True, help="model id (litellm format)")
    p_run_pkg.add_argument("--trials", type=int, default=None)
    p_run_pkg.add_argument("--threads", type=int, default=None)
    p_run_pkg.add_argument("--limit", type=int, default=None,
                           help="cap the number of items (for smoke tests)")
    p_run_pkg.add_argument("--bootstrap", type=int, default=0,
                           help="bootstrap iterations for CI (0 = normal approx)")
    p_run_pkg.add_argument(
        "--provider-authorization",
        default=None,
        help="strict provider-disclosure authorization JSON for non-public data",
    )
    p_run_pkg.set_defaults(func=cmd_run_package)

    p_run_tool = sub.add_parser("run-tool", help="run a tool-using agent (SUT) against a package cohort")
    p_run_tool.add_argument("package", help="path to a benchmark package directory (needs cohort/)")
    p_run_tool.add_argument("--model", required=True, help="executor model id (litellm format)")
    p_run_tool.add_argument("--system-prompt", default=None,
                            help="agent instructions, or @path to read from a file")
    p_run_tool.add_argument(
        "--max-iters",
        type=int,
        default=None,
        help="legacy package override (build-spec v2 binds max turns)",
    )
    p_run_tool.add_argument("--trials", type=int, default=None)
    p_run_tool.add_argument("--threads", type=int, default=None)
    p_run_tool.add_argument("--limit", type=int, default=None)
    p_run_tool.add_argument(
        "--provider-authorization",
        default=None,
        help="strict provider-disclosure authorization JSON for non-public data",
    )
    p_run_tool.set_defaults(func=cmd_run_tool)

    p_report = sub.add_parser("report", help="build a model card (+ optional checklist) from a scores CSV")
    p_report.add_argument("scores", help="path to a scores CSV or a compiled.csv")
    p_report.add_argument("--model", default=None, help="model to select (with --compiled)")
    p_report.add_argument("--compiled", action="store_true",
                          help="treat the input as a multi-model compiled.csv")
    p_report.add_argument("--checklist", default=None,
                          help="checklist name to append (e.g. tripod_llm)")
    p_report.add_argument("--output", default=None, help="write markdown here instead of stdout")
    p_report.set_defaults(func=cmd_report)

    p_compare = sub.add_parser("compare", help="build a comparative scorecard across tools")
    p_compare.add_argument("--vendor", action="append", default=[], metavar="NAME=CSV",
                           help="a vendor label and its scores CSV; repeatable")
    p_compare.add_argument("--higher-is-better", default=None,
                           help="comma list of criterion:false direction overrides")
    p_compare.add_argument("--output", default=None, help="write the scorecard CSV here")
    p_compare.set_defaults(func=cmd_compare)

    p_monitor = sub.add_parser("monitor", help="run a canary and check it against a baseline")
    p_monitor.add_argument("benchmark", help="benchmark name (matches benchmarks/<name>/)")
    p_monitor.add_argument("--config", required=True, help="path to a MonitorConfig JSON")
    p_monitor.add_argument("--model", default=None, help="override the model in the config")
    p_monitor.add_argument("--timestamp", default=None, help="ISO timestamp for the canary row")
    p_monitor.set_defaults(func=cmd_monitor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
