"""Offline measurement checks and blinded review exports for image generation."""

from __future__ import annotations

from collections import Counter
import csv
import json
import math
from pathlib import Path
import random
import re
import secrets
from statistics import fmean
import zipfile

from arisekit.common.hashing import source_sha256
from arisekit.images.image_generation import _candidate, _comparison, _frozen_plan, _generated_text, _json_response, _records, _runtime_hash
from arisekit.images.imaging import digest, normalized, verify_collection, write_private
from arisekit.types import BenchmarkItem
from arisekit.images.image_metrics import analysis_options, kendall_tau_b, paired_score_diagnostics
from arisekit import __version__


def _quantile(values, fraction):
    values = sorted(values)
    index = (len(values) - 1) * fraction
    lower = int(index)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (index - lower)


def _interval(values, requested, unit):
    defined = [value for value in values if value is not None]
    return {"unit": unit, "requested": requested, "defined": len(defined), "undefined": requested - len(defined),
            "percentile_95": [_quantile(defined, .025), _quantile(defined, .975)] if defined else None,
            "one_sided_95_lower": _quantile(defined, .05) if defined else None,
            "method": "percentiles of defined draws; undefined tied draws reported separately"}


def _calibration_and_forms(items, rows):
    errors = [row['generated']['accuracy'] - row['original']['accuracy'] for row in rows]
    styles = sorted({item.metadata.get('question_style', 'single') for item in items})
    per_model = []
    for row in rows:
        forms = {}
        for style in styles:
            selected = [i for i, item in enumerate(items) if item.metadata.get('question_style', 'single') == style]
            forms[style] = {arm: fmean(row['scores'][arm][i]['correct'] for i in selected) for arm in ('original', 'generated')}
        repeats = {}
        for arm in ('original', 'generated'):
            groups = {}
            for item, score in zip(items, row['scores'][arm]):
                groups.setdefault((item.metadata['source_id'], item.metadata['target_id']), []).append(score)
            pairs = [(a, b) for values in groups.values() for index, a in enumerate(values) for b in values[:index]]
            valid = [(a, b) for a, b in pairs if a['valid'] and b['valid']]
            repeats[arm] = {'assigned_pairs': len(pairs), 'valid_pairs': len(valid),
                'prediction_changes': sum(a['answer'] != b['answer'] for a, b in valid),
                'score_range_across_forms': max(form[arm] for form in forms.values()) - min(form[arm] for form in forms.values())}
        per_model.append({'model': row['model'], 'forms': forms, 'within_image_repeats': repeats})
    stable = []
    complete = all(not row[arm]['missing'] for row in rows for arm in ('original', 'generated'))
    if len(styles) >= 2 and complete:
        for index, left in enumerate(per_model):
            for right in per_model[:index]:
                source_deltas = [left['forms'][style]['original'] - right['forms'][style]['original'] for style in styles]
                direction = 1 if all(value > 0 for value in source_deltas) else -1 if all(value < 0 for value in source_deltas) else 0
                if not direction:
                    continue
                generated_deltas = [left['forms'][style]['generated'] - right['forms'][style]['generated'] for style in styles]
                a, b = rows[index]['generated'], next(row['generated'] for row in rows if row['model'] == right['model'])
                mean_delta = a['correct'] * b['assigned'] - b['correct'] * a['assigned']
                outcome = 'preserved' if mean_delta * direction > 0 else 'reversed' if mean_delta * direction < 0 else 'collapsed'
                stable.append({'left': left['model'], 'right': right['model'], 'original_deltas': source_deltas,
                    'generated_deltas': generated_deltas, 'mean_outcome': outcome,
                    'all_generated_forms_preserve': all(value * direction > 0 for value in generated_deltas)})
    return {'mean_absolute_score_error': fmean(abs(value) for value in errors),
        'maximum_absolute_score_error': max(abs(value) for value in errors),
        'root_mean_squared_score_error': math.sqrt(fmean(value * value for value in errors)),
        'unique_source_tasks': len({(item.metadata['source_id'], item.metadata['target_id']) for item in items}),
        'forms': styles, 'repeatability_status': 'not-estimable-incomplete' if not complete else 'descriptive-repeated-forms' if len(styles) >= 2 else 'not-estimable-single-form',
        'models': per_model, 'stable_original_comparisons': stable,
        'stable_comparison_outcomes': dict(Counter(pair['mean_outcome'] for pair in stable)),
        'stable_original_definition': 'Same strict score ordering in every original-form repeat; descriptive of these repeats only.'}


def contract_diagnostics(question, contract):
    """Check declared vocabulary and simple form rules, without judging clinical meaning."""
    text = normalized(question)
    missing = [term for term in contract['task_contract']['required_terms']
               if not re.search(r'(?<!\w)' + re.escape(normalized(term)) + r'(?!\w)', text)]
    start = contract['starts_with']
    return {'missing_required_terms': missing,
        'start_rule_satisfied': not start or bool(re.match(re.escape(start.casefold()) + r'\b', question.casefold().strip())),
        'question_mark_rule_satisfied': not contract['ends_with_question_mark'] or question.rstrip().endswith('?')}


def _contract_report(plan, completed):
    contracts = plan.get('public_task_contracts')
    if not contracts:
        return {'status': 'not-frozen-in-plan' if plan['brief'].get('question_styles') else 'not-declared', 'checked': 0}
    rows = []
    for identifier, contract in contracts.items():
        question = _json_response(_generated_text(plan, completed, identifier))['question']
        checks = contract_diagnostics(question, contract)
        rows.append({'id': identifier, **checks, 'structural_conflict': bool(checks['missing_required_terms']) or
            not checks['start_rule_satisfied'] or not checks['question_mark_rule_satisfied'],
            'ai_criteria_aligned': _json_response(completed['review:' + identifier]['response'])['criteria_aligned']
                if 'review:' + identifier in completed else None})
    return {'status': 'checked-frozen-contracts', 'checked': len(rows),
        'structural_conflicts': sum(row['structural_conflict'] for row in rows),
        'missing_term_counts': dict(Counter(term for row in rows for term in row['missing_required_terms'])),
        'start_rule_failures': sum(not row['start_rule_satisfied'] for row in rows),
        'question_mark_failures': sum(not row['question_mark_rule_satisfied'] for row in rows),
        'ai_aligned_despite_structural_conflict': sum(row['structural_conflict'] and row['ai_criteria_aligned'] is True for row in rows),
        'per_task': rows, 'scope': 'Declared vocabulary and simple form checks; no clinical validity judgment or item exclusion.'}


def generation_report(root: str | Path, *, bootstrap=2000, seed="image-generation-validation-v1", analysis=None):
    if type(bootstrap) is not int or not 1 <= bootstrap <= 100000:
        raise ValueError("Choose 1–100000 bootstrap replicates")
    options = analysis_options(analysis)
    root = Path(root)
    plan, records = _frozen_plan(root), _records(root)
    if any("generate:" + item["id"] not in records["completed"] for item in plan["originals"]):
        raise ValueError("Retain every assigned generated question before comparing the benchmark")
    comparison = _comparison(plan, records["completed"])
    items = [BenchmarkItem.from_dict(row) for row in plan["originals"]]
    results = {}
    for profile in plan["brief"]["profiles"]:
        subset = [item for item in items if item.metadata["profile"] == profile]
        rows = []
        for model in comparison["models"]:
            arms = {arm: [row for row in model[arm]["scores"] if row["profile"] == profile]
                    for arm in ("original", "generated")}
            original, generated = arms["original"], arms["generated"]
            changed = [a["answer"] != b["answer"] for a, b in zip(original, generated) if a["valid"] and b["valid"]]
            rows.append({"model": model["model"], **{arm: {
                "assigned": len(values), "correct": sum(row["correct"] for row in values),
                "accuracy": fmean(row["correct"] for row in values),
                "invalid": sum(not row["valid"] and not row["missing"] for row in values),
                "missing": sum(row["missing"] for row in values), "errors": sum(bool(row["error"]) for row in values)}
                for arm, values in arms.items()},
                "paired_valid": len(changed), "prediction_changes": sum(changed),
                "paired_correctness": dict(Counter(f"{a['correct']}->{b['correct']}" for a, b in zip(original, generated))),
                "scores": arms})
        complete = all(not row[arm]["missing"] for row in rows for arm in ("original", "generated"))
        enough = len(rows) >= 2 and complete
        x, y = [[row[arm]["accuracy"] for row in rows] for arm in ("original", "generated")]
        concordance = kendall_tau_b(x, y) if enough else None
        rng = random.Random(seed + ":" + profile)
        model_draws = []
        if enough:
            for _ in range(bootstrap):
                sample = [rng.randrange(len(rows)) for _ in rows]
                model_draws.append(kendall_tau_b([x[i] for i in sample], [y[i] for i in sample])["tau_b"])
        groups = [[i for i, item in enumerate(subset) if item.metadata["source_id"] in group]
                  for group in plan["split"]["groups"]]
        groups = [group for group in groups if group]
        item_draws = []
        if enough and len(groups) >= 2:
            for _ in range(bootstrap):
                sample = [index for _ in groups for index in groups[rng.randrange(len(groups))]]
                a, b = [[fmean(row["scores"][arm][i]["correct"] for i in sample) for row in rows]
                        for arm in ("original", "generated")]
                item_draws.append(kendall_tau_b(a, b)["tau_b"])
        mean_x, mean_y = fmean(x), fmean(y)
        variance_x, variance_y = fmean((v - mean_x) ** 2 for v in x), fmean((v - mean_y) ** 2 for v in y)
        covariance = fmean((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
        denominator = variance_x + variance_y + (mean_x - mean_y) ** 2
        reference_counts = Counter(normalized(str(item.ground_truth)) for item in subset)
        longest = sum(normalized(str(item.ground_truth)) == normalized(max(item.metadata["choices"], key=lambda v: (len(v), v))) for item in subset)
        results[profile] = {
            "models": [{key: value for key, value in row.items() if key != "scores"} for row in rows],
            "ranking_status": "incomplete-model-data" if not complete else "fewer-than-two-models" if not enough else
                              "undefined-all-tied-arm" if concordance["tau_b"] is None else "exploratory-estimate",
            "concordance": concordance,
            "model_bootstrap": _interval(model_draws, bootstrap if enough else 0, "model roster with replacement"),
            "group_bootstrap": _interval(item_draws, bootstrap if enough and len(groups) >= 2 else 0, "connected source groups with replacement"),
            "source_groups": len(groups),
            "group_interval_status": "estimated" if len(groups) >= 2 and enough else "not-estimable",
            "group_interval_reason": None if len(groups) >= 2 else "Fewer than two independent supplied groups; no item-independence assumption substituted.",
            "paired_score_diagnostics": paired_score_diagnostics(x, y, settings=options) if enough else None,
            "lin_ccc": 2 * covariance / denominator if enough and denominator else None,
            "mean_score_difference": mean_y - mean_x,
            "calibration": _calibration_and_forms(subset, rows),
            "source_reference_baselines": {"uniform_random_expected": fmean(1 / len(item.metadata["choices"]) for item in subset),
                "majority_class_accuracy": max(reference_counts.values()) / len(subset),
                "longest_label_accuracy": longest / len(subset), "reference_counts": dict(reference_counts)},
        }
    return {"schema_version": "arisekit.image-generation-validation.v1", "arisekit_version": __version__, "plan_sha256": digest(plan),
            "generator_policy_sha256": plan['brief'].get('generator_policy_sha256'),
            "generation_runtime_sha256": plan['runtime_sha256'], "analysis_runtime_matches_generation": plan['runtime_sha256'] == _runtime_hash(),
            "evaluation_role": plan['brief'].get('evaluation_role', 'unspecified'),
            "analysis_sha256": digest(source_sha256(("images/image_validation.py", "images/image_metrics.py"), Path(__file__).parents[1])),
            "analysis_settings": options, "analysis_settings_sha256": digest(options),
            "analysis_role": "exploratory diagnostics; generator selection objective unchanged", "seed": seed, "bootstrap_replicates": bootstrap,
            "claim_status": "exploratory; independent expert validation pending", "expert_ratings_completed": 0,
            "task_scope": "New question wording over the same images and unchanged source labels; not novel case or reference generation.",
            "original_prompt_origin": "Source-supplied or ARISEKit adapter questions, not necessarily official language-model benchmark prompts.",
            "profiles": results, "image_controls": {row["model"]: {arm: row[arm]["image_controls"]
                for arm in ("original", "generated")} for row in comparison["models"]},
            "originality": comparison["originality"], "ai_review": comparison["ai_review"],
            "copy_repair": comparison['copy_repair'],
            'declared_contract_checks': _contract_report(plan, records['completed']),
            "bootstrap_policy": "Model intervals condition on the observed items and roster. Group intervals preserve supplied dependence. Neither establishes population equivalence or a clinical claim."}


def export_review_packet(root: str | Path, destination: str | Path):
    root, destination = Path(root), Path(destination)
    plan, records = _frozen_plan(root), _records(root)
    if destination.exists():
        raise ValueError("Review export already exists; retain its mapping and ratings")
    originals = [BenchmarkItem.from_dict(row) for row in plan["originals"]]
    generated = [_candidate(item, _generated_text(plan, records['completed'], item.id)) for item in originals]
    public, private = destination / "reviewer", destination / "private"
    public.mkdir(parents=True, mode=0o700)
    private.mkdir(mode=0o700)
    nonce = secrets.token_hex(32)
    entries = []
    for arm, items in (("original", originals), ("generated", generated)):
        for item in items:
            token = digest({"nonce": nonce, "arm": arm, "id": item.id})[:20]
            image_paths = []
            for index, image in enumerate(item.attachments):
                name = f"images/{token}-{index}{Path(image).suffix}"
                path = public / name
                path.parent.mkdir(exist_ok=True)
                path.write_bytes((root / "source" / image).read_bytes())
                path.chmod(0o600)
                image_paths.append(name)
            question = str(item.prompt).rsplit("\nAnswer with exactly one label from: ", 1)[0]
            entries.append({"review_item_id": token, "question": question, "choices": json.dumps(item.metadata["choices"]),
                "image_paths": ";".join(image_paths), "expert_answer": "", "ambiguous": "", "unsupported_findings": "",
                "answer_format_clear": "", "provenance_guess": "", "notes": "", "arm": arm,
                "source_item_id": item.id, "source_reference": item.ground_truth})
    entries.sort(key=lambda row: row["review_item_id"])
    fields = [key for key in entries[0] if key not in {"arm", "source_item_id", "source_reference"}]
    with (public / "ratings.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({key: "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r"))
                          else value for key, value in row.items()} for row in entries)
    (public / "ratings.csv").chmod(0o600)
    (public / "README.txt").write_text(
        "Review each question and its image independently. Enter an answer from the choices or state unable to determine.\n"
        "For ambiguous, unsupported_findings and answer_format_clear, enter yes, no or unsure.\n"
        "For provenance_guess, enter original, generated or unsure. Preserve item IDs and record your reviewer ID separately.\n"
        "Keep independent ratings separate before adjudication. Do not consult the private mapping until ratings are sealed.\n"
        "Original questions can be adapter baselines over released dataset labels. Both arms reuse the same source images.\n"
        "Formatting is normalized; wording and recognizable public images may still reveal provenance. The guess field checks blinding.\n")
    source = verify_collection(root / "source")["source"]
    (public / "SOURCE.txt").write_text("\n".join(f"{key}: {source[key]}" for key in
        ("name", "revision", "license", "url", "citation") if key in source) + "\n")
    files = {path.relative_to(public).as_posix(): digest(path.read_bytes()) for path in public.rglob("*") if path.is_file()}
    write_private(public / "manifest.json", {"schema_version": "arisekit.image-item-review.v1", "items": len(entries), "files": files})
    write_private(private / "mapping.json", {"plan_sha256": digest(plan), "nonce": nonce, "items": entries})
    with zipfile.ZipFile(destination / "reviewer-packet.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(public.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(public))
    return {"items": len(entries), "archive": str(destination / "reviewer-packet.zip"),
            "expert_ratings_completed": 0, "private_mapping": str(private / "mapping.json")}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--analysis-config", type=Path, help="JSON diagnostic settings; see medical-image-analysis.md")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a fresh evidence directory")
    report = generation_report(args.run, bootstrap=args.bootstrap,
                               analysis=json.loads(args.analysis_config.read_text()) if args.analysis_config else None)
    packet = export_review_packet(args.run, args.output / "review")
    write_private(args.output / "validation.json", report)
    print(json.dumps({"report": str(args.output / "validation.json"), **packet}))


if __name__ == "__main__":
    main()
