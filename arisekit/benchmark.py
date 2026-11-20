"""The Benchmark class: dataset + scorer + run."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from arisekit.agentic import run_agent
from arisekit.client import REFERENCE_STUB_MODEL, ModelClient
from arisekit.common.jsonio import canonical_json as _canonical_json_text
from arisekit.dataset import Dataset
from arisekit.egress import (
    ProviderDisclosureAuthorization,
    ProviderDisclosureRequirement,
    generated_bundle_hash,
)
from arisekit.run_manifest import (
    RunManifest,
    build_automatic_run_manifest,
    sha256_digest,
)
from arisekit.runner import RunSummary, RunnerConfig, run as run_dataset
from arisekit.scorer import BaseScorer
from arisekit.analysis.stats import aggregate
from arisekit.sut import SystemUnderTest
from arisekit.types import Metric, RunResult, Tool

if TYPE_CHECKING:
    from arisekit.runtime.cost_preview import (
        CostPreview,
        PricingResolver,
        PricingSnapshot,
        TokenEstimator,
    )
    from arisekit.runtime.rescore import ScoringRevision
    from arisekit.analysis.sweep import BenchmarkSweepResults, BenchmarkSweepSpec


@dataclass
class Results:
    """The output of Benchmark.run(): raw responses, per-item metrics, aggregates."""

    benchmark: str
    model: str
    raw: list[RunResult]
    per_item: list[tuple[str, list[Metric]]]
    metrics: list[Metric]
    summary: RunSummary
    bundle_path: Path | None = None
    report_path: Path | None = None
    judge_summary: dict[str, Any] | None = None
    judge_artifacts: list[Path] = field(default_factory=list)

    @property
    def cost(self) -> float:
        return self.summary.cost_total

    def to_csv(self, path: str | Path) -> Path:
        """Write the `benchmark,model,category,metric,n,value,ci` shape."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError(f"refusing to replace symlink score output: {path}")
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh, lineterminator="\n")
                writer.writerow(
                    ["benchmark", "model", "category", "metric", "n", "value", "ci"]
                )
                for m in self.metrics:
                    writer.writerow([
                        self.benchmark,
                        self.model,
                        m.category,
                        m.name,
                        m.n if m.n is not None else "",
                        f"{m.value:.6f}",
                        f"{m.ci:.6f}" if m.ci is not None else "",
                    ])
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return path


class BenchmarkScoringError(RuntimeError):
    """Scoring failed after inference artifacts and accounting were retained."""

    def __init__(
        self,
        *,
        benchmark: str,
        model: str,
        raw: Sequence[RunResult],
        summary: RunSummary,
        cause: Exception,
    ) -> None:
        self.benchmark = benchmark
        self.model = model
        self.raw = tuple(raw)
        self.summary = summary
        self.cause_type = type(cause).__name__
        super().__init__(
            f"scoring failed after inference: {self.cause_type}: {cause}"
        )


@dataclass(frozen=True)
class _GatedPackageBinding:
    benchmark_content_hash: str
    system_prompt: str | None
    system_prompt_hash: str
    scorer_fingerprint: str
    scorer_object: BaseScorer
    scorer_spec_json: str


class Benchmark:
    """A benchmark = dataset + scorer + a name. Run on one or more models."""

    def __init__(
        self,
        *,
        name: str,
        dataset: Dataset,
        scorer: BaseScorer,
        runner_config: RunnerConfig | None = None,
        tools: list[Tool] | None = None,
        max_turns: int = 8,
        allowed_model_routes: Sequence[str] | None = None,
        provider_disclosure_requirement: ProviderDisclosureRequirement | None = None,
        sut_factory: Callable[..., SystemUnderTest] | None = None,
        package_asset_manifest_sha256: str | None = None,
    ):
        if (
            isinstance(max_turns, bool)
            or not isinstance(max_turns, int)
            or max_turns < 1
        ):
            raise ValueError("max_turns must be a positive integer")
        self.name = name
        self.dataset = dataset
        self.scorer = scorer
        self.runner_config = runner_config or RunnerConfig()
        self.tools = list(tools) if tools is not None else None
        self.max_turns = max_turns
        self._sut_factory = sut_factory
        self._package_modality = None
        self._package_asset_manifest_sha256 = package_asset_manifest_sha256
        self.allowed_model_routes = _normalize_allowed_model_routes(
            allowed_model_routes
        )
        if (
            provider_disclosure_requirement is not None
            and not isinstance(
                provider_disclosure_requirement, ProviderDisclosureRequirement
            )
        ):
            raise TypeError(
                "provider_disclosure_requirement must be a "
                "ProviderDisclosureRequirement"
            )
        self._provider_disclosure_requirement = provider_disclosure_requirement
        self._gated_package_binding: _GatedPackageBinding | None = None
        self.scorer.configure(system_prompt=dataset.system_prompt)

    @property
    def provider_disclosure_requirement(
        self,
    ) -> ProviderDisclosureRequirement | None:
        return self._provider_disclosure_requirement

    def run(
        self,
        model: str | ModelClient | SystemUnderTest,
        *,
        trials: int | None = None,
        threads: int | None = None,
        limit: int | None = None,
        results_dir: str | Path | None = None,
        bootstrap: int = 0,
        bootstrap_seed: int | None = None,
        on_progress: Callable[[RunResult], None] | None = None,
        manifest: RunManifest | None = None,
        auto_manifest: bool = False,
        max_cost: float | None = None,
        max_calls: int | None = None,
        provider_authorization: ProviderDisclosureAuthorization | None = None,
        provider_profile: Any = None,
    ) -> Results:
        if isinstance(bootstrap, bool) or not isinstance(bootstrap, int) or bootstrap < 0:
            raise ValueError("bootstrap must be a non-negative integer")
        if bootstrap_seed is not None and (
            isinstance(bootstrap_seed, bool) or not isinstance(bootstrap_seed, int)
        ):
            raise ValueError("bootstrap_seed must be an integer or None")
        cfg = RunnerConfig(
            trials=trials if trials is not None else self.runner_config.trials,
            threads=threads if threads is not None else self.runner_config.threads,
            max_retries=self.runner_config.max_retries,
            retry_backoff=self.runner_config.retry_backoff,
            results_dir=Path(results_dir) if results_dir else self.runner_config.results_dir,
            temperature=self.runner_config.temperature,
            max_tokens=self.runner_config.max_tokens,
            max_cost=max_cost if max_cost is not None else self.runner_config.max_cost,
            max_cost_per_call=self.runner_config.max_cost_per_call,
            require_known_cost=self.runner_config.require_known_cost,
            max_calls=max_calls if max_calls is not None else self.runner_config.max_calls,
            reserved_failure_types=self.runner_config.reserved_failure_types,
        )
        fhir_limits = getattr(self, "_fhir_limits", None)
        if fhir_limits is not None:
            for key in ("max_cost", "max_cost_per_call", "max_calls"):
                value = getattr(cfg, key)
                if value is None or value > fhir_limits[key]:
                    raise ValueError(f"{key} exceeds the frozen FHIR brief")
            if not cfg.require_known_cost:
                raise ValueError("FHIR packages require known provider costs")
        runtime_dataset = self.dataset
        runtime_scorer = self.scorer
        if self.provider_disclosure_requirement is not None:
            if not isinstance(model, str):
                raise ValueError(
                    "non-public build-spec v1 benchmarks require a standard "
                    "string-backed model route; custom clients, endpoints, and "
                    "systems under test are not authorized"
                )
            if self.tools is not None:
                raise ValueError(
                    "non-public build-spec v1 text benchmarks cannot add tools"
                )
            runtime_dataset, runtime_scorer = self._validated_gated_runtime()
        if provider_profile is not None:
            from arisekit.providers import ProviderProfile
            if not isinstance(provider_profile, ProviderProfile) or model != provider_profile.model:
                raise ValueError("provider profile must match the requested model route")
            if self.provider_disclosure_requirement is not None:
                raise ValueError("provider profiles need a separate reviewed endpoint authorization for non-public packages")
            configured_limit = cfg.max_tokens
            pinned = dict(provider_profile.parameters)
            cfg.temperature = pinned.get("temperature")
            cfg.max_tokens = min(configured_limit, pinned.get("max_tokens", pinned.get("max_completion_tokens"))) if configured_limit is not None else None
            model = provider_profile.client()
        ds = runtime_dataset.limit(limit) if limit else runtime_dataset

        if self._sut_factory is not None and not isinstance(model, SystemUnderTest):
            sut = self._sut_factory(
                model,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )
        elif not isinstance(model, SystemUnderTest) and self.tools is not None:
            sut = SystemUnderTest.from_agent(
                model,
                self.tools,
                max_iters=self.max_turns,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )
        else:
            sut = SystemUnderTest.resolve(model)
        execution_route = _execution_model_route(model, sut)
        if (
            self.allowed_model_routes is not None
            and execution_route not in self.allowed_model_routes
        ):
            allowed = ", ".join(self.allowed_model_routes)
            raise ValueError(
                f"model route {execution_route!r} is not in this benchmark's "
                f"reviewed allowlist: {allowed}"
            )
        if self.provider_disclosure_requirement is not None:
            self.provider_disclosure_requirement.validate_authorization(
                model_route=execution_route,
                authorization=provider_authorization,
            )
        effective_manifest = manifest
        if effective_manifest is None and (
            auto_manifest or self.provider_disclosure_requirement is not None
        ):
            effective_manifest = self._automatic_manifest(
                model=model,
                sut=sut,
                cfg=cfg,
                selected=ds,
                limit=limit,
                bootstrap=bootstrap,
                bootstrap_seed=bootstrap_seed,
                provider_authorization=provider_authorization,
                execution_route=execution_route,
                runtime_dataset=runtime_dataset,
                runtime_scorer=runtime_scorer,
            )
        elif (
            effective_manifest is not None
            and self.provider_disclosure_requirement is not None
        ):
            self._validate_provider_disclosure_manifest(
                effective_manifest,
                provider_authorization=provider_authorization,
                execution_route=execution_route,
            )
        raw, summary = run_dataset(
            ds,
            model=sut,
            benchmark_name=self.name,
            config=cfg,
            on_progress=on_progress,
            manifest=effective_manifest,
        )

        model_id = sut.name
        from arisekit.judges.rubric import RubricJudge
        rubric_scorer = runtime_scorer if isinstance(runtime_scorer, RubricJudge) else None
        judge_summary = None
        judge_artifacts = []
        if rubric_scorer is not None:
            rubric_scorer.begin_run(summary.output_path.parent / (summary.output_path.stem + ".judges"), smoke=execution_route == "stub/reference")
        try:
            # Scorers decide how failures contribute. Passing every result ensures
            # an errored item is not silently removed from the aggregate.
            by_item: dict[str, list[RunResult]] = defaultdict(list)
            for r in raw:
                by_item[r.id].append(r)

            per_item: list[tuple[str, list[Metric]]] = []
            for item in ds:
                responses = by_item.get(item.id, [])
                if not responses:
                    continue
                metrics = runtime_scorer.score_item(item, responses)
                per_item.append((item.id, metrics))

            metrics = aggregate(
                (m for _, m in per_item),
                bootstrap=bootstrap,
                seed=bootstrap_seed,
            )
        except Exception as exc:  # noqa: BLE001 - retain post-inference evidence
            raise BenchmarkScoringError(
                benchmark=self.name,
                model=model_id,
                raw=raw,
                summary=summary,
                cause=exc,
            ) from exc
        finally:
            if rubric_scorer is not None:
                judge_summary = rubric_scorer.end_run()
                judge_artifacts = [p for p in (rubric_scorer.journal_path, rubric_scorer.summary_path, rubric_scorer.summary_path.parent / "judge-calls.jsonl") if p is not None and p.exists()]

        results = Results(
            benchmark=self.name,
            model=model_id,
            raw=raw,
            per_item=per_item,
            metrics=metrics,
            summary=summary,
            judge_summary=judge_summary,
            judge_artifacts=judge_artifacts,
        )

        # Persist scores alongside raw checkpoints.
        scores_root = cfg.results_dir / "scores" / self.name
        if summary.manifest_digest is not None:
            scores_root = scores_root / summary.manifest_digest
        scores_path = scores_root / f"{_slug(model_id)}.csv"
        results.to_csv(scores_path)
        from arisekit.run_inspection import write_run_inspection

        inspection = write_run_inspection(
            results,
            scores_path=scores_path,
            results_root=cfg.results_dir,
        )
        results.bundle_path = inspection.bundle_path
        results.report_path = inspection.report_path
        return results

    def rescore(
        self,
        checkpoint: str | Path,
        *,
        scorer: BaseScorer | None = None,
        baseline: ScoringRevision | str | Path | None = None,
        primary_metric: str | tuple[str, str] | None = None,
        bootstrap: int = 0,
        seed: int = 0,
        results_dir: str | Path | None = None,
        model: str | None = None,
        expected_trials: int | None = None,
    ) -> ScoringRevision:
        """Create an immutable scoring revision without invoking the solver."""

        from arisekit.runtime.rescore import load_responses, rescore

        captured = load_responses(
            checkpoint,
            benchmark=self,
            model=model,
            expected_trials=expected_trials,
        )
        return rescore(
            captured,
            scorer=self.scorer if scorer is None else scorer,
            results_dir=(
                Path(results_dir)
                if results_dir is not None
                else self.runner_config.results_dir
            ),
            baseline=baseline,
            primary_metric=primary_metric,
            bootstrap=bootstrap,
            seed=seed,
        )

    def preview_cost(
        self,
        model: str,
        *,
        trials: int | None = None,
        limit: int | None = None,
        max_tokens: int | None = None,
        pricing: PricingSnapshot | None = None,
        token_estimator: TokenEstimator | None = None,
        pricing_resolver: PricingResolver | None = None,
    ) -> CostPreview:
        """Prepare a deterministic, no-dispatch cost preview receipt."""

        from arisekit.runtime.cost_preview import preview_benchmark_cost

        return preview_benchmark_cost(
            self,
            model=model,
            trials=trials,
            limit=limit,
            max_tokens=max_tokens,
            pricing=pricing,
            token_estimator=token_estimator,
            pricing_resolver=pricing_resolver,
        )

    def run_many(
        self,
        models: Sequence[str] | BenchmarkSweepSpec,
        *,
        providers: Mapping[str, str] | None = None,
        trials: int | Mapping[str, int] | None = None,
        threads: int | None = None,
        limit: int | None = None,
        bootstrap: int = 0,
        bootstrap_seed: int = 0,
        max_cost: float | None = None,
        max_calls: int | None = None,
        cost_preview_digest: str | None = None,
        results_dir: str | Path | None = None,
        provider_authorizations: Mapping[
            str, ProviderDisclosureAuthorization
        ] | None = None,
    ) -> BenchmarkSweepResults:
        """Run one benchmark over an explicit ordered model list.

        Advanced callers may pass a ``BenchmarkSweepSpec`` directly as
        ``models``. String routes use the benchmark trial count unless a
        shared integer or per-route mapping is supplied.
        """

        from arisekit.analysis.sweep import (
            BenchmarkSweepSpec,
            SweepModel,
            run_benchmark_sweep,
        )

        if isinstance(models, BenchmarkSweepSpec):
            if (
                providers is not None
                or trials is not None
                or threads is not None
                or limit is not None
                or bootstrap != 0
                or bootstrap_seed != 0
                or max_cost is not None
                or max_calls is not None
                or cost_preview_digest is not None
            ):
                raise ValueError(
                    "execution settings cannot override a BenchmarkSweepSpec"
                )
            spec = models
        else:
            if isinstance(models, (str, bytes)):
                raise TypeError("models must be a sequence of model routes")
            routes = tuple(models)
            if not routes:
                raise ValueError("models must not be empty")
            if any(not isinstance(route, str) for route in routes):
                raise TypeError("models must contain only string model routes")
            provider_map = dict(providers or {})
            extras = sorted(set(provider_map) - set(routes))
            if extras:
                raise ValueError(
                    "providers include unselected model routes: " + ", ".join(extras)
                )
            if isinstance(trials, Mapping):
                trial_map = dict(trials)
                extras = sorted(set(trial_map) - set(routes))
                missing = sorted(set(routes) - set(trial_map))
                if extras or missing:
                    detail = []
                    if missing:
                        detail.append("missing " + ", ".join(missing))
                    if extras:
                        detail.append("unselected " + ", ".join(extras))
                    raise ValueError(
                        "per-model trials must exactly cover selected routes ("
                        + "; ".join(detail)
                        + ")"
                    )
            else:
                count = self.runner_config.trials if trials is None else trials
                trial_map = {route: count for route in routes}
            planned = tuple(
                SweepModel(
                    model=route,
                    provider=provider_map.get(
                        route,
                        "stub" if route == REFERENCE_STUB_MODEL else "litellm",
                    ),
                    trials=trial_map[route],
                )
                for route in routes
            )
            spec = BenchmarkSweepSpec(
                benchmark=self.name,
                models=planned,
                allowed_model_routes=self.allowed_model_routes,
                threads=threads if threads is not None else self.runner_config.threads,
                limit=limit,
                bootstrap=bootstrap,
                bootstrap_seed=bootstrap_seed,
                max_cost=max_cost,
                max_calls=max_calls,
                cost_preview_digest=cost_preview_digest,
            )
        return run_benchmark_sweep(
            self,
            spec,
            results_dir=(
                Path(results_dir)
                if results_dir is not None
                else self.runner_config.results_dir
            ),
            provider_authorizations=provider_authorizations,
        )

    def _automatic_manifest(
        self,
        *,
        model: str | ModelClient | SystemUnderTest,
        sut: SystemUnderTest,
        cfg: RunnerConfig,
        selected: Dataset,
        limit: int | None,
        bootstrap: int,
        bootstrap_seed: int | None,
        provider_authorization: ProviderDisclosureAuthorization | None,
        execution_route: str,
        runtime_dataset: Dataset,
        runtime_scorer: BaseScorer,
    ) -> RunManifest:
        tools_value = getattr(sut, "tools", None)
        tools = list(tools_value) if tools_value is not None else list(self.tools or [])
        client = getattr(sut, "agent_client", None)
        if client is None:
            client = getattr(sut, "client", None)
        if self.provider_disclosure_requirement is not None:
            provider = self.provider_disclosure_requirement.provider_for_route(
                execution_route
            )
        elif model == REFERENCE_STUB_MODEL:
            provider = "stub"
        else:
            provider = (
                "litellm"
                if isinstance(model, str)
                else f"python:{type(sut).__module__}.{type(sut).__qualname__}"
            )
        own_prompt = getattr(sut, "system_prompt", None)
        effective_prompt = own_prompt or runtime_dataset.system_prompt

        code_objects: list[Any] = [runtime_scorer, type(sut), run_dataset, Benchmark]
        code_objects.extend(tool.fn for tool in tools)
        if client is not None:
            code_objects.append(type(client))
        if tools:
            code_objects.append(run_agent)

        client_config: dict[str, Any] = {}
        if client is not None:
            for name in ("temperature", "max_tokens", "timeout"):
                if hasattr(client, name):
                    client_config[name] = getattr(client, name)
            api_base = getattr(client, "api_base", None)
            if api_base is not None:
                client_config["api_base_hash"] = sha256_digest(str(api_base))
            profile = getattr(client, "profile", None)
            if profile is not None:
                client_config["provider_profile_sha256"] = profile.digest
            extra = getattr(client, "extra", None)
            if extra is not None:
                client_config["extra_hash"] = sha256_digest(extra)

        disclosure_identity: dict[str, str] | None = None
        if self.provider_disclosure_requirement is not None:
            if provider_authorization is None:
                raise ValueError(
                    "provider-disclosure authorization is required for the "
                    "automatic run manifest"
                )
            disclosure_identity = self._provider_disclosure_identity(
                provider_authorization
            )

        model_config = {
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "max_turns": getattr(sut, "max_iters", None),
            "threads": cfg.threads,
            "max_retries": cfg.max_retries,
            "retry_backoff": cfg.retry_backoff,
            "max_cost_per_call": cfg.max_cost_per_call,
            "require_known_cost": cfg.require_known_cost,
            "bootstrap": bootstrap,
            "client": client_config,
        }
        if cfg.reserved_failure_types:
            model_config["reserved_failure_types"] = list(cfg.reserved_failure_types)
        if bootstrap_seed is not None:
            model_config["bootstrap_seed"] = bootstrap_seed
        if self._package_asset_manifest_sha256 is not None:
            model_config["package_asset_manifest_sha256"] = (
                self._package_asset_manifest_sha256
            )
        if disclosure_identity is not None:
            model_config["provider_disclosure"] = disclosure_identity

        return build_automatic_run_manifest(
            benchmark_name=self.name,
            items=runtime_dataset,
            selected_item_ids=[item.id for item in selected],
            system_prompt=effective_prompt,
            tools=tools,
            code_objects=code_objects,
            model=sut.name,
            model_route=execution_route,
            provider=provider,
            trials=cfg.trials,
            limit=limit,
            model_config=model_config,
        )

    def _validated_gated_runtime(self) -> tuple[Dataset, BaseScorer]:
        binding = self._gated_package_binding
        if binding is None:
            raise ValueError(
                "non-public benchmark is missing its strict package binding"
            )
        try:
            item_payload = [item.to_dict() for item in self.dataset]
            item_json = _canonical_json_text(item_payload)
            content_hash = sha256_digest(item_payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"runtime dataset is not the authorized package snapshot: {exc}"
            ) from exc
        if content_hash != binding.benchmark_content_hash:
            raise ValueError(
                "runtime dataset content does not match the authorized package"
            )
        if self.dataset.system_prompt != binding.system_prompt:
            raise ValueError(
                "runtime system prompt does not match the authorized package"
            )
        if sha256_digest(self.dataset.system_prompt or "") != binding.system_prompt_hash:
            raise ValueError(
                "runtime system prompt hash does not match the authorized package"
            )
        if self.scorer is not binding.scorer_object:
            raise ValueError(
                "runtime scorer is not the package's canonical deterministic scorer"
            )
        if _scorer_fingerprint(self.scorer) != binding.scorer_fingerprint:
            raise ValueError(
                "runtime scorer configuration does not match the authorized package"
            )

        from arisekit.package import BenchmarkManifest, scorer_from_manifest

        scorer_spec = json.loads(binding.scorer_spec_json)
        runtime_scorer = scorer_from_manifest(
            BenchmarkManifest(
                id=self.name,
                name=self.name,
                scorer=scorer_spec,
            )
        )
        if runtime_scorer is None:
            raise ValueError(
                "authorized package scorer is no longer deterministically bindable"
            )
        runtime_scorer.configure(system_prompt=binding.system_prompt)
        runtime_dataset = Dataset.from_items(
            json.loads(item_json),
            system_prompt=binding.system_prompt,
            name=self.dataset.name,
        )
        return runtime_dataset, runtime_scorer

    def _provider_disclosure_identity(
        self,
        provider_authorization: ProviderDisclosureAuthorization,
    ) -> dict[str, str]:
        requirement = self.provider_disclosure_requirement
        if requirement is None:
            raise ValueError("benchmark has no provider-disclosure requirement")
        return {
            "generated_bundle_hash": requirement.generated_bundle_hash,
            "authorization_digest": provider_authorization.digest,
        }

    def _validate_provider_disclosure_manifest(
        self,
        manifest: RunManifest,
        *,
        provider_authorization: ProviderDisclosureAuthorization | None,
        execution_route: str,
    ) -> None:
        if provider_authorization is None:
            raise ValueError(
                "provider-disclosure authorization is required for the run manifest"
            )
        expected = self._provider_disclosure_identity(provider_authorization)
        declared_route = manifest.model_config.get("route")
        if declared_route != execution_route:
            raise ValueError(
                "caller-supplied run manifest route does not match the selected "
                f"model route: expected {execution_route!r}"
            )
        requirement = self.provider_disclosure_requirement
        assert requirement is not None
        binding = self._gated_package_binding
        if binding is None:
            raise ValueError(
                "non-public benchmark is missing its strict package binding"
            )
        if manifest.benchmark_content_hash != binding.benchmark_content_hash:
            raise ValueError(
                "caller-supplied run manifest does not bind the authorized "
                "package dataset"
            )
        if manifest.prompt_hash != binding.system_prompt_hash:
            raise ValueError(
                "caller-supplied run manifest does not bind the authorized "
                "package system prompt"
            )
        expected_provider = requirement.provider_for_route(execution_route)
        if manifest.provider != expected_provider:
            raise ValueError(
                "caller-supplied run manifest provider does not match the "
                f"reviewed provider: expected {expected_provider!r}"
            )
        declared = manifest.model_config.get("provider_disclosure")
        if not isinstance(declared, Mapping) or dict(declared) != expected:
            raise ValueError(
                "caller-supplied run manifest does not bind the exact "
                f"provider disclosure: expected {expected!r}"
            )

    @classmethod
    def from_package(
        cls,
        pkg_or_path: Any,
        *,
        scorer: BaseScorer | None = None,
        runner_config: RunnerConfig | None = None,
        system_prompt: str | None = None,
        allowed_model_routes: Sequence[str] | None = None,
    ) -> "Benchmark":
        """Construct a Benchmark from a Benchmark Package.

        Deterministic scorer kinds (exact-match, contains, choice,
        numeric, and versioned pass-at-one) are bound automatically from
        the manifest. Rubric-panel and trajectory-judge scorers still need
        a caller-supplied judge client. Agentic/FHIR packages bind their
        environment and tool catalog from ``env.json``. A reviewed
        model-route allowlist in package provenance is restored
        automatically. Callers may narrow it but cannot expand it.
        """
        from arisekit.package import (
            ASSET_MANIFEST_FILENAME,
            BenchmarkPackage,
            agentic_fhir_binding_from_package,
            dataset_from_package,
            load_package,
            multimodal_image_binding_from_package,
            scorer_from_manifest,
        )

        if isinstance(pkg_or_path, BenchmarkPackage):
            package_root = Path(pkg_or_path.root)
            asset_path = package_root / ASSET_MANIFEST_FILENAME
            if (
                pkg_or_path.asset_manifest is not None
                or asset_path.is_file()
                or asset_path.is_symlink()
            ):
                pkg = load_package(package_root, verify_assets=True)
            else:
                pkg = pkg_or_path
        else:
            package_root = Path(pkg_or_path)
            pkg = load_package(
                package_root,
                verify_assets=(
                    (package_root / ASSET_MANIFEST_FILENAME).is_file()
                    or (package_root / ASSET_MANIFEST_FILENAME).is_symlink()
                ),
            )
        build_schema = _manifest_build_spec_schema(pkg.manifest.provenance)
        is_generated_build = build_schema is not None
        if is_generated_build and pkg.asset_manifest is None:
            raise ValueError(
                f"{build_schema} packages require a verified asset-manifest.json"
            )
        if build_schema == "arisekit.benchmark-build-spec.v2":
            _validate_agentic_v2_governance(pkg.manifest.provenance)
        if build_schema == "arisekit.benchmark-build-spec.v3":
            _validate_multimodal_v3_governance(pkg.manifest.provenance)
        package_routes = _manifest_allowed_model_routes(pkg.manifest.provenance)
        disclosure_requirement = _manifest_provider_disclosure_requirement(
            pkg,
            package_routes=package_routes,
        )
        canonical_prompt = system_prompt
        if is_generated_build:
            canonical_prompt = _manifest_system_prompt(pkg.manifest.provenance)
            if system_prompt is not None and system_prompt != canonical_prompt:
                raise ValueError(
                    "system_prompt cannot override the prompt frozen in a "
                    f"{build_schema} package"
                )
            if scorer is not None:
                raise ValueError(
                    f"scorer overrides are not allowed for {build_schema} packages"
                )
        image_inference = pkg.manifest.provenance.get("image_inference")
        if pkg.manifest.provenance.get("image_task_schema") == "arisekit.image-task.v1" and image_inference is not None:
            if (not isinstance(image_inference, dict) or
                set(image_inference) != {"schema_version", "system_prompt", "temperature", "max_tokens"} or
                image_inference["schema_version"] != "arisekit.image-inference.v1" or
                not isinstance(image_inference["system_prompt"], str) or not image_inference["system_prompt"].strip() or
                type(image_inference["temperature"]) not in {int, float} or not math.isfinite(image_inference["temperature"]) or
                not 0 <= image_inference["temperature"] <= 2 or
                type(image_inference["max_tokens"]) is not int or image_inference["max_tokens"] <= 0):
                raise ValueError("Invalid frozen image inference contract")
            if system_prompt is not None and system_prompt != image_inference["system_prompt"]:
                raise ValueError("system_prompt differs from the frozen image inference contract")
            configured = runner_config or RunnerConfig()
            if any(getattr(configured, key) not in (None, image_inference[key]) for key in ("temperature", "max_tokens")):
                raise ValueError("Runner settings differ from the frozen image inference contract")
            canonical_prompt = image_inference["system_prompt"]
            runner_config = replace(configured, temperature=image_inference["temperature"], max_tokens=image_inference["max_tokens"])
        dataset = dataset_from_package(pkg, system_prompt=canonical_prompt)
        bound = scorer or scorer_from_manifest(pkg.manifest)
        if bound is None:
            kind = pkg.manifest.scorer.get("kind")
            raise ValueError(
                f"scorer kind {kind!r} needs an explicit runtime binding; "
                f"pass scorer= to Benchmark.from_package()"
            )
        sut_factory: Callable[..., SystemUnderTest] | None = None
        max_turns = 8
        if pkg.manifest.modality == "agentic-fhir":
            agentic_binding = agentic_fhir_binding_from_package(pkg)
            max_turns = agentic_binding.max_turns

            def sut_factory(
                model: Any,
                *,
                temperature: float | None,
                max_tokens: int | None,
            ) -> SystemUnderTest:
                return agentic_binding.build_sut(
                    model,
                    system_prompt=canonical_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
        elif pkg.manifest.modality == "multimodal":
            multimodal_binding = multimodal_image_binding_from_package(pkg)

            def sut_factory(
                model: Any,
                *,
                temperature: float | None,
                max_tokens: int | None,
            ) -> SystemUnderTest:
                del temperature, max_tokens
                return multimodal_binding.build_sut(model)

        requested_routes = _normalize_allowed_model_routes(allowed_model_routes)
        if (
            package_routes is not None
            and requested_routes is not None
            and not set(requested_routes).issubset(package_routes)
        ):
            raise ValueError(
                "allowed_model_routes may narrow package provenance but cannot "
                "add an unreviewed model route"
            )
        if pkg.env and pkg.env.get("schema_version") == "arisekit.fhir-docker-env.v1":
            limits = pkg.env["limits"]
            selected_config = runner_config or RunnerConfig()
            settings = {}
            for key in ("max_calls", "max_cost", "max_cost_per_call"):
                value = getattr(selected_config, key)
                if value is not None and value > limits[key]:
                    raise ValueError(f"{key} exceeds the frozen FHIR brief")
                settings[key] = value if value is not None else limits[key]
            runner_config = replace(selected_config, **settings, require_known_cost=True)
        benchmark = cls(
            name=pkg.manifest.id,
            dataset=dataset,
            scorer=bound,
            runner_config=runner_config,
            max_turns=max_turns,
            allowed_model_routes=(
                requested_routes
                if requested_routes is not None
                else package_routes
            ),
            provider_disclosure_requirement=disclosure_requirement,
            sut_factory=sut_factory,
            package_asset_manifest_sha256=(
                sha256_digest((pkg.root / ASSET_MANIFEST_FILENAME).read_bytes())
                if pkg.asset_manifest is not None
                else None
            ),
        )
        benchmark._package_modality = pkg.manifest.modality
        if pkg.env and pkg.env.get("schema_version") == "arisekit.fhir-docker-env.v1":
            benchmark._fhir_limits = dict(pkg.env["limits"])
        if disclosure_requirement is not None:
            item_payload = [item.to_dict() for item in dataset]
            benchmark._gated_package_binding = _GatedPackageBinding(
                benchmark_content_hash=sha256_digest(item_payload),
                system_prompt=canonical_prompt,
                system_prompt_hash=sha256_digest(canonical_prompt or ""),
                scorer_fingerprint=_scorer_fingerprint(bound),
                scorer_object=bound,
                scorer_spec_json=_canonical_json_text(pkg.manifest.scorer),
            )
        return benchmark


def _slug(model: str) -> str:
    return model.replace("/", "__").replace(":", "_")


def _normalize_allowed_model_routes(
    routes: Sequence[str] | None,
) -> tuple[str, ...] | None:
    if routes is None:
        return None
    if isinstance(routes, (str, bytes)):
        raise TypeError("allowed_model_routes must be a sequence of model ids")
    normalized = tuple(routes)
    if not normalized:
        raise ValueError("allowed_model_routes must contain at least one model id")
    if any(not isinstance(route, str) or not route.strip() for route in normalized):
        raise ValueError("allowed_model_routes entries must be non-empty strings")
    if len(set(normalized)) != len(normalized):
        raise ValueError("allowed_model_routes must not contain duplicates")
    return normalized


def _manifest_allowed_model_routes(
    provenance: dict[str, Any],
) -> tuple[str, ...] | None:
    readiness = provenance.get("readiness")
    if not isinstance(readiness, dict) or "allowed_model_routes" not in readiness:
        return None
    routes = readiness["allowed_model_routes"]
    if not isinstance(routes, list):
        raise ValueError(
            "package provenance readiness.allowed_model_routes must be a list"
        )
    return _normalize_allowed_model_routes(routes)


def _manifest_provider_disclosure_requirement(
    package: Any,
    *,
    package_routes: tuple[str, ...] | None,
) -> ProviderDisclosureRequirement | None:
    """Restore the non-public scaffold gate without affecting legacy packages."""

    provenance = package.manifest.provenance
    build_schema = _manifest_build_spec_schema(provenance)
    is_generated_build = build_schema is not None
    governance = provenance.get("data_governance")
    if "data_governance" not in provenance:
        if is_generated_build:
            raise ValueError(
                f"{build_schema} package is missing data_governance provenance"
            )
        return None
    if not isinstance(governance, dict):
        raise ValueError(
            "package provenance.data_governance must be an object"
        )
    release_posture = governance.get("release_posture")
    if release_posture not in ("public", "restricted", "private", "held-out"):
        raise ValueError(
            "scaffolded package release_posture must be public, restricted, "
            "private, or held-out"
        )
    if is_generated_build:
        classification = governance.get("classification")
        if classification not in (
            "public",
            "synthetic",
            "deidentified",
            "limited",
            "identifiable",
        ):
            raise ValueError(
                f"{build_schema} data_governance.classification is invalid"
            )
        if classification in ("limited", "identifiable"):
            raise ValueError(
                f"{build_schema} cannot materialize {classification!r} data"
            )
        if release_posture == "public" and classification not in (
            "public",
            "synthetic",
        ):
            raise ValueError(
                "public release posture requires public or synthetic data"
            )
    if release_posture == "public":
        return None
    if not is_generated_build:
        raise ValueError(
            "non-public data_governance requires the exact "
            "supported benchmark-build-spec marker"
        )
    scorer_kind = package.manifest.scorer.get("kind")
    if scorer_kind not in ("exact-match", "contains", "choice", "numeric"):
        raise ValueError(
            "non-public build-spec v1 packages require a deterministic scorer; "
            "judge-provider disclosure is not defined for "
            f"scorer kind {scorer_kind!r}"
        )

    raw_sweep = provenance.get("first_sweep")
    if not isinstance(raw_sweep, list) or not raw_sweep:
        raise ValueError(
            "non-public scaffolded package first_sweep must provide a complete "
            "route-to-provider mapping"
        )
    route_providers: list[tuple[str, str]] = []
    seen_routes: set[str] = set()
    for index, entry in enumerate(raw_sweep):
        if not isinstance(entry, dict):
            raise ValueError(f"first_sweep[{index}] must be an object")
        route = entry.get("model")
        provider = entry.get("provider")
        if not isinstance(route, str) or not route.strip():
            raise ValueError(f"first_sweep[{index}].model must be non-empty")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError(f"first_sweep[{index}].provider must be non-empty")
        if route in seen_routes:
            raise ValueError(
                f"first_sweep contains duplicate model route {route!r}"
            )
        seen_routes.add(route)
        route_providers.append((route, provider))

    if package_routes is None:
        raise ValueError(
            "non-public scaffolded package must declare reviewed model routes"
        )
    mapped_routes = {route for route, _ in route_providers}
    reviewed_routes = set(package_routes)
    if mapped_routes != reviewed_routes:
        missing = sorted(reviewed_routes - mapped_routes)
        unexpected = sorted(mapped_routes - reviewed_routes)
        raise ValueError(
            "non-public scaffolded package route-to-provider mapping is "
            f"incomplete; missing={missing}, unexpected={unexpected}"
        )

    return ProviderDisclosureRequirement(
        generated_bundle_hash=generated_bundle_hash(package.root),
        access_classification=release_posture,
        route_providers=tuple(route_providers),
        judge_providers=(),
    )


def _manifest_build_spec_schema(provenance: Mapping[str, Any]) -> str | None:
    build_spec = provenance.get("build_spec")
    if not isinstance(build_spec, dict):
        return None
    schema = build_spec.get("schema_version")
    if schema in (
        "arisekit.benchmark-build-spec.v1",
        "arisekit.benchmark-build-spec.v2",
        "arisekit.benchmark-build-spec.v3",
    ):
        return str(schema)
    return None


def _validate_agentic_v2_governance(provenance: Mapping[str, Any]) -> None:
    governance = provenance.get("data_governance")
    if not isinstance(governance, Mapping):
        raise ValueError(
            "agentic build-spec v2 package is missing data_governance provenance"
        )
    classification = governance.get("classification")
    release_posture = governance.get("release_posture")
    if classification not in ("public", "synthetic") or release_posture != "public":
        raise ValueError(
            "agentic build-spec v2 runtime supports only public-release public "
            "or synthetic data"
        )


def _validate_multimodal_v3_governance(provenance: Mapping[str, Any]) -> None:
    governance = provenance.get("data_governance")
    if not isinstance(governance, Mapping):
        raise ValueError(
            "multimodal build-spec v3 package is missing data_governance provenance"
        )
    classification = governance.get("classification")
    release_posture = governance.get("release_posture")
    if classification not in ("public", "synthetic") or release_posture != "public":
        raise ValueError(
            "multimodal build-spec v3 runtime supports only public-release public "
            "or synthetic data"
        )


def _manifest_system_prompt(provenance: Mapping[str, Any]) -> str | None:
    source = provenance.get("source")
    if not isinstance(source, dict) or "system_prompt" not in source:
        raise ValueError(
            "generated build package is missing source.system_prompt provenance"
        )
    prompt_record = source["system_prompt"]
    if prompt_record is None:
        return None
    if not isinstance(prompt_record, dict) or set(prompt_record) != {
        "text",
        "sha256",
    }:
        raise ValueError(
            "generated build source.system_prompt must contain text and sha256"
        )
    text = prompt_record.get("text")
    expected_hash = prompt_record.get("sha256")
    if not isinstance(text, str) or not isinstance(expected_hash, str):
        raise ValueError(
            "generated build source.system_prompt text and sha256 are invalid"
        )
    if sha256_digest(text) != expected_hash:
        raise ValueError(
            "generated build source.system_prompt hash does not match its text"
        )
    return text


def _scorer_fingerprint(scorer: BaseScorer) -> str:
    return sha256_digest(
        {
            "type": f"{type(scorer).__module__}.{type(scorer).__qualname__}",
            "state": vars(scorer),
        }
    )


def _execution_model_route(
    model: str | ModelClient | SystemUnderTest,
    sut: SystemUnderTest,
) -> str:
    """Resolve the dispatch route without trusting a wrapper's display name.

    ``ModelSUT`` and ``AgentSUT`` allow callers to assign a friendly ``name``.
    That label is useful in reports, but it must not let an underlying client
    route bypass a reviewed execution allowlist.
    """

    if isinstance(model, str):
        return model
    for owner in (
        getattr(sut, "client", None),
        getattr(sut, "agent_client", None),
        model,
        sut,
    ):
        if owner is None:
            continue
        for attribute in ("model_route", "model"):
            route = getattr(owner, attribute, None)
            if isinstance(route, str) and route.strip():
                return route
    return sut.name
