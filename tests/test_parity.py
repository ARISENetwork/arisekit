import pytest

from arisekit.parity import ParityObservation, aggregate_case_estimates, compare_parity


def _observation(
    *,
    arm: str,
    model: str,
    specialty: str,
    base: str,
    variant: str,
    trial: int,
    value: float,
) -> ParityObservation:
    return ParityObservation(
        arm=arm,
        model=model,
        specialty=specialty,
        base_case=base,
        variant=variant,
        trial=trial,
        metric="f1_weighted",
        value=value,
    )


def test_aggregate_trials_within_variants_then_variants_within_base():
    observations = [
        _observation(
            arm="reference", model="m1", specialty="card", base="c1",
            variant="base", trial=1, value=0.2,
        ),
        _observation(
            arm="reference", model="m1", specialty="card", base="c1",
            variant="base", trial=2, value=0.4,
        ),
        _observation(
            arm="reference", model="m1", specialty="card", base="c1",
            variant="p1", trial=1, value=0.8,
        ),
    ]

    estimates = aggregate_case_estimates(observations, metric="f1_weighted")

    assert len(estimates) == 1
    assert estimates[0].value == pytest.approx(0.55)
    assert estimates[0].variants == 2
    assert estimates[0].observations == 3


def test_compare_parity_passes_constant_level_shift_with_preserved_profile():
    observations: list[ParityObservation] = []
    for specialty_index, specialty in enumerate(("card", "neuro")):
        for case_index in range(3):
            for model_index, model in enumerate(("m1", "m2", "m3", "m4")):
                reference = 0.45 + 0.08 * model_index + 0.01 * specialty_index
                for arm, shift in (("reference", 0.0), ("generated", 0.02)):
                    for variant_index in range(2):
                        for trial in (1, 2):
                            observations.append(
                                _observation(
                                    arm=arm,
                                    model=model,
                                    specialty=specialty,
                                    base=f"{specialty}-{case_index}",
                                    variant=f"v{variant_index}",
                                    trial=trial,
                                    value=reference + shift,
                                )
                            )

    report = compare_parity(
        observations,
        metric="f1_weighted",
        reference_arm="reference",
        generated_arm="generated",
        bootstrap_draws=300,
        seed=4,
    )

    assert report.level.estimate == pytest.approx(0.02)
    assert report.profile_rmse.estimate == pytest.approx(0.0, abs=1e-12)
    assert report.passed is True
    assert set(report.scores["reference"]) == {"m1", "m2", "m3", "m4"}


def test_compare_parity_detects_changed_relative_discrimination():
    observations: list[ParityObservation] = []
    reference_values = {"m1": 0.3, "m2": 0.5, "m3": 0.7, "m4": 0.9}
    generated_values = {"m1": 0.9, "m2": 0.7, "m3": 0.5, "m4": 0.3}
    for arm, values in (("reference", reference_values), ("generated", generated_values)):
        for model, value in values.items():
            for case_index in range(4):
                observations.append(
                    _observation(
                        arm=arm,
                        model=model,
                        specialty="allergy",
                        base=f"a{case_index}",
                        variant="base",
                        trial=1,
                        value=value,
                    )
                )

    report = compare_parity(
        observations,
        metric="f1_weighted",
        reference_arm="reference",
        generated_arm="generated",
        bootstrap_draws=100,
    )

    assert report.level.passed is True
    assert report.profile_rmse.passed is False
    assert report.passed is False


def test_compare_parity_rejects_incomplete_model_by_base_matrix():
    observations = [
        _observation(
            arm="reference", model="m1", specialty="card", base="c1",
            variant="base", trial=1, value=0.5,
        ),
        _observation(
            arm="reference", model="m2", specialty="card", base="c1",
            variant="base", trial=1, value=0.6,
        ),
        _observation(
            arm="reference", model="m1", specialty="card", base="c2",
            variant="base", trial=1, value=0.5,
        ),
        _observation(
            arm="generated", model="m1", specialty="card", base="g1",
            variant="base", trial=1, value=0.5,
        ),
        _observation(
            arm="generated", model="m2", specialty="card", base="g1",
            variant="base", trial=1, value=0.6,
        ),
    ]

    with pytest.raises(ValueError, match="incomplete model-by-base matrix"):
        compare_parity(
            observations,
            metric="f1_weighted",
            reference_arm="reference",
            generated_arm="generated",
            bootstrap_draws=0,
        )


def test_parity_rejects_duplicate_trials_and_unequal_arm_coverage():
    duplicate = _observation(
        arm="reference",
        model="m1",
        specialty="card",
        base="c1",
        variant="base",
        trial=1,
        value=0.5,
    )
    with pytest.raises(ValueError, match="duplicate parity observation"):
        aggregate_case_estimates([duplicate, duplicate], metric="f1_weighted")

    observations: list[ParityObservation] = []
    for arm, variants in (("reference", ("base", "p1")), ("generated", ("base",))):
        for model in ("m1", "m2", "m3"):
            for variant in variants:
                observations.append(
                    _observation(
                        arm=arm,
                        model=model,
                        specialty="card",
                        base=f"{arm}-c1",
                        variant=variant,
                        trial=1,
                        value=0.5,
                    )
                )
    with pytest.raises(ValueError, match="same variant and trial coverage"):
        compare_parity(
            observations,
            metric="f1_weighted",
            reference_arm="reference",
            generated_arm="generated",
            bootstrap_draws=0,
        )

    noncontiguous = [
        _observation(
            arm="reference",
            model="m1",
            specialty="card",
            base="c1",
            variant="base",
            trial=trial,
            value=0.5,
        )
        for trial in (1, 3)
    ]
    with pytest.raises(ValueError, match="contiguous trials"):
        aggregate_case_estimates(noncontiguous, metric="f1_weighted")


@pytest.mark.parametrize(
    ("trial", "value", "message"),
    [(True, 0.5, "positive integer"), (1, True, "finite")],
)
def test_parity_observation_rejects_boolean_numeric_fields(trial, value, message):
    observation = _observation(
        arm="reference",
        model="m1",
        specialty="card",
        base="c1",
        variant="base",
        trial=trial,
        value=value,
    )
    with pytest.raises(ValueError, match=message):
        observation.validate()


def test_parity_rejects_unmatched_specialty_strata():
    observations = []
    for arm, specialty in (("reference", "card"), ("generated", "neuro")):
        for model in ("m1", "m2", "m3"):
            observations.append(
                _observation(
                    arm=arm,
                    model=model,
                    specialty=specialty,
                    base=f"{arm}-c1",
                    variant="base",
                    trial=1,
                    value=0.5,
                )
            )
    with pytest.raises(ValueError, match="same specialty strata"):
        compare_parity(
            observations,
            metric="f1_weighted",
            reference_arm="reference",
            generated_arm="generated",
            bootstrap_draws=0,
        )


def test_parity_rejects_equal_counts_with_disjoint_variant_sets_by_model():
    observations = []
    for arm, base in (("reference", "Ref001"), ("generated", "Gen001")):
        for model, suffixes in (("model-a", (0, 1)), ("model-b", (8, 9))):
            for suffix in suffixes:
                observations.append(
                    ParityObservation(
                        arm=arm,
                        model=model,
                        specialty="Cardiology",
                        base_case=base,
                        variant=f"{base}-{suffix}",
                        trial=1,
                        metric="score",
                        value=0.5,
                    )
                )

    with pytest.raises(ValueError, match="inconsistent exact variant/trial coverage"):
        compare_parity(
            observations,
            metric="score",
            reference_arm="reference",
            generated_arm="generated",
            bootstrap_draws=0,
        )
