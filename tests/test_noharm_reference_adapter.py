"""Offline contract tests for the canonical public NOHARM adapter."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

import arisekit.cli as cli
from arisekit.authoring.content_inventory import (
    ReferenceSelectionInventory,
    canonical_item_content_sha256,
)
from arisekit.evaluation.canonical_noharm_judge import (
    _judge_runtime_digest,
    build_open30_judge_manifest,
    execute_canonical_noharm_judge,
    execute_open30_judge_canary,
)
from arisekit.judge_handoff import (
    _verify_judge_execution_manifest,
    normalize_judge_panel,
)
from arisekit.evaluation.noharm_judge_contract import canonical_noharm_panel_entry
from arisekit.run_manifest import sha256_digest


REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS_ROOT = REPO_ROOT / "benchmarks"
if str(BENCHMARKS_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS_ROOT))

from noharm_reference import (  # noqa: E402
    AggregateMetric,
    NoHarmBundleError,
    NoHarmReferenceBundle,
    NoHarmSelection,
    compare_aggregate_metrics,
    load_aggregate_csv,
    replay_judged_aggregates,
)
from noharm_reference.runtime import (  # noqa: E402
    build_public_command,
    execute_public_command,
    inspection_lines,
)


PUBLIC_RELEASE = (
    REPO_ROOT.parent / "mast-private-1" / "release" / "benchmarks" / "noharm"
)


def _hash(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: object, *, indent: int | None = None) -> None:
    _write(path, json.dumps(payload, indent=indent, ensure_ascii=False) + "\n")


def _make_public_bundle(root: Path) -> Path:
    _write(root / "prompts" / "default.md", "Canonical response instructions")
    _write(
        root / "DATA.md",
        "\n".join(
            [
                "JUDGE_VERSION: v2",
                "gemini/gemini-3-flash-preview",
                "gemini/gemini-3.5-flash",
            ]
        ),
    )
    _write(root / "config" / "benchmark.yaml", "benchmark:\n  name: donoharm\n")
    _write(root / "requirements.txt", "litellm==1.80.0\n")
    _write(root / "data_loader.py", "PUBLIC = True\n")
    _write(root / "run.py", "PUBLIC = True\n")
    _write(root / "score.py", "PUBLIC = True\n")
    _write(
        root / "judge" / "config.py",
        "\n".join(
            [
                'MATCH = "gemini/gemini-3-flash-preview"',
                'REVIEW = "gemini/gemini-3.5-flash"',
            ]
        ),
    )
    _write(
        root / "judge" / "pyproject.toml",
        '[project]\nname = "noharm-judge"\nversion = "1.0.0"\n',
    )
    for filename in (
        "extract_match.md",
        "global_match_review.md",
        "severity.md",
        "triage.md",
    ):
        _write(root / "judge" / "prompts" / filename, f"Prompt {filename}")
    for filename in (
        "judged.schema.json",
        "match.schema.json",
        "review.schema.json",
        "severity.schema.json",
        "strategies.schema.json",
        "triage.schema.json",
    ):
        _write_json(root / "judge" / "schemas" / filename, {"type": "object"})

    item_rows: list[dict[str, object]] = []
    for base_number in range(1, 31):
        base_id = f"Case{base_number:03d}"
        for perturb_id in [None, *range(10)]:
            item_id = base_id if perturb_id is None else f"{base_id}-{perturb_id}"
            category = "baseline" if perturb_id is None else f"Category {perturb_id}"
            candidate_id = None if perturb_id is None else perturb_id + 1
            presentation = f"Presentation for {item_id}"
            metadata = {
                "base_id": base_id,
                "perturb_id": perturb_id,
                "category": category,
                "candidate_id": candidate_id,
                "open": True,
            }
            item_rows.append(
                {"id": item_id, "prompt": presentation, "metadata": metadata}
            )
            _write_json(
                root / "dataset" / "perturbations" / f"{item_id}.json",
                {
                    "id": item_id,
                    "base_id": base_id,
                    "perturb_id": perturb_id,
                    "n_perturbs": 10,
                    "candidate_id": candidate_id,
                    "category": category,
                    "description": None,
                    "presentation": presentation,
                },
            )

        _write_json(
            root / "dataset" / "rubrics" / f"{base_id}.json",
            {
                "id": base_id,
                "open": True,
                "case": {
                    "presentation": f"Presentation for {base_id}",
                    "recommendations": "Specialist recommendation",
                },
                "options": [
                    {
                        "id": 1,
                        "text": "Required clinical action",
                        "category": "Follow-up",
                        "score": 9,
                        "bestInGroup": False,
                        "isHarmOfInaction": True,
                    }
                ],
                "abstractionGroups": [],
                "specialistConsult": None,
            },
        )
        _write(root / "guidance" / f"{base_id}.yaml", "version: 1\n")

    _write(
        root / "dataset" / "items.jsonl",
        "".join(json.dumps(row) + "\n" for row in item_rows),
    )
    return root


def test_construct_and_hash_use_minimal_reference_import_footprint(
    tmp_path: Path,
):
    root = _make_public_bundle(tmp_path / "noharm")
    script = """
import json
import sys
import typing
from pathlib import Path

repository_root = Path(sys.argv[1]).resolve()
bundle_root = Path(sys.argv[2]).resolve()

import benchmarks.noharm_reference as noharm_reference

before_attribute = sorted(
    name
    for name in sys.modules
    if name.startswith("benchmarks.noharm_reference.")
)
bundle_type = noharm_reference.NoHarmReferenceBundle
bundle = bundle_type(bundle_root)
bundle_sha256 = bundle.hashes.bundle_sha256

local_modules = []
for name, module in sys.modules.items():
    source = getattr(module, "__file__", None)
    if source is None:
        continue
    try:
        relative = Path(source).resolve().relative_to(repository_root)
    except ValueError:
        continue
    if relative.parts[0] not in {"arisekit", "benchmarks"}:
        continue
    local_modules.append((name, relative.as_posix()))

dataset_type = typing.get_type_hints(bundle_type.dataset)["return"]
benchmark_item_type = typing.get_type_hints(bundle_type._to_benchmark_item)["return"]
inventory_type = typing.get_type_hints(
    bundle_type.build_reference_selection_inventory
)["return"]
items_type = typing.get_type_hints(bundle_type.items.fget)["return"]
items_element_type = typing.get_args(items_type)[0]

resolved_exports = sorted(
    name
    for name in noharm_reference.__all__
    if getattr(noharm_reference, name, None) is not None
)

print(
    json.dumps(
        {
            "before_attribute": before_attribute,
            "bundle_sha256": bundle_sha256,
            "local_modules": sorted(local_modules),
            "public_exports": sorted(noharm_reference.__all__),
            "resolved_exports": resolved_exports,
            "type_hints": {
                "benchmark_item": [
                    benchmark_item_type.__module__,
                    benchmark_item_type.__name__,
                ],
                "dataset": [dataset_type.__module__, dataset_type.__name__],
                "inventory": [inventory_type.__module__, inventory_type.__name__],
                "items_element": [
                    items_element_type.__module__,
                    items_element_type.__name__,
                ],
            },
        },
        sort_keys=True,
    )
)
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(REPO_ROOT),
            str(root),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    observed = json.loads(completed.stdout)

    assert observed["before_attribute"] == []
    assert len(observed["bundle_sha256"]) == 64
    assert observed["resolved_exports"] == observed["public_exports"]
    assert observed["type_hints"] == {
        "benchmark_item": ["arisekit.types", "BenchmarkItem"],
        "dataset": ["arisekit.dataset", "Dataset"],
        "inventory": [
            "arisekit.authoring.content_inventory",
            "ReferenceSelectionInventory",
        ],
        "items_element": ["arisekit.types", "BenchmarkItem"],
    }
    assert observed["local_modules"] == [
        ["benchmarks", "benchmarks/__init__.py"],
        ["benchmarks.noharm_reference", "benchmarks/noharm_reference/__init__.py"],
        [
            "benchmarks.noharm_reference.adapter",
            "benchmarks/noharm_reference/adapter.py",
        ],
    ]


def test_loads_public_shape_and_exact_k_selection(tmp_path: Path):
    bundle = NoHarmReferenceBundle(_make_public_bundle(tmp_path / "noharm"))

    assert bundle.base_case_count == 30
    assert bundle.row_count == 330
    assert len(bundle.items) == 330
    assert len(bundle.base_cases) == 30
    assert len(bundle.select(1)) == 30
    assert len(bundle.select(5)) == 150
    assert len(bundle.select(11)) == 330
    assert [item.id for item in bundle.select(5)[:6]] == [
        "Case001",
        "Case001-0",
        "Case001-1",
        "Case001-2",
        "Case001-3",
        "Case002",
    ]


def test_selection_can_freeze_a_deterministic_base_subset(tmp_path: Path):
    bundle = NoHarmReferenceBundle(_make_public_bundle(tmp_path / "noharm"))

    limited = bundle.selection(k=5, base_limit=5)
    assert limited.base_ids == (
        "Case001",
        "Case002",
        "Case003",
        "Case004",
        "Case005",
    )
    assert len(limited.item_ids) == 25
    assert limited.to_dict() == {
        "k": 5,
        "policy": "baseline-plus-first-perturbations",
        "base_ids": [
            "Case001",
            "Case002",
            "Case003",
            "Case004",
            "Case005",
        ],
        "item_ids": list(limited.item_ids),
    }
    explicit = bundle.selection(
        k=2,
        base_ids=["Case010", "Case002"],
    )
    assert explicit.base_ids == ("Case002", "Case010")
    assert explicit.item_ids == (
        "Case002",
        "Case002-0",
        "Case010",
        "Case010-0",
    )
    assert [item.id for item in bundle.select(k=2, base_limit=1)] == [
        "Case001",
        "Case001-0",
    ]
    assert len(bundle.dataset(k=5, base_limit=5)) == 25


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"base_limit": 0}, "base_limit must be an integer"),
        ({"base_limit": 31}, "base_limit must be an integer"),
        ({"base_ids": []}, "at least one"),
        ({"base_ids": ["Case001", "Case001"]}, "duplicates"),
        ({"base_ids": ["Case999"]}, "unknown NOHARM base ids"),
        (
            {"base_ids": ["Case001"], "base_limit": 1},
            "mutually exclusive",
        ),
    ],
)
def test_selection_rejects_ambiguous_or_unknown_base_subsets(
    tmp_path: Path,
    kwargs: dict[str, object],
    message: str,
):
    bundle = NoHarmReferenceBundle(_make_public_bundle(tmp_path / "noharm"))

    with pytest.raises(ValueError, match=message):
        bundle.selection(k=5, **kwargs)  # type: ignore[arg-type]


def test_dataset_preserves_canonical_concatenated_user_prompt(tmp_path: Path):
    bundle = NoHarmReferenceBundle(_make_public_bundle(tmp_path / "noharm"))
    dataset = bundle.dataset(k=5)

    assert dataset.name == "donoharm"
    assert dataset.system_prompt is None
    assert dataset[0].prompt == (
        "Canonical response instructions\n\nPresentation for Case001"
    )


def test_reference_inventory_hashes_raw_presentations_and_round_trips(
    tmp_path: Path,
):
    bundle = NoHarmReferenceBundle(_make_public_bundle(tmp_path / "noharm"))
    selection = bundle.selection(
        k=5,
        base_ids=("Case010", "Case002"),
    )

    inventory = bundle.build_reference_selection_inventory(
        selection,
        source_manifest_sha256=_hash("upstream-source-manifest"),
        source_revision="public-release-test-revision",
        selection_protocol_sha256=_hash("selection-protocol"),
        selection_commit_sha256=_hash("pre-evaluation-selection-commit"),
    )

    assert inventory.bundle_sha256 == bundle.hashes.bundle_sha256
    assert [family.family_id for family in inventory.families] == [
        "Case002",
        "Case010",
    ]
    first_family = inventory.families[0]
    assert first_family.baseline_item_id == "Case002"
    assert first_family.item_ids == (
        "Case002",
        "Case002-0",
        "Case002-1",
        "Case002-2",
        "Case002-3",
    )
    baseline_hash = next(
        item.content_sha256 for item in first_family.items if item.item_id == "Case002"
    )
    assert baseline_hash == canonical_item_content_sha256("Presentation for Case002")
    assert baseline_hash != canonical_item_content_sha256(
        "Canonical response instructions\n\nPresentation for Case002"
    )
    assert ReferenceSelectionInventory.from_json(inventory.canonical_json) == inventory
    assert (
        ReferenceSelectionInventory.from_json(inventory.canonical_json).inventory_sha256
        == inventory.inventory_sha256
    )


@pytest.mark.parametrize(
    "selection",
    [
        NoHarmSelection(
            k=5,
            base_ids=("Case001", "Case001"),
            item_ids=(
                "Case001",
                "Case001-0",
                "Case001-1",
                "Case001-2",
                "Case001-3",
            ),
        ),
        replace(
            NoHarmSelection(
                k=5,
                base_ids=("Case001",),
                item_ids=(
                    "Case001",
                    "Case001-0",
                    "Case001-1",
                    "Case001-2",
                    "Case001-3",
                ),
            ),
            item_ids=(
                "Case001",
                "Case001-0",
                "Case001-1",
                "Case001-2",
                "Case001-2",
            ),
        ),
    ],
)
def test_reference_inventory_rejects_invalid_or_duplicate_selection(
    tmp_path: Path,
    selection: NoHarmSelection,
):
    bundle = NoHarmReferenceBundle(_make_public_bundle(tmp_path / "noharm"))

    with pytest.raises(ValueError, match="selection"):
        bundle.build_reference_selection_inventory(
            selection,
            source_manifest_sha256=_hash("upstream-source-manifest"),
            source_revision="public-release-test-revision",
            selection_protocol_sha256=_hash("selection-protocol"),
            selection_commit_sha256=_hash("pre-evaluation-selection-commit"),
        )


@pytest.mark.parametrize("invalid_k", [0, 12, -1, 1.5, True])
def test_k_must_match_released_range(tmp_path: Path, invalid_k: object):
    bundle = NoHarmReferenceBundle(_make_public_bundle(tmp_path / "noharm"))
    with pytest.raises(ValueError, match="k must be an integer"):
        bundle.select(invalid_k)  # type: ignore[arg-type]


def test_variant_resolves_defensive_copy_of_base_rubric(tmp_path: Path):
    bundle = NoHarmReferenceBundle(_make_public_bundle(tmp_path / "noharm"))

    rubric = bundle.rubric_for("Case001-7")
    assert rubric["id"] == "Case001"
    rubric["options"][0]["score"] = 1
    assert bundle.rubric_for("Case001")["options"][0]["score"] == 9
    with pytest.raises(KeyError, match="unknown NOHARM item"):
        bundle.rubric_for("Closed999")


def test_hashes_separate_logical_content_from_raw_assets(tmp_path: Path):
    root = _make_public_bundle(tmp_path / "noharm")
    first = NoHarmReferenceBundle(root).hashes
    rubric_path = root / "dataset" / "rubrics" / "Case001.json"
    payload = json.loads(rubric_path.read_text(encoding="utf-8"))
    _write_json(rubric_path, payload, indent=4)
    second = NoHarmReferenceBundle(root).hashes

    assert first.content_sha256 == second.content_sha256
    assert first.data_sha256 != second.data_sha256
    assert first.bundle_sha256 != second.bundle_sha256
    assert first.judge_sha256 == second.judge_sha256
    assert (
        first.assets["dataset/rubrics/Case001.json"]
        != second.assets["dataset/rubrics/Case001.json"]
    )
    assert len(first.content_sha256) == 64
    assert len(first.runtime_dependency_lock_sha256) == 64


def test_dependency_manifests_are_part_of_judge_and_bundle_identity(
    tmp_path: Path,
):
    root = _make_public_bundle(tmp_path / "noharm")
    first = NoHarmReferenceBundle(root).hashes

    assert "requirements.txt" in first.assets
    assert "judge/pyproject.toml" in first.assets

    _write(root / "requirements.txt", "litellm==1.81.0\n")
    second = NoHarmReferenceBundle(root).hashes

    assert second.content_sha256 == first.content_sha256
    assert second.data_sha256 == first.data_sha256
    assert second.runtime_dependency_lock_sha256 != (
        first.runtime_dependency_lock_sha256
    )
    assert second.judge_sha256 != first.judge_sha256
    assert second.bundle_sha256 != first.bundle_sha256


def test_rejects_any_closed_item(tmp_path: Path):
    root = _make_public_bundle(tmp_path / "noharm")
    items_path = root / "dataset" / "items.jsonl"
    rows = [json.loads(line) for line in items_path.read_text().splitlines()]
    rows[0]["metadata"]["open"] = False
    _write(items_path, "".join(json.dumps(row) + "\n" for row in rows))

    with pytest.raises(NoHarmBundleError, match="closed content is rejected"):
        NoHarmReferenceBundle(root)


def test_rejects_extra_unreferenced_rubric(tmp_path: Path):
    root = _make_public_bundle(tmp_path / "noharm")
    _write_json(root / "dataset" / "rubrics" / "Closed999.json", {"id": "Closed999"})

    with pytest.raises(
        NoHarmBundleError, match="rubric assets do not match public cases"
    ):
        NoHarmReferenceBundle(root)


def test_rejects_noncanonical_family_order(tmp_path: Path):
    root = _make_public_bundle(tmp_path / "noharm")
    items_path = root / "dataset" / "items.jsonl"
    rows = [json.loads(line) for line in items_path.read_text().splitlines()]
    rows[1], rows[2] = rows[2], rows[1]
    _write(items_path, "".join(json.dumps(row) + "\n" for row in rows))

    with pytest.raises(NoHarmBundleError, match="baseline followed by perturbations"):
        NoHarmReferenceBundle(root)


def test_replays_point_estimates_and_compares_cached_csv(tmp_path: Path):
    judged_path = tmp_path / "judged.jsonl"
    records = [
        {"id": "Case001", "judge": "judge-a", "metrics": {"F1_weighted": 0.2}},
        {"id": "Case001-0", "judge": "judge-a", "metrics": {"F1_weighted": 0.4}},
        {"id": "Case002", "judge": "judge-a", "metrics": {"F1_weighted": 0.8}},
        {"id": "Case002-0", "judge": "judge-a", "metrics": {"F1_weighted": 0.6}},
        {"id": "Case002-0", "judge": "judge-b", "metrics": {"F1_weighted": 0.0}},
    ]
    _write(judged_path, "".join(json.dumps(record) + "\n" for record in records))
    replayed = replay_judged_aggregates(judged_path, judge_names=["judge-a"])

    assert replayed == (
        AggregateMetric(
            category="Overall",
            metric="F1_weighted",
            trials=2,
            mean=0.5,
        ),
    )

    csv_path = tmp_path / "scores.csv"
    _write(
        csv_path,
        "category,metric,trials,mean,ci,ci_lo,ci_hi\n"
        "Overall,F1_weighted,2,0.5000,0.1,0.4,0.6\n",
    )
    cached = load_aggregate_csv(csv_path)
    comparison = compare_aggregate_metrics(replayed, cached)
    assert comparison.matches
    assert comparison.deltas[0].delta == 0.0
    assert comparison.deltas[0].observed_trials == 2


def test_comparison_reports_value_trial_and_missing_metric_failures():
    observed = [
        AggregateMetric("Overall", "F1_weighted", 30, 0.7),
        AggregateMetric("Overall", "Recall_weighted", 30, 0.6),
    ]
    reference = [
        AggregateMetric("Overall", "F1_weighted", 100, 0.71),
        AggregateMetric("Overall", "Precision_weighted", 30, 0.8),
    ]
    comparison = compare_aggregate_metrics(observed, reference, absolute_tolerance=0.02)

    assert not comparison.matches
    assert comparison.deltas[0].within_tolerance is False
    assert comparison.missing_observed == (("Overall", "Precision_weighted"),)
    assert comparison.missing_reference == (("Overall", "Recall_weighted"),)


def test_load_aggregate_csv_rejects_wrong_shape(tmp_path: Path):
    path = tmp_path / "scores.csv"
    _write(path, "metric,value\nF1_weighted,0.7\n")
    with pytest.raises(ValueError, match="not a canonical NOHARM aggregate CSV"):
        load_aggregate_csv(path)


@pytest.mark.skipif(
    not PUBLIC_RELEASE.is_dir(), reason="public NOHARM sibling checkout absent"
)
def test_current_canonical_public_release_contract():
    bundle = NoHarmReferenceBundle(PUBLIC_RELEASE)

    assert bundle.base_case_count == 30
    assert bundle.row_count == 330
    assert len(bundle.select(5)) == 150
    assert [item.id for item in bundle.select(5)[:5]] == [
        "All001",
        "All001-0",
        "All001-1",
        "All001-2",
        "All001-3",
    ]
    assert len(bundle.hashes.assets) > 400
    assert bundle.hashes.assets["dataset/items.jsonl"]


def _canonical_panel(bundle: NoHarmReferenceBundle) -> list[dict[str, object]]:
    assets = bundle.hashes.assets
    return [
        canonical_noharm_panel_entry(
            judge_assets_sha256=bundle.hashes.judge_sha256,
            runtime_dependency_lock_sha256=(
                bundle.hashes.runtime_dependency_lock_sha256
            ),
            match_prompt_sha256=assets["judge/prompts/extract_match.md"],
            review_prompt_sha256=assets["judge/prompts/global_match_review.md"],
        )
    ]


def _blinded_inputs(path: Path) -> Path:
    rows = []
    for index in (1, 2):
        response = f"Clinical response {index}"
        rows.append(
            {
                "schema_version": "arisekit.noharm-parity-judge-input.v1",
                "opaque_id": "jh_" + str(index) * 64,
                "binding_digest": str(index + 2) * 64,
                "response_sha256": sha256(
                    json.dumps(
                        response,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest(),
                "case": {
                    "prompt": f"Blinded case {index}",
                    "rubric": {
                        "id": "[case]",
                        "case": {"presentation": f"Presentation {index}"},
                        "options": [
                            {
                                "id": 1,
                                "text": "Obtain ECG",
                                "category": "Diagnostic",
                                "score": 9,
                                "isHarmOfInaction": True,
                            }
                        ],
                    },
                    "guidance": {"spirit": "Evaluate clinically equivalent actions."},
                },
                "response": response,
            }
        )
    _write(
        path,
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
    )
    return path


class _FakeJudgeConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _fake_judge_module() -> SimpleNamespace:
    def judge_responses(*, model_name, responses, rubrics, config, judged_path):
        assert model_name == "blinded-cohort"
        assert config.match_judge == "gemini/gemini-3-flash-preview"
        assert config.review_judge == "gemini/gemini-3.5-flash"
        assert config.severity_judge is None
        assert config.triage_judge is None
        assert all(row["id"].startswith("Opaque") for row in responses)
        assert set(rubrics) == {row["id"] for row in responses}
        assert all("arm" not in row and "model" not in row for row in responses)
        _write(
            judged_path,
            "".join(
                json.dumps(
                    {
                        "id": row["id"],
                        "trial": 1,
                        "metrics": {
                            "F1_weighted": 0.8,
                            "Severe_rate": 0.0,
                            "Triage": float("nan"),
                        },
                    }
                )
                + "\n"
                for row in responses
            ),
        )
        return {
            "stages": {
                "match": {"cost": 0.1},
                "review": {"cost": 0.1},
            },
            "provider_call_count": 2 * len(responses),
            "provider_job_ids": {
                "match": ["provider-match-job"],
                "review": ["provider-review-job"],
            },
        }

    return SimpleNamespace(
        __name__="offline_fake_noharm_judge",
        JudgeConfig=_FakeJudgeConfig,
        judge_responses=judge_responses,
    )


def test_single_judge_panel_requires_exact_hash_bound_canonical_contract(
    tmp_path: Path,
) -> None:
    bundle = NoHarmReferenceBundle(_make_public_bundle(tmp_path / "noharm"))
    panel = _canonical_panel(bundle)
    assert normalize_judge_panel(panel) == tuple(panel)

    generic = [dict(panel[0])]
    generic[0]["settings"] = {"temperature": 0}
    with pytest.raises(ValueError, match="canonical NOHARM judge settings"):
        normalize_judge_panel(generic)

    tampered = json.loads(json.dumps(panel))
    tampered[0]["settings"]["canonical_pipeline"]["execution_mode"] = "sync"
    with pytest.raises(ValueError, match="cohort-pooled"):
        normalize_judge_panel(tampered)


def test_canonical_batch_adapter_is_blinded_resumable_and_convert_compatible(
    tmp_path: Path,
) -> None:
    bundle_root = _make_public_bundle(tmp_path / "noharm")
    bundle = NoHarmReferenceBundle(bundle_root)
    judge_input = _blinded_inputs(tmp_path / "judge-input.jsonl")
    panel = _canonical_panel(bundle)
    spec = {
        "schema_version": "arisekit.noharm-parity-judge-execution-spec.v1",
        "judge_input_sha256": sha256(judge_input.read_bytes()).hexdigest(),
        "judge_panel": panel,
        "judge_runtime_hash": _judge_runtime_digest(bundle),
    }
    spec_path = tmp_path / "judge-spec.json"
    _write_json(spec_path, spec)
    output = tmp_path / "judged.jsonl"

    with pytest.raises(ValueError, match="--execute-live"):
        execute_canonical_noharm_judge(
            judge_input,
            judge_execution_spec_path=spec_path,
            reference_bundle_path=bundle_root,
            cache_root=tmp_path / "cache",
            output_path=output,
            max_cost_usd=10,
            max_calls=10,
            execute_live=False,
            judge_module=_fake_judge_module(),
        )

    summary = execute_canonical_noharm_judge(
        judge_input,
        judge_execution_spec_path=spec_path,
        reference_bundle_path=bundle_root,
        cache_root=tmp_path / "cache",
        output_path=output,
        max_cost_usd=10,
        max_calls=10,
        execute_live=True,
        judge_module=_fake_judge_module(),
    )
    assert summary.complete is True
    assert summary.expected == 2
    assert summary.calls_made == 4
    assert summary.cost_usd == pytest.approx(0.2)
    rows = [
        json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()
    ]
    assert {row["judge"] for row in rows} == {"noharm-v2-canonical"}
    assert all("Triage" not in row["metrics"] for row in rows)
    assert all(
        row["judge_provenance"]["provider_response_ids"]
        == [
            "match:provider-match-job",
            "review:provider-review-job",
        ]
        for row in rows
    )
    assert (tmp_path / "judged.jsonl.execution.json").is_file()
    _execution_path, execution_digest = _verify_judge_execution_manifest(
        output,
        judge_input_sha256=spec["judge_input_sha256"],
        judge_panel=panel,
        judge_runtime_hash=spec["judge_runtime_hash"],
    )
    assert execution_digest == summary.manifest_digest

    resumed = execute_canonical_noharm_judge(
        judge_input,
        judge_execution_spec_path=spec_path,
        reference_bundle_path=bundle_root,
        cache_root=tmp_path / "cache",
        output_path=output,
        max_cost_usd=10,
        max_calls=10,
        execute_live=True,
        judge_module=_fake_judge_module(),
    )
    assert resumed.skipped == 2
    assert resumed.calls_made == 0


def test_open30_canaries_and_combined_manifest_are_strictly_bound(
    tmp_path: Path,
) -> None:
    bundle_root = _make_public_bundle(tmp_path / "noharm")
    expected_models = {
        "match": "gemini-3-flash-preview",
        "review": "gemini-3.5-flash",
    }
    canary_paths = {}
    for stage in ("match", "review"):
        path = tmp_path / f"{stage}-canary.json"
        execute_open30_judge_canary(
            stage=stage,
            reference_bundle_path=bundle_root,
            output_path=path,
            execute_live=True,
            caller=lambda _model, supplied_stage: (
                expected_models[supplied_stage],
                f"response-{supplied_stage}",
            ),
        )
        canary_paths[stage] = path

    pilot = {
        "canonical_judge": {
            "family": "google-gemini",
            "implementation": "release/benchmarks/noharm/judge",
            "version": "v2",
            "stages": [
                {
                    "stage": stage,
                    "provider": "gemini",
                    "model": (
                        "gemini/gemini-3-flash-preview"
                        if stage == "match"
                        else "gemini/gemini-3.5-flash"
                    ),
                    "expected_provider_model": expected_models[stage],
                }
                for stage in ("match", "review")
            ],
        }
    }
    pilot_path = tmp_path / "pilot.json"
    campaign_path = tmp_path / "campaign-summary.json"
    bundle_manifest_path = tmp_path / "bundle-manifest.json"
    _write_json(pilot_path, pilot)
    _write_json(
        campaign_path,
        {"complete": True, "coverage": {"responses": 3600}},
    )
    _write_json(
        bundle_manifest_path,
        {"judge_contract": {"digest": sha256_digest("judge-contract")}},
    )
    output = tmp_path / "judge-manifest.json"
    manifest = build_open30_judge_manifest(
        pilot_path=pilot_path,
        reference_bundle_path=bundle_root,
        campaign_summary_path=campaign_path,
        candidate_bundle_manifest_path=bundle_manifest_path,
        match_canary_path=canary_paths["match"],
        review_canary_path=canary_paths["review"],
        response_count=3600,
        conversion_judge_ids=("noharm-v2-canonical",),
        output_path=output,
    )
    assert manifest["complete"] is True
    assert manifest["response_count"] == 3600
    assert manifest["judge_runtime_sha256"] == sha256_digest(
        [
            json.loads(canary_paths[stage].read_text(encoding="utf-8"))
            for stage in ("match", "review")
        ]
    )


def test_public_runtime_validates_and_executes_the_released_entrypoint(
    tmp_path: Path,
) -> None:
    bundle_root = _make_public_bundle(tmp_path / "noharm")
    output = tmp_path / "upstream-arguments.json"
    _write(
        bundle_root / "run.py",
        "\n".join(
            [
                "import json",
                "import sys",
                "from pathlib import Path",
                "Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))",
            ]
        ),
    )
    command = build_public_command(
        bundle_root,
        action="run",
        upstream_args=(str(output), "--model", "provider/model with space"),
    )

    assert command.cwd == bundle_root.resolve()
    assert command.argv[-2:] == ("--model", "provider/model with space")
    assert command.bundle.row_count == 330
    assert execute_public_command(command) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == [
        "--model",
        "provider/model with space",
    ]


def test_public_runtime_refuses_a_bundle_changed_after_validation(
    tmp_path: Path,
) -> None:
    bundle_root = _make_public_bundle(tmp_path / "noharm")
    command = build_public_command(bundle_root, action="score")
    _write(bundle_root / "README.md", "Changed after validation")

    with pytest.raises(ValueError, match="changed after command construction"):
        execute_public_command(command)


def test_public_benchmark_cli_inspects_and_dry_runs_without_upstream_execution(
    tmp_path: Path,
    capsys,
) -> None:
    bundle_root = _make_public_bundle(tmp_path / "noharm")

    assert cli.main(
        [
            "public-benchmark",
            "noharm",
            "--source",
            str(bundle_root),
            "inspect",
        ]
    ) == 0
    inspected = capsys.readouterr().out
    assert "public benchmark: noharm" in inspected
    assert "base cases: 30" in inspected
    assert "canonical k=5 rows: 150" in inspected
    assert "structural compatibility only" in inspected
    assert "run help:" in inspected

    assert cli.main(
        [
            "public-benchmark",
            "noharm",
            "--source",
            str(bundle_root),
            "--dry-run",
            "run",
            "--",
            "--model-config",
            "config/models/example.yaml",
        ]
    ) == 0
    planned = capsys.readouterr().out
    assert "bundle sha256:" in planned
    assert "--model-config config/models/example.yaml" in planned
    assert "upstream command was not executed" in planned


def test_public_runtime_inspection_is_stable_and_names_the_claim_boundary(
    tmp_path: Path,
) -> None:
    bundle = NoHarmReferenceBundle(_make_public_bundle(tmp_path / "noharm"))

    lines = inspection_lines(bundle)

    assert lines[0] == "public benchmark: noharm"
    assert "base cases: 30" in lines
    assert "rows: 330" in lines
    assert lines[-1].startswith("claim boundary: structural compatibility only")
