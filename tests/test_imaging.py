import base64
from copy import deepcopy
import io
import json
import hashlib
from pathlib import Path
import random

from PIL import Image
import pytest

from arisekit.benchmark import Benchmark
from arisekit.client import ModelResponse, _build_messages
from arisekit.images.image_generation import advance_images, freeze_images, image_status
from arisekit.images.imaging import (ImageAnswerScorer, SOURCE_SCHEMA, digest, ingest_collection,
    inspect_image, source_item, split_collection, verify_collection, class_membership_target, connect_medmnist)
from arisekit.package import load_package
from arisekit.runner import RunnerConfig
from arisekit.types import RunResult


def collection(count=4, *, profiles=("classification", "closed-vqa")):
    rows, assets = [], {}
    for index in range(count):
        rng = random.Random(index)
        image = Image.frombytes("RGB", (20, 20), bytes(rng.randrange(256) for _ in range(1200)))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        name = f"image-{index}.png"
        assets[name] = buffer.getvalue()
        rows.append({"id": f"case-{index}", "group_id": f"patient-{index}", "group_basis": "patient",
            "field": "synthetic imaging", "modality": "synthetic", "images": [name], "tags": ["control"],
            "targets": [{"id": profile, "profile": profile, "choices": ["class one", "class two"],
                "answer": "class one", "question": "Which synthetic source class is assigned to this image?",
                "evidence": "Artificial fixture has assigned class one. This is not a clinical label.",
                "provenance": {"kind": "dataset-annotation", "source": "Synthetic engineering fixture"}} for profile in profiles]})
    return {"schema_version": SOURCE_SCHEMA, "source": {"name": "Synthetic fixture", "revision": "1", "license": "CC0"},
            "authorization": {"authorized": True, "provider_permission": True, "data_class": "synthetic", "scope": "Engineering tests"},
            "records": rows}, assets


def brief(**changes):
    return {"field": "synthetic imaging", "criteria": "Ask a concise question about the assigned source class.",
        "profiles": ["classification", "closed-vqa"], "case_count": 2, "seed": "reproducible", "evaluation_fraction": .5,
        "generator_model": "writer", "critic_model": "reviewer", "models": ["vision"], "max_calls": 24,
        "max_cost": 1, "max_cost_per_call": .1, **changes}


class ImageClient:
    def __init__(self, model, calls, *, invalid=False):
        self.model, self.calls, self.invalid = model, calls, invalid

    def __call__(self, call):
        messages = _build_messages(call)
        blocks = messages[-1]["content"]
        images = [block["image_url"]["url"] for block in blocks if block["type"] == "image_url"] if isinstance(blocks, list) else []
        if call.item.metadata.get("image_condition") in {"question-only", "taxonomy-only"}:
            assert not images
        else:
            assert images
        assert all(inspect_image(base64.b64decode(url.split(",", 1)[1])) for url in images)
        self.calls.append((self.model, call, images))
        step = call.item.metadata.get("image_step", "solve:")
        if step.startswith("generate:"):
            target = json.loads(call.item.prompt)["source_target"]
            text = json.dumps({"question": "Select the assigned source class for the attached synthetic image.",
                "target_id": target["id"], "grounding": target.get("evidence", "Finite synthetic class vocabulary"), "uncertainty": "Artificial source label only."})
            if self.invalid:
                text = text.replace(target["id"], "invented-target")
        elif step.startswith("review:"):
            text = json.dumps({"grounded": True, "criteria_aligned": True, "issues": [], "uncertainty": "Engineering fixture only"})
        else:
            if "image_step" in call.item.metadata:
                assert call.item.ground_truth is None
            assert "source_target" not in str(call.item.prompt)
            text = "class one"
        return ModelResponse(text=text, cost=.001, cost_known=True, tokens_in=15, tokens_out=10)


def test_ingest_private_integrity_and_failures(tmp_path):
    manifest, assets = collection()
    source = ingest_collection(tmp_path / "source", manifest, assets)
    assert verify_collection(tmp_path / "source") == source
    assert (tmp_path / "source").stat().st_mode & 0o077 == 0
    image = tmp_path / "source" / next(iter(source["assets"]))
    assert image.stat().st_mode & 0o077 == 0
    image.write_bytes(b"broken")
    with pytest.raises(ValueError, match="corrupt"):
        verify_collection(tmp_path / "source")
    for bad, message in [(b"not a png", "corrupt"), (assets["image-0.png"][:40], "corrupt")]:
        with pytest.raises(ValueError, match=message):
            inspect_image(bad)
    missing = dict(assets)
    missing.pop("image-0.png")
    with pytest.raises(ValueError, match="Missing image"):
        ingest_collection(tmp_path / "missing", manifest, missing)
    manifest["records"][0]["images"] = ["../image.png"]
    with pytest.raises(ValueError, match="flat"):
        ingest_collection(tmp_path / "unsafe", manifest, assets)


def test_patient_and_pixel_duplicates_cannot_cross_split(tmp_path):
    manifest, assets = collection(6)
    manifest["records"][1]["group_id"] = manifest["records"][0]["group_id"]
    assets["image-2.png"] = assets["image-1.png"]
    source = ingest_collection(tmp_path / "source", manifest, assets)
    split = split_collection(source, seed="abc", evaluation_fraction=.5)
    assert split == split_collection(source, seed="abc", evaluation_fraction=.5)
    assert {"case-0", "case-1", "case-2"} <= set(split["source"]) or {"case-0", "case-1", "case-2"} <= set(split["evaluation"])
    reverse = deepcopy(source)
    reverse["records"].reverse()
    assert split == split_collection(reverse, seed="abc", evaluation_fraction=.5)
    assert set(split["source"]).isdisjoint(split["evaluation"])


@pytest.mark.parametrize("mutation,match", [
    (lambda m: m["authorization"].update(authorized=False), "authorization"),
    (lambda m: m["records"][0].pop("group_id"), "group_id"),
    (lambda m: m["records"][0]["targets"][0].update(profile="report-generation"), "separate adapter"),
    (lambda m: m["records"][0]["targets"][0].update(answer="invented finding"), "source answer"),
    (lambda m: m["records"][0]["targets"][0].update(choices=["Yes", "YES."]), "unambiguous"),
])
def test_no_invented_references_or_silent_profile_substitution(tmp_path, mutation, match):
    manifest, assets = collection()
    mutation(manifest)
    with pytest.raises(ValueError, match=match):
        ingest_collection(tmp_path / "source", manifest, assets)


def test_frozen_workflow_images_comparison_resume_and_portable_package(tmp_path):
    manifest, assets = collection()
    ingest_collection(tmp_path / "source", manifest, assets)
    status = freeze_images(tmp_path, brief())
    calls = []
    clients = dict(generator=ImageClient("writer", calls), critic=ImageClient("reviewer", calls), solvers={"vision": ImageClient("vision", calls)})
    while status["next_step"]:
        status = advance_images(tmp_path, **clients)
        assert status["status"] != "stopped", status
    assert status["status"] == "complete"
    assert len(calls) == 16
    assert status["cost_total"] == pytest.approx(.016)
    assert all(row["generated"]["accuracy_all_assigned"] == 1 for row in status["comparison"]["models"])
    assert {row["profile"] for row in status["comparison"]["models"][0]["generated"]["scores"]} == {"classification", "closed-vqa"}
    advance_images(tmp_path, **clients)
    assert len(calls) == 16
    package = load_package(tmp_path / "generated", verify_assets=True)
    assert all(item.attachments for item in package.items)
    benchmark = Benchmark.from_package(tmp_path / "generated", runner_config=RunnerConfig(results_dir=tmp_path / "portable-results", max_retries=1))
    result = benchmark.run(ImageClient("vision", calls))
    assert result.summary.completed == 4, result.raw
    generated_calls = {call.item.id: call for model, call, _ in calls[:16]
                       if model == "vision" and call.item.metadata["image_step"].startswith("solve:0:generated:")}
    for _, call, _ in calls[16:]:
        evaluated = generated_calls[call.item.id]
        assert _build_messages(call) == _build_messages(evaluated)
        assert call.temperature == evaluated.temperature == 0
        assert call.max_tokens == evaluated.max_tokens == 128
    benchmark.run(ImageClient("vision", calls))
    assert len(calls) == 20
    assert image_status(tmp_path)["calls_total"] == 16
    with pytest.raises(ValueError, match="frozen image inference"):
        Benchmark.from_package(tmp_path / "generated", system_prompt="Different task")
    for config in (RunnerConfig(temperature=1), RunnerConfig(max_tokens=256)):
        with pytest.raises(ValueError, match="frozen image inference"):
            Benchmark.from_package(tmp_path / "generated", runner_config=config)
    # Solvers receive no reference metadata, and the generation criteria are frozen into writer calls.
    for model, call, _ in calls[:16]:
        if model == "writer":
            assert json.loads(call.item.prompt)["criteria"] == brief()["criteria"]
        if model == "vision":
            assert "reference_provenance" not in call.item.metadata


def test_invalid_generation_retained_without_second_paid_call(tmp_path):
    manifest, assets = collection()
    ingest_collection(tmp_path / "source", manifest, assets)
    freeze_images(tmp_path, brief())
    calls = []
    clients = dict(generator=ImageClient("writer", calls, invalid=True), critic=ImageClient("reviewer", calls), solvers={})
    status = advance_images(tmp_path, **clients)
    assert status["status"] == "stopped"
    assert "unchanged source target" in status["error"]
    assert list((tmp_path / "responses").glob("*.json"))
    advance_images(tmp_path, **clients)
    assert len(calls) == 1


def test_scorer_negative_controls_and_presentation_perturbations(tmp_path):
    manifest, assets = collection()
    source = ingest_collection(tmp_path / "source", manifest, assets)
    row = source["records"][0]
    item = source_item(row, row["targets"][0])
    scorer = ImageAnswerScorer()
    for answer in ["class one", "  CLASS ONE.\n"]:
        assert scorer.score_response(item, RunResult(item.id, 1, answer))["correct"] == 1
    for answer in ["class two", "not class one", "class one or class two", "class one because it looks normal"]:
        assert scorer.score_response(item, RunResult(item.id, 1, answer))["correct"] == 0
    item.metadata["choices"].reverse()
    assert scorer.score_response(item, RunResult(item.id, 1, "class one"))["correct"] == 1
    item.ground_truth = "class two"
    assert scorer.score_response(item, RunResult(item.id, 1, "class one"))["correct"] == 0
    assert scorer.score_response(item, RunResult(item.id, 1, ""))["missing"]
    assert scorer.score_response(item, RunResult(item.id, 1, None, error="transport"))["error"] == "transport"


def test_plan_and_assets_cannot_change_after_freeze(tmp_path):
    manifest, assets = collection()
    ingest_collection(tmp_path / "source", manifest, assets)
    freeze_images(tmp_path, brief())
    plan = json.loads((tmp_path / "image-plan.json").read_text())
    plan["brief"]["criteria"] = "Changed criteria"
    (tmp_path / "image-plan.json").write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="frozen image plan differs"):
        image_status(tmp_path)


def test_model_json_fences_normalize_without_losing_raw_response(tmp_path):
    manifest, assets = collection()
    ingest_collection(tmp_path / "source", manifest, assets)
    freeze_images(tmp_path, brief())
    calls = []
    class FencedWriter(ImageClient):
        def __call__(self, call):
            assert call.extra["response_format"]["json_schema"]["strict"] is True
            response = super().__call__(call)
            response.text = "```json\n" + response.text + "\n```"
            return response
    status = advance_images(tmp_path, generator=FencedWriter("writer", calls), critic=None, solvers={})
    assert status["completed_steps"] == 1
    response = json.loads(next((tmp_path / "responses").glob("*.json")).read_text())
    assert response["response"].startswith("```json\n")


def test_jpeg_decode_and_unsupported_format_errors(tmp_path):
    jpeg = io.BytesIO()
    Image.new("RGB", (8, 8), "gray").save(jpeg, format="JPEG")
    assert inspect_image(jpeg.getvalue())["media_type"] == "image/jpeg"
    unsupported = io.BytesIO()
    Image.new("RGB", (8, 8), "gray").save(unsupported, format="GIF")
    with pytest.raises(ValueError, match="single-frame PNG and JPEG"):
        inspect_image(unsupported.getvalue())
    manifest, assets = collection()
    assets["image-0.png"] = jpeg.getvalue()
    with pytest.raises(ValueError, match="extension differs"):
        ingest_collection(tmp_path / "source", manifest, assets)


def test_image_profile_cannot_enter_the_fhir_generator():
    from arisekit.generation.benchmark_emulation import emulation_generation_request, emulation_profile
    assert emulation_profile("medical images")["runtime"] == "image-generation"
    with pytest.raises(ValueError, match="freeze_images"):
        emulation_generation_request(request_id="images", family="medical images", specialty="test",
            need_statement="Create image tasks", evidence={"source": "Authorized image evidence"}, case_count=2)


@pytest.mark.parametrize("dataset", ["breastmnist", "dermamnist"])
def test_repository_sampling_resolution_and_derived_provenance(tmp_path, monkeypatch, dataset):
    import numpy as np
    import arisekit.images.imaging as imaging
    spec = deepcopy(imaging.MEDMNIST_SOURCES[dataset])
    channels = (3,) if spec["channels"] == 3 else ()
    image_array = np.random.default_rng(17).integers(0, 255, size=(6, 64, 64) + channels, dtype=np.uint8)
    buffer = io.BytesIO()
    np.savez_compressed(buffer, test_images=image_array, test_labels=np.array([[0], [0], [0], [1], [1], [1]], dtype=np.uint8))
    raw = buffer.getvalue()
    spec.update(test_count=6, releases={64: (hashlib.md5(raw).hexdigest(), len(raw))})
    monkeypatch.setitem(imaging.MEDMNIST_SOURCES, dataset, spec)
    seen = []
    def download(url, **kwargs):
        seen.append(url)
        return io.BytesIO(raw)
    monkeypatch.setattr(imaging.urllib.request, "urlopen", download)
    options = dict(dataset=dataset, size=64, count=4, seed="criteria-source", positive_classes=[spec["classes"][0]], authorized=True)
    source = connect_medmnist(tmp_path / "source", **options)
    assert seen[0].endswith(dataset + "_64.npz?download=1")
    assert source["source"]["license"] == spec["license"]
    assert source["source"]["selection"]["class_counts"][spec["classes"][0]] == 2
    assert source["source"]["selection"]["class_counts"][spec["classes"][1]] == 2
    assert {asset["width"] for asset in source["assets"].values()} == {64}
    assert all(row["group_basis"] == "conservative-cohort" for row in source["records"])
    encoding = {str(code): label for code, label in enumerate(spec["classes"])}
    assert all(row["targets"][0]["provenance"]["label_encoding"] == encoding for row in source["records"])
    answers = [row["targets"][1]["answer"] for row in source["records"]]
    assert answers.count("yes") == 2 and answers.count("no") == 2
    assert all(row["targets"][1]["provenance"]["parent_kind"] == "dataset-annotation" for row in source["records"])
    assert connect_medmnist(tmp_path / "repeat", **options) == source
    excluded = connect_medmnist(tmp_path / "holdout", **options, exclude_indices=[0, 3])
    assert not {0, 3} & set(excluded["source"]["selection"]["indices"])
    assert excluded["source"]["selection"]["excluded_indices"] == [0, 3]
    from arisekit.images.image_generation import main
    archive = tmp_path / "official.npz"
    archive.write_bytes(raw)
    main(["connect-medmnist", str(tmp_path / "cli"), "--dataset", dataset, "--size", "64", "--count", "4",
          "--archive", str(archive), "--exclude-index", "0", "--exclude-index", "3", "--authorize-source-and-provider"])
    assert verify_collection(tmp_path / "cli" / "source")["source"]["selection"]["excluded_indices"] == [0, 3]
    for invalid in [[0, 0], [-1], [6], [True], "0"]:
        with pytest.raises(ValueError, match="Excluded test indices"):
            connect_medmnist(tmp_path / "invalid-exclusion", **options, exclude_indices=invalid)
    with pytest.raises(ValueError, match="source classification choices"):
        connect_medmnist(tmp_path / "invented", **{**options, "positive_classes": ["invented diagnosis"]})
    with pytest.raises(ValueError, match="checksum"):
        monkeypatch.setattr(imaging.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(raw[:-1]))
        connect_medmnist(tmp_path / "changed", **options)


def test_derived_references_verify_parent_answers_and_origins(tmp_path):
    manifest, assets = collection(profiles=("classification",))
    for row in manifest["records"]:
        parent = row["targets"][0]
        parent["provenance"]["kind"] = "ai"
        row["targets"].append(class_membership_target(parent, ["class one"]))
    source = ingest_collection(tmp_path / "good", manifest, assets)
    assert source["records"][0]["targets"][1]["provenance"]["parent_kind"] == "ai"
    altered = deepcopy(manifest)
    altered["records"][0]["targets"][1]["answer"] = "no"
    with pytest.raises(ValueError, match="Derived annotation differs"):
        ingest_collection(tmp_path / "changed", altered, assets)
    altered = deepcopy(manifest)
    altered["records"][0]["targets"][0]["answer"] = "class two"
    with pytest.raises(ValueError, match="Derived annotation differs"):
        ingest_collection(tmp_path / "changed-parent", altered, assets)


def test_ambiguous_targets_require_explicit_selection_and_all_requested_targets_are_used(tmp_path):
    manifest, assets = collection()
    for row in manifest["records"]:
        extra = deepcopy(row["targets"][1]); extra["id"] = "specific-vqa"
        row["targets"].append(extra)
    for directory in ("ambiguous", "selected", "multiple-selected", "missing"):
        ingest_collection(tmp_path / directory / "source", manifest, assets)
    with pytest.raises(ValueError, match="choose explicit target_ids"):
        freeze_images(tmp_path / "ambiguous", brief())
    status = freeze_images(tmp_path / "selected", brief(target_ids={"closed-vqa": ["specific-vqa"]}))
    plan = json.loads((tmp_path / "selected" / "image-plan.json").read_text())
    assert {item["metadata"]["target_id"] for item in plan["originals"]} == {"classification", "specific-vqa"}
    assert status["selection"]["tasks"] == 4
    expanded = freeze_images(tmp_path / "multiple-selected", brief(target_ids={"closed-vqa": ["closed-vqa", "specific-vqa"]}))
    assert expanded["selection"]["tasks"] == 6
    assert expanded["total_steps"] == 24
    with pytest.raises(ValueError, match="absent from the selected"):
        freeze_images(tmp_path / "missing", brief(target_ids={"closed-vqa": ["specific-vqa", "absent-target"]}))


def test_cross_profile_contradictions_are_reported_without_hiding_accuracy(tmp_path):
    manifest, assets = collection(2, profiles=("classification",))
    for row in manifest["records"]:
        row["targets"].append(class_membership_target(row["targets"][0], ["class one"]))
    ingest_collection(tmp_path / "source", manifest, assets)
    status = freeze_images(tmp_path, brief(evaluation_fraction=1))
    calls = []
    class ContradictorySolver(ImageClient):
        def __call__(self, call):
            response = super().__call__(call)
            if call.item.metadata.get("image_step", "").startswith("solve:") and call.item.id.endswith("--class-membership"):
                response.text = "no"
            return response
    clients = dict(generator=ImageClient("writer", calls), critic=ImageClient("reviewer", calls), solvers={"vision": ContradictorySolver("vision", calls)})
    while status["next_step"]:
        status = advance_images(tmp_path, **clients)
        assert status["status"] != "stopped", status
    for arm in ("original", "generated"):
        result = status["comparison"]["models"][0][arm]
        assert result["profiles"]["classification"]["correct"] == 2
        assert result["profiles"]["closed-vqa"]["correct"] == 0
        assert result["class_membership_consistency"]["observed_pairs"] == 2
        assert result["class_membership_consistency"]["contradictions"] == 2
    assert status["comparison"]["originality"]["exact_duplicate_task_groups"] == []


def control_collection():
    manifest, assets = collection(2, profiles=("classification",))
    manifest["records"][1]["targets"][0]["answer"] = "class two"
    for row in manifest["records"]:
        row["targets"].append(class_membership_target(row["targets"][0], ["class one"]))
    return manifest, assets


def test_image_controls_bind_distinct_pixels_and_report_prediction_changes(tmp_path):
    manifest, assets = control_collection()
    source = ingest_collection(tmp_path / "source", manifest, assets)
    options = brief(evaluation_fraction=1, image_controls=["question-only", "contrasting-image"], max_calls=32)
    status = freeze_images(tmp_path, options)
    plan = json.loads((tmp_path / "image-plan.json").read_text())
    assert plan["brief"]["image_controls"] == ["contrasting-image", "question-only"]
    assert status["total_steps"] == 32
    assert all(row == {"expected": 4, "assigned": 4, "unavailable": 0} for row in status["image_controls"].values())
    image_answers = {source["assets"][row["images"][0]]["sha256"]: row["targets"][0]["answer"] for row in source["records"]}
    calls = []

    class PixelFixtureSolver(ImageClient):
        def __call__(self, call):
            response = super().__call__(call)
            assert "reference_provenance" not in call.item.metadata
            assert "donor_reference" not in call.item.metadata
            label = image_answers[digest(Path(call.item.attachments[0]).read_bytes())] if call.item.attachments else "class one"
            response.text = ("yes" if label == "class one" else "no") if call.item.id.endswith("--class-membership") else label
            return response

    clients = dict(generator=ImageClient("writer", calls), critic=ImageClient("reviewer", calls),
                   solvers={"vision": PixelFixtureSolver("vision", calls)})
    while status["next_step"]:
        status = advance_images(tmp_path, **clients)
        assert status["status"] != "stopped", status
    assert len(calls) == 32
    for model, call, images in calls:
        step = call.item.metadata["image_step"]
        if step.startswith("control:"):
            condition = call.item.metadata["image_condition"]
            binding = plan["image_controls"][condition][call.item.id]
            assert [digest(base64.b64decode(url.split(",", 1)[1])) for url in images] == binding["image_sha256"]
            if condition == "contrasting-image":
                original = next(item for item in plan["originals"] if item["id"] == call.item.id)
                assert not set(original["attachments"]) & set(binding["image_refs"])
                assert binding["donor_reference"] != original["ground_truth"]
    for arm in ("original", "generated"):
        result = status["comparison"]["models"][0][arm]
        assert result["accuracy_all_assigned"] == 1
        omitted, contrasted = (result["image_controls"][key] for key in ("question-only", "contrasting-image"))
        assert omitted["original_reference_matches"] == 2
        assert omitted["prediction_changed"] == 2 and omitted["paired_valid"] == 4
        assert contrasted["original_reference_matches"] == 0
        assert contrasted["donor_reference_matches"] == 4
        assert contrasted["prediction_changed"] == 4 and contrasted["paired_valid"] == 4
        assert all(profile["original_reference_matches"] == 0 for profile in contrasted["profiles"].values())
    advance_images(tmp_path, **clients)
    assert len(calls) == 32
    assert all(item.attachments for item in load_package(tmp_path / "generated", verify_assets=True).items)


@pytest.mark.parametrize("different_task", [False, True])
def test_unavailable_contrasts_are_explicit_and_never_dispatched(tmp_path, different_task):
    manifest, assets = collection(2, profiles=("classification",))
    if different_task:
        manifest["records"][1]["targets"][0].update(answer="class two", question="Which unrelated source attribute is present?")
    ingest_collection(tmp_path / "source", manifest, assets)
    status = freeze_images(tmp_path, brief(profiles=["classification"], evaluation_fraction=1,
        image_controls=["contrasting-image"]))
    assert status["total_steps"] == 8
    assert status["image_controls"]["contrasting-image"] == {"expected": 2, "assigned": 0, "unavailable": 2}
    calls = []
    while status["next_step"]:
        status = advance_images(tmp_path, generator=ImageClient("writer", calls), critic=ImageClient("reviewer", calls),
                                solvers={"vision": ImageClient("vision", calls)})
        assert status["status"] != "stopped", status
    assert len(calls) == 8
    for arm in ("original", "generated"):
        control = status["comparison"]["models"][0][arm]["image_controls"]["contrasting-image"]
        assert control["unavailable"] == 2
        assert control["assigned"] == control["missing"] == control["paired_valid"] == 0
        assert all(row["unavailable_reason"] for row in control["rows"])


def test_control_invalid_and_empty_outputs_keep_the_assigned_denominator(tmp_path):
    manifest, assets = collection(2, profiles=("classification",))
    ingest_collection(tmp_path / "source", manifest, assets)
    status = freeze_images(tmp_path, brief(profiles=["classification"], evaluation_fraction=1, image_controls=["question-only"]))
    calls = []

    class BadControlSolver(ImageClient):
        def __call__(self, call):
            response = super().__call__(call)
            if call.item.metadata.get("image_condition") == "question-only":
                response.text = "not a permitted label" if call.item.id.startswith("case-0--") else ""
            return response

    while status["next_step"]:
        status = advance_images(tmp_path, generator=ImageClient("writer", calls), critic=ImageClient("reviewer", calls),
                                solvers={"vision": BadControlSolver("vision", calls)})
        assert status["status"] != "stopped", status
    for arm in ("original", "generated"):
        control = status["comparison"]["models"][0][arm]["image_controls"]["question-only"]
        assert control["assigned"] == 2
        assert control["invalid"] == control["missing"] == 1
        assert control["valid"] == control["paired_valid"] == control["prediction_changed"] == 0


def test_control_assignments_are_stable_and_call_limits_apply_before_dispatch(tmp_path):
    manifest, assets = control_collection()
    for name in ("first", "reordered", "limited"):
        ingest_collection(tmp_path / name / "source", manifest, assets)
    first = brief(evaluation_fraction=1, image_controls=["question-only", "contrasting-image"], max_calls=32)
    freeze_images(tmp_path / "first", first)
    freeze_images(tmp_path / "reordered", {**first, "image_controls": list(reversed(first["image_controls"]))})
    a, b = (json.loads((tmp_path / name / "image-plan.json").read_text()) for name in ("first", "reordered"))
    assert a["image_controls"] == b["image_controls"]
    assert a["steps"] == b["steps"]
    with pytest.raises(ValueError, match="needs 32 calls"):
        freeze_images(tmp_path / "limited", {**first, "max_calls": 31})


def test_different_png_encodings_of_identical_pixels_cannot_form_a_contrast(tmp_path):
    manifest, assets = control_collection()
    buffer = io.BytesIO()
    Image.open(io.BytesIO(assets["image-0.png"])).save(buffer, format="PNG", compress_level=0)
    assets["image-1.png"] = buffer.getvalue()
    assert assets["image-0.png"] != assets["image-1.png"]
    ingest_collection(tmp_path / "source", manifest, assets)
    status = freeze_images(tmp_path, brief(evaluation_fraction=1, image_controls=["contrasting-image"]))
    assert status["image_controls"]["contrasting-image"] == {"expected": 4, "assigned": 0, "unavailable": 4}


@pytest.mark.parametrize("value", [["invented-control"], ["question-only", "question-only"], "question-only", [{}]])
def test_invalid_control_designs_fail_before_source_dispatch(tmp_path, value):
    with pytest.raises(ValueError, match="distinct question-only"):
        freeze_images(tmp_path, brief(image_controls=value))
