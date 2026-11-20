"""Prompted response sets: collection, scope, operation identity, and judging, with a fake OpenRouter transport."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from arisekit.common.hashing import json_sha256, sha256
from arisekit.common.jsonio import read_json, read_jsonl
from cases import each_case
from conftest import SYNTHETIC
from test_web_pipeline import FakeOpenRouter

from pipeline import backends
from pipeline.e2e import text_v2_runtime
from pipeline.e2e.project import Project, sanitize_model
from tools import run_inference
from tools import web_pipeline as web
from tools import web_pipeline_teams as teams

GOLDEN = Path(__file__).parent / "fixtures" / "response-prompts" / "golden-unprompted.json"
VOLATILE = {"created_at", "updated_at", "started_at", "runtime_s", "runtime"}
MODELS = ["test/response-a", "test/response-b"]
TEXT_A = "Think about patient safety first."
TEXT_B = "Answer step by step."
V1_CONFIG = {
    "version": 1,
    "generationModel": "test/generator",
    "ratingModels": [],
    "responseModels": MODELS,
    "judgeModel": "test/judge",
}


def team_config(**responses: Any) -> dict[str, Any]:
    return {
        "version": 2,
        "teams": {
            "generation": {"models": ["test/generator"], "integrator": ""},
            "rating": {"models": [], "integrator": ""},
            "responses": {
                "models": list(MODELS),
                "integrator": "",
                "modelReasoning": {"test/response-a": "low"},
                **responses,
            },
            "judge": {"models": ["test/judge"], "integrator": ""},
        },
    }


def entry(name: str, text: str) -> dict[str, str]:
    from pipeline.e2e.response_prompts import prompt_id

    return {"id": prompt_id(name), "name": name, "text": text, "sha256": sha256(text), "savedAt": "2026-11-06T00:00:00Z"}


def save_prompts(project: Project, *entries: dict[str, str]) -> None:
    (project.root / "prompts.json").write_text(json.dumps({"version": 1, "prompts": list(entries)}))


def new_project(root: Path, trials: int = 1) -> Project:
    project = Project.create(root, trials)
    project.update_provenance(judge_scoring_source_commit=text_v2_runtime.CURRENT_COMMIT)
    project.import_case("Syn002", SYNTHETIC)
    return project


def request(project: Project, stage: str, config: dict[str, Any], **action: Any) -> dict[str, Any]:
    return {"project": str(project.root), "action": {"stage": stage, **action}, "config": deepcopy(config)}


def success(value: dict[str, Any]) -> dict[str, Any]:
    result = web.execute(value)
    assert result["status"] == "completed", result
    return result


def failure(value: dict[str, Any]) -> str:
    result = web.execute(value)
    assert result["status"] == "failed", result
    return "; ".join(result["errors"])


def masked(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "<volatile>" if key in VOLATILE else masked(item) for key, item in value.items()}
    if isinstance(value, list):
        return [masked(item) for item in value]
    return value


def recorded(project: Project) -> dict[str, Any]:
    return {
        "receipts": {path.stem: masked(read_jsonl(path)) for path in project.response_files()},
        "provenance": masked(project.provenance()),
        "operations": {
            path.name: masked(read_json(path))
            for path in sorted((project.root / "web-execution").glob("responses-*.json"))
        },
    }


def run_cli(monkeypatch: pytest.MonkeyPatch, project: Project, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["run_inference.py", str(project.root), *args])
    run_inference.main()


def golden_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Unprompted values from every collection path; the fixture holds them as produced before prompts existed."""
    config = team_config()
    values: dict[str, Any] = {"validate_config": teams.validate_config(deepcopy(config))}
    v2 = new_project(tmp_path / "v2" / "project", trials=2)
    team = values["validate_config"]["teams"]["responses"]
    spec = teams._response_spec(v2, team, v2.items())
    values["v2"] = {
        "spec": spec,
        "identity": json_sha256(spec),
        "result": success(request(v2, "responses", config)),
        **recorded(v2),
    }
    v1 = new_project(tmp_path / "v1" / "project")
    values["v1"] = {"result": success(request(v1, "responses", V1_CONFIG)), **recorded(v1)}
    template = tmp_path / "template.txt"
    template.write_text("A legacy prompt file.\n")
    for name, extra in (("cli", []), ("cli_prompt_file", ["--prompt-file", str(template)])):
        cli = new_project(tmp_path / name / "project")
        run_cli(monkeypatch, cli, "--model", "test/response-b", "--model", "test/response-a",
                "--backend", "openrouter", "--reasoning-effort", "low", *extra)
        values[name] = recorded(cli)
    return values


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeOpenRouter:
    fake = FakeOpenRouter()
    monkeypatch.setattr(backends, "TRANSPORTS", {"openrouter": fake})
    return fake


@pytest.fixture
def project(tmp_path: Path, fake: FakeOpenRouter) -> Project:
    project = new_project(tmp_path / "project")
    save_prompts(project, entry("Safety first", TEXT_A), entry("Step by step", TEXT_B))
    return project


def test_unprompted_collection_matches_values_from_before_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeOpenRouter
) -> None:
    expected = read_json(GOLDEN)
    actual = json.loads(json.dumps(golden_values(tmp_path, monkeypatch)))
    assert actual == expected
    assert json.dumps(actual) == json.dumps(expected)  # key order too


def test_validate_config_keeps_teams_without_prompts_and_checks_prompt_ids() -> None:
    config = team_config()
    assert "prompts" not in teams.validate_config(deepcopy(config))["teams"]["responses"]
    listed = teams.validate_config(team_config(prompts=["safety-first", "step-by-step"]))
    assert listed["teams"]["responses"]["prompts"] == ["safety-first", "step-by-step"]
    for bad in (["Safety First"], ["safety-first", "safety-first"], "safety-first", [3]):
        with pytest.raises(ValueError, match="prompts"):
            teams.validate_config(team_config(prompts=bad))


def test_response_sets_list_unprompted_then_each_prompt_in_config_order() -> None:
    team = team_config(prompts=["step-by-step", "safety-first"])["teams"]["responses"]
    assert teams.response_sets(team) == [
        ("test/response-a", "test/response-a", None),
        ("test/response-b", "test/response-b", None),
        ("test/response-a+step-by-step", "test/response-a", "step-by-step"),
        ("test/response-b+step-by-step", "test/response-b", "step-by-step"),
        ("test/response-a+safety-first", "test/response-a", "safety-first"),
        ("test/response-b+safety-first", "test/response-b", "safety-first"),
    ]


def test_cli_and_web_build_the_same_prompted_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: Project, fake: FakeOpenRouter
) -> None:
    config = team_config(prompts=["safety-first"])
    success(request(project, "responses", config, prompt="safety-first"))
    item = project.items()[0]
    assert {detail["prompt"] for detail in fake.details} == {f"{TEXT_A}\n\n{item['prompt']}"}
    assert all(detail["system"] == "" for detail in fake.details)
    assert fake.calls == MODELS
    assert [d.get("reasoning_effort") for d in fake.details] == ["low", None]
    name = "test/response-a+safety-first"
    web_row = read_jsonl(project.responses_path(sanitize_model(name)))[0]
    assert web_row["model"] == "test/response-a"
    assert web_row["responseSet"] == name
    assert web_row["prompt"] == {"id": "safety-first", "sha256": sha256(TEXT_A)}
    provenance = project.provenance()
    assert provenance["models"] == [name, "test/response-b+safety-first"]
    assert provenance["inference"]["set_prompts"][name] == {
        "id": "safety-first", "name": "Safety first", "sha256": sha256(TEXT_A)
    }
    assert provenance["inference"]["model_routes"][name] == {
        "backend": "openrouter", "model": "test/response-a", "kwargs": {"reasoning_effort": "low"}
    }

    cli = new_project(tmp_path / "cli")
    save_prompts(cli, entry("Safety first", TEXT_A))
    run_cli(monkeypatch, cli, "--model", "test/response-a", "--backend", "openrouter",
            "--reasoning-effort", "low", "--prompt", "Safety first")
    cli_row = read_jsonl(cli.responses_path(sanitize_model(name)))[0]
    assert cli_row["input_sha256"] == web_row["input_sha256"]
    assert {key: cli_row[key] for key in ("model", "responseSet", "prompt", "route")} == {
        key: web_row[key] for key in ("model", "responseSet", "prompt", "route")
    }
    assert fake.details[-1]["prompt"] == f"{TEXT_A}\n\n{item['prompt']}"
    assert cli.provenance()["inference"]["set_prompts"] == {name: provenance["inference"]["set_prompts"][name]}
    assert cli.provenance()["inference"]["template_sha256"] == sha256("")


CliRefusal = tuple[str, str, list[str] | None, list[str], str | None]


def test_cli_refusals_leave_collection_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = ["--model", "test/response-a", "--backend", "openrouter"]
    b = ["--model", "test/response-b", "--backend", "openrouter"]
    cases: list[CliRefusal] = [
        ("--prompt with --prompt-file", "Legacy.", None,
         [*a, "--prompt", "safety-first", "--prompt-file", "{template}"], None),
        ("unsaved prompt name", "Legacy.", None, [*a, "--prompt", "Unsaved prompt"], None),
        ("--prompt on a prompt-file project", "A legacy prompt file.", [*a, "--prompt-file", "{template}"],
         [*b, "--prompt", "safety-first"],
         "This project was collected with --prompt-file; add prompts in a new project."),
        ("--prompt-file on a saved-prompt project", "A legacy prompt file.", [*a, "--prompt", "safety-first"],
         [*a, "--prompt-file", "{template}"],
         "This project collects with saved prompts; use --prompt-file in a new project."),
        ("one model, baseline low then prompted high", "Legacy.", [*a, "--reasoning-effort", "low"],
         [*a, "--reasoning-effort", "high", "--prompt", "safety-first"], None),
        ("one model, prompted low then baseline high", "Legacy.",
         [*a, "--reasoning-effort", "low", "--prompt", "safety-first"], [*a, "--reasoning-effort", "high"], None),
    ]

    def run(case: CliRefusal) -> None:
        label, template_text, prior, refused, message = case
        root = tmp_path / label.replace(" ", "-").replace(",", "")
        with pytest.MonkeyPatch.context() as mp:
            fake = FakeOpenRouter()
            mp.setattr(backends, "TRANSPORTS", {"openrouter": fake})
            project = new_project(root / "project")
            save_prompts(project, entry("Safety first", TEXT_A), entry("Step by step", TEXT_B))
            template = root / "template.txt"
            template.write_text(template_text)

            def args(values: list[str]) -> list[str]:
                return [str(template) if value == "{template}" else value for value in values]

            if prior is not None:
                run_cli(mp, project, *args(prior))
            calls, files = list(fake.calls), project.response_files()
            saved = {path: path.read_bytes() for path in [*files, project.provenance_path] if path.exists()}
            capsys.readouterr()
            with pytest.raises(SystemExit):
                run_cli(mp, project, *args(refused))
            if message is not None:
                assert message in capsys.readouterr().err
            assert fake.calls == calls
            assert project.response_files() == files
            assert {path: path.read_bytes() for path in saved} == saved

    each_case(cases, lambda c: c[0], run)


def test_prompted_sets_can_be_added_after_collection_but_models_cannot_change(
    project: Project, fake: FakeOpenRouter
) -> None:
    success(request(project, "responses", team_config()))
    success(request(project, "responses", team_config(prompts=["safety-first"]), prompt="safety-first"))
    assert project.provenance()["models"] == [
        *MODELS, "test/response-a+safety-first", "test/response-b+safety-first"
    ]
    calls = list(fake.calls)
    removed = team_config(prompts=["safety-first"])
    removed["teams"]["responses"]["models"] = ["test/response-a"]
    removed["teams"]["responses"]["modelReasoning"] = {"test/response-a": "low"}
    assert "Response model scope changed after collection" in failure(request(project, "responses", removed))
    dropped = failure(request(project, "responses", team_config()))
    assert "Response model scope changed after collection" in dropped
    changed = team_config(prompts=["safety-first"])
    changed["teams"]["responses"]["modelReasoning"] = {"test/response-a": "high"}
    assert "changed inference route" in failure(request(project, "responses", changed, prompt="safety-first"))
    assert fake.calls == calls


def _collide(project: Project) -> dict[str, Any]:
    save_prompts(project, entry("b", "Prompt b."))
    config = team_config(prompts=["b"])
    config["teams"]["responses"] = {"models": ["test/a+b", "test/a"], "integrator": "", "prompts": ["b"]}
    return config


WebRefusal = tuple[str, Callable[[Project], dict[str, Any]], str, dict[str, Any], str]


def test_web_prompt_refusals_before_any_call(tmp_path: Path) -> None:
    cases: list[WebRefusal] = [
        ("colliding set ids with prompt", _collide, "responses", {"prompt": "b"}, "collide"),
        ("colliding set ids without prompt", _collide, "responses", {}, "collide"),
        ("prompt not listed in the team", lambda p: team_config(), "responses", {"prompt": "safety-first"}, "prompt"),
        ("listed prompt not saved", lambda p: team_config(prompts=["not-saved"]), "responses",
         {"prompt": "not-saved"}, "not-saved"),
        ("prompt on judge", lambda p: team_config(), "judge", {"rubric": "run1", "prompt": "safety-first"}, "prompt"),
    ]

    def run(case: WebRefusal) -> None:
        label, setup, stage, action, expected = case
        with pytest.MonkeyPatch.context() as mp:
            fake = FakeOpenRouter()
            mp.setattr(backends, "TRANSPORTS", {"openrouter": fake})
            project = new_project(tmp_path / label.replace(" ", "-") / "project")
            save_prompts(project, entry("Safety first", TEXT_A), entry("Step by step", TEXT_B))
            config = setup(project)
            assert expected in failure(request(project, stage, config, **action))
            assert fake.calls == []
            assert not project.response_files()
            assert "models" not in project.provenance()

    each_case(cases, lambda c: c[0], run)


def test_cli_unprompted_run_checks_each_declared_set_against_its_own_prompt(
    monkeypatch: pytest.MonkeyPatch, project: Project, fake: FakeOpenRouter
) -> None:
    success(request(project, "responses", team_config()))
    success(request(project, "responses", team_config(prompts=["safety-first"]), prompt="safety-first"))
    calls = list(fake.calls)
    run_cli(monkeypatch, project, "--model", "test/response-a", "--backend", "openrouter",
            "--reasoning-effort", "low")
    run_cli(monkeypatch, project, "--model", "test/response-b", "--backend", "openrouter",
            "--prompt", "safety-first")
    assert fake.calls == calls
    assert set(project.provenance()["inference"]["set_prompts"]) == {
        "test/response-a+safety-first", "test/response-b+safety-first"
    }


def test_operation_identity_is_per_arm_and_each_arm_resumes(
    project: Project, fake: FakeOpenRouter
) -> None:
    baseline_config = team_config()
    baseline_team = teams.validate_config(deepcopy(baseline_config))["teams"]["responses"]
    baseline_identity = json_sha256(teams._response_spec(project, baseline_team, project.items()))
    baseline = success(request(project, "responses", baseline_config))["operation"]
    assert baseline == baseline_identity

    a_config = team_config(prompts=["safety-first"])
    a = success(request(project, "responses", a_config, prompt="safety-first"))["operation"]
    ab_config = team_config(prompts=["safety-first", "step-by-step"])
    b = success(request(project, "responses", ab_config, prompt="step-by-step"))["operation"]
    assert len({baseline, a, b}) == 3

    saved = {prompt["id"]: prompt for prompt in json.loads((project.root / "prompts.json").read_text())["prompts"]}
    team = teams.validate_config(deepcopy(ab_config))["teams"]["responses"]
    items = project.items()
    assert json_sha256(teams._response_spec(project, team, items)) == baseline
    a_spec = teams._response_spec(project, team, items, saved["safety-first"])
    assert json_sha256(a_spec) == a
    assert a_spec["prompt"] == {"id": "safety-first", "sha256": sha256(TEXT_A)}
    assert "prompts" not in a_spec["team"]
    assert "prompt" not in teams._response_spec(project, team, items)
    for identity in (baseline, a, b):
        assert (project.root / "web-execution" / f"responses-{identity}.json").exists()

    calls = list(fake.calls)
    assert success(request(project, "responses", ab_config))["operation"] == baseline
    assert success(request(project, "responses", ab_config, prompt="safety-first"))["operation"] == a
    assert success(request(project, "responses", ab_config, prompt="step-by-step"))["operation"] == b
    assert fake.calls == calls
    assert len(list((project.root / "web-execution").glob("responses-*.json"))) == 3


def judged(project: Project) -> set[str]:
    return {path.stem for path in (project.root / "results" / "judge").glob("*.jsonl")}


def test_prompted_first_project_collects_baseline_then_judges_both(
    project: Project, fake: FakeOpenRouter
) -> None:
    config = team_config(prompts=["safety-first"])
    success(request(project, "generate", config))
    success(request(project, "responses", config, prompt="safety-first"))
    assert project.provenance()["models"] == ["test/response-a+safety-first", "test/response-b+safety-first"]
    success(request(project, "responses", config))
    assert project.provenance()["models"] == [
        *MODELS, "test/response-a+safety-first", "test/response-b+safety-first"
    ]
    result = success(request(project, "judge", config, rubric="run1"))
    assert result["judgments"] == 4
    assert judged(project) == {
        "test-response-a", "test-response-b", "test-response-a+safety-first", "test-response-b+safety-first"
    }
    success(request(project, "score", config))


def test_prompted_only_project_judges_its_collected_sets(project: Project, fake: FakeOpenRouter) -> None:
    config = team_config(prompts=["safety-first"])
    success(request(project, "generate", config))
    success(request(project, "responses", config, prompt="safety-first"))
    prompted = ["test/response-a+safety-first", "test/response-b+safety-first"]
    result = success(request(project, "judge", config, rubric="run1"))
    assert result["judgments"] == 2
    assert judged(project) == {sanitize_model(name) for name in prompted}
    success(request(project, "score", config))
    # A declared set with no responses refuses judging up front, before any call.
    project.update_provenance(models=[*MODELS, *prompted])
    calls = list(fake.calls)
    message = failure(request(project, "judge", config, rubric="run1"))
    assert message == "test/response-a: no responses collected yet; finish its collection before judging"
    assert fake.calls == calls


def test_a_prompted_run_reads_prompts_json_once(
    monkeypatch: pytest.MonkeyPatch, project: Project, fake: FakeOpenRouter
) -> None:
    reads = []
    original = teams.load_prompts
    monkeypatch.setattr(teams, "load_prompts", lambda target: reads.append(target) or original(target))
    success(request(project, "responses", team_config(prompts=["safety-first"]), prompt="safety-first"))
    assert len(reads) == 1
