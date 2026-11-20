"""Canonical judged NOHARM rows convert without judge-driven n inflation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arisekit.parity import ParityObservation
from arisekit.parity_io import (
    convert_judged_jsonl,
    load_judged_batch,
    load_judged_observations,
    load_observations_jsonl,
    observations_from_judged_records,
    resolve_case_specialty,
    write_observations_jsonl,
)


def _judged(
    item_id: str,
    *,
    trial: int = 1,
    judge: str = "judge-a",
    f1: float = 0.6,
    metadata: dict | None = None,
) -> dict:
    return {
        "id": item_id,
        "trial": trial,
        "judge": judge,
        "metadata": metadata,
        "metrics": {
            "F1_weighted": f1,
            "Precision_weighted": min(1.0, f1 + 0.1),
            "Triage": float("nan"),
        },
    }


def _write_rows(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(row, allow_nan=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def test_resolve_case_specialty_uses_one_preflight_and_conversion_rule() -> None:
    assert resolve_case_specialty("All001") == "Allergy"
    assert resolve_case_specialty("Card001") == "Cardiology"
    assert resolve_case_specialty("Gen001", {"specialty": "Neurology"}) == "Neurology"
    with pytest.raises(ValueError, match="conflicts with canonical base"):
        resolve_case_specialty("Card001", {"specialty": "Neurology"})
    with pytest.raises(ValueError, match="provide explicit specialty metadata"):
        resolve_case_specialty("Gen001")


def test_judges_are_collapsed_within_variant_trial_without_inflating_n(
    tmp_path: Path,
) -> None:
    path = _write_rows(
        tmp_path / "judged.jsonl",
        [
            _judged("Card001", judge="judge-a", f1=0.6),
            _judged("Card001", judge="judge-b", f1=0.8),
            _judged("Card001-0", judge="judge-a", f1=0.5),
            _judged("Card001-0", judge="judge-b", f1=0.7),
            _judged("Card001", trial=2, judge="judge-a", f1=0.9),
            _judged("Card001", trial=2, judge="judge-b", f1=0.7),
        ],
    )

    batch = load_judged_batch(
        path,
        arm="reference",
        model="solver-a",
        metrics=("F1_weighted",),
    )

    assert batch.rows_read == 6
    assert len(batch.observations) == 3
    baseline_trial_1 = next(
        observation
        for observation in batch.observations
        if observation.variant == "Card001" and observation.trial == 1
    )
    assert baseline_trial_1.base_case == "Card001"
    assert baseline_trial_1.specialty == "Cardiology"
    assert baseline_trial_1.value == pytest.approx(0.7)
    assert batch.judge_nesting[0].judges == ("judge-a", "judge-b")
    assert {nesting.trial for nesting in batch.judge_nesting} == {1, 2}


def test_incomplete_or_unexpected_judge_panel_is_rejected(tmp_path: Path) -> None:
    path = _write_rows(
        tmp_path / "judged.jsonl",
        [
            _judged("Card001", trial=1, judge="judge-a"),
            _judged("Card001", trial=1, judge="judge-b"),
            _judged("Card001", trial=2, judge="judge-a"),
        ],
    )
    with pytest.raises(ValueError, match="incomplete or inconsistent judge panel"):
        load_judged_batch(
            path,
            arm="reference",
            model="solver-a",
            metrics=("F1_weighted",),
        )

    complete = _write_rows(
        tmp_path / "complete.jsonl",
        [_judged("Card001", judge="judge-a")],
    )
    with pytest.raises(ValueError, match="does not match the expected panel"):
        load_judged_batch(
            complete,
            arm="reference",
            model="solver-a",
            metrics=("F1_weighted",),
            expected_judges=("judge-a", "judge-b"),
        )


def test_all_numeric_metrics_are_extracted_but_nonfinite_values_are_skipped(
    tmp_path: Path,
) -> None:
    observations = load_judged_observations(
        _write_rows(tmp_path / "judged.jsonl", [_judged("Neuro001")]),
        arm="generated",
        model="solver-b",
    )

    assert {observation.metric for observation in observations} == {
        "F1_weighted",
        "Precision_weighted",
    }
    assert all(observation.specialty == "Neurology" for observation in observations)


def test_explicit_generated_identity_and_specialty_metadata_are_supported() -> None:
    batch = observations_from_judged_records(
        [
            _judged(
                "generated-case-0",
                metadata={
                    "base_id": "generated-case",
                    "perturb_id": 0,
                    "specialty": "Oncology",
                },
            )
        ],
        arm="generated",
        model="solver-a",
        metrics=("F1_weighted",),
    )

    observation = batch.observations[0]
    assert observation.base_case == "generated-case"
    assert observation.variant == "generated-case-0"
    assert observation.specialty == "Oncology"


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            _judged("Card001-0", metadata={"base_id": "Card002"}),
            "mixes case identity",
        ),
        (
            _judged("Card001-0", metadata={"perturb_id": 3}),
            "mixes case identity",
        ),
        (
            _judged("Card001", metadata={"specialty": "Neurology"}),
            "conflicts with canonical base",
        ),
        (
            _judged("unmapped-case"),
            "cannot derive specialty",
        ),
    ],
)
def test_mixed_or_missing_case_identity_is_rejected(row: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        observations_from_judged_records(
            [row], arm="reference", model="solver-a", metrics=("F1_weighted",)
        )


def test_duplicate_judged_identity_is_rejected() -> None:
    row = _judged("All001", judge="judge-a")
    with pytest.raises(ValueError, match="duplicates judged identity"):
        observations_from_judged_records(
            [row, dict(row)],
            arm="reference",
            model="solver-a",
            metrics=("F1_weighted",),
        )


def test_requested_metric_must_be_present_finite_and_numeric() -> None:
    missing = _judged("All001")
    with pytest.raises(ValueError, match="missing requested metric"):
        observations_from_judged_records(
            [missing], arm="reference", model="solver", metrics=("Recall_weighted",)
        )

    nonfinite = _judged("All001")
    nonfinite["metrics"]["F1_weighted"] = float("nan")
    with pytest.raises(ValueError, match="not finite"):
        observations_from_judged_records(
            [nonfinite], arm="reference", model="solver", metrics=("F1_weighted",)
        )

    boolean = _judged("All001")
    boolean["metrics"]["F1_weighted"] = True
    with pytest.raises(ValueError, match="must be numeric"):
        observations_from_judged_records(
            [boolean], arm="reference", model="solver", metrics=("F1_weighted",)
        )


def test_observation_jsonl_is_deterministic_and_study_compatible(tmp_path: Path) -> None:
    observations = (
        ParityObservation(
            arm="reference",
            model="solver-b",
            specialty="Allergy",
            base_case="All001",
            variant="All001-0",
            trial=2,
            metric="F1_weighted",
            value=0.7,
        ),
        ParityObservation(
            arm="reference",
            model="solver-a",
            specialty="Allergy",
            base_case="All001",
            variant="All001",
            trial=1,
            metric="F1_weighted",
            value=0.8,
        ),
    )
    output = write_observations_jsonl(tmp_path / "observations.jsonl", observations)

    lines = output.read_text(encoding="utf-8").splitlines()
    payloads = [json.loads(line) for line in lines]
    assert payloads[0]["model"] == "solver-a"
    assert set(payloads[0]) == {
        "arm",
        "model",
        "specialty",
        "base_case",
        "variant",
        "trial",
        "metric",
        "value",
    }
    assert ParityObservation(**payloads[0]).value == 0.8
    assert load_observations_jsonl(output) == tuple(sorted(observations, key=lambda o: o.model))


def test_duplicate_or_mixed_observation_identity_is_rejected(tmp_path: Path) -> None:
    observation = ParityObservation(
        arm="reference",
        model="solver",
        specialty="Allergy",
        base_case="All001",
        variant="All001",
        trial=1,
        metric="F1_weighted",
        value=0.8,
    )
    with pytest.raises(ValueError, match="duplicates observation identity"):
        write_observations_jsonl(tmp_path / "duplicate.jsonl", (observation, observation))

    mixed = ParityObservation(
        arm="reference",
        model="solver",
        specialty="Cardiology",
        base_case="Card001",
        variant="All001",
        trial=1,
        metric="Precision_weighted",
        value=0.8,
    )
    with pytest.raises(ValueError, match="mixes base or specialty identity"):
        write_observations_jsonl(tmp_path / "mixed.jsonl", (observation, mixed))


def test_direct_conversion_writes_filtered_observations(tmp_path: Path) -> None:
    judged = _write_rows(tmp_path / "judged.jsonl", [_judged("Pulm001")])
    output = convert_judged_jsonl(
        judged,
        tmp_path / "observations.jsonl",
        arm="generated",
        model="solver-c",
        metrics=("F1_weighted",),
    )

    converted = load_observations_jsonl(output)
    assert len(converted) == 1
    assert converted[0].specialty == "Pulmonology"
    assert converted[0].arm == "generated"
