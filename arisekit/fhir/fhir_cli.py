"""FHIR environment commands; reuse the generation controller and benchmark runner."""
from dataclasses import asdict
import json
from pathlib import Path

from arisekit.fhir.fhir_workflow import generation_request, validate_brief


def command(args):
    from arisekit.generation.autonomous_generation import run_autonomous_generation
    from arisekit.benchmark import Benchmark
    from arisekit.dataset import Dataset
    from arisekit.runner import RunnerConfig
    from arisekit.package import load_package
    try:
        if args.fhir_command == "native":
            from arisekit.fhir.fhir_native import freeze, verify, NativeMedAgentSUT, NativeMedAgentScorer, TASK_FILE
            if args.native_command == "freeze":
                print(json.dumps(freeze(args.source, args.output), indent=2))
                return 0
            binding = json.loads(Path(args.binding).read_text())
            verify(args.source, binding)
            from arisekit.types import BenchmarkItem
            tasks = json.loads((Path(args.source) / TASK_FILE).read_text())
            selected = [row for row in tasks if int(row["id"].split("_")[1]) <= args.per_family
                        and int(row["id"].split("_")[0][4:]) in args.categories]
            dataset = Dataset([BenchmarkItem(id=row["id"],
                prompt=f"<instruction>\n{row['instruction']}\n</instruction>\n<context>\n{row['context']}\n</context>\n",
                ground_truth={"binding_sha256": binding["binding_sha256"]},
                metadata={"category": row["id"].split("_")[0]}) for row in selected])
            benchmark = Benchmark(name="medagent-native-original-v2", dataset=dataset,
                scorer=NativeMedAgentScorer(binding["binding_sha256"]),
                runner_config=RunnerConfig(max_calls=args.max_calls, max_cost=args.max_cost,
                    max_cost_per_call=args.max_cost_per_call, require_known_cost=True, max_retries=1))
            result = benchmark.run(NativeMedAgentSUT(args.source, binding, args.model),
                results_dir=args.output, threads=1, auto_manifest=True)
            receipt = {"binding_sha256": binding["binding_sha256"], "expected": len(selected),
                "completed": result.summary.completed, "errors": result.summary.errored,
                "model": args.model, "cost_usd": result.cost, "calls": result.summary.calls_total,
                "stop_reason": result.summary.stop_reason, "metrics": [m.to_dict() for m in result.metrics],
                "agent": binding["agent"], "per_family": args.per_family}
            (Path(args.output) / "native-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps(receipt, indent=2))
            return 2 if result.summary.errored or result.summary.stop_reason else 0
        if args.fhir_command == "review":
            from arisekit.fhir.fhir_review import prepare, summarize
            report = prepare(args.package, args.output) if args.review_command == "prepare" else summarize(args.packet, args.ratings)
            print(json.dumps(report, indent=2))
            return 0
        if args.fhir_command == "generate":
            brief = validate_brief(json.loads(Path(args.brief).read_text()))
            limits = brief["limits"]
            report = run_autonomous_generation(Dataset([generation_request(brief)]), model=args.model,
                config=RunnerConfig(max_calls=limits["max_calls"], max_cost=limits["max_cost"],
                    max_cost_per_call=limits["max_cost_per_call"], require_known_cost=True, max_tokens=12000),
                output_dir=args.output, data_classification=brief["data_classification"], max_repairs=1)
            print(json.dumps(report, indent=2, default=str))
            return 0 if report.get("compiled") == report.get("requested") and not report.get("stop_reason") else 2
        package = load_package(args.package, verify_assets=True)
        from arisekit.fhir.fhir_workflow import binding_from_package, FHIROutcomeScorer
        binding = binding_from_package(package)
        benchmark = Benchmark.from_package(args.package)
        benchmark.runner_config = RunnerConfig(max_calls=binding.limits["max_calls"],
            max_cost=binding.limits["max_cost"], max_cost_per_call=binding.limits["max_cost_per_call"],
            require_known_cost=True, max_retries=1)
        model = "stub/reference" if args.fhir_command == "validate" else args.model
        results = benchmark.run(model, trials=args.trials, threads=1,
                                results_dir=args.output, auto_manifest=True)
        report = {"summary": {**asdict(results.summary), "output_path": str(results.summary.output_path)},
                  "scores": [{"id": item.id, "metrics": [m.to_dict() for m in FHIROutcomeScorer().score_item(item,
                      [r for r in results.raw if r.id == item.id])]} for item in package.items]}
        if args.fhir_command == "validate":
            from arisekit.fhir.fhir_workflow import validation_controls
            report["controls"] = validation_controls(package, results, args.trials)
        output = Path(args.output) / "fhir-report.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        return 2 if results.summary.errored or results.summary.stop_reason or not report.get("controls", {"passed": True})["passed"] else 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"FHIR environment: {exc}")
        return 2


def add_parser(sub):
    parser = sub.add_parser("fhir", help="generate and evaluate a Docker-backed FHIR R4 benchmark")
    commands = parser.add_subparsers(dest="fhir_command", required=True)
    native = commands.add_parser("native", help="freeze or run an explicitly matched original MedAgentBench release")
    native_commands = native.add_subparsers(dest="native_command", required=True)
    freeze = native_commands.add_parser("freeze")
    freeze.add_argument("--source", required=True, help="authorized medagentbench_v2 checkout")
    freeze.add_argument("--output", required=True)
    freeze.set_defaults(func=command)
    native_eval = native_commands.add_parser("eval")
    native_eval.add_argument("--source", required=True)
    native_eval.add_argument("--binding", required=True)
    native_eval.add_argument("--model", required=True)
    native_eval.add_argument("--per-family", type=int, choices=range(1, 31), default=1)
    native_eval.add_argument("--categories", type=int, nargs="+", choices=range(1, 11), default=list(range(1, 11)))
    native_eval.add_argument("--max-calls", type=int, default=64)
    native_eval.add_argument("--max-cost", type=float, default=3)
    native_eval.add_argument("--max-cost-per-call", type=float, default=0.25)
    native_eval.add_argument("--output", required=True, help="private retained results directory")
    native_eval.set_defaults(func=command)
    review = commands.add_parser("review", help="prepare and summarize independent clinical review")
    reviews = review.add_subparsers(dest="review_command", required=True)
    packet = reviews.add_parser("prepare")
    packet.add_argument("package")
    packet.add_argument("--output", required=True)
    packet.set_defaults(func=command)
    summary = reviews.add_parser("summarize")
    summary.add_argument("--packet", required=True)
    summary.add_argument("--ratings", required=True)
    summary.set_defaults(func=command)
    generate = commands.add_parser("generate", help="freeze an authored brief and generate a runnable FHIR package")
    generate.add_argument("--brief", required=True)
    generate.add_argument("--model", required=True)
    generate.add_argument("--output", required=True)
    generate.set_defaults(func=command)
    evaluate = commands.add_parser("eval", help="run a package in disposable HAPI containers, with resume")
    evaluate.add_argument("package")
    evaluate.add_argument("--model", required=True, help="provider model or stub/reference for an executable positive control")
    evaluate.add_argument("--trials", type=int, default=1)
    evaluate.add_argument("--output", required=True)
    evaluate.set_defaults(func=command)
    validate = commands.add_parser("validate", help="execute positive plans twice and test null/mutation controls")
    validate.add_argument("package")
    validate.add_argument("--trials", type=int, default=2)
    validate.add_argument("--output", required=True)
    validate.set_defaults(func=command)
