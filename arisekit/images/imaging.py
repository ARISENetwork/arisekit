"""Private image collections and finite-answer medical image task contracts."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
import urllib.request
import warnings
from typing import Any, Mapping

from arisekit.package import BenchmarkManifest, write_package
from arisekit.scorer import BaseScorer
from arisekit.types import BenchmarkItem, Metric, RunResult

SOURCE_SCHEMA = "arisekit.image-source.v1"
TASK_SCHEMA = "arisekit.image-task.v1"
IMAGE_SOLVER_SYSTEM = ("Answer the medical image question using only the supplied question, choices and images. "
    "Choose the single best answer from the listed labels, even when uncertain. "
    "Return only that label exactly as written, without explanation, JSON or additional text.")
PROFILES = {
    "classification": {"metric": "classification_accuracy", "output": "one class label"},
    "closed-vqa": {"metric": "closed_vqa_accuracy", "output": "one of the supplied answer choices"},
}
MAX_ASSET_BYTES = 5_000_000
MAX_COLLECTION_BYTES = 10_000_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
MEDMNIST_SOURCES = {
    "breastmnist": {"name": "BreastMNIST", "field": "breast imaging", "modality": "ultrasound", "license": "CC BY 4.0",
        "classes": ["malignant", "normal or benign"], "test_count": 156, "channels": 1,
        "releases": {28: ("750601b1f35ba3300ea97c75c52ff8f6", 559580),
            64: ("742edef2a1fd1524b2efff4bd7ba9364", 2846041),
            128: ("363e4b3f8d712e9b5de15470a2aaadf1", 10961822),
            224: ("b56378a6eefa9fed602bb16d192d4c8b", 30903564)}},
    "dermamnist": {"name": "DermaMNIST", "field": "dermatology", "modality": "dermoscopy", "license": "CC BY-NC 4.0",
        "classes": ["actinic keratoses and intraepithelial carcinoma", "basal cell carcinoma", "benign keratosis-like lesions",
                    "dermatofibroma", "melanoma", "melanocytic nevi", "vascular lesions"], "test_count": 2005, "channels": 3,
        "releases": {28: ("0744692d530f8e62ec473284d019b0c7", 19725078),
                     64: ("b70a2f5635c6199aeaa28c31d7202e1f", 100130190)}},
}


def image_source_catalog() -> list[dict]:
    return json.loads(canonical([{"id": key, **{name: spec[name] for name in ("name", "field", "modality", "license", "classes")},
             "sizes": sorted(spec["releases"])} for key, spec in MEDMNIST_SOURCES.items()]))


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value).encode()).hexdigest()


def write_private(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as stream:
        temporary = Path(stream.name)
        stream.write(canonical(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_json(path: Path) -> Any:
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    def constant(value):
        raise ValueError(f"Nonfinite JSON number: {value}")
    return json.loads(path.read_text(), object_pairs_hook=pairs, parse_constant=constant)


def _text(value: Any, name: str, maximum: int = 2000) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValueError(f"Supply {name} within {maximum} characters")
    return value.strip()


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split()).rstrip(".?!")


def inspect_image(payload: bytes) -> dict[str, Any]:
    """Decode every image; MIME signatures alone do not establish integrity."""
    from PIL import Image
    if not 0 < len(payload) <= MAX_ASSET_BYTES:
        raise ValueError("Image assets must contain 1–5,000,000 bytes")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as image:
                if image.format not in {"PNG", "JPEG"} or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Only single-frame PNG and JPEG images are supported; convert DICOM/volumes explicitly")
                if image.width * image.height > 20_000_000 or min(image.size) < 2:
                    raise ValueError("Image dimensions must be at least 2 pixels and at most 20 megapixels")
                image.verify()
            with Image.open(io.BytesIO(payload)) as image:
                image.load()
                rgb = image.convert("RGB")
                pixel_hash = digest(str(rgb.size).encode() + rgb.tobytes())
                small = rgb.convert("L").resize((9, 8))
                pixels = [small.getpixel((x, y)) for y in range(8) for x in range(9)]
                perceptual = sum((pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x)
                                 for y in range(8) for x in range(8))
                return {"sha256": digest(payload), "pixel_sha256": pixel_hash, "size_bytes": len(payload),
                        "width": image.width, "height": image.height, "dhash": f"{perceptual:016x}",
                        "media_type": "image/png" if image.format == "PNG" else "image/jpeg"}
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Image is corrupt, truncated, or too large to decode") from exc


def ingest_collection(root: str | Path, manifest: Mapping[str, Any], assets: Mapping[str, bytes]) -> dict[str, Any]:
    """Copy an authorized collection into an owner-private content-addressed store."""
    root = Path(root)
    if root.exists():
        raise ValueError("Choose a new image collection directory")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SOURCE_SCHEMA:
        raise ValueError(f"Expected {SOURCE_SCHEMA}")
    authorization = manifest.get("authorization", {})
    if (not isinstance(authorization, dict) or authorization.get("authorized") is not True
            or authorization.get("data_class") not in {"public", "synthetic", "institution-approved"}):
        raise ValueError("Record authorization and data_class before ingesting images")
    authorization = {**authorization, "scope": _text(authorization.get("scope"), "authorization scope"),
                     "provider_permission": authorization.get("provider_permission") is True}
    source = manifest.get("source", {})
    if not isinstance(source, dict):
        raise ValueError("Supply source provenance")
    source = {**source, **{key: _text(source.get(key), f"source {key}") for key in ("name", "revision", "license")}}
    rows = manifest.get("records")
    if not isinstance(rows, list) or not 2 <= len(rows) <= 200:
        raise ValueError("Supply 2–200 image records")
    if not isinstance(assets, Mapping) or sum(len(value) for value in assets.values()) > MAX_COLLECTION_BYTES:
        raise ValueError("The selected collection exceeds 10 MB")
    records, checked_assets, seen_ids, used = [], {}, set(), set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not _ID.fullmatch(row["id"]):
            raise ValueError("Each image record needs a safe, unique id")
        if row["id"] in seen_ids:
            raise ValueError("Duplicate image record id")
        seen_ids.add(row["id"])
        group_id = _text(row.get("group_id"), "patient/case group_id", 200)
        basis = row.get("group_basis")
        if basis not in {"patient", "case", "conservative-cohort"}:
            raise ValueError("group_basis must be patient, case, or conservative-cohort")
        paths = row.get("images")
        if not isinstance(paths, list) or not 1 <= len(paths) <= 4 or len(set(paths)) != len(paths):
            raise ValueError("Each record must reference 1–4 distinct image filenames")
        references = []
        for name in paths:
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,126}\.(png|jpe?g)", name):
                raise ValueError("Use flat PNG/JPEG image filenames; paths and URLs are not accepted")
            if name not in assets:
                raise ValueError(f"Missing image asset: {name}")
            payload = assets[name]
            detail = inspect_image(payload)
            suffix = ".png" if detail["media_type"] == "image/png" else ".jpg"
            if (Path(name).suffix == ".png") != (suffix == ".png"):
                raise ValueError(f"Image extension differs from decoded format: {name}")
            reference = "attachments/" + detail["sha256"] + suffix
            checked_assets[reference] = (detail, payload)
            references.append(reference)
            used.add(name)
        targets = row.get("targets")
        if not isinstance(targets, list) or not targets or len(targets) > 20:
            raise ValueError("Each record needs 1–20 source-grounded targets")
        checked_targets, target_ids = [], set()
        for target in targets:
            if not isinstance(target, dict) or not _ID.fullmatch(str(target.get("id", ""))) or target["id"] in target_ids:
                raise ValueError("Each source target needs a distinct safe id")
            target_ids.add(target["id"])
            if target.get("profile") not in PROFILES:
                raise ValueError("Select classification or closed-vqa; report/localization scoring needs a separate adapter")
            choices = target.get("choices")
            if (not isinstance(choices, list) or not 2 <= len(choices) <= 30 or
                any(not isinstance(choice, str) or not choice.strip() or len(choice) > 160 for choice in choices) or
                len({normalized(choice) for choice in choices}) != len(choices)):
                raise ValueError("Supply 2–30 unambiguous answer choices")
            if target.get("answer") not in choices:
                raise ValueError("The source answer must be one of its choices")
            if 'public_task' in target:
                public = target['public_task']
                if (target['profile'] != 'closed-vqa' or {normalized(value) for value in choices} != {'yes', 'no'} or
                    not isinstance(public, dict) or set(public) != {'semantic_frame', 'question_type'}):
                    raise ValueError('Public semantic frames require a closed yes/no task and frame/type fields only')
                target = {**target, 'public_task': {'semantic_frame': _text(public['semantic_frame'], 'public semantic frame'),
                    'question_type': _text(public['question_type'], 'public question type', 100)}}
            provenance = target.get("provenance", {})
            if not isinstance(provenance, dict) or provenance.get("kind") not in {"dataset-annotation", "expert", "ai", "derived-annotation"}:
                raise ValueError("Identify reference provenance as dataset-annotation, expert, ai, or derived-annotation")
            checked_targets.append({**target, "question": _text(target.get("question"), "original task/question"),
                "evidence": _text(target.get("evidence"), "source annotation evidence"),
                "provenance": {**provenance, "source": _text(provenance.get("source"), "reference source")}})
        for target in checked_targets:
            if target["provenance"]["kind"] == "derived-annotation":
                _verify_class_membership(target, checked_targets)
        tags = row.get("tags", [])
        if not isinstance(tags, list) or any(not isinstance(tag, str) or len(tag) > 100 for tag in tags):
            raise ValueError("Record tags must be strings within 100 characters")
        records.append({"id": row["id"], "group_id": group_id, "group_basis": basis,
                        "field": _text(row.get("field"), "field of interest", 100),
                        "modality": _text(row.get("modality"), "modality", 100),
                        "tags": tags, "images": references, "targets": checked_targets})
    if set(assets) != used:
        raise ValueError("Upload only images referenced by the manifest")
    frozen = {"schema_version": SOURCE_SCHEMA, "source": source, "authorization": authorization,
              "records": sorted(records, key=lambda row: row["id"]),
              "assets": {name: value[0] for name, value in sorted(checked_assets.items())}}
    root.mkdir(parents=True, mode=0o700)
    (root / "attachments").mkdir(mode=0o700)
    for name, (_, payload) in checked_assets.items():
        path = root / name
        with path.open("xb") as stream:
            os.chmod(path, 0o600)
            stream.write(payload)
    write_private(root / "source.json", frozen)
    return frozen


def ingest_local(manifest_path: str | Path, destination: str | Path) -> dict[str, Any]:
    path = Path(manifest_path).resolve()
    manifest = read_json(path)
    names = {name for row in manifest["records"] for name in row["images"]}
    assets = {}
    for name in names:
        asset = path.parent / name
        if asset.is_symlink() or asset.parent != path.parent or not asset.is_file():
            raise ValueError(f"Missing or unsafe local image: {name}")
        if asset.stat().st_size > MAX_ASSET_BYTES:
            raise ValueError("Local image exceeds 5 MB")
        assets[name] = asset.read_bytes()
    return ingest_collection(destination, manifest, assets)


def verify_collection(root: str | Path) -> dict[str, Any]:
    root = Path(root)
    if root.is_symlink() or (root / "source.json").is_symlink():
        raise ValueError("Image collections cannot be symlinks")
    source = read_json(root / "source.json")
    for name, expected in source["assets"].items():
        if not re.fullmatch(r"attachments/[a-f0-9]{64}\.(png|jpg)", name):
            raise ValueError("Unsafe frozen asset path")
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ASSET_BYTES:
            raise ValueError(f"Missing or unsafe frozen image: {name}")
        if inspect_image(path.read_bytes()) != expected:
            raise ValueError(f"Frozen image integrity differs: {name}")
    return source


def split_collection(source: dict, *, seed: str, evaluation_fraction: float) -> dict[str, Any]:
    """Keep patient/case groups and byte-identical decoded images together."""
    if type(evaluation_fraction) not in {float, int} or not 0 < evaluation_fraction <= 1:
        raise ValueError("evaluation_fraction must be greater than 0 and at most 1")
    rows = source["records"]
    parents = {row["id"]: row["id"] for row in rows}
    def find(key):
        while parents[key] != key:
            key = parents[key]
        return key
    seen = {}
    for row in rows:
        keys = ["group:" + row["group_id"]] + ["pixel:" + source["assets"][image]["pixel_sha256"] for image in row["images"]]
        for key in keys:
            if key in seen:
                parents[find(row["id"])] = find(seen[key])
            else:
                seen[key] = row["id"]
    groups = {}
    for row in rows:
        groups.setdefault(find(row["id"]), []).append(row["id"])
    ordered = sorted(groups.values(), key=lambda ids: digest({"seed": seed, "ids": sorted(ids)}))
    if evaluation_fraction < 1 and len(ordered) < 2:
        raise ValueError("A source/evaluation split needs at least two independent groups; use evaluation_fraction=1 for one unresolved cohort")
    count = len(ordered) if evaluation_fraction == 1 else max(1, min(len(ordered) - 1, round(len(ordered) * evaluation_fraction)))
    evaluation = sorted(item for group in ordered[:count] for item in group)
    exemplars = sorted(item for group in ordered[count:] for item in group)
    near = []
    for left in exemplars:
        for right in evaluation:
            a = next(row for row in rows if row["id"] == left)
            b = next(row for row in rows if row["id"] == right)
            distance = min((int(source["assets"][x]["dhash"], 16) ^ int(source["assets"][y]["dhash"], 16)).bit_count()
                           for x in a["images"] for y in b["images"])
            if distance <= 2:
                near.append({"source_id": left, "evaluation_id": right, "dhash_distance": distance})
    return {"seed": seed, "evaluation_fraction": evaluation_fraction, "evaluation": evaluation, "source": exemplars,
            "groups": sorted([sorted(ids) for ids in groups.values()]), "near_duplicate_diagnostics": near,
            "group_basis": sorted({row["group_basis"] for row in rows}),
            "patient_separation": "supplied-patient-groups" if all(row["group_basis"] == "patient" for row in rows)
            else "not independently verified; supplied case groups or conservative cohort used"}


def source_item(row: dict, target: dict, question: str | None = None) -> BenchmarkItem:
    return BenchmarkItem(id=row["id"] + "--" + target["id"],
        prompt=(question or target["question"]) + "\nAnswer with exactly one label from: " + canonical(target["choices"]),
        ground_truth=target["answer"], attachments=row["images"],
        metadata={"image_task_schema": TASK_SCHEMA, "profile": target["profile"], "choices": target["choices"],
            "source_id": row["id"], "target_id": target["id"], "group_id": row["group_id"],
            "field": row["field"], "modality": row["modality"], "reference_provenance": target["provenance"],
            "question_origin": target.get("question_origin", "source-supplied")})


def class_membership_target(parent: dict, positive_classes: list[str], *, target_id: str = "class-membership") -> dict:
    """Derive yes/no references from explicit source-class membership, without new clinical labels."""
    if (parent.get("profile") != "classification" or not isinstance(positive_classes, list)
        or not positive_classes or any(not isinstance(value, str) for value in positive_classes)
        or len(set(positive_classes)) != len(positive_classes)
        or not set(positive_classes) < set(parent["choices"])):
        raise ValueError("Class membership requires a nonempty proper subset of the source classification choices")
    if parent.get("answer") not in parent["choices"]:
        raise ValueError("Class membership requires an unchanged source class answer")
    reference = {key: parent[key] for key in ("answer", "choices", "provenance")}
    return {"id": target_id, "profile": "closed-vqa", "choices": ["yes", "no"],
        "question": "Does this image belong to any of these source classes: " + canonical(positive_classes) + "?",
        "question_origin": "deterministic-class-membership", "answer": "yes" if parent["answer"] in positive_classes else "no",
        "evidence": "Deterministic source-class membership from target " + parent["id"] + "; parent reference SHA-256: " + digest(reference),
        "provenance": {"kind": "derived-annotation", "source": parent["provenance"]["source"],
            "parent_kind": parent["provenance"]["kind"],
            "rule": "class-membership-v1", "from_target": parent["id"], "positive_classes": positive_classes,
            "parent_reference_sha256": digest(reference)}}


def _verify_class_membership(target: dict, targets: list[dict]) -> None:
    provenance = target["provenance"]
    parent = next((row for row in targets if row["id"] == provenance.get("from_target")), None)
    if parent is None or provenance.get("rule") != "class-membership-v1":
        raise ValueError("A derived annotation needs an existing classification target and class-membership-v1 rule")
    expected = class_membership_target(parent, provenance.get("positive_classes"), target_id=target["id"])
    if (target["profile"] != "closed-vqa" or target["choices"] != ["yes", "no"] or target["answer"] != expected["answer"]
        or provenance != expected["provenance"]):
        raise ValueError("Derived annotation differs from its source class membership or reference hash")


class ImageAnswerScorer(BaseScorer):
    """Strict finite-answer scoring, with explicit invalid and missing denominators."""
    rescore_safe = True

    def configuration(self):
        return {"kind": "image-answer", "schema_version": TASK_SCHEMA}

    def score_response(self, item: BenchmarkItem, result: RunResult) -> dict[str, Any]:
        if item.metadata.get("image_task_schema") != TASK_SCHEMA or item.metadata.get("profile") not in PROFILES:
            raise ValueError("An image answer scorer requires a bound finite-answer task")
        choices = item.metadata["choices"]
        expected = normalized(str(item.ground_truth))
        if expected not in {normalized(value) for value in choices}:
            raise ValueError("Reference differs from the bound answer vocabulary")
        if result.error or result.response is None or not str(result.response).strip():
            return {"correct": 0, "valid": False, "missing": True, "error": result.error}
        answer = normalized(str(result.response))
        valid = answer in {normalized(value) for value in choices}
        return {"correct": int(valid and answer == expected), "valid": valid, "missing": False, "error": None}

    def score_item(self, item, responses):
        scored = [self.score_response(item, response) for response in responses]
        if not scored:
            return []
        metric = PROFILES[item.metadata["profile"]]["metric"]
        return [Metric(metric, sum(row["correct"] for row in scored) / len(scored), n=len(scored)),
                Metric("invalid_output", sum(not row["valid"] for row in scored) / len(scored), n=len(scored))]


def export_image_package(path: Path, collection: Path, items: list[BenchmarkItem], *, brief: dict, arm: str) -> Path:
    source = verify_collection(collection)
    refs = sorted({name for item in items for name in item.attachments})
    attachment_manifest = {"schema_version": "arisekit.image-attachments.v1",
        "assets": [{"path": name, **{key: source["assets"][name][key] for key in ("sha256", "size_bytes", "media_type")}} for name in refs],
        "case_bindings": {item.id: item.attachments for item in items}}
    write_package(path, manifest=BenchmarkManifest(id="medical-images-" + arm, name="Medical images: " + brief["field"],
        modality="multimodal", scorer={"kind": "image-answer"}, provenance={"image_task_schema": TASK_SCHEMA,
            "image_inference": {"schema_version": "arisekit.image-inference.v1", "system_prompt": IMAGE_SOLVER_SYSTEM,
                "temperature": 0, "max_tokens": 128},
            "source_sha256": digest(source), "source": source["source"], "authorization": source["authorization"],
            "brief": brief, "arm": arm, "image_origin": "existing source images", "expert_review": False}), items=items,
        attachment_assets={name: (collection / name).read_bytes() for name in refs}, attachments=attachment_manifest,
        readme="# Medical image benchmark\n\nRun with `arisekit run-package . --model <vision-model>`.\n"
        "Questions use existing images and retained source references. AI review is separate from expert judgment.\n"
        "This package contains authorized image bytes and must follow its source authorization.\n", write_asset_manifest=True)
    os.chmod(path, 0o700)
    for member in path.rglob("*"):
        os.chmod(member, 0o700 if member.is_dir() else 0o600)
    return path


def connect_medmnist(destination: str | Path, *, dataset: str = "breastmnist", size: int = 128,
                     count: int = 6, authorized: bool = False, seed: str = "medical-images-v2",
                     sampling: str = "balanced-labels", include_classes: list[str] | None = None,
                     positive_classes: list[str] | None = None, archive_path: str | Path | None = None,
                     exclude_indices: list[int] | None = None) -> dict[str, Any]:
    """Import supported official releases with explicit sampling and optional derived task design."""
    import numpy as np
    from PIL import Image
    if authorized is not True or type(count) is not int or not 2 <= count <= 24:
        raise ValueError("Authorize the selected source license and model providers, and choose 2–24 images")
    if not isinstance(dataset, str) or dataset not in MEDMNIST_SOURCES:
        raise ValueError("Select a supported medical image repository")
    spec = MEDMNIST_SOURCES[dataset]
    excluded = [] if exclude_indices is None else exclude_indices
    if (not isinstance(excluded, list) or any(type(value) is not int or not 0 <= value < spec["test_count"] for value in excluded)
        or len(set(excluded)) != len(excluded)):
        raise ValueError("Excluded test indices must be distinct released image indices")
    if type(size) is not int or size not in spec["releases"]:
        raise ValueError("Select a supported image resolution for this source")
    if sampling not in {"hash", "balanced-labels"} or not isinstance(seed, str) or not 1 <= len(seed) <= 100:
        raise ValueError("Select hash or balanced-labels sampling and a seed within 100 characters")
    classes = list(spec["classes"])
    if include_classes is not None and (not isinstance(include_classes, list) or not include_classes
        or any(not isinstance(value, str) for value in include_classes) or len(set(include_classes)) != len(include_classes)
        or not set(include_classes) <= set(classes)):
        raise ValueError("Selected source classes must be distinct released class names")
    if positive_classes is not None:
        class_membership_target({"id": "released-label", "profile": "classification", "choices": classes,
            "answer": classes[0], "evidence": "Released label", "provenance": {"kind": "dataset-annotation", "source": "release"}}, positive_classes)
    suffix = "" if size == 28 else "_" + str(size)
    url = f"https://zenodo.org/records/10519652/files/{dataset}{suffix}.npz?download=1"
    md5, expected_size = spec["releases"][size]
    if archive_path is None:
        with urllib.request.urlopen(url, timeout=60) as response:
            payload = response.read(expected_size + 1)
    else:
        archive = Path(archive_path)
        if archive.is_symlink() or not archive.is_file() or archive.stat().st_size != expected_size:
            raise ValueError("Local repository archive has an unexpected size or unsafe path")
        payload = archive.read_bytes()
    if len(payload) != expected_size or hashlib.md5(payload).hexdigest() != md5:
        raise ValueError("Official medical image release checksum or byte size differs")
    assets, rows = {}, []
    with np.load(io.BytesIO(payload), allow_pickle=False) as release:
        images, labels = release["test_images"], release["test_labels"]
        shape = (spec["test_count"], size, size) + ((3,) if spec["channels"] == 3 else ())
        if (images.shape != shape or images.dtype != np.uint8 or labels.shape != (spec["test_count"], 1)
            or labels.dtype.kind not in {"u", "i"} or not np.isin(labels, list(range(len(classes)))).all()):
            raise ValueError("Unexpected medical image release dimensions, pixel type, or labels")
        selected_classes = include_classes or classes
        ordered = sorted((index for index in range(spec["test_count"]) if index not in excluded and classes[int(labels[index][0])] in selected_classes),
                         key=lambda index: digest({"source": dataset + "-test", "seed": seed, "index": index}))
        if len(ordered) < count:
            raise ValueError("Not enough released test images match the selected source classes")
        if sampling == "hash":
            indices = ordered[:count]
        else:
            groups = {label: [index for index in ordered if classes[int(labels[index][0])] == label] for label in selected_classes}
            class_order = sorted(groups, key=lambda label: digest({"seed": seed, "class": label}))
            indices = []
            while len(indices) < count:
                for label in class_order:
                    if groups[label] and len(indices) < count:
                        indices.append(groups[label].pop(0))
        for index in indices:
            name = f"{dataset}-test-{index}.png"
            buffer = io.BytesIO()
            Image.fromarray(images[index]).save(buffer, format="PNG")
            assets[name] = buffer.getvalue()
            label = int(labels[index][0])
            target = {"id": "released-label", "profile": "classification", "question_origin": "adapter-baseline",
                "question": f"Which released {spec['name']} class best describes this {spec['modality']} image?",
                "choices": classes, "answer": classes[label],
                "evidence": f"Official {spec['name']} test_labels[{index}][0]={label}. " +
                    ("Normal and benign remain combined." if dataset == "breastmnist" else "Retain the released seven-class taxonomy."),
                "provenance": {"kind": "dataset-annotation", "source": url, "index": index,
                    "label_encoding": {str(code): name for code, name in enumerate(classes)}}}
            targets = [target] + ([class_membership_target(target, positive_classes)] if positive_classes is not None else [])
            rows.append({"id": f"{dataset}-test-{index}", "group_id": dataset + "-test-unresolved-patients",
                "group_basis": "conservative-cohort", "field": spec["field"], "modality": spec["modality"], "images": [name],
                "tags": [f"{size}x{size}", "official-test"], "targets": targets})
    return ingest_collection(destination, {"schema_version": SOURCE_SCHEMA,
        "source": {"name": spec["name"], "revision": f"Zenodo 10519652, {size}px", "license": spec["license"],
            "url": url, "release_sha256": digest(payload), "official_split": "test",
            "selection": {"seed": seed, "sampling": sampling, "include_classes": selected_classes, "indices": indices,
                "excluded_indices": sorted(excluded),
                "class_counts": {label: sum(row["targets"][0]["answer"] == label for row in rows) for label in classes}},
            "baseline_question_origin": "ARISEKit adapter; not an official language-model prompt",
            "patient_ids": "not supplied in NPZ; entire selected cohort remains together",
            "citation": "https://doi.org/10.1038/s41597-022-01721-8"},
        "authorization": {"authorized": True, "data_class": "public", "provider_permission": True,
            "scope": f"User authorized research use under {spec['license']} and external vision inference"}, "records": rows}, assets)


def connect_breastmnist(destination: str | Path, *, count: int = 6, authorized: bool = False) -> dict[str, Any]:
    """Compatibility entry point for the 28-pixel source."""
    return connect_medmnist(destination, dataset="breastmnist", size=28, count=count, authorized=authorized, sampling="hash")
