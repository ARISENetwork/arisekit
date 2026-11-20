"""Prospective image-input controls, kept separate from benchmark accuracy."""

from arisekit.images.imaging import ImageAnswerScorer, digest, normalized
from arisekit.types import RunResult

IMAGE_CONTROLS = ("question-only", "contrasting-image")


def freeze_image_controls(items, source, conditions, seed):
    assets = source["assets"]

    def pixels(item):
        return {assets[name]["pixel_sha256"] for name in item.attachments}

    def task(item):
        return (item.metadata["profile"], item.metadata["target_id"], normalized(str(item.prompt)),
                normalized(item.metadata["field"]), normalized(item.metadata["modality"]))

    bindings = {}
    for condition in conditions:
        rows = {}
        for item in items:
            donor = None
            if condition == "contrasting-image":
                candidates = [other for other in items if task(other) == task(item)
                    and normalized(str(other.ground_truth)) != normalized(str(item.ground_truth))
                    and len(other.attachments) == len(item.attachments) and pixels(item).isdisjoint(pixels(other))]
                if candidates:
                    donor = min(candidates, key=lambda other: digest({"seed": seed, "item": item.id, "donor": other.id}))
            available = condition == "question-only" or donor is not None
            images = donor.attachments if donor is not None else []
            rows[item.id] = {"available": available, "image_refs": images,
                "image_sha256": [assets[name]["sha256"] for name in images],
                "donor_id": donor.id if donor is not None else None,
                "donor_reference": donor.ground_truth if donor is not None else None,
                "unavailable_reason": None if available else
                    "No selected task with the same source question, target, field, modality and image count has a different reference and distinct pixels."}
        bindings[condition] = rows
    return bindings


def image_control_summary(bindings):
    return {condition: {"expected": len(rows), "assigned": sum(row["available"] for row in rows.values()),
                        "unavailable": sum(not row["available"] for row in rows.values())}
            for condition, rows in bindings.items()}


def compare_image_controls(items, primary, bindings, completed, model_index, arm):
    scorer = ImageAnswerScorer()
    matched = {row["id"]: row for row in primary}
    controls = {}
    for condition, assignments in bindings.items():
        rows = []
        for item in items:
            binding, baseline = assignments[item.id], matched[item.id]
            if not binding["available"]:
                rows.append({"id": item.id, "profile": item.metadata["profile"], "available": False,
                             "unavailable_reason": binding["unavailable_reason"]})
                continue
            response = completed.get(f"control:{model_index}:{arm}:{condition}:{item.id}")
            result = RunResult(item.id, 1, response.get("response") if response else None,
                               error=response.get("error") if response else "missing output")
            score = scorer.score_response(item, result)
            answer = normalized(str(result.response)) if score["valid"] else None
            paired = bool(score["valid"] and baseline["valid"])
            rows.append({"id": item.id, "profile": item.metadata["profile"], "available": True, **score,
                "answer": answer, "matched_reference_match": baseline["correct"], "paired_valid": paired,
                "prediction_changed": answer != baseline["answer"] if paired else None,
                "donor_id": binding["donor_id"], "donor_reference": binding["donor_reference"],
                "donor_reference_match": bool(score["valid"] and answer == normalized(str(binding["donor_reference"])))
                    if binding["donor_id"] is not None else None})

        def summary(values):
            assigned = [row for row in values if row["available"]]
            return {"expected": len(values), "assigned": len(assigned), "unavailable": len(values) - len(assigned),
                "valid": sum(row["valid"] for row in assigned), "missing": sum(row["missing"] for row in assigned),
                "invalid": sum(not row["valid"] and not row["missing"] for row in assigned),
                "errors": sum(bool(row["error"]) for row in assigned),
                "matched_reference_matches": sum(row["matched_reference_match"] for row in assigned),
                "original_reference_matches": sum(row["correct"] for row in assigned),
                "paired_valid": sum(row["paired_valid"] for row in assigned),
                "prediction_changed": sum(row["prediction_changed"] is True for row in assigned),
                "donor_reference_matches": sum(row["donor_reference_match"] is True for row in assigned)}

        controls[condition] = {**summary(rows), "profiles": {profile: summary([row for row in rows if row["profile"] == profile])
            for profile in sorted({item.metadata["profile"] for item in items})}, "rows": rows,
            "reference_policy": "Agreement with the original source reference is measured separately from normal accuracy. Contrasting-image donor references remain separate; prediction changes are descriptive."}
    return controls
